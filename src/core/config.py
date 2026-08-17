from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Вся конфигурация системы. Только из .env — никаких констант в коде."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(default="")
    contact_email: str = Field(default="")
    telegram_api_id: int | None = Field(default=None)
    telegram_api_hash: str | None = Field(default=None)
    telegram_session_name: str = Field(default="lead_radar_collector")
    channel_id: int | None = Field(default=None)

    @field_validator("telegram_api_id", "channel_id", mode="before")
    @classmethod
    def _empty_string_to_none(cls, value: Any) -> Any:
        # Поля "ещё не заполнены владельцем" стоят в .env как TELEGRAM_API_ID= (пустая строка).
        # pydantic иначе пытается распарсить "" как int и падает при каждом запуске.
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    db_path: Path = Field(default=Path("data/lead_radar.db"))

    log_dir: Path = Field(default=Path("logs"))
    log_level: str = Field(default="INFO")

    score_threshold: int = Field(default=50)
    min_budget_rub: int = Field(default=5000)

    daily_brief_time: str = Field(default="09:00")

    @property
    def migrations_dir(self) -> Path:
        return Path(__file__).resolve().parents[2] / "migrations"

    @property
    def config_dir(self) -> Path:
        return Path(__file__).resolve().parents[2] / "config"


def get_settings() -> Settings:
    return Settings()
