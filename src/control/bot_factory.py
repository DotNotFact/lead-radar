from __future__ import annotations

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from src.core.config import Settings


def build_bot(settings: Settings) -> Bot:
    """Общая точка создания aiogram Bot - единственное место, где учитывается
    TELEGRAM_PROXY_URL. httpx-коллекторы прокси не нуждаются в этой функции - httpx сам
    читает HTTP_PROXY/HTTPS_PROXY из окружения."""
    if settings.telegram_proxy_url:
        session = AiohttpSession(proxy=settings.telegram_proxy_url)
        return Bot(token=settings.bot_token, session=session)
    return Bot(token=settings.bot_token)
