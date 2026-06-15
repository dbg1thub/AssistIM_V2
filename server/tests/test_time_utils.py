"""Time helper tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from app.utils.time import ensure_utc, isoformat_utc


def test_isoformat_utc_serializes_naive_values_as_explicit_utc() -> None:
    value = isoformat_utc(datetime(2026, 6, 16, 13, 0, 0))

    assert value == "2026-06-16T13:00:00+00:00"
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_isoformat_utc_normalizes_aware_values_to_utc() -> None:
    value = isoformat_utc(datetime(2026, 6, 16, 22, 0, 0, tzinfo=timezone(timedelta(hours=9))))

    assert value == "2026-06-16T13:00:00+00:00"
    assert ensure_utc(datetime.fromisoformat(value)).tzinfo is UTC
