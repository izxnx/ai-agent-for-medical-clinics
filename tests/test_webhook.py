import json
from pathlib import Path
import httpx
import pytest
from app import main

FIXTURES=Path(__file__).parent/'fixtures'
class FakePool:
    async def fetchval(self,*args): return 1

@pytest.fixture
def fake_state(monkeypatch):
    main.app.state.pool=FakePool()
    saved={"keys":set(),"data":[],"escalated":[],"call_logs":[]}
    async def save(pool,key,call_id,data):
        if key in saved["keys"]: return 1,False
        saved["keys"].add(key); saved["data"].append(data); return len(saved["keys"]),True
    async def exists(pool,call_id): return call_id in {'call-fake-001'}
    async def save_log(pool,**kwargs):
        saved["call_logs"].append(kwargs)
        return 50
    async def escalate(pool,call_id,reason): saved["escalated"].append(call_id); return [1]
    monkeypatch.setattr(main.db,'save_booking_request',save)
    monkeypatch.setattr(main.db,'booking_exists_for_call',exists)
    monkeypatch.setattr(main.db,'save_call_log',save_log)
    monkeypatch.setattr(main.db,'escalate_booking',escalate)
    monkeypatch.setattr(main.notifier,'fire_and_forget',lambda coro: coro.close())
    async def failed(*args,**kwargs): raise RuntimeError('telegram down')
    monkeypatch.setattr(main.notifier,'notify_booking',failed)
    return saved

async def post(payload,headers=None):
    transport=httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport,base_url='http://test') as client:
        return await client.post('/vapi/webhook',json=payload,headers=headers or {})

def read(name): return json.loads((FIXTURES/name).read_text(encoding='utf-8-sig'))

@pytest.mark.asyncio
async def test_webhook_auth_and_invalid_json():
    tr=httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=tr,base_url='http://test') as c:
        assert (await c.post('/vapi/webhook',json={})).status_code==401
        assert (await c.post('/vapi/webhook',content=b'{',headers={'X-Vapi-Secret':'test-secret'})).status_code==400
        assert (await c.post('/vapi/webhook',json={'message':None},headers={'Authorization':'Bearer test-secret'})).status_code==200

@pytest.mark.asyncio
async def test_booking_duplicate_and_string_result(fake_state):
    p=read('tool_regular.json')
    first=await post(p,{'X-Vapi-Secret':'test-secret'}); second=await post(p,{'X-Vapi-Secret':'test-secret'})
    assert first.status_code==second.status_code==200
    assert first.json()['results'][0]['toolCallId']=='tool-001'
    assert isinstance(first.json()['results'][0]['result'],str)
    assert '\n' not in first.json()['results'][0]['result']
    assert len(fake_state["keys"])==1
    assert fake_state["data"][0].patient_phone == "+380000000000"

@pytest.mark.asyncio
async def test_validation_returns_field(fake_state):
    result=await post(read('tool_validation_error.json'),{'X-Vapi-Secret':'test-secret'})
    assert 'city_or_branch' in result.json()['results'][0]['result']

@pytest.mark.asyncio
async def test_bad_tool_id_is_skipped(fake_state):
    result=await post({'message':{'type':'tool-calls','toolCallList':[{'name':'what'}]}},{'X-Vapi-Secret':'test-secret'})
    assert result.json()=={'results':[]}

@pytest.mark.asyncio
async def test_end_of_call_and_escalation(fake_state):
    p=read('end_call_escalate.json')
    result=await post(p,{'X-Vapi-Secret':'test-secret'})
    assert result.status_code==200
    assert fake_state["escalated"]==["call-fake-001"]

@pytest.mark.asyncio
async def test_level1_without_customer_number_and_auto_urgency(fake_state):
    urgent=read('tool_level1_no_name.json')
    assert (await post(urgent,{'X-Vapi-Secret':'test-secret'})).status_code==200
    assert fake_state['data'][0].patient_name=='Не вказано'
    assert fake_state['data'][0].patient_phone=='' and fake_state['data'][0].is_urgent
    p=read('tool_regular.json')
    p['message']['toolCallList'][0]['id']='auto-urgent'
    p['message']['toolCallList'][0]['parameters']['symptoms_summary']='нога раптово побіліла'
    await post(p,{'X-Vapi-Secret':'test-secret'})
    assert fake_state['data'][-1].is_urgent

@pytest.mark.asyncio
async def test_telegram_exception_does_not_change_tool_response(monkeypatch,fake_state):
    pending=[]
    monkeypatch.setattr(main.notifier,'fire_and_forget',lambda coro: pending.append(coro))
    result=await post(read('tool_regular.json'),{'X-Vapi-Secret':'test-secret'})
    assert result.status_code==200
    assert result.json()['results'][0]['result']
    with pytest.raises(RuntimeError): await pending[0]

@pytest.mark.asyncio
async def test_level2_validation_duplicate_and_empty_end_calls(fake_state):
    assert (await post(read('tool_level2.json'),{'X-Vapi-Secret':'test-secret'})).status_code==200
    callback=read('tool_callback.json')
    callback_result=await post(callback,{'X-Vapi-Secret':'test-secret'})
    assert callback_result.status_code==200
    assert fake_state['data'][-1].patient_phone=='+380000000000' and fake_state['data'][-1].service_or_specialty=='Передзвін'
    assert (await post(read('end_call_urgent_no_booking.json'),{'X-Vapi-Secret':'test-secret'})).status_code==200
    assert fake_state['call_logs'][-1]['needs_callback'] is True
    assert fake_state['call_logs'][-1]['is_urgent'] is True
    assert (await post(read('end_call_empty.json'),{'X-Vapi-Secret':'test-secret'})).status_code==200
    assert fake_state['call_logs'][-1]['needs_callback'] is False
    assert (await post(read('end_call_booking.json'),{'X-Vapi-Secret':'test-secret'})).status_code==200
    assert fake_state['call_logs'][-1]['needs_callback'] is False

@pytest.mark.asyncio
async def test_non_ascii_secret_uses_utf8_bytes(monkeypatch,fake_state):
    assert main._secret_matches('тест-секрет','тест-секрет')
    assert not main._secret_matches('інший','тест-секрет')
    monkeypatch.setattr(main.settings,'vapi_secret','test-secret')
    response=await post({'message':None},{'X-Vapi-Secret':'test-secret'})
    assert response.status_code==200


@pytest.mark.asyncio
async def test_lifespan_without_telegram_leaves_database_available(monkeypatch,caplog):
    class Pool:
        closed=False
        async def close(self): self.closed=True
    pool=Pool(); migrations=[]; workers=[]
    async def create_pool(dsn): return pool
    async def run_migrations(dbpool): migrations.append(dbpool)
    async def retry_loop(dbpool): workers.append(dbpool)
    monkeypatch.setattr(main.db,'create_pool',create_pool)
    monkeypatch.setattr(main.db,'run_migrations',run_migrations)
    monkeypatch.setattr(main.telegram,'configured',lambda:False)
    monkeypatch.setattr(main.notifier,'retry_loop',retry_loop)
    async with main.lifespan(main.app):
        assert main.app.state.pool is pool
        assert migrations==[pool] and workers==[]
        assert 'заявки лишаються в БД' in caplog.text
    assert pool.closed
