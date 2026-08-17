from __future__ import annotations

from datetime import date

import aiosqlite

from src.core import repository
from src.core.yaml_config import ActionsConfig

_INTERVAL_DAYS = {"daily": 1, "every_3_days": 3, "weekly": 7}


async def materialize_due_actions(
    conn: aiosqlite.Connection, actions_config: ActionsConfig, today: date
) -> int:
    """Превращает шаблоны actions.yaml в строки actions при наступлении срока.
    Идемпотентно: повторный вызов в тот же день не плодит дубликаты."""
    created = 0
    created += await _materialize_recurring(conn, actions_config, today)
    created += await _materialize_seasonal(conn, actions_config, today)
    created += await _materialize_one_off(conn, actions_config)
    return created


async def _materialize_recurring(conn: aiosqlite.Connection, actions_config: ActionsConfig, today: date) -> int:
    created = 0
    for item in actions_config.recurring:
        interval = _INTERVAL_DAYS.get(item.recurrence, 1)
        latest = await repository.get_latest_action_by_title(conn, item.title)

        should_create = latest is None
        if latest is not None and latest.status in ("done", "dropped"):
            reference = latest.completed_at.date() if latest.completed_at else (
                latest.created_at.date() if latest.created_at else today
            )
            should_create = (today - reference).days >= interval

        if should_create:
            await repository.insert_action(
                conn,
                title=item.title,
                priority=item.priority,
                due_date=today,
                recurrence=item.recurrence,
                expected_value=item.expected_value,
            )
            created += 1
    return created


async def _materialize_seasonal(conn: aiosqlite.Connection, actions_config: ActionsConfig, today: date) -> int:
    created = 0
    month_day = today.strftime("%m-%d")
    for item in actions_config.seasonal:
        if item.activate_on != month_day:
            continue
        if await repository.action_exists_this_year(conn, item.title, today.year):
            continue
        await repository.insert_action(conn, title=item.title, priority=item.priority, due_date=today)
        created += 1
    return created


async def _materialize_one_off(conn: aiosqlite.Connection, actions_config: ActionsConfig) -> int:
    created = 0
    for item in actions_config.one_off:
        existing = await repository.get_latest_action_by_title(conn, item.title)
        if existing is not None:
            continue
        due = date.fromisoformat(item.due_date) if item.due_date else None
        await repository.insert_action(conn, title=item.title, priority=item.priority, due_date=due)
        created += 1
    return created
