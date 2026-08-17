from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.core.models import Lead

CALLBACK_PREFIX = "outcome"


def build_lead_keyboard(lead: Lead) -> InlineKeyboardMarkup:
    if lead.id is None:
        raise ValueError("Lead должен быть сохранён в БД (иметь id) до отправки уведомления")

    buttons: list[InlineKeyboardButton] = []
    if lead.url:
        buttons.append(InlineKeyboardButton(text="Открыть", url=lead.url))
    buttons.append(
        InlineKeyboardButton(text="Ответил", callback_data=f"{CALLBACK_PREFIX}:replied:{lead.id}")
    )
    buttons.append(
        InlineKeyboardButton(text="Мимо", callback_data=f"{CALLBACK_PREFIX}:ignored:{lead.id}")
    )
    return InlineKeyboardMarkup(inline_keyboard=[buttons])
