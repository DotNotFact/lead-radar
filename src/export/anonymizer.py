from __future__ import annotations

import re

# Телефон: РФ/международный, с разделителями или без, 10 значащих цифр (3-3-2-2) с
# опциональным кодом страны. Требование ровно такой группировки цифр отличает номера от
# обычных чисел бюджета в тексте ("150000 руб") и дат ("2026-08-25" - группировка 4-2-2).
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+\d{1,3}|8)?[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?!\d)"
)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")

_USERNAME_RE = re.compile(r"@[A-Za-z][A-Za-z0-9_]{2,31}")

_PROFILE_LINK_RE = re.compile(
    r"https?://\S*(?:t\.me|/user/|/users/|/resume/)\S*", re.IGNORECASE
)

# Эвристика для имён: срабатывает только после сигнальной фразы ("меня зовут", "заказчик:", ...).
# Это не NER, полноценного распознавания сущностей в стеке нет - ложноотрицательные случаи
# (имя без сигнальной фразы) не ловятся. Задокументировано в CLAUDE.md.
_NAME_SIGNAL_RE = re.compile(
    r"(меня зовут|мо[йя] имя(?:\s*[:\-])?|заказчик|исполнитель|контактное лицо|контакт)"
    r"\s*[:\-]?\s*"
    r"([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)",
    re.IGNORECASE,
)


def _replace_name(match: re.Match[str]) -> str:
    return f"{match.group(1)}: [PERSON]"


def anonymize_text(text: str | None) -> str | None:
    """Вырезает PII из свободного текста лида перед экспортом (инвариант 5: экспорт всегда
    обезличен). Телефоны/email/@username/ссылки на профили - удаляются полностью. Имена людей,
    распознанные по сигнальной фразе, заменяются на [PERSON]."""
    if not text:
        return text

    result = _EMAIL_RE.sub("", text)
    result = _PROFILE_LINK_RE.sub("", result)
    result = _USERNAME_RE.sub("", result)
    result = _PHONE_RE.sub("", result)
    result = _NAME_SIGNAL_RE.sub(_replace_name, result)
    return re.sub(r"[ \t]{2,}", " ", result).strip()
