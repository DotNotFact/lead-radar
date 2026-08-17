from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from apscheduler.triggers.cron import CronTrigger

from src.control import bot as bot_module
from src.core import runtime_settings
from src.core.config import Settings
from src.core.db import get_connection

logger = logging.getLogger("lead_radar.control.menu")

router = Router(name="lead_radar_menu")

_BACK_BUTTON = InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:main")

_THRESHOLD_PRESETS = [30, 50, 70, 90]
_BUDGET_PRESETS = [3000, 5000, 10000, 20000]
_BRIEF_TIME_PRESETS = ["08:00", "09:00", "10:00", "12:00"]

WELCOME_TEXT = (
    "👋 Lead Radar на связи.\n\n"
    "Слежу за hh.ru, Kwork, Telegram-чатами и RSS, оцениваю релевантность и присылаю сюда "
    "только то, что стоит внимания. Никогда не пишу заказчикам сам — это всегда делаешь ты.\n\n"
    "Выбирай раздел кнопками ниже или командами (/help — полный список)."
)

HELP_TEXT = (
    "📖 Команды Lead Radar\n\n"
    "Лиды:\n"
    "/brief — бриф на сегодня\n"
    "/stats [7d|30d] — статистика\n"
    "/export [дней] — CSV-выгрузка (обезличенная)\n"
    "/sources, /health — статус источников\n"
    "/pause, /resume — пауза/возобновление сбора\n"
    "/addchat @handle — добавить Telegram-чат\n\n"
    "Задачи:\n"
    "/todo <текст>, /done <id>, /snooze <id> <дней>\n\n"
    "CRM:\n"
    "/crm, /crm_add <название>, /crm_touch <id> <дней> [результат], "
    "/crm_status <id> <статус>\n\n"
    "Доход:\n"
    "/income <сумма> [заметка], /goal <сумма>\n\n"
    "Шаблоны:\n"
    "/templates, /template <имя>\n\n"
    "hh.ru:\n"
    "/hh_status — статусы собственных откликов (нужен OAuth, см. README.md)\n\n"
    "Настройки:\n"
    "/settings, /set_threshold <число>, /set_budget_floor <число>, "
    "/set_brief_time <ЧЧ:ММ>\n\n"
    "/menu — это меню кнопками. Инструкция по первому запуску и полной настройке — "
    "в README.md проекта."
)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Бриф", callback_data="menu:brief"),
                InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats"),
            ],
            [
                InlineKeyboardButton(text="🏢 CRM", callback_data="menu:crm"),
                InlineKeyboardButton(text="💰 Доход", callback_data="menu:income"),
            ],
            [
                InlineKeyboardButton(text="📝 Шаблоны", callback_data="menu:templates"),
                InlineKeyboardButton(text="🔧 Источники", callback_data="menu:sources"),
            ],
            [
                InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings"),
                InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help"),
            ],
        ]
    )


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_BACK_BUTTON]])


def stats_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="7 дней", callback_data="menu:stats:7"),
                InlineKeyboardButton(text="30 дней", callback_data="menu:stats:30"),
            ],
            [_BACK_BUTTON],
        ]
    )


def settings_menu_keyboard() -> InlineKeyboardMarkup:
    threshold_row = [
        InlineKeyboardButton(text=f"🎯 {v}", callback_data=f"menu:settings:th:{v}")
        for v in _THRESHOLD_PRESETS
    ]
    budget_row = [
        InlineKeyboardButton(text=f"💰 {v}", callback_data=f"menu:settings:mb:{v}")
        for v in _BUDGET_PRESETS
    ]
    time_row = [
        InlineKeyboardButton(text=f"🕐 {v}", callback_data=f"menu:settings:bt:{v.replace(':', '')}")
        for v in _BRIEF_TIME_PRESETS
    ]
    return InlineKeyboardMarkup(inline_keyboard=[threshold_row, budget_row, time_row, [_BACK_BUTTON]])


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard())


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await message.answer("Главное меню:", reply_markup=main_menu_keyboard())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu_keyboard())


async def _show(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup) -> None:
    message = callback.message
    if message is not None and hasattr(message, "edit_text"):
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except Exception:
            pass
    if message is not None and hasattr(message, "answer"):
        await message.answer(text, reply_markup=keyboard)


async def _apply_settings_preset(conn: Any, kind: str, raw_value: str, scheduler: Any) -> None:
    if kind == "th":
        await runtime_settings.set_score_threshold(conn, float(raw_value))
    elif kind == "mb":
        await runtime_settings.set_min_budget_rub(conn, int(raw_value))
    elif kind == "bt" and len(raw_value) == 4 and raw_value.isdigit():
        time_str = f"{raw_value[:2]}:{raw_value[2:]}"
        await runtime_settings.set_daily_brief_time(conn, time_str)
        if scheduler is not None:
            try:
                scheduler.reschedule_job(
                    "daily_brief",
                    trigger=CronTrigger(hour=int(raw_value[:2]), minute=int(raw_value[2:])),
                )
            except Exception:
                logger.exception("reschedule_daily_brief_failed")


@router.callback_query(F.data.startswith("menu:"))
async def handle_menu_callback(
    callback: CallbackQuery,
    db_path: Path,
    config_dir: Path,
    settings: Settings,
    scheduler: Any = None,
) -> None:
    data = callback.data or ""
    _, _, rest = data.partition(":")
    parts = rest.split(":")
    action = parts[0] if parts else ""

    await callback.answer()

    if action == "main":
        await _show(callback, "Главное меню:", main_menu_keyboard())
        return
    if action == "help":
        await _show(callback, HELP_TEXT, main_menu_keyboard())
        return

    conn = await get_connection(db_path)
    try:
        if action == "brief":
            text = await bot_module.brief_text(conn, config_dir, settings)
            await _show(callback, text, back_keyboard())
        elif action == "stats":
            if len(parts) > 1 and parts[1].isdigit():
                text = await bot_module.stats_text(conn, int(parts[1]))
                await _show(callback, text, back_keyboard())
            else:
                await _show(callback, "Статистика за период:", stats_menu_keyboard())
        elif action == "crm":
            text = await bot_module.crm_text(conn)
            await _show(callback, text, back_keyboard())
        elif action == "income":
            text = await bot_module.income_text(conn)
            await _show(callback, text, back_keyboard())
        elif action == "templates":
            await _show(callback, bot_module.templates_list_text(config_dir), back_keyboard())
        elif action == "sources":
            text = await bot_module.sources_text(conn)
            await _show(callback, text, back_keyboard())
        elif action == "settings":
            if len(parts) >= 3:
                await _apply_settings_preset(conn, parts[1], parts[2], scheduler)
            text = await bot_module.settings_text(conn, config_dir, settings)
            await _show(callback, text, settings_menu_keyboard())
        else:
            await _show(callback, "Неизвестный раздел меню.", main_menu_keyboard())
    finally:
        await conn.close()
