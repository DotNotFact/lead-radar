from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import httpx
import pytest
import respx

from scripts.collect_hh import collect_and_store
from src.core.config import Settings
from src.core.yaml_config import SourceConfig, SourcesConfig, load_keywords_config

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _make_item(item_id: int) -> dict[str, Any]:
    return {
        "id": str(item_id),
        "name": f"Backend разработчик C# №{item_id}",
        "salary": {"from": 60000 + item_id, "to": 100000 + item_id, "currency": "RUR", "gross": True},
        "employer": {"name": "Company"},
        "area": {"name": "Москва"},
        "schedule": {"name": "Удалённая работа"},
        "experience": {"name": "От 1 года до 3 лет"},
        "published_at": datetime.now(timezone.utc).isoformat(),
        "snippet": {
            "requirement": "Опыт C# и ASP.NET Core",
            "responsibility": "Доработка API, интеграция с эквайрингом",
        },
        "alternate_url": f"https://hh.ru/vacancy/{item_id}",
    }


@pytest.mark.asyncio
@respx.mock
async def test_full_pipeline_persists_100_plus_leads_with_parsed_budget(tmp_path: Path) -> None:
    """Замена живого гейта Фазы 1 (api.hh.ru недоступен из песочницы, см. чат): те же
    объём и форма данных, что и в реальном ответе API, проходят через весь конвейер -
    сбор -> парсинг бюджета -> скоринг -> дедуп -> запись в БД."""
    items_page0 = [_make_item(i) for i in range(100)]
    items_page1 = [_make_item(i) for i in range(100, 130)]

    def search_responder(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "0"))
        if page == 0:
            return httpx.Response(200, json={"items": items_page0, "pages": 2, "page": 0})
        return httpx.Response(200, json={"items": items_page1, "pages": 2, "page": 1})

    respx.get("https://api.hh.ru/vacancies").mock(side_effect=search_responder)
    respx.get(url__regex=r"https://api\.hh\.ru/vacancies/\d+$").mock(
        return_value=httpx.Response(
            200,
            json={
                "description": "<p>Полное описание вакансии, стек C# и ASP.NET Core.</p>",
                "key_skills": [{"name": "C#"}, {"name": "ASP.NET Core"}],
            },
        )
    )

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        db_path=tmp_path / "test.db",
        contact_email="test@example.com",
    )
    sources_config = SourcesConfig(
        sources={
            "hh_ru": SourceConfig.model_validate(
                {
                    "tier": 1,
                    "enabled": True,
                    "poll_interval": 300,
                    "queries": ["C#"],
                    "remote_only": True,
                    "fetch_full_description": True,
                    "initial_lookback_days": 7,
                }
            )
        }
    )
    keywords_config = load_keywords_config(CONFIG_DIR)

    stats = await collect_and_store(settings, sources_config, keywords_config)

    assert "error" not in stats
    assert stats["new"] >= 100
    assert stats["total"] == stats["new"]

    async with aiosqlite.connect(settings.db_path) as conn:
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM leads WHERE budget_min IS NOT NULL AND source_id = 'hh_ru'"
        )
        row = await cursor.fetchone()
        with_budget = row[0] if row else 0

    assert with_budget >= 100


@pytest.mark.asyncio
@respx.mock
async def test_second_run_only_inserts_new_leads(tmp_path: Path) -> None:
    items = [_make_item(i) for i in range(5)]
    respx.get("https://api.hh.ru/vacancies").mock(
        return_value=httpx.Response(200, json={"items": items, "pages": 1, "page": 0})
    )
    respx.get(url__regex=r"https://api\.hh\.ru/vacancies/\d+$").mock(
        return_value=httpx.Response(200, json={"description": "<p>Текст</p>", "key_skills": []})
    )

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        db_path=tmp_path / "test.db",
        contact_email="test@example.com",
    )
    sources_config = SourcesConfig(
        sources={
            "hh_ru": SourceConfig.model_validate(
                {"tier": 1, "enabled": True, "poll_interval": 300, "queries": ["C#"]}
            )
        }
    )
    keywords_config = load_keywords_config(CONFIG_DIR)

    first = await collect_and_store(settings, sources_config, keywords_config)
    second = await collect_and_store(settings, sources_config, keywords_config)

    assert first["new"] == 5
    assert second["new"] == 0
    assert second["duplicates"] == 5
