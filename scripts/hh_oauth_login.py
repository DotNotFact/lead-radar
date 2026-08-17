"""Разовая интерактивная авторизация hh.ru OAuth (для отслеживания собственных откликов).

Перед запуском:
1. Зарегистрировать приложение на https://dev.hh.ru/admin - тип "Веб", Redirect URI можно
   указать любой валидный https-адрес (например, https://api.hh.ru) - код авторизации всё
   равно копируется вручную из адресной строки, отдельный сервер-приёмник не нужен.
2. Вписать HH_CLIENT_ID, HH_CLIENT_SECRET, HH_REDIRECT_URI в .env (redirect_uri должен
   ТОЧНО совпадать с тем, что указано в настройках приложения на dev.hh.ru).

Запуск: python -m scripts.hh_oauth_login
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from src.core.config import get_settings
from src.core.env_file import update_env_file

AUTHORIZE_URL = "https://hh.ru/oauth/authorize"
TOKEN_URL = "https://hh.ru/oauth/token"


def _extract_code(raw_input: str) -> str:
    raw_input = raw_input.strip()
    if raw_input.startswith("http"):
        query = parse_qs(urlparse(raw_input).query)
        codes = query.get("code")
        if not codes:
            raise ValueError("В ссылке нет параметра code")
        return codes[0]
    return raw_input


async def main() -> None:
    settings = get_settings()
    if not settings.hh_client_id or not settings.hh_client_secret or not settings.hh_redirect_uri:
        print(
            "Сначала заполни HH_CLIENT_ID, HH_CLIENT_SECRET, HH_REDIRECT_URI в .env "
            "(зарегистрировать приложение: https://dev.hh.ru/admin)."
        )
        return

    params = {
        "response_type": "code",
        "client_id": settings.hh_client_id,
        "redirect_uri": settings.hh_redirect_uri,
    }
    print("Открой в браузере (под своим hh.ru-аккаунтом, тем, с которого откликаешься):")
    print(f"{AUTHORIZE_URL}?{urlencode(params)}")
    print()
    print("После разрешения тебя перекинет на redirect_uri с ?code=... в адресной строке.")
    print("Вставь сюда либо весь итоговый адрес, либо только значение code:")

    raw = input("> ")
    try:
        code = _extract_code(raw)
    except ValueError as exc:
        print(f"Не удалось распознать code: {exc}")
        return

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.hh_client_id,
                "client_secret": settings.hh_client_secret,
                "redirect_uri": settings.hh_redirect_uri,
            },
        )

    if response.status_code != 200:
        print(f"hh.ru вернул ошибку {response.status_code}: {response.text[:500]}")
        return

    payload = response.json()
    access_token = payload["access_token"]
    refresh_token = payload["refresh_token"]

    update_env_file(
        Path(".env"), {"HH_ACCESS_TOKEN": access_token, "HH_REFRESH_TOKEN": refresh_token}
    )
    print("Готово: HH_ACCESS_TOKEN и HH_REFRESH_TOKEN записаны в .env.")
    print("Дальше: python -m scripts.sync_hh_applications")


if __name__ == "__main__":
    asyncio.run(main())
