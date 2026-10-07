import os
import pytest
import respx
import httpx
from app import telegram
from app.config import settings

@pytest.mark.asyncio
async def test_telegram_ok_retry_perm_and_redacted(caplog,monkeypatch):
    monkeypatch.setattr(settings,'tg_bot_token','FAKE_TOKEN')
    monkeypatch.setattr(settings,'tg_admin_ids','100,200')
    with respx.mock(base_url='https://api.telegram.org') as router:
        route=router.post('/botFAKE_TOKEN/sendMessage')
        route.side_effect=[httpx.Response(200,json={'ok':True}),httpx.Response(429,json={'description':'retry'})]
        await telegram.send_message('тест')
        assert 'FAKE_TOKEN' not in caplog.text
    with respx.mock(base_url='https://api.telegram.org') as router:
        route=router.post('/botFAKE_TOKEN/sendMessage').mock(return_value=httpx.Response(500,json={'description':'down'}))
        assert await telegram._send_one(httpx.AsyncClient(), 'sendMessage', {'chat_id':'100'})=='retry'
    with respx.mock(base_url='https://api.telegram.org') as router:
        router.post('/botFAKE_TOKEN/sendMessage').mock(return_value=httpx.Response(400,json={'description':'bad'}))
        assert await telegram._send_one(httpx.AsyncClient(), 'sendMessage', {'chat_id':'100'})=='perm'
