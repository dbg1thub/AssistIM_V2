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


def isoformat_utc(value: datetime | None) -> str | None:
    """Serialize one datetime while preserving naive wall-clock values."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.isoformat()
    return ensure_utc(value).isoformat()



