from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

SOURCE_HEALTH_LOGGER = "lead_radar.source_health"

_SECRET_KEYS = {"bot_token", "telegram_api_hash", "channel_id", "token", "api_hash", "session"}

_STANDARD_RECORD_KEYS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
    "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
    "relativeCreated", "thread", "threadName", "processName", "process", "taskName",
}


class JsonFormatter(logging.Formatter):
    """Структурный лог в одну JSON-строку на запись. Никогда не пишет значения секретов -
    вызывающий код обязан не класть их в extra."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_KEYS or key in _SECRET_KEYS:
                continue
            try:
                json.dumps(value)
            except TypeError:
                value = str(value)
            extra[key] = value
        if extra:
            payload["extra"] = extra
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(log_dir: Path, level: str = "INFO") -> None:
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = JsonFormatter()

    file_handler = RotatingFileHandler(
        log_dir / "lead_radar.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger("lead_radar")
    root.setLevel(level)
    root.handlers = [file_handler, console_handler]
    root.propagate = False


def log_source_degraded(source_id: str, reason: str) -> None:
    """Единая точка логирования отказа источника - на неё смотрят при поиске проблем."""
    logging.getLogger(SOURCE_HEALTH_LOGGER).warning(
        "source_degraded", extra={"source_id": source_id, "reason": reason, "event": "source_degraded"}
    )
