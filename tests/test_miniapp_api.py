from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.core import repository
from src.core.config import Settings
from src.core.db import apply_migrations, get_connection
from src.webapp.api import _get_settings, require_owner
from src.webapp.auth import TelegramUser
from src.webapp.server import create_app

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


async def _seed_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    await apply_migrations(db_path, MIGRATIONS_DIR)
    return db_path


def _client(db_path: Path, *, authenticated: bool = True) -> TestClient:
    def _override_settings() -> Settings:
        return Settings(  # type: ignore[call-arg]
            _env_file=None, db_path=db_path, bot_token="test-token", miniapp_owner_telegram_id=777
        )

    app = create_app()
    app.dependency_overrides[_get_settings] = _override_settings
    if authenticated:
        app.dependency_overrides[require_owner] = lambda: TelegramUser(
            id=777, first_name="Danila", username="danila"
        )
    return TestClient(app)


@pytest.mark.asyncio
async def test_sources_requires_authorization_header(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    client = _client(db_path, authenticated=False)

    response = client.get("/api/sources")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_sources_lists_all_known_sources_with_yaml_defaults(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    client = _client(db_path)

    response = client.get("/api/sources")
    assert response.status_code == 200
    body = {item["id"]: item for item in response.json()}

    assert set(body) == {
        "hh_ru", "kwork_projects", "kwork_catalog", "remoteok", "freelancer", "rss_remote_jobs", "telegram",
    }
    assert body["hh_ru"]["enabled"] is True
    assert body["hh_ru"]["requires_restart_to_enable"] is False

    # freelancer выключен в sources.yaml по умолчанию (нет FREELANCER_OAUTH_TOKEN) - включить
    # его через API можно, но без перезапуска процесса это не заработает
    assert body["freelancer"]["enabled"] is False
    assert body["freelancer"]["requires_restart_to_enable"] is True

    # telegram работает через постоянное соединение - всегда требует перезапуска
    assert body["telegram"]["requires_restart_to_enable"] is True


@pytest.mark.asyncio
async def test_sources_reflect_health_from_db(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    conn = await get_connection(db_path)
    await repository.ensure_source(conn, "hh_ru", 1)
    await repository.mark_source_failed(conn, "hh_ru", "403 от api.hh.ru")
    await conn.close()

    client = _client(db_path)
    response = client.get("/api/sources")
    hh_ru = next(item for item in response.json() if item["id"] == "hh_ru")

    assert hh_ru["consecutive_failures"] == 1
    assert hh_ru["last_error"] == "403 от api.hh.ru"


@pytest.mark.asyncio
async def test_toggle_unknown_source_returns_404(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    client = _client(db_path)

    response = client.post("/api/sources/not_a_real_source/toggle", json={"enabled": False})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_toggle_persists_override_and_is_reflected_on_next_list(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    client = _client(db_path)

    toggle_response = client.post("/api/sources/hh_ru/toggle", json={"enabled": False})
    assert toggle_response.status_code == 200
    assert toggle_response.json()["enabled"] is False
    # hh_ru был включён и опрашивается в планировщике на старте - выключение действует сразу
    assert toggle_response.json()["requires_restart_to_enable"] is False

    list_response = client.get("/api/sources")
    hh_ru = next(item for item in list_response.json() if item["id"] == "hh_ru")
    assert hh_ru["enabled"] is False


@pytest.mark.asyncio
async def test_toggle_requires_authorization(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    client = _client(db_path, authenticated=False)

    response = client.post("/api/sources/hh_ru/toggle", json={"enabled": False})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_authenticated_user(tmp_path: Path) -> None:
    db_path = await _seed_db(tmp_path)
    client = _client(db_path)

    response = client.get("/api/me")
    assert response.status_code == 200
    assert response.json() == {"id": 777, "first_name": "Danila", "username": "danila"}
