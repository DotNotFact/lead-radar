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


async def fetch_export_rows(
    conn: aiosqlite.Connection, days: int, *, ai_assistable_only: bool = False
) -> list[dict[str, Any]]:
    """Только обезличенные поля (инвариант 5): без author_handle, external_id, raw_meta,
    id пользователей. Дубликаты кросспостов (duplicate_of IS NOT NULL) не экспортируются -
    аналитика должна считать уникальные лиды. ai_assistable_only сужает выборку до лидов,
    помеченных как выполнимые ИИ (см. config/keywords.yaml -> ai_assistable) - используется
    /export_ai, чтобы не отдавать ИИ заказы, которые она заведомо не потянет."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = """
        SELECT l.source_id, l.title, l.text, l.url, l.published_at, l.budget_min, l.budget_max,
               l.budget_currency, l.budget_confidence, l.stack_tags, l.score, lo.outcome
        FROM leads l
        LEFT JOIN lead_outcomes lo ON lo.lead_id = l.id
        WHERE l.collected_at >= ? AND l.duplicate_of IS NULL
    """
    if ai_assistable_only:
        query += " AND l.ai_assistable = 1"
    query += " ORDER BY l.published_at DESC"

    cursor = await conn.execute(query, (since,))
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


def render_ai_handoff(rows: list[dict[str, Any]], intro: str = "") -> bytes:
    """Обычный читаемый текст (не CSV/JSONL) - для вставки в чат с ИИ вместе с prompt-текстом
    из config/prompts.yaml (lead_batch_for_ai). Используется /export_ai."""
    lines: list[str] = [intro.rstrip(), ""] if intro.strip() else []

    for i, row in enumerate(rows, start=1):
        lines.append(f"### Лид {i} - {row['source_id']}")
        if row.get("title"):
            lines.append(f"Заголовок: {row['title']}")
        if row.get("text"):
            lines.append(f"Описание: {row['text']}")

        budget_min, budget_max = row.get("budget_min"), row.get("budget_max")
        if budget_min is not None or budget_max is not None:
            amount = budget_max if budget_max is not None else budget_min
            currency = row.get("budget_currency") or ""
            lines.append(f"Бюджет: {amount} {currency}".strip())

        if row.get("url"):
            lines.append(f"Ссылка: {row['url']}")
        lines.append("")

    return "\n".join(lines).strip().encode("utf-8")
