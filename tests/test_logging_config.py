from __future__ import annotations

import json
import logging
from pathlib import Path

from src.core.logging_config import log_source_degraded, setup_logging


def test_setup_logging_writes_json_lines(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    setup_logging(log_dir, level="INFO")

    logger = logging.getLogger("lead_radar.test")
    logger.info("hello", extra={"foo": "bar"})

    log_file = log_dir / "lead_radar.log"
    assert log_file.exists()

    line = log_file.read_text(encoding="utf-8").strip().splitlines()[-1]
    record = json.loads(line)
    assert record["message"] == "hello"
    assert record["extra"]["foo"] == "bar"


def test_log_source_degraded_never_leaks_secret_keys(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    setup_logging(log_dir, level="INFO")

    log_source_degraded("kwork", "structure changed")

    log_file = log_dir / "lead_radar.log"
    line = log_file.read_text(encoding="utf-8").strip().splitlines()[-1]
    record = json.loads(line)
    assert record["extra"]["source_id"] == "kwork"
    assert record["extra"]["event"] == "source_degraded"
