from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.actions.brief import ESCALATION_THRESHOLD, compose_daily_brief
from src.core import repository
from src.core.db import apply_migrations, get_connection
from src.core.models import Lead

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


async def _db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    return db_path


@pytest.mark.asyncio
async def test_brief_lists_today_and_overdue_actions(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    today = date(2026, 8, 17)

    await repository.insert_action(conn, title="Написать заказчикам", priority=2, due_date=today)
    await repository.insert_action(
        conn, title="Обновить резюме", priority=1, due_date=date(2026, 8, 10)
    )

    text = await compose_daily_brief(conn, today, threshold=50)
    await conn.close()

    assert "Написать заказчикам" in text
    assert "Обновить резюме" in text
    assert "Действия на сегодня" in text
    assert "Просроченное" in text


@pytest.mark.asyncio
async def test_brief_escalates_action_snoozed_three_plus_times(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    today = date(2026, 8, 17)

    action_id = await repository.insert_action(
        conn,
        title="Поднять резюме",
        priority=2,
        due_date=date(2026, 8, 1),
        expected_value="Поднимает видимость в поиске рекрутёров",
    )
    for _ in range(ESCALATION_THRESHOLD):
        await repository.snooze_action(conn, action_id, days=1)

    # snooze двигает due_date вперёд, но с учётом max(due_date, today) - подвинем обратно в прошлое
    await conn.execute("UPDATE actions SET due_date = ? WHERE id = ?", ("2026-08-01", action_id))
    await conn.commit()

    text = await compose_daily_brief(conn, today, threshold=50)
    await conn.close()

    assert "🔴" in text
    assert "Поднимает видимость в поиске рекрутёров" in text


@pytest.mark.asyncio
async def test_brief_shows_no_actions_message_when_empty(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    text = await compose_daily_brief(conn, date(2026, 8, 17), threshold=50)
    await conn.close()
    assert "На сегодня действий нет" in text


@pytest.mark.asyncio
async def test_brief_includes_daily_stats_and_source_health(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    today = date(2026, 8, 17)

    await repository.ensure_source(conn, "hh_ru", 1)
    await repository.mark_source_failed(conn, "hh_ru", "403 forbidden")

    lead = Lead(
        source_id="hh_ru",
        external_id="1",
        score=90,
        collected_at=datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc),
    )
    await repository.insert_lead(conn, lead)

    text = await compose_daily_brief(conn, today, threshold=50)
    await conn.close()

    assert "собрано лидов: 1" in text
    assert "прошло порог" in text
    assert "лучший источник: hh_ru" in text
    assert "403 forbidden" in text
