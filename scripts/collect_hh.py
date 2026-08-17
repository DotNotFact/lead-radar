"""Разовый прогон коллектора hh.ru: собрать, оценить, сохранить в БД.
Запуск: python -m scripts.collect_hh
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

from src.collectors.hh_ru import HhRuCollector
from src.core import repository
from src.core.config import Settings, get_settings
from src.core.db import apply_migrations, get_connection
from src.core.http import SourceUnavailableError
from src.core.logging_config import log_source_degraded, setup_logging
from src.core.models import Lead
from src.core.yaml_config import KeywordsConfig, SourcesConfig, load_keywords_config, load_sources_config
from src.scoring.budget import parse_budget
from src.scoring.dedup import content_hash
from src.scoring.scorer import score_lead

logger = logging.getLogger("lead_radar.scripts.collect_hh")


def _strip_html(html: str) -> str:
    from selectolax.parser import HTMLParser

    return HTMLParser(html).text(separator="\n").strip()


async def collect_and_store(
    settings: Settings, sources_config: SourcesConfig, keywords_config: KeywordsConfig
) -> dict[str, int]:
    """Возвращает {"new": N, "duplicates": N, "total": N} либо {"error": 1} при недоступности
    источника (источник переводится в degraded, система не падает)."""
    hh_config = sources_config.sources["hh_ru"]
    if not hh_config.enabled:
        logger.info("hh_ru_disabled")
        return {"new": 0, "duplicates": 0, "total": 0, "disabled": 1}

    extra = hh_config.model_extra or {}
    collector = HhRuCollector(
        base_url=extra.get("base_url", "https://api.hh.ru"),
        queries=list(extra.get("queries", [])),
        remote_only=bool(extra.get("remote_only", True)),
        contact_email=settings.contact_email,
        poll_interval=hh_config.poll_interval,
    )

    await apply_migrations(settings.db_path, settings.migrations_dir)
    conn = await get_connection(settings.db_path)
    try:
        await repository.ensure_source(conn, collector.source_id, collector.tier)

        since = await repository.get_last_published_at(conn, collector.source_id)
        if since is None:
            lookback_days = int(extra.get("initial_lookback_days", 7))
            since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        try:
            raw_leads = await collector.fetch(since)
        except SourceUnavailableError as exc:
            await repository.mark_source_failed(conn, collector.source_id, str(exc))
            log_source_degraded(collector.source_id, str(exc))
            return {"new": 0, "duplicates": 0, "total": 0, "error": 1}

        fetch_full = bool(extra.get("fetch_full_description", True))
        new_count = 0
        dup_count = 0

        async with httpx.AsyncClient(
            base_url=collector.base_url,
            headers={"User-Agent": collector.user_agent},
            timeout=20.0,
        ) as client:
            for raw in raw_leads:
                text = raw.text
                if fetch_full:
                    try:
                        detail = await collector.fetch_full_description(client, raw.external_id)
                    except SourceUnavailableError:
                        detail = None
                    if detail:
                        description = detail.get("description")
                        if description:
                            text = _strip_html(description)
                        skills = [s["name"] for s in detail.get("key_skills", [])]
                        if skills:
                            raw.meta["key_skills"] = skills

                budget = parse_budget(raw.raw_budget or text)
                scoring = score_lead(raw.title, text, raw.author_handle, budget, keywords_config)

                hash_ = content_hash(f"{raw.title or ''} {text or ''}")
                duplicate_of = await repository.find_duplicate_by_hash(
                    conn, hash_, collector.source_id
                )

                lead = Lead(
                    source_id=raw.source_id,
                    external_id=raw.external_id,
                    url=raw.url,
                    title=raw.title,
                    text=text,
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
                inserted = await repository.insert_lead(conn, lead)
                if inserted:
                    new_count += 1
                else:
                    dup_count += 1

        await repository.mark_source_ok(conn, collector.source_id)
        total = await repository.count_leads(conn, collector.source_id)
        logger.info(
            "hh_ru_collect_done",
            extra={"new": new_count, "duplicates": dup_count, "total_in_db": total},
        )
        return {"new": new_count, "duplicates": dup_count, "total": total}
    finally:
        await conn.close()


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_dir, settings.log_level)
    sources_config = load_sources_config(settings.config_dir)
    keywords_config = load_keywords_config(settings.config_dir)

    stats = await collect_and_store(settings, sources_config, keywords_config)

    if stats.get("disabled"):
        print("hh_ru отключён в config/sources.yaml (enabled: false)")
    elif stats.get("error"):
        print("hh_ru недоступен — источник помечен degraded, см. логи")
    else:
        print(
            f"Новых лидов: {stats['new']}, дублей(external_id): {stats['duplicates']}, "
            f"всего в БД по hh_ru: {stats['total']}"
        )


if __name__ == "__main__":
    asyncio.run(main())
