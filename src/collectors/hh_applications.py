from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from src.core.env_file import update_env_file
from src.core.http import SourceUnavailableError, request_with_retry
from src.core.models import HhApplication

logger = logging.getLogger("lead_radar.collectors.hh_applications")

TOKEN_URL = "https://hh.ru/oauth/token"
NEGOTIATIONS_URL = "https://api.hh.ru/negotiations"


class HhOAuthError(Exception):
    """Протухший/отозванный refresh_token - чинится не бэкоффом, а повторным логином
    (python -m scripts.hh_oauth_login), в отличие от SourceUnavailableError."""


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        # hh.ru иногда отдаёт смещение без двоеточия ("+0300" вместо "+03:00")
        if len(value) >= 5 and value[-5] in "+-":
            try:
                return datetime.fromisoformat(f"{value[:-2]}:{value[-2:]}")
            except ValueError:
                return None
        return None


def raw_item_to_application(item: dict[str, Any]) -> HhApplication:
    """Поля - по документации hh.ru API для /negotiations, не проверены на живом ответе (нет
    доступа к персональному OAuth-токену из песочницы). Если структура на практике другая,
    отсутствующие поля просто останутся None - приложение не упадёт, но данные будут неполными.
    Стоит свериться при первом живом запуске владельца."""
    vacancy = item.get("vacancy") or {}
    state = item.get("state")
    state_id = state.get("id") if isinstance(state, dict) else (str(state) if state else None)

    return HhApplication(
        id=str(item.get("id")),
        vacancy_id=str(vacancy["id"]) if vacancy.get("id") is not None else None,
        vacancy_title=vacancy.get("name"),
        vacancy_url=vacancy.get("alternate_url"),
        state=state_id,
        hh_created_at=_parse_dt(item.get("created_at")),
        hh_updated_at=_parse_dt(item.get("updated_at")),
    )


class HhApplicationsClient:
    """Клиент личных откликов hh.ru (OAuth от аккаунта владельца - публичный API вакансий
    из Фазы 1 для чужих данных не годится)."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        access_token: str,
        refresh_token: str,
        env_path: Path,
        contact_email: str = "",
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.env_path = env_path
        self._user_agent = (
            f"lead-radar/0.1 (contact: {contact_email})" if contact_email else "lead-radar/0.1"
        )

    async def _refresh(self, client: httpx.AsyncClient) -> None:
        response = await request_with_retry(
            client,
            "POST",
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            # сами решаем, что делать с неуспехом (HhOAuthError, не SourceUnavailableError)
            passthrough_statuses=frozenset(range(400, 500)),
        )
        if response.status_code != 200:
            raise HhOAuthError(
                f"Не удалось обновить токен hh.ru ({response.status_code}) - нужен новый логин: "
                "python -m scripts.hh_oauth_login"
            )
        payload = response.json()
        self.access_token = payload["access_token"]
        self.refresh_token = payload.get("refresh_token", self.refresh_token)
        update_env_file(
            self.env_path,
            {"HH_ACCESS_TOKEN": self.access_token, "HH_REFRESH_TOKEN": self.refresh_token},
        )
        logger.info("hh_oauth_token_refreshed")

    async def fetch_applications(self) -> list[HhApplication]:
        async with httpx.AsyncClient(headers={"User-Agent": self._user_agent}, timeout=20.0) as client:
            raw_items = await self._fetch_all_pages(client)
        return [raw_item_to_application(item) for item in raw_items]

    async def _fetch_all_pages(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 0
        refreshed_once = False

        while True:
            response = await request_with_retry(
                client,
                "GET",
                NEGOTIATIONS_URL,
                params={"page": page, "per_page": 50},
                headers={"Authorization": f"Bearer {self.access_token}"},
                # сами решаем: 401/403 -> рефреш токена, а не сразу SourceUnavailableError
                passthrough_statuses=frozenset({401, 403}),
            )

            if response.status_code in (401, 403) and not refreshed_once:
                await self._refresh(client)
                refreshed_once = True
                continue
            if response.status_code != 200:
                raise SourceUnavailableError(
                    f"hh_applications: {response.status_code} - {response.text[:200]}"
                )

            payload = response.json()
            page_items = payload.get("items")
            if page_items is None:
                raise SourceUnavailableError(
                    "hh_applications: ответ без ключа items - структура API изменилась"
                )
            items.extend(page_items)

            pages = payload.get("pages", 1)
            page += 1
            if page >= pages:
                break

        return items
