from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.actions.brief import compose_daily_brief
from src.core import repository
from src.core.db import apply_migrations, get_connection

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


async def _db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    return db_path


@pytest.mark.asyncio
async def test_income_for_period_sums_only_within_range(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)

    await repository.insert_payment(conn, amount=10000, received_at=date(2026, 8, 5))
    await repository.insert_payment(conn, amount=20000, received_at=date(2026, 8, 20))
    await repository.insert_payment(conn, amount=5000, received_at=date(2026, 7, 31))  # вне периода
    await repository.insert_payment(conn, amount=7000, received_at=date(2026, 9, 1))  # вне периода

    total = await repository.get_income_for_period(conn, date(2026, 8, 1), date(2026, 9, 1))
    await conn.close()

    assert total == 30000


@pytest.mark.asyncio
async def test_income_for_period_empty_is_zero(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    total = await repository.get_income_for_period(conn, date(2026, 8, 1), date(2026, 9, 1))
    await conn.close()
    assert total == 0


@pytest.mark.asyncio
async def test_brief_shows_income_without_goal(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    today = date(2026, 8, 17)
    await repository.insert_payment(conn, amount=15000, received_at=today)

    text = await compose_daily_brief(conn, today, threshold=50)
    await conn.close()

    assert "15000" in text
    assert "цель не задана" in text


@pytest.mark.asyncio
async def test_brief_shows_income_vs_goal_percentage(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    today = date(2026, 8, 17)
    await repository.insert_payment(conn, amount=50000, received_at=today)
    await repository.set_system_state(conn, repository.MONTHLY_GOAL_KEY, "100000")

    text = await compose_daily_brief(conn, today, threshold=50)
    await conn.close()

    assert "50000 из 100000 ₽ (50%)" in text
