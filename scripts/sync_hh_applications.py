"""Синхронизация собственных откликов на hh.ru: подтягивает статусы, определяет изменения.
Требует OAuth-токен - см. python -m scripts.hh_oauth_login.
Запуск: python -m scripts.sync_hh_applications
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TypedDict

from src.collectors.hh_applications import HhApplicationsClient, HhOAuthError
from src.core import repository
from src.core.config import Settings, get_settings
from src.core.db import apply_migrations, get_connection
from src.core.http import SourceUnavailableError
from src.core.logging_config import log_source_degraded, setup_logging
from src.core.models import HhApplication

logger = logging.getLogger("lead_radar.scripts.sync_hh_applications")

SOURCE_ID = "hh_applications"


class SyncResult(TypedDict):
    configured: bool
    changed: list[HhApplication]
    error: str | None


def is_configured(settings: Settings) -> bool:
    return bool(
        settings.hh_client_id
        and settings.hh_client_secret
        and settings.hh_access_token
        and settings.hh_refresh_token
    )


async def sync_hh_applications(settings: Settings, env_path: Path) -> SyncResult:
    """changed - отклики, у которых состояние отличается от последнего, о котором уведомляли
    владельца (см. repository.upsert_hh_application про last_notified_state)."""
    if not is_configured(settings):
        return {"configured": False, "changed": [], "error": None}

    client = HhApplicationsClient(
        client_id=settings.hh_client_id,
        client_secret=settings.hh_client_secret,
        access_token=settings.hh_access_token,
        refresh_token=settings.hh_refresh_token,
        env_path=env_path,
        contact_email=settings.contact_email,
    )

    await apply_migrations(settings.db_path, settings.migrations_dir)
    conn = await get_connection(settings.db_path)
    changed: list[HhApplication] = []
    try:
        await repository.ensure_source(conn, SOURCE_ID, 1)
        try:
            applications = await client.fetch_applications()
        except (SourceUnavailableError, HhOAuthError) as exc:
            await repository.mark_source_failed(conn, SOURCE_ID, str(exc))
            log_source_degraded(SOURCE_ID, str(exc))
            return {"configured": True, "changed": [], "error": str(exc)}

        for app in applications:
            existing = await repository.get_hh_application(conn, app.id)
            if existing is not None:
                baseline = existing.last_notified_state or existing.state
                if app.state is not None and app.state != baseline:
                    changed.append(app)
            await repository.upsert_hh_application(conn, app)

        await repository.mark_source_ok(conn, SOURCE_ID)
    finally:
        await conn.close()

    return {"configured": True, "changed": changed, "error": None}


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_dir, settings.log_level)
    env_path = Path(".env")

    result = await sync_hh_applications(settings, env_path)
    if not result["configured"]:
        print("hh_applications: не настроено (HH_CLIENT_ID/SECRET/ACCESS_TOKEN/REFRESH_TOKEN) - "
              "см. python -m scripts.hh_oauth_login")
    elif result["error"]:
        print(f"hh_applications: ошибка - {result['error']}")
    else:
        changed = result["changed"]
        print(f"hh_applications: синхронизировано, изменений статуса: {len(changed)}")
        for app in changed:
            print(f"  [{app.id}] {app.vacancy_title} -> {app.state}")


if __name__ == "__main__":
    asyncio.run(main())
