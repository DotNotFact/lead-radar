from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.control.bot import cmd_addchat
from src.control.chat_config import add_runtime_chat, load_runtime_chats


def test_add_runtime_chat_creates_file_and_dedupes(tmp_path: Path) -> None:
    assert load_runtime_chats(tmp_path) == []

    added_first = add_runtime_chat(tmp_path, "@new_freelance_chat")
    assert added_first is True
    assert load_runtime_chats(tmp_path) == ["@new_freelance_chat"]

    added_second = add_runtime_chat(tmp_path, "@new_freelance_chat")
    assert added_second is False
    assert load_runtime_chats(tmp_path) == ["@new_freelance_chat"]

    add_runtime_chat(tmp_path, "@another_chat")
    assert load_runtime_chats(tmp_path) == ["@new_freelance_chat", "@another_chat"]


@pytest.mark.asyncio
async def test_cmd_addchat_reports_success_and_duplicate(tmp_path: Path) -> None:
    message = SimpleNamespace(text="/addchat @some_chat", answer=AsyncMock())
    await cmd_addchat(message, config_dir=tmp_path)
    message.answer.assert_called_once()
    assert "Добавлено" in message.answer.call_args.args[0]

    message2 = SimpleNamespace(text="/addchat @some_chat", answer=AsyncMock())
    await cmd_addchat(message2, config_dir=tmp_path)
    assert "уже в списке" in message2.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_addchat_without_argument_shows_usage(tmp_path: Path) -> None:
    message = SimpleNamespace(text="/addchat", answer=AsyncMock())
    await cmd_addchat(message, config_dir=tmp_path)
    assert "Использование" in message.answer.call_args.args[0]
