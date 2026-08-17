from __future__ import annotations

from pathlib import Path

from src.core.config import Settings


def test_settings_defaults_without_env_file() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.score_threshold == 50
    assert settings.min_budget_rub == 5000
    assert settings.daily_brief_time == "09:00"
    assert settings.db_path == Path("data/lead_radar.db")


def test_settings_reads_env_file(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    env_file = tmp_path / ".env"
    env_file.write_text("BOT_TOKEN=test-token\nSCORE_THRESHOLD=75\n", encoding="utf-8")

    settings = Settings(_env_file=str(env_file))  # type: ignore[call-arg]

    assert settings.bot_token == "test-token"
    assert settings.score_threshold == 75


def test_settings_treats_blank_optional_int_env_as_none(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # .env.example ставит TELEGRAM_API_ID= и CHANNEL_ID= пустыми до заполнения владельцем -
    # pydantic иначе пытается распарсить "" как int и падает на каждом запуске.
    env_file = tmp_path / ".env"
    env_file.write_text("TELEGRAM_API_ID=\nCHANNEL_ID=\n", encoding="utf-8")

    settings = Settings(_env_file=str(env_file))  # type: ignore[call-arg]

    assert settings.telegram_api_id is None
    assert settings.channel_id is None
