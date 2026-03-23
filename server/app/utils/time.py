"""Time helpers."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalize one datetime to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
