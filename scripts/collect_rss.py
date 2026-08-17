"""Разовый прогон RSS-коллектора удалённых вакансий.
Запуск: python -m scripts.collect_rss
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from src.collectors.rss_jobs import RssJobsCollector
from src.core import repository
from src.core.config import Settings, get_settings
from src.core.db import apply_migrations, get_connection
from src.core.http import SourceUnavailableError
from src.core.logging_config import log_source_degraded, setup_logging
from src.core.pipeline import score_and_store_lead
from src.core.yaml_config import (
    KeywordsConfig,
    SourcesConfig,
    load_keywords_config,
    load_sources_config,
)

logger = logging.getLogger("lead_radar.scripts.collect_rss")


async def collect_and_store(
    settings: Settings, sources_config: SourcesConfig, keywords_config: KeywordsConfig
) -> dict[str, int]:
    config = sources_config.sources.get("rss_remote_jobs")
    if config is None or not config.enabled:
        return {"new": 0, "duplicates": 0, "total": 0, "disabled": 1}

    extra = config.model_extra or {}
    feed_urls = [
        f["url"] for f in extra.get("feeds", []) if isinstance(f, dict) and not f.get("disabled")
    ]
    collector = RssJobsCollector(
        feed_urls=feed_urls, contact_email=settings.contact_email, poll_interval=config.poll_interval
    )

    await apply_migrations(settings.db_path, settings.migrations_dir)
    conn = await get_connection(settings.db_path)
    try:
        await repository.ensure_source(conn, collector.source_id, collector.tier)
        since = await repository.get_last_published_at(conn, collector.source_id)
        since = since or (datetime.now(timezone.utc) - timedelta(days=3))

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


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_dir, settings.log_level)
    sources_config = load_sources_config(settings.config_dir)
    keywords_config = load_keywords_config(settings.config_dir)

    stats = await collect_and_store(settings, sources_config, keywords_config)
    print(f"rss_remote_jobs: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
