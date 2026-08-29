from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.control.bot import (
    cmd_ai_leads,
    cmd_brief,
    cmd_crm,
    cmd_crm_add,
    cmd_crm_status,
    cmd_crm_touch,
    cmd_done,
    cmd_export,
    cmd_export_ai,
    cmd_goal,
    cmd_hh_status,
    cmd_income,
    cmd_pause,
    cmd_resume,
    cmd_set_brief_time,
    cmd_set_budget_floor,
    cmd_set_threshold,
    cmd_settings,
    cmd_snooze,
    cmd_sources,
    cmd_stats,
    cmd_todo,
    handle_outcome_callback,
)
from src.core import repository
from src.core.config import Settings
from src.core.db import apply_migrations, get_connection
from src.core.models import HhApplication, Lead

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

    await cmd_brief(message, db_path=db_path, config_dir=CONFIG_DIR, settings=Settings(_env_file=None, score_threshold=50))  # type: ignore[call-arg]

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


@pytest.mark.asyncio
async def test_cmd_ai_leads_reports_no_leads_when_empty(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(answer=AsyncMock())
    await cmd_ai_leads(message, db_path=db_path)
    assert "нет лидов" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_ai_leads_lists_only_flagged_leads(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    conn = await get_connection(db_path)
    await repository.ensure_source(conn, "hh_ru", 1)
    await repository.insert_lead(
        conn,
        Lead(source_id="hh_ru", external_id="1", title="Простой парсер", ai_assistable=True),
    )
    await repository.insert_lead(
        conn,
        Lead(source_id="hh_ru", external_id="2", title="Сложный проект", ai_assistable=False),
    )
    await conn.close()

    message = SimpleNamespace(answer=AsyncMock())
    await cmd_ai_leads(message, db_path=db_path)

    text = message.answer.call_args.args[0]
    assert "Простой парсер" in text
    assert "Сложный проект" not in text


@pytest.mark.asyncio
async def test_cmd_export_ai_sends_document_with_only_flagged_leads(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    conn = await get_connection(db_path)
    await repository.ensure_source(conn, "hh_ru", 1)
    await repository.insert_lead(
        conn,
        Lead(source_id="hh_ru", external_id="1", title="Простой парсер", ai_assistable=True),
    )
    await repository.insert_lead(
        conn,
        Lead(source_id="hh_ru", external_id="2", title="Сложный проект", ai_assistable=False),
    )
    await conn.close()

    message = SimpleNamespace(text="/export_ai 30", answer_document=AsyncMock())
    await cmd_export_ai(message, db_path=db_path, config_dir=CONFIG_DIR)

    message.answer_document.assert_called_once()
    document = message.answer_document.call_args.args[0]
    assert document.filename == "lead_radar_ai_export_30d.txt"
    content = document.data.decode("utf-8")
    assert "Простой парсер" in content
    assert "Сложный проект" not in content


@pytest.mark.asyncio
async def test_cmd_export_ai_reports_when_nothing_flagged(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(text="/export_ai", answer=AsyncMock())
    await cmd_export_ai(message, db_path=db_path, config_dir=CONFIG_DIR)
    assert "нет лидов" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_export_sends_csv_document(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    conn = await get_connection(db_path)
    await repository.ensure_source(conn, "hh_ru", 1)
    await repository.insert_lead(
        conn, Lead(source_id="hh_ru", external_id="1", title="Тест", score=80)
    )
    await conn.close()

    message = SimpleNamespace(text="/export 30", answer_document=AsyncMock())
    await cmd_export(message, db_path=db_path)

    message.answer_document.assert_called_once()
    document = message.answer_document.call_args.args[0]
    assert document.filename == "lead_radar_export_30d.csv"
    assert b"hh_ru" in document.data


@pytest.mark.asyncio
async def test_cmd_export_defaults_to_30_days(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(text="/export", answer_document=AsyncMock())
    await cmd_export(message, db_path=db_path)
    document = message.answer_document.call_args.args[0]
    assert document.filename == "lead_radar_export_30d.csv"


@pytest.mark.asyncio
async def test_cmd_stats_reports_conversion(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    conn = await get_connection(db_path)
    await repository.ensure_source(conn, "hh_ru", 1)
    await repository.insert_lead(conn, Lead(source_id="hh_ru", external_id="1", score=80))
    await conn.close()

    message = SimpleNamespace(text="/stats 30d", answer=AsyncMock())
    await cmd_stats(message, db_path=db_path)

    message.answer.assert_called_once()
    text = message.answer.call_args.args[0]
    assert "hh_ru" in text
    assert "30 дн." in text


@pytest.mark.asyncio
async def test_cmd_crm_add_and_list(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)

    add_message = SimpleNamespace(text="/crm_add Acme LLC", answer=AsyncMock())
    await cmd_crm_add(add_message, db_path=db_path)
    assert "Acme LLC" in add_message.answer.call_args.args[0]

    list_message = SimpleNamespace(answer=AsyncMock())
    await cmd_crm(list_message, db_path=db_path)
    text = list_message.answer.call_args.args[0]
    assert "Acme LLC" in text
    assert "новый" in text


@pytest.mark.asyncio
async def test_cmd_crm_add_without_name_shows_usage(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(text="/crm_add", answer=AsyncMock())
    await cmd_crm_add(message, db_path=db_path)
    assert "Использование" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_crm_empty_shows_hint(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(answer=AsyncMock())
    await cmd_crm(message, db_path=db_path)
    assert "/crm_add" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_crm_touch_records_result_and_schedules_next(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    add_message = SimpleNamespace(text="/crm_add Beta Inc", answer=AsyncMock())
    await cmd_crm_add(add_message, db_path=db_path)

    conn = await get_connection(db_path)
    company = (await repository.list_companies(conn))[0]
    await conn.close()

    touch_message = SimpleNamespace(text=f"/crm_touch {company.id} 5 Обещали подумать", answer=AsyncMock())
    await cmd_crm_touch(touch_message, db_path=db_path)

    conn = await get_connection(db_path)
    updated = await repository.get_company(conn, company.id)  # type: ignore[arg-type]
    open_action = await repository.get_open_action_for_company(conn, company.id)  # type: ignore[arg-type]
    await conn.close()

    assert updated is not None and updated.result == "Обещали подумать"
    assert open_action is not None


@pytest.mark.asyncio
async def test_cmd_crm_touch_rejects_bad_args(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(text="/crm_touch abc", answer=AsyncMock())
    await cmd_crm_touch(message, db_path=db_path)
    assert "Использование" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_crm_touch_unknown_company(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(text="/crm_touch 999 5 привет", answer=AsyncMock())
    await cmd_crm_touch(message, db_path=db_path)
    assert "не найдена" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_crm_status_updates_status(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    add_message = SimpleNamespace(text="/crm_add Delta", answer=AsyncMock())
    await cmd_crm_add(add_message, db_path=db_path)

    conn = await get_connection(db_path)
    company = (await repository.list_companies(conn))[0]
    await conn.close()

    status_message = SimpleNamespace(text=f"/crm_status {company.id} won", answer=AsyncMock())
    await cmd_crm_status(status_message, db_path=db_path)

    conn = await get_connection(db_path)
    updated = await repository.get_company(conn, company.id)  # type: ignore[arg-type]
    await conn.close()
    assert updated is not None and updated.status == "won"


@pytest.mark.asyncio
async def test_cmd_crm_status_rejects_invalid_status(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(text="/crm_status 1 bogus", answer=AsyncMock())
    await cmd_crm_status(message, db_path=db_path)
    assert "Использование" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_income_records_payment(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(text="/income 15000 за консультацию", answer=AsyncMock())
    await cmd_income(message, db_path=db_path)

    assert "15000" in message.answer.call_args.args[0]

    conn = await get_connection(db_path)
    total = await repository.get_income_for_period(conn, date.today(), date.today() + timedelta(days=1))
    await conn.close()
    assert total == 15000


@pytest.mark.asyncio
async def test_cmd_income_rejects_non_numeric(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(text="/income много", answer=AsyncMock())
    await cmd_income(message, db_path=db_path)
    assert "Использование" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_goal_sets_monthly_goal(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(text="/goal 200000", answer=AsyncMock())
    await cmd_goal(message, db_path=db_path)

    assert "200000" in message.answer.call_args.args[0]

    conn = await get_connection(db_path)
    stored = await repository.get_system_state(conn, repository.MONTHLY_GOAL_KEY)
    await conn.close()
    assert stored == "200000"


@pytest.mark.asyncio
async def test_cmd_hh_status_empty(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(answer=AsyncMock())
    await cmd_hh_status(message, db_path=db_path)
    assert "python -m scripts.hh_oauth_login" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_hh_status_lists_applications(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    conn = await get_connection(db_path)
    await repository.upsert_hh_application(
        conn, HhApplication(id="1", vacancy_title="Backend Dev", state="invitation")
    )
    await conn.close()

    message = SimpleNamespace(answer=AsyncMock())
    await cmd_hh_status(message, db_path=db_path)
    text = message.answer.call_args.args[0]
    assert "Backend Dev" in text
    assert "invitation" in text


@pytest.mark.asyncio
async def test_cmd_settings_shows_effective_values(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    settings = Settings(_env_file=None, score_threshold=50, daily_brief_time="09:00")  # type: ignore[call-arg]

    message = SimpleNamespace(answer=AsyncMock())
    await cmd_settings(message, db_path=db_path, config_dir=CONFIG_DIR, settings=settings)
    text = message.answer.call_args.args[0]

    assert "50" in text
    assert "09:00" in text
    assert "/set_threshold" in text


@pytest.mark.asyncio
async def test_cmd_set_threshold_updates_and_reflects_in_settings(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    settings = Settings(_env_file=None, score_threshold=50)  # type: ignore[call-arg]

    set_message = SimpleNamespace(text="/set_threshold 77", answer=AsyncMock())
    await cmd_set_threshold(set_message, db_path=db_path)
    assert "77" in set_message.answer.call_args.args[0]

    settings_message = SimpleNamespace(answer=AsyncMock())
    await cmd_settings(settings_message, db_path=db_path, config_dir=CONFIG_DIR, settings=settings)
    assert "77" in settings_message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_set_threshold_rejects_non_numeric(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(text="/set_threshold abc", answer=AsyncMock())
    await cmd_set_threshold(message, db_path=db_path)
    assert "Использование" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_set_budget_floor_updates(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(text="/set_budget_floor 8000", answer=AsyncMock())
    await cmd_set_budget_floor(message, db_path=db_path)
    assert "8000" in message.answer.call_args.args[0]

    conn = await get_connection(db_path)
    value = await repository.get_system_state(conn, "override:min_budget_rub")
    await conn.close()
    assert value == "8000"


@pytest.mark.asyncio
async def test_cmd_set_brief_time_without_scheduler(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(text="/set_brief_time 14:30", answer=AsyncMock())
    await cmd_set_brief_time(message, db_path=db_path)
    text = message.answer.call_args.args[0]
    assert "14:30" in text
    assert "перезапуска" in text


@pytest.mark.asyncio
async def test_cmd_set_brief_time_reschedules_when_scheduler_present(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    fake_scheduler = SimpleNamespace(reschedule_job=MagicMock())
    message = SimpleNamespace(text="/set_brief_time 14:30", answer=AsyncMock())

    await cmd_set_brief_time(message, db_path=db_path, scheduler=fake_scheduler)

    fake_scheduler.reschedule_job.assert_called_once()
    args, kwargs = fake_scheduler.reschedule_job.call_args
    assert args[0] == "daily_brief"
    text = message.answer.call_args.args[0]
    assert "применится сразу" in text


@pytest.mark.asyncio
async def test_cmd_set_brief_time_rejects_bad_format(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    message = SimpleNamespace(text="/set_brief_time 25:99", answer=AsyncMock())
    await cmd_set_brief_time(message, db_path=db_path)
    assert "Использование" in message.answer.call_args.args[0]
