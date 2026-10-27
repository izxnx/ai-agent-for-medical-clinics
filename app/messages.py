"""Тексти сповіщень для адміністраторів (Telegram, parse_mode=HTML). Без залежностей - легко тестувати."""
from html import escape
import json
import re
from zoneinfo import ZoneInfo

from . import transcripts

KYIV = ZoneInfo("Europe/Kyiv")


def _e(value) -> str:
    return escape(str(value)) if value else "не вказано"


def _truncate_message(text: str, limit: int = 4096) -> str:
    if len(text) <= limit:
        return text
    tokens = re.findall(r"<[^>]*>|&(?:amp|lt|gt|quot|#x27);|.", text, re.S)
    output = []
    stack = []
    visible = raw = 0
    for token in tokens:
        next_stack = list(stack)
        if token.startswith("<"):
            if token.startswith("</"):
                tag = token[2:-1]
                if tag in next_stack:
                    next_stack.remove(tag)
            else:
                tag = token[1:-1].split()[0].rstrip("/")
                if tag in {"b", "i", "u", "s", "code", "pre", "blockquote"}:
                    next_stack.append(tag)
        decoded_width = 0 if token.startswith("<") else 1
        closers = sum(len(f"</{tag}>") for tag in next_stack)
        if visible + decoded_width > limit or raw + len(token) + closers > limit:
            break
        output.append(token)
        raw += len(token)
        visible += decoded_width
        stack = next_stack
    output.extend(f"</{tag}>" for tag in reversed(stack))
    return "".join(output)


def _when(r) -> str:
    return r["created_at"].astimezone(KYIV).strftime("%d.%m %H:%M")


def format_booking(r) -> str:
    when = " ".join(x for x in (r["preferred_date"], r["preferred_time"]) if x)
    head = f"🆕 <b>Нова заявка #{r['id']}</b>"
    lines = [
        head,
        "",
        f"👤 {_e(r['patient_name'])}",
        f"📞 {_e(r['patient_phone'])}",
        f"🩺 {_e(r['service_or_specialty'])}",
        f"📍 {_e(r['city_or_branch'])}",
        f"🕒 Бажано: {_e(when)}",
    ]
    if r["symptoms_summary"]:
        lines.append(f"📝 Скарги: {_e(r['symptoms_summary'])}")
    lines.append(f"\n<i>Дзвінок: {_when(r)}</i>")
    text = "\n".join(lines)
    return _truncate_message(text, 4096)


REPORT_LIMIT = 4096
_NOT_SAID = "не назвав"


def _analysis(r) -> dict:
    value = r["analysis"]
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = None
    return value if isinstance(value, dict) else {}


def _v(value, missing: str = "не вказано") -> str:
    return escape(str(value)) if value else missing


def _report_fields(r, bookings) -> dict:
    """Дані для звіту: із заявки (підтверджені пацієнтом), інакше з аналізу Retell."""
    a = _analysis(r)
    if bookings:
        b = bookings[-1]
        when = " ".join(
            x for x in (b["preferred_date"], b["preferred_time"]) if x and x.casefold() != "не вказано"
        )
        return {
            "name": b["patient_name"], "phone": b["patient_phone"] or r["caller_phone"],
            "service": b["service_or_specialty"], "city": b["city_or_branch"],
            "when": when, "complaint": b["symptoms_summary"],
        }
    return {
        "name": a.get("patient_name"), "phone": a.get("patient_phone") or r["caller_phone"],
        "service": a.get("service"), "city": a.get("city"),
        "when": a.get("preferred_time"), "complaint": a.get("complaint"),
    }


def _dialog(transcript: str | None, budget: int) -> str:
    """Діалог обома сторонами; budget рахується по довжині HTML, як ліміт Telegram."""
    lines, used = [], 0
    for is_user, text in transcripts.turns(transcript):
        who = "Пацієнт" if is_user else "Олена"
        line = f"<b>{who}:</b> {escape(text)}"
        if used + len(line) + 1 > budget:
            room = budget - used - len(who) - 12
            if room > 40:
                lines.append(f"<b>{who}:</b> {escape(text[: room // 2])}…")
            else:
                lines.append("…")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def format_report(r, bookings=()) -> str:
    """Звіт після дзвінка: підсумок, ключові поля, згорнутий діалог (варіант D)."""
    a = _analysis(r)
    f = _report_fields(r, bookings)
    if bookings:
        head = "🆕 <b>Заявка " + ", ".join(f"#{b['id']}" for b in bookings) + "</b>"
    else:
        head = "📞 <b>Дзвінок без заявки</b>"

    lines = [head, ""]
    summary = a.get("summary_uk") or r["call_summary"]
    if summary:
        lines += [f"📋 {escape(summary)}", ""]
    if bookings or a:
        lines.append(f"👤 {_v(f['name'], _NOT_SAID)} · 📞 {_v(f['phone'], _NOT_SAID)}")
        lines.append(f"🩺 {_v(f['service'])} · 📍 {_v(f['city'])} · 🕒 {_v(f['when'])}")
        if f["complaint"]:
            lines.append(f"📝 {escape(f['complaint'])}")
    else:
        lines.append("<i>Аналіз розмови від Retell не надійшов, деталі в діалозі нижче.</i>")
    lines.append(f"\n<i>Дзвінок: {_when(r)}</i>")
    text = "\n".join(lines)

    quote_open, quote_close = "\n<blockquote expandable>💬 <b>Розмова</b>\n", "</blockquote>"
    dialog = _dialog(r["transcript"], REPORT_LIMIT - len(text) - len(quote_open) - len(quote_close) - 50)
    if dialog:
        text += quote_open + dialog + quote_close
    return _truncate_message(text, REPORT_LIMIT)


def recording_caption(r) -> str:
    """Підпис до запису розмови (ліміт Telegram - 1024 символи)."""
    ids = r["booking_ids"]
    what = "Заявка " + ", ".join(f"#{i}" for i in ids) if ids else "Дзвінок без заявки"
    head = "🎙 <b>Запис розмови</b>"
    text = f"{head}\n{what}\n📞 {_e(r['caller_phone'])}\n<i>Дзвінок: {_when(r)}</i>"
    return _truncate_message(text, 1024)
