"""Надсилання повідомлень і записів до Telegram-чатів адміністраторів."""
import logging
import ipaddress
from urllib.parse import quote, urljoin, urlparse

import httpx

from .config import settings

log = logging.getLogger("telegram")
MAX_RECORDING_BYTES = 45 * 1024 * 1024
CHUNK_SIZE = 64 * 1024


class TelegramDeliveryError(RuntimeError):
    """Безпечна для логів помилка доставки без URL, токенів або тексту відповіді API."""


def get_chat_ids() -> list[str]:
    """Повертає ID адміністраторів або групи з TG_ADMIN_IDS."""
    return [value.strip() for value in settings.tg_admin_ids.split(",") if value.strip()]


def configured() -> bool:
    return bool(settings.tg_bot_token and get_chat_ids())


def recording_url_allowed(url: str) -> bool:
    """Дозволяє лише HTTPS URL з точного списку хостів VAPI_RECORDING_HOSTS."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
        ):
            return False
        if host.lower() == "localhost" or host.lower().endswith((".localhost", ".local", ".internal")):
            return False
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            pass
        normalized_host = host.encode("idna").decode("ascii").lower()
        return normalized_host in settings.allowed_recording_hosts
    except (UnicodeError, ValueError):
        return False


def _is_api_success(response: httpx.Response) -> bool:
    if not response.is_success:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("ok") is True


async def _send_to_chats(
    method: str,
    payload: dict,
    file_bytes: bytes | None = None,
    filename: str | None = None,
) -> None:
    """Надсилає у всі налаштовані чати; успіх є, якщо доставлено хоча б в один."""
    chat_ids = get_chat_ids()
    if not settings.tg_bot_token or not chat_ids:
        return

    if file_bytes is not None:
        file_key = {"sendAudio": "audio", "sendDocument": "document"}.get(method)
        if file_key is None:
            raise ValueError("Multipart upload is supported only for audio and document")
        files = {file_key: (filename or "recording.bin", file_bytes)}
    else:
        files = None

    failures: list[str] = []
    timeout = 60.0 if files is not None else 15.0
    async with httpx.AsyncClient(timeout=timeout) as client:
        for chat_id in chat_ids:
            # Токен Telegram присутній в URL Bot API, тому URL і винятки HTTPX не логувати.
            api_url = f"https://api.telegram.org/bot{settings.tg_bot_token}/{method}"
            request_payload = {**payload, "chat_id": chat_id}
            try:
                if files is None:
                    response = await client.post(api_url, json=request_payload)
                else:
                    response = await client.post(api_url, data=request_payload, files=files)
            except httpx.HTTPError as exc:
                log.warning("Telegram %s failed for chat %s (%s)", method, chat_id, type(exc).__name__)
                failures.append(f"{chat_id}:network")
                continue

            if _is_api_success(response):
                continue

            log.warning("Telegram %s failed for chat %s (HTTP %s)", method, chat_id, response.status_code)
            failures.append(f"{chat_id}:http_{response.status_code}")

    if len(failures) == len(chat_ids):
        # Не додаємо опис Telegram API: у ньому не має бути секретів або приватних даних.
        raise TelegramDeliveryError(f"{method} was not delivered to any configured Telegram chat")
    if failures:
        log.warning("Telegram %s was delivered only to some configured chats", method)


async def send_message(text: str) -> None:
    await _send_to_chats("sendMessage", {
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })


def _recording_filename(content_type: str, url_path: str) -> tuple[str, str]:
    """Повертає безпечний тип методу Telegram і назву файла за MIME/URL."""
    mime = content_type.split(";", 1)[0].strip().lower()
    suffix = urlparse(url_path).path.rsplit(".", 1)[-1].lower() if "." in urlparse(url_path).path else ""

    if mime == "audio/mpeg" or suffix == "mp3":
        return "sendAudio", "recording.mp3"
    if mime in {"audio/mp4", "audio/m4a", "audio/x-m4a"} or suffix == "m4a":
        return "sendAudio", "recording.m4a"
    if mime in {"audio/wav", "audio/x-wav", "audio/wave"} or suffix == "wav":
        return "sendDocument", "recording.wav"
    if mime == "audio/ogg" or suffix == "ogg":
        return "sendDocument", "recording.ogg"
    if mime == "audio/aac" or suffix == "aac":
        return "sendDocument", "recording.aac"
    if mime in {"application/octet-stream", "binary/octet-stream", ""}:
        return "sendDocument", "recording.bin"
    if mime.startswith("audio/"):
        return "sendDocument", "recording.audio"
    raise TelegramDeliveryError("Recording endpoint returned a non-audio content type")


async def send_recording(call_id: str, private_api_key: str, caption: str) -> None:
    """Отримує запис через приватний API Vapi й надсилає його без збереження signed URL."""
    if not call_id.strip() or not private_api_key.strip():
        raise TelegramDeliveryError("Vapi call ID and private API key are required")

    api_url = f"https://api.vapi.ai/call/{quote(call_id, safe='')}/mono-recording"
    content = bytearray()
    content_type = ""
    final_path = ""
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
            current_url = api_url
            for redirect_count in range(4):
                # Приватний ключ надсилається тільки до api.vapi.ai, ніколи на signed URL.
                headers = {"Authorization": f"Bearer {private_api_key}"} if current_url == api_url else {}
                async with client.stream("GET", current_url, headers=headers) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if redirect_count == 3 or not location:
                            raise TelegramDeliveryError("Recording redirect limit exceeded")
                        next_url = urljoin(current_url, location)
                        if not recording_url_allowed(next_url):
                            raise TelegramDeliveryError("Recording redirect host is not allowlisted")
                        current_url = next_url
                        continue

                    if not response.is_success:
                        log.warning("Recording download failed (HTTP %s)", response.status_code)
                        raise TelegramDeliveryError("Recording download failed")
                    content_type = response.headers.get("content-type", "")
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > MAX_RECORDING_BYTES:
                        raise TelegramDeliveryError("Recording is larger than the configured upload limit")
                    async for chunk in response.aiter_bytes(CHUNK_SIZE):
                        content.extend(chunk)
                        if len(content) > MAX_RECORDING_BYTES:
                            raise TelegramDeliveryError("Recording is larger than the configured upload limit")
                    final_path = urlparse(current_url).path
                    break
            else:
                raise TelegramDeliveryError("Recording redirect limit exceeded")
    except TelegramDeliveryError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Recording download failed (%s)", type(exc).__name__)
        raise TelegramDeliveryError("Recording download failed") from None

    method, filename = _recording_filename(content_type, final_path)
    await _send_to_chats(
        method,
        {"caption": caption, "parse_mode": "HTML"},
        file_bytes=bytes(content),
        filename=filename,
    )
