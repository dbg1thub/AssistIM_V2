"""
Session Manager Module

Manager for chat sessions, unread counts, and current session.
"""
import asyncio
import json
import time
from datetime import datetime
from typing import Any, Callable, Optional

from client.core import logging
from client.core.avatar_utils import avatar_seed
from client.core.i18n import tr
from client.core.logging import setup_logging
from client.events.event_bus import get_event_bus
from client.managers.message_manager import MessageEvent, get_message_manager
from client.models.message import ChatMessage, MessageStatus, Session, format_message_preview, resolve_recall_notice
from client.services.session_service import get_session_service
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
    HIDDEN_SESSIONS_STATE_KEY = "chat.hidden_sessions"

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
        self._session_service = get_session_service()

        self._sessions: dict[str, Session] = {}
        self._current_session_id: Optional[str] = None
        self._lock = asyncio.Lock()
        self._session_fetch_tasks: dict[str, asyncio.Task[Optional[Session]]] = {}
        self._hidden_sessions: dict[str, float] = {}

        self._event_subscriptions: list[tuple[str, Callable]] = []
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

        await self._subscribe(MessageEvent.RECEIVED, self._on_message_received)
        await self._subscribe(MessageEvent.SYNC_COMPLETED, self._on_history_synced)
        await self._subscribe(MessageEvent.EDITED, self._on_message_mutated)
        await self._subscribe(MessageEvent.RECALLED, self._on_message_mutated)
        await self._subscribe(MessageEvent.DELETED, self._on_message_mutated)

        self._running = True
        self._initialized = True

        await self._load_hidden_sessions()

        # Load sessions from database
        await self._load_from_database()

        logger.info("Session manager initialized")

    async def _subscribe(self, event_type: str, handler: Callable) -> None:
        """Subscribe to an event and retain it for explicit teardown."""
        self._event_subscriptions.append((event_type, handler))
        await self._event_bus.subscribe(event_type, handler)

    async def _unsubscribe_all(self) -> None:
        """Remove all event-bus subscriptions owned by this manager."""
        while self._event_subscriptions:
            event_type, handler = self._event_subscriptions.pop()
            await self._event_bus.unsubscribe(event_type, handler)

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

    async def _load_hidden_sessions(self) -> None:
        """Load locally hidden-session tombstones from persisted app state."""
        try:
            db = get_database()
            if not db.is_connected:
                self._hidden_sessions = {}
                return

            raw_value = await db.get_app_state(self.HIDDEN_SESSIONS_STATE_KEY)
            parsed = json.loads(raw_value) if raw_value else {}
            hidden_sessions: dict[str, float] = {}
            if isinstance(parsed, dict):
                for session_id, hidden_at in parsed.items():
                    try:
                        hidden_sessions[str(session_id)] = float(hidden_at)
                    except (TypeError, ValueError):
                        continue
            self._hidden_sessions = hidden_sessions
        except Exception as exc:
            logger.warning("Failed to load hidden sessions: %s", exc)
            self._hidden_sessions = {}

    async def _save_hidden_sessions(self) -> None:
        """Persist locally hidden-session tombstones."""
        db = get_database()
        if not db.is_connected:
            return

        if self._hidden_sessions:
            await db.set_app_state(
                self.HIDDEN_SESSIONS_STATE_KEY,
                json.dumps(self._hidden_sessions),
            )
            return

        await db.delete_app_state(self.HIDDEN_SESSIONS_STATE_KEY)

    @staticmethod
    def _session_timestamp_value(value: Any) -> float:
        """Normalize timestamp-like values into epoch seconds."""
        if value is None:
            return 0.0
        if isinstance(value, datetime):
            return value.timestamp()
        if hasattr(value, "timestamp"):
            try:
                return float(value.timestamp())
            except (TypeError, ValueError):
                return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _session_activity_timestamp(self, session: Session) -> float:
        """Return the best available activity timestamp for one session."""
        return max(
            self._session_timestamp_value(session.last_message_time),
            self._session_timestamp_value(session.updated_at),
            self._session_timestamp_value(session.created_at),
        )

    async def _hide_session(self, session_id: str, hidden_at: Optional[float] = None) -> None:
        """Persist a local tombstone so remote refresh does not resurrect the session immediately."""
        self._hidden_sessions[session_id] = max(float(hidden_at or 0.0), time.time())
        await self._save_hidden_sessions()

    async def _unhide_session(self, session_id: str) -> None:
        """Remove a local tombstone once the session should become visible again."""
        if session_id not in self._hidden_sessions:
            return
        self._hidden_sessions.pop(session_id, None)
        await self._save_hidden_sessions()

    def _should_hide_session(self, session: Session) -> bool:
        """Return whether a remote session should stay hidden locally."""
        hidden_at = self._hidden_sessions.get(session.session_id)
        if hidden_at is None:
            return False
        return self._session_activity_timestamp(session) <= hidden_at

    def _dedupe_direct_sessions(self, sessions: list[Session]) -> list[Session]:
        """Keep only the newest direct session for the same participant set."""
        visible_sessions: list[Session] = []
        seen_direct_keys: set[tuple[str, ...]] = set()

        for session in sessions:
            if session.is_ai_session or session.session_type == "group":
                visible_sessions.append(session)
                continue

            member_key = tuple(sorted({str(item or "") for item in session.participant_ids if str(item or "")}))
            if len(member_key) < 2:
                continue
            if member_key in seen_direct_keys:
                continue

            seen_direct_keys.add(member_key)
            visible_sessions.append(session)

        return visible_sessions

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
            payload = await self._session_service.fetch_session(session_id)
        except Exception as exc:
            logger.warning("Fetch session %s failed: %s", session_id, exc)
            return None
        session = await self._build_session_from_payload(
            payload,
            fallback_name=message.sender_id or "New Chat",
        )
        if session is not None:
            session.extra["last_message_type"] = message.message_type.value
        return session

    async def _build_session_from_payload(
        self,
        payload: Optional[dict[str, Any]],
        *,
        fallback_name: str,
        avatar: str = "",
    ) -> Optional[Session]:
        """Normalize a backend payload into a local Session model."""
        data = dict(payload or {})
        if not data:
            return None

        data.setdefault("session_id", data.get("id", ""))
        data.setdefault("name", fallback_name)
        session_type = str(data.get("session_type") or data.get("type") or "direct")
        if session_type == "private":
            session_type = "direct"
        data["session_type"] = session_type

        current_user = await self._get_current_user_context()
        current_user_id = str(current_user.get("id", "") or "")
        if str(data.get("last_message_status") or "") == MessageStatus.RECALLED.value:
            actor_id = str(data.get("last_message_sender_id", "") or "")
            data["last_message"] = (
                tr("message.recalled.self", "You recalled a message")
                if actor_id and actor_id == current_user_id
                else tr("message.recalled.other", "The other side recalled a message")
            )

        if session_type != "group" and not data.get("is_ai_session"):
            counterpart_name = self._resolve_counterpart_name(
                data.get("members") or [],
                current_user_id,
            ) or self._resolve_counterpart_id(
                data.get("participant_ids") or [],
                current_user_id,
            )
            if counterpart_name:
                data["name"] = counterpart_name

        if avatar and not data.get("avatar"):
            data["avatar"] = avatar

        try:
            session = Session.from_dict(data)
        except Exception as exc:
            logger.warning("Normalize session payload failed: %s", exc)
            return None

        session.extra["members"] = data.get("members") or []
        if data.get("last_message_status"):
            session.extra["last_message_status"] = data.get("last_message_status")
        if data.get("last_message_sender_id"):
            session.extra["last_message_sender_id"] = data.get("last_message_sender_id")
        self._normalize_session_display(session, current_user)
        return session

    async def _remember_session(self, session: Session) -> Session:
        """Insert a fetched session once and return the canonical cached object."""
        existing = self._sessions.get(session.session_id)
        if existing is not None:
            return existing

        await self.add_session(session)
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
        session.extra["members"] = list(message.extra.get("members") or [])
        session.extra["counterpart_id"] = str(message.sender_id or "")
        session.extra["counterpart_username"] = str(message.extra.get("sender_username", "") or "")
        session.extra["gender"] = str(message.extra.get("sender_gender", "") or "")
        session.extra["avatar_seed"] = avatar_seed(
            message.sender_id,
            message.extra.get("sender_username", ""),
            message.extra.get("sender_nickname", "") or message.extra.get("sender_name", ""),
        )
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
        """Normalize direct-session display fields to the counterpart profile."""
        if session.is_ai_session or session.session_type == "group":
            return

        counterpart = self._resolve_counterpart_profile(
            session.extra.get("members") or [],
            session.participant_ids,
            current_user,
        )
        counterpart_name = str(counterpart.get("display_name", "") or "")
        counterpart_id = str(counterpart.get("id", "") or "")
        counterpart_username = str(counterpart.get("username", "") or "")
        counterpart_avatar = str(counterpart.get("avatar", "") or "")
        counterpart_gender = str(counterpart.get("gender", "") or "")

        if counterpart_name:
            session.extra["server_name"] = session.name
            session.name = counterpart_name

        current_user_id = str(current_user.get("id", "") or "")
        current_username = str(current_user.get("username", "") or "")
        current_nickname = str(current_user.get("nickname", "") or "")
        private_chat_label = tr("session.private_chat", "Private Chat")
        self_names = {value for value in {current_user_id, current_username, current_nickname, private_chat_label} if value}
        if (not session.name or session.name in self_names) and counterpart_id:
            session.extra["server_name"] = session.name
            session.name = counterpart_id

        if counterpart_avatar:
            session.avatar = counterpart_avatar
        if counterpart_gender:
            session.extra["gender"] = counterpart_gender
        if counterpart_id:
            session.extra["counterpart_id"] = counterpart_id
        if counterpart_username:
            session.extra["counterpart_username"] = counterpart_username

        session.extra["avatar_seed"] = avatar_seed(
            counterpart_id or session.session_id,
            counterpart_username or session.name,
            counterpart_name or session.name,
        )

    def _resolve_counterpart_profile(
        self,
        members: list[dict[str, Any]],
        participant_ids: list[str],
        current_user: dict[str, Any],
    ) -> dict[str, str]:
        """Resolve one normalized counterpart profile for a direct chat."""
        current_user_id = str(current_user.get("id", "") or "")
        current_username = str(current_user.get("username", "") or "")

        for member in members:
            member_id = str(member.get("id", "") or "")
            member_username = str(member.get("username", "") or "")
            if current_user_id and member_id == current_user_id:
                continue
            if current_username and member_username == current_username:
                continue
            return {
                "id": member_id,
                "username": member_username,
                "nickname": str(member.get("nickname", "") or ""),
                "avatar": str(member.get("avatar", "") or ""),
                "gender": str(member.get("gender", "") or ""),
                "display_name": (
                    str(member.get("nickname", "") or "")
                    or member_username
                    or member_id
                ),
            }

        counterpart_id = self._resolve_counterpart_id(participant_ids, current_user_id)
        return {
            "id": counterpart_id,
            "username": "",
            "nickname": "",
            "avatar": "",
            "gender": "",
            "display_name": counterpart_id,
        }

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
        await self._unhide_session(message.session_id)
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
            await self._unhide_session(message.session_id)
            await self._ensure_session_exists(message)

        db = get_database()
        changed_sessions: dict[str, Session] = {}

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

                changed_sessions[session.session_id] = session

        if changed_sessions and db.is_connected:
            await db.save_sessions_batch(list(changed_sessions.values()))

        if changed_sessions:
            await self._event_bus.emit(SessionEvent.UPDATED, {
                "sessions": self.sessions,
            })

    async def _on_message_mutated(self, data: dict) -> None:
        """Refresh session preview after edit/recall/delete events."""
        session_id = str(data.get("session_id", "") or "")
        if not session_id:
            return
        await self.refresh_session_preview(session_id)

    def _is_session_visible(self, session: Session, current_user: dict[str, Any]) -> bool:
        """Return whether a session has a valid visible counterpart for the current user."""
        if session.is_ai_session or session.session_type == "group":
            return True

        current_user_id = str(current_user.get("id", "") or "")
        counterpart_name = self._resolve_counterpart_name(session.extra.get("members") or [], current_user_id)
        counterpart_id = self._resolve_counterpart_id(session.participant_ids, current_user_id)
        return bool(counterpart_name or counterpart_id)

    @staticmethod
    def _carry_local_session_state(target: Session, source: Optional[Session]) -> None:
        """Preserve local-only session state that the backend does not currently track."""
        if source is None:
            return

        if getattr(source, "is_pinned", False):
            setattr(target, "is_pinned", True)
            target.extra["is_pinned"] = True
        if "pinned_at" in source.extra:
            target.extra["pinned_at"] = source.extra["pinned_at"]

    async def load_sessions(self, sessions: list[Session]) -> None:
        """Load sessions from storage."""
        current_user = await self._get_current_user_context()
        async with self._lock:
            self._sessions.clear()
            for session in self._dedupe_direct_sessions(sessions):
                self._normalize_session_display(session, current_user)
                if not self._is_session_visible(session, current_user):
                    continue
                if self._should_hide_session(session):
                    continue
                self._sessions[session.session_id] = session

        await self._event_bus.emit(SessionEvent.UPDATED, {
            "sessions": self.sessions,
        })

    async def _replace_sessions(self, sessions: list[Session]) -> None:
        """Replace the in-memory session snapshot with a normalized remote snapshot."""
        current_user = await self._get_current_user_context()
        hidden_changed = False
        async with self._lock:
            existing_sessions = dict(self._sessions)
            self._sessions.clear()
            for session in self._dedupe_direct_sessions(sessions):
                self._normalize_session_display(session, current_user)
                if not self._is_session_visible(session, current_user):
                    continue
                if self._should_hide_session(session):
                    continue
                if session.session_id in self._hidden_sessions:
                    self._hidden_sessions.pop(session.session_id, None)
                    hidden_changed = True
                self._carry_local_session_state(session, existing_sessions.get(session.session_id))
                self._sessions[session.session_id] = session

            if self._current_session_id and self._current_session_id not in self._sessions:
                self._current_session_id = None

        if hidden_changed:
            await self._save_hidden_sessions()

        db = get_database()
        if db.is_connected:
            await db.replace_sessions(list(self._sessions.values()))

        await self._event_bus.emit(SessionEvent.UPDATED, {
            "sessions": self.sessions,
        })

    async def refresh_remote_sessions(self) -> list[Session]:
        """Fetch the current user's session snapshot from the backend and replace local cache."""
        try:
            payload = await self._session_service.fetch_sessions()
        except Exception as exc:
            logger.warning("Refresh remote sessions failed: %s", exc)
            return self.sessions

        unread_count_map = await self._fetch_remote_unread_counts()

        remote_sessions: list[Session] = []
        for item in payload or []:
            data = dict(item or {})
            session = await self._build_session_from_payload(
                data,
                fallback_name=str(data.get("name", "") or tr("session.private_chat", "Private Chat")),
                avatar=str(data.get("avatar", "") or ""),
            )
            if session is not None:
                session.unread_count = int(unread_count_map.get(session.session_id, 0))
                remote_sessions.append(session)

        await self._replace_sessions(remote_sessions)
        logger.info("Refreshed %d remote sessions", len(remote_sessions))
        return self.sessions

    async def _fetch_remote_unread_counts(self) -> dict[str, int]:
        """Fetch authoritative unread counts from the backend."""
        try:
            payload = await self._session_service.fetch_unread_counts()
        except Exception as exc:
            logger.warning("Refresh remote unread counts failed: %s", exc)
            return {}

        unread_by_session: dict[str, int] = {}
        for item in payload or []:
            session_id = str(item.get("session_id", "") or "")
            if not session_id:
                continue
            try:
                unread_by_session[session_id] = max(0, int(item.get("unread", 0) or 0))
            except (TypeError, ValueError):
                unread_by_session[session_id] = 0
        return unread_by_session

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
        """Hide a session locally without deleting the remote conversation."""
        async with self._lock:
            session = self._sessions.pop(session_id, None)

        hidden_at = self._session_activity_timestamp(session) if session is not None else time.time()
        await self._hide_session(session_id, hidden_at=hidden_at)

        if session:
            db = get_database()
            if db.is_connected:
                await db.delete_session(session_id)

            if self._current_session_id == session_id:
                self._current_session_id = None

            await self._event_bus.emit(SessionEvent.DELETED, {
                "session_id": session_id,
            })

            logger.info(f"Session removed: {session_id}")

    async def set_pinned(self, session_id: str, pinned: bool) -> None:
        """Persist pinned state for a session and refresh the list."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return

            db = get_database()
            affected_sessions: list[Session] = []
            desired_pinned_at = time.time() if pinned else None
            current_pinned_at = session.extra.get("pinned_at")
            if getattr(session, "is_pinned", False) != pinned or current_pinned_at != desired_pinned_at:
                setattr(session, "is_pinned", pinned)
                session.extra["is_pinned"] = pinned
                session.extra["pinned_at"] = desired_pinned_at
                affected_sessions.append(session)

            if db.is_connected:
                for changed in affected_sessions:
                    await db.save_session(changed)

        for changed in affected_sessions:
            await self._event_bus.emit(SessionEvent.UPDATED, {
                "session": changed,
            })

    async def mark_session_unread(self, session_id: str, unread: bool) -> None:
        """Manually mark a session read or unread."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return

            new_count = max(1, session.unread_count) if unread else 0
            if session.unread_count == new_count:
                return

            session.unread_count = new_count

            db = get_database()
            if db.is_connected:
                await db.update_session_unread(session_id, new_count)

        await self._event_bus.emit(SessionEvent.UNREAD_CHANGED, {
            "session_id": session_id,
            "unread_count": new_count,
        })

    async def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    def find_direct_session(self, user_id: str) -> Optional[Session]:
        """Find an existing direct session by participant id."""
        for session in self._sessions.values():
            if session.is_ai_session or session.session_type == "group":
                continue
            if user_id in session.participant_ids:
                return session
        return None

    async def ensure_remote_session(
        self,
        session_id: str,
        *,
        fallback_name: str = "Session",
        avatar: str = "",
    ) -> Optional[Session]:
        """Fetch a session from the backend and cache it locally when needed."""
        existing = self._sessions.get(session_id)
        if existing is not None:
            return existing

        try:
            payload = await self._session_service.fetch_session(session_id)
        except Exception as exc:
            logger.warning("Fetch session %s failed: %s", session_id, exc)
            return None

        session = await self._build_session_from_payload(
            payload,
            fallback_name=fallback_name,
            avatar=avatar,
        )
        if session is None:
            return None
        await self._unhide_session(session.session_id)
        return await self._remember_session(session)

    async def ensure_direct_session(
        self,
        user_id: str,
        *,
        display_name: str = "",
        avatar: str = "",
    ) -> Optional[Session]:
        """Return an existing direct session or create one via the backend."""
        existing = self.find_direct_session(user_id)
        if existing is not None:
            return existing

        try:
            payload = await self._session_service.create_direct_session(
                user_id,
                display_name=display_name or tr("session.private_chat", "Private Chat"),
            )
        except Exception as exc:
            logger.warning("Create direct session for %s failed: %s", user_id, exc)
            return None

        session = await self._build_session_from_payload(
            payload,
            fallback_name=display_name or tr("session.private_chat", "Private Chat"),
            avatar=avatar,
        )
        if session is None:
            return None
        await self._unhide_session(session.session_id)
        return await self._remember_session(session)

    async def refresh_session_preview(self, session_id: str) -> None:
        """Refresh a session preview from the latest persisted local message."""
        session = self._sessions.get(session_id)
        if session is None:
            return

        db = get_database()
        if not db.is_connected:
            return

        last_message = await db.get_last_message(session_id)
        if last_message and last_message.status == MessageStatus.RECALLED:
            preview = resolve_recall_notice(last_message)
        else:
            preview = format_message_preview(last_message.content, last_message.message_type) if last_message else ""
        preview_time = last_message.timestamp if last_message else session.updated_at
        extra = dict(session.extra)
        if last_message:
            extra["last_message_type"] = last_message.message_type.value
        else:
            extra.pop("last_message_type", None)

        await self.update_session(
            session_id,
            last_message=preview,
            last_message_time=preview_time,
            extra=extra,
        )

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
                    content=resolve_recall_notice(message) if message.status == MessageStatus.RECALLED else format_message_preview(message.content, message.message_type),
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
        if session:
            await self._event_bus.emit(SessionEvent.UPDATED, {
                "session": session,
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
                await self._event_bus.emit(SessionEvent.UPDATED, {
                    "session": session,
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
                    await self._event_bus.emit(SessionEvent.UPDATED, {
                        "session": session,
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

        for task in self._session_fetch_tasks.values():
            if not task.done():
                task.cancel()

        if self._session_fetch_tasks:
            await asyncio.gather(*self._session_fetch_tasks.values(), return_exceptions=True)
            self._session_fetch_tasks.clear()

        await self._unsubscribe_all()
        self._sessions.clear()
        self._current_session_id = None
        self._initialized = False

        logger.info("Session manager closed")


_session_manager: Optional[SessionManager] = None


def peek_session_manager() -> Optional[SessionManager]:
    """Return the existing session manager singleton if it was created."""
    return _session_manager


def get_session_manager() -> SessionManager:
    """Get the global session manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


