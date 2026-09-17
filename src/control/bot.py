from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, get_args

import aiosqlite
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from apscheduler.triggers.cron import CronTrigger

from src.actions.brief import compose_daily_brief, format_income_line
from src.actions.materializer import materialize_due_actions
from src.control.chat_config import add_runtime_chat
from src.control.prompts import load_prompts
from src.control.templates import load_templates
from src.core import repository, runtime_settings
from src.core.config import Settings
from src.core.db import get_connection
from src.core.models import CompanyStatus, Outcome
from src.core.yaml_config import load_actions_config, load_keywords_config
from src.crm import service as crm_service
from src.export.exporter import export_leads, fetch_export_rows, render_ai_handoff
from src.export.stats import format_stats_message
from src.notifier.keyboard import CALLBACK_PREFIX

logger = logging.getLogger("lead_radar.control.bot")

router = Router(name="lead_radar")

_VALID_OUTCOMES = set(get_args(Outcome))
_OUTCOME_LABELS = {"replied": "Ответил", "ignored": "Мимо"}
_VALID_COMPANY_STATUSES = set(get_args(CompanyStatus))


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


async def sources_text(conn: aiosqlite.Connection) -> str:
    sources = await repository.list_sources(conn)
    if not sources:
        return "Источников пока нет."

    lines = []
    for source in sources:
        flag = "🟢" if source["enabled"] and not source["consecutive_failures"] else "🔴"
        lines.append(
            f"{flag} {source['id']} (tier {source['tier']}), "
            f"ok: {source['last_ok_at'] or '-'}, ошибок подряд: {source['consecutive_failures']}"
        )
    return "\n".join(lines)


@router.message(Command("sources"))
async def cmd_sources(message: Message, db_path: Path) -> None:
    conn = await get_connection(db_path)
    try:
        text = await sources_text(conn)
    finally:
        await conn.close()
    await message.answer(text)


@router.message(Command("pause"))
async def cmd_pause(message: Message, db_path: Path) -> None:
    conn = await get_connection(db_path)
    try:
        await repository.set_system_state(conn, "collecting_paused", "1")
    finally:
        await conn.close()
    await message.answer("Сбор лидов приостановлен. /resume - включить обратно.")


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


async def brief_text(conn: aiosqlite.Connection, config_dir: Path, settings: Settings) -> str:
    today = date.today()
    actions_config = load_actions_config(config_dir)
    await materialize_due_actions(conn, actions_config, today)
    threshold = await runtime_settings.get_score_threshold(conn, settings)
    return await compose_daily_brief(conn, today, threshold)


@router.message(Command("brief"))
async def cmd_brief(message: Message, db_path: Path, config_dir: Path, settings: Settings) -> None:
    conn = await get_connection(db_path)
    try:
        text = await brief_text(conn, config_dir, settings)
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


@router.message(Command("export"))
async def cmd_export(message: Message, db_path: Path) -> None:
    parts = (message.text or "").split()[1:]
    days = int(parts[0]) if parts and parts[0].isdigit() else 30

    conn = await get_connection(db_path)
    try:
        content = await export_leads(conn, days, "csv")
    finally:
        await conn.close()

    filename = f"lead_radar_export_{days}d.csv"
    await message.answer_document(BufferedInputFile(content, filename=filename))


@router.message(Command("export_ai"))
async def cmd_export_ai(message: Message, db_path: Path, config_dir: Path) -> None:
    parts = (message.text or "").split()[1:]
    days = int(parts[0]) if parts and parts[0].isdigit() else 30

    conn = await get_connection(db_path)
    try:
        rows = await fetch_export_rows(conn, days, ai_assistable_only=True)
    finally:
        await conn.close()

    if not rows:
        await message.answer(
            f"За {days} дн. нет лидов, помеченных как выполнимые с помощью ИИ (см. /ai_leads)."
        )
        return

    prompts = load_prompts(config_dir)
    intro = str((prompts.get("lead_batch_for_ai") or {}).get("text", "")).strip()
    content = render_ai_handoff(rows, intro)

    filename = f"lead_radar_ai_export_{days}d.txt"
    await message.answer_document(BufferedInputFile(content, filename=filename))


async def stats_text(conn: aiosqlite.Connection, days: int) -> str:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    conversion = await repository.get_source_conversion_stats(conn, since)
    budgets = await repository.get_budget_distribution(conn, since)
    return format_stats_message(f"{days} дн.", conversion, budgets)


@router.message(Command("stats"))
async def cmd_stats(message: Message, db_path: Path) -> None:
    parts = (message.text or "").split()[1:]
    period = parts[0] if parts else "7d"
    days = 30 if period == "30d" else 7

    conn = await get_connection(db_path)
    try:
        text = await stats_text(conn, days)
    finally:
        await conn.close()
    await message.answer(text)


async def ai_leads_text(conn: aiosqlite.Connection) -> str:
    leads = await repository.get_recent_ai_assistable_leads(conn)
    if not leads:
        return (
            "Пока нет лидов, помеченных как выполнимые с помощью ИИ. Критерии - "
            "config/keywords.yaml -> ai_assistable."
        )

    lines = [f"🤖 Лиды, которые может закрыть ИИ ({len(leads)}):"]
    for lead in leads:
        amount = lead.budget_max if lead.budget_max is not None else lead.budget_min
        budget = f"{amount} {lead.budget_currency or ''}".strip() if amount is not None else "бюджет не указан"
        title = (lead.title or lead.text or "").strip()
        if len(title) > 80:
            title = title[:80].rstrip() + "..."
        lines.append(f"[{lead.id}] {title} - {budget} ({lead.source_id})")
    return "\n".join(lines)


@router.message(Command("ai_leads"))
async def cmd_ai_leads(message: Message, db_path: Path) -> None:
    conn = await get_connection(db_path)
    try:
        text = await ai_leads_text(conn)
    finally:
        await conn.close()
    await message.answer(text)


_COMPANY_STATUS_LABELS = {
    "new": "новый",
    "contacted": "написал",
    "negotiating": "переговоры",
    "won": "выиграно",
    "lost": "потеряно",
    "on_hold": "пауза",
}


async def crm_text(conn: aiosqlite.Connection) -> str:
    companies = await repository.list_companies(conn, open_only=True)
    lines = []
    for company in companies:
        next_touch = await repository.get_open_action_for_company(conn, company.id) if company.id else None
        due = f", след. касание: {next_touch.due_date}" if next_touch and next_touch.due_date else ""
        status_label = _COMPANY_STATUS_LABELS.get(company.status, company.status)
        lines.append(f"[{company.id}] {company.name} - {status_label}{due}")

    if not lines:
        return "В CRM пока нет компаний. Добавить: /crm_add <название>"
    return "Компании в работе:\n" + "\n".join(lines)


@router.message(Command("crm"))
async def cmd_crm(message: Message, db_path: Path) -> None:
    conn = await get_connection(db_path)
    try:
        text = await crm_text(conn)
    finally:
        await conn.close()
    await message.answer(text)


@router.message(Command("crm_add"))
async def cmd_crm_add(message: Message, db_path: Path) -> None:
    text = message.text or ""
    _, _, name = text.partition(" ")
    name = name.strip()
    if not name:
        await message.answer("Использование: /crm_add <название компании>")
        return

    conn = await get_connection(db_path)
    try:
        company_id = await crm_service.add_company(conn, name=name)
    finally:
        await conn.close()
    await message.answer(f"Добавлено в CRM: [{company_id}] {name}. Первое касание - сегодня.")


@router.message(Command("crm_touch"))
async def cmd_crm_touch(message: Message, db_path: Path) -> None:
    parts = (message.text or "").split(maxsplit=3)[1:]
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].lstrip("-").isdigit():
        await message.answer("Использование: /crm_touch <id> <дней до следующего касания> [результат]")
        return

    company_id = int(parts[0])
    next_days = int(parts[1])
    result = parts[2] if len(parts) > 2 else None

    conn = await get_connection(db_path)
    try:
        if await repository.get_company(conn, company_id) is None:
            await message.answer(f"Компания [{company_id}] не найдена.")
            return
        await crm_service.touch_company(
            conn, company_id=company_id, next_touch_in_days=next_days, result=result
        )
    finally:
        await conn.close()
    await message.answer(f"Записано: [{company_id}], следующее касание через {next_days} дн.")


@router.message(Command("crm_status"))
async def cmd_crm_status(message: Message, db_path: Path) -> None:
    parts = (message.text or "").split()[1:]
    if len(parts) != 2 or not parts[0].isdigit() or parts[1] not in _VALID_COMPANY_STATUSES:
        statuses = ", ".join(sorted(_VALID_COMPANY_STATUSES))
        await message.answer(f"Использование: /crm_status <id> <статус>\nСтатусы: {statuses}")
        return

    company_id, status = int(parts[0]), parts[1]
    conn = await get_connection(db_path)
    try:
        if await repository.get_company(conn, company_id) is None:
            await message.answer(f"Компания [{company_id}] не найдена.")
            return
        await crm_service.set_company_status(conn, company_id, status)
    finally:
        await conn.close()
    await message.answer(f"[{company_id}] - новый статус: {_COMPANY_STATUS_LABELS.get(status, status)}")


@router.message(Command("income"))
async def cmd_income(message: Message, db_path: Path) -> None:
    parts = (message.text or "").split(maxsplit=2)[1:]
    if not parts or not parts[0].isdigit():
        await message.answer("Использование: /income <сумма> [заметка]")
        return

    amount = int(parts[0])
    note = parts[1] if len(parts) > 1 else None

    conn = await get_connection(db_path)
    try:
        await repository.insert_payment(conn, amount=amount, received_at=date.today(), note=note)
    finally:
        await conn.close()
    await message.answer(f"Записано поступление: {amount} ₽")


@router.message(Command("goal"))
async def cmd_goal(message: Message, db_path: Path) -> None:
    parts = (message.text or "").split()[1:]
    if not parts or not parts[0].isdigit():
        await message.answer("Использование: /goal <сумма в месяц>")
        return

    amount = int(parts[0])
    conn = await get_connection(db_path)
    try:
        await repository.set_system_state(conn, repository.MONTHLY_GOAL_KEY, str(amount))
    finally:
        await conn.close()
    await message.answer(f"Цель на месяц: {amount} ₽")


async def income_text(conn: aiosqlite.Connection) -> str:
    line = await format_income_line(conn, date.today())
    return f"{line}\n\nЗаписать: /income <сумма> [заметка]\nЦель: /goal <сумма>"


def templates_list_text(config_dir: Path) -> str:
    templates = load_templates(config_dir)
    if not templates:
        return "Шаблонов пока нет. Добавь их в config/templates.yaml."

    lines = [f"• {name} - {tmpl.get('title', name)}" for name, tmpl in templates.items()]
    return "Доступные шаблоны:\n" + "\n".join(lines) + "\n\nПолучить текст: /template <имя>"


@router.message(Command("templates"))
async def cmd_templates(message: Message, config_dir: Path) -> None:
    await message.answer(templates_list_text(config_dir))


@router.message(Command("template"))
async def cmd_template(message: Message, config_dir: Path) -> None:
    parts = (message.text or "").split(maxsplit=1)[1:]
    if not parts:
        await message.answer("Использование: /template <имя>")
        return

    name = parts[0].strip()
    templates = load_templates(config_dir)
    template = templates.get(name)
    if template is None:
        await message.answer(f"Шаблон «{name}» не найден. Список: /templates")
        return

    await message.answer(str(template.get("text", "")).strip())


def prompts_list_text(config_dir: Path) -> str:
    prompts = load_prompts(config_dir)
    if not prompts:
        return "Промптов пока нет. Добавь их в config/prompts.yaml."

    lines = [f"• {name} - {p.get('title', name)}" for name, p in prompts.items()]
    return "Промпты для ИИ:\n" + "\n".join(lines) + "\n\nПолучить текст: /prompt <имя>"


@router.message(Command("prompts"))
async def cmd_prompts(message: Message, config_dir: Path) -> None:
    await message.answer(prompts_list_text(config_dir))


@router.message(Command("prompt"))
async def cmd_prompt(message: Message, config_dir: Path) -> None:
    parts = (message.text or "").split(maxsplit=1)[1:]
    if not parts:
        await message.answer("Использование: /prompt <имя>")
        return

    name = parts[0].strip()
    prompts = load_prompts(config_dir)
    prompt = prompts.get(name)
    if prompt is None:
        await message.answer(f"Промпт «{name}» не найден. Список: /prompts")
        return

    await message.answer(str(prompt.get("text", "")).strip())


async def hh_status_text(conn: aiosqlite.Connection) -> str:
    applications = await repository.list_hh_applications(conn)
    if not applications:
        return (
            "Откликов на hh.ru пока нет в базе. Если HH_CLIENT_ID/SECRET/токены заполнены в "
            ".env, синхронизация подтянет их автоматически; иначе см. "
            "python -m scripts.hh_oauth_login в README.md."
        )
    lines = [f"• {a.vacancy_title or a.vacancy_id or a.id} - {a.state or '?'}" for a in applications]
    return "Отклики на hh.ru:\n" + "\n".join(lines)


@router.message(Command("hh_status"))
async def cmd_hh_status(message: Message, db_path: Path) -> None:
    conn = await get_connection(db_path)
    try:
        text = await hh_status_text(conn)
    finally:
        await conn.close()
    await message.answer(text)


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


async def settings_text(conn: aiosqlite.Connection, config_dir: Path, settings: Settings) -> str:
    keywords_config = load_keywords_config(config_dir)
    threshold = await runtime_settings.get_score_threshold(conn, settings)
    min_budget = await runtime_settings.get_min_budget_rub(conn, keywords_config)
    brief_time = await runtime_settings.get_daily_brief_time(conn, settings)
    return (
        "⚙️ Текущие настройки:\n"
        f"• Порог уведомления: {threshold:.0f} - /set_threshold <число>\n"
        f"• Мин. бюджет: {min_budget} ₽ - /set_budget_floor <число>\n"
        f"• Время брифа: {brief_time} - /set_brief_time <ЧЧ:ММ>"
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message, db_path: Path, config_dir: Path, settings: Settings) -> None:
    conn = await get_connection(db_path)
    try:
        text = await settings_text(conn, config_dir, settings)
    finally:
        await conn.close()
    await message.answer(text)


@router.message(Command("set_threshold"))
async def cmd_set_threshold(message: Message, db_path: Path) -> None:
    parts = (message.text or "").split()[1:]
    if not parts or not parts[0].lstrip("-").isdigit():
        await message.answer("Использование: /set_threshold <число>")
        return

    value = float(parts[0])
    conn = await get_connection(db_path)
    try:
        await runtime_settings.set_score_threshold(conn, value)
    finally:
        await conn.close()
    await message.answer(f"Порог уведомления: {value:.0f}. Действует сразу, без перезапуска.")


@router.message(Command("set_budget_floor"))
async def cmd_set_budget_floor(message: Message, db_path: Path) -> None:
    parts = (message.text or "").split()[1:]
    if not parts or not parts[0].isdigit():
        await message.answer("Использование: /set_budget_floor <число>")
        return

    value = int(parts[0])
    conn = await get_connection(db_path)
    try:
        await runtime_settings.set_min_budget_rub(conn, value)
    finally:
        await conn.close()
    await message.answer(f"Минимальный бюджет: {value} ₽. Действует сразу, без перезапуска.")


@router.message(Command("set_brief_time"))
async def cmd_set_brief_time(message: Message, db_path: Path, scheduler: Any = None) -> None:
    parts = (message.text or "").split()[1:]
    if not parts or not _TIME_RE.match(parts[0]):
        await message.answer("Использование: /set_brief_time <ЧЧ:ММ>, например /set_brief_time 09:30")
        return

    time_str = parts[0]
    conn = await get_connection(db_path)
    try:
        await runtime_settings.set_daily_brief_time(conn, time_str)
    finally:
        await conn.close()

    applied_now = False
    if scheduler is not None:
        hour, minute = time_str.split(":")
        try:
            scheduler.reschedule_job(
                "daily_brief", trigger=CronTrigger(hour=int(hour), minute=int(minute))
            )
            applied_now = True
        except Exception:
            logger.exception("reschedule_daily_brief_failed")

    suffix = "применится сразу" if applied_now else "применится после перезапуска процесса"
    await message.answer(f"Время брифа: {time_str} ({suffix}).")
