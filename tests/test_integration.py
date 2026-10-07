import os
import uuid
import pytest
import asyncpg
from app import db
from app.schemas import BookingRequest

@pytest.mark.integration
@pytest.mark.asyncio
async def test_database_idempotency_escalation_upsert_and_advisory_lock():
    dsn=os.getenv('TEST_DATABASE_URL')
    if not dsn: pytest.skip('TEST_DATABASE_URL not configured')
    schema='test_'+uuid.uuid4().hex
    admin=await asyncpg.connect(dsn)
    await admin.execute(f'CREATE SCHEMA "{schema}"')
    pool=None
    try:
        pool=await asyncpg.create_pool(dsn,server_settings={'search_path':schema})
        await db.run_migrations(pool)
        await db.run_migrations(pool)
        request=BookingRequest(patient_name='Вигадане Ім’я',patient_phone='+380000000000',service_or_specialty='Консультація',city_or_branch='Львів')
        rid,created=await db.save_booking_request(pool,'key','call',request)
        assert created
        assert await db.save_booking_request(pool,'key','call',request)==(rid,False)
        assert await db.escalate_booking(pool,'call','ознака тестова')==[rid]
        logid=await db.save_call_log(pool,'call-log',None,'hangup','вигаданий транскрипт',None,True,False,None,False)
        assert await db.save_call_log(pool,'call-log',None,'done','оновлений транскрипт',None,False,False,None,False)==logid
        async with pool.acquire() as conn:
            assert await conn.fetchval('SELECT transcript FROM call_logs WHERE id=$1',logid)=='оновлений транскрипт'
            assert await conn.fetchval('SELECT pg_try_advisory_lock(727002)')
            assert await conn.fetchval('SELECT pg_advisory_unlock(727002)')
    finally:
        if pool: await pool.close()
        await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.close()
