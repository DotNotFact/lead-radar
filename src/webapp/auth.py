from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from pydantic import BaseModel, ValidationError

_MAX_AUTH_AGE_SECONDS = 24 * 60 * 60  # против повторного использования утёкшей initData


class TelegramUser(BaseModel):
    id: int
    first_name: str | None = None
    username: str | None = None


class InitDataAuthError(Exception):
    """initData отсутствует, повреждена, подпись не совпадает, просрочена, или пользователь не владелец."""


def _compute_secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def validate_init_data(
    init_data: str,
    *,
    bot_token: str,
    owner_id: int,
    max_age_seconds: int = _MAX_AUTH_AGE_SECONDS,
) -> TelegramUser:
    """Проверяет initData Telegram Mini App по официальному алгоритму:
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app -
    секретный ключ HMAC-SHA256(bot_token, "WebAppData"), сама подпись - HMAC-SHA256
    отсортированной по ключу строки "key=value" (без hash) этим секретом.

    Сверх спецификации Telegram (собственные требования Mini App, не опция): auth_date не
    старше max_age_seconds и user.id должен совпадать с owner_id - приложение однопользовательское,
    второго владельца не бывает (см. docs/miniapp-brief.md, п.2 жёстких ограничений)."""
    if not init_data:
        raise InitDataAuthError("initData отсутствует")

    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError as exc:
        raise InitDataAuthError("initData: не удалось разобрать строку") from exc

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataAuthError("initData без hash")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret_key = _compute_secret_key(bot_token)
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise InitDataAuthError("подпись initData не совпадает")

    auth_date_raw = pairs.get("auth_date")
    if not auth_date_raw or not auth_date_raw.isdigit():
        raise InitDataAuthError("initData без корректного auth_date")
    if time.time() - int(auth_date_raw) > max_age_seconds:
        raise InitDataAuthError("initData просрочена")

    user_raw = pairs.get("user")
    if not user_raw:
        raise InitDataAuthError("initData без user")
    try:
        user = TelegramUser.model_validate(json.loads(user_raw))
    except (ValueError, ValidationError) as exc:
        raise InitDataAuthError("initData: поле user повреждено") from exc

    if user.id != owner_id:
        raise InitDataAuthError("пользователь не владелец Mini App")

    return user
