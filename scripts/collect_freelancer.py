"""Разовый прогон коллектора Freelancer.com. Требует FREELANCER_OAUTH_TOKEN в .env.
Запуск: python -m scripts.collect_freelancer
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from src.collectors.freelancer import FreelancerCollector
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

logger = logging.getLogger("lead_radar.scripts.collect_freelancer")


def is_configured(settings: Settings) -> bool:
    return bool(settings.freelancer_oauth_token)


async def collect_and_store(
    settings: Settings, sources_config: SourcesConfig, keywords_config: KeywordsConfig
) -> dict[str, int]:
    config = sources_config.sources.get("freelancer")
    if config is None or not config.enabled:
        return {"new": 0, "duplicates": 0, "total": 0, "disabled": 1}
    if not is_configured(settings):
        logger.warning("freelancer_token_missing")
        return {"new": 0, "duplicates": 0, "total": 0, "unconfigured": 1}

    extra = config.model_extra or {}
    queries = list(extra.get("queries", []))
    collector = FreelancerCollector(
        oauth_token=settings.freelancer_oauth_token,
        base_url=extra.get("base_url", "https://www.freelancer.com/api/projects/0.1"),
        queries=queries,
        contact_email=settings.contact_email,
        poll_interval=config.poll_interval,
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
    print(f"freelancer: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
