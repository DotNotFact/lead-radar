from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from src.core.models import Lead, LeadOutcome, Outcome

_LEAD_COLUMNS = (
    "id, source_id, external_id, url, title, text, published_at, collected_at, "
    "budget_min, budget_max, budget_currency, budget_confidence, stack_tags, "
    "content_hash, duplicate_of, score, author_handle, raw_meta"
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
            stack_tags, content_hash, duplicate_of, score, author_handle, raw_meta
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
