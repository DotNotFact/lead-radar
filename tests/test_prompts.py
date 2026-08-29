from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.control.bot import cmd_prompt, cmd_prompts
from src.control.prompts import load_prompts

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def test_load_real_prompts_yaml_has_expected_entries() -> None:
    prompts = load_prompts(CONFIG_DIR)
    assert "lead_batch_for_ai" in prompts
    assert "freelance_profile" in prompts
    assert "title" in prompts["lead_batch_for_ai"]
    assert "text" in prompts["lead_batch_for_ai"]


def test_load_prompts_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_prompts(tmp_path) == {}


@pytest.mark.asyncio
async def test_cmd_prompts_lists_names_and_titles() -> None:
    message = SimpleNamespace(answer=AsyncMock())
    await cmd_prompts(message, config_dir=CONFIG_DIR)
    text = message.answer.call_args.args[0]
    assert "freelance_profile" in text
    assert "/prompt" in text


@pytest.mark.asyncio
async def test_cmd_prompts_empty_config_dir(tmp_path: Path) -> None:
    message = SimpleNamespace(answer=AsyncMock())
    await cmd_prompts(message, config_dir=tmp_path)
    assert "пока нет" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_prompt_sends_text() -> None:
    message = SimpleNamespace(text="/prompt freelance_profile", answer=AsyncMock())
    await cmd_prompt(message, config_dir=CONFIG_DIR)
    text = message.answer.call_args.args[0]
    assert "специализация" in text.lower()


@pytest.mark.asyncio
async def test_cmd_prompt_unknown_name() -> None:
    message = SimpleNamespace(text="/prompt does_not_exist", answer=AsyncMock())
    await cmd_prompt(message, config_dir=CONFIG_DIR)
    assert "не найден" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_prompt_without_argument() -> None:
    message = SimpleNamespace(text="/prompt", answer=AsyncMock())
    await cmd_prompt(message, config_dir=CONFIG_DIR)
    assert "Использование" in message.answer.call_args.args[0]
