"""Telegram-сповіщення з повторними спробами та короткими DB claim leases."""

import asyncio
import logging
from uuid import uuid4

from . import messages, telegram
from .config import settings

log = logging.getLogger("notifier")
POLL_SECONDS = 15
MAX_RECORDING_ATTEMPTS = 8
MESSAGE_LEASE_SECONDS = 300
RECORDING_LEASE_SECONDS = 600
_tasks: set[asyncio.Task] = set()


def fire_and_forget(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _release_message_claim(pool, table: str, row_id: int, token: str) -> None:
    await pool.execute(
        f"UPDATE {table} SET notify_claim_token = NULL, notify_claimed_until = NULL "
        "WHERE id = $1 AND notify_claim_token = $2",
        row_id,
        token,
    )


async def _notify(pool, table: str, row_id: int, fmt) -> bool | None:
    """Claim row короткою транзакцією, Telegram HTTP виконується після її commit."""
    token = uuid4().hex
    try:
        async with pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"""
                UPDATE {table}
                SET notify_claim_token = $2,
                    notify_claimed_until = now() + ($3::double precision * interval '1 second')
                WHERE id = $1 AND admin_notified_at IS NULL
                  AND (notify_claim_token IS NULL OR notify_claimed_until < now())
                RETURNING *
                """,
                row_id,
                token,
                float(MESSAGE_LEASE_SECONDS),
            )
        if row is None:
            return None

        # Мережа викликається після завершення транзакції: блокування рядка не тримається до 15 с.
        try:
            await telegram.send_message(fmt(row))
        except Exception as exc:
            try:
                await _release_message_claim(pool, table, row_id, token)
            except Exception as release_exc:
                log.error("notify claim release failed for %s #%s (%s)", table, row_id, type(release_exc).__name__)
            log.error("notify %s #%s failed (%s), will retry", table, row_id, type(exc).__name__)
            return False

        await pool.execute(
            f"UPDATE {table} SET admin_notified_at = now(), notify_claim_token = NULL, "
            "notify_claimed_until = NULL WHERE id = $1 AND notify_claim_token = $2",
            row_id,
            token,
        )
        return True
    except Exception as exc:
        log.error("notify %s #%s failed (%s)", table, row_id, type(exc).__name__)
        return False


async def notify_booking(pool, row_id: int):
    if not telegram.configured():
        return None
    return await _notify(pool, "booking_requests", row_id, messages.format_booking)


async def notify_call(pool, row_id: int):
    if not telegram.configured():
        return None
    return await _notify(pool, "call_logs", row_id, messages.format_call)


async def notify_recording(pool, row_id: int) -> bool | None:
    """Завантажує запис через приватний Vapi API після короткого DB claim."""
    if not telegram.configured() or not settings.recording_forwarding_enabled:
        return None
    token = uuid4().hex
    try:
        async with pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"""
                UPDATE call_logs AS cl
                SET recording_claim_token = $2,
                    recording_claimed_until = now() + ($4::double precision * interval '1 second'),
                    recording_attempts = recording_attempts + 1
                WHERE cl.id = $1 AND cl.send_recording AND cl.recording_sent_at IS NULL
                  AND cl.recording_attempts < $3
                  AND (cl.recording_claim_token IS NULL OR cl.recording_claimed_until < now())
                RETURNING cl.*,
                    ARRAY(SELECT b.id FROM booking_requests b
                          WHERE b.call_id = cl.call_id ORDER BY b.id) AS booking_ids
                """,
                row_id,
                token,
                MAX_RECORDING_ATTEMPTS,
                float(RECORDING_LEASE_SECONDS),
            )
        if row is None:
            return None

        try:
            await telegram.send_recording(
                row["call_id"], settings.vapi_private_api_key, messages.recording_caption(row)
            )
        except Exception as exc:
            try:
                await pool.execute(
                    "UPDATE call_logs SET recording_claim_token = NULL, recording_claimed_until = NULL "
                    "WHERE id = $1 AND recording_claim_token = $2",
                    row_id,
                    token,
                )
            except Exception as release_exc:
                log.error("recording claim release failed for call_log #%s (%s)", row_id, type(release_exc).__name__)
            log.warning("recording for call_log #%s not delivered (%s)", row_id, type(exc).__name__)
            return False

        await pool.execute(
            "UPDATE call_logs SET recording_sent_at = now(), recording_claim_token = NULL, "
            "recording_claimed_until = NULL WHERE id = $1 AND recording_claim_token = $2",
            row_id,
            token,
        )
        return True
    except Exception as exc:
        log.error("notify_recording #%s failed (%s)", row_id, type(exc).__name__)
        return False


async def notify_after_call(pool, call_log_id: int, needs_callback: bool):
    """Спершу надсилає текст передзвону, потім дозволений запис розмови."""
    if needs_callback:
        await notify_call(pool, call_log_id)
    await notify_recording(pool, call_log_id)


async def retry_loop(pool) -> None:
    while True:
        await asyncio.sleep(POLL_SECONDS)
        try:
            rows = await pool.fetch(
                "SELECT id FROM booking_requests WHERE admin_notified_at IS NULL "
                "AND (notify_claimed_until IS NULL OR notify_claimed_until < now()) "
                "ORDER BY created_at LIMIT 20"
            )
            for row in rows:
                if await notify_booking(pool, row["id"]) is False:
                    break
            rows = await pool.fetch(
                "SELECT id FROM call_logs WHERE needs_callback AND admin_notified_at IS NULL "
                "AND (notify_claimed_until IS NULL OR notify_claimed_until < now()) "
                "ORDER BY created_at LIMIT 20"
            )
            for row in rows:
                if await notify_call(pool, row["id"]) is False:
                    break
            if settings.recording_forwarding_enabled:
                rows = await pool.fetch(
                    "SELECT id FROM call_logs WHERE send_recording AND recording_sent_at IS NULL "
                    "AND recording_attempts < $1 "
                    "AND (recording_claimed_until IS NULL OR recording_claimed_until < now()) "
                    "ORDER BY created_at LIMIT 20",
                    MAX_RECORDING_ATTEMPTS,
                )
                for row in rows:
                    await notify_recording(pool, row["id"])
        except Exception as exc:
            log.error("retry loop failed (%s)", type(exc).__name__)
