"""
Session Manager Module

Manager for chat sessions, unread counts, and current session.
"""
import asyncio
from datetime import datetime
from typing import Any, Callable, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.events.event_bus import get_event_bus
from client.managers.message_manager import MessageEvent, get_message_manager
from client.models.message import ChatMessage, Session

setup_logging()
logger = logging.get_logger(__name__)


class SessionEvent:
    """Session event types."""

    CREATED = "session_created"
    UPDATED = "session_updated"
    DELETED = "session_deleted"
    SELECTED = "session_selected"
    UNREAD_CHANGED = "session_unread_changed"
    MESSAGE_ADDED = "session_message_added"


class SessionManager:
    """
    Manager for chat sessions.
    
    Responsibilities:
        - Manage session list
        - Track unread counts
        - Handle current session
        - Sort sessions
        - Emit events to UI via EventBus
    """

    def __init__(self):
        self._event_bus = get_event_bus()
        self._msg_manager = get_message_manager()

        self._sessions: dict[str, Session] = {}
        self._current_session_id: Optional[str] = None
        self._lock = asyncio.Lock()

        self._tasks: set[asyncio.Task] = set()
        self._running = False
        self._initialized = False

    @property
    def sessions(self) -> list[Session]:
        """Get all sessions sorted by last message time."""
        return self._get_sorted_sessions()

    @property
    def current_session_id(self) -> Optional[str]:
        """Get current session ID."""
        return self._current_session_id

    @property
    def current_session(self) -> Optional[Session]:
        """Get current session."""
        if self._current_session_id:
            return self._sessions.get(self._current_session_id)
        return None

    def _get_sorted_sessions(self) -> list[Session]:
        """Get sessions sorted by last message time (descending)."""
        session_list = list(self._sessions.values())

        def sort_key(s: Session) -> datetime:
            return s.last_message_time or s.updated_at or datetime.min

        return sorted(session_list, key=sort_key, reverse=True)

    async def initialize(self) -> None:
        """Initialize session manager."""
        if self._initialized:
            logger.debug("Session manager already initialized")
            return

        await self._event_bus.subscribe(
            MessageEvent.RECEIVED,
            self._on_message_received,
        )

        self._running = True
        self._initialized = True

        logger.info("Session manager initialized")

    async def _on_message_received(self, data: dict) -> None:
        """Handle incoming message."""
        message: ChatMessage = data["message"]

        await self.add_message_to_session(
            session_id=message.session_id,
            message=message,
        )

        if self._current_session_id != message.session_id:
            await self.increment_unread(message.session_id)

    async def load_sessions(self, sessions: list[Session]) -> None:
        """Load sessions from storage."""
        async with self._lock:
            for session in sessions:
                self._sessions[session.session_id] = session

        await self._event_bus.emit(SessionEvent.UPDATED, {
            "sessions": self.sessions,
        })

    async def add_session(self, session: Session) -> None:
        """Add a new session."""
        async with self._lock:
            self._sessions[session.session_id] = session

        await self._event_bus.emit(SessionEvent.CREATED, {
            "session": session,
        })

        logger.info(f"Session added: {session.session_id}")

    async def remove_session(self, session_id: str) -> None:
        """Remove a session."""
        async with self._lock:
            session = self._sessions.pop(session_id, None)

        if session:
            if self._current_session_id == session_id:
                self._current_session_id = None

            await self._event_bus.emit(SessionEvent.DELETED, {
                "session_id": session_id,
            })

            logger.info(f"Session removed: {session_id}")

    async def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    async def select_session(self, session_id: str) -> None:
        """Select a session as current."""
        old_id = self._current_session_id
        self._current_session_id = session_id

        if old_id != session_id:
            await self._event_bus.emit(SessionEvent.SELECTED, {
                "session_id": session_id,
                "previous_session_id": old_id,
            })

            await self.clear_unread(session_id)

            logger.info(f"Session selected: {session_id}")

    async def clear_current_session(self) -> None:
        """Clear current session selection."""
        old_id = self._current_session_id
        self._current_session_id = None

        await self._event_bus.emit(SessionEvent.SELECTED, {
            "session_id": None,
            "previous_session_id": old_id,
        })

    async def add_message_to_session(
            self,
            session_id: str,
            message: ChatMessage,
    ) -> None:
        """Add a message to session's last message."""
        async with self._lock:
            session = self._sessions.get(session_id)

            if session:
                session.update_last_message(
                    content=message.content,
                    timestamp=message.timestamp,
                )

        await self._event_bus.emit(SessionEvent.MESSAGE_ADDED, {
            "session_id": session_id,
            "message": message,
        })

    async def increment_unread(self, session_id: str) -> None:
        """Increment unread count for a session."""
        async with self._lock:
            session = self._sessions.get(session_id)

            if session:
                session.increment_unread()

                await self._event_bus.emit(SessionEvent.UNREAD_CHANGED, {
                    "session_id": session_id,
                    "unread_count": session.unread_count,
                })

    async def clear_unread(self, session_id: str) -> None:
        """Clear unread count for a session."""
        async with self._lock:
            session = self._sessions.get(session_id)

            if session:
                old_count = session.unread_count
                session.clear_unread()

                if old_count > 0:
                    await self._event_bus.emit(SessionEvent.UNREAD_CHANGED, {
                        "session_id": session_id,
                        "unread_count": 0,
                    })

    async def update_session(
            self,
            session_id: str,
            **kwargs,
    ) -> None:
        """Update session fields."""
        async with self._lock:
            session = self._sessions.get(session_id)

            if session:
                for key, value in kwargs.items():
                    if hasattr(session, key):
                        setattr(session, key, value)

                await self._event_bus.emit(SessionEvent.UPDATED, {
                    "session": session,
                })

    def get_total_unread_count(self) -> int:
        """Get total unread count across all sessions."""
        return sum(s.unread_count for s in self._sessions.values())

    def get_unread_count(self, session_id: str) -> int:
        """Get unread count for a specific session."""
        session = self._sessions.get(session_id)
        return session.unread_count if session else 0

    async def create_ai_session(
            self,
            session_id: str,
            name: str = "AI Assistant",
    ) -> Session:
        """Create a new AI session."""
        session = Session(
            session_id=session_id,
            name=name,
            session_type="ai",
            is_ai_session=True,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            last_message_time=datetime.now(),
        )

        await self.add_session(session)
        await self.select_session(session_id)

        return session

    async def close(self) -> None:
        """Close session manager."""
        logger.info("Closing session manager")

        self._running = False

        for task in self._tasks:
            if not task.done():
                task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._sessions.clear()

        logger.info("Session manager closed")


_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get the global session manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
