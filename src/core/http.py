from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger("lead_radar.http")

DEFAULT_MAX_RETRIES = 4
DEFAULT_BACKOFF_BASE = 2.0


class SourceUnavailableError(Exception):
    """Источник недоступен после исчерпания ретраев — вызывающий код переводит источник в degraded."""


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    passthrough_statuses: frozenset[int] = frozenset(),
    **kwargs: Any,
) -> httpx.Response:
    """Экспоненциальный бэкофф на 429/5xx/сетевые ошибки, уважает Retry-After. Любой другой
    неуспешный статус (4xx кроме 429) сразу становится SourceUnavailableError вместо того,
    чтобы всплыть как необработанный httpx.HTTPStatusError из чьего-то raise_for_status() -
    как правило это не транзиентная проблема (бан по IP, защита), ретраить бессмысленно и
    означало бы "долбить" источник (инвариант 4). Источник уходит в degraded до следующего
    цикла опроса - это и есть "тихий режим", а не блокирующий sleep на час внутри процесса.

    passthrough_statuses - коды, которые вызывающий код обрабатывает сам (например, OAuth-
    клиент сам решает, рефрешить токен на 401/403 или сдаваться) - возвращаются как есть,
    без ретрая и без SourceUnavailableError."""
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            last_error = exc
        else:
            if response.status_code in passthrough_statuses:
                return response
            if response.status_code == 429 or response.status_code >= 500:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else backoff_base**attempt
                logger.warning(
                    "http_retry",
                    extra={
                        "url": url,
                        "status": response.status_code,
                        "attempt": attempt,
                        "delay": delay,
                    },
                )
                if attempt == max_retries:
                    raise SourceUnavailableError(
                        f"{url} -> {response.status_code} после {attempt + 1} попыток"
                    )
                await asyncio.sleep(delay)
                continue
            if response.status_code >= 400:
                raise SourceUnavailableError(f"{url} -> {response.status_code}: {response.text[:200]}")
            return response

        if attempt == max_retries:
            raise SourceUnavailableError(f"{url} -> {last_error}") from last_error
        await asyncio.sleep(backoff_base**attempt)

    raise SourceUnavailableError(f"{url} -> попытки исчерпаны")
