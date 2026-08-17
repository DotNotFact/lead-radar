from __future__ import annotations

from pathlib import Path

import pytest

from src.core.yaml_config import load_keywords_config
from src.scoring.budget import parse_budget
from src.scoring.scorer import score_lead

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture
def keywords():  # type: ignore[no-untyped-def]
    return load_keywords_config(CONFIG_DIR)


def test_strong_positive_lead_scores_above_threshold(keywords) -> None:  # type: ignore[no-untyped-def]
    title = "Доработать API на .NET Core, нужна интеграция с React-фронтом"
    text = (
        "Нужно доработать интеграцию с эквайрингом на ASP.NET Core, есть легаси, "
        "требуется постепенно перенести часть логики, работы много, описание подробное. "
        "Бюджет 25000 руб, пишите в личку @customer. " * 3
    )
    budget = parse_budget(text)
    result = score_lead(title, text, "@customer", budget, keywords)
    assert len(title) + len(text) >= 400  # проверяем, что тест действительно бьёт detailed_spec
    assert result.score >= keywords.notification_threshold
    assert "stack" in result.matched_signals
    assert "detailed_spec" in result.matched_signals
    assert "adjacent_skills" in result.matched_signals
    assert "c#" in result.stack_tags or ".net" in result.stack_tags


def test_unpaid_test_task_scores_negative(keywords) -> None:  # type: ignore[no-untyped-def]
    title = "Тестовое задание за отзыв"
    text = "Нужно тестовое задание на энтузиазме, оплата после запуска, нужен партнёр"
    budget = parse_budget(text)
    result = score_lead(title, text, None, budget, keywords)
    assert result.score < 0
    assert "unpaid_or_test" in result.matched_signals


def test_stack_mismatch_penalized(keywords) -> None:  # type: ignore[no-untyped-def]
    title = "Нужен PHP разработчик"
    text = "Ищем PHP разработчика для доработки сайта на Laravel"
    budget = parse_budget(text)
    result = score_lead(title, text, None, budget, keywords)
    assert "stack_mismatch" in result.matched_signals


def test_junior_low_pay_only_penalized_with_low_budget(keywords) -> None:  # type: ignore[no-untyped-def]
    text_low = "Ищем junior разработчика, бюджет 2000 руб"
    budget_low = parse_budget(text_low)
    result_low = score_lead("Junior вакансия", text_low, None, budget_low, keywords)
    assert "junior_low_pay" in result_low.matched_signals

    text_high = "Ищем junior разработчика с наставником, бюджет 150000 руб в месяц"
    budget_high = parse_budget(text_high)
    result_high = score_lead("Junior вакансия", text_high, None, budget_high, keywords)
    assert "junior_low_pay" not in result_high.matched_signals
