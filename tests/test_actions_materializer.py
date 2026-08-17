from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.actions.materializer import materialize_due_actions
from src.core import repository
from src.core.db import apply_migrations, get_connection
from src.core.yaml_config import (
    ActionsConfig,
    OneOffActionTemplate,
    RecurringActionTemplate,
    SeasonalActionTemplate,
)

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


async def _db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    return db_path


@pytest.mark.asyncio
async def test_recurring_action_created_when_none_exists(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    config = ActionsConfig(
        recurring=[RecurringActionTemplate(title="Проверить Avito", recurrence="daily", priority=2)]
    )

    created = await materialize_due_actions(conn, config, date(2026, 8, 17))
    await conn.close()

    assert created == 1


@pytest.mark.asyncio
async def test_recurring_action_not_duplicated_while_still_pending(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    config = ActionsConfig(
        recurring=[RecurringActionTemplate(title="Проверить Avito", recurrence="daily", priority=2)]
    )

    await materialize_due_actions(conn, config, date(2026, 8, 17))
    created_second_run = await materialize_due_actions(conn, config, date(2026, 8, 17))
    await conn.close()

    assert created_second_run == 0


@pytest.mark.asyncio
async def test_recurring_action_recreated_after_interval_once_done(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    config = ActionsConfig(
        recurring=[
            RecurringActionTemplate(title="Поднять объявление", recurrence="every_3_days", priority=3)
        ]
    )

    await materialize_due_actions(conn, config, date(2026, 8, 17))
    latest = await repository.get_latest_action_by_title(conn, "Поднять объявление")
    assert latest is not None
    completed_at = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    await repository.mark_action_done(conn, latest.id, completed_at=completed_at)  # type: ignore[arg-type]

    too_soon = await materialize_due_actions(conn, config, date(2026, 8, 18))
    assert too_soon == 0

    after_interval = await materialize_due_actions(conn, config, date(2026, 8, 20))
    await conn.close()
    assert after_interval == 1


@pytest.mark.asyncio
async def test_seasonal_action_created_once_per_year(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    config = ActionsConfig(
        seasonal=[
            SeasonalActionTemplate(title="Переписать объявление под пересдачи", activate_on="08-25", priority=2)
        ]
    )

    not_yet = await materialize_due_actions(conn, config, date(2026, 8, 17))
    assert not_yet == 0

    on_date = await materialize_due_actions(conn, config, date(2026, 8, 25))
    assert on_date == 1

    same_day_again = await materialize_due_actions(conn, config, date(2026, 8, 25))
    await conn.close()
    assert same_day_again == 0


@pytest.mark.asyncio
async def test_one_off_action_created_only_once_ever(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    config = ActionsConfig(
        one_off=[OneOffActionTemplate(title="Заполнить анкету репетитора", priority=3)]
    )

    first = await materialize_due_actions(conn, config, date(2026, 8, 17))
    second = await materialize_due_actions(conn, config, date(2026, 9, 1))
    await conn.close()

    assert first == 1
    assert second == 0
