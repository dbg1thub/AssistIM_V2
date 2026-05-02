"""Logging configuration."""

from __future__ import annotations

import logging
from logging.config import dictConfig

from app.core.runtime_diagnostics import InMemoryDiagnosticLogHandler


def configure_logging() -> None:
    """Configure structured-ish logging output."""
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
            },
            "root": {
                "handlers": ["console"],
                "level": "INFO",
            },
        }
    )
    root_logger = logging.getLogger()
    if not any(isinstance(handler, InMemoryDiagnosticLogHandler) for handler in root_logger.handlers):
        root_logger.addHandler(InMemoryDiagnosticLogHandler())


logger = logging.getLogger("assistim")
