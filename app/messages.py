"""Тексти сповіщень для адміністраторів (Telegram, parse_mode=HTML). Без залежностей - легко тестувати."""
from html import escape
import re
from zoneinfo import ZoneInfo

from . import urgency

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
                if tag in {"b", "i", "u", "s", "code", "pre"}:
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
    if r["is_urgent"]:
        head = f"🚨 <b>ВАЖЛИВЕ</b> - заявка #{r['id']}\nПередзвонити першими!"
    else:
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
    if r["is_urgent"]:
        lines.append(f"⚠️ Причина: {_e(r['urgent_reason'])}")
    lines.append(f"\n<i>Дзвінок: {_when(r)}</i>")
    text = "\n".join(lines)
    return _truncate_message(text, 4096)


def format_call(r) -> str:
    """Дзвінок, після якого немає заявки (пацієнт кинув слухавку, збій tool тощо)."""
    if r["is_urgent"]:
        head = "🚨 <b>ВАЖЛИВЕ</b> - дзвінок БЕЗ заявки\nПередзвонити першими!"
    else:
        head = "📞 <b>Дзвінок без заявки</b>"
    snippet = urgency.user_part(r["transcript"])[:300]
    lines = [head, "", f"📞 Номер: {_e(r['caller_phone'])}"]
    if r["is_urgent"]:
        lines.append(f"⚠️ Причина: {_e(r['urgent_reason'])}")
    if snippet:
        lines.append(f"💬 Пацієнт казав: {_e(snippet)}")
    lines.append(f"\n<i>Дзвінок: {_when(r)}</i>")
    return _truncate_message("\n".join(lines), 4096)


def recording_caption(r) -> str:
    """Підпис до запису розмови (ліміт Telegram - 1024 символи)."""
    urgent = r["is_urgent"] or r["booking_urgent"]
    ids = r["booking_ids"]
    what = "Заявка " + ", ".join(f"#{i}" for i in ids) if ids else "Дзвінок без заявки"
    head = "🚨 <b>ВАЖЛИВЕ</b> · 🎙 Запис розмови" if urgent else "🎙 <b>Запис розмови</b>"
    text = f"{head}\n{what}\n📞 {_e(r['caller_phone'])}\n<i>Дзвінок: {_when(r)}</i>"
    return _truncate_message(text, 1024)
