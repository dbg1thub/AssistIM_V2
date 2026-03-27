"""Pure message-action eligibility helpers shared by chat UI."""

from __future__ import annotations

from datetime import datetime

from client.core.datetime_utils import coerce_local_datetime
from client.models.message import ChatMessage, MessageStatus


RECALL_WINDOW_SECONDS = 120.0

_RECALLABLE_STATUSES = {
    MessageStatus.SENT,
    MessageStatus.RECEIVED,
    MessageStatus.DELIVERED,
    MessageStatus.READ,
    MessageStatus.EDITED,
}

_LOCAL_DELETE_STATUSES = {
    MessageStatus.PENDING,
    MessageStatus.SENDING,
    MessageStatus.FAILED,
    MessageStatus.RECALLED,
}


def message_age_seconds(message: ChatMessage, *, now: datetime | None = None) -> float:
    """Return one non-negative age for a message using the best available timestamp."""
    reference = coerce_local_datetime(message.timestamp) or coerce_local_datetime(message.updated_at)
    current = coerce_local_datetime(now) or datetime.now()
    if reference is None:
        return 0.0
    return max(0.0, (current - reference).total_seconds())


def should_offer_recall(message: ChatMessage, *, now: datetime | None = None) -> bool:
    """Return whether the context menu should offer recall for this message."""
    if not message.is_self or message.status not in _RECALLABLE_STATUSES:
        return False
    return message_age_seconds(message, now=now) <= RECALL_WINDOW_SECONDS


def should_offer_delete(message: ChatMessage, *, now: datetime | None = None) -> bool:
    """Return whether the context menu should offer local delete for this message."""
    if not message.is_self:
        return True
    if message.status in _LOCAL_DELETE_STATUSES:
        return True
    return not should_offer_recall(message, now=now)
