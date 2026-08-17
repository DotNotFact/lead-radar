from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from src.core.http import SourceUnavailableError, request_with_retry
from src.core.models import HealthStatus, RawLead

logger = logging.getLogger("lead_radar.collectors.kwork")

_STATE_MARKER = "window.stateData="


def _extract_state_data(html: str) -> dict[str, Any]:
    """Kwork рендерит карточки на сервере и кладёт весь стейт в один <script> как
    window.stateData=. Это надёжнее CSS-селекторов (не ломается от смены вёрстки/классов),
    но зависит от того, что Kwork не переименует сам ключ - за этим следит smoke-проверка ниже."""
    idx = html.find(_STATE_MARKER)
    if idx == -1:
        raise SourceUnavailableError(
            "kwork: window.stateData не найден в HTML - структура страницы изменилась"
        )
    start = idx + len(_STATE_MARKER)
    try:
        data, _ = json.JSONDecoder().raw_decode(html, start)
    except json.JSONDecodeError as exc:
        raise SourceUnavailableError(f"kwork: не удалось распарсить stateData - {exc}") from exc
    if not isinstance(data, dict):
        raise SourceUnavailableError("kwork: stateData больше не объект")
    return data


def _get_projects_list(state: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        data = state["wantsListData"]["pagination"]["data"]
    except (KeyError, TypeError) as exc:
        raise SourceUnavailableError(
            "kwork_projects: структура stateData.wantsListData.pagination.data изменилась"
        ) from exc
    if not isinstance(data, list):
        raise SourceUnavailableError("kwork_projects: pagination.data больше не список")
    return data


def _get_catalog_list(state: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        data = state["viewData"]["kworks"]["posts"]["data"]
    except (KeyError, TypeError) as exc:
        raise SourceUnavailableError(
            "kwork_catalog: структура stateData.viewData.kworks.posts.data изменилась"
        ) from exc
    if not isinstance(data, list):
        raise SourceUnavailableError("kwork_catalog: posts.data больше не список")
    return data


def _parse_kwork_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


class KworkProjectsCollector:
    """Раздел проектов заказчиков (kwork.ru/projects) - реальные лиды, доступен без
    авторизации. Только первая страница: пагинация ?page= запрещена robots.txt."""

    source_id = "kwork_projects"
    tier = 2
    _URL = "https://kwork.ru/projects"

    def __init__(self, contact_email: str = "", poll_interval: int = 900) -> None:
        self.poll_interval = poll_interval
        self._user_agent = f"lead-radar/0.1 (contact: {contact_email})" if contact_email else "lead-radar/0.1"
        self._consecutive_failures = 0
        self._last_error: str | None = None

    async def fetch(self, since: datetime) -> list[RawLead]:
        try:
            async with httpx.AsyncClient(headers={"User-Agent": self._user_agent}, timeout=20.0) as client:
                response = await request_with_retry(client, "GET", self._URL)
                state = _extract_state_data(response.text)
                items = _get_projects_list(state)
        except SourceUnavailableError as exc:
            self._consecutive_failures += 1
            self._last_error = str(exc)
            raise

        self._consecutive_failures = 0
        self._last_error = None
        return [self._to_raw_lead(item) for item in items]

    def _to_raw_lead(self, item: dict[str, Any]) -> RawLead:
        price_limit = item.get("priceLimit")
        possible_price_limit = item.get("possiblePriceLimit")
        budget_parts = []
        if price_limit:
            budget_parts.append(f"от {price_limit}")
        if possible_price_limit:
            budget_parts.append(f"до {possible_price_limit}")
        raw_budget = (" ".join(budget_parts) + " ₽") if budget_parts else None

        user = item.get("user") or {}
        username = user.get("username")

        return RawLead(
            source_id=self.source_id,
            external_id=str(item["id"]),
            url=f"https://kwork.ru/projects/{item['id']}",
            title=item.get("name"),
            text=item.get("description"),
            raw_budget=raw_budget,
            published_at=_parse_kwork_datetime(item.get("date_create")),
            author_handle=f"@{username}" if username else None,
            meta={
                "category_id": item.get("category_id"),
                "max_days": item.get("max_days"),
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


class KworkCatalogCollector:
    """Каталог услуг фрилансеров по категориям - только аналитика спроса (title, price,
    seller_level, delivery_days, кол-во отзывов как прокси orders_completed), НЕ лиды.
    Опрашивается редко (раз в сутки). Только первая страница каждой категории."""

    source_id = "kwork_catalog"
    tier = 2

    def __init__(
        self,
        category_urls: list[str],
        contact_email: str = "",
        poll_interval: int = 86400,
        min_request_interval: float = 10.0,
    ) -> None:
        self.category_urls = category_urls
        self.poll_interval = poll_interval
        self._user_agent = f"lead-radar/0.1 (contact: {contact_email})" if contact_email else "lead-radar/0.1"
        self._min_request_interval = min_request_interval
        self._consecutive_failures = 0
        self._last_error: str | None = None

    async def fetch(self, since: datetime) -> list[RawLead]:
        leads: list[RawLead] = []
        failures = 0

        async with httpx.AsyncClient(headers={"User-Agent": self._user_agent}, timeout=20.0) as client:
            for index, url in enumerate(self.category_urls):
                if index > 0:
                    await asyncio.sleep(self._min_request_interval)
                try:
                    response = await request_with_retry(client, "GET", url)
                    state = _extract_state_data(response.text)
                    items = _get_catalog_list(state)
                except SourceUnavailableError as exc:
                    failures += 1
                    self._last_error = f"{url}: {exc}"
                    logger.warning(
                        "kwork_catalog_category_failed", extra={"url": url, "error": str(exc)}
                    )
                    continue
                leads.extend(self._to_raw_lead(item) for item in items)

        if self.category_urls and failures == len(self.category_urls):
            self._consecutive_failures += 1
            raise SourceUnavailableError(self._last_error or "kwork_catalog: все категории недоступны")

        self._consecutive_failures = 0
        if failures:
            self._last_error = f"{failures}/{len(self.category_urls)} категорий не удалось загрузить"
        else:
            self._last_error = None
        return leads

    def _to_raw_lead(self, item: dict[str, Any]) -> RawLead:
        price = item.get("price")
        raw_url = item.get("url")
        return RawLead(
            source_id=self.source_id,
            external_id=str(item["id"]),
            url=f"https://kwork.ru{raw_url}" if raw_url else None,
            title=item.get("gtitle"),
            text=None,
            raw_budget=f"{price} ₽" if price is not None else None,
            published_at=None,
            author_handle=f"@{item['userName']}" if item.get("userName") else None,
            meta={
                "kind": "market_intelligence",
                "seller_level": item.get("sellerLevel"),
                "delivery_days": item.get("days"),
                "reviews_count": item.get("userRatingCount"),
                "category": item.get("categoryTitle"),
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
