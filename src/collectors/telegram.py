from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable, Protocol

from src.core.models import HealthStatus, RawLead

logger = logging.getLogger("lead_radar.collectors.telegram")

RawLeadHandler = Callable[[RawLead], Awaitable[None]]


class TelegramClientLike(Protocol):
    """Минимальный срез Telethon.TelegramClient, который использует коллектор — позволяет
    подставлять фейковый клиент в тестах без реальной сессии/сети."""

    def iter_messages(
        self, entity: str, *, offset_date: datetime | None, reverse: bool
    ) -> AsyncIterator[Any]: ...

    def add_event_handler(self, callback: Callable[[Any], Awaitable[None]], event: Any) -> None: ...


class TelegramCollector:
    """Коллектор Telegram. Клиент создаётся и подключается снаружи (src/main.py) —
    коллектор только читает, никогда не вступает в чаты и не пишет в них (инвариант 3)."""

    source_id = "telegram"
    tier = 1

    def __init__(self, client: TelegramClientLike, chats: list[str], poll_interval: int = 0) -> None:
        self.client = client
        self.chats = chats
        self.poll_interval = poll_interval
        self._consecutive_failures = 0
        self._last_error: str | None = None

    async def fetch(self, since: datetime) -> list[RawLead]:
        """Догоняющий опрос истории — вызывается при старте, чтобы не потерять сообщения
        за время простоя."""
        leads: list[RawLead] = []
        for chat in self.chats:
            try:
                async for message in self.client.iter_messages(chat, offset_date=since, reverse=True):
                    lead = await self._message_to_raw_lead(chat, message)
                    if lead is not None:
                        leads.append(lead)
            except Exception as exc:  # источник деградирует, система не падает (инвариант 6)
                self._consecutive_failures += 1
                self._last_error = f"{chat}: {exc}"
                logger.warning("telegram_chat_fetch_failed", extra={"chat": chat, "error": str(exc)})
        if not self._last_error:
            self._consecutive_failures = 0
        return leads

    def register_realtime_handler(self, on_new_lead: RawLeadHandler) -> None:
        """Регистрирует обработчик новых сообщений в реальном времени. Импорт telethon.events
        лениво — чтобы модуль был импортируемым (и тестируемым) без установленного telethon
        в путях, где реальный клиент не нужен."""
        from telethon import events

        async def _handler(event: Any) -> None:
            message = event.message
            chat = str(getattr(event, "chat_id", "") or "")
            lead = await self._message_to_raw_lead(chat, message)
            if lead is not None:
                await on_new_lead(lead)

        self.client.add_event_handler(_handler, events.NewMessage(chats=self.chats or None))

    async def _message_to_raw_lead(self, chat: str, message: Any) -> RawLead | None:
        text = getattr(message, "text", None) or getattr(message, "raw_text", None)
        if not text:
            return None

        author_handle = await self._safe_author_handle(message)
        message_date = getattr(message, "date", None)
        if message_date is not None and message_date.tzinfo is None:
            message_date = message_date.replace(tzinfo=timezone.utc)

        return RawLead(
            source_id=self.source_id,
            external_id=f"{chat}:{message.id}",
            url=None,
            title=None,
            text=text,
            raw_budget=text,
            published_at=message_date,
            author_handle=author_handle,
            meta={"chat": chat, "message_id": message.id},
        )

    async def _safe_author_handle(self, message: Any) -> str | None:
        try:
            sender = await message.get_sender()
        except Exception:
            return None
        username = getattr(sender, "username", None)
        return f"@{username}" if username else None

    async def health(self) -> HealthStatus:
        return HealthStatus(
            source_id=self.source_id,
            ok=self._consecutive_failures == 0,
            checked_at=datetime.now(timezone.utc),
            last_error=self._last_error,
            consecutive_failures=self._consecutive_failures,
        )
