from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

from scripts.collect_remoteok import collect_and_store
from src.core import repository
from src.core.config import Settings
from src.core.db import get_connection
from src.core.yaml_config import SourceConfig, SourcesConfig, load_keywords_config

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _api_response() -> list[object]:
    return [
        {"legal": "https://remoteok.com/legal"},
        {
            "id": "42",
            "position": "C# / .NET Backend Developer",
            "company": "Acme",
            "description": "Remote C# / ASP.NET Core role, legacy integration work.",
            "tags": ["dotnet", "csharp"],
            "url": "https://remoteok.com/remote-jobs/42",
            "date": datetime.now(timezone.utc).isoformat(),
            "salary_min": 70000,
            "salary_max": 100000,
        },
    ]


@pytest.mark.asyncio
@respx.mock
async def test_remoteok_lead_is_scored_and_stored(tmp_path: Path) -> None:
    respx.get("https://remoteok.com/api").mock(return_value=httpx.Response(200, json=_api_response()))

    settings = Settings(
        _env_file=None, db_path=tmp_path / "test.db", contact_email="test@example.com"  # type: ignore[call-arg]
    )
    sources_config = SourcesConfig(
        sources={
            "remoteok": SourceConfig.model_validate(
                {"tier": 1, "enabled": True, "poll_interval": 1800, "queries": ["dotnet", "c#"]}
            )
        }
    )
    keywords_config = load_keywords_config(CONFIG_DIR)

    stats = await collect_and_store(settings, sources_config, keywords_config)
    assert stats["new"] == 1

    conn = await get_connection(settings.db_path)
    lead = await repository.get_lead_by_external_id(conn, "remoteok", "42")
    await conn.close()

    assert lead is not None
    assert lead.score is not None and lead.score > 0
    assert lead.budget_currency == "USD"


@pytest.mark.asyncio
async def test_remoteok_disabled_source_is_skipped(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, db_path=tmp_path / "test.db")  # type: ignore[call-arg]
    sources_config = SourcesConfig(
        sources={"remoteok": SourceConfig.model_validate({"tier": 1, "enabled": False, "poll_interval": 1800})}
    )
    keywords_config = load_keywords_config(CONFIG_DIR)

    stats = await collect_and_store(settings, sources_config, keywords_config)
    assert stats == {"new": 0, "duplicates": 0, "total": 0, "disabled": 1}
