from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from src.core.db import apply_migrations

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"

EXPECTED_TABLES = {
    "sources", "leads", "lead_outcomes", "actions", "schema_migrations", "system_state",
    "companies", "payments", "hh_applications",
}


@pytest.mark.asyncio
async def test_migrations_apply_and_are_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"

    applied_first = await apply_migrations(db_path, MIGRATIONS_DIR)
    assert applied_first == sorted(applied_first)  # применяются по порядку имён файлов
    assert set(applied_first) == {
        "0001_init", "0002_system_state", "0003_crm_income", "0004_hh_applications",
        "0005_ai_assistable",
    }

    applied_second = await apply_migrations(db_path, MIGRATIONS_DIR)
    assert applied_second == []

    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        rows = await cursor.fetchall()
        table_names = {row[0] for row in rows}

    assert EXPECTED_TABLES.issubset(table_names)


@pytest.mark.asyncio
async def test_indexes_created(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)

    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        rows = await cursor.fetchall()
        index_names = {row[0] for row in rows}

    assert "idx_leads_published_at" in index_names
    assert "idx_actions_status_due" in index_names
