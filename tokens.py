from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

# Секрет для подписи ссылок. Отдельный LINK_SECRET — лучше; если не задан,
# переиспользуем секрет вебхука (он и так стабильный и уже в .env).
SECRET = (os.getenv("LINK_SECRET") or os.getenv("BEDOLAGA_WEBHOOK_SECRET") or "").encode("utf-8")
TTL = int(os.getenv("LINK_TTL_DAYS", "365")) * 86400   # срок жизни ссылки (запас; реальный барьер — is_full_active)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make(user_id: int) -> str:
    """Подписанный токен для user_id (кладётся в ссылку сообщения)."""
    body = f"{int(user_id)}.{int(time.time()) + TTL}".encode()
    sig = hmac.new(SECRET, body, hashlib.sha256).digest()
    return f"{_b64(body)}.{_b64(sig)}"


def verify(token: str) -> int | None:
    """user_id, если токен валиден и не просрочен; иначе None (fail-closed)."""
    if not SECRET:                       # секрет не настроен — ничего не пропускаем
        return None
    try:
        body_b64, sig_b64 = token.split(".", 1)
        body = _unb64(body_b64)
        expected = hmac.new(SECRET, body, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(sig_b64)):
            return None
        user_id_s, exp_s = body.decode().split(".")
        if int(exp_s) < int(time.time()):
            return None
        return int(user_id_s)
    except Exception:                    # любой кривой токен — просто невалиден
        return None
