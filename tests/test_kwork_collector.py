from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest
import respx

from src.collectors.kwork import KworkCatalogCollector, KworkProjectsCollector
from src.core.http import SourceUnavailableError


def _projects_html(items: list[dict[str, object]]) -> str:
    state = {"wantsListData": {"pagination": {"data": items}}}
    return f"<html><script>window.stateData={json.dumps(state)};</script></html>"


def _catalog_html(items: list[dict[str, object]]) -> str:
    state = {"viewData": {"kworks": {"posts": {"data": items}}}}
    return f"<html><script>window.stateData={json.dumps(state)};</script></html>"


def _project_item(item_id: int, **overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "id": item_id,
        "name": "Доработать API на .NET Core",
        "description": "Нужно доработать интеграцию с эквайрингом",
        "priceLimit": "20000.00",
        "possiblePriceLimit": 30000,
        "category_id": "272",
        "max_days": "5",
        "date_create": "2026-08-17 12:00:00",
        "user": {"username": "some_customer"},
    }
    item.update(overrides)
    return item


def _catalog_item(item_id: int, **overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "id": item_id,
        "url": f"/website-repair/{item_id}/dorabotka",
        "gtitle": "Доработка сайта на WordPress",
        "userName": "some_seller",
        "price": 1000,
        "sellerLevel": 3,
        "days": 2,
        "userRatingCount": "432",
        "categoryTitle": "Доработка и настройка сайта",
    }
    item.update(overrides)
    return item


@pytest.mark.asyncio
@respx.mock
async def test_projects_collector_parses_items() -> None:
    html = _projects_html([_project_item(1), _project_item(2, user={"username": None})])
    respx.get("https://kwork.ru/projects").mock(return_value=httpx.Response(200, text=html))

    collector = KworkProjectsCollector(contact_email="test@example.com")
    leads = await collector.fetch(datetime.now(timezone.utc))

    assert len(leads) == 2
    assert leads[0].source_id == "kwork_projects"
    assert leads[0].external_id == "1"
    assert leads[0].url == "https://kwork.ru/projects/1"
    assert leads[0].author_handle == "@some_customer"
    assert "20000.00" in (leads[0].raw_budget or "")
    assert "30000" in (leads[0].raw_budget or "")
    assert leads[1].author_handle is None

    health = await collector.health()
    assert health.ok is True


@pytest.mark.asyncio
@respx.mock
async def test_projects_collector_raises_when_state_marker_missing() -> None:
    respx.get("https://kwork.ru/projects").mock(
        return_value=httpx.Response(200, text="<html>no state here</html>")
    )
    collector = KworkProjectsCollector()

    with pytest.raises(SourceUnavailableError):
        await collector.fetch(datetime.now(timezone.utc))

    health = await collector.health()
    assert health.ok is False
    assert health.consecutive_failures == 1


@pytest.mark.asyncio
@respx.mock
async def test_projects_collector_raises_when_structure_changed() -> None:
    html = "<html><script>window.stateData={\"somethingElse\": true};</script></html>"
    respx.get("https://kwork.ru/projects").mock(return_value=httpx.Response(200, text=html))
    collector = KworkProjectsCollector()

    with pytest.raises(SourceUnavailableError, match="структура"):
        await collector.fetch(datetime.now(timezone.utc))


@pytest.mark.asyncio
@respx.mock
async def test_catalog_collector_aggregates_across_categories(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("src.collectors.kwork.asyncio.sleep", _no_sleep)

    url_a = "https://kwork.ru/categories/a"
    url_b = "https://kwork.ru/categories/b"
    respx.get(url_a).mock(return_value=httpx.Response(200, text=_catalog_html([_catalog_item(1)])))
    respx.get(url_b).mock(return_value=httpx.Response(200, text=_catalog_html([_catalog_item(2)])))

    collector = KworkCatalogCollector(category_urls=[url_a, url_b], contact_email="test@example.com")
    leads = await collector.fetch(datetime.now(timezone.utc))

    assert len(leads) == 2
    assert {lead.external_id for lead in leads} == {"1", "2"}
    assert leads[0].meta["kind"] == "market_intelligence"
    assert leads[0].published_at is None  # каталог не даёт даты публикации


@pytest.mark.asyncio
@respx.mock
async def test_catalog_collector_survives_partial_category_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("src.collectors.kwork.asyncio.sleep", _no_sleep)

    url_ok = "https://kwork.ru/categories/ok"
    url_broken = "https://kwork.ru/categories/broken"
    respx.get(url_ok).mock(return_value=httpx.Response(200, text=_catalog_html([_catalog_item(1)])))
    respx.get(url_broken).mock(return_value=httpx.Response(200, text="<html>broken</html>"))

    collector = KworkCatalogCollector(category_urls=[url_broken, url_ok])
    leads = await collector.fetch(datetime.now(timezone.utc))

    assert len(leads) == 1
    health = await collector.health()
    assert health.ok is True  # не все категории упали - источник не деградирует целиком


@pytest.mark.asyncio
@respx.mock
async def test_catalog_collector_raises_when_all_categories_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("src.collectors.kwork.asyncio.sleep", _no_sleep)
    monkeypatch.setattr("src.core.http.asyncio.sleep", _no_sleep)

    url_a = "https://kwork.ru/categories/a"
    respx.get(url_a).mock(return_value=httpx.Response(500))

    collector = KworkCatalogCollector(category_urls=[url_a])

    with pytest.raises(SourceUnavailableError):
        await collector.fetch(datetime.now(timezone.utc))
