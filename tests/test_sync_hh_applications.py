from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from scripts.sync_hh_applications import is_configured, sync_hh_applications
from src.core import repository
from src.core.config import Settings
from src.core.db import get_connection


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    defaults: dict[str, object] = dict(
        _env_file=None,
        db_path=tmp_path / "test.db",
        hh_client_id="cid",
        hh_client_secret="secret",
        hh_access_token="token",
        hh_refresh_token="rtoken",
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_is_configured_requires_all_four_fields(tmp_path: Path) -> None:
    assert is_configured(_settings(tmp_path)) is True
    assert is_configured(_settings(tmp_path, hh_access_token="")) is False


@pytest.mark.asyncio
async def test_sync_skips_when_not_configured(tmp_path: Path) -> None:
    settings = _settings(tmp_path, hh_client_id="")
    result = await sync_hh_applications(settings, tmp_path / ".env")
    assert result["configured"] is False
    assert result["changed"] == []


@pytest.mark.asyncio
@respx.mock
async def test_sync_detects_no_change_on_first_sync(tmp_path: Path) -> None:
    respx.get("https://api.hh.ru/negotiations").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": "1", "vacancy": {"id": "10", "name": "Dev"}, "state": {"id": "response"}}], "pages": 1},
        )
    )
    settings = _settings(tmp_path)
    result = await sync_hh_applications(settings, tmp_path / ".env")

    assert result["error"] is None
    assert result["changed"] == []  # первая синхронизация - не с чем сравнивать

    conn = await get_connection(settings.db_path)
    stored = await repository.get_hh_application(conn, "1")
    await conn.close()
    assert stored is not None
    assert stored.state == "response"


@pytest.mark.asyncio
@respx.mock
async def test_sync_detects_state_change_on_second_sync(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    respx.get("https://api.hh.ru/negotiations").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": "1", "vacancy": {"id": "10", "name": "Dev"}, "state": {"id": "response"}}], "pages": 1},
        )
    )
    first = await sync_hh_applications(settings, tmp_path / ".env")
    assert first["changed"] == []

    respx.get("https://api.hh.ru/negotiations").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": "1", "vacancy": {"id": "10", "name": "Dev"}, "state": {"id": "invitation"}}], "pages": 1},
        )
    )
    second = await sync_hh_applications(settings, tmp_path / ".env")

    assert len(second["changed"]) == 1
    assert second["changed"][0].state == "invitation"


@pytest.mark.asyncio
@respx.mock
async def test_sync_does_not_reflag_unnotified_but_unchanged_state(tmp_path: Path) -> None:
    """Если состояние не менялось между синками - не должно попадать в changed повторно."""
    settings = _settings(tmp_path)
    respx.get("https://api.hh.ru/negotiations").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": "1", "state": {"id": "response"}}], "pages": 1},
        )
    )
    await sync_hh_applications(settings, tmp_path / ".env")

    respx.get("https://api.hh.ru/negotiations").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": "1", "state": {"id": "invitation"}}], "pages": 1},
        )
    )
    second = await sync_hh_applications(settings, tmp_path / ".env")
    assert len(second["changed"]) == 1

    conn = await get_connection(settings.db_path)
    await repository.mark_hh_application_notified(conn, "1", "invitation")
    await conn.close()

    # то же состояние ещё раз - уже не изменение
    third = await sync_hh_applications(settings, tmp_path / ".env")
    assert third["changed"] == []


@pytest.mark.asyncio
@respx.mock
async def test_sync_marks_source_degraded_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("src.core.http.asyncio.sleep", _no_sleep)

    respx.get("https://api.hh.ru/negotiations").mock(return_value=httpx.Response(500))
    settings = _settings(tmp_path)

    result = await sync_hh_applications(settings, tmp_path / ".env")

    assert result["error"] is not None
    assert result["changed"] == []

    conn = await get_connection(settings.db_path)
    degraded = await repository.get_degraded_sources(conn)
    await conn.close()
    assert any(d["id"] == "hh_applications" for d in degraded)
