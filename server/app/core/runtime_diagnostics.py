"""In-process runtime diagnostics for the development dashboard."""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


MAX_HTTP_RECORDS = 120
MAX_LOG_RECORDS = 120


def _iso_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(float(timestamp), UTC).isoformat()


@dataclass(slots=True)
class RuntimeHttpRequestRecord:
    method: str
    path: str
    status_code: int
    duration_ms: float
    user_id: str
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "path": self.path,
            "status_code": self.status_code,
            "duration_ms": self.duration_ms,
            "user_id": self.user_id,
            "timestamp": _iso_from_timestamp(self.timestamp),
        }


@dataclass(slots=True)
class RuntimeLogRecord:
    level: str
    logger: str
    message: str
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "logger": self.logger,
            "message": self.message,
            "timestamp": _iso_from_timestamp(self.timestamp),
        }


class RuntimeDiagnosticsStore:
    """Small thread-safe in-memory store for recent runtime diagnostics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._http_records: deque[RuntimeHttpRequestRecord] = deque(maxlen=MAX_HTTP_RECORDS)
        self._log_records: deque[RuntimeLogRecord] = deque(maxlen=MAX_LOG_RECORDS)
        self._total_requests = 0
        self._error_requests = 0
        self._slow_requests = 0

    def record_http_request(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        user_id: str,
        timestamp: float,
        slow_request_ms: int,
    ) -> None:
        normalized_status = int(status_code or 0)
        record = RuntimeHttpRequestRecord(
            method=str(method or "").upper(),
            path=str(path or ""),
            status_code=normalized_status,
            duration_ms=round(float(duration_ms or 0.0), 2),
            user_id=str(user_id or "anonymous"),
            timestamp=float(timestamp),
        )
        with self._lock:
            self._total_requests += 1
            if normalized_status >= 400:
                self._error_requests += 1
            if record.duration_ms >= max(0, int(slow_request_ms or 0)):
                self._slow_requests += 1
            self._http_records.append(record)

    def record_log(self, record: logging.LogRecord) -> None:
        if int(record.levelno) < logging.WARNING:
            return
        log_record = RuntimeLogRecord(
            level=str(record.levelname or ""),
            logger=str(record.name or ""),
            message=record.getMessage(),
            timestamp=float(record.created),
        )
        with self._lock:
            self._log_records.append(log_record)

    def reset(self) -> None:
        with self._lock:
            self._http_records.clear()
            self._log_records.clear()
            self._total_requests = 0
            self._error_requests = 0
            self._slow_requests = 0

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            http_records = list(self._http_records)
            log_records = list(self._log_records)
            return {
                "http": {
                    "total_requests": self._total_requests,
                    "error_requests": self._error_requests,
                    "slow_requests": self._slow_requests,
                    "recent": [item.to_dict() for item in reversed(http_records)],
                },
                "logs": {
                    "recent_warnings_errors": [item.to_dict() for item in reversed(log_records)],
                },
            }


class InMemoryDiagnosticLogHandler(logging.Handler):
    """Logging handler that mirrors warnings/errors into RuntimeDiagnosticsStore."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            runtime_diagnostics.record_log(record)
        except Exception:
            pass


runtime_diagnostics = RuntimeDiagnosticsStore()


def record_http_request(
    *,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    user_id: str,
    timestamp: float,
    slow_request_ms: int,
) -> None:
    runtime_diagnostics.record_http_request(
        method=method,
        path=path,
        status_code=status_code,
        duration_ms=duration_ms,
        user_id=user_id,
        timestamp=timestamp,
        slow_request_ms=slow_request_ms,
    )


def runtime_diagnostics_snapshot() -> dict[str, Any]:
    return runtime_diagnostics.snapshot()


def reset_runtime_diagnostics() -> None:
    runtime_diagnostics.reset()
