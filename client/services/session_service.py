"""Session Service Module.

HTTP-facing session service that centralizes session-related backend calls.
"""

from __future__ import annotations

from typing import Any, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.network.http_client import get_http_client


setup_logging()
logger = logging.get_logger(__name__)


class SessionService:
    """Encapsulate session-related HTTP operations."""

    def __init__(self) -> None:
        self._http = get_http_client()

    async def fetch_session(self, session_id: str) -> dict[str, Any]:
        """Fetch one session payload from the backend."""
        payload = await self._http.get(f"/sessions/{session_id}")
        return dict(payload or {})

    async def fetch_sessions(self) -> list[dict[str, Any]]:
        """Fetch the current user's remote session snapshot."""
        payload = await self._http.get("/sessions")
        if not isinstance(payload, list):
            logger.warning("Unexpected sessions payload: %r", payload)
            return []
        return [dict(item) for item in payload if isinstance(item, dict)]

    async def fetch_unread_counts(self) -> list[dict[str, Any]]:
        """Fetch authoritative unread counts for all sessions."""
        payload = await self._http.get("/sessions/unread")
        if not isinstance(payload, list):
            logger.warning("Unexpected unread-count payload: %r", payload)
            return []
        return [dict(item) for item in payload if isinstance(item, dict)]

    async def create_direct_session(self, user_id: str) -> dict[str, Any]:
        """Create one direct session for the given user."""
        payload = await self._http.post(
            "/sessions/direct",
            json={
                "participant_ids": [user_id],
                "encryption_mode": "e2ee_private",
            },
        )
        return dict(payload or {})


_session_service: Optional[SessionService] = None


def get_session_service() -> SessionService:
    """Get the global session service instance."""
    global _session_service
    if _session_service is None:
        _session_service = SessionService()
    return _session_service

