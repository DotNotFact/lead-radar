"""Разовая настройка профиля бота в Telegram: список команд, описание, короткое описание.
Ничего не отправляет ни в один чат - меняет только метаданные самого бота (владелец видит их
в чате с ботом и в его профиле).
Запуск: python -m scripts.setup_bot
"""
from __future__ import annotations

import asyncio

from aiogram import Bot
from aiogram.types import BotCommand

from src.core.config import get_settings

COMMANDS = [
    BotCommand(command="brief", description="Бриф на сегодня: действия, просроченное, статистика"),
    BotCommand(command="stats", description="Статистика за период: /stats 7d или /stats 30d"),
    BotCommand(command="export", description="Экспорт лидов в CSV: /export [дней]"),
    BotCommand(command="sources", description="Статус всех источников"),
    BotCommand(command="health", description="Диагностика источников"),
    BotCommand(command="pause", description="Приостановить сбор лидов"),
    BotCommand(command="resume", description="Возобновить сбор лидов"),
    BotCommand(command="addchat", description="Добавить Telegram-чат: /addchat @handle"),
    BotCommand(command="todo", description="Добавить задачу в очередь: /todo текст"),
    BotCommand(command="done", description="Отметить задачу выполненной: /done id"),
    BotCommand(command="snooze", description="Отложить задачу: /snooze id дней"),
]

DESCRIPTION = (
    "Lead Radar — персональный радар заказов и очередь действий для .NET-разработчика.\n\n"
    "Следит за hh.ru, Kwork, Telegram-чатами и RSS-фидами удалённой работы, оценивает "
    "релевантность и присылает сюда только то, что стоит внимания. Ничего не отвечает и не "
    "пишет заказчикам от вашего имени — только читает и уведомляет."
)

SHORT_DESCRIPTION = "Радар заказов: hh.ru, Kwork, Telegram, RSS. Только уведомления, без автоответов."


async def main() -> None:
    settings = get_settings()
    if not settings.bot_token:
        print("BOT_TOKEN не задан в .env")
        return

    bot = Bot(token=settings.bot_token)
    try:
        await bot.set_my_commands(COMMANDS)
        await bot.set_my_description(DESCRIPTION)
        await bot.set_my_short_description(SHORT_DESCRIPTION)
        me = await bot.get_me()
        print(f"Готово: команды и описание установлены для @{me.username}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
