from __future__ import annotations

import re

from aiogram.filters import Command

from scripts.setup_bot import COMMANDS, DESCRIPTION, SHORT_DESCRIPTION
from src.control.bot import router

_COMMAND_NAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")


def _registered_command_names() -> set[str]:
    names: set[str] = set()
    for observer in router.message.handlers:
        for f in observer.filters or []:
            if isinstance(f.callback, Command):
                names.update(c for c in f.callback.commands if isinstance(c, str))
    return names


def test_command_names_are_valid_telegram_commands() -> None:
    for command in COMMANDS:
        assert _COMMAND_NAME_RE.match(command.command), command.command
        assert 1 <= len(command.description) <= 256


def test_command_list_covers_all_implemented_bot_commands() -> None:
    # Сверяется напрямую с роутером, а не с захардкоженным списком - список команд не сможет
    # незаметно разъехаться с тем, что реально зарегистрировано в control/bot.py.
    names = {c.command for c in COMMANDS}
    assert names == _registered_command_names()


def test_descriptions_within_telegram_limits() -> None:
    assert 1 <= len(DESCRIPTION) <= 512
    assert 1 <= len(SHORT_DESCRIPTION) <= 120
