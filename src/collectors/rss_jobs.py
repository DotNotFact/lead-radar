from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx

from src.core.http import SourceUnavailableError, request_with_retry
from src.core.models import HealthStatus, RawLead

logger = logging.getLogger("lead_radar.collectors.rss_jobs")


class RssJobsCollector:
    """Публичные RSS-фиды удалённых вакансий (feedparser). Разные фиды не зависят друг от
    друга - падение одного не роняет остальные (инвариант 6)."""

    source_id = "rss_remote_jobs"
    tier = 1

    def __init__(self, feed_urls: list[str], contact_email: str = "", poll_interval: int = 900) -> None:
        self.feed_urls = feed_urls
        self.poll_interval = poll_interval
        self._user_agent = f"lead-radar/0.1 (contact: {contact_email})" if contact_email else "lead-radar/0.1"
        self._consecutive_failures = 0
        self._last_error: str | None = None

    async def fetch(self, since: datetime) -> list[RawLead]:
        leads: list[RawLead] = []
        failures = 0

        async with httpx.AsyncClient(headers={"User-Agent": self._user_agent}, timeout=20.0) as client:
            for url in self.feed_urls:
                try:
                    response = await request_with_retry(client, "GET", url)
                    response.raise_for_status()
                    parsed = await asyncio.to_thread(feedparser.parse, response.content)
                    if parsed.bozo and not parsed.entries:
                        raise SourceUnavailableError(
                            f"{url}: не удалось разобрать фид - {parsed.get('bozo_exception')}"
                        )
                except SourceUnavailableError as exc:
                    failures += 1
                    self._last_error = str(exc)
                    logger.warning("rss_feed_failed", extra={"url": url, "error": str(exc)})
                    continue

                for entry in parsed.entries:
                    lead = self._entry_to_raw_lead(url, entry)
                    if lead.published_at is None or lead.published_at >= since:
                        leads.append(lead)

        if self.feed_urls and failures == len(self.feed_urls):
            self._consecutive_failures += 1
            raise SourceUnavailableError(self._last_error or "rss_remote_jobs: все фиды недоступны")

        self._consecutive_failures = 0
        if not failures:
            self._last_error = None
        return leads

    def _entry_to_raw_lead(self, feed_url: str, entry: Any) -> RawLead:
        published_at = None
        published_parsed = getattr(entry, "published_parsed", None)
        if published_parsed:
            year, month, day, hour, minute, second = published_parsed[:6]
            published_at = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)

        external_id = entry.get("id") or entry.get("link") or entry.get("title", "")

        return RawLead(
            source_id=self.source_id,
            external_id=str(external_id),
            url=entry.get("link"),
            title=entry.get("title"),
            text=entry.get("summary"),
            raw_budget=None,
            published_at=published_at,
            author_handle=None,
            meta={"feed_url": feed_url},
        )

    async def health(self) -> HealthStatus:
        return HealthStatus(
            source_id=self.source_id,
            ok=self._consecutive_failures == 0,
            checked_at=datetime.now(timezone.utc),
            last_error=self._last_error,
            consecutive_failures=self._consecutive_failures,
        )
