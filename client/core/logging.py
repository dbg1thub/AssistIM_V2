"""
Logging Module

Unified logging configuration with file and console handlers.
"""
import logging
import os
import sys
from dataclasses import dataclass, field
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path
from queue import Queue
from typing import Optional


DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class SafeRotatingFileHandler(RotatingFileHandler):
    """Rotating file handler that tolerates Windows file-lock rollover failures."""

    def doRollover(self) -> None:
        try:
            super().doRollover()
        except PermissionError:
            # Another local profile/process may still hold the file handle.
            # Keep logging to the current file instead of crashing stderr.
            if self.stream:
                self.stream.flush()


def _default_log_path() -> str:
    """Resolve the default log file path, isolating profiles when requested."""
    explicit_path = os.getenv("ASSISTIM_LOG_FILE", "").strip()
    if explicit_path:
        return explicit_path

    profile = os.getenv("ASSISTIM_PROFILE", "").strip()
    if profile:
        safe_profile = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in profile) or "default"
        return f"logs/assistim.{safe_profile}.log"

    return "logs/assistim.log"


@dataclass
class LogConfig:
    """Logging configuration."""
    
    level: str = field(default_factory=lambda: os.getenv("ASSISTIM_LOG_LEVEL", "INFO"))
    file_path: str = field(default_factory=_default_log_path)
    max_bytes: int = field(default_factory=lambda: int(os.getenv("ASSISTIM_LOG_MAX_BYTES", "10485760")))
    backup_count: int = field(default_factory=lambda: int(os.getenv("ASSISTIM_LOG_BACKUP_COUNT", "5")))
    format_string: str = DEFAULT_FORMAT
    enable_console: bool = True
    enable_file: bool = True


_loggers: dict[str, logging.Logger] = {}
_config: Optional[LogConfig] = None
_config_signature: Optional[tuple] = None
_queue_listener: Optional[QueueListener] = None
_queue: Optional[Queue] = None
_active_handlers: list[logging.Handler] = []


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
    
    handler = SafeRotatingFileHandler(
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
    global _config, _config_signature, _queue_listener, _queue, _active_handlers
    
    _config = config or LogConfig()
    signature = (
        _config.level,
        _config.file_path,
        _config.max_bytes,
        _config.backup_count,
        _config.enable_console,
        _config.enable_file,
    )
    if signature == _config_signature:
        return

    level = _get_level_from_string(_config.level)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    for handler in list(root_logger.handlers):
        if getattr(handler, "_assistim_handler", False):
            root_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    if _queue_listener is not None:
        _queue_listener.stop()
        _queue_listener = None

    for handler in _active_handlers:
        try:
            handler.close()
        except Exception:
            pass
    _active_handlers = []

    target_handlers: list[logging.Handler] = []

    if _config.enable_console:
        console_handler = _setup_console_handler(level)
        target_handlers.append(console_handler)

    file_handler = _setup_file_handler(_config)
    if file_handler:
        target_handlers.append(file_handler)

    if target_handlers:
        _queue = Queue(-1)
        queue_handler = QueueHandler(_queue)
        queue_handler.setLevel(logging.DEBUG)
        queue_handler._assistim_handler = True
        root_logger.addHandler(queue_handler)

        _queue_listener = QueueListener(_queue, *target_handlers, respect_handler_level=True)
        _queue_listener.start()
        _active_handlers = target_handlers
    
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    _config_signature = signature


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
