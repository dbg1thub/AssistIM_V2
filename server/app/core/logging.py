"""Logging configuration."""

from __future__ import annotations

import logging
from pathlib import Path
from logging.config import dictConfig

from app.core.config import get_settings
from app.core.runtime_diagnostics import InMemoryDiagnosticLogHandler


def configure_logging() -> None:
    """Configure structured-ish logging output."""
    settings = get_settings()
    log_dir = Path(settings.log_dir).expanduser().resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "assistim.log"
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": (
                        "%(asctime)s level=%(levelname)s logger=%(name)s "
                        "message=%(message)s"
                    ),
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                },
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "default",
                    "filename": str(log_file),
                    "maxBytes": int(settings.log_file_max_bytes),
                    "backupCount": int(settings.log_file_backup_count),
                    "encoding": "utf-8",
                },
            },
            "root": {
                "handlers": ["console", "file"],
                "level": "INFO",
            },
        }
    )
    root_logger = logging.getLogger()
    if not any(isinstance(handler, InMemoryDiagnosticLogHandler) for handler in root_logger.handlers):
        root_logger.addHandler(InMemoryDiagnosticLogHandler())


logger = logging.getLogger("assistim")
