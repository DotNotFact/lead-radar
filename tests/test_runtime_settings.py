from __future__ import annotations

from pathlib import Path

import pytest

from src.core import repository, runtime_settings
from src.core.config import Settings
from src.core.db import apply_migrations, get_connection
from src.core.models import RawLead
from src.core.pipeline import score_and_store_lead
from src.core.yaml_config import load_keywords_config

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


async def _db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    return db_path


@pytest.mark.asyncio
async def test_score_threshold_falls_back_to_settings_default(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    settings = Settings(_env_file=None, score_threshold=42)  # type: ignore[call-arg]

    value = await runtime_settings.get_score_threshold(conn, settings)
    await conn.close()
    assert value == 42.0


@pytest.mark.asyncio
async def test_set_score_threshold_overrides_default(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    settings = Settings(_env_file=None, score_threshold=42)  # type: ignore[call-arg]

    await runtime_settings.set_score_threshold(conn, 77)
    value = await runtime_settings.get_score_threshold(conn, settings)
    await conn.close()
    assert value == 77.0


@pytest.mark.asyncio
async def test_min_budget_override_falls_back_to_keywords_yaml(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    keywords_config = load_keywords_config(CONFIG_DIR)

    value = await runtime_settings.get_min_budget_rub(conn, keywords_config)
    await conn.close()
    assert value == keywords_config.budget_parsing.min_budget_rub


@pytest.mark.asyncio
async def test_apply_min_budget_override_changes_scoring_outcome(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    keywords_config = load_keywords_config(CONFIG_DIR)

    await repository.ensure_source(conn, "hh_ru", 1)

    # бюджет 8000 при дефолтном пороге 5000 не должен штрафоваться "below_budget_floor"
    raw = RawLead(
        source_id="hh_ru", external_id="1", title="Доработать", text="бюджет 8000 руб",
        raw_budget="8000 руб",
    )
    await score_and_store_lead(conn, raw, keywords_config)

    lead_before = await repository.get_lead_by_external_id(conn, "hh_ru", "1")
    assert lead_before is not None

    # поднимаем порог до 10000 - теперь тот же бюджет должен штрафоваться
    await runtime_settings.set_min_budget_rub(conn, 10000)
    raw2 = RawLead(
        source_id="hh_ru", external_id="2", title="Доработать2", text="бюджет 8000 руб",
        raw_budget="8000 руб",
    )
    await score_and_store_lead(conn, raw2, keywords_config)
    lead_after = await repository.get_lead_by_external_id(conn, "hh_ru", "2")
    await conn.close()

    assert lead_after is not None
    assert (lead_after.score or 0) < (lead_before.score or 0)


@pytest.mark.asyncio
async def test_daily_brief_time_falls_back_and_can_be_overridden(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    settings = Settings(_env_file=None, daily_brief_time="09:00")  # type: ignore[call-arg]

    assert await runtime_settings.get_daily_brief_time(conn, settings) == "09:00"

    await runtime_settings.set_daily_brief_time(conn, "14:30")
    value = await runtime_settings.get_daily_brief_time(conn, settings)
    await conn.close()
    assert value == "14:30"


@pytest.mark.asyncio
async def test_source_enabled_falls_back_to_default_when_no_override(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)

    assert await runtime_settings.get_source_enabled(conn, "hh_ru", default=True) is True
    assert await runtime_settings.get_source_enabled(conn, "freelancer", default=False) is False
    await conn.close()


@pytest.mark.asyncio
async def test_set_source_enabled_overrides_default_independently_per_source(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)

    await runtime_settings.set_source_enabled(conn, "hh_ru", False)
    assert await runtime_settings.get_source_enabled(conn, "hh_ru", default=True) is False
    # другой источник не затронут
    assert await runtime_settings.get_source_enabled(conn, "remoteok", default=True) is True

    await runtime_settings.set_source_enabled(conn, "hh_ru", True)
    assert await runtime_settings.get_source_enabled(conn, "hh_ru", default=True) is True
    await conn.close()
