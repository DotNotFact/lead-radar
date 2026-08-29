from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from src.webapp.auth import InitDataAuthError, validate_init_data

BOT_TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"


def _sign(params: dict[str, str], bot_token: str) -> str:
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()


def _build_init_data(*, user_id: int, bot_token: str = BOT_TOKEN, auth_date: int | None = None) -> str:
    """Строит корректно подписанную initData - тот же алгоритм, что реализует
    validate_init_data, но независимо (тест не должен молча совпасть с багом в реализации)."""
    params = {
        "query_id": "AAabc123",
        "user": json.dumps(
            {"id": user_id, "first_name": "Danila", "username": "danila"}, separators=(",", ":")
        ),
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
    }
    params["hash"] = _sign(params, bot_token)
    return urlencode(params)


def test_valid_init_data_returns_matching_owner() -> None:
    init_data = _build_init_data(user_id=777)
    user = validate_init_data(init_data, bot_token=BOT_TOKEN, owner_id=777)
    assert user.id == 777
    assert user.username == "danila"


def test_valid_init_data_for_a_different_user_id_is_rejected() -> None:
    init_data = _build_init_data(user_id=777)
    with pytest.raises(InitDataAuthError, match="владелец"):
        validate_init_data(init_data, bot_token=BOT_TOKEN, owner_id=999)


def test_tampered_user_id_invalidates_signature() -> None:
    # Подпись посчитана для 777 - если поменять id в теле (пытаясь выдать себя за владельца),
    # hash больше не совпадает, а не "молча доверяем новому значению".
    init_data = _build_init_data(user_id=777)
    tampered = init_data.replace("777", "778")
    with pytest.raises(InitDataAuthError, match="подпись"):
        validate_init_data(tampered, bot_token=BOT_TOKEN, owner_id=778)


def test_wrong_bot_token_rejected() -> None:
    init_data = _build_init_data(user_id=777)
    with pytest.raises(InitDataAuthError, match="подпись"):
        validate_init_data(init_data, bot_token="000000:completely-different-token", owner_id=777)


def test_expired_init_data_rejected() -> None:
    ancient = int(time.time()) - 999_999
    init_data = _build_init_data(user_id=777, auth_date=ancient)
    with pytest.raises(InitDataAuthError, match="просрочена"):
        validate_init_data(init_data, bot_token=BOT_TOKEN, owner_id=777)


def test_fresh_init_data_within_max_age_accepted() -> None:
    almost_expired = int(time.time()) - 100
    init_data = _build_init_data(user_id=777, auth_date=almost_expired)
    user = validate_init_data(init_data, bot_token=BOT_TOKEN, owner_id=777, max_age_seconds=3600)
    assert user.id == 777


def test_empty_init_data_rejected() -> None:
    with pytest.raises(InitDataAuthError, match="отсутствует"):
        validate_init_data("", bot_token=BOT_TOKEN, owner_id=777)


def test_missing_hash_rejected() -> None:
    with pytest.raises(InitDataAuthError, match="hash"):
        validate_init_data("auth_date=123&user=%7B%7D", bot_token=BOT_TOKEN, owner_id=777)


def test_missing_user_field_rejected() -> None:
    params = {"auth_date": str(int(time.time()))}
    params["hash"] = _sign(params, BOT_TOKEN)
    init_data = urlencode(params)
    with pytest.raises(InitDataAuthError, match="user"):
        validate_init_data(init_data, bot_token=BOT_TOKEN, owner_id=777)
