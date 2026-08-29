from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

import aiosqlite

from src.core.models import Action, Company, HhApplication, Lead, LeadOutcome, Outcome, Payment

_ACTION_COLUMNS = (
    "id, title, description, priority, due_date, recurrence, status, created_at, "
    "completed_at, snooze_count, expected_value, company_id"
)


def _row_to_action(row: aiosqlite.Row) -> Action:
    return Action(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        priority=row["priority"],
        due_date=date.fromisoformat(row["due_date"]) if row["due_date"] else None,
        recurrence=row["recurrence"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        snooze_count=row["snooze_count"],
        expected_value=row["expected_value"],
        company_id=row["company_id"],
    )

_LEAD_COLUMNS = (
    "id, source_id, external_id, url, title, text, published_at, collected_at, "
    "budget_min, budget_max, budget_currency, budget_confidence, stack_tags, "
    "content_hash, duplicate_of, score, author_handle, raw_meta, ai_assistable"
)


def _row_to_lead(row: aiosqlite.Row) -> Lead:
    return Lead(
        id=row["id"],
        source_id=row["source_id"],
        external_id=row["external_id"],
        url=row["url"],
        title=row["title"],
        text=row["text"],
        published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
        collected_at=datetime.fromisoformat(row["collected_at"]) if row["collected_at"] else None,
        budget_min=row["budget_min"],
        budget_max=row["budget_max"],
        budget_currency=row["budget_currency"],
        budget_confidence=row["budget_confidence"],
        stack_tags=json.loads(row["stack_tags"]) if row["stack_tags"] else [],
        content_hash=row["content_hash"],
        duplicate_of=row["duplicate_of"],
        score=row["score"],
        author_handle=row["author_handle"],
        raw_meta=json.loads(row["raw_meta"]) if row["raw_meta"] else {},
        ai_assistable=bool(row["ai_assistable"]),
    )


async def ensure_source(conn: aiosqlite.Connection, source_id: str, tier: int) -> None:
    await conn.execute(
        "INSERT INTO sources(id, tier, enabled) VALUES (?, ?, 1) "
        "ON CONFLICT(id) DO NOTHING",
        (source_id, tier),
    )
    await conn.commit()


async def mark_source_ok(conn: aiosqlite.Connection, source_id: str) -> None:
    await conn.execute(
        "UPDATE sources SET last_ok_at = ?, last_error = NULL, consecutive_failures = 0 WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), source_id),
    )
    await conn.commit()


async def mark_source_failed(conn: aiosqlite.Connection, source_id: str, error: str) -> None:
    await conn.execute(
        "UPDATE sources SET last_error = ?, consecutive_failures = consecutive_failures + 1 "
        "WHERE id = ?",
        (error, source_id),
    )
    await conn.commit()


async def get_last_published_at(conn: aiosqlite.Connection, source_id: str) -> datetime | None:
    cursor = await conn.execute(
        "SELECT MAX(published_at) FROM leads WHERE source_id = ?", (source_id,)
    )
    row = await cursor.fetchone()
    if row is None or row[0] is None:
        return None
    return datetime.fromisoformat(row[0])


async def insert_lead(conn: aiosqlite.Connection, lead: Lead) -> bool:
    """Возвращает True, если запись новая (не дубликат по source_id+external_id)."""
    cursor = await conn.execute(
        """
        INSERT OR IGNORE INTO leads (
            source_id, external_id, url, title, text, published_at, collected_at,
            budget_min, budget_max, budget_currency, budget_confidence,
            stack_tags, content_hash, duplicate_of, score, author_handle, raw_meta,
            ai_assistable
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lead.source_id,
            lead.external_id,
            lead.url,
            lead.title,
            lead.text,
            lead.published_at.isoformat() if lead.published_at else None,
            (lead.collected_at or datetime.now(timezone.utc)).isoformat(),
            lead.budget_min,
            lead.budget_max,
            lead.budget_currency,
            lead.budget_confidence,
            json.dumps(lead.stack_tags, ensure_ascii=False),
            lead.content_hash,
            lead.duplicate_of,
            lead.score,
            lead.author_handle,
            json.dumps(lead.raw_meta, ensure_ascii=False),
            int(lead.ai_assistable),
        ),
    )
    await conn.commit()
    return cursor.rowcount > 0


async def find_duplicate_by_hash(conn: aiosqlite.Connection, content_hash: str, exclude_source: str) -> int | None:
    """Ищет уже сохранённый лид с тем же хешем из другого источника (кросспост)."""
    cursor = await conn.execute(
        "SELECT id FROM leads WHERE content_hash = ? AND source_id != ? ORDER BY id LIMIT 1",
        (content_hash, exclude_source),
    )
    row = await cursor.fetchone()
    return int(row[0]) if row else None


async def count_leads(conn: aiosqlite.Connection, source_id: str | None = None) -> int:
    if source_id:
        cursor = await conn.execute("SELECT COUNT(*) FROM leads WHERE source_id = ?", (source_id,))
    else:
        cursor = await conn.execute("SELECT COUNT(*) FROM leads")
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def get_lead(conn: aiosqlite.Connection, lead_id: int) -> Lead | None:
    cursor = await conn.execute(f"SELECT {_LEAD_COLUMNS} FROM leads WHERE id = ?", (lead_id,))
    row = await cursor.fetchone()
    return _row_to_lead(row) if row else None


async def get_lead_by_external_id(conn: aiosqlite.Connection, source_id: str, external_id: str) -> Lead | None:
    cursor = await conn.execute(
        f"SELECT {_LEAD_COLUMNS} FROM leads WHERE source_id = ? AND external_id = ?",
        (source_id, external_id),
    )
    row = await cursor.fetchone()
    return _row_to_lead(row) if row else None


async def get_unnotified_leads_above_threshold(
    conn: aiosqlite.Connection, threshold: float, limit: int = 50
) -> list[Lead]:
    """Лиды выше порога уведомления, для которых ещё не отправлялось сообщение владельцу."""
    cursor = await conn.execute(
        f"""
        SELECT {_LEAD_COLUMNS} FROM leads
        WHERE score >= ?
          AND duplicate_of IS NULL
          AND id NOT IN (SELECT lead_id FROM lead_outcomes WHERE notified_at IS NOT NULL)
        ORDER BY published_at ASC
        LIMIT ?
        """,
        (threshold, limit),
    )
    rows = await cursor.fetchall()
    return [_row_to_lead(row) for row in rows]


async def get_recent_ai_assistable_leads(conn: aiosqlite.Connection, limit: int = 20) -> list[Lead]:
    """Лиды, помеченные как выполнимые с помощью ИИ (см. config/keywords.yaml -> ai_assistable),
    для команды /ai_leads. Не фильтрует по дубликатам/уведомлённости - это отдельный обзорный
    список, а не очередь уведомлений."""
    cursor = await conn.execute(
        f"""
        SELECT {_LEAD_COLUMNS} FROM leads
        WHERE ai_assistable = 1
        ORDER BY published_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = await cursor.fetchall()
    return [_row_to_lead(row) for row in rows]


async def record_notified(conn: aiosqlite.Connection, lead_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await conn.execute(
        "INSERT INTO lead_outcomes(lead_id, notified_at) VALUES (?, ?) "
        "ON CONFLICT(lead_id) DO UPDATE SET notified_at = excluded.notified_at",
        (lead_id, now),
    )
    await conn.commit()


async def record_outcome(conn: aiosqlite.Connection, lead_id: int, outcome: Outcome) -> None:
    now = datetime.now(timezone.utc).isoformat()
    replied_at = now if outcome in ("replied", "negotiating", "won") else None
    await conn.execute(
        """
        INSERT INTO lead_outcomes(lead_id, outcome, replied_at) VALUES (?, ?, ?)
        ON CONFLICT(lead_id) DO UPDATE SET
            outcome = excluded.outcome,
            replied_at = COALESCE(lead_outcomes.replied_at, excluded.replied_at)
        """,
        (lead_id, outcome, replied_at),
    )
    await conn.commit()


async def list_sources(conn: aiosqlite.Connection) -> list[dict[str, object]]:
    cursor = await conn.execute(
        "SELECT id, tier, enabled, last_ok_at, last_error, consecutive_failures FROM sources "
        "ORDER BY id"
    )
    rows = await cursor.fetchall()
    return [
        {
            "id": row["id"],
            "tier": row["tier"],
            "enabled": bool(row["enabled"]),
            "last_ok_at": row["last_ok_at"],
            "last_error": row["last_error"],
            "consecutive_failures": row["consecutive_failures"],
        }
        for row in rows
    ]


MONTHLY_GOAL_KEY = "monthly_income_goal"


async def get_system_state(conn: aiosqlite.Connection, key: str, default: str | None = None) -> str | None:
    cursor = await conn.execute("SELECT value FROM system_state WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row["value"] if row else default


async def set_system_state(conn: aiosqlite.Connection, key: str, value: str) -> None:
    await conn.execute(
        "INSERT INTO system_state(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    await conn.commit()


async def get_latest_action_by_title(conn: aiosqlite.Connection, title: str) -> Action | None:
    cursor = await conn.execute(
        f"SELECT {_ACTION_COLUMNS} FROM actions WHERE title = ? ORDER BY created_at DESC LIMIT 1",
        (title,),
    )
    row = await cursor.fetchone()
    return _row_to_action(row) if row else None


async def action_exists_this_year(conn: aiosqlite.Connection, title: str, year: int) -> bool:
    cursor = await conn.execute(
        "SELECT 1 FROM actions WHERE title = ? AND strftime('%Y', created_at) = ? LIMIT 1",
        (title, str(year)),
    )
    return await cursor.fetchone() is not None


async def insert_action(
    conn: aiosqlite.Connection,
    *,
    title: str,
    priority: int,
    due_date: date | None,
    recurrence: str | None = None,
    expected_value: str | None = None,
    description: str | None = None,
    company_id: int | None = None,
) -> int:
    cursor = await conn.execute(
        "INSERT INTO actions(title, description, priority, due_date, recurrence, status, "
        "created_at, snooze_count, expected_value, company_id) "
        "VALUES (?, ?, ?, ?, ?, 'pending', ?, 0, ?, ?)",
        (
            title,
            description,
            priority,
            due_date.isoformat() if due_date else None,
            recurrence,
            datetime.now(timezone.utc).isoformat(),
            expected_value,
            company_id,
        ),
    )
    await conn.commit()
    return int(cursor.lastrowid or 0)


async def get_action(conn: aiosqlite.Connection, action_id: int) -> Action | None:
    cursor = await conn.execute(f"SELECT {_ACTION_COLUMNS} FROM actions WHERE id = ?", (action_id,))
    row = await cursor.fetchone()
    return _row_to_action(row) if row else None


async def get_actions_for_brief(conn: aiosqlite.Connection, today: date) -> tuple[list[Action], list[Action]]:
    """Возвращает (действия на сегодня, просроченные) - только с проставленным due_date."""
    today_str = today.isoformat()
    cursor = await conn.execute(
        f"SELECT {_ACTION_COLUMNS} FROM actions WHERE status = 'pending' AND due_date = ? "
        "ORDER BY priority ASC",
        (today_str,),
    )
    today_rows = await cursor.fetchall()

    cursor = await conn.execute(
        f"SELECT {_ACTION_COLUMNS} FROM actions WHERE status = 'pending' AND due_date < ? "
        "ORDER BY priority ASC",
        (today_str,),
    )
    overdue_rows = await cursor.fetchall()

    return [_row_to_action(r) for r in today_rows], [_row_to_action(r) for r in overdue_rows]


async def mark_action_done(
    conn: aiosqlite.Connection, action_id: int, completed_at: datetime | None = None
) -> None:
    await conn.execute(
        "UPDATE actions SET status = 'done', completed_at = ? WHERE id = ?",
        ((completed_at or datetime.now(timezone.utc)).isoformat(), action_id),
    )
    await conn.commit()


async def snooze_action(conn: aiosqlite.Connection, action_id: int, days: int) -> None:
    cursor = await conn.execute("SELECT due_date FROM actions WHERE id = ?", (action_id,))
    row = await cursor.fetchone()
    base = date.fromisoformat(row["due_date"]) if row and row["due_date"] else date.today()
    new_due = max(base, date.today()) + timedelta(days=days)
    await conn.execute(
        "UPDATE actions SET due_date = ?, snooze_count = snooze_count + 1 WHERE id = ?",
        (new_due.isoformat(), action_id),
    )
    await conn.commit()


async def get_daily_stats(conn: aiosqlite.Connection, today: date, threshold: float) -> dict[str, Any]:
    start = today.isoformat()
    end = (today + timedelta(days=1)).isoformat()

    cursor = await conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN score >= ? THEN 1 ELSE 0 END) FROM leads "
        "WHERE collected_at >= ? AND collected_at < ?",
        (threshold, start, end),
    )
    row = await cursor.fetchone()
    collected = row[0] or 0 if row else 0
    above_threshold = row[1] or 0 if row else 0

    cursor = await conn.execute(
        "SELECT COUNT(*) FROM lead_outcomes WHERE replied_at >= ? AND replied_at < ?", (start, end)
    )
    replied_row = await cursor.fetchone()
    replied = replied_row[0] or 0 if replied_row else 0

    cursor = await conn.execute(
        "SELECT source_id, COUNT(*) as cnt FROM leads WHERE collected_at >= ? AND collected_at < ? "
        "GROUP BY source_id ORDER BY cnt DESC LIMIT 1",
        (start, end),
    )
    best_row = await cursor.fetchone()

    return {
        "collected": collected,
        "above_threshold": above_threshold,
        "replied": replied,
        "best_source": best_row[0] if best_row else None,
    }


def _degraded_notified_key(source_id: str) -> str:
    return f"degraded_notified:{source_id}"


async def was_degradation_notified(conn: aiosqlite.Connection, source_id: str) -> bool:
    value = await get_system_state(conn, _degraded_notified_key(source_id))
    return value == "1"


async def set_degradation_notified(conn: aiosqlite.Connection, source_id: str, notified: bool) -> None:
    await set_system_state(conn, _degraded_notified_key(source_id), "1" if notified else "0")


async def get_degraded_sources(conn: aiosqlite.Connection) -> list[dict[str, Any]]:
    cursor = await conn.execute(
        "SELECT id, last_error, consecutive_failures FROM sources WHERE consecutive_failures > 0"
    )
    rows = await cursor.fetchall()
    return [
        {
            "id": row["id"],
            "last_error": row["last_error"],
            "consecutive_failures": row["consecutive_failures"],
        }
        for row in rows
    ]


async def get_source_conversion_stats(conn: aiosqlite.Connection, since: datetime) -> list[dict[str, Any]]:
    cursor = await conn.execute(
        """
        SELECT
            l.source_id,
            COUNT(*) AS collected,
            SUM(CASE WHEN lo.notified_at IS NOT NULL THEN 1 ELSE 0 END) AS notified,
            SUM(CASE WHEN lo.outcome = 'replied' THEN 1 ELSE 0 END) AS replied,
            SUM(CASE WHEN lo.outcome = 'won' THEN 1 ELSE 0 END) AS won
        FROM leads l
        LEFT JOIN lead_outcomes lo ON lo.lead_id = l.id
        WHERE l.collected_at >= ? AND l.duplicate_of IS NULL
        GROUP BY l.source_id
        ORDER BY collected DESC
        """,
        (since.isoformat(),),
    )
    rows = await cursor.fetchall()
    return [
        {
            "source_id": row["source_id"],
            "collected": row["collected"],
            "notified": row["notified"] or 0,
            "replied": row["replied"] or 0,
            "won": row["won"] or 0,
        }
        for row in rows
    ]


_BUDGET_BUCKETS: list[tuple[int, int | None]] = [
    (0, 5000),
    (5000, 10000),
    (10000, 30000),
    (30000, 100000),
    (100000, None),
]


async def get_budget_distribution(conn: aiosqlite.Connection, since: datetime) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for low, high in _BUDGET_BUCKETS:
        if high is None:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM leads WHERE collected_at >= ? AND duplicate_of IS NULL "
                "AND budget_max >= ?",
                (since.isoformat(), low),
            )
        else:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM leads WHERE collected_at >= ? AND duplicate_of IS NULL "
                "AND budget_max >= ? AND budget_max < ?",
                (since.isoformat(), low, high),
            )
        row = await cursor.fetchone()
        result.append({"low": low, "high": high, "count": row[0] if row else 0})
    return result


async def get_outcome(conn: aiosqlite.Connection, lead_id: int) -> LeadOutcome | None:
    cursor = await conn.execute(
        "SELECT lead_id, notified_at, replied_at, outcome, amount, notes "
        "FROM lead_outcomes WHERE lead_id = ?",
        (lead_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return LeadOutcome(
        lead_id=row["lead_id"],
        notified_at=datetime.fromisoformat(row["notified_at"]) if row["notified_at"] else None,
        replied_at=datetime.fromisoformat(row["replied_at"]) if row["replied_at"] else None,
        outcome=row["outcome"],
        amount=row["amount"],
        notes=row["notes"],
    )


# ---- CRM: companies ----

_COMPANY_COLUMNS = "id, name, contact_person, contact_info, status, result, created_at, updated_at"


def _row_to_company(row: aiosqlite.Row) -> Company:
    return Company(
        id=row["id"],
        name=row["name"],
        contact_person=row["contact_person"],
        contact_info=row["contact_info"],
        status=row["status"],
        result=row["result"],
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
    )


async def insert_company(
    conn: aiosqlite.Connection,
    *,
    name: str,
    contact_person: str | None = None,
    contact_info: str | None = None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    cursor = await conn.execute(
        "INSERT INTO companies(name, contact_person, contact_info, status, created_at, updated_at) "
        "VALUES (?, ?, ?, 'new', ?, ?)",
        (name, contact_person, contact_info, now, now),
    )
    await conn.commit()
    return int(cursor.lastrowid or 0)


async def get_company(conn: aiosqlite.Connection, company_id: int) -> Company | None:
    cursor = await conn.execute(f"SELECT {_COMPANY_COLUMNS} FROM companies WHERE id = ?", (company_id,))
    row = await cursor.fetchone()
    return _row_to_company(row) if row else None


async def list_companies(conn: aiosqlite.Connection, *, open_only: bool = False) -> list[Company]:
    if open_only:
        cursor = await conn.execute(
            f"SELECT {_COMPANY_COLUMNS} FROM companies WHERE status NOT IN ('won', 'lost') "
            "ORDER BY updated_at DESC"
        )
    else:
        cursor = await conn.execute(f"SELECT {_COMPANY_COLUMNS} FROM companies ORDER BY updated_at DESC")
    rows = await cursor.fetchall()
    return [_row_to_company(r) for r in rows]


async def update_company_status(conn: aiosqlite.Connection, company_id: int, status: str) -> None:
    await conn.execute(
        "UPDATE companies SET status = ?, updated_at = ? WHERE id = ?",
        (status, datetime.now(timezone.utc).isoformat(), company_id),
    )
    await conn.commit()


async def update_company_result(conn: aiosqlite.Connection, company_id: int, result: str) -> None:
    await conn.execute(
        "UPDATE companies SET result = ?, updated_at = ? WHERE id = ?",
        (result, datetime.now(timezone.utc).isoformat(), company_id),
    )
    await conn.commit()


async def get_open_action_for_company(conn: aiosqlite.Connection, company_id: int) -> Action | None:
    cursor = await conn.execute(
        f"SELECT {_ACTION_COLUMNS} FROM actions WHERE company_id = ? AND status = 'pending' "
        "ORDER BY due_date DESC LIMIT 1",
        (company_id,),
    )
    row = await cursor.fetchone()
    return _row_to_action(row) if row else None


# ---- Учёт дохода ----


async def insert_payment(
    conn: aiosqlite.Connection,
    *,
    amount: int,
    received_at: date,
    currency: str = "RUB",
    company_id: int | None = None,
    lead_id: int | None = None,
    note: str | None = None,
) -> int:
    cursor = await conn.execute(
        "INSERT INTO payments(amount, currency, received_at, lead_id, company_id, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            amount,
            currency,
            received_at.isoformat(),
            lead_id,
            company_id,
            note,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    await conn.commit()
    return int(cursor.lastrowid or 0)


async def get_income_for_period(conn: aiosqlite.Connection, start: date, end: date) -> int:
    """[start, end) - end не включается."""
    cursor = await conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE received_at >= ? AND received_at < ?",
        (start.isoformat(), end.isoformat()),
    )
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


# ---- hh.ru: собственные отклики ----

_HH_APP_COLUMNS = (
    "id, vacancy_id, vacancy_title, vacancy_url, state, hh_created_at, hh_updated_at, "
    "last_synced_at, last_notified_state"
)


def _row_to_hh_application(row: aiosqlite.Row) -> HhApplication:
    return HhApplication(
        id=row["id"],
        vacancy_id=row["vacancy_id"],
        vacancy_title=row["vacancy_title"],
        vacancy_url=row["vacancy_url"],
        state=row["state"],
        hh_created_at=datetime.fromisoformat(row["hh_created_at"]) if row["hh_created_at"] else None,
        hh_updated_at=datetime.fromisoformat(row["hh_updated_at"]) if row["hh_updated_at"] else None,
        last_synced_at=datetime.fromisoformat(row["last_synced_at"]) if row["last_synced_at"] else None,
        last_notified_state=row["last_notified_state"],
    )


async def get_hh_application(conn: aiosqlite.Connection, app_id: str) -> HhApplication | None:
    cursor = await conn.execute(
        f"SELECT {_HH_APP_COLUMNS} FROM hh_applications WHERE id = ?", (app_id,)
    )
    row = await cursor.fetchone()
    return _row_to_hh_application(row) if row else None


async def list_hh_applications(conn: aiosqlite.Connection) -> list[HhApplication]:
    cursor = await conn.execute(
        f"SELECT {_HH_APP_COLUMNS} FROM hh_applications ORDER BY hh_updated_at DESC"
    )
    rows = await cursor.fetchall()
    return [_row_to_hh_application(r) for r in rows]


async def upsert_hh_application(conn: aiosqlite.Connection, app: HhApplication) -> None:
    """Обновляет состояние отклика. last_notified_state не трогается - им управляет только
    mark_hh_application_notified, иначе неудачная отправка уведомления потеряется молча."""
    now = datetime.now(timezone.utc).isoformat()
    await conn.execute(
        """
        INSERT INTO hh_applications(
            id, vacancy_id, vacancy_title, vacancy_url, state, hh_created_at, hh_updated_at,
            last_synced_at, last_notified_state
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(id) DO UPDATE SET
            vacancy_id = excluded.vacancy_id,
            vacancy_title = excluded.vacancy_title,
            vacancy_url = excluded.vacancy_url,
            state = excluded.state,
            hh_created_at = excluded.hh_created_at,
            hh_updated_at = excluded.hh_updated_at,
            last_synced_at = excluded.last_synced_at
        """,
        (
            app.id,
            app.vacancy_id,
            app.vacancy_title,
            app.vacancy_url,
            app.state,
            app.hh_created_at.isoformat() if app.hh_created_at else None,
            app.hh_updated_at.isoformat() if app.hh_updated_at else None,
            now,
        ),
    )
    await conn.commit()


async def mark_hh_application_notified(conn: aiosqlite.Connection, app_id: str, state: str | None) -> None:
    await conn.execute(
        "UPDATE hh_applications SET last_notified_state = ? WHERE id = ?", (state, app_id)
    )
    await conn.commit()
