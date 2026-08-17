from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.core import repository
from src.core.db import apply_migrations, get_connection
from src.core.models import HhApplication
from src.notifier.hh_application_alerts import notify_application_changes

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


@pytest.mark.asyncio
async def test_notify_application_changes_sends_and_marks_notified(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    conn = await get_connection(db_path)
    await repository.upsert_hh_application(
        conn, HhApplication(id="1", vacancy_title="Backend Dev", state="invitation")
    )

    fake_bot = AsyncMock()
    changed = [HhApplication(id="1", vacancy_title="Backend Dev", state="invitation")]

    sent = await notify_application_changes(fake_bot, channel_id=-100123, conn=conn, changed=changed)
    await conn.close()

    assert sent == 1
    fake_bot.send_message.assert_called_once()
    text = fake_bot.send_message.call_args.kwargs["text"]
    assert "Backend Dev" in text
    assert "приглашение" in text.lower()


@pytest.mark.asyncio
async def test_notify_application_changes_degrades_on_single_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("src.core.retry.asyncio.sleep", _no_sleep)

    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    conn = await get_connection(db_path)
    await repository.upsert_hh_application(conn, HhApplication(id="1", state="invitation"))
    await repository.upsert_hh_application(conn, HhApplication(id="2", state="discard"))

    call_count = 0

    async def flaky_send(*args: object, **kwargs: object) -> None:
        nonlocal call_count
        call_count += 1
        if call_count <= 4:
            raise RuntimeError("network blip")

    fake_bot = AsyncMock()
    fake_bot.send_message = AsyncMock(side_effect=flaky_send)

    changed = [
        HhApplication(id="1", state="invitation"),
        HhApplication(id="2", state="discard"),
    ]
    sent = await notify_application_changes(fake_bot, channel_id=-100123, conn=conn, changed=changed)
    await conn.close()

    assert sent == 1  # второй прошёл, несмотря на постоянный сбой первого
