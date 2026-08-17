from __future__ import annotations

import re

from scripts.setup_bot import COMMANDS, DESCRIPTION, SHORT_DESCRIPTION

_COMMAND_NAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")


def test_command_names_are_valid_telegram_commands() -> None:
    for command in COMMANDS:
        assert _COMMAND_NAME_RE.match(command.command), command.command
        assert 1 <= len(command.description) <= 256


def test_command_list_covers_all_implemented_bot_commands() -> None:
    names = {c.command for c in COMMANDS}
    expected = {
        "brief", "stats", "export", "sources", "health",
        "pause", "resume", "addchat", "todo", "done", "snooze",
    }
    assert names == expected


def test_descriptions_within_telegram_limits() -> None:
    assert 1 <= len(DESCRIPTION) <= 512
    assert 1 <= len(SHORT_DESCRIPTION) <= 120
