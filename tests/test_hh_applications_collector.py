from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from src.collectors.hh_applications import (
    HhApplicationsClient,
    HhOAuthError,
    raw_item_to_application,
)
from src.core.http import SourceUnavailableError


def test_raw_item_to_application_parses_expected_fields() -> None:
    item = {
        "id": "123",
        "vacancy": {"id": "555", "name": "Backend Developer", "alternate_url": "https://hh.ru/vacancy/555"},
        "state": {"id": "invitation", "name": "Приглашение"},
        "created_at": "2026-08-01T10:00:00+0300",
        "updated_at": "2026-08-10T12:00:00+0300",
    }
    app = raw_item_to_application(item)

    assert app.id == "123"
    assert app.vacancy_id == "555"
    assert app.vacancy_title == "Backend Developer"
    assert app.state == "invitation"
    assert app.hh_created_at is not None
    assert app.hh_updated_at is not None


def test_raw_item_to_application_tolerates_missing_fields() -> None:
    app = raw_item_to_application({"id": "1"})
    assert app.id == "1"
    assert app.vacancy_id is None
    assert app.state is None


@pytest.mark.asyncio
@respx.mock
async def test_fetch_applications_single_page() -> None:
    respx.get("https://api.hh.ru/negotiations").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {"id": "1", "vacancy": {"id": "10", "name": "Dev"}, "state": {"id": "response"}}
                ],
                "pages": 1,
            },
        )
    )
    client = HhApplicationsClient(
        client_id="cid", client_secret="secret", access_token="token", refresh_token="rtoken",
        env_path=Path("unused.env"),
    )
    apps = await client.fetch_applications()
    assert len(apps) == 1
    assert apps[0].id == "1"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_applications_paginates() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "0"))
        if page == 0:
            return httpx.Response(200, json={"items": [{"id": "1"}], "pages": 2})
        return httpx.Response(200, json={"items": [{"id": "2"}], "pages": 2})

    respx.get("https://api.hh.ru/negotiations").mock(side_effect=responder)
    client = HhApplicationsClient(
        client_id="cid", client_secret="secret", access_token="token", refresh_token="rtoken",
        env_path=Path("unused.env"),
    )
    apps = await client.fetch_applications()
    assert {a.id for a in apps} == {"1", "2"}


@pytest.mark.asyncio
@respx.mock
async def test_fetch_applications_refreshes_token_on_401(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("HH_ACCESS_TOKEN=old\nHH_REFRESH_TOKEN=old_refresh\n", encoding="utf-8")

    call_count = 0

    def responder(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        auth = request.headers.get("Authorization")
        if auth == "Bearer old":
            return httpx.Response(401)
        return httpx.Response(200, json={"items": [{"id": "1"}], "pages": 1})

    respx.get("https://api.hh.ru/negotiations").mock(side_effect=responder)
    respx.post("https://hh.ru/oauth/token").mock(
        return_value=httpx.Response(200, json={"access_token": "new", "refresh_token": "new_refresh"})
    )

    client = HhApplicationsClient(
        client_id="cid", client_secret="secret", access_token="old", refresh_token="old_refresh",
        env_path=env_path,
    )
    apps = await client.fetch_applications()

    assert len(apps) == 1
    assert client.access_token == "new"
    content = env_path.read_text(encoding="utf-8")
    assert "HH_ACCESS_TOKEN=new" in content
    assert "HH_REFRESH_TOKEN=new_refresh" in content


@pytest.mark.asyncio
@respx.mock
async def test_fetch_applications_raises_oauth_error_when_refresh_fails(tmp_path: Path) -> None:
    respx.get("https://api.hh.ru/negotiations").mock(return_value=httpx.Response(401))
    respx.post("https://hh.ru/oauth/token").mock(return_value=httpx.Response(400))

    client = HhApplicationsClient(
        client_id="cid", client_secret="secret", access_token="old", refresh_token="bad",
        env_path=tmp_path / ".env",
    )
    with pytest.raises(HhOAuthError):
        await client.fetch_applications()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_applications_raises_when_items_key_missing() -> None:
    respx.get("https://api.hh.ru/negotiations").mock(return_value=httpx.Response(200, json={"pages": 1}))
    client = HhApplicationsClient(
        client_id="cid", client_secret="secret", access_token="token", refresh_token="rtoken",
        env_path=Path("unused.env"),
    )
    with pytest.raises(SourceUnavailableError):
        await client.fetch_applications()
