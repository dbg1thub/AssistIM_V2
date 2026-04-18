from datetime import datetime, timedelta

from client.core.chat_time_buckets import TIME_BUCKET_BREAK_SECONDS, is_chat_time_break


def test_is_chat_time_break_returns_false_within_same_short_window() -> None:
    start = datetime(2026, 4, 19, 10, 0, 0)
    end = start + timedelta(seconds=TIME_BUCKET_BREAK_SECONDS - 1)

    assert is_chat_time_break(start, end) is False


def test_is_chat_time_break_returns_true_at_five_minutes() -> None:
    start = datetime(2026, 4, 19, 10, 0, 0)
    end = start + timedelta(seconds=TIME_BUCKET_BREAK_SECONDS)

    assert is_chat_time_break(start, end) is True


def test_is_chat_time_break_returns_true_across_day_boundary() -> None:
    start = datetime(2026, 4, 19, 23, 59, 0)
    end = datetime(2026, 4, 20, 0, 1, 0)

    assert is_chat_time_break(start, end) is True
