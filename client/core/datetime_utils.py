"""Shared datetime normalization helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def coerce_local_datetime(value: Any) -> datetime | None:
    """Normalize timestamp-like values into a naive local datetime.

    Server ISO strings are currently emitted as UTC without an explicit offset,
    so naive ISO values are interpreted as UTC and converted to local time.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone().replace(tzinfo=None)
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.fromtimestamp(float(text))
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone().replace(tzinfo=None)
    return None


def to_epoch_seconds(value: Any) -> float:
    """Convert timestamp-like values into epoch seconds."""
    normalized = coerce_local_datetime(value)
    if normalized is None:
        return 0.0
    return normalized.timestamp()
