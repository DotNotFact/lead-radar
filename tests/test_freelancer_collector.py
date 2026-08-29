from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from src.collectors.freelancer import FreelancerCollector
from src.core.http import SourceUnavailableError


def _search_response(*projects: dict[str, object], total_count: int | None = None) -> dict[str, object]:
    return {
        "status": "success",
        "result": {"projects": list(projects), "total_count": total_count if total_count is not None else len(projects)},
    }


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_projects_and_sends_oauth_header() -> None:
    now = datetime.now(timezone.utc)
    project = {
        "id": 555,
        "title": "C# / .NET backend for a booking platform",
        "description": "Need help fixing legacy ASP.NET Core integration bugs.",
        "seo_url": "555/csharp-net-backend",
        "submitdate": now.timestamp(),
        "budget": {"minimum": 500, "maximum": 1500, "currency": {"code": "USD"}},
        "jobs": [{"name": "C#"}, {"name": ".NET"}],
        "type": "fixed",
    }
    route = respx.get("https://www.freelancer.com/api/projects/0.1/projects/active/").mock(
        return_value=httpx.Response(200, json=_search_response(project))
    )

    collector = FreelancerCollector(oauth_token="secret-token", queries=["C#"], contact_email="test@example.com")
    leads = await collector.fetch(now - timedelta(days=1))

    assert route.calls.last.request.headers["freelancer-oauth-v1"] == "secret-token"
    assert len(leads) == 1
    lead = leads[0]
    assert lead.source_id == "freelancer"
    assert lead.external_id == "555"
    assert lead.url == "https://www.freelancer.com/projects/555/csharp-net-backend"
    assert lead.raw_budget == "от 500 до 1500 USD"
    assert "ASP.NET Core" in (lead.text or "")

    health = await collector.health()
    assert health.ok is True


@pytest.mark.asyncio
@respx.mock
async def test_fetch_deduplicates_across_queries() -> None:
    now = datetime.now(timezone.utc)
    project = {"id": 1, "title": "Dup", "submitdate": now.timestamp()}
    respx.get("https://www.freelancer.com/api/projects/0.1/projects/active/").mock(
        return_value=httpx.Response(200, json=_search_response(project))
    )

    collector = FreelancerCollector(oauth_token="t", queries=["C#", ".NET"])
    leads = await collector.fetch(now - timedelta(days=1))
    assert len(leads) == 1


@pytest.mark.asyncio
@respx.mock
async def test_fetch_filters_by_since() -> None:
    now = datetime.now(timezone.utc)
    old_project = {"id": 1, "title": "Old", "submitdate": (now - timedelta(days=30)).timestamp()}
    recent_project = {"id": 2, "title": "Recent", "submitdate": now.timestamp()}
    respx.get("https://www.freelancer.com/api/projects/0.1/projects/active/").mock(
        return_value=httpx.Response(200, json=_search_response(old_project, recent_project))
    )

    collector = FreelancerCollector(oauth_token="t", queries=["C#"])
    leads = await collector.fetch(now - timedelta(days=1))
    assert [lead.external_id for lead in leads] == ["2"]


@pytest.mark.asyncio
@respx.mock
async def test_fetch_raises_on_invalid_token() -> None:
    respx.get("https://www.freelancer.com/api/projects/0.1/projects/active/").mock(
        return_value=httpx.Response(401, json={"status": "error", "message": "Invalid token"})
    )

    collector = FreelancerCollector(oauth_token="bad-token", queries=["C#"])
    with pytest.raises(SourceUnavailableError):
        await collector.fetch(datetime.now(timezone.utc) - timedelta(days=1))

    health = await collector.health()
    assert health.ok is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_stops_when_no_projects_returned() -> None:
    respx.get("https://www.freelancer.com/api/projects/0.1/projects/active/").mock(
        return_value=httpx.Response(200, json=_search_response())
    )

    collector = FreelancerCollector(oauth_token="t", queries=["C#"])
    leads = await collector.fetch(datetime.now(timezone.utc) - timedelta(days=1))
    assert leads == []
