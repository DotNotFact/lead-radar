from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

from scripts.collect_freelancer import collect_and_store, is_configured
from src.core import repository
from src.core.config import Settings
from src.core.db import get_connection
from src.core.yaml_config import SourceConfig, SourcesConfig, load_keywords_config

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def test_is_configured_requires_token() -> None:
    assert is_configured(Settings(_env_file=None)) is False  # type: ignore[call-arg]
    assert is_configured(Settings(_env_file=None, freelancer_oauth_token="x")) is True  # type: ignore[call-arg]


@pytest.mark.asyncio
@respx.mock
async def test_freelancer_lead_is_scored_and_stored(tmp_path: Path) -> None:
    payload = {
        "status": "success",
        "result": {
            "projects": [
                {
                    "id": 99,
                    "title": "C# / .NET Core backend fix",
                    "description": "Legacy ASP.NET Core integration, budget negotiable.",
                    "seo_url": "99/csharp-fix",
                    "submitdate": datetime.now(timezone.utc).timestamp(),
                    "budget": {"minimum": 500, "maximum": 1000, "currency": {"code": "USD"}},
                    "jobs": [{"name": "C#"}],
                }
            ],
            "total_count": 1,
        },
    }
    respx.get("https://www.freelancer.com/api/projects/0.1/projects/active/").mock(
        return_value=httpx.Response(200, json=payload)
    )

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        db_path=tmp_path / "test.db",
        contact_email="test@example.com",
        freelancer_oauth_token="secret",
    )
    sources_config = SourcesConfig(
        sources={
            "freelancer": SourceConfig.model_validate(
                {"tier": 1, "enabled": True, "poll_interval": 1800, "queries": ["C#"]}
            )
        }
    )
    keywords_config = load_keywords_config(CONFIG_DIR)

    stats = await collect_and_store(settings, sources_config, keywords_config)
    assert stats["new"] == 1

    conn = await get_connection(settings.db_path)
    lead = await repository.get_lead_by_external_id(conn, "freelancer", "99")
    await conn.close()
    assert lead is not None
    assert lead.score is not None and lead.score > 0


@pytest.mark.asyncio
async def test_freelancer_skipped_without_token(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, db_path=tmp_path / "test.db")  # type: ignore[call-arg]
    sources_config = SourcesConfig(
        sources={"freelancer": SourceConfig.model_validate({"tier": 1, "enabled": True, "poll_interval": 1800})}
    )
    keywords_config = load_keywords_config(CONFIG_DIR)

    stats = await collect_and_store(settings, sources_config, keywords_config)
    assert stats == {"new": 0, "duplicates": 0, "total": 0, "unconfigured": 1}


@pytest.mark.asyncio
async def test_freelancer_disabled_source_is_skipped(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None, db_path=tmp_path / "test.db", freelancer_oauth_token="secret"  # type: ignore[call-arg]
    )
    sources_config = SourcesConfig(
        sources={"freelancer": SourceConfig.model_validate({"tier": 1, "enabled": False, "poll_interval": 1800})}
    )
    keywords_config = load_keywords_config(CONFIG_DIR)

    stats = await collect_and_store(settings, sources_config, keywords_config)
    assert stats == {"new": 0, "duplicates": 0, "total": 0, "disabled": 1}
