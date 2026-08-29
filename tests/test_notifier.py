from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.core import repository
from src.core.db import apply_migrations, get_connection
from src.core.models import Lead
from src.notifier.formatter import format_lead_message
from src.notifier.keyboard import build_lead_keyboard
from src.notifier.notifier import notify_pending_leads, send_lead_notification

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def test_format_lead_message_matches_expected_shape() -> None:
    lead = Lead(
        id=1,
        source_id="kwork",
        external_id="1",
        title="Доработать API на .NET Core, нужно допилить интеграцию с эквайрингом",
        score=87,
        budget_min=25000,
        budget_max=25000,
        budget_currency="₽",
        stack_tags=["c#", "api", "интеграция"],
    )
    text = format_lead_message(lead)
    lines = text.splitlines()
    assert lines[0] == "🔥 87 | Kwork | 25 000 ₽"
    assert "##" not in text  # "c#" санитизируется в "c", а не в "c#" (двойной хеш)
    assert "#api" in lines[-1]
    assert "#интеграция" in lines[-1]


def test_format_lead_message_handles_missing_budget_and_score() -> None:
    lead = Lead(id=2, source_id="fl_ru", external_id="2", title="Что-то без бюджета")
    text = format_lead_message(lead)
    assert "бюджет не указан" in text
    assert text.startswith("📄 ? |")


def test_format_lead_message_marks_ai_assistable_leads() -> None:
    lead = Lead(id=3, source_id="rss_remote_jobs", external_id="3", title="Простой парсер", ai_assistable=True)
    text = format_lead_message(lead)
    assert "🤖" in text.splitlines()[0]


def test_format_lead_message_omits_ai_marker_when_not_assistable() -> None:
    lead = Lead(id=4, source_id="rss_remote_jobs", external_id="4", title="Сложный проект", ai_assistable=False)
    text = format_lead_message(lead)
    assert "🤖" not in text.splitlines()[0]


def test_keyboard_requires_saved_lead() -> None:
    lead = Lead(source_id="hh_ru", external_id="1")
    with pytest.raises(ValueError):
        build_lead_keyboard(lead)


def test_keyboard_has_open_replied_ignored_buttons() -> None:
    lead = Lead(id=5, source_id="hh_ru", external_id="1", url="https://hh.ru/vacancy/1")
    keyboard = build_lead_keyboard(lead)
    texts = [btn.text for row in keyboard.inline_keyboard for btn in row]
    assert texts == ["Открыть", "Ответил", "Мимо"]


@pytest.mark.asyncio
async def test_send_lead_notification_calls_bot_and_records_notified(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    conn = await get_connection(db_path)
    await repository.ensure_source(conn, "hh_ru", 1)
    await repository.insert_lead(conn, Lead(source_id="hh_ru", external_id="1", score=90))
    lead = await repository.get_lead_by_external_id(conn, "hh_ru", "1")
    assert lead is not None

    fake_bot = AsyncMock()
    await send_lead_notification(fake_bot, channel_id=-100123, lead=lead, conn=conn)

    fake_bot.send_message.assert_called_once()
    assert fake_bot.send_message.call_args.kwargs["chat_id"] == -100123

    outcome = await repository.get_outcome(conn, lead.id)  # type: ignore[arg-type]
    await conn.close()
    assert outcome is not None
    assert outcome.notified_at is not None


@pytest.mark.asyncio
async def test_notify_pending_leads_sends_only_leads_above_threshold_once(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    conn = await get_connection(db_path)
    await repository.ensure_source(conn, "hh_ru", 1)
    await repository.insert_lead(conn, Lead(source_id="hh_ru", external_id="1", score=90))
    await repository.insert_lead(conn, Lead(source_id="hh_ru", external_id="2", score=10))

    fake_bot = AsyncMock()
    sent_first = await notify_pending_leads(fake_bot, channel_id=-100123, conn=conn, threshold=50)
    sent_second = await notify_pending_leads(fake_bot, channel_id=-100123, conn=conn, threshold=50)
    await conn.close()

    assert sent_first == 1  # только тот, что выше порога
    assert fake_bot.send_message.call_count == 1
    assert sent_second == 0  # уже отправлен, повторно не шлём


@pytest.mark.asyncio
async def test_notify_pending_leads_degrades_on_single_send_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("src.core.retry.asyncio.sleep", _no_sleep)

    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    conn = await get_connection(db_path)
    await repository.ensure_source(conn, "hh_ru", 1)
    await repository.insert_lead(conn, Lead(source_id="hh_ru", external_id="1", score=90))
    await repository.insert_lead(conn, Lead(source_id="hh_ru", external_id="2", score=95))

    call_count = 0

    async def flaky_send(*args: object, **kwargs: object) -> None:
        nonlocal call_count
        call_count += 1
        if call_count <= 4:  # исчерпывает все попытки retry_with_backoff (max_retries=3) для лида 1
            raise RuntimeError("network blip")

    fake_bot = AsyncMock()
    fake_bot.send_message = AsyncMock(side_effect=flaky_send)

    sent = await notify_pending_leads(fake_bot, channel_id=-100123, conn=conn, threshold=50)
    await conn.close()

    assert sent == 1  # второй лид всё равно отправлен, несмотря на постоянный сбой первого
    assert call_count == 5
