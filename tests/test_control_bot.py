from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.control.bot import cmd_pause, cmd_resume, cmd_sources, handle_outcome_callback
from src.core import repository
from src.core.db import apply_migrations, get_connection
from src.core.models import Lead

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


async def _seed_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    return db_path


@pytest.mark.asyncio
async def test_cmd_sources_reports_health(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    conn = await get_connection(db_path)
    await repository.ensure_source(conn, "hh_ru", 1)
    await repository.mark_source_failed(conn, "hh_ru", "boom")
    await conn.close()

    message = SimpleNamespace(answer=AsyncMock())
    await cmd_sources(message, db_path=db_path)

    message.answer.assert_called_once()
    text = message.answer.call_args.args[0]
    assert "hh_ru" in text
    assert "🔴" in text


@pytest.mark.asyncio
async def test_cmd_pause_and_resume_toggle_state(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)

    message = SimpleNamespace(answer=AsyncMock())
    await cmd_pause(message, db_path=db_path)

    conn = await get_connection(db_path)
    state = await repository.get_system_state(conn, "collecting_paused")
    await conn.close()
    assert state == "1"

    await cmd_resume(message, db_path=db_path)

    conn = await get_connection(db_path)
    state = await repository.get_system_state(conn, "collecting_paused")
    await conn.close()
    assert state == "0"


@pytest.mark.asyncio
async def test_outcome_callback_records_and_answers(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    conn = await get_connection(db_path)
    await repository.ensure_source(conn, "hh_ru", 1)
    await repository.insert_lead(conn, Lead(source_id="hh_ru", external_id="1", score=90))
    lead = await repository.get_lead_by_external_id(conn, "hh_ru", "1")
    await conn.close()
    assert lead is not None and lead.id is not None

    callback_message = SimpleNamespace(edit_reply_markup=AsyncMock())
    callback = SimpleNamespace(
        data=f"outcome:replied:{lead.id}", answer=AsyncMock(), message=callback_message
    )

    await handle_outcome_callback(callback, db_path=db_path)

    callback.answer.assert_called_once()
    callback_message.edit_reply_markup.assert_called_once()

    conn = await get_connection(db_path)
    outcome = await repository.get_outcome(conn, lead.id)
    await conn.close()
    assert outcome is not None
    assert outcome.outcome == "replied"
    assert outcome.replied_at is not None


@pytest.mark.asyncio
async def test_outcome_callback_rejects_malformed_data(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    callback = SimpleNamespace(data="garbage", answer=AsyncMock(), message=None)

    await handle_outcome_callback(callback, db_path=db_path)

    callback.answer.assert_called_once()
    assert "Некорректные" in callback.answer.call_args.args[0]
