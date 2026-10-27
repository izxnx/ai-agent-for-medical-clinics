"""Перевірка підпису X-Retell-Signature без залежності від retell-sdk.

Формат заголовка: ``v=<unix_ms>,d=<hex>``, де ``d = HMAC-SHA256(api_key, raw_body + str(v))``.
Алгоритм збігається з ``retell.lib.webhook_auth.verify`` в офіційному SDK.
Підпис рахується по сирому тілу запиту, а не по пересеріалізованому JSON.
"""
import hashlib
import hmac
import re
import time

MAX_SKEW_MS = 5 * 60 * 1000
_SIGNATURE_RE = re.compile(r"v=(\d+),d=([0-9a-f]{64})")


def verify(raw_body: str, api_key: str, signature: str, now_ms: int | None = None) -> bool:
    if not raw_body.strip() or not api_key or not signature:
        return False
    match = _SIGNATURE_RE.fullmatch(signature.strip())
    if not match:
        return False
    timestamp = int(match.group(1))
    current = int(time.time() * 1000) if now_ms is None else now_ms
    if abs(current - timestamp) > MAX_SKEW_MS:
        return False
    expected = hmac.new(
        api_key.encode("utf-8"), (raw_body + str(timestamp)).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, match.group(2))


def sign(raw_body: str, api_key: str, now_ms: int | None = None) -> str:
    """Для локальних тестів: формує заголовок так само, як Retell."""
    timestamp = int(time.time() * 1000) if now_ms is None else now_ms
    digest = hmac.new(
        api_key.encode("utf-8"), (raw_body + str(timestamp)).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"v={timestamp},d={digest}"
