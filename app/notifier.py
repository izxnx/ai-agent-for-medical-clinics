"""Сповіщення адмінам: миттєво після збереження + фоновий retry.

Гарантія "щонайменше раз": рядок блокується (FOR UPDATE SKIP LOCKED), відправляється в Telegram,
і тільки тоді ставиться admin_notified_at. Якщо Telegram не відповів - лишається NULL,
і наступний тік циклу спробує знову. Дубль можливий лише якщо процес впаде між відправкою і commit.
"""
import asyncio
import logging

from . import messages, telegram

log = logging.getLogger("notifier")
POLL_SECONDS = 15
MAX_RECORDING_ATTEMPTS = 8  # ~2 хвилини спроб; далі запис лишається в Vapi і в БД (recording_url)
_tasks: set[asyncio.Task] = set()  # тримаємо посилання, щоб задачі не збирав GC


def fire_and_forget(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _notify(pool, table: str, row_id: int, fmt) -> bool | None:
    """True - відправлено, False - помилка (буде retry), None - нічого робити (вже відправлено)."""
    # table приходить лише з наших літералів нижче, не від користувача
    try:
        async with pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT * FROM {table} WHERE id = $1 AND admin_notified_at IS NULL "
                "FOR UPDATE SKIP LOCKED",
                row_id,
            )
            if row is None:
                return None
            await telegram.send_message(fmt(row))
            await conn.execute(f"UPDATE {table} SET admin_notified_at = now() WHERE id = $1", row_id)
        return True
    except Exception:
        log.exception("notify %s #%s failed, will retry", table, row_id)
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
    """Надсилає запис розмови окремим повідомленням. Помилка запису не блокує текстові сповіщення."""
    if not telegram.configured():
        return None
    try:
        async with pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT cl.*,
                       ARRAY(SELECT b.id FROM booking_requests b
                             WHERE b.call_id = cl.call_id ORDER BY b.id) AS booking_ids,
                       EXISTS(SELECT 1 FROM booking_requests b
                              WHERE b.call_id = cl.call_id AND b.is_urgent) AS booking_urgent
                FROM call_logs cl
                WHERE cl.id = $1 AND cl.send_recording AND cl.recording_sent_at IS NULL
                  AND cl.recording_url IS NOT NULL AND cl.recording_attempts < $2
                FOR UPDATE OF cl SKIP LOCKED
                """,
                row_id, MAX_RECORDING_ATTEMPTS,
            )
            if row is None:
                return None
            try:
                await telegram.send_recording(row["recording_url"], messages.recording_caption(row))
            except Exception as e:
                await conn.execute(
                    "UPDATE call_logs SET recording_attempts = recording_attempts + 1 WHERE id = $1",
                    row_id,
                )
                log.warning("recording for call_log #%s not delivered: %s", row_id, e)
                return False
            await conn.execute("UPDATE call_logs SET recording_sent_at = now() WHERE id = $1", row_id)
        return True
    except Exception:
        log.exception("notify_recording #%s failed", row_id)
        return False


async def notify_after_call(pool, call_log_id: int, escalated_booking_ids: list[int], needs_callback: bool):
    """Порядок важливий: спершу текст (найважливіше), потім запис розмови."""
    for rid in escalated_booking_ids:
        await notify_booking(pool, rid)
    if needs_callback:
        await notify_call(pool, call_log_id)
    await notify_recording(pool, call_log_id)


async def retry_loop(pool) -> None:
    while True:
        await asyncio.sleep(POLL_SECONDS)
        try:
            rows = await pool.fetch(
                "SELECT id FROM booking_requests WHERE admin_notified_at IS NULL "
                "ORDER BY is_urgent DESC, created_at LIMIT 20"
            )
            for r in rows:
                if await notify_booking(pool, r["id"]) is False:
                    break  # Telegram, імовірно, лежить - не штурмуємо, спробуємо наступного тіку
            rows = await pool.fetch(
                "SELECT id FROM call_logs WHERE needs_callback AND admin_notified_at IS NULL "
                "ORDER BY is_urgent DESC, created_at LIMIT 20"
            )
            for r in rows:
                if await notify_call(pool, r["id"]) is False:
                    break
            rows = await pool.fetch(
                "SELECT id FROM call_logs WHERE send_recording AND recording_sent_at IS NULL "
                "AND recording_url IS NOT NULL AND recording_attempts < $1 "
                "ORDER BY created_at LIMIT 20",
                MAX_RECORDING_ATTEMPTS,
            )
            for r in rows:
                await notify_recording(pool, r["id"])
        except Exception:
            log.exception("retry loop error")
