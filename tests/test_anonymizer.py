from __future__ import annotations

from src.export.anonymizer import anonymize_text


def _anon(text: str) -> str:
    result = anonymize_text(text)
    assert result is not None
    return result


def test_removes_ru_phone_with_separators() -> None:
    result = _anon("Звоните +7 (999) 123-45-67 в любое время")
    assert "999" not in result
    assert "123-45-67" not in result


def test_removes_ru_phone_without_separators() -> None:
    result = _anon("Мой номер 89991234567 для связи")
    assert "89991234567" not in result


def test_removes_email() -> None:
    result = _anon("Пишите на customer@example.com по любым вопросам")
    assert "customer@example.com" not in result
    assert "@" not in result or "example.com" not in result


def test_removes_telegram_username() -> None:
    result = _anon("Пишите в личку @ivan_petrov87 по проекту")
    assert "@ivan_petrov87" not in result


def test_removes_profile_link() -> None:
    result = _anon("Смотрите портфолио https://kwork.ru/user/some_seller здесь")
    assert "kwork.ru/user/some_seller" not in result


def test_removes_telegram_profile_link() -> None:
    result = _anon("Свяжитесь через https://t.me/some_customer прямо сейчас")
    assert "t.me/some_customer" not in result


def test_replaces_person_name_after_signal_phrase() -> None:
    result = _anon("Меня зовут Александр Иванов, нужна доработка сайта")
    assert "Александр" not in result
    assert "Иванов" not in result
    assert "[PERSON]" in result


def test_replaces_name_after_contact_signal() -> None:
    result = _anon("Заказчик: Мария, бюджет 20000 руб")
    assert "Мария" not in result
    assert "[PERSON]" in result


def test_keeps_order_text_stack_and_budget_language_intact() -> None:
    text = "Нужно доработать API на ASP.NET Core, бюджет 25000 руб, интеграция с эквайрингом"
    result = _anon(text)
    assert "ASP.NET Core" in result
    assert "25000" in result
    assert "интеграция" in result
    assert "эквайрингом" in result


def test_does_not_touch_iso_dates() -> None:
    result = _anon("Дедлайн 2026-08-25, работы на 3 дня")
    assert "2026-08-25" in result


def test_does_not_touch_plain_budget_numbers() -> None:
    result = _anon("Бюджет 150000 руб, готовы обсуждать")
    assert "150000" in result


def test_empty_and_none_safe() -> None:
    assert anonymize_text("") == ""
    assert anonymize_text(None) is None


def test_multiple_pii_types_in_one_text() -> None:
    text = (
        "Меня зовут Пётр Сидоров, звоните +7 999 111-22-33 или пишите на "
        "peter@example.com, тг @petr_sidorov. Нужна доработка бэкенда, бюджет 30000 руб."
    )
    result = _anon(text)
    assert "Пётр" not in result
    assert "Сидоров" not in result
    assert "999" not in result
    assert "peter@example.com" not in result
    assert "@petr_sidorov" not in result
    assert "бэкенда" in result
    assert "30000" in result
