from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from src.collectors.rss_jobs import RssJobsCollector
from src.core.http import SourceUnavailableError

_FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Backend .NET Developer</title>
      <link>https://example.com/jobs/1</link>
      <guid>https://example.com/jobs/1</guid>
      <description>Looking for a C# / ASP.NET Core developer for a remote contract.</description>
      <pubDate>{pub_date}</pubDate>
    </item>
    <item>
      <title>Frontend Designer</title>
      <link>https://example.com/jobs/2</link>
      <guid>https://example.com/jobs/2</guid>
      <description>Looking for a designer.</description>
      <pubDate>{old_date}</pubDate>
    </item>
  </channel>
</rss>
"""


def _feed(pub_date: str, old_date: str) -> str:
    return _FEED_XML.format(pub_date=pub_date, old_date=old_date)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_entries_and_filters_by_since() -> None:
    now = datetime.now(timezone.utc)
    recent = now - timedelta(hours=1)
    old = now - timedelta(days=10)
    xml = _feed(recent.strftime("%a, %d %b %Y %H:%M:%S GMT"), old.strftime("%a, %d %b %Y %H:%M:%S GMT"))

    respx.get("https://example.com/feed.rss").mock(return_value=httpx.Response(200, text=xml))

    collector = RssJobsCollector(feed_urls=["https://example.com/feed.rss"], contact_email="test@example.com")
    since = now - timedelta(days=1)
    leads = await collector.fetch(since)

    assert len(leads) == 1
    assert leads[0].title == "Backend .NET Developer"
    assert leads[0].source_id == "rss_remote_jobs"
    assert leads[0].external_id == "https://example.com/jobs/1"

    health = await collector.health()
    assert health.ok is True


@pytest.mark.asyncio
@respx.mock
async def test_fetch_raises_when_all_feeds_broken() -> None:
    respx.get("https://example.com/broken.rss").mock(
        return_value=httpx.Response(200, text="not xml at all {{{")
    )
    collector = RssJobsCollector(feed_urls=["https://example.com/broken.rss"])

    with pytest.raises(SourceUnavailableError):
        await collector.fetch(datetime.now(timezone.utc) - timedelta(days=1))

    health = await collector.health()
    assert health.ok is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_survives_partial_feed_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("src.core.http.asyncio.sleep", _no_sleep)

    now = datetime.now(timezone.utc)
    xml = _feed(
        now.strftime("%a, %d %b %Y %H:%M:%S GMT"), (now - timedelta(days=10)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    )
    respx.get("https://example.com/good.rss").mock(return_value=httpx.Response(200, text=xml))
    respx.get("https://example.com/broken.rss").mock(return_value=httpx.Response(500))

    collector = RssJobsCollector(feed_urls=["https://example.com/broken.rss", "https://example.com/good.rss"])
    leads = await collector.fetch(now - timedelta(days=1))

    assert len(leads) == 1
    health = await collector.health()
    assert health.ok is True  # не все фиды упали
