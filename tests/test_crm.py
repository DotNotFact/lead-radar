from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from src.core import repository
from src.core.db import apply_migrations, get_connection
from src.crm import service as crm_service

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


async def _db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    return db_path


@pytest.mark.asyncio
async def test_add_company_creates_company_and_first_touch_action(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)

    company_id = await crm_service.add_company(conn, name="Acme LLC")

    company = await repository.get_company(conn, company_id)
    action = await repository.get_open_action_for_company(conn, company_id)
    await conn.close()

    assert company is not None
    assert company.name == "Acme LLC"
    assert company.status == "new"
    assert action is not None
    assert action.due_date == date.today()
    assert "Acme LLC" in action.title


@pytest.mark.asyncio
async def test_touch_company_closes_old_action_and_schedules_next(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    company_id = await crm_service.add_company(conn, name="Beta Inc")
    first_action = await repository.get_open_action_for_company(conn, company_id)
    assert first_action is not None and first_action.id is not None

    await crm_service.touch_company(
        conn, company_id=company_id, next_touch_in_days=5, result="Обещали подумать"
    )

    closed_action = await repository.get_action(conn, first_action.id)
    new_open_action = await repository.get_open_action_for_company(conn, company_id)
    company = await repository.get_company(conn, company_id)
    await conn.close()

    assert closed_action is not None and closed_action.status == "done"
    assert new_open_action is not None
    assert new_open_action.id != first_action.id
    assert new_open_action.due_date == date.today() + timedelta(days=5)
    assert company is not None and company.result == "Обещали подумать"


@pytest.mark.asyncio
async def test_touch_company_without_next_touch_leaves_no_open_action(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    company_id = await crm_service.add_company(conn, name="Gamma")

    await crm_service.touch_company(conn, company_id=company_id, next_touch_in_days=None, result="Отказ")

    open_action = await repository.get_open_action_for_company(conn, company_id)
    await conn.close()
    assert open_action is None


@pytest.mark.asyncio
async def test_set_company_status_won_closes_open_action(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    company_id = await crm_service.add_company(conn, name="Delta")
    open_action = await repository.get_open_action_for_company(conn, company_id)
    assert open_action is not None and open_action.id is not None

    await crm_service.set_company_status(conn, company_id, "won")

    company = await repository.get_company(conn, company_id)
    action = await repository.get_action(conn, open_action.id)
    await conn.close()

    assert company is not None and company.status == "won"
    assert action is not None and action.status == "done"


@pytest.mark.asyncio
async def test_list_companies_open_only_excludes_won_and_lost(tmp_path: Path) -> None:
    db_path = await _db(tmp_path)
    conn = await get_connection(db_path)
    open_id = await crm_service.add_company(conn, name="Open Co")
    won_id = await crm_service.add_company(conn, name="Won Co")
    await crm_service.set_company_status(conn, won_id, "won")

    open_companies = await repository.list_companies(conn, open_only=True)
    all_companies = await repository.list_companies(conn, open_only=False)
    await conn.close()

    open_ids = {c.id for c in open_companies}
    assert open_id in open_ids
    assert won_id not in open_ids
    assert len(all_companies) == 2
