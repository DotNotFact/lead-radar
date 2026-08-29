from __future__ import annotations

from pydantic import BaseModel


class SourceStatus(BaseModel):
    id: str
    tier: int
    enabled: bool
    poll_interval: int
    last_ok_at: str | None
    last_error: str | None
    consecutive_failures: int
    requires_restart_to_enable: bool


class ToggleSourceRequest(BaseModel):
    enabled: bool


class MeResponse(BaseModel):
    id: int
    first_name: str | None
    username: str | None
