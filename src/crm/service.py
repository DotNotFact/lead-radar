from __future__ import annotations

from datetime import date, timedelta

import aiosqlite

from src.core import repository

_TOUCH_ACTION_PRIORITY = 2  # тот же порядок величины, что и у /todo (priority=3) - чуть важнее


async def add_company(
    conn: aiosqlite.Connection,
    *,
    name: str,
    contact_person: str | None = None,
    contact_info: str | None = None,
    first_touch_in_days: int = 0,
) -> int:
    """Создаёт компанию и сразу ставит первое напоминание о касании в очередь actions."""
    company_id = await repository.insert_company(
        conn, name=name, contact_person=contact_person, contact_info=contact_info
    )
    due = date.today() + timedelta(days=first_touch_in_days)
    await repository.insert_action(
        conn,
        title=f"Связаться: {name}",
        priority=_TOUCH_ACTION_PRIORITY,
        due_date=due,
        company_id=company_id,
    )
    return company_id


async def touch_company(
    conn: aiosqlite.Connection,
    *,
    company_id: int,
    next_touch_in_days: int | None,
    result: str | None = None,
) -> None:
    """Фиксирует результат текущего касания: закрывает открытое напоминание (если есть),
    записывает результат, при необходимости ставит следующее напоминание."""
    open_action = await repository.get_open_action_for_company(conn, company_id)
    if open_action is not None and open_action.id is not None:
        await repository.mark_action_done(conn, open_action.id)

    if result:
        await repository.update_company_result(conn, company_id, result)

    if next_touch_in_days is not None:
        company = await repository.get_company(conn, company_id)
        name = company.name if company else str(company_id)
        due = date.today() + timedelta(days=next_touch_in_days)
        await repository.insert_action(
            conn,
            title=f"Связаться: {name}",
            priority=_TOUCH_ACTION_PRIORITY,
            due_date=due,
            company_id=company_id,
        )


async def set_company_status(conn: aiosqlite.Connection, company_id: int, status: str) -> None:
    """Смена статуса. Для won/lost закрывает все ещё открытые напоминания о касании -
    дальше гнаться не за чем."""
    await repository.update_company_status(conn, company_id, status)
    if status in ("won", "lost"):
        open_action = await repository.get_open_action_for_company(conn, company_id)
        if open_action is not None and open_action.id is not None:
            await repository.mark_action_done(conn, open_action.id)
