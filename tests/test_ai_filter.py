from __future__ import annotations

from pathlib import Path

import pytest

from src.core.yaml_config import load_keywords_config
from src.scoring.ai_filter import is_ai_assistable
from src.scoring.budget import parse_budget

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture
def keywords():  # type: ignore[no-untyped-def]
    return load_keywords_config(CONFIG_DIR)


def test_matching_keyword_and_budget_under_ceiling_is_assistable(keywords) -> None:  # type: ignore[no-untyped-def]
    text = "Нужен простой парсер сайта в Excel, бюджет 10000 руб"
    budget = parse_budget(text)
    assert is_ai_assistable("Нужен парсер", text, budget, keywords.ai_assistable) is True


def test_no_matching_keyword_is_not_assistable(keywords) -> None:  # type: ignore[no-untyped-def]
    text = "Нужен senior бэкенд-разработчик на 3 месяца, сложная система биллинга, бюджет 300000 руб"
    budget = parse_budget(text)
    assert is_ai_assistable("Senior разработчик", text, budget, keywords.ai_assistable) is False


def test_budget_above_ceiling_is_not_assistable(keywords) -> None:  # type: ignore[no-untyped-def]
    text = "Нужен парсер каталога товаров, бюджет 200000 руб"
    budget = parse_budget(text)
    assert is_ai_assistable("Парсер каталога", text, budget, keywords.ai_assistable) is False


def test_matching_keyword_without_budget_is_assistable(keywords) -> None:  # type: ignore[no-untyped-def]
    # Бюджет не указан вовсе - не отсеиваем по бюджетному условию, раз тип задачи подходит.
    text = "Нужен простой телеграм бот для сбора заявок"
    budget = parse_budget(text)
    assert budget.budget_max is None
    assert is_ai_assistable("Телеграм бот", text, budget, keywords.ai_assistable) is True


def test_foreign_currency_budget_not_checked_against_ruble_ceiling(keywords) -> None:  # type: ignore[no-untyped-def]
    # Бюджет в валюте, отличной от RUB, не сравнивается с рублёвым потолком (условие
    # срабатывает только для None/RUB - см. is_ai_assistable).
    text = "Need a simple landing page, budget $500"
    budget = parse_budget(text)
    assert is_ai_assistable("Landing page", text, budget, keywords.ai_assistable) is True
