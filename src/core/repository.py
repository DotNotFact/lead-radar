from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from src.core.models import Lead


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
