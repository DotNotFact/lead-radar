from __future__ import annotations

from datetime import date, timedelta

import aiosqlite

from src.core import repository
from src.core.models import Action

ESCALATION_THRESHOLD = 3


def _format_action_line(action: Action, escalate: bool) -> str:
    marker = "🔴" if escalate else "•"
    line = f"{marker} [{action.id}] {action.title} (приоритет {action.priority})"
    if escalate and action.expected_value:
        line += f"\n   ⚠ {action.expected_value} (откладывалось {action.snooze_count} раз)"
    return line


def _month_bounds(today: date) -> tuple[date, date]:
    start = today.replace(day=1)
    next_month = start.replace(day=28) + timedelta(days=4)
    end = next_month.replace(day=1)
    return start, end


async def format_income_line(conn: aiosqlite.Connection, today: date) -> str:
    """Отдельная функция, чтобы то же самое можно было показать по кнопке "Доход" в меню,
    не только в ежедневном брифе."""
    month_start, month_end = _month_bounds(today)
    income = await repository.get_income_for_period(conn, month_start, month_end)
    goal_raw = await repository.get_system_state(conn, repository.MONTHLY_GOAL_KEY)
    if goal_raw:
        goal = int(goal_raw)
        percent = (income / goal * 100) if goal else 0
        return f"**Доход за месяц:** {income} из {goal} ₽ ({percent:.0f}%)"
    return f"**Доход за месяц:** {income} ₽ (цель не задана, /goal <сумма>)"


async def compose_daily_brief(conn: aiosqlite.Connection, today: date, threshold: float) -> str:
    today_actions, overdue_actions = await repository.get_actions_for_brief(conn, today)

    sections: list[str] = [f"📋 Бриф на {today.isoformat()}"]

    if today_actions:
        sections.append("**Действия на сегодня:**\n" + "\n".join(
            _format_action_line(a, False) for a in today_actions
        ))
    else:
        sections.append("На сегодня действий нет.")

    if overdue_actions:
        sections.append("**Просроченное:**\n" + "\n".join(
            _format_action_line(a, a.snooze_count >= ESCALATION_THRESHOLD) for a in overdue_actions
        ))

    stats = await repository.get_daily_stats(conn, today, threshold)
    sections.append(
        "**Итоги суток:**\n"
        f"• собрано лидов: {stats['collected']}\n"
        f"• прошло порог ({threshold:.0f}+): {stats['above_threshold']}\n"
        f"• отвечено: {stats['replied']}\n"
        f"• лучший источник: {stats['best_source'] or '-'}"
    )

    sections.append(await format_income_line(conn, today))

    degraded = await repository.get_degraded_sources(conn)
    if degraded:
        lines = []
        for s in degraded:
            detail = s["last_error"] or f"ошибок подряд: {s['consecutive_failures']}"
            lines.append(f"⚠ {s['id']}: {detail}")
        sections.append("**Здоровье источников:**\n" + "\n".join(lines))

    return "\n\n".join(sections)
