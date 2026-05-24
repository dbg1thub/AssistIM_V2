"""Low-overhead UI diagnostic event buffer.

This module avoids logging on every UI transition. It records compact state in
memory and only flushes the recent trace when an anomaly is detected.
"""

from __future__ import annotations

from collections import deque
import logging
import threading
import time
from typing import Any

_MAX_EVENTS = 180
_MIN_FLUSH_INTERVAL_SECONDS = 1.5
_events: deque[tuple[float, int, str, dict[str, Any]]] = deque(maxlen=_MAX_EVENTS)
_lock = threading.Lock()
_last_flush_at = 0.0


def record_ui_event(event: str, **fields: Any) -> None:
    """Append one compact diagnostic event without writing to logs."""
    try:
        with _lock:
            _events.append((time.monotonic(), threading.get_ident(), str(event), dict(fields)))
    except Exception:
        return


def flush_ui_events(logger: logging.Logger, reason: str, **extra: Any) -> None:
    """Write the buffered diagnostic trace once when a real anomaly appears."""
    global _last_flush_at
    try:
        now = time.monotonic()
        with _lock:
            if now - _last_flush_at < _MIN_FLUSH_INTERVAL_SECONDS:
                return
            _last_flush_at = now
            items = list(_events)
        stack = str(extra.get("stack", "") or "")
        compact_extra = dict(extra)
        if stack:
            compact_extra["stack"] = "<attached>"
        if not items:
            logger.warning("[ui-diag] trace reason=%s extra=%s events=empty", reason, _compact_fields(compact_extra))
            return
        base = items[0][0]
        lines = [
            f"[ui-diag] trace reason={reason} extra={_compact_fields(compact_extra)} event_count={len(items)}"
        ]
        if stack:
            lines.append(f"stack:\n{stack}")
        for ts, thread_id, event, fields in items:
            lines.append(f"+{ts - base:.3f}s tid={thread_id} {event} {_compact_fields(fields)}")
        logger.warning("\n".join(lines))
    except Exception:
        logger.exception("[ui-diag] failed to flush diagnostic trace")


def _compact_fields(fields: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in fields.items():
        text = str(value)
        if len(text) > 260:
            text = f"{text[:260]}..."
        parts.append(f"{key}={text!r}")
    return " ".join(parts)
