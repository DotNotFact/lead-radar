from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import aiosqlite

from src.export.anonymizer import anonymize_text

ExportFormat = Literal["csv", "jsonl"]

_EXPORT_COLUMNS = (
    "source_id",
    "title",
    "text",
    "url",
    "published_at",
    "budget_min",
    "budget_max",
    "budget_currency",
    "budget_confidence",
    "stack_tags",
    "score",
    "outcome",
)


async def fetch_export_rows(conn: aiosqlite.Connection, days: int) -> list[dict[str, Any]]:
    """Только обезличенные поля (инвариант 5): без author_handle, external_id, raw_meta,
    id пользователей. Дубликаты кросспостов (duplicate_of IS NOT NULL) не экспортируются -
    аналитика должна считать уникальные лиды."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cursor = await conn.execute(
        """
        SELECT l.source_id, l.title, l.text, l.url, l.published_at, l.budget_min, l.budget_max,
               l.budget_currency, l.budget_confidence, l.stack_tags, l.score, lo.outcome
        FROM leads l
        LEFT JOIN lead_outcomes lo ON lo.lead_id = l.id
        WHERE l.collected_at >= ? AND l.duplicate_of IS NULL
        ORDER BY l.published_at DESC
        """,
        (since,),
    )
    rows = await cursor.fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "source_id": row["source_id"],
                "title": anonymize_text(row["title"]),
                "text": anonymize_text(row["text"]),
                "url": row["url"],
                "published_at": row["published_at"],
                "budget_min": row["budget_min"],
                "budget_max": row["budget_max"],
                "budget_currency": row["budget_currency"],
                "budget_confidence": row["budget_confidence"],
                "stack_tags": json.loads(row["stack_tags"]) if row["stack_tags"] else [],
                "score": row["score"],
                "outcome": row["outcome"],
            }
        )
    return result


def render_csv(rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_EXPORT_COLUMNS)
    writer.writeheader()
    for row in rows:
        flat = dict(row)
        flat["stack_tags"] = ",".join(flat["stack_tags"])
        writer.writerow(flat)
    return buffer.getvalue().encode("utf-8-sig")


def render_jsonl(rows: list[dict[str, Any]]) -> bytes:
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    body = "\n".join(lines)
    return (body + "\n" if lines else "").encode("utf-8")


async def export_leads(conn: aiosqlite.Connection, days: int, fmt: ExportFormat) -> bytes:
    rows = await fetch_export_rows(conn, days)
    return render_csv(rows) if fmt == "csv" else render_jsonl(rows)
