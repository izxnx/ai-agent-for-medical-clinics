import asyncio
import hmac
import json
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import ValidationError

from app import db, notifier, telegram, urgency
from .config import settings
from .schemas import BookingRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx на INFO пише URL, а в ньому токен бота
log = logging.getLogger("webhook")  # у логах лише id, без імен/телефонів/скарг

MIN_USER_CHARS = 40  # дзвінок без заявки, де пацієнт сказав менше, вважаємо випадковим
TOOL_FAILURE_MESSAGE = "Вибачте, сталася технічна помилка. Будь ласка, зателефонуйте нам зранку."


def _transcript_text(value) -> str:
    """Перетворює задокументовані Vapi рядок або список реплік у текст."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        lines = []
        for item in value:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("message") or item.get("content")
            if isinstance(role, str) and isinstance(content, str):
                speaker = "User" if role.lower() in {"user", "customer"} else "Assistant"
                lines.append(f"{speaker}: {content}")
        return "\n".join(lines)
    return ""


def _recording_url(value) -> str | None:
    """Дістає URL із recording; точну форму URL-об'єкта звірити на першому Vapi дзвінку."""
    # TODO(verify-vapi): зіставити ключі об'єкта recording і redirect hosts з першим синтетичним звітом.
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return None
    preferred_keys = (
        "url", "recordingUrl", "presignedUrl", "presignedMonoUrl", "monoUrl",
        "stereoUrl", "presignedStereoUrl",
    )
    for key in preferred_keys:
        candidate = value.get(key)
        if isinstance(candidate, str):
            return candidate
    for key, candidate in value.items():
        lowered = str(key).lower()
        if any(part in lowered for part in ("recording", "mono", "stereo")):
            nested = _recording_url(candidate)
            if nested:
                return nested
    return None


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
    call_id = call.get("id", "") if isinstance(call, dict) else ""
    args = dict(args) if isinstance(args, dict) else {}
    # Vapi Call Object документує customer.number; якщо воно відсутнє, номер збирає асистент.
    # Якщо пацієнт підтвердив "номер, з якого дзвонить", модель може лишити поле порожнім
    if not args.get("patient_phone"):
        customer = call.get("customer") if isinstance(call, dict) else None
        customer = customer if isinstance(customer, dict) else {}
        args["patient_phone"] = customer.get("number") or ""

    if not call_id:
        raise ValueError("missing call id")

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

    artifact = msg.get("artifact")
    artifact = artifact if isinstance(artifact, dict) else {}
    transcript = _transcript_text(artifact.get("transcript") or msg.get("transcript"))
    recording_url = (
        _recording_url(artifact.get("recording"))
        or artifact.get("recordingUrl")
        or msg.get("recordingUrl")
    )
    if not isinstance(recording_url, str) or not telegram.recording_url_allowed(recording_url):
        recording_url = None
        log.info("recording omitted because its host is not allowlisted for call %s", call_id)
    user_text = urgency.user_part(transcript)
    hits = urgency.find_urgent(user_text)
    reason = ("автоперевірка розмови: " + ", ".join(hits)) if hits else None
    has_booking = await db.booking_exists_for_call(pool, call_id)

    # Дзвінок без заявки, але пацієнт щось казав -> адміну на передзвін
    needs_callback = (not has_booking) and (bool(hits) or len(user_text) >= MIN_USER_CHARS)

    log_id = await db.save_call_log(
        pool,
        call_id=call_id,
        caller_phone=(call.get("customer") or {}).get("number") if isinstance(call.get("customer"), dict) else None,
        ended_reason=msg.get("endedReason"),
        transcript=transcript or None,
        recording_url=recording_url,
        needs_callback=needs_callback,
        is_urgent=bool(hits),
        urgent_reason=reason,
        send_recording=bool(recording_url) and (has_booking or needs_callback),  # порожні дзвінки адмінам не шлемо
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
    return bool(provided and expected) and hmac.compare_digest(
        provided.encode("utf-8"), expected.encode("utf-8")
    )


# --- Webhook -----------------------------------------------------------------
@app.post("/vapi/webhook")
async def vapi_webhook(request: Request, x_vapi_secret: str = Header(default=""), authorization: str = Header(default="")):
    # Custom Credential у Vapi налаштовується як Bearer або X-Vapi-Secret.
    scheme, separator, credential = authorization.partition(" ")
    bearer_secret = credential.strip() if separator and scheme.lower() == "bearer" else ""
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
        call = call if isinstance(call, dict) else {}
        results = []
        tool_calls = msg.get("toolCallList", [])
        if not isinstance(tool_calls, list):
            log.warning("toolCallList is not a list for call %s", call.get("id", "unknown"))
            return {"results": results}
        for tc in tool_calls:
            if not isinstance(tc, dict) or not isinstance(tc.get("id"), str) or not tc["id"].strip():
                log.warning("tool call without id skipped")
                continue
            function = tc.get("function")
            function = function if isinstance(function, dict) else {}
            # Актуальний payload: toolCallList[].function.{name,arguments}.
            # Верхньорівневі поля залишено для сумісності зі старими інтеграціями.
            raw_tool_name = function.get("name") or tc.get("name")
            tool_name = raw_tool_name if isinstance(raw_tool_name, str) else "unknown"
            tool = TOOLS.get(tool_name)
            if tool is None:
                response = {"toolCallId": tc["id"], "error": "Unknown tool"}
            else:
                try:
                    args = function.get("arguments", tc.get("arguments", tc.get("parameters", {})))
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = None
                    if not isinstance(args, dict):
                        result = "Аргументи заявки некоректні. Збери дані ще раз і повтори виклик."
                    else:
                        result = await tool(pool, args, call, tc["id"])
                    response = {"toolCallId": tc["id"], "result": " ".join(str(result).split())}
                except Exception as exc:
                    log.error("tool %s failed for call %s (%s)", tool_name, call.get("id", "unknown"), type(exc).__name__)
                    response = {"toolCallId": tc["id"], "error": TOOL_FAILURE_MESSAGE}
            results.append(response)
        return {"results": results}

    if kind == "end-of-call-report":
        try:
            await handle_end_of_call(pool, msg)
        except Exception as exc:
            call = msg.get("call")
            call_id = call.get("id", "unknown") if isinstance(call, dict) else "unknown"
            log.error("end-of-call-report failed for call %s (%s)", call_id, type(exc).__name__)
        return {}

    return {}


@app.get("/health")
async def health(request: Request):
    await request.app.state.pool.fetchval("SELECT 1")
    return {"ok": True}
