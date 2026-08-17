from __future__ import annotations

from pydantic import BaseModel

from src.core.yaml_config import KeywordsConfig
from src.scoring.budget import BudgetParseResult


class ScoringResult(BaseModel):
    score: float
    matched_signals: list[str] = []
    stack_tags: list[str] = []


def _matched_terms(haystack: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term.lower() in haystack]


def score_lead(
    title: str | None,
    text: str | None,
    author_handle: str | None,
    budget: BudgetParseResult,
    config: KeywordsConfig,
) -> ScoringResult:
    haystack = f"{title or ''}\n{text or ''}".lower()
    combined_len = len(f"{title or ''}{text or ''}")

    score = 0.0
    matched_signals: list[str] = []
    stack_tags: list[str] = []

    for name, signal in config.positive_signals.items():
        if name == "has_explicit_budget":
            if budget.budget_min is not None or budget.budget_max is not None:
                score += signal.weight
                matched_signals.append(name)
            continue
        if name == "detailed_spec":
            min_chars = signal.min_chars or 0
            if combined_len >= min_chars:
                score += signal.weight
                matched_signals.append(name)
            continue
        if name == "author_has_contact":
            if author_handle:
                score += signal.weight
                matched_signals.append(name)
            continue

        matched = _matched_terms(haystack, signal.terms)
        if matched:
            score += signal.weight
            matched_signals.append(name)
            if name == "stack":
                stack_tags.extend(matched)

    budget_ceiling = config.budget_parsing.min_budget_rub
    is_below_floor = (
        budget.currency in (None, "RUB")
        and budget.budget_max is not None
        and budget.budget_max < budget_ceiling
    )

    for name, signal in config.negative_signals.items():
        if name == "below_budget_floor":
            if is_below_floor:
                score += signal.weight
                matched_signals.append(name)
            continue
        if name == "junior_low_pay":
            matched = _matched_terms(haystack, signal.terms)
            if matched and is_below_floor:
                score += signal.weight
                matched_signals.append(name)
            continue

        matched = _matched_terms(haystack, signal.terms)
        if matched:
            score += signal.weight
            matched_signals.append(name)

    return ScoringResult(score=score, matched_signals=matched_signals, stack_tags=stack_tags)
