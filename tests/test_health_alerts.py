from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.core import repository
from src.core.db import apply_migrations, get_connection
from src.notifier.health_alerts import check_and_notify_source_health

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


@pytest.mark.asyncio
async def test_notifies_once_when_source_degrades(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    conn = await get_connection(db_path)
    await repository.ensure_source(conn, "hh_ru", 1)
    await repository.mark_source_failed(conn, "hh_ru", "403 forbidden")

    fake_bot = AsyncMock()

    await check_and_notify_source_health(fake_bot, channel_id=-100123, conn=conn)
    await check_and_notify_source_health(fake_bot, channel_id=-100123, conn=conn)
    await conn.close()

    assert fake_bot.send_message.call_count == 1  # не спамит на каждый цикл
    text = fake_bot.send_message.call_args.kwargs["text"]
    assert "hh_ru" in text
    assert "403 forbidden" in text


@pytest.mark.asyncio
async def test_notifies_on_recovery(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    conn = await get_connection(db_path)
    await repository.ensure_source(conn, "hh_ru", 1)
    await repository.mark_source_failed(conn, "hh_ru", "timeout")

    fake_bot = AsyncMock()
    await check_and_notify_source_health(fake_bot, channel_id=-100123, conn=conn)

    await repository.mark_source_ok(conn, "hh_ru")
    await check_and_notify_source_health(fake_bot, channel_id=-100123, conn=conn)
    await conn.close()

    assert fake_bot.send_message.call_count == 2
    recovery_text = fake_bot.send_message.call_args_list[1].kwargs["text"]
    assert "✅" in recovery_text
    assert "hh_ru" in recovery_text


@pytest.mark.asyncio
async def test_no_notification_when_healthy(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    conn = await get_connection(db_path)
    await repository.ensure_source(conn, "hh_ru", 1)

    fake_bot = AsyncMock()
    await check_and_notify_source_health(fake_bot, channel_id=-100123, conn=conn)
    await conn.close()

    fake_bot.send_message.assert_not_called()
