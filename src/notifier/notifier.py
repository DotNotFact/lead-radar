from __future__ import annotations

import logging

import aiosqlite
from aiogram import Bot

from src.core import repository
from src.core.models import Lead
from src.notifier.formatter import format_lead_message
from src.notifier.keyboard import build_lead_keyboard

logger = logging.getLogger("lead_radar.notifier")


async def send_lead_notification(
    bot: Bot, channel_id: int, lead: Lead, conn: aiosqlite.Connection
) -> None:
    """Единственное место в системе, откуда лид уходит наружу — и только владельцу в его
    приватный канал (инвариант 1: никакого автоматического контакта с заказчиком)."""
    if lead.id is None:
        raise ValueError("Lead должен быть сохранён в БД перед отправкой уведомления")

    await bot.send_message(
        chat_id=channel_id,
        text=format_lead_message(lead),
        reply_markup=build_lead_keyboard(lead),
        disable_web_page_preview=True,
    )
    await repository.record_notified(conn, lead.id)
    logger.info("lead_notified", extra={"lead_id": lead.id, "source_id": lead.source_id})
