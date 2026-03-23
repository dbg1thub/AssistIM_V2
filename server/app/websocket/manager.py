"""Compatibility exports for the realtime hub."""

from __future__ import annotations

from app.realtime.hub import InMemoryRealtimeHub, RealtimeHub, get_realtime_hub


ConnectionManager = InMemoryRealtimeHub
connection_manager: RealtimeHub = get_realtime_hub()
