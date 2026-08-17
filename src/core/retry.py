from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger("lead_radar.retry")

T = TypeVar("T")

DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 2.0


async def retry_with_backoff(
    func: Callable[[], Awaitable[T]],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
) -> T:
    """Общая обёртка для внешних вызовов без собственного HTTP-уровня (Telegram Bot API через
    aiogram и т.п.) - экспоненциальный бэкофф, как того требует ТРЕБОВАНИЯ К КОДУ."""
    last_exc: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            return await func()
        except Exception as exc:
            last_exc = exc
            if attempt == max_retries:
                break
            delay = backoff_base**attempt
            logger.warning(
                "retry_attempt_failed", extra={"attempt": attempt, "delay": delay, "error": str(exc)}
            )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc
