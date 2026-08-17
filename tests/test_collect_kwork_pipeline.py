from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

from scripts.collect_kwork import collect_kwork_catalog, collect_kwork_projects
from src.core import repository
from src.core.config import Settings
from src.core.db import get_connection
from src.core.yaml_config import SourceConfig, SourcesConfig, load_keywords_config

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _projects_html() -> str:
    state = {
        "wantsListData": {
            "pagination": {
                "data": [
                    {
                        "id": 1,
                        "name": "Доработать API на .NET Core, нужна интеграция с эквайрингом",
                        "description": (
                            "Нужно доработать интеграцию с эквайрингом на ASP.NET Core, "
                            "легаси, бюджет 25000 руб, пишите @customer1"
                        ),
                        "priceLimit": "25000.00",
                        "possiblePriceLimit": 35000,
                        "category_id": "272",
                        "max_days": "5",
                        "date_create": "2026-08-17 12:00:00",
                        "user": {"username": "customer1"},
                    }
                ]
            }
        }
    }
    return f"<html><script>window.stateData={json.dumps(state)};</script></html>"


def _catalog_html() -> str:
    state = {
        "viewData": {
          "kworks": {
            "posts": {
                "data": [
                    {
                        "id": 501,
                        "url": "/website-repair/501/dorabotka",
                        "gtitle": "Доработка сайта на 1С Битрикс",
                        "userName": "seller1",
                        "price": 1000,
                        "sellerLevel": 3,
                        "days": 2,
                        "userRatingCount": "432",
                        "categoryTitle": "Доработка и настройка сайта",
                    }
                ]
            }
          }
        }
    }
    return f"<html><script>window.stateData={json.dumps(state)};</script></html>"


@pytest.mark.asyncio
@respx.mock
async def test_projects_lead_is_scored_and_notifiable(tmp_path: Path) -> None:
    respx.get("https://kwork.ru/projects").mock(
        return_value=httpx.Response(200, text=_projects_html())
    )

    settings = Settings(
        _env_file=None, db_path=tmp_path / "test.db", contact_email="test@example.com"  # type: ignore[call-arg]
    )
    sources_config = SourcesConfig(
        sources={"kwork_projects": SourceConfig.model_validate({"tier": 2, "enabled": True, "poll_interval": 900})}
    )
    keywords_config = load_keywords_config(CONFIG_DIR)

    stats = await collect_kwork_projects(settings, sources_config, keywords_config)
    assert stats["new"] == 1

    conn = await get_connection(settings.db_path)
    lead = await repository.get_lead_by_external_id(conn, "kwork_projects", "1")
    assert lead is not None
    assert lead.score is not None and lead.score > 0

    unnotified = await repository.get_unnotified_leads_above_threshold(conn, threshold=1)
    await conn.close()
    assert len(unnotified) == 1  # реальный лид - кандидат на уведомление


@pytest.mark.asyncio
@respx.mock
async def test_catalog_lead_has_no_score_and_is_never_notified(tmp_path: Path) -> None:
    respx.get("https://kwork.ru/categories/a").mock(
        return_value=httpx.Response(200, text=_catalog_html())
    )

    settings = Settings(
        _env_file=None, db_path=tmp_path / "test.db", contact_email="test@example.com"  # type: ignore[call-arg]
    )
    sources_config = SourcesConfig(
        sources={
            "kwork_catalog": SourceConfig.model_validate(
                {
                    "tier": 2,
                    "enabled": True,
                    "poll_interval": 86400,
                    "categories": ["https://kwork.ru/categories/a"],
                }
            )
        }
    )

    stats = await collect_kwork_catalog(settings, sources_config)
    assert stats["new"] == 1

    conn = await get_connection(settings.db_path)
    lead = await repository.get_lead_by_external_id(conn, "kwork_catalog", "501")
    assert lead is not None
    assert lead.score is None

    # даже с порогом 0 (или отрицательным) NULL-score никогда не пройдёт "score >= threshold"
    unnotified = await repository.get_unnotified_leads_above_threshold(conn, threshold=-1000)
    await conn.close()
    assert unnotified == []
