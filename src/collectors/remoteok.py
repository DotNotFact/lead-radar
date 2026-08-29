from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from selectolax.parser import HTMLParser

from src.core.http import SourceUnavailableError, request_with_retry
from src.core.models import HealthStatus, RawLead

logger = logging.getLogger("lead_radar.collectors.remoteok")


class RemoteOkCollector:
    """RemoteOK: публичный JSON API (https://remoteok.com/api), без авторизации. robots.txt
    RemoteOK разрешает `*` (User-agent) в общем случае - запрещены только известные
    AI-обучающие краулеры (Amazonbot, Bytespider и т.п.), которых мы не изображаем.

    API не поддерживает поиск по ключевым словам - отдаёт все вакансии разом, фильтрация
    по queries происходит на нашей стороне (по тегам/должности/описанию). Первый элемент
    ответа - служебная запись ("legal": "..."), а не вакансия - отсеивается по отсутствию
    полей id/position.
    """

    source_id = "remoteok"
    tier = 1

    def __init__(
        self,
        *,
        base_url: str = "https://remoteok.com/api",
        queries: list[str] | None = None,
        contact_email: str = "",
        poll_interval: int = 1800,
    ) -> None:
        self.base_url = base_url
        self.queries = [q.lower() for q in (queries or [])]
        self.poll_interval = poll_interval
        self._user_agent = f"lead-radar/0.1 (contact: {contact_email})" if contact_email else "lead-radar/0.1"
        self._consecutive_failures = 0
        self._last_error: str | None = None

    async def fetch(self, since: datetime) -> list[RawLead]:
        async with httpx.AsyncClient(headers={"User-Agent": self._user_agent}, timeout=20.0) as client:
            try:
                response = await request_with_retry(client, "GET", self.base_url)
                payload: Any = response.json()
            except SourceUnavailableError as exc:
                self._consecutive_failures += 1
                self._last_error = str(exc)
                raise
            except ValueError as exc:
                # response.json() бросает ValueError (json.JSONDecodeError - его подкласс) на
                # невалидном теле - тоже деградация источника, а не падение всего скрипта.
                self._consecutive_failures += 1
                self._last_error = f"невалидный JSON: {exc}"
                raise SourceUnavailableError(self._last_error) from exc

        if not isinstance(payload, list):
            self._consecutive_failures += 1
            self._last_error = f"неожиданная форма ответа: {type(payload).__name__}, ожидался список"
            raise SourceUnavailableError(self._last_error)

        self._consecutive_failures = 0
        self._last_error = None

        leads: list[RawLead] = []
        for item in payload:
            if not isinstance(item, dict) or "id" not in item or "position" not in item:
                continue  # служебная запись (legal notice) или неожиданный формат - пропускаем
            published_at = self._parse_date(item.get("date"))
            if published_at is not None and published_at < since:
                continue
            if self.queries and not self._matches_query(item):
                continue
            leads.append(self._to_raw_lead(item))
        return leads

    def _matches_query(self, item: dict[str, Any]) -> bool:
        tags = item.get("tags") or []
        haystack = " ".join(
            [str(item.get("position", "")), str(item.get("description", "")), " ".join(str(t) for t in tags)]
        ).lower()
        return any(query in haystack for query in self.queries)

    def _parse_date(self, raw: Any) -> datetime | None:
        if not raw:
            return None
        try:
            value = str(raw).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _to_raw_lead(self, item: dict[str, Any]) -> RawLead:
        salary_min = item.get("salary_min")
        salary_max = item.get("salary_max")
        raw_budget = None
        if salary_min or salary_max:
            parts = []
            if salary_min:
                parts.append(f"от {salary_min}")
            if salary_max:
                parts.append(f"до {salary_max}")
            raw_budget = " ".join(parts) + " $"

        description = item.get("description")
        text = HTMLParser(description).text(separator="\n").strip() if description else None

        return RawLead(
            source_id=self.source_id,
            external_id=str(item["id"]),
            url=item.get("url") or item.get("apply_url"),
            title=item.get("position"),
            text=text,
            raw_budget=raw_budget,
            published_at=self._parse_date(item.get("date")),
            author_handle=None,
            meta={"company": item.get("company"), "tags": item.get("tags")},
        )

    async def health(self) -> HealthStatus:
        return HealthStatus(
            source_id=self.source_id,
            ok=self._consecutive_failures == 0,
            checked_at=datetime.now(timezone.utc),
            last_error=self._last_error,
            consecutive_failures=self._consecutive_failures,
        )
