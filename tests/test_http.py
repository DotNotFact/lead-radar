from __future__ import annotations

import httpx
import pytest
import respx

from src.core.http import SourceUnavailableError, request_with_retry


@pytest.mark.asyncio
@respx.mock
async def test_success_returns_response() -> None:
    respx.get("https://example.com/ok").mock(return_value=httpx.Response(200, json={"ok": True}))
    async with httpx.AsyncClient() as client:
        response = await request_with_retry(client, "GET", "https://example.com/ok")
    assert response.status_code == 200


@pytest.mark.asyncio
@respx.mock
async def test_403_raises_source_unavailable_without_raise_for_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Регрессия: раньше 403 (и любой другой 4xx кроме 429) не ретраился
    request_with_retry, возвращался как обычный response, и падал необработанным
    httpx.HTTPStatusError на чьём-то response.raise_for_status() - роняя весь скрипт
    вместо аккуратного degraded. Поймано вживую на api.hh.ru (DDoS-Guard)."""
    call_count = 0

    def responder(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(403, text="forbidden")

    respx.get("https://example.com/blocked").mock(side_effect=responder)

    async with httpx.AsyncClient() as client:
        with pytest.raises(SourceUnavailableError):
            await request_with_retry(client, "GET", "https://example.com/blocked")

    assert call_count == 1  # 403 - не транзиентная штука, ретраить бессмысленно


@pytest.mark.asyncio
@respx.mock
async def test_404_raises_source_unavailable() -> None:
    respx.get("https://example.com/missing").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        with pytest.raises(SourceUnavailableError):
            await request_with_retry(client, "GET", "https://example.com/missing")


@pytest.mark.asyncio
@respx.mock
async def test_429_retries_with_backoff_then_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("src.core.http.asyncio.sleep", _no_sleep)

    respx.get("https://example.com/limited").mock(return_value=httpx.Response(429))
    async with httpx.AsyncClient() as client:
        with pytest.raises(SourceUnavailableError):
            await request_with_retry(client, "GET", "https://example.com/limited", max_retries=2)


@pytest.mark.asyncio
@respx.mock
async def test_passthrough_statuses_bypass_error_handling() -> None:
    respx.get("https://example.com/auth").mock(return_value=httpx.Response(403))
    async with httpx.AsyncClient() as client:
        response = await request_with_retry(
            client, "GET", "https://example.com/auth", passthrough_statuses=frozenset({403})
        )
    assert response.status_code == 403  # вызывающий код сам решает, что делать
