from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

Outcome = Literal["ignored", "replied", "negotiating", "won", "lost"]
ActionStatus = Literal["pending", "done", "snoozed", "dropped"]
CompanyStatus = Literal["new", "contacted", "negotiating", "won", "lost", "on_hold"]


class RawLead(BaseModel):
    """Сырая запись коллектора до скоринга и дедупликации."""

    source_id: str
    external_id: str
    url: str | None = None
    title: str | None = None
    text: str | None = None
    raw_budget: str | None = None
    published_at: datetime | None = None
    author_handle: str | None = None
    meta: dict[str, Any] = {}


class Lead(BaseModel):
    id: int | None = None
    source_id: str
    external_id: str
    url: str | None = None
    title: str | None = None
    text: str | None = None
    published_at: datetime | None = None
    collected_at: datetime | None = None
    budget_min: int | None = None
    budget_max: int | None = None
    budget_currency: str | None = None
    budget_confidence: float | None = None
    stack_tags: list[str] = []
    content_hash: str | None = None
    duplicate_of: int | None = None
    score: float | None = None
    author_handle: str | None = None
    raw_meta: dict[str, Any] = {}
    ai_assistable: bool = False


class LeadOutcome(BaseModel):
    lead_id: int
    notified_at: datetime | None = None
    replied_at: datetime | None = None
    outcome: Outcome | None = None
    amount: int | None = None
    notes: str | None = None


class Action(BaseModel):
    id: int | None = None
    title: str
    description: str | None = None
    priority: int
    due_date: date | None = None
    recurrence: str | None = None
    status: ActionStatus = "pending"
    created_at: datetime | None = None
    completed_at: datetime | None = None
    snooze_count: int = 0
    expected_value: str | None = None
    company_id: int | None = None


class Company(BaseModel):
    id: int | None = None
    name: str
    contact_person: str | None = None
    contact_info: str | None = None
    status: CompanyStatus = "new"
    result: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class HhApplication(BaseModel):
    id: str
    vacancy_id: str | None = None
    vacancy_title: str | None = None
    vacancy_url: str | None = None
    state: str | None = None
    hh_created_at: datetime | None = None
    hh_updated_at: datetime | None = None
    last_synced_at: datetime | None = None
    last_notified_state: str | None = None


class Payment(BaseModel):
    id: int | None = None
    amount: int
    currency: str = "RUB"
    received_at: date
    lead_id: int | None = None
    company_id: int | None = None
    note: str | None = None
    created_at: datetime | None = None


class HealthStatus(BaseModel):
    source_id: str
    ok: bool
    checked_at: datetime
    last_error: str | None = None
    consecutive_failures: int = 0
