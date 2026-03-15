"""
Logging Module

Unified logging configuration with file and console handlers.
"""
import logging
import os
import sys
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass
class LogConfig:
    """Logging configuration."""
    
    level: str = field(default_factory=lambda: os.getenv("ASSISTIM_LOG_LEVEL", "INFO"))
    file_path: str = field(default_factory=lambda: os.getenv("ASSISTIM_LOG_FILE", "logs/assistim.log"))
    max_bytes: int = field(default_factory=lambda: int(os.getenv("ASSISTIM_LOG_MAX_BYTES", "10485760")))
    backup_count: int = field(default_factory=lambda: int(os.getenv("ASSISTIM_LOG_BACKUP_COUNT", "5")))
    format_string: str = DEFAULT_FORMAT
    enable_console: bool = True
    enable_file: bool = True


_loggers: dict[str, logging.Logger] = {}
_config: Optional[LogConfig] = None


def _setup_console_handler(level: int) -> logging.StreamHandler:
    """Create console handler with specified level."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    formatter = logging.Formatter(DEFAULT_FORMAT, DATE_FORMAT)
    handler.setFormatter(formatter)
    return handler


def _setup_file_handler(config: LogConfig) -> Optional[RotatingFileHandler]:
    """Create rotating file handler."""
    if not config.enable_file:
        return None
    
    log_path = Path(config.file_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    handler = RotatingFileHandler(
        config.file_path,
        maxBytes=config.max_bytes,
        backupCount=config.backup_count,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(DEFAULT_FORMAT, DATE_FORMAT)
    handler.setFormatter(formatter)
    return handler


def _get_level_from_string(level: str) -> int:
    """Convert string level to logging constant."""
    levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return levels.get(level.upper(), logging.INFO)


def setup_logging(config: Optional[LogConfig] = None) -> None:
    """
    Setup global logging configuration.
    
    Args:
        config: Optional logging configuration. Uses default if not provided.
    """
    global _config
    
    _config = config or LogConfig()
    level = _get_level_from_string(_config.level)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    if not root_logger.handlers:
        if _config.enable_console:
            console_handler = _setup_console_handler(level)
            root_logger.addHandler(console_handler)
        
        file_handler = _setup_file_handler(_config)
        if file_handler:
            root_logger.addHandler(file_handler)
    
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the specified name.
    
    Args:
        name: Logger name (typically __name__)
    
    Returns:
        Configured logger instance
    """
    if name not in _loggers:
        _loggers[name] = logging.getLogger(name)
    return _loggers[name]


def get_log_config() -> Optional[LogConfig]:
    """Get the current logging configuration."""
    return _config
