"""Logging configuration."""

from __future__ import annotations

import logging
from logging.config import dictConfig


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


logger = logging.getLogger("assistim")
