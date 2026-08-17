from __future__ import annotations

from pathlib import Path


def update_env_file(path: Path, updates: dict[str, str]) -> None:
    """Точечно заменяет KEY=... строки в .env, не трогая остальное (комментарии, порядок,
    незатронутые ключи). Ключи, которых ещё нет в файле, дописываются в конец. Используется
    для сохранения OAuth-токенов hh.ru после логина/рефреша - .env остаётся единственным
    местом хранения секретов (инвариант 2)."""
    remaining = dict(updates)
    lines: list[str] = []

    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in remaining:
                    lines.append(f"{key}={remaining.pop(key)}")
                    continue
            lines.append(raw_line)

    for key, value in remaining.items():
        lines.append(f"{key}={value}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
