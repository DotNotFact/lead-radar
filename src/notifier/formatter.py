from __future__ import annotations

import re

from src.core.models import Lead

SOURCE_DISPLAY_NAMES: dict[str, str] = {
    "hh_ru": "hh.ru",
    "telegram": "Telegram",
    "kwork": "Kwork",
    "fl_ru": "FL.ru",
    "habr_freelance": "Хабр Фриланс",
    "rss_remote_jobs": "RSS",
    "remoteok": "RemoteOK",
    "freelancer": "Freelancer.com",
}

_MAX_BODY_CHARS = 220
_MAX_TAGS = 6


def _hot_emoji(score: float | None) -> str:
    if score is None:
        return "📄"
    return "🔥" if score >= 80 else "⚡"


def _format_budget(lead: Lead) -> str:
    if lead.budget_min is None and lead.budget_max is None:
        return "бюджет не указан"
    currency = lead.budget_currency or ""
    if lead.budget_min is not None and lead.budget_max is not None and lead.budget_min != lead.budget_max:
        low = f"{lead.budget_min:,}".replace(",", " ")
        high = f"{lead.budget_max:,}".replace(",", " ")
        return f"{low}–{high} {currency}".strip()
    amount = lead.budget_max if lead.budget_max is not None else lead.budget_min
    return f"{amount:,} {currency}".replace(",", " ").strip()


def _sanitize_tag(term: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", "", term.lower())


def format_lead_message(lead: Lead) -> str:
    source_name = SOURCE_DISPLAY_NAMES.get(lead.source_id, lead.source_id)
    score_str = f"{lead.score:.0f}" if lead.score is not None else "?"
    ai_marker = " 🤖" if lead.ai_assistable else ""
    header = f"{_hot_emoji(lead.score)} {score_str} | {source_name} | {_format_budget(lead)}{ai_marker}"

    body = (lead.title or lead.text or "").strip()
    if len(body) > _MAX_BODY_CHARS:
        body = body[:_MAX_BODY_CHARS].rstrip() + "..."

    tags = sorted({_sanitize_tag(t) for t in lead.stack_tags if _sanitize_tag(t)})
    tags_line = " ".join(f"#{t}" for t in tags[:_MAX_TAGS])

    parts = [header, body]
    if tags_line:
        parts.append(tags_line)
    return "\n".join(p for p in parts if p)
