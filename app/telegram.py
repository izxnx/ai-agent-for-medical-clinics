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


def _description(r: httpx.Response) -> str:
    try:
        return str(r.json().get("description", ""))
    except ValueError:
        return ""


async def _send_one(client: httpx.AsyncClient, method: str, payload: dict, files: dict = None) -> str:
    """'ok' - доставлено; 'retry' - тимчасова помилка; 'perm' - адмін недосяжний
    (найчастіше: не натискав /start у боті, або заблокував його)."""
    url = f"https://api.telegram.org/bot{settings.tg_bot_token}/{method}"
    chat_id = payload.get("chat_id")
    try:
        # Для відправки файлів (multipart/form-data) параметри передаються в data, а не json
        if files:
            r = await client.post(url, data=payload, files=files)
        else:
            r = await client.post(url, json=payload)
    except httpx.HTTPError as e:
        log.warning("telegram %s -> %s: %s", method, chat_id, type(e).__name__)
        return "retry"

    if r.status_code == 200:
        return "ok"

    log.warning("telegram %s -> %s: HTTP %s (%s)", method, chat_id, r.status_code, _description(r))
    return "retry" if r.status_code == 429 or r.status_code >= 500 else "perm"


async def _broadcast(method: str, payload: dict, file_bytes: bytes = None, filename: str = None) -> None:
    """Шле кожному адміну окремо. Успіх = дійшло щонайменше одному."""
    ids = admin_ids()
    # Збільшуємо таймаут для завантаження та відправки файлів
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = []
        for cid in ids:
            req_payload = {**payload, "chat_id": cid}

            req_files = None
            if file_bytes:
                # Визначаємо ключ залежно від методу Telegram API
                file_key = "audio" if method == "sendAudio" else "document"
                req_files = {file_key: (filename, file_bytes)}

            tasks.append(_send_one(client, method, req_payload, req_files))

        outcomes = await asyncio.gather(*tasks)

    if "ok" not in outcomes:
        raise RuntimeError(f"{method}: не доставлено нікому {list(outcomes)}")
    if len(set(outcomes)) > 1:
        log.warning("%s: доставлено не всім адмінам %s", method, list(outcomes))


async def send_message(text: str) -> None:
    await _broadcast("sendMessage", {
        "text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
    })


async def send_recording(url: str, caption: str) -> None:
    """Фізично завантажує файл за посиланням і надсилає його в Telegram як multipart."""
    log.info("Завантаження запису розмови з %s", url)

    # 1. Завантажуємо файл в оперативну пам'ять (із підтримкою редиректів)
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            file_bytes = resp.content
        except httpx.HTTPError as e:
            log.error("telegram.send_recording failed to download %s: %s", url, type(e).__name__)
            raise RuntimeError(f"Не вдалося викачати запис: {e}")

    # 2. Визначаємо формат і відправляємо в Telegram
    path = urlparse(url).path.lower()
    if path.endswith((".mp3", ".m4a")):
        await _broadcast(
            "sendAudio",
            {"caption": caption, "parse_mode": "HTML"},
            file_bytes=file_bytes,
            filename="recording.mp3"
        )
    else:
        await _broadcast(
            "sendDocument",
            {"caption": caption, "parse_mode": "HTML"},
            file_bytes=file_bytes,
            filename="recording.wav"
        )