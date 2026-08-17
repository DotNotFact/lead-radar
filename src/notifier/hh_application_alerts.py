from __future__ import annotations

import logging

import aiosqlite
from aiogram import Bot

from src.core import repository
from src.core.models import HhApplication
from src.core.retry import retry_with_backoff

logger = logging.getLogger("lead_radar.notifier.hh_application_alerts")

_STATE_LABELS = {
    "response": "отклик отправлен",
    "invitation": "🎉 приглашение на собеседование",
    "discard": "отказ",
}


def _format_change(app: HhApplication) -> str:
    label = _STATE_LABELS.get(app.state or "", app.state or "неизвестно")
    title = app.vacancy_title or app.vacancy_id or app.id
    line = f"hh.ru: «{title}» — {label}"
    if app.vacancy_url:
        line += f"\n{app.vacancy_url}"
    return line


async def notify_application_changes(
    bot: Bot, channel_id: int, conn: aiosqlite.Connection, changed: list[HhApplication]
) -> int:
    """Шлёт по одному сообщению на изменившийся отклик. Сбой на одном не должен блокировать
    остальные (инвариант 6); last_notified_state обновляется только при успешной отправке,
    чтобы неудача не терялась молча."""
    sent = 0
    for app in changed:
        text = _format_change(app)

        async def _send(text: str = text) -> None:
            await bot.send_message(chat_id=channel_id, text=text)

        try:
            await retry_with_backoff(_send)
        except Exception:
            logger.exception("hh_application_notify_failed", extra={"application_id": app.id})
            continue
        await repository.mark_hh_application_notified(conn, app.id, app.state)
        sent += 1
    return sent
