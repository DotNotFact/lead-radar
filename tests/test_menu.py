from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.control import menu
from src.core import repository
from src.core.config import Settings
from src.core.db import apply_migrations, get_connection

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


async def _seed_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    return db_path


def _settings() -> Settings:
    return Settings(_env_file=None, score_threshold=50, daily_brief_time="09:00")  # type: ignore[call-arg]


def _fake_callback(data: str) -> SimpleNamespace:
    edited = SimpleNamespace(edit_text=AsyncMock())
    return SimpleNamespace(data=data, answer=AsyncMock(), message=edited)


def test_main_menu_keyboard_has_all_sections() -> None:
    keyboard = menu.main_menu_keyboard()
    texts = {btn.text for row in keyboard.inline_keyboard for btn in row}
    assert texts == {
        "📋 Бриф", "📊 Статистика", "🏢 CRM", "💰 Доход", "🤖 ИИ-лиды",
        "📝 Шаблоны", "🔧 Источники", "⚙️ Настройки", "❓ Помощь",
    }


def test_settings_menu_keyboard_encodes_brief_time_without_colon() -> None:
    keyboard = menu.settings_menu_keyboard()
    callback_data = {btn.callback_data for row in keyboard.inline_keyboard for btn in row}
    assert "menu:settings:bt:0900" in callback_data
    assert "menu:settings:th:50" in callback_data
    assert "menu:settings:mb:5000" in callback_data


@pytest.mark.asyncio
async def test_cmd_start_and_menu_send_keyboard() -> None:
    message = SimpleNamespace(answer=AsyncMock())
    await menu.cmd_start(message)
    assert message.answer.call_args.kwargs["reply_markup"] is not None

    message2 = SimpleNamespace(answer=AsyncMock())
    await menu.cmd_menu(message2)
    assert "меню" in message2.answer.call_args.args[0].lower()


@pytest.mark.asyncio
async def test_cmd_help_lists_commands() -> None:
    message = SimpleNamespace(answer=AsyncMock())
    await menu.cmd_help(message)
    text = message.answer.call_args.args[0]
    assert "/brief" in text
    assert "/crm_add" in text
    assert "/set_threshold" in text


@pytest.mark.asyncio
async def test_menu_callback_main_shows_main_menu() -> None:
    callback = _fake_callback("menu:main")
    await menu.handle_menu_callback(
        callback, db_path=Path("unused.db"), config_dir=CONFIG_DIR, settings=_settings()
    )
    callback.answer.assert_called_once()
    callback.message.edit_text.assert_called_once()
    assert "Главное меню" in callback.message.edit_text.call_args.args[0]


@pytest.mark.asyncio
async def test_menu_callback_brief_shows_brief_text(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    callback = _fake_callback("menu:brief")

    await menu.handle_menu_callback(
        callback, db_path=db_path, config_dir=CONFIG_DIR, settings=_settings()
    )

    text = callback.message.edit_text.call_args.args[0]
    assert "Бриф на" in text


@pytest.mark.asyncio
async def test_menu_callback_stats_shows_submenu_then_period(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)

    submenu_callback = _fake_callback("menu:stats")
    await menu.handle_menu_callback(
        submenu_callback, db_path=db_path, config_dir=CONFIG_DIR, settings=_settings()
    )
    assert "период" in submenu_callback.message.edit_text.call_args.args[0].lower()

    period_callback = _fake_callback("menu:stats:30")
    await menu.handle_menu_callback(
        period_callback, db_path=db_path, config_dir=CONFIG_DIR, settings=_settings()
    )
    assert "30 дн." in period_callback.message.edit_text.call_args.args[0]


@pytest.mark.asyncio
async def test_menu_callback_settings_preset_applies_threshold(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    callback = _fake_callback("menu:settings:th:90")

    await menu.handle_menu_callback(
        callback, db_path=db_path, config_dir=CONFIG_DIR, settings=_settings()
    )

    conn = await get_connection(db_path)
    value = await repository.get_system_state(conn, "override:score_threshold")
    await conn.close()
    assert value == "90.0"
    assert "90" in callback.message.edit_text.call_args.args[0]


@pytest.mark.asyncio
async def test_menu_callback_settings_preset_applies_brief_time_and_reschedules(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    fake_scheduler = SimpleNamespace(reschedule_job=MagicMock())
    callback = _fake_callback("menu:settings:bt:1200")

    await menu.handle_menu_callback(
        callback, db_path=db_path, config_dir=CONFIG_DIR, settings=_settings(), scheduler=fake_scheduler
    )

    conn = await get_connection(db_path)
    value = await repository.get_system_state(conn, "override:daily_brief_time")
    await conn.close()
    assert value == "12:00"
    fake_scheduler.reschedule_job.assert_called_once()
    assert fake_scheduler.reschedule_job.call_args.args[0] == "daily_brief"


@pytest.mark.asyncio
async def test_menu_callback_crm_income_templates_sources(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)

    for action, expected_snippet in [
        ("crm", "CRM"),
        ("income", "Доход"),
        ("templates", "шаблон"),
        ("sources", "Источников"),
    ]:
        callback = _fake_callback(f"menu:{action}")
        await menu.handle_menu_callback(
            callback, db_path=db_path, config_dir=CONFIG_DIR, settings=_settings()
        )
        text = callback.message.edit_text.call_args.args[0]
        assert expected_snippet.lower() in text.lower() or len(text) > 0


@pytest.mark.asyncio
async def test_menu_callback_help() -> None:
    callback = _fake_callback("menu:help")
    await menu.handle_menu_callback(
        callback, db_path=Path("unused.db"), config_dir=CONFIG_DIR, settings=_settings()
    )
    assert "/brief" in callback.message.edit_text.call_args.args[0]


@pytest.mark.asyncio
async def test_menu_callback_falls_back_to_answer_when_edit_fails(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    edited = SimpleNamespace(edit_text=AsyncMock(side_effect=RuntimeError("message not modified")))
    edited.answer = AsyncMock()
    callback = SimpleNamespace(data="menu:main", answer=AsyncMock(), message=edited)

    await menu.handle_menu_callback(
        callback, db_path=db_path, config_dir=CONFIG_DIR, settings=_settings()
    )

    edited.answer.assert_called_once()
