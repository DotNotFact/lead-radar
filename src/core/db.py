from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger("lead_radar.db")


async def apply_migrations(db_path: Path, migrations_dir: Path) -> list[str]:
    """Применяет все ещё не применённые *.sql из migrations_dir, по имени файла (сортировка).
    Возвращает список версий, применённых за этот вызов."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    applied: list[str] = []
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        await conn.commit()

        cursor = await conn.execute("SELECT version FROM schema_migrations")
        rows = await cursor.fetchall()
        already_applied = {row[0] for row in rows}

        for path in sorted(migrations_dir.glob("*.sql")):
            version = path.stem
            if version in already_applied:
                continue
            sql = path.read_text(encoding="utf-8")
            await conn.executescript(sql)
            await conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (version,)
            )
            await conn.commit()
            applied.append(version)
            logger.info("migration_applied", extra={"version": version})

    return applied


async def get_connection(db_path: Path) -> aiosqlite.Connection:
    conn = await aiosqlite.connect(db_path)
    await conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = aiosqlite.Row
    return conn
