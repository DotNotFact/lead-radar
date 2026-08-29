from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
import respx

from src.collectors.remoteok import RemoteOkCollector
from src.core.http import SourceUnavailableError


def _api_response(*jobs: dict[str, Any]) -> list[object]:
    # Первый элемент реального ответа RemoteOK - служебная запись, не вакансия.
    return [{"legal": "https://remoteok.com/legal", "0": "Legal notice"}, *jobs]


@pytest.mark.asyncio
@respx.mock
async def test_fetch_parses_jobs_and_skips_legal_notice() -> None:
    now = datetime.now(timezone.utc)
    payload = _api_response(
        {
            "id": "123",
            "position": "Senior .NET Backend Developer",
            "company": "Acme",
            "description": "<p>Looking for a <b>C# / ASP.NET Core</b> developer.</p>",
            "tags": ["dotnet", "csharp", "backend"],
            "url": "https://remoteok.com/remote-jobs/123",
            "date": now.isoformat(),
            "salary_min": 60000,
            "salary_max": 90000,
        }
    )
    respx.get("https://remoteok.com/api").mock(return_value=httpx.Response(200, json=payload))

    collector = RemoteOkCollector(queries=["dotnet", "c#"], contact_email="test@example.com")
    leads = await collector.fetch(now - timedelta(days=1))

    assert len(leads) == 1
    lead = leads[0]
    assert lead.source_id == "remoteok"
    assert lead.external_id == "123"
    assert lead.title == "Senior .NET Backend Developer"
    assert "C# / ASP.NET Core" in (lead.text or "")
    assert "<b>" not in (lead.text or "")
    assert lead.raw_budget == "от 60000 до 90000 $"

    health = await collector.health()
    assert health.ok is True


@pytest.mark.asyncio
@respx.mock
async def test_fetch_filters_out_non_matching_queries() -> None:
    now = datetime.now(timezone.utc)
    payload = _api_response(
        {
            "id": "1",
            "position": "PHP Developer",
            "description": "Laravel project",
            "tags": ["php"],
            "date": now.isoformat(),
        }
    )
    respx.get("https://remoteok.com/api").mock(return_value=httpx.Response(200, json=payload))

    collector = RemoteOkCollector(queries=["c#", ".net"])
    leads = await collector.fetch(now - timedelta(days=1))
    assert leads == []


@pytest.mark.asyncio
@respx.mock
async def test_fetch_filters_by_since() -> None:
    now = datetime.now(timezone.utc)
    old_job = {
        "id": "1",
        "position": ".NET Developer",
        "tags": ["dotnet"],
        "date": (now - timedelta(days=30)).isoformat(),
    }
    recent_job = {
        "id": "2",
        "position": ".NET Developer",
        "tags": ["dotnet"],
        "date": now.isoformat(),
    }
    respx.get("https://remoteok.com/api").mock(
        return_value=httpx.Response(200, json=_api_response(old_job, recent_job))
    )

    collector = RemoteOkCollector(queries=["dotnet"])
    leads = await collector.fetch(now - timedelta(days=1))

    assert len(leads) == 1
    assert leads[0].external_id == "2"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_raises_on_invalid_json() -> None:
    respx.get("https://remoteok.com/api").mock(return_value=httpx.Response(200, text="not json"))

    collector = RemoteOkCollector()
    with pytest.raises(SourceUnavailableError):
        await collector.fetch(datetime.now(timezone.utc) - timedelta(days=1))

    health = await collector.health()
    assert health.ok is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_raises_on_unexpected_shape() -> None:
    respx.get("https://remoteok.com/api").mock(return_value=httpx.Response(200, json={"not": "a list"}))

    collector = RemoteOkCollector()
    with pytest.raises(SourceUnavailableError):
        await collector.fetch(datetime.now(timezone.utc) - timedelta(days=1))
