"""Відправка адмінам у Telegram. Токен бота лежить в URL, тому URL ніколи не потрапляє в логи/помилки."""
import logging
from urllib.parse import urlparse

import httpx

from .config import settings

log = logging.getLogger("telegram")

def get_chat_ids() -> list[str]:
    """Повертає список ID чатів (або один ID групи) з .env"""
    return [x.strip() for x in settings.tg_admin_ids.split(",") if x.strip()]

def configured() -> bool:
    return bool(settings.tg_bot_token and get_chat_ids())

def _description(r: httpx.Response) -> str:
    try:
        return str(r.json().get("description", ""))
    except ValueError:
        return ""

async def _send_to_chat(method: str, payload: dict, file_bytes: bytes = None, filename: str = None) -> None:
    """Відправляє лог у вказаний чат/групу."""
    if not configured():
        return

    async with httpx.AsyncClient(timeout=60.0) as client:
        for chat_id in get_chat_ids():
            url = f"https://api.telegram.org/bot{settings.tg_bot_token}/{method}"
            req_payload = {**payload, "chat_id": chat_id}

            req_files = None
            if file_bytes:
                file_key = "audio" if method == "sendAudio" else "document"
                req_files = {file_key: (filename, file_bytes)}

            try:
                if req_files:
                    r = await client.post(url, data=req_payload, files=req_files)
                else:
                    r = await client.post(url, json=req_payload)

                if r.status_code != 200:
                    log.warning("telegram %s -> %s: HTTP %s (%s)", method, chat_id, r.status_code, _description(r))
            except httpx.HTTPError as e:
                log.warning("telegram %s -> %s: %s", method, chat_id, type(e).__name__)

async def send_message(text: str) -> None:
    await _send_to_chat("sendMessage", {
        "text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
    })

async def send_recording(url: str, caption: str) -> None:
    """Викачує запис та кидає його в чат адмінів."""
    log.info("Завантаження запису розмови з %s", url)

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            file_bytes = resp.content
        except httpx.HTTPError as e:
            log.error("telegram.send_recording failed to download %s: %s", url, type(e).__name__)
            raise RuntimeError(f"Не вдалося викачати запис: {e}")

    path = urlparse(url).path.lower()
    if path.endswith((".mp3", ".m4a")):
        await _send_to_chat("sendAudio", {"caption": caption, "parse_mode": "HTML"}, file_bytes=file_bytes, filename="recording.mp3")
    else:
        await _send_to_chat("sendDocument", {"caption": caption, "parse_mode": "HTML"}, file_bytes=file_bytes, filename="recording.wav")