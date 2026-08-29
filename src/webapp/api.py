from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Annotated, cast

import aiosqlite
from fastapi import APIRouter, Depends, Header, HTTPException

from scripts.collect_freelancer import is_configured as freelancer_configured
from src.core import repository, runtime_settings
from src.core.config import Settings, get_settings
from src.core.db import get_connection
from src.core.yaml_config import SourcesConfig, load_sources_config
from src.webapp.auth import InitDataAuthError, TelegramUser, validate_init_data
from src.webapp.schemas import MeResponse, SourceStatus, ToggleSourceRequest

logger = logging.getLogger("lead_radar.webapp.api")

router = APIRouter(prefix="/api")

# Источники с job'ой в планировщике (src/main.py), которая перечитывает override при каждом
# прогоне - для них выключение уже запущенного источника действует немедленно. telegram
# работает через постоянное соединение, запускаемое один раз при старте процесса - для него
# любое изменение требует перезапуска, см. SourceStatus.requires_restart_to_enable ниже.
_POLLED_SOURCE_IDS = frozenset(
    {"hh_ru", "kwork_projects", "kwork_catalog", "remoteok", "freelancer", "rss_remote_jobs"}
)
_ALL_SOURCE_IDS = _POLLED_SOURCE_IDS | {"telegram"}


def _get_settings() -> Settings:
    return get_settings()


async def get_db(settings: Annotated[Settings, Depends(_get_settings)]) -> AsyncGenerator[aiosqlite.Connection, None]:
    conn = await get_connection(settings.db_path)
    try:
        yield conn
    finally:
        await conn.close()


async def require_owner(
    settings: Annotated[Settings, Depends(_get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> TelegramUser:
    if settings.miniapp_owner_telegram_id is None:
        logger.error("miniapp_owner_telegram_id_not_configured")
        raise HTTPException(status_code=500, detail="MINIAPP_OWNER_TELEGRAM_ID не настроен в .env")

    if not authorization or not authorization.startswith("tma "):
        raise HTTPException(status_code=401, detail='Ожидается заголовок Authorization: "tma <initData>"')
    init_data = authorization.removeprefix("tma ").strip()

    if not settings.bot_token:
        logger.error("miniapp_bot_token_not_configured")
        raise HTTPException(status_code=500, detail="BOT_TOKEN не настроен в .env")

    try:
        return validate_init_data(init_data, bot_token=settings.bot_token, owner_id=settings.miniapp_owner_telegram_id)
    except InitDataAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/me")
async def get_me(user: Annotated[TelegramUser, Depends(require_owner)]) -> MeResponse:
    return MeResponse(id=user.id, first_name=user.first_name, username=user.username)


def _source_config(sources_config: SourcesConfig, source_id: str) -> tuple[bool, int]:
    """(enabled в sources.yaml, poll_interval) для источника; отсутствующая запись = выключен."""
    config = sources_config.sources.get(source_id)
    if config is None:
        return False, 0
    return config.enabled, config.poll_interval


def _consecutive_failures(row: dict[str, object] | None) -> int:
    # repository.list_sources() возвращает dict[str, object] (намеренно нетипизированный,
    # общий для нескольких вызывающих) - здесь мы знаем схему БД (INTEGER NOT NULL DEFAULT 0).
    return cast(int, row["consecutive_failures"]) if row else 0


def _requires_restart_to_enable(source_id: str, sources_config: SourcesConfig, settings: Settings) -> bool:
    if source_id == "telegram":
        # Постоянное Telethon-соединение поднимается один раз в main.py при старте - нет
        # job'ы, которая перечитывала бы override на лету.
        return True

    yaml_enabled, _ = _source_config(sources_config, source_id)
    if not yaml_enabled:
        return True
    if source_id == "freelancer" and not freelancer_configured(settings):
        return True
    return False


@router.get("/sources")
async def list_sources(
    _user: Annotated[TelegramUser, Depends(require_owner)],
    settings: Annotated[Settings, Depends(_get_settings)],
    conn: Annotated[aiosqlite.Connection, Depends(get_db)],
) -> list[SourceStatus]:
    sources_config = load_sources_config(settings.config_dir)
    db_rows = {row["id"]: row for row in await repository.list_sources(conn)}

    result: list[SourceStatus] = []
    for source_id in sorted(_ALL_SOURCE_IDS):
        yaml_enabled, poll_interval = _source_config(sources_config, source_id)
        effective_enabled = await runtime_settings.get_source_enabled(conn, source_id, default=yaml_enabled)
        row = db_rows.get(source_id)

        result.append(
            SourceStatus(
                id=source_id,
                tier=sources_config.sources[source_id].tier if source_id in sources_config.sources else 0,
                enabled=effective_enabled,
                poll_interval=poll_interval,
                last_ok_at=str(row["last_ok_at"]) if row and row["last_ok_at"] else None,
                last_error=str(row["last_error"]) if row and row["last_error"] else None,
                consecutive_failures=_consecutive_failures(row),
                requires_restart_to_enable=_requires_restart_to_enable(source_id, sources_config, settings),
            )
        )
    return result


@router.post("/sources/{source_id}/toggle")
async def toggle_source(
    source_id: str,
    body: ToggleSourceRequest,
    _user: Annotated[TelegramUser, Depends(require_owner)],
    settings: Annotated[Settings, Depends(_get_settings)],
    conn: Annotated[aiosqlite.Connection, Depends(get_db)],
) -> SourceStatus:
    if source_id not in _ALL_SOURCE_IDS:
        raise HTTPException(status_code=404, detail=f"Неизвестный источник: {source_id}")

    await runtime_settings.set_source_enabled(conn, source_id, body.enabled)
    logger.info("source_toggled", extra={"source_id": source_id, "enabled": body.enabled})

    sources_config = load_sources_config(settings.config_dir)
    db_rows = {row["id"]: row for row in await repository.list_sources(conn)}
    row = db_rows.get(source_id)
    yaml_enabled, poll_interval = _source_config(sources_config, source_id)

    return SourceStatus(
        id=source_id,
        tier=sources_config.sources[source_id].tier if source_id in sources_config.sources else 0,
        enabled=body.enabled,
        poll_interval=poll_interval,
        last_ok_at=str(row["last_ok_at"]) if row and row["last_ok_at"] else None,
        last_error=str(row["last_error"]) if row and row["last_error"] else None,
        consecutive_failures=_consecutive_failures(row),
        requires_restart_to_enable=_requires_restart_to_enable(source_id, sources_config, settings),
    )
