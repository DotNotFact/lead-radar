from __future__ import annotations

from src.scoring.budget import parse_budget


def test_empty_text_returns_no_budget() -> None:
    result = parse_budget(None)
    assert result.budget_min is None
    assert result.confidence == 0.0


def test_range_with_currency() -> None:
    result = parse_budget("Бюджет от 10000 до 20000 ₽")
    assert result.budget_min == 10000
    assert result.budget_max == 20000
    assert result.currency == "RUB"
    assert result.confidence > 0.5


def test_range_without_from_keyword() -> None:
    result = parse_budget("15000-25000 руб за проект")
    assert result.budget_min == 15000
    assert result.budget_max == 25000
    assert result.currency == "RUB"


def test_thousand_abbreviation_k_cyrillic() -> None:
    result = parse_budget("Готовы заплатить 15к за доработку")
    assert result.budget_min == 15000
    assert result.budget_max == 15000


def test_thousand_abbreviation_latin_k() -> None:
    result = parse_budget("Budget 15k usdt for the integration")
    assert result.budget_min == 15000
    assert result.currency == "USDT"


def test_tys_abbreviation() -> None:
    result = parse_budget("оплата 20 тыс руб")
    assert result.budget_min == 20000
    assert result.currency == "RUB"


def test_dollar_sign() -> None:
    result = parse_budget("Pay $500 for the api integration")
    assert result.budget_min == 500
    assert result.currency == "USD"


def test_hourly_rate_flagged() -> None:
    result = parse_budget("1500 руб в час")
    assert result.is_hourly is True
    assert result.budget_min == 1500


def test_no_currency_low_confidence() -> None:
    result = parse_budget("нужно закончить за 5 дней")
    # "5" будет распознано как одиночное число без валюты - низкая уверенность
    assert result.confidence <= 0.3
