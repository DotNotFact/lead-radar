from __future__ import annotations

from src.scoring.dedup import content_hash, is_near_duplicate, normalize_text, similarity_ratio


def test_normalize_strips_urls_emoji_punctuation() -> None:
    text = "Нужен C#-разработчик!!! 🔥🔥 Пишите сюда: https://t.me/somechat   срочно"
    normalized = normalize_text(text)
    assert "https" not in normalized
    assert "🔥" not in normalized
    assert "!" not in normalized
    assert "  " not in normalized  # схлопнуты пробелы


def test_identical_after_normalization_same_hash() -> None:
    a = "Нужен C# разработчик, срочно! Пишите: @vasya"
    b = "нужен c# разработчик  срочно писите: @vasya"
    # разный регистр и пунктуация, но одна и та же суть — normalize должен сблизить их
    assert normalize_text(a) != normalize_text(b)  # опечатка "писите" ломает точное совпадение
    assert similarity_ratio(normalize_text(a), normalize_text(b)) > 0.85


def test_exact_crosspost_same_hash() -> None:
    a = "Ищу разработчика C# для доработки API, бюджет 20000 руб"
    b = "ИЩУ РАЗРАБОТЧИКА C# ДЛЯ ДОРАБОТКИ API, БЮДЖЕТ 20000 РУБ!!!"
    assert content_hash(a) == content_hash(b)


def test_near_duplicate_detection() -> None:
    a = normalize_text("Нужен опытный C# разработчик для интеграции с 1С, бюджет 30000")
    b = normalize_text("Нужен опытный C# разработчик для интеграции с 1С бюджет 30000 руб")
    assert is_near_duplicate(a, b, threshold=0.85)


def test_unrelated_texts_not_duplicate() -> None:
    a = normalize_text("Ищу дизайнера для лендинга")
    b = normalize_text("Нужен бэкенд разработчик C# ASP.NET Core с опытом PostgreSQL")
    assert not is_near_duplicate(a, b)
