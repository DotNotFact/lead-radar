from __future__ import annotations

from pathlib import Path

from src.core.env_file import update_env_file


def test_replaces_existing_key_preserves_others(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("BOT_TOKEN=abc\nHH_ACCESS_TOKEN=old\n# comment\nCONTACT_EMAIL=\n", encoding="utf-8")

    update_env_file(env_path, {"HH_ACCESS_TOKEN": "new"})

    content = env_path.read_text(encoding="utf-8")
    assert "HH_ACCESS_TOKEN=new" in content
    assert "BOT_TOKEN=abc" in content
    assert "# comment" in content
    assert "CONTACT_EMAIL=" in content
    assert "old" not in content


def test_appends_missing_key(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("BOT_TOKEN=abc\n", encoding="utf-8")

    update_env_file(env_path, {"HH_REFRESH_TOKEN": "xyz"})

    content = env_path.read_text(encoding="utf-8")
    assert "BOT_TOKEN=abc" in content
    assert "HH_REFRESH_TOKEN=xyz" in content


def test_creates_file_if_missing(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    update_env_file(env_path, {"HH_ACCESS_TOKEN": "abc"})
    assert env_path.read_text(encoding="utf-8").strip() == "HH_ACCESS_TOKEN=abc"


def test_updates_multiple_keys_at_once(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("HH_ACCESS_TOKEN=old_access\nHH_REFRESH_TOKEN=old_refresh\n", encoding="utf-8")

    update_env_file(env_path, {"HH_ACCESS_TOKEN": "new_access", "HH_REFRESH_TOKEN": "new_refresh"})

    content = env_path.read_text(encoding="utf-8")
    assert "HH_ACCESS_TOKEN=new_access" in content
    assert "HH_REFRESH_TOKEN=new_refresh" in content
    assert "old" not in content
