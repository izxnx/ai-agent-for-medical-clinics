import asyncio
import hmac
import json
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import ValidationError

from . import db, notifier, telegram, urgency
from .config import settings
from .schemas import BookingRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx на INFO пише URL, а в ньому токен бота
log = logging.getLogger("webhook")  # у логах лише id, без імен/телефонів/скарг

MIN_USER_CHARS = 40  # дзвінок без заявки, де пацієнт сказав менше, вважаємо випадковим


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_for_startup()
    app.state.pool = await db.create_pool(settings.database_url)
    await db.run_migrations(app.state.pool)
    worker = None
    if telegram.configured():
        worker = asyncio.create_task(notifier.retry_loop(app.state.pool))
    else:
        log.warning("Telegram не налаштовано: сповіщення вимкнені, заявки лишаються в БД")
    yield
    if worker:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
    await app.state.pool.close()


app = FastAPI(lifespan=lifespan)


# --- Tools -------------------------------------------------------------------
async def submit_booking_request(pool, args: dict, call: dict, tool_call_id: str) -> str:
    """Рядок, який повертаємо, агент озвучить пацієнту."""
    call_id = call.get("id", "")
    args = dict(args)
    # TODO(verify-vapi): підтвердити шлях call.customer.number для робочого webhook payload.
    # Якщо пацієнт підтвердив "номер, з якого дзвонить", модель може лишити поле порожнім
    if not args.get("patient_phone"):
        args["patient_phone"] = (call.get("customer") or {}).get("number") or ""

    try:
        data = BookingRequest(**args)
    except ValidationError as e:
        bad = ", ".join(sorted({str(err["loc"][0]) for err in e.errors() if err["loc"]}))
        return f"Дані некоректні або відсутні: {bad}. Перепитай у пацієнта саме це."

    # Друга лінія захисту: прапорець від LLM АБО збіг за ключовими словами
    hits = urgency.find_urgent(f"{data.symptoms_summary or ''} {data.urgent_reason or ''}")
    if hits and not data.is_urgent:
        reason = "; ".join(filter(None, [data.urgent_reason, "автоперевірка: " + ", ".join(hits)]))
        data = data.model_copy(update={"is_urgent": True, "urgent_reason": reason})

    rid, created = await db.save_booking_request(pool, f"{call_id}:{tool_call_id}", call_id, data)
    log.info("booking #%s %s urgent=%s", rid, "created" if created else "duplicate", data.is_urgent)
    if created:
        notifier.fire_and_forget(notifier.notify_booking(pool, rid))  # не затримуємо відповідь агенту

    if data.is_urgent:
        return "Заявку прийнято і позначено як пріоритетну. Адміністратор зв'яжеться з вами."
    return "Заявку прийнято. Адміністратор підтвердить час і зв'яжеться з вами."


TOOLS = {"submit_booking_request": submit_booking_request}
# Далі сюди: "check_availability", "get_doctors" ...


# --- Кінець дзвінка ------------------------------------------------------------
async def handle_end_of_call(pool, msg: dict) -> None:
    call = msg.get("call") or {}
    call_id = call.get("id", "")
    if not call_id:
        log.warning("end-of-call-report without call id")
        return

    artifact = msg.get("artifact", {})  # у новіших версіях Vapi транскрипт тут, у старіших - у msg
    transcript = artifact.get("transcript") or msg.get("transcript") or ""
    recording = artifact.get("recording")
    # TODO(verify-vapi): artifact.recording може мати інший тип/URL залежно від зберігання у Vapi.
    recording_url = (recording if isinstance(recording, str) else
                     recording.get("url") if isinstance(recording, dict) else None)
    recording_url = recording_url or artifact.get("recordingUrl") or msg.get("recordingUrl")
    user_text = urgency.user_part(transcript)
    hits = urgency.find_urgent(user_text)
    reason = ("автоперевірка розмови: " + ", ".join(hits)) if hits else None
    has_booking = await db.booking_exists_for_call(pool, call_id)

    # Дзвінок без заявки, але пацієнт щось казав -> адміну на передзвін
    needs_callback = (not has_booking) and (bool(hits) or len(user_text) >= MIN_USER_CHARS)

    log_id = await db.save_call_log(
        pool,
        call_id=call_id,
        caller_phone=(call.get("customer") or {}).get("number"),
        ended_reason=msg.get("endedReason"),
        transcript=transcript or None,
        recording_url=recording_url,
        needs_callback=needs_callback,
        is_urgent=bool(hits),
        urgent_reason=reason,
        send_recording=has_booking or needs_callback,  # порожні дзвінки адмінам не шлемо
    )

    escalated: list[int] = []
    if has_booking and hits:
        # Модель не позначила заявку терміновою, а в розмові гострі ознаки -> підвищуємо
        escalated = await db.escalate_booking(pool, call_id, reason)
        for rid in escalated:
            log.warning("booking #%s escalated to urgent by transcript check", rid)
    if needs_callback:
        log.warning("call %s ended without booking, callback needed (urgent=%s)", log_id, bool(hits))

    notifier.fire_and_forget(notifier.notify_after_call(pool, log_id, escalated, needs_callback))


def _secret_matches(provided: str, expected: str) -> bool:
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


# --- Webhook -----------------------------------------------------------------
@app.post("/vapi/webhook")
async def vapi_webhook(request: Request, x_vapi_secret: str = Header(default=""), authorization: str = Header(default="")):
    # TODO(verify-vapi): точний HTTP-заголовок залежить від налаштувань credential у Vapi.
    bearer_secret = authorization[7:] if authorization.startswith("Bearer ") else ""
    if not (_secret_matches(x_vapi_secret, settings.vapi_secret)
            or _secret_matches(bearer_secret, settings.vapi_secret)):
        raise HTTPException(status_code=401, detail="unauthorized")

    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="invalid json")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid json")
    msg = body.get("message", {})
    if not isinstance(msg, dict):
        msg = {}

    kind = msg.get("type")
    if kind not in {"tool-calls", "end-of-call-report"}:
        return {}
    pool = request.app.state.pool

    if kind == "tool-calls":
        call = msg.get("call", {})
        results = []
        tool_calls = msg.get("toolCallList", [])
        if not isinstance(tool_calls, list):
            log.warning("toolCallList is not a list for call %s", call.get("id", "unknown"))
            return {"results": results}
        for tc in tool_calls:
            if not isinstance(tc, dict) or not tc.get("id"):
                log.warning("tool call without id skipped")
                continue
            tool = TOOLS.get(tc.get("name"))
            if tool is None:
                result = "Невідомий інструмент."
            else:
                try:
                    args = tc.get("arguments", tc.get("parameters", {}))
                    if isinstance(args, str):
                        args = json.loads(args)
                    result = await tool(pool, args, call, tc["id"])
                except Exception as exc:
                    log.error("tool %s failed for call %s (%s)", tc.get("name"), call.get("id", "unknown"), type(exc).__name__)
                    result = "Вибачте, сталася технічна помилка. Будь ласка, зателефонуйте нам зранку."
            results.append({"toolCallId": tc["id"], "result": " ".join(str(result).split())})
        return {"results": results}

    if kind == "end-of-call-report":
        try:
            await handle_end_of_call(pool, msg)
        except Exception as exc:
            log.error("end-of-call-report failed for call %s (%s)", (msg.get("call") or {}).get("id", "unknown"), type(exc).__name__)
        return {}

    return {}


@app.get("/health")
async def health(request: Request):
    await request.app.state.pool.fetchval("SELECT 1")
    return {"ok": True}
