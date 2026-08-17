from __future__ import annotations

from aiogram import Dispatcher

from src.control.bot import router as bot_router
from src.control.menu import router as menu_router


def build_dispatcher() -> Dispatcher:
    """Отдельный модуль, а не bot.py - menu.py импортирует текстовые билдеры из bot.py,
    так что сборка диспетчера внутри bot.py дала бы цикл импортов."""
    dp = Dispatcher()
    dp.include_router(bot_router)
    dp.include_router(menu_router)
    return dp
