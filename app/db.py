import asyncio
import json
import logging
from pathlib import Path

import asyncpg

from .schemas import BookingRequest

log = logging.getLogger("db")
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


async def create_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn, min_size=1, max_size=10)


async def run_migrations(pool: asyncpg.Pool) -> None:
    """Мінімальний мігратор: застосовує migrations/*.sql по порядку, по одному разу."""
    async with pool.acquire() as conn:
        await conn.execute("SELECT pg_advisory_lock(727001)")  # щоб два інстанси не мігрували разом
        try:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            done = {r["name"] for r in await conn.fetch("SELECT name FROM schema_migrations")}
            for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if f.name in done:
                    continue
                log.info("applying migration %s", f.name)
                async with conn.transaction():
                    await conn.execute(f.read_text())
                    await conn.execute("INSERT INTO schema_migrations(name) VALUES ($1)", f.name)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(727001)")


# Тимчасові збої БД: обрив з'єднання, перезапуск Postgres, вичерпаний пул, тайм-аут.
TRANSIENT_DB_ERRORS = (
    OSError,
    asyncio.TimeoutError,
    asyncpg.InterfaceError,
    asyncpg.PostgresConnectionError,
    asyncpg.TooManyConnectionsError,
    asyncpg.CannotConnectNowError,
)
# Retell чекає відповідь custom function до 10 с: 3 спроби по 2.5 с + паузи вкладаються в цей ліміт.
SAVE_ATTEMPT_TIMEOUT = 2.5
SAVE_RETRY_DELAYS = (0.3, 0.7)


async def save_booking_request_with_retry(
    pool: asyncpg.Pool, key: str, call_id: str, d: BookingRequest
) -> tuple[int, bool]:
    """Кілька швидких спроб при тимчасовому збої БД. Дублів немає завдяки idempotency_key."""
    for attempt in range(len(SAVE_RETRY_DELAYS) + 1):
        try:
            rid, created = await asyncio.wait_for(
                save_booking_request(pool, key, call_id, d), SAVE_ATTEMPT_TIMEOUT
            )
            return rid, created
        except TRANSIENT_DB_ERRORS as exc:
            if attempt == len(SAVE_RETRY_DELAYS):
                raise
            log.warning("booking save attempt %s failed (%s), retrying", attempt + 1, type(exc).__name__)
            await asyncio.sleep(SAVE_RETRY_DELAYS[attempt])
    raise RuntimeError("unreachable")


async def save_booking_request(
    pool: asyncpg.Pool, key: str, call_id: str, d: BookingRequest
) -> tuple[int, bool]:
    """Повертає (id, created). Повторний виклик з тим самим key дубля не створює."""
    row = await pool.fetchrow(
        """
        INSERT INTO booking_requests
            (idempotency_key, call_id, patient_name, patient_phone, service_or_specialty,
             city_or_branch, preferred_date, preferred_time, symptoms_summary)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING id
        """,
        key, call_id, d.patient_name, d.patient_phone, d.service_or_specialty,
        d.city_or_branch, d.preferred_date, d.preferred_time, d.symptoms_summary,
    )
    if row:
        return row["id"], True
    existing = await pool.fetchval("SELECT id FROM booking_requests WHERE idempotency_key = $1", key)
    return existing, False


async def booking_contact_for_call(pool: asyncpg.Pool, call_id: str) -> asyncpg.Record:
    """Повертає наявність заявки й лише явно переданий у ній контактний номер."""
    return await pool.fetchrow(
        """
        SELECT EXISTS (
                   SELECT 1 FROM booking_requests WHERE call_id = $1
               ) AS has_booking,
               (
                   SELECT NULLIF(patient_phone, '')
                   FROM booking_requests
                   WHERE call_id = $1 AND patient_phone <> ''
                   ORDER BY id DESC
                   LIMIT 1
               ) AS patient_phone
        """,
        call_id,
    )


async def save_call_log(
    pool: asyncpg.Pool, call_id: str, caller_phone: str | None, ended_reason: str | None,
    transcript: str | None, recording_url: str | None,
    needs_callback: bool, send_recording: bool, caller_id: str | None = None,
) -> int:
    return await pool.fetchval(
        """
        INSERT INTO call_logs (call_id, caller_phone, ended_reason, transcript, recording_url,
                               needs_callback, send_recording, caller_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (call_id) DO UPDATE SET
            caller_phone = EXCLUDED.caller_phone,
            caller_id = COALESCE(EXCLUDED.caller_id, call_logs.caller_id),
            ended_reason = EXCLUDED.ended_reason,
            transcript = EXCLUDED.transcript,
            recording_url = EXCLUDED.recording_url,
            needs_callback = EXCLUDED.needs_callback,
            send_recording = EXCLUDED.send_recording
        RETURNING id
        """,
        call_id, caller_phone, ended_reason, transcript, recording_url,
        needs_callback, send_recording, caller_id,
    )


ANALYSIS_FIELDS = (
    "summary_uk", "patient_name", "patient_phone", "service", "city", "preferred_time", "complaint",
)


async def save_call_analysis(
    pool: asyncpg.Pool, call_id: str, call_summary: str | None, analysis: dict
) -> int | None:
    """Зберігає результат Post-Call Analysis. Повертає id журналу дзвінка або None."""
    return await pool.fetchval(
        """
        UPDATE call_logs SET call_summary = $2, analysis = $3::jsonb, analyzed_at = now()
        WHERE call_id = $1
        RETURNING id
        """,
        call_id, call_summary, json.dumps(analysis, ensure_ascii=False),
    )
