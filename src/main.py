"""Точка входа: планировщик (hh.ru, уведомления, ежедневный бриф), Telegram-коллектор
(catch-up + realtime) и polling управляющего бота — всё в одном процессе.

Запуск: python -m src.main

Требует BOT_TOKEN как минимум. CHANNEL_ID, TELEGRAM_API_ID/HASH и заполненный список чатов
нужны для соответствующих частей (уведомления, Telegram-источник) - при их отсутствии эти
части просто не стартуют, остальное продолжает работать (инвариант 6: деградация, не падение).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from scripts.collect_hh import collect_and_store
from src.actions.brief import compose_daily_brief
from src.actions.materializer import materialize_due_actions
from src.collectors.telegram import TelegramCollector
from src.control.bot import build_dispatcher
from src.control.chat_config import load_runtime_chats
from src.core import repository
from src.core.config import Settings, get_settings
from src.core.db import apply_migrations, get_connection
from src.core.logging_config import log_source_degraded, setup_logging
from src.core.models import Lead, RawLead
from src.core.yaml_config import (
    KeywordsConfig,
    SourceConfig,
    SourcesConfig,
    load_actions_config,
    load_keywords_config,
    load_sources_config,
)
from src.notifier.notifier import notify_pending_leads
from src.scoring.budget import parse_budget
from src.scoring.dedup import content_hash
from src.scoring.scorer import score_lead

logger = logging.getLogger("lead_radar.main")


async def _is_paused(settings: Settings) -> bool:
    conn = await get_connection(settings.db_path)
    try:
        value = await repository.get_system_state(conn, "collecting_paused", "0")
    finally:
        await conn.close()
    return value == "1"


async def _run_hh_job(settings: Settings, sources_config: SourcesConfig, keywords_config: KeywordsConfig) -> None:
    if await _is_paused(settings):
        return
    await collect_and_store(settings, sources_config, keywords_config)


async def _run_notify_job(bot: Bot, settings: Settings) -> None:
    if not settings.channel_id:
        return
    conn = await get_connection(settings.db_path)
    try:
        sent = await notify_pending_leads(bot, settings.channel_id, conn, settings.score_threshold)
        if sent:
            logger.info("notify_job_done", extra={"sent": sent})
    finally:
        await conn.close()


async def _run_daily_brief_job(bot: Bot, settings: Settings) -> None:
    if not settings.channel_id:
        logger.warning("brief_skipped_no_channel_id")
        return
    conn = await get_connection(settings.db_path)
    try:
        actions_config = load_actions_config(settings.config_dir)
        today = datetime.now(timezone.utc).date()
        await materialize_due_actions(conn, actions_config, today)
        text = await compose_daily_brief(conn, today, settings.score_threshold)
    finally:
        await conn.close()
    await bot.send_message(chat_id=settings.channel_id, text=text)


async def _store_raw_lead(conn: Any, raw: RawLead, keywords_config: KeywordsConfig) -> None:
    budget = parse_budget(raw.text)
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
    await repository.insert_lead(conn, lead)


async def _start_telegram(settings: Settings, telegram_config: SourceConfig, keywords_config: KeywordsConfig) -> Any:
    """Поднимает Telethon-клиент, делает catch-up за время простоя, включает реалтайм-хендлер.
    Требует уже созданную *.session (создаётся один раз владельцем интерактивно - см. CLAUDE.md),
    поэтому не может быть проверено автоматически."""
    from telethon import TelegramClient

    client = TelegramClient(
        settings.telegram_session_name, settings.telegram_api_id, settings.telegram_api_hash
    )
    await client.start()

    extra = telegram_config.model_extra or {}
    chats = list(extra.get("chats", [])) + load_runtime_chats(settings.config_dir)
    collector = TelegramCollector(client, chats=chats, poll_interval=telegram_config.poll_interval)

    conn = await get_connection(settings.db_path)
    try:
        await repository.ensure_source(conn, collector.source_id, collector.tier)
        since = await repository.get_last_published_at(conn, collector.source_id)
        since = since or datetime.now(timezone.utc)
        try:
            raw_leads = await collector.fetch(since)
        except Exception as exc:
            await repository.mark_source_failed(conn, collector.source_id, str(exc))
            log_source_degraded(collector.source_id, str(exc))
            raw_leads = []
        else:
            await repository.mark_source_ok(conn, collector.source_id)

        for raw in raw_leads:
            await _store_raw_lead(conn, raw, keywords_config)
    finally:
        await conn.close()

    async def on_new_lead(raw: RawLead) -> None:
        realtime_conn = await get_connection(settings.db_path)
        try:
            await _store_raw_lead(realtime_conn, raw, keywords_config)
        finally:
            await realtime_conn.close()

    collector.register_realtime_handler(on_new_lead)
    return client


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_dir, settings.log_level)
    logger.info("startup")

    await apply_migrations(settings.db_path, settings.migrations_dir)

    sources_config = load_sources_config(settings.config_dir)
    keywords_config = load_keywords_config(settings.config_dir)

    if not settings.bot_token:
        logger.error("bot_token_missing")
        print("BOT_TOKEN не задан в .env - управляющий бот не может стартовать.")
        return

    bot = Bot(token=settings.bot_token)
    dispatcher = build_dispatcher()
    scheduler = AsyncIOScheduler()

    hh_config = sources_config.sources.get("hh_ru")
    if hh_config is not None and hh_config.enabled and hh_config.poll_interval > 0:
        scheduler.add_job(
            _run_hh_job,
            IntervalTrigger(seconds=hh_config.poll_interval),
            args=[settings, sources_config, keywords_config],
            id="hh_ru_collect",
        )

    scheduler.add_job(
        _run_notify_job, IntervalTrigger(seconds=60), args=[bot, settings], id="notify_pending"
    )

    hour_str, minute_str = settings.daily_brief_time.split(":")
    scheduler.add_job(
        _run_daily_brief_job,
        CronTrigger(hour=int(hour_str), minute=int(minute_str)),
        args=[bot, settings],
        id="daily_brief",
    )

    telegram_config = sources_config.sources.get("telegram")
    telegram_client = None
    if (
        telegram_config is not None
        and telegram_config.enabled
        and settings.telegram_api_id
        and settings.telegram_api_hash
    ):
        telegram_client = await _start_telegram(settings, telegram_config, keywords_config)
    else:
        logger.info("telegram_source_disabled_or_unconfigured")

    scheduler.start()
    try:
        await dispatcher.start_polling(
            bot,
            db_path=settings.db_path,
            config_dir=settings.config_dir,
            score_threshold=settings.score_threshold,
        )
    finally:
        scheduler.shutdown(wait=False)
        if telegram_client is not None:
            await telegram_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
