from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.control.bot import cmd_template, cmd_templates
from src.control.templates import load_templates

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def test_load_real_templates_yaml_has_expected_entries() -> None:
    templates = load_templates(CONFIG_DIR)
    assert "hh_response" in templates
    assert "title" in templates["hh_response"]
    assert "text" in templates["hh_response"]


def test_load_templates_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_templates(tmp_path) == {}


@pytest.mark.asyncio
async def test_cmd_templates_lists_names_and_titles() -> None:
    message = SimpleNamespace(answer=AsyncMock())
    await cmd_templates(message, config_dir=CONFIG_DIR)
    text = message.answer.call_args.args[0]
    assert "hh_response" in text
    assert "/template" in text


@pytest.mark.asyncio
async def test_cmd_templates_empty_config_dir(tmp_path: Path) -> None:
    message = SimpleNamespace(answer=AsyncMock())
    await cmd_templates(message, config_dir=tmp_path)
    assert "пока нет" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_template_sends_text() -> None:
    message = SimpleNamespace(text="/template hh_response", answer=AsyncMock())
    await cmd_template(message, config_dir=CONFIG_DIR)
    text = message.answer.call_args.args[0]
    assert "вакансия" in text.lower()


@pytest.mark.asyncio
async def test_cmd_template_unknown_name() -> None:
    message = SimpleNamespace(text="/template does_not_exist", answer=AsyncMock())
    await cmd_template(message, config_dir=CONFIG_DIR)
    assert "не найден" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_template_without_argument() -> None:
    message = SimpleNamespace(text="/template", answer=AsyncMock())
    await cmd_template(message, config_dir=CONFIG_DIR)
    assert "Использование" in message.answer.call_args.args[0]
