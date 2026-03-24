"""Contact-related event bus topics."""

from __future__ import annotations


class ContactEvent:
    """Contact/UI sync event types emitted from realtime mutations."""

    SYNC_REQUIRED = "contact_sync_required"
