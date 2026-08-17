"""Разовый прогон коллекторов Kwork: раздел проектов заказчиков (реальные лиды, обычный
скоринг) и каталог услуг фрилансеров (только рыночная аналитика, score=None, без уведомлений).
Запуск: python -m scripts.collect_kwork
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import aiosqlite

from src.collectors.kwork import KworkCatalogCollector, KworkProjectsCollector
from src.core import repository
from src.core.config import Settings, get_settings
from src.core.db import apply_migrations, get_connection
from src.core.http import SourceUnavailableError
from src.core.logging_config import log_source_degraded, setup_logging
from src.core.models import Lead, RawLead
from src.core.pipeline import score_and_store_lead
from src.core.yaml_config import (
    KeywordsConfig,
    SourcesConfig,
    load_keywords_config,
    load_sources_config,
)
from src.scoring.budget import parse_budget
from src.scoring.dedup import content_hash

logger = logging.getLogger("lead_radar.scripts.collect_kwork")


async def _store_unscored_lead(conn: aiosqlite.Connection, raw: RawLead) -> bool:
    """Для kwork_catalog: рыночная аналитика, не лид. score=None -> никогда не пройдёт
    "score >= порог" (NULL в SQL всегда даёт ложь), поэтому никогда не уведомляется."""
    budget = parse_budget(raw.raw_budget)
    hash_ = content_hash(raw.title or "")
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
        stack_tags=[],
        content_hash=hash_,
        duplicate_of=None,
        score=None,
        author_handle=raw.author_handle,
        raw_meta=raw.meta,
    )
    return await repository.insert_lead(conn, lead)


async def collect_kwork_projects(
    settings: Settings, sources_config: SourcesConfig, keywords_config: KeywordsConfig
) -> dict[str, int]:
    config = sources_config.sources.get("kwork_projects")
    if config is None or not config.enabled:
        return {"new": 0, "duplicates": 0, "total": 0, "disabled": 1}

    collector = KworkProjectsCollector(
        contact_email=settings.contact_email, poll_interval=config.poll_interval
    )

    await apply_migrations(settings.db_path, settings.migrations_dir)
    conn = await get_connection(settings.db_path)
    try:
        await repository.ensure_source(conn, collector.source_id, collector.tier)
        since = await repository.get_last_published_at(conn, collector.source_id)
        since = since or (datetime.now(timezone.utc) - timedelta(days=1))

        try:
            raw_leads = await collector.fetch(since)
        except SourceUnavailableError as exc:
            await repository.mark_source_failed(conn, collector.source_id, str(exc))
            log_source_degraded(collector.source_id, str(exc))
            return {"new": 0, "duplicates": 0, "total": 0, "error": 1}

        new_count = 0
        dup_count = 0
        for raw in raw_leads:
            inserted = await score_and_store_lead(conn, raw, keywords_config)
            new_count += int(inserted)
            dup_count += int(not inserted)

        await repository.mark_source_ok(conn, collector.source_id)
        total = await repository.count_leads(conn, collector.source_id)
        return {"new": new_count, "duplicates": dup_count, "total": total}
    finally:
        await conn.close()


async def collect_kwork_catalog(settings: Settings, sources_config: SourcesConfig) -> dict[str, int]:
    config = sources_config.sources.get("kwork_catalog")
    if config is None or not config.enabled:
        return {"new": 0, "duplicates": 0, "total": 0, "disabled": 1}

    extra = config.model_extra or {}
    collector = KworkCatalogCollector(
        category_urls=list(extra.get("categories", [])),
        contact_email=settings.contact_email,
        poll_interval=config.poll_interval,
        min_request_interval=float(extra.get("min_request_interval_seconds", 10)),
    )

    await apply_migrations(settings.db_path, settings.migrations_dir)
    conn = await get_connection(settings.db_path)
    try:
        await repository.ensure_source(conn, collector.source_id, collector.tier)

        try:
            raw_leads = await collector.fetch(datetime.now(timezone.utc))
        except SourceUnavailableError as exc:
            await repository.mark_source_failed(conn, collector.source_id, str(exc))
            log_source_degraded(collector.source_id, str(exc))
            return {"new": 0, "duplicates": 0, "total": 0, "error": 1}

        new_count = 0
        dup_count = 0
        for raw in raw_leads:
            inserted = await _store_unscored_lead(conn, raw)
            new_count += int(inserted)
            dup_count += int(not inserted)

        await repository.mark_source_ok(conn, collector.source_id)
        total = await repository.count_leads(conn, collector.source_id)
        return {"new": new_count, "duplicates": dup_count, "total": total}
    finally:
        await conn.close()


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_dir, settings.log_level)
    sources_config = load_sources_config(settings.config_dir)
    keywords_config = load_keywords_config(settings.config_dir)

    projects_stats = await collect_kwork_projects(settings, sources_config, keywords_config)
    catalog_stats = await collect_kwork_catalog(settings, sources_config)

    print(f"kwork_projects: {projects_stats}")
    print(f"kwork_catalog: {catalog_stats}")


if __name__ == "__main__":
    asyncio.run(main())
