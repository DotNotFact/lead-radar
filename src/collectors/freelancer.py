from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx

from src.core.http import SourceUnavailableError, request_with_retry
from src.core.models import HealthStatus, RawLead

logger = logging.getLogger("lead_radar.collectors.freelancer")

_INTER_PAGE_DELAY = 0.3  # вежливая пауза между страницами, как у hh_ru


class FreelancerCollector:
    """Freelancer.com: официальный публичный API (developers.freelancer.com), личный OAuth-
    токен из настроек аккаунта (Settings -> API), без отдельного партнёрского доступа - в
    отличие от Upwork, у которого публичного job-search API давно нет. robots.txt
    freelancer.com не запрещает /projects* для общего User-agent.

    Поля ответа - по документации API, НЕ проверены на живом токене (нет доступа к личному
    аккаунту владельца). Если структура на практике отличается, отсутствующие поля останутся
    None, а не уронят коллектор - стоит свериться на первом реальном прогоне владельца, тот же
    подход, что у HhApplicationsClient (src/collectors/hh_applications.py)."""

    source_id = "freelancer"
    tier = 1

    def __init__(
        self,
        *,
        oauth_token: str,
        base_url: str = "https://www.freelancer.com/api/projects/0.1",
        queries: list[str] | None = None,
        contact_email: str = "",
        poll_interval: int = 1800,
        page_size: int = 50,
    ) -> None:
        self.oauth_token = oauth_token
        self.base_url = base_url
        self.queries = queries or []
        self.poll_interval = poll_interval
        self.page_size = page_size
        self._user_agent = f"lead-radar/0.1 (contact: {contact_email})" if contact_email else "lead-radar/0.1"
        self._consecutive_failures = 0
        self._last_error: str | None = None

    async def fetch(self, since: datetime) -> list[RawLead]:
        seen_ids: set[str] = set()
        leads: list[RawLead] = []

        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers={"User-Agent": self._user_agent, "freelancer-oauth-v1": self.oauth_token},
            timeout=20.0,
        ) as client:
            try:
                for query in self.queries:
                    async for item in self._search(client, query):
                        project_id = str(item.get("id"))
                        if project_id in seen_ids:
                            continue
                        published_at = self._parse_submitdate(item.get("submitdate"))
                        if published_at is not None and published_at < since:
                            continue
                        seen_ids.add(project_id)
                        leads.append(self._to_raw_lead(item))
            except SourceUnavailableError as exc:
                self._consecutive_failures += 1
                self._last_error = str(exc)
                raise
            else:
                self._consecutive_failures = 0
                self._last_error = None

        return leads

    async def _search(self, client: httpx.AsyncClient, query: str) -> AsyncIterator[dict[str, Any]]:
        offset = 0
        while True:
            params: dict[str, Any] = {
                "query": query,
                "limit": self.page_size,
                "offset": offset,
                "full_description": "true",
                "job_details": "true",
                "compact": "true",
            }
            response = await request_with_retry(client, "GET", "/projects/active/", params=params)
            payload = response.json()
            result = payload.get("result") or {}
            projects = result.get("projects") or []
            if not projects:
                break

            for item in projects:
                if isinstance(item, dict) and item.get("id") is not None:
                    yield item

            offset += len(projects)
            total_count = result.get("total_count", 0)
            if offset >= total_count or len(projects) < self.page_size:
                break
            await asyncio.sleep(_INTER_PAGE_DELAY)

    def _parse_submitdate(self, raw: Any) -> datetime | None:
        if raw is None:
            return None
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return None

    def _to_raw_lead(self, item: dict[str, Any]) -> RawLead:
        budget = item.get("budget") or {}
        currency = ((budget.get("currency") or {}).get("code")) if isinstance(budget, dict) else None
        raw_budget = None
        if budget.get("minimum") or budget.get("maximum"):
            parts = []
            if budget.get("minimum"):
                parts.append(f"от {budget['minimum']}")
            if budget.get("maximum"):
                parts.append(f"до {budget['maximum']}")
            raw_budget = " ".join(parts) + (f" {currency}" if currency else "")

        seo_url = item.get("seo_url")
        url = f"https://www.freelancer.com/projects/{seo_url}" if seo_url else None

        jobs = item.get("jobs") or []
        tags = [j.get("name") for j in jobs if isinstance(j, dict) and j.get("name")]

        return RawLead(
            source_id=self.source_id,
            external_id=str(item["id"]),
            url=url,
            title=item.get("title"),
            text=item.get("description") or item.get("preview_description"),
            raw_budget=raw_budget,
            published_at=self._parse_submitdate(item.get("submitdate")),
            author_handle=None,
            meta={"tags": tags, "type": item.get("type")},
        )

    async def health(self) -> HealthStatus:
        return HealthStatus(
            source_id=self.source_id,
            ok=self._consecutive_failures == 0,
            checked_at=datetime.now(timezone.utc),
            last_error=self._last_error,
            consecutive_failures=self._consecutive_failures,
        )
