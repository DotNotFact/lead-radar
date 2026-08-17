from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import get_args

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from src.actions.brief import compose_daily_brief
from src.actions.materializer import materialize_due_actions
from src.control.chat_config import add_runtime_chat
from src.core import repository
from src.core.db import get_connection
from src.core.models import Outcome
from src.core.yaml_config import load_actions_config
from src.notifier.keyboard import CALLBACK_PREFIX

logger = logging.getLogger("lead_radar.control.bot")

router = Router(name="lead_radar")

_VALID_OUTCOMES = set(get_args(Outcome))
_OUTCOME_LABELS = {"replied": "Ответил", "ignored": "Мимо"}


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp


@router.callback_query(F.data.startswith(f"{CALLBACK_PREFIX}:"))
async def handle_outcome_callback(callback: CallbackQuery, db_path: Path) -> None:
    data = callback.data or ""
    _, _, rest = data.partition(":")
    outcome_value, _, lead_id_str = rest.partition(":")

    if outcome_value not in _VALID_OUTCOMES or not lead_id_str.isdigit():
        await callback.answer("Некорректные данные кнопки")
        return

    lead_id = int(lead_id_str)
    conn = await get_connection(db_path)
    try:
        await repository.record_outcome(conn, lead_id, outcome_value)  # type: ignore[arg-type]
    finally:
        await conn.close()

    await callback.answer(_OUTCOME_LABELS.get(outcome_value, "Записано"))
    if callback.message is not None and hasattr(callback.message, "edit_reply_markup"):
        await callback.message.edit_reply_markup(reply_markup=None)

    logger.info("outcome_recorded", extra={"lead_id": lead_id, "outcome": outcome_value})


@router.message(Command("health"))
async def cmd_health(message: Message, db_path: Path) -> None:
    conn = await get_connection(db_path)
    try:
        sources = await repository.list_sources(conn)
    finally:
        await conn.close()

    if not sources:
        await message.answer("Источников пока нет.")
        return

    lines = ["Диагностика источников:"]
    for source in sources:
        status = "OK" if source["enabled"] and not source["consecutive_failures"] else (
            "выключен" if not source["enabled"] else f"деградирует ({source['consecutive_failures']} подряд)"
        )
        lines.append(f"• {source['id']}: {status}")
    await message.answer("\n".join(lines))


@router.message(Command("sources"))
async def cmd_sources(message: Message, db_path: Path) -> None:
    conn = await get_connection(db_path)
    try:
        sources = await repository.list_sources(conn)
    finally:
        await conn.close()

    if not sources:
        await message.answer("Источников пока нет.")
        return

    lines = []
    for source in sources:
        flag = "🟢" if source["enabled"] and not source["consecutive_failures"] else "🔴"
        lines.append(
            f"{flag} {source['id']} (tier {source['tier']}), "
            f"ok: {source['last_ok_at'] or '—'}, ошибок подряд: {source['consecutive_failures']}"
        )
    await message.answer("\n".join(lines))


@router.message(Command("pause"))
async def cmd_pause(message: Message, db_path: Path) -> None:
    conn = await get_connection(db_path)
    try:
        await repository.set_system_state(conn, "collecting_paused", "1")
    finally:
        await conn.close()
    await message.answer("Сбор лидов приостановлен. /resume — включить обратно.")


@router.message(Command("resume"))
async def cmd_resume(message: Message, db_path: Path) -> None:
    conn = await get_connection(db_path)
    try:
        await repository.set_system_state(conn, "collecting_paused", "0")
    finally:
        await conn.close()
    await message.answer("Сбор лидов возобновлён.")


@router.message(Command("addchat"))
async def cmd_addchat(message: Message, config_dir: Path) -> None:
    text = (message.text or "")
    _, _, handle = text.partition(" ")
    handle = handle.strip()
    if not handle:
        await message.answer("Использование: /addchat @channel_or_link")
        return

    added = add_runtime_chat(config_dir, handle)
    if added:
        await message.answer(f"Добавлено: {handle}. Появится в опросе после перезапуска сборщика.")
    else:
        await message.answer(f"{handle} уже в списке.")


@router.message(Command("brief"))
async def cmd_brief(message: Message, db_path: Path, config_dir: Path, score_threshold: float) -> None:
    today = date.today()
    conn = await get_connection(db_path)
    try:
        actions_config = load_actions_config(config_dir)
        await materialize_due_actions(conn, actions_config, today)
        text = await compose_daily_brief(conn, today, score_threshold)
    finally:
        await conn.close()
    await message.answer(text)


@router.message(Command("todo"))
async def cmd_todo(message: Message, db_path: Path) -> None:
    text = (message.text or "")
    _, _, title = text.partition(" ")
    title = title.strip()
    if not title:
        await message.answer("Использование: /todo <текст задачи>")
        return

    conn = await get_connection(db_path)
    try:
        action_id = await repository.insert_action(
            conn, title=title, priority=3, due_date=date.today()
        )
    finally:
        await conn.close()
    await message.answer(f"Добавлено в очередь: [{action_id}] {title}")


@router.message(Command("done"))
async def cmd_done(message: Message, db_path: Path) -> None:
    action_id = _parse_id_arg(message.text)
    if action_id is None:
        await message.answer("Использование: /done <id>")
        return

    conn = await get_connection(db_path)
    try:
        await repository.mark_action_done(conn, action_id)
    finally:
        await conn.close()
    await message.answer(f"Готово: [{action_id}]")


@router.message(Command("snooze"))
async def cmd_snooze(message: Message, db_path: Path) -> None:
    text = (message.text or "")
    parts = text.split()[1:]
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        await message.answer("Использование: /snooze <id> <дней>")
        return

    action_id, days = int(parts[0]), int(parts[1])
    conn = await get_connection(db_path)
    try:
        await repository.snooze_action(conn, action_id, days)
    finally:
        await conn.close()
    await message.answer(f"Отложено: [{action_id}] на {days} дн.")


def _parse_id_arg(text: str | None) -> int | None:
    parts = (text or "").split()[1:]
    if len(parts) != 1 or not parts[0].isdigit():
        return None
    return int(parts[0])
