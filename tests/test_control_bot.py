from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.control.bot import (
    cmd_brief,
    cmd_done,
    cmd_pause,
    cmd_resume,
    cmd_snooze,
    cmd_sources,
    cmd_todo,
    handle_outcome_callback,
)
from src.core import repository
from src.core.db import apply_migrations, get_connection
from src.core.models import Lead

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


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


@pytest.mark.asyncio
async def test_cmd_brief_materializes_and_sends_text(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(answer=AsyncMock())

    await cmd_brief(message, db_path=db_path, config_dir=CONFIG_DIR, score_threshold=50)

    message.answer.assert_called_once()
    text = message.answer.call_args.args[0]
    assert "Бриф на" in text


@pytest.mark.asyncio
async def test_cmd_todo_adds_action(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(text="/todo Позвонить заказчику", answer=AsyncMock())

    await cmd_todo(message, db_path=db_path)

    message.answer.assert_called_once()
    assert "Позвонить заказчику" in message.answer.call_args.args[0]

    conn = await get_connection(db_path)
    action = await repository.get_latest_action_by_title(conn, "Позвонить заказчику")
    await conn.close()
    assert action is not None
    assert action.status == "pending"


@pytest.mark.asyncio
async def test_cmd_todo_without_text_shows_usage(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(text="/todo", answer=AsyncMock())
    await cmd_todo(message, db_path=db_path)
    assert "Использование" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_done_marks_action_completed(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    conn = await get_connection(db_path)
    action_id = await repository.insert_action(conn, title="Тест", priority=2, due_date=None)
    await conn.close()

    message = SimpleNamespace(text=f"/done {action_id}", answer=AsyncMock())
    await cmd_done(message, db_path=db_path)

    conn = await get_connection(db_path)
    action = await repository.get_latest_action_by_title(conn, "Тест")
    await conn.close()
    assert action is not None
    assert action.status == "done"
    assert action.completed_at is not None


@pytest.mark.asyncio
async def test_cmd_snooze_pushes_due_date_and_increments_count(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    conn = await get_connection(db_path)
    from datetime import date

    action_id = await repository.insert_action(
        conn, title="Тест снуза", priority=2, due_date=date(2026, 8, 1)
    )
    await conn.close()

    message = SimpleNamespace(text=f"/snooze {action_id} 5", answer=AsyncMock())
    await cmd_snooze(message, db_path=db_path)

    conn = await get_connection(db_path)
    action = await repository.get_latest_action_by_title(conn, "Тест снуза")
    await conn.close()
    assert action is not None
    assert action.snooze_count == 1
    assert action.due_date is not None and action.due_date > date(2026, 8, 1)


@pytest.mark.asyncio
async def test_cmd_snooze_rejects_bad_args(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(text="/snooze abc", answer=AsyncMock())
    await cmd_snooze(message, db_path=db_path)
    assert "Использование" in message.answer.call_args.args[0]
