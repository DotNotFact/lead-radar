from __future__ import annotations

from pathlib import Path

from src.core.yaml_config import load_keywords_config, load_sources_config

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def test_real_sources_yaml_is_valid() -> None:
    config = load_sources_config(CONFIG_DIR)
    assert "hh_ru" in config.sources
    hh = config.sources["hh_ru"]
    assert hh.tier == 1
    assert hh.enabled is True
    assert hh.model_extra is not None
    assert "queries" in hh.model_extra


def test_real_keywords_yaml_is_valid() -> None:
    config = load_keywords_config(CONFIG_DIR)
    assert "stack" in config.positive_signals
    assert "unpaid_or_test" in config.negative_signals
    assert config.notification_threshold == 50
    assert "₽" in config.budget_parsing.currency_symbols
