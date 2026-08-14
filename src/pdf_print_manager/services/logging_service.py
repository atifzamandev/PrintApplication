"""Rotating log files plus the small `SessionLogger` used to persist each
session's activity-log lines alongside whatever the UI shows live."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

_LOG_FILE_NAME = "pdf-print-manager.log"
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 5


def default_log_dir() -> Path:
    xdg_state = os.environ.get("XDG_STATE_HOME")
    xdg_data = os.environ.get("XDG_DATA_HOME")
    base = xdg_state or xdg_data
    if base:
        return Path(base) / "pdf-print-manager" / "logs"
    return Path.home() / ".local" / "share" / "pdf-print-manager" / "logs"


def configure_logging(log_dir: Optional[Path] = None) -> Path:
    """Attach a rotating file handler to the root logger. Safe to call once
    at startup; returns the directory the log file lives in."""
    log_dir = log_dir or default_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        log_dir / _LOG_FILE_NAME,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return log_dir


class SessionLogger:
    """Thin wrapper so the job manager / worker can log a session's activity
    line without reaching for `logging.getLogger(...)` directly everywhere."""

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger("pdf_print_manager.session")

    def info(self, message: str) -> None:
        self._logger.info(message)

    def warning(self, message: str) -> None:
        self._logger.warning(message)

    def error(self, message: str) -> None:
        self._logger.error(message)
