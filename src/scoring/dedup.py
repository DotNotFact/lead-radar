from __future__ import annotations

import hashlib
import re

_URL_RE = re.compile(r"https?://\S+")
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "]+",
    re.UNICODE,
)
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Нижний регистр, убраны ссылки, эмодзи, пунктуация, лишние пробелы — для сравнения
    кросспостов одного и того же заказа в разных чатах."""
    lowered = text.lower()
    no_urls = _URL_RE.sub(" ", lowered)
    no_emoji = _EMOJI_RE.sub(" ", no_urls)
    no_punct = _PUNCT_RE.sub(" ", no_emoji)
    return _WHITESPACE_RE.sub(" ", no_punct).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def levenshtein_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous_row = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current_row = [i]
        for j, char_b in enumerate(b, start=1):
            insert_cost = current_row[j - 1] + 1
            delete_cost = previous_row[j] + 1
            substitute_cost = previous_row[j - 1] + (char_a != char_b)
            current_row.append(min(insert_cost, delete_cost, substitute_cost))
        previous_row = current_row
    return previous_row[-1]


def similarity_ratio(a: str, b: str) -> float:
    """1.0 = идентичны, 0.0 = ничего общего."""
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    return 1.0 - levenshtein_distance(a, b) / max_len


def is_near_duplicate(a: str, b: str, threshold: float = 0.9) -> bool:
    """a, b — уже нормализованный текст (normalize_text)."""
    return similarity_ratio(a, b) >= threshold
