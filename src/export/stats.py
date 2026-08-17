from __future__ import annotations

from typing import Any


def format_stats_message(period_label: str, conversion: list[dict[str, Any]], budgets: list[dict[str, Any]]) -> str:
    lines = [f"📊 Статистика за {period_label}"]

    if conversion:
        lines.append("\nПо источникам (собрано / уведомлено / ответил / выиграно):")
        for row in conversion:
            lines.append(
                f"• {row['source_id']}: {row['collected']} / {row['notified']} / "
                f"{row['replied']} / {row['won']}"
            )
    else:
        lines.append("\nЗа этот период данных нет.")

    if budgets and any(b["count"] for b in budgets):
        lines.append("\nРаспределение бюджетов:")
        for bucket in budgets:
            label = f"{bucket['low']}+" if bucket["high"] is None else f"{bucket['low']}-{bucket['high']}"
            lines.append(f"• {label} ₽: {bucket['count']}")

    return "\n".join(lines)
