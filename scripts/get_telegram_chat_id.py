"""Отримати лише ID чатів з Telegram updates без виводу токена чи сирих даних."""

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from dotenv import dotenv_values


def main() -> int:
    env_file = Path(__file__).resolve().parents[1] / ".env"
    token = os.environ.get("TG_BOT_TOKEN") or dotenv_values(env_file).get("TG_BOT_TOKEN")
    if not token:
        print("У .env не задано TG_BOT_TOKEN.")
        return 1

    url = f"https://api.telegram.org/bot{token}/getUpdates?limit=100&timeout=0"
    try:
        with urlopen(url, timeout=15) as response:
            payload = json.load(response)
    except HTTPError as exc:
        print(f"Telegram повернув HTTP {exc.code}; тіло відповіді приховано.")
        return 1
    except (URLError, TimeoutError, ValueError):
        print("Не вдалося прочитати Telegram updates; секрети й тіло відповіді приховано.")
        return 1

    if not isinstance(payload, dict) or payload.get("ok") is not True:
        print("Telegram не повернув updates. Перевірте токен або вимкніть встановлений webhook.")
        return 1

    ids = set()
    for update in payload.get("result", []):
        if not isinstance(update, dict):
            continue
        for key in ("message", "edited_message", "channel_post", "edited_channel_post"):
            message = update.get(key)
            chat = message.get("chat") if isinstance(message, dict) else None
            chat_id = chat.get("id") if isinstance(chat, dict) else None
            if isinstance(chat_id, int):
                ids.add(chat_id)

    if not ids:
        print("Чатів не знайдено. Додайте бота до приватної групи та надішліть /start@<username_бота>.")
        return 1

    print("Знайдені chat ID (перенесіть потрібний у TG_ADMIN_IDS):")
    for chat_id in sorted(ids):
        print(chat_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
