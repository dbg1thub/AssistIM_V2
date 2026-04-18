from __future__ import annotations

from typing import Any

from client.core.datetime_utils import coerce_local_datetime


TIME_BUCKET_BREAK_SECONDS = 5 * 60


def normalize_chat_bucket_timestamp(value: Any):
    """Normalize a message timestamp for chat time-bucket comparisons."""
    return coerce_local_datetime(value)


def is_chat_time_break(current_value: Any, next_value: Any) -> bool:
    """Return whether two adjacent messages should be split into different chat buckets."""
    current_time = normalize_chat_bucket_timestamp(current_value)
    next_time = normalize_chat_bucket_timestamp(next_value)
    if current_time is None or next_time is None:
        return False
    if current_time.date() != next_time.date():
        return True
    return abs((next_time - current_time).total_seconds()) >= TIME_BUCKET_BREAK_SECONDS


__all__ = [
    "TIME_BUCKET_BREAK_SECONDS",
    "is_chat_time_break",
    "normalize_chat_bucket_timestamp",
]
