from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_templates(config_dir: Path) -> dict[str, dict[str, Any]]:
    """Шаблоны первого ответа из config/templates.yaml. Пустой словарь, если файла нет или
    он пуст - деградация вместо падения, команды бота просто скажут "шаблонов нет"."""
    path = config_dir / "templates.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    templates = data.get("templates") or {}
    return dict(templates)
