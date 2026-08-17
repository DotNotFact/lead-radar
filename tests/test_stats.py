from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from src.core import repository
from src.core.db import apply_migrations, get_connection
from src.core.models import Lead
from src.export.stats import format_stats_message

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


@pytest.mark.asyncio
async def test_source_conversion_stats(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    conn = await get_connection(db_path)
    await repository.ensure_source(conn, "hh_ru", 1)
    now = datetime.now(timezone.utc)

    await repository.insert_lead(
        conn, Lead(source_id="hh_ru", external_id="1", score=90, collected_at=now)
    )
    lead1 = await repository.get_lead_by_external_id(conn, "hh_ru", "1")
    assert lead1 is not None and lead1.id is not None
    await repository.record_notified(conn, lead1.id)
    await repository.record_outcome(conn, lead1.id, "won")

    await repository.insert_lead(
        conn, Lead(source_id="hh_ru", external_id="2", score=10, collected_at=now)
    )

    since = now - timedelta(days=1)
    stats = await repository.get_source_conversion_stats(conn, since)
    await conn.close()

    assert len(stats) == 1
    assert stats[0]["source_id"] == "hh_ru"
    assert stats[0]["collected"] == 2
    assert stats[0]["notified"] == 1
    assert stats[0]["won"] == 1


@pytest.mark.asyncio
async def test_source_conversion_stats_excludes_duplicates(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    conn = await get_connection(db_path)
    await repository.ensure_source(conn, "telegram", 1)
    now = datetime.now(timezone.utc)

    await repository.insert_lead(
        conn, Lead(source_id="telegram", external_id="1", score=50, collected_at=now)
    )
    await repository.insert_lead(
        conn, Lead(source_id="telegram", external_id="2", score=50, duplicate_of=1, collected_at=now)
    )

    stats = await repository.get_source_conversion_stats(conn, now - timedelta(days=1))
    await conn.close()

    assert stats[0]["collected"] == 1


@pytest.mark.asyncio
async def test_budget_distribution_buckets(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    conn = await get_connection(db_path)
    await repository.ensure_source(conn, "hh_ru", 1)
    now = datetime.now(timezone.utc)

    budgets = [3000, 8000, 20000, 50000, 150000]
    for i, budget in enumerate(budgets):
        await repository.insert_lead(
            conn,
            Lead(
                source_id="hh_ru",
                external_id=str(i),
                budget_max=budget,
                collected_at=now,
            ),
        )

    distribution = await repository.get_budget_distribution(conn, now - timedelta(days=1))
    await conn.close()

    counts = {(b["low"], b["high"]): b["count"] for b in distribution}
    assert counts[(0, 5000)] == 1
    assert counts[(5000, 10000)] == 1
    assert counts[(10000, 30000)] == 1
    assert counts[(30000, 100000)] == 1
    assert counts[(100000, None)] == 1


def test_format_stats_message_renders_sections() -> None:
    conversion: list[dict[str, Any]] = [
        {"source_id": "hh_ru", "collected": 10, "notified": 5, "replied": 2, "won": 1}
    ]
    budgets: list[dict[str, Any]] = [
        {"low": 0, "high": 5000, "count": 3},
        {"low": 100000, "high": None, "count": 1},
    ]

    text = format_stats_message("7 дн.", conversion, budgets)

    assert "hh_ru" in text
    assert "10 / 5 / 2 / 1" in text
    assert "100000+" in text
