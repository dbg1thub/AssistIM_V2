"""Moment-related event bus topics."""

from __future__ import annotations


class MomentEvent:
    """Moment/UI sync event types emitted from realtime mutations."""

    SYNC_REQUIRED = "moment_sync_required"
