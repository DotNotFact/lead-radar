from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_prompts(config_dir: Path) -> dict[str, dict[str, Any]]:
    """Промпты для внешнего ИИ из config/prompts.yaml - тот же паттерн, что load_templates
    (src/control/templates.py) для ответов заказчикам. Пустой словарь, если файла нет или он
    пуст - деградация, а не падение."""
    path = config_dir / "prompts.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    prompts = data.get("prompts") or {}
    return dict(prompts)
