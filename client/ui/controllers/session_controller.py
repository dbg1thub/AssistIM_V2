"""
Session Controller Module

Controller for session list interactions.
"""

from typing import Any, Callable, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.events.event_bus import get_event_bus
from client.managers.session_manager import SessionEvent, get_session_manager

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
        self._event_bus = get_event_bus()
        self._session_manager = get_session_manager()
        self._handlers: dict[str, Callable] = {}

    async def initialize(self) -> None:
        """Initialize session controller."""
        await self._event_bus.subscribe(
            SessionEvent.UPDATED,
            self._on_session_updated,
        )
        await self._event_bus.subscribe(
            SessionEvent.MESSAGE_ADDED,
            self._on_message_added,
        )
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
        return list(self._session_manager.sessions.values())

    def _on_session_updated(self, data: dict) -> None:
        """Handle session updated event."""
        handler = self._handlers.get("session_updated")
        if handler:
            try:
                handler(data)
            except Exception as e:
                logger.error(f"Handler error: {e}")

    def _on_message_added(self, data: dict) -> None:
        """Handle message added event."""
        handler = self._handlers.get("message_added")
        if handler:
            try:
                handler(data)
            except Exception as e:
                logger.error(f"Handler error: {e}")

    def set_handler(self, event: str, handler: Callable) -> None:
        """Set event handler."""
        self._handlers[event] = handler

    def remove_handler(self, event: str) -> None:
        """Remove event handler."""
        self._handlers.pop(event, None)


_session_controller: Optional[SessionController] = None


def get_session_controller() -> SessionController:
    """Get the global session controller instance."""
    global _session_controller
    if _session_controller is None:
        _session_controller = SessionController()
    return _session_controller
