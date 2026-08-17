from __future__ import annotations

import aiosqlite

from src.core import repository
from src.core.models import Lead, RawLead
from src.core.runtime_settings import apply_min_budget_override
from src.core.yaml_config import KeywordsConfig
from src.scoring.budget import parse_budget
from src.scoring.dedup import content_hash
from src.scoring.scorer import score_lead


async def score_and_store_lead(
    conn: aiosqlite.Connection, raw: RawLead, keywords_config: KeywordsConfig
) -> bool:
    """Общий хвост конвейера для всех источников с реальными лидами: парсинг бюджета,
    скоринг, дедуп по хешу текста, запись. Возвращает True, если запись новая."""
    keywords_config = await apply_min_budget_override(conn, keywords_config)
    budget = parse_budget(raw.raw_budget or raw.text)
    scoring = score_lead(raw.title, raw.text, raw.author_handle, budget, keywords_config)
    hash_ = content_hash(f"{raw.title or ''} {raw.text or ''}")
    duplicate_of = await repository.find_duplicate_by_hash(conn, hash_, raw.source_id)

    lead = Lead(
        source_id=raw.source_id,
        external_id=raw.external_id,
        url=raw.url,
        title=raw.title,
        text=raw.text,
        published_at=raw.published_at,
        budget_min=budget.budget_min,
        budget_max=budget.budget_max,
        budget_currency=budget.currency,
        budget_confidence=budget.confidence,
        stack_tags=scoring.stack_tags,
        content_hash=hash_,
        duplicate_of=duplicate_of,
        score=scoring.score,
        author_handle=raw.author_handle,
        raw_meta=raw.meta,
    )
    return await repository.insert_lead(conn, lead)
