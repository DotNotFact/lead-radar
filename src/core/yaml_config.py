from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict


class SourceConfig(BaseModel):
    """Общие поля источника. Специфичные для коллектора поля (queries, base_url, chats, ...)
    остаются доступны через model_extra — ядро их не типизирует."""

    model_config = ConfigDict(extra="allow")

    tier: int
    enabled: bool = True
    poll_interval: int = 0
    note: str | None = None


class SourcesConfig(BaseModel):
    sources: dict[str, SourceConfig]


def load_sources_config(config_dir: Path) -> SourcesConfig:
    data = _load_yaml(config_dir / "sources.yaml")
    return SourcesConfig.model_validate(data)


class SignalConfig(BaseModel):
    weight: float
    terms: list[str] = []
    min_chars: int | None = None
    note: str | None = None


class BudgetParsingConfig(BaseModel):
    currency_symbols: list[str]
    min_budget_rub: int


class KeywordsConfig(BaseModel):
    positive_signals: dict[str, SignalConfig]
    negative_signals: dict[str, SignalConfig]
    notification_threshold: float
    budget_parsing: BudgetParsingConfig


def load_keywords_config(config_dir: Path) -> KeywordsConfig:
    data = _load_yaml(config_dir / "keywords.yaml")
    return KeywordsConfig.model_validate(data)


class RecurringActionTemplate(BaseModel):
    title: str
    recurrence: str
    priority: int
    expected_value: str | None = None


class SeasonalActionTemplate(BaseModel):
    title: str
    activate_on: str  # "MM-DD"
    priority: int


class OneOffActionTemplate(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str
    due_date: str | None = None
    priority: int


class ActionsConfig(BaseModel):
    recurring: list[RecurringActionTemplate] = []
    seasonal: list[SeasonalActionTemplate] = []
    one_off: list[OneOffActionTemplate] = []


def load_actions_config(config_dir: Path) -> ActionsConfig:
    data = _load_yaml(config_dir / "actions.yaml")
    return ActionsConfig.model_validate(data)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        loaded: dict[str, Any] = yaml.safe_load(f)
    return loaded
