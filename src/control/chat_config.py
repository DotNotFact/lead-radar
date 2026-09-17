from __future__ import annotations

from pathlib import Path

import yaml

_HEADER = (
    "# Чаты, добавленные через бот-команду /addchat.\n"
    "# Основной список для массового заполнения (60-100 чатов) - config/sources.yaml "
    "(telegram.chats).\n"
    "# Этот файл коллектор Telegram читает вместе с sources.yaml.\n"
)


def _runtime_chats_path(config_dir: Path) -> Path:
    return config_dir / "telegram_chats_runtime.yaml"


def load_runtime_chats(config_dir: Path) -> list[str]:
    path = _runtime_chats_path(config_dir)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [str(c) for c in (data.get("chats") or [])]


def add_runtime_chat(config_dir: Path, handle: str) -> bool:
    """Возвращает True, если чат добавлен впервые (False - уже был в списке).
    Пишет в отдельный sidecar-файл, а не в sources.yaml, чтобы не терять ручные
    комментарии владельца при перезаписи."""
    chats = load_runtime_chats(config_dir)
    if handle in chats:
        return False
    chats.append(handle)
    path = _runtime_chats_path(config_dir)
    body = "\n".join(f'  - "{c}"' for c in chats)
    path.write_text(f"{_HEADER}chats:\n{body}\n", encoding="utf-8")
    return True
