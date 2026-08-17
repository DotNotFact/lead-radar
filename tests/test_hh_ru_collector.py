from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from src.collectors.hh_ru import HhRuCollector
from src.core.http import SourceUnavailableError

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _make_item(item_id: int) -> dict[str, Any]:
    return {
        "id": str(item_id),
        "name": f"Разработчик C# №{item_id}",
        "salary": {"from": 50000 + item_id, "to": 90000 + item_id, "currency": "RUR", "gross": True},
        "employer": {"name": f"Company {item_id}"},
        "area": {"name": "Москва"},
        "schedule": {"name": "Удалённая работа"},
        "experience": {"name": "От 1 года до 3 лет"},
        "published_at": datetime.now(timezone.utc).isoformat(),
        "snippet": {"requirement": "Опыт C# и ASP.NET Core", "responsibility": "Доработка API"},
        "alternate_url": f"https://hh.ru/vacancy/{item_id}",
    }


@pytest.mark.asyncio
@respx.mock
async def test_fetch_paginates_and_dedupes_across_queries() -> None:
    page0_items = [_make_item(i) for i in range(100)]
    page1_items = [_make_item(i) for i in range(100, 150)]

    def responder(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "0"))
        if page == 0:
            return httpx.Response(200, json={"items": page0_items, "pages": 2, "page": 0})
        return httpx.Response(200, json={"items": page1_items, "pages": 2, "page": 1})

    respx.get("https://api.hh.ru/vacancies").mock(side_effect=responder)

    collector = HhRuCollector(
        queries=["C#", ".NET"],  # два запроса вернут одинаковые id -> дедуп внутри fetch
        contact_email="test@example.com",
    )

    since = datetime.now(timezone.utc) - timedelta(days=7)
    leads = await collector.fetch(since)

    assert len(leads) == 150  # дедуп по id сработал, несмотря на 2 запроса x 2 страницы
    assert leads[0].source_id == "hh_ru"
    assert leads[0].raw_budget is not None and "₽" in leads[0].raw_budget

    health = await collector.health()
    assert health.ok is True
    assert health.consecutive_failures == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_raises_and_marks_unhealthy_on_persistent_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.get("https://api.hh.ru/vacancies").mock(return_value=httpx.Response(500))

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("src.core.http.asyncio.sleep", _no_sleep)

    collector = HhRuCollector(queries=["C#"], contact_email="test@example.com")

    with pytest.raises(SourceUnavailableError):
        await collector.fetch(datetime.now(timezone.utc) - timedelta(days=1))

    health = await collector.health()
    assert health.ok is False
    assert health.consecutive_failures == 1
