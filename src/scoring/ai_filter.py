from __future__ import annotations

from src.core.yaml_config import AiAssistableConfig
from src.scoring.budget import BudgetParseResult


def is_ai_assistable(
    title: str | None,
    text: str | None,
    budget: BudgetParseResult,
    config: AiAssistableConfig,
) -> bool:
    """Отдельная метка "закрывается ИИ целиком" - не влияет на основной score (см.
    scorer.py), только на /ai_leads и значок 🤖 в уведомлении. Срабатывает при совпадении
    хотя бы одного ключевого слова из config.terms И бюджете не выше потолка (когда бюджет
    вообще известен - лид без указанного бюджета не отсеивается по этому условию)."""
    haystack = f"{title or ''}\n{text or ''}".lower()
    if not any(term.lower() in haystack for term in config.terms):
        return False

    if budget.currency in (None, "RUB") and budget.budget_max is not None:
        return budget.budget_max <= config.budget_ceiling_rub

    return True
