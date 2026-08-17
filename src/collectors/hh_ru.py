from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx

from src.core.http import SourceUnavailableError, request_with_retry
from src.core.models import HealthStatus, RawLead

logger = logging.getLogger("lead_radar.collectors.hh_ru")

_PER_PAGE = 100
_INTER_PAGE_DELAY = 0.3  # вежливая пауза между страницами, даже к официальному API

# hh.ru отдаёт валюту ISO-кодом (RUR/USD/...), budget-парсер ждёт символ из keywords.yaml
_CURRENCY_CODE_TO_SYMBOL = {"RUR": "₽", "RUB": "₽", "USD": "$"}


class HhRuCollector:
    """Коллектор hh.ru. Публичный бесплатный API, ключ не нужен."""

    source_id = "hh_ru"
    tier = 1

    def __init__(
        self,
        *,
        base_url: str = "https://api.hh.ru",
        queries: list[str] | None = None,
        remote_only: bool = True,
        contact_email: str = "",
        poll_interval: int = 300,
        area: int = 113,  # 113 = Россия
    ) -> None:
        self.base_url = base_url
        self.queries = queries or []
        self.remote_only = remote_only
        self.poll_interval = poll_interval
        self._user_agent = f"lead-radar/0.1 (contact: {contact_email})" if contact_email else "lead-radar/0.1"
        self._area = area
        self._consecutive_failures = 0
        self._last_error: str | None = None

    @property
    def user_agent(self) -> str:
        return self._user_agent

    async def fetch(self, since: datetime) -> list[RawLead]:
        seen_ids: set[str] = set()
        leads: list[RawLead] = []

        async with httpx.AsyncClient(
            base_url=self.base_url, headers={"User-Agent": self._user_agent}, timeout=20.0
        ) as client:
            try:
                for query in self.queries:
                    async for item in self._search(client, query, since):
                        vacancy_id = str(item["id"])
                        if vacancy_id in seen_ids:
                            continue
                        seen_ids.add(vacancy_id)
                        leads.append(self._to_raw_lead(item))
            except SourceUnavailableError as exc:
                self._consecutive_failures += 1
                self._last_error = str(exc)
                raise
            else:
                self._consecutive_failures = 0
                self._last_error = None

        return leads

    async def _search(
        self, client: httpx.AsyncClient, query: str, since: datetime
    ) -> AsyncIterator[dict[str, Any]]:
        page = 0
        while True:
            params: dict[str, Any] = {
                "text": query,
                "area": self._area,
                "per_page": _PER_PAGE,
                "page": page,
                "date_from": since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                "order_by": "publication_time",
            }
            if self.remote_only:
                params["schedule"] = "remote"

            response = await request_with_retry(client, "GET", "/vacancies", params=params)
            payload = response.json()

            for item in payload.get("items", []):
                yield item

            page += 1
            if page >= payload.get("pages", 0):
                break
            await asyncio.sleep(_INTER_PAGE_DELAY)

    async def fetch_full_description(self, client: httpx.AsyncClient, vacancy_id: str) -> dict[str, Any]:
        response = await request_with_retry(client, "GET", f"/vacancies/{vacancy_id}")
        result: dict[str, Any] = response.json()
        return result

    def _to_raw_lead(self, item: dict[str, Any]) -> RawLead:
        salary = item.get("salary") or {}
        salary_parts = []
        if salary.get("from"):
            salary_parts.append(f"от {salary['from']}")
        if salary.get("to"):
            salary_parts.append(f"до {salary['to']}")
        currency_code = salary.get("currency")
        if currency_code:
            salary_parts.append(_CURRENCY_CODE_TO_SYMBOL.get(currency_code, str(currency_code)))
        raw_budget = " ".join(salary_parts) or None

        snippet = item.get("snippet") or {}
        text_parts = [snippet.get("requirement"), snippet.get("responsibility")]
        text = "\n".join(p for p in text_parts if p) or None

        published_at = None
        if item.get("published_at"):
            published_at = datetime.fromisoformat(item["published_at"])

        return RawLead(
            source_id=self.source_id,
            external_id=str(item["id"]),
            url=item.get("alternate_url"),
            title=item.get("name"),
            text=text,
            raw_budget=raw_budget,
            published_at=published_at,
            author_handle=None,
            meta={
                "employer": (item.get("employer") or {}).get("name"),
                "area": (item.get("area") or {}).get("name"),
                "schedule": (item.get("schedule") or {}).get("name"),
                "experience": (item.get("experience") or {}).get("name"),
                "salary_gross": salary.get("gross"),
            },
        )

    async def health(self) -> HealthStatus:
        return HealthStatus(
            source_id=self.source_id,
            ok=self._consecutive_failures == 0,
            checked_at=datetime.now(timezone.utc),
            last_error=self._last_error,
            consecutive_failures=self._consecutive_failures,
        )
