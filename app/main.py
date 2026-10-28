import asyncio
import hashlib
import json
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import ValidationError

from app import db, notifier, telegram
from . import retell_auth, transcripts
from .config import settings
from .schemas import BookingRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx на INFO пише URL, а в ньому токен бота
log = logging.getLogger("webhook")  # у логах лише id, без імен/телефонів/скарг

TOOL_FAILURE_MESSAGE = "Вибачте, сталася технічна помилка. Будь ласка, зателефонуйте нам зранку."


def _transcript_text(value) -> str:
    """Перетворює транскрипт Retell (рядок або transcript_object[]) у текст User:/Assistant:."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        lines = []
        for item in value:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content") or item.get("message")
            if isinstance(role, str) and isinstance(content, str):
                speaker = "User" if role.lower() in {"user", "customer"} else "Assistant"
                lines.append(f"{speaker}: {content}")
        return "\n".join(lines)
    return ""


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
async def submit_booking_request(pool, args: dict, call: dict) -> str:
    """Повертає агенту інструкцію про завершення після збереження заявки."""
    call_id = call.get("call_id", "") if isinstance(call, dict) else ""
    args = dict(args) if isinstance(args, dict) else {}

    if not call_id:
        raise ValueError("missing call id")

    try:
        data = BookingRequest(**args)
    except ValidationError as e:
        bad = ", ".join(sorted({str(err["loc"][0]) for err in e.errors() if err["loc"]}))
        return f"Дані некоректні або відсутні: {bad}. Перепитай у пацієнта саме це."

    # Retell не передає tool_call_id, тому ключ ідемпотентності = дзвінок + нормалізовані дані.
    # Повтор того самого запиту (retry, подвійний виклик) не створить дубль заявки.
    digest = hashlib.sha256(
        json.dumps(data.model_dump(), sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    rid, created = await db.save_booking_request_with_retry(pool, f"{call_id}:{digest}", call_id, data)
    log.info("booking #%s %s", rid, "created" if created else "duplicate")
    # Адміну заявка приходить одним звітом після дзвінка (підсумок + діалог + запис),
    # а не окремим повідомленням посеред розмови. Якщо звіт не прийде, retry_loop надішле картку.

    if data.patient_phone:
        return "Заявку збережено. Подякуй пацієнту, повідом, що адміністратор зв'яжеться зранку, і заверши дзвінок."
    # Без номера передзвін неможливий: агент не має цього обіцяти.
    return (
        "Звернення збережено без номера телефону. Не обіцяй передзвін. Скажи, що без номера "
        "адміністратор не зможе зателефонувати, і запропонуй зателефонувати в клініку в робочий час. "
        "Подякуй і заверши дзвінок."
    )


TOOLS = {"submit_booking_request": submit_booking_request}
# Далі сюди: "check_availability", "get_doctors" ...


# --- Кінець дзвінка ------------------------------------------------------------
async def handle_call_ended(pool, call: dict) -> int | None:
    call_id = call.get("call_id", "")
    if not isinstance(call_id, str) or not call_id:
        log.warning("call_ended without call id")
        return None

    transcript = _transcript_text(call.get("transcript_object")) or _transcript_text(call.get("transcript"))
    user_text = transcripts.user_part(transcript)
    booking = await db.booking_contact_for_call(pool, call_id)
    has_booking = booking["has_booking"]

    # Дзвінок без заявки, але пацієнт щось казав -> адміну на передзвін
    needs_callback = (not has_booking) and bool(user_text.strip())

    # Caller ID не є підтвердженим контактом: caller_phone = лише номер із заявки,
    # а номер, з якого дзвонили (вхідний телефонний дзвінок), зберігаємо окремо в caller_id.
    reason = call.get("disconnection_reason")
    caller_id = None
    if call.get("direction") == "inbound":
        caller_id = _clean_text(call.get("from_number"), 40)
    log_id = await db.save_call_log(
        pool,
        call_id=call_id,
        caller_phone=booking["patient_phone"],
        ended_reason=reason if isinstance(reason, str) else None,
        transcript=transcript or None,
        # recording_url не зберігаємо; notifier бере свіжий URL з Retell API за call_id.
        recording_url=None,
        needs_callback=needs_callback,
        send_recording=settings.recording_forwarding_enabled and (has_booking or needs_callback),
        caller_id=caller_id,
    )

    if needs_callback:
        log.info("call %s ended without booking, callback requested", log_id)
    # Звіт адміну надсилається після події call_analyzed (там підсумок і поля від Retell).
    # Якщо аналіз не прийде, retry_loop надішле звіт без підсумку через REPORT_WAIT_SECONDS.
    return log_id


def _clean_text(value, limit: int = 300) -> str | None:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    text = " ".join(str(value).split())[:limit]
    return text or None


async def handle_call_analyzed(pool, call: dict) -> None:
    """call_analyzed містить повні дані дзвінка + call_analysis. Зберігаємо й надсилаємо звіт."""
    call_id = call.get("call_id", "")
    if not isinstance(call_id, str) or not call_id:
        log.warning("call_analyzed without call id")
        return
    log_id = await handle_call_ended(pool, call)  # upsert: подія call_ended могла загубитися
    if log_id is None:
        return

    analysis = call.get("call_analysis")
    analysis = analysis if isinstance(analysis, dict) else {}
    custom = analysis.get("custom_analysis_data")
    custom = custom if isinstance(custom, dict) else {}
    fields = {k: v for k in db.ANALYSIS_FIELDS if (v := _clean_text(custom.get(k), 600 if k == "summary_uk" else 300))}
    await db.save_call_analysis(pool, call_id, _clean_text(analysis.get("call_summary"), 1000), fields)
    notifier.fire_and_forget(notifier.notify_after_call(pool, log_id))


async def _verified_json(request: Request, signature: str) -> dict:
    raw = await request.body()
    try:
        raw_text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="invalid body")
    if not retell_auth.verify(raw_text, settings.retell_api_key, signature):
        raise HTTPException(status_code=401, detail="unauthorized")
    try:
        body = json.loads(raw_text)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid json")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid json")
    return body


# --- Custom function (Retell -> backend під час дзвінка) ----------------------
@app.post("/retell/function")
async def retell_function(request: Request, x_retell_signature: str = Header(default="")):
    """Payload Retell: {"name": ..., "call": {...}, "args": {...}}. Відповідь іде в LLM агента."""
    body = await _verified_json(request, x_retell_signature)
    call = body.get("call")
    call = call if isinstance(call, dict) else {}
    call_id = call.get("call_id", "unknown")
    tool_name = body.get("name") if isinstance(body.get("name"), str) else "unknown"

    tool = TOOLS.get(tool_name)
    if tool is None:
        log.warning("unknown tool %s for call %s", tool_name, call_id)
        return {"error": "Unknown tool"}

    args = body.get("args")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = None
    if not isinstance(args, dict):
        return {"result": "Аргументи заявки некоректні. Збери дані ще раз і повтори виклик."}

    try:
        result = await tool(request.app.state.pool, args, call)
    except Exception as exc:
        log.error("tool %s failed for call %s (%s)", tool_name, call_id, type(exc).__name__)
        return {"error": f"Технічна помилка. Скажи пацієнту: «{TOOL_FAILURE_MESSAGE}» і заверши дзвінок."}
    return {"result": " ".join(str(result).split())}


# --- Webhook подій дзвінка ---------------------------------------------------
@app.post("/retell/webhook")
async def retell_webhook(request: Request, x_retell_signature: str = Header(default="")):
    """Retell чекає 2xx без тіла за 10 с, інакше повторює до 3 разів (обробка ідемпотентна)."""
    body = await _verified_json(request, x_retell_signature)
    event = body.get("event")
    handlers = {"call_ended": handle_call_ended, "call_analyzed": handle_call_analyzed}
    if event in handlers:
        call = body.get("call")
        call = call if isinstance(call, dict) else {}
        try:
            await handlers[event](request.app.state.pool, call)
        except Exception as exc:
            log.error("%s failed for call %s (%s)", event, call.get("call_id", "unknown"), type(exc).__name__)
            # 5xx -> Retell повторить подію; save_call_log і сповіщення ідемпотентні.
            raise HTTPException(status_code=500, detail="temporary failure")
    return Response(status_code=204)


@app.get("/health")
async def health(request: Request):
    await request.app.state.pool.fetchval("SELECT 1")
    return {"ok": True}
