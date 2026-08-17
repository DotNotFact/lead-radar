from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from src.collectors.telegram import TelegramCollector


class FakeMessage:
    def __init__(
        self, msg_id: int, text: str, date: datetime, sender_username: str | None = None
    ) -> None:
        self.id = msg_id
        self.text = text
        self.date = date
        self._sender_username = sender_username

    async def get_sender(self) -> Any:
        if self._sender_username is None:
            return None
        return SimpleNamespace(username=self._sender_username)


class FakeClient:
    def __init__(self, messages_by_chat: dict[str, list[FakeMessage]], fail_chats: set[str] | None = None) -> None:
        self.messages_by_chat = messages_by_chat
        self.fail_chats = fail_chats or set()
        self.added_handlers: list[tuple[Any, Any]] = []

    def iter_messages(self, entity: str, *, offset_date: datetime | None, reverse: bool) -> Any:
        if entity in self.fail_chats:
            raise RuntimeError("chat unavailable")
        return self._gen(entity)

    async def _gen(self, entity: str) -> Any:
        for message in self.messages_by_chat.get(entity, []):
            yield message

    def add_event_handler(self, callback: Any, event: Any) -> None:
        self.added_handlers.append((callback, event))


NOW = datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_fetch_converts_messages_to_raw_leads() -> None:
    client = FakeClient(
        {
            "@chat_one": [
                FakeMessage(1, "Нужен C# разработчик, бюджет 20000 руб", NOW, "customer1"),
                FakeMessage(2, "Ищу дизайнера", NOW, None),
            ]
        }
    )
    collector = TelegramCollector(client, chats=["@chat_one"])

    leads = await collector.fetch(NOW - timedelta(days=1))

    assert len(leads) == 2
    assert leads[0].external_id == "@chat_one:1"
    assert leads[0].author_handle == "@customer1"
    assert leads[1].author_handle is None
    assert leads[0].source_id == "telegram"


@pytest.mark.asyncio
async def test_fetch_skips_empty_messages() -> None:
    client = FakeClient({"@chat_one": [FakeMessage(1, "", NOW, None)]})
    collector = TelegramCollector(client, chats=["@chat_one"])

    leads = await collector.fetch(NOW - timedelta(days=1))

    assert leads == []


@pytest.mark.asyncio
async def test_fetch_degrades_on_single_chat_failure_without_losing_others() -> None:
    client = FakeClient(
        {"@good_chat": [FakeMessage(1, "Нужен бэкенд разработчик C#", NOW, "cust")]},
        fail_chats={"@bad_chat"},
    )
    collector = TelegramCollector(client, chats=["@bad_chat", "@good_chat"])

    leads = await collector.fetch(NOW - timedelta(days=1))

    assert len(leads) == 1
    assert leads[0].external_id == "@good_chat:1"

    health = await collector.health()
    assert health.ok is False
    assert health.consecutive_failures == 1
    assert "bad_chat" in (health.last_error or "")


@pytest.mark.asyncio
async def test_register_realtime_handler_wires_event_and_produces_lead() -> None:
    client = FakeClient({})
    collector = TelegramCollector(client, chats=["@chat_one"])

    received: list[str] = []

    async def on_new_lead(lead: Any) -> None:
        received.append(lead.external_id)

    collector.register_realtime_handler(on_new_lead)

    assert len(client.added_handlers) == 1
    callback, _event_filter = client.added_handlers[0]

    fake_event = SimpleNamespace(
        message=FakeMessage(42, "Срочно нужен C# разработчик", NOW, "author"),
        chat_id="@chat_one",
    )
    await callback(fake_event)

    assert received == ["@chat_one:42"]
