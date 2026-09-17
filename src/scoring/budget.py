from __future__ import annotations

import re

from pydantic import BaseModel

_CURRENCY_PATTERNS: dict[str, str] = {
    "RUB": r"(?:₽|руб\.?|рублей|рубля|рубль|\bр\.)",
    "USD": r"\$|usd\b",
    "USDT": r"usdt",
}

_SCALE_PATTERNS: list[tuple[str, float]] = [
    (r"тыс\.?", 1000.0),
    (r"к\b", 1000.0),
    (r"k\b", 1000.0),
]

_HOURLY_RE = re.compile(r"в\s*час|/\s*час|почасов", re.IGNORECASE)

_NUMBER = r"\d[\d\s]*(?:[.,]\d+)?"

_RANGE_RE = re.compile(
    rf"(?:от\s*)?({_NUMBER})\s*(тыс\.?|к\b|k\b)?\s*(?:-|–|-|до)\s*({_NUMBER})\s*(тыс\.?|к\b|k\b)?",
    re.IGNORECASE,
)

_SINGLE_RE = re.compile(rf"({_NUMBER})\s*(тыс\.?|к\b|k\b)?", re.IGNORECASE)


class BudgetParseResult(BaseModel):
    budget_min: int | None = None
    budget_max: int | None = None
    currency: str | None = None
    confidence: float = 0.0
    is_hourly: bool = False


def _to_number(raw: str) -> float:
    cleaned = raw.replace(" ", "").replace(",", ".")
    return float(cleaned)


def _apply_scale(value: float, scale_token: str | None) -> float:
    if not scale_token:
        return value
    token = scale_token.strip().lower()
    for pattern, multiplier in _SCALE_PATTERNS:
        if re.fullmatch(pattern, token, re.IGNORECASE):
            return value * multiplier
    return value


def _detect_currency(text: str) -> str | None:
    for currency, pattern in _CURRENCY_PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            return currency
    return None


def parse_budget(text: str | None) -> BudgetParseResult:
    """Извлекает бюджет из свободного текста. Настраиваемых магических констант нет -
    список валютных обозначений задаётся в keywords.yaml (currency_symbols), сам парсер
    универсален по правилам ТЗ: диапазоны, сокращения тыс/к/k, почасовая ставка."""
    if not text:
        return BudgetParseResult()

    currency = _detect_currency(text)
    is_hourly = bool(_HOURLY_RE.search(text))

    range_match = _RANGE_RE.search(text)
    if range_match:
        low_raw, low_scale, high_raw, high_scale = range_match.groups()
        low = _apply_scale(_to_number(low_raw), low_scale)
        high = _apply_scale(_to_number(high_raw), high_scale)
        if low > high:
            low, high = high, low
        confidence = 0.9 if currency else 0.5
        if is_hourly:
            confidence *= 0.7
        return BudgetParseResult(
            budget_min=int(low), budget_max=int(high), currency=currency,
            confidence=round(confidence, 2), is_hourly=is_hourly,
        )

    if currency:
        # ищем число рядом с найденной валютой, а не первое число в тексте.
        # currency_pattern оборачивается в (?:...) - иначе его "|" рвёт всё выражение
        currency_pattern = f"(?:{_CURRENCY_PATTERNS[currency]})"
        number_then_currency = re.compile(
            rf"({_NUMBER})\s*(тыс\.?|к\b|k\b)?\s*{currency_pattern}", re.IGNORECASE
        )
        currency_then_number = re.compile(
            rf"{currency_pattern}\s*({_NUMBER})\s*(тыс\.?|к\b|k\b)?", re.IGNORECASE
        )
        match = number_then_currency.search(text) or currency_then_number.search(text)
        if match:
            groups = match.groups()
            amount_raw, scale = groups[0], groups[1] if len(groups) > 1 else None
            amount = _apply_scale(_to_number(amount_raw), scale)
            confidence = 0.85 if not is_hourly else 0.6
            return BudgetParseResult(
                budget_min=int(amount), budget_max=int(amount), currency=currency,
                confidence=round(confidence, 2), is_hourly=is_hourly,
            )

    single_match = _SINGLE_RE.search(text)
    if single_match:
        amount_raw, scale = single_match.groups()
        amount = _apply_scale(_to_number(amount_raw), scale)
        confidence = 0.3 if not is_hourly else 0.2
        return BudgetParseResult(
            budget_min=int(amount), budget_max=int(amount), currency=currency,
            confidence=round(confidence, 2), is_hourly=is_hourly,
        )

    return BudgetParseResult(currency=currency, is_hourly=is_hourly)
