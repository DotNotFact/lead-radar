from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.core import repository
from src.core.db import apply_migrations, get_connection
from src.core.models import Lead
from src.export.exporter import export_leads, fetch_export_rows

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


async def _seed(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    conn = await get_connection(db_path)
    await repository.ensure_source(conn, "hh_ru", 1)
    await repository.insert_lead(
        conn,
        Lead(
            source_id="hh_ru",
            external_id="1",
            title="Доработать API",
            text="Звоните +7 999 111-22-33 или пишите на customer@example.com",
            author_handle="@some_customer",
            score=80,
            budget_min=20000,
            budget_max=30000,
            budget_currency="RUB",
            stack_tags=["c#", ".net"],
            collected_at=datetime.now(timezone.utc),
        ),
    )
    # дубликат кросспоста - не должен попасть в экспорт
    await repository.insert_lead(
        conn,
        Lead(
            source_id="hh_ru",
            external_id="2",
            title="Дубликат",
            score=10,
            duplicate_of=1,
            collected_at=datetime.now(timezone.utc),
        ),
    )
    await conn.close()
    return db_path


@pytest.mark.asyncio
async def test_export_rows_exclude_pii_and_duplicates(tmp_path: Path) -> None:
    db_path = await _seed(tmp_path)
    conn = await get_connection(db_path)
    rows = await fetch_export_rows(conn, days=30)
    await conn.close()

    assert len(rows) == 1  # дубликат исключён
    row = rows[0]
    assert "author_handle" not in row
    assert "external_id" not in row
    assert "+7" not in (row["text"] or "")
    assert "customer@example.com" not in (row["text"] or "")
    assert row["budget_min"] == 20000


@pytest.mark.asyncio
async def test_export_csv_is_well_formed(tmp_path: Path) -> None:
    db_path = await _seed(tmp_path)
    conn = await get_connection(db_path)
    content = await export_leads(conn, days=30, fmt="csv")
    await conn.close()

    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["source_id"] == "hh_ru"
    assert "999" not in rows[0]["text"]


@pytest.mark.asyncio
async def test_export_jsonl_is_well_formed(tmp_path: Path) -> None:
    db_path = await _seed(tmp_path)
    conn = await get_connection(db_path)
    content = await export_leads(conn, days=30, fmt="jsonl")
    await conn.close()

    lines = content.decode("utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["source_id"] == "hh_ru"
    assert "author_handle" not in record


@pytest.mark.asyncio
async def test_export_excludes_leads_outside_window(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    conn = await get_connection(db_path)
    await repository.ensure_source(conn, "hh_ru", 1)
    await repository.insert_lead(
        conn,
        Lead(
            source_id="hh_ru",
            external_id="old",
            title="Старый лид",
            collected_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        ),
    )
    rows = await fetch_export_rows(conn, days=30)
    await conn.close()
    assert rows == []
