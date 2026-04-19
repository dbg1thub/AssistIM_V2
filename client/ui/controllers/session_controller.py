"""
Session Controller Module

Controller for session list interactions.
"""

from typing import Any, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.managers.session_manager import get_session_manager

setup_logging()
logger = logging.get_logger(__name__)


class SessionController:
    """
    Controller for session list.

    Responsibilities:
        - Handle session selection
        - Coordinate with SessionManager
        - Emit events for UI updates
    """

    def __init__(self):
        self._session_manager = get_session_manager()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize session controller."""
        if self._initialized:
            return

        self._initialized = True
        logger.info("Session controller initialized")

    async def select_session(self, session_id: str) -> None:
        """Select a session."""
        await self._session_manager.select_session(session_id)
        logger.info(f"Session selected: {session_id}")

    async def clear_selection(self) -> None:
        """Clear current session selection."""
        await self._session_manager.clear_current_session()

    def get_current_session(self) -> Optional[Any]:
        """Get current selected session."""
        return self._session_manager.current_session

    def get_current_session_id(self) -> Optional[str]:
        """Get current session ID."""
        return self._session_manager.current_session_id

    def get_sessions(self) -> list[Any]:
        """Get all sessions."""
        return list(self._session_manager.sessions)

    def get_session(self, session_id: str) -> Optional[Any]:
        """Get one session by id from the current cached list."""
        for session in self._session_manager.sessions:
            if getattr(session, "session_id", None) == session_id:
                return session
        return None

    async def remove_session(self, session_id: str) -> None:
        """Remove a session."""
        await self._session_manager.remove_session(session_id)

    async def set_pinned(self, session_id: str, pinned: bool) -> None:
        """Persist pinned state for a session."""
        await self._session_manager.set_pinned(session_id, pinned)

    async def set_muted(self, session_id: str, muted: bool) -> None:
        """Persist local do-not-disturb state for a session."""
        await self._session_manager.set_muted(session_id, muted)

    async def set_group_member_nickname_visibility(self, session_id: str, enabled: bool) -> None:
        """Persist the local group-member label visibility preference for a session."""
        await self._session_manager.set_group_member_nickname_visibility(session_id, enabled)

    async def set_ai_reply_suggestions_enabled(self, session_id: str, enabled: bool) -> None:
        """Persist the per-session smart-reply toggle locally."""
        await self._session_manager.set_ai_reply_suggestions_enabled(session_id, enabled)

    async def set_ai_auto_translate_enabled(self, session_id: str, enabled: bool) -> None:
        """Persist the per-session incoming-translation toggle locally."""
        await self._session_manager.set_ai_auto_translate_enabled(session_id, enabled)

    async def apply_group_payload(self, session_id: str, payload: dict[str, Any], *, include_self_fields: bool) -> Optional[Any]:
        """Apply one authoritative group payload to the cached session state."""
        return await self._session_manager.apply_group_payload(
            session_id,
            payload,
            include_self_fields=include_self_fields,
        )

    async def mark_group_announcement_viewed(self, session_id: str, announcement_message_id: str) -> Optional[Any]:
        """Persist that one group announcement version was opened by the current user."""
        return await self._session_manager.mark_group_announcement_viewed(session_id, announcement_message_id)

    def is_session_muted(self, session_id: str) -> bool:
        """Return whether local do-not-disturb is enabled for a session."""
        return self._session_manager.is_session_muted(session_id)

    async def mark_session_unread(self, session_id: str, unread: bool) -> None:
        """Toggle unread state for a session."""
        await self._session_manager.mark_session_unread(session_id, unread)

    async def close(self) -> None:
        """Close the lightweight session controller state and retire the singleton."""
        self._initialized = False
        global _session_controller
        if _session_controller is self:
            _session_controller = None


_session_controller: Optional[SessionController] = None


def peek_session_controller() -> Optional[SessionController]:
    """Return the existing session controller singleton if it was created."""
    return _session_controller


def get_session_controller() -> SessionController:
    """Get the global session controller instance."""
    global _session_controller
    if _session_controller is None:
        _session_controller = SessionController()
    return _session_controller
