from __future__ import annotations

import aiosqlite

from src.core import repository
from src.core.config import Settings
from src.core.yaml_config import KeywordsConfig

_THRESHOLD_KEY = "override:score_threshold"
_MIN_BUDGET_KEY = "override:min_budget_rub"
_BRIEF_TIME_KEY = "override:daily_brief_time"


async def get_score_threshold(conn: aiosqlite.Connection, settings: Settings) -> float:
    value = await repository.get_system_state(conn, _THRESHOLD_KEY)
    return float(value) if value is not None else float(settings.score_threshold)


async def set_score_threshold(conn: aiosqlite.Connection, value: float) -> None:
    await repository.set_system_state(conn, _THRESHOLD_KEY, str(value))


async def get_min_budget_rub(conn: aiosqlite.Connection, keywords_config: KeywordsConfig) -> int:
    value = await repository.get_system_state(conn, _MIN_BUDGET_KEY)
    return int(value) if value is not None else keywords_config.budget_parsing.min_budget_rub


async def set_min_budget_rub(conn: aiosqlite.Connection, value: int) -> None:
    await repository.set_system_state(conn, _MIN_BUDGET_KEY, str(value))


async def apply_min_budget_override(
    conn: aiosqlite.Connection, keywords_config: KeywordsConfig
) -> KeywordsConfig:
    """Подставляет порог бюджета, изменённый владельцем через /set_budget_floor, вместо того
    что зашито в keywords.yaml - без этого пришлось бы лезть в файл руками. Вызывается один
    раз на весь конвейер оценки лида (src/core/pipeline.py), а не в каждом коллекторе."""
    effective = await get_min_budget_rub(conn, keywords_config)
    if effective == keywords_config.budget_parsing.min_budget_rub:
        return keywords_config
    return keywords_config.model_copy(
        update={
            "budget_parsing": keywords_config.budget_parsing.model_copy(
                update={"min_budget_rub": effective}
            )
        }
    )


async def get_daily_brief_time(conn: aiosqlite.Connection, settings: Settings) -> str:
    value = await repository.get_system_state(conn, _BRIEF_TIME_KEY)
    return value if value is not None else settings.daily_brief_time


async def set_daily_brief_time(conn: aiosqlite.Connection, value: str) -> None:
    await repository.set_system_state(conn, _BRIEF_TIME_KEY, value)
