"""Відправка адмінам у Telegram. Токен бота лежить в URL, тому URL ніколи не потрапляє в логи/помилки."""
import asyncio
import logging
from urllib.parse import urlparse

import httpx

from .config import settings

log = logging.getLogger("telegram")


def admin_ids() -> list[str]:
    return [x.strip() for x in settings.tg_admin_ids.split(",") if x.strip()]


def configured() -> bool:
    return bool(settings.tg_bot_token and admin_ids())


def _description(r) -> str:
    try:
        return str(r.json().get("description", ""))
    except ValueError:
        return ""


async def _send_one(client: httpx.AsyncClient, method: str, payload: dict) -> str:
    """'ok' - доставлено; 'retry' - тимчасова помилка; 'perm' - адмін недосяжний
    (найчастіше: не натискав /start у боті, або заблокував його)."""
    url = f"https://api.telegram.org/bot{settings.tg_bot_token}/{method}"
    chat_id = payload["chat_id"]
    try:
        r = await client.post(url, json=payload)
    except httpx.HTTPError as e:
        log.warning("telegram %s -> %s: %s", method, chat_id, type(e).__name__)
        return "retry"
    if r.status_code == 200:
        return "ok"
    log.warning("telegram %s -> %s: HTTP %s %s", method, chat_id, r.status_code, _description(r))
    return "retry" if r.status_code == 429 or r.status_code >= 500 else "perm"


async def _broadcast(method: str, payload: dict) -> None:
    """Шле кожному адміну окремо. Успіх = дійшло щонайменше одному:
    якщо один адмін не натиснув /start, решта все одно отримає, а повідомлення не крутиться вічно."""
    ids = admin_ids()
    async with httpx.AsyncClient(timeout=15) as client:
        outcomes = await asyncio.gather(
            *(_send_one(client, method, {**payload, "chat_id": cid}) for cid in ids)
        )
    if "ok" not in outcomes:
        raise RuntimeError(f"{method}: не доставлено нікому {list(outcomes)}")
    if len(set(outcomes)) > 1:
        log.warning("%s: доставлено не всім адмінам %s", method, list(outcomes))


async def send_message(text: str) -> None:
    await _broadcast("sendMessage", {
        "text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
    })


async def send_recording(url: str, caption: str) -> None:
    """Telegram сам завантажує файл за посиланням (є ліміт на розмір, близько 20 МБ - звірте з Bot API).
    sendAudio приймає лише mp3/m4a, решту (wav тощо) шлемо як документ."""
    if urlparse(url).path.lower().endswith((".mp3", ".m4a")):
        await _broadcast("sendAudio", {"audio": url, "caption": caption, "parse_mode": "HTML"})
    else:
        await _broadcast("sendDocument", {"document": url, "caption": caption, "parse_mode": "HTML"})
