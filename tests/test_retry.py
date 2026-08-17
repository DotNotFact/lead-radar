from __future__ import annotations

import pytest

from src.core.retry import retry_with_backoff


@pytest.mark.asyncio
async def test_retry_succeeds_after_transient_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("src.core.retry.asyncio.sleep", _no_sleep)

    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("transient")
        return "ok"

    result = await retry_with_backoff(flaky, max_retries=3)

    assert result == "ok"
    assert attempts == 3


@pytest.mark.asyncio
async def test_retry_raises_after_exhausting_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("src.core.retry.asyncio.sleep", _no_sleep)

    attempts = 0

    async def always_fails() -> str:
        nonlocal attempts
        attempts += 1
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        await retry_with_backoff(always_fails, max_retries=2)

    assert attempts == 3  # первая попытка + 2 ретрая
