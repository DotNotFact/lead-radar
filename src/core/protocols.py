from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.core.models import HealthStatus, RawLead


class Collector(Protocol):
    """Единый интерфейс источника. Новый источник = новый файл в src/collectors/,
    без правок в ядре."""

    source_id: str
    tier: int
    poll_interval: int

    async def fetch(self, since: datetime) -> list[RawLead]: ...

    async def health(self) -> HealthStatus: ...
