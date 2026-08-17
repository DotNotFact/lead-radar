from __future__ import annotations

import logging

import aiosqlite
from aiogram import Bot

from src.core import repository
from src.core.retry import retry_with_backoff

logger = logging.getLogger("lead_radar.notifier.health_alerts")


async def check_and_notify_source_health(bot: Bot, channel_id: int, conn: aiosqlite.Connection) -> None:
    """Уведомляет владельца сразу при переходе источника в degraded (а не только в ежедневном
    брифе) и при восстановлении - но только один раз на каждый переход, не на каждый цикл
    планировщика (инвариант 6: владелец узнаёт о деградации)."""
    degraded = await repository.get_degraded_sources(conn)
    degraded_by_id = {row["id"]: row for row in degraded}
    all_sources = await repository.list_sources(conn)

    for source in all_sources:
        source_id = str(source["id"])
        is_degraded = source_id in degraded_by_id
        already_notified = await repository.was_degradation_notified(conn, source_id)

        if is_degraded and not already_notified:
            detail = degraded_by_id[source_id]["last_error"] or "источник недоступен"
            text = f"⚠️ Источник {source_id} деградирует: {detail}"

            async def _send(text: str = text) -> None:
                await bot.send_message(chat_id=channel_id, text=text)

            await retry_with_backoff(_send)
            await repository.set_degradation_notified(conn, source_id, True)
        elif not is_degraded and already_notified:
            recovery_text = f"✅ Источник {source_id} снова в порядке"

            async def _send_recovery(text: str = recovery_text) -> None:
                await bot.send_message(chat_id=channel_id, text=text)

            await retry_with_backoff(_send_recovery)
            await repository.set_degradation_notified(conn, source_id, False)
