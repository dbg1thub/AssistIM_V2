"""
Session Manager Module

Manager for chat sessions, unread counts, and current session.
"""
import asyncio
import json
from datetime import datetime
from typing import Any, Callable, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.events.event_bus import get_event_bus
from client.managers.message_manager import MessageEvent, get_message_manager
from client.models.message import ChatMessage, Session, format_message_preview
from client.network.http_client import get_http_client
from client.storage.database import get_database

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
        self._session_fetch_tasks: dict[str, asyncio.Task[Optional[Session]]] = {}

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
        await self._event_bus.subscribe(
            MessageEvent.SYNC_COMPLETED,
            self._on_history_synced,
        )

        self._running = True
        self._initialized = True

        # Load sessions from database
        await self._load_from_database()

        logger.info("Session manager initialized")

    async def _load_from_database(self) -> None:
        """Load sessions from local database."""
        from client.storage.database import get_database

        try:
            db = get_database()
            if db.is_connected:
                sessions = await db.get_all_sessions()
                if sessions:
                    await self.load_sessions(sessions)
                    logger.info(f"Loaded {len(sessions)} sessions from database")
        except Exception as e:
            logger.warning(f"Failed to load sessions from database: {e}")

    async def _ensure_session_exists(self, message: ChatMessage) -> Optional[Session]:
        """Ensure a session exists locally before applying message updates."""
        session_id = message.session_id
        if not session_id:
            return None

        existing = self._sessions.get(session_id)
        if existing:
            return existing

        async with self._lock:
            existing = self._sessions.get(session_id)
            if existing:
                return existing

            fetch_task = self._session_fetch_tasks.get(session_id)
            if fetch_task is None:
                fetch_task = asyncio.create_task(self._fetch_or_build_session(message))
                self._session_fetch_tasks[session_id] = fetch_task

        try:
            session = await fetch_task
        finally:
            async with self._lock:
                if self._session_fetch_tasks.get(session_id) is fetch_task:
                    self._session_fetch_tasks.pop(session_id, None)

        if not session:
            return None

        async with self._lock:
            existing = self._sessions.get(session_id)

        if existing:
            return existing

        await self.add_session(session)
        return session

    async def _fetch_or_build_session(self, message: ChatMessage) -> Optional[Session]:
        """Fetch session details from backend or build a fallback local session."""
        session = await self._fetch_remote_session(message.session_id, message)
        if session is None:
            session = await self._build_fallback_session(message)

        if session:
            session.update_last_message(
                content=format_message_preview(message.content, message.message_type),
                timestamp=message.timestamp,
            )
            session.extra["last_message_type"] = message.message_type.value

        return session

    async def _fetch_remote_session(self, session_id: str, message: ChatMessage) -> Optional[Session]:
        """Fetch and normalize a session from the backend."""
        try:
            payload = await get_http_client().get(f"/sessions/{session_id}")
        except Exception as exc:
            logger.warning("Fetch session %s failed: %s", session_id, exc)
            return None

        data = dict(payload or {})
        if not data:
            return None

        data.setdefault("session_id", data.get("id", session_id))
        session_type = str(data.get("session_type") or data.get("type") or "direct")
        if session_type == "private":
            session_type = "direct"
        data["session_type"] = session_type

        current_user_id = await self._get_current_user_id()
        counterpart_name = self._resolve_counterpart_name(
            data.get("members") or [],
            current_user_id,
        ) or self._resolve_counterpart_id(
            data.get("participant_ids") or [],
            current_user_id,
        )
        if counterpart_name:
            data["name"] = counterpart_name
        elif not data.get("name") or data.get("name") == "Private Chat":
            data["name"] = message.sender_id or "New Chat"

        try:
            session = Session.from_dict(data)
        except Exception as exc:
            logger.warning("Normalize session %s failed: %s", session_id, exc)
            return None

        session.extra.update({
            "members": data.get("members") or [],
            "last_message_type": message.message_type.value,
        })
        return session

    async def _build_fallback_session(self, message: ChatMessage) -> Session:
        """Build a minimal local session when the backend detail fetch fails."""
        current_user_id = await self._get_current_user_id()
        participant_ids = [value for value in (current_user_id, message.sender_id) if value]
        session_type = str(message.extra.get("session_type", "direct") or "direct")
        if session_type == "private":
            session_type = "direct"

        session = Session(
            session_id=message.session_id,
            name=(
                str(message.extra.get("sender_nickname", "") or "")
                or str(message.extra.get("sender_name", "") or "")
                or message.sender_id
                or "New Chat"
            ),
            session_type=session_type,
            participant_ids=list(dict.fromkeys(participant_ids)),
            last_message=format_message_preview(message.content, message.message_type),
            last_message_time=message.timestamp,
            avatar=str(message.extra.get("sender_avatar", "") or "") or None,
            created_at=message.timestamp,
            updated_at=message.timestamp,
        )
        session.extra["last_message_type"] = message.message_type.value
        return session

    async def _get_current_user_id(self) -> str:
        """Load current user id from persisted auth state."""
        current_user = await self._get_current_user_context()
        return str(current_user.get("id", "") or "")

    async def _get_current_user_context(self) -> dict[str, Any]:
        """Load current user profile from persisted auth state."""
        try:
            db = get_database()
            if not db.is_connected:
                return {}
            stored_user = await db.get_app_state("auth.user_profile")
            if stored_user:
                return json.loads(stored_user)
            return {"id": str(await db.get_app_state("auth.user_id") or "")}
        except Exception:
            return {}

    def _normalize_session_display(self, session: Session, current_user: dict[str, Any]) -> None:
        """Normalize direct-session display names to the counterpart."""
        if session.is_ai_session or session.session_type == "group":
            return

        current_user_id = str(current_user.get("id", "") or "")
        current_username = str(current_user.get("username", "") or "")
        current_nickname = str(current_user.get("nickname", "") or "")

        counterpart_name = self._resolve_counterpart_name(
            session.extra.get("members") or [],
            current_user_id,
        )
        if counterpart_name:
            session.extra["server_name"] = session.name
            session.name = counterpart_name
            return

        self_names = {value for value in {current_user_id, current_username, current_nickname, "Private Chat"} if value}
        if not session.name or session.name in self_names:
            counterpart_id = self._resolve_counterpart_id(session.participant_ids, current_user_id)
            if counterpart_id:
                session.extra["server_name"] = session.name
                session.name = counterpart_id

    @staticmethod
    def _resolve_counterpart_name(members: list[dict[str, Any]], current_user_id: str) -> str:
        """Resolve the other participant's display name for direct chats."""
        for member in members:
            member_id = str(member.get("id", "") or "")
            if current_user_id and member_id == current_user_id:
                continue
            return (
                str(member.get("nickname", "") or "")
                or str(member.get("username", "") or "")
                or member_id
            )
        return ""

    @staticmethod
    def _resolve_counterpart_id(participant_ids: list[str], current_user_id: str) -> str:
        """Resolve counterpart user id when profile data is unavailable."""
        for participant_id in participant_ids:
            participant_id = str(participant_id or "")
            if not participant_id:
                continue
            if current_user_id and participant_id == current_user_id:
                continue
            return participant_id
        return ""

    async def _on_message_received(self, data: dict) -> None:
        """Handle incoming message."""
        message: ChatMessage = data["message"]
        await self._ensure_session_exists(message)

        await self.add_message_to_session(
            session_id=message.session_id,
            message=message,
        )

        if self._current_session_id != message.session_id:
            await self.increment_unread(message.session_id)

    async def _on_history_synced(self, data: dict) -> None:
        """Apply a synced message batch without re-emitting per-message updates."""
        messages: list[ChatMessage] = data.get("messages") or []
        if not messages:
            return

        for message in messages:
            await self._ensure_session_exists(message)

        db = get_database()
        changed_sessions: dict[str, Session] = {}
        unread_changes: dict[str, int] = {}

        async with self._lock:
            for message in messages:
                session = self._sessions.get(message.session_id)
                if not session:
                    continue

                session.update_last_message(
                    content=format_message_preview(message.content, message.message_type),
                    timestamp=message.timestamp,
                )
                session.extra["last_message_type"] = message.message_type.value

                if self._current_session_id != message.session_id:
                    session.increment_unread()
                    unread_changes[session.session_id] = session.unread_count

                changed_sessions[session.session_id] = session

        if changed_sessions and db.is_connected:
            await db.save_sessions_batch(list(changed_sessions.values()))

        if unread_changes:
            for session_id, unread_count in unread_changes.items():
                await self._event_bus.emit(SessionEvent.UNREAD_CHANGED, {
                    "session_id": session_id,
                    "unread_count": unread_count,
                })

        if changed_sessions:
            await self._event_bus.emit(SessionEvent.UPDATED, {
                "sessions": self.sessions,
            })

    async def load_sessions(self, sessions: list[Session]) -> None:
        """Load sessions from storage."""
        current_user = await self._get_current_user_context()
        async with self._lock:
            for session in sessions:
                self._normalize_session_display(session, current_user)
                self._sessions[session.session_id] = session

        await self._event_bus.emit(SessionEvent.UPDATED, {
            "sessions": self.sessions,
        })

    async def add_session(self, session: Session) -> None:
        """Add a new session."""
        async with self._lock:
            self._sessions[session.session_id] = session

        db = get_database()
        if db.is_connected:
            await db.save_session(session)

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
                    content=format_message_preview(message.content, message.message_type),
                    timestamp=message.timestamp,
                )
                session.extra["last_message_type"] = message.message_type.value

                db = get_database()
                if db.is_connected:
                    await db.save_session(session)

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

                db = get_database()
                if db.is_connected:
                    await db.update_session_unread(session_id, session.unread_count)

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

                db = get_database()
                if db.is_connected:
                    await db.update_session_unread(session_id, session.unread_count)

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

                db = get_database()
                if db.is_connected:
                    await db.save_session(session)

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

        for task in self._session_fetch_tasks.values():
            if not task.done():
                task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        if self._session_fetch_tasks:
            await asyncio.gather(*self._session_fetch_tasks.values(), return_exceptions=True)
            self._session_fetch_tasks.clear()

        self._sessions.clear()

        logger.info("Session manager closed")


_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get the global session manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
