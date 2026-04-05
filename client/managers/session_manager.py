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
from client.core.avatar_utils import profile_avatar_seed
from client.core.i18n import tr
from client.core.logging import setup_logging
from client.events.event_bus import get_event_bus
from client.managers.call_manager import CallEvent, get_call_manager
from client.managers.message_manager import MessageEvent, get_message_manager
from client.models.message import ChatMessage, MessageStatus, Session, format_message_preview, normalize_message_mentions, resolve_recall_notice
from client.services.e2ee_service import get_e2ee_service
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
    ENCRYPTION_MODE_PLAIN = "plain"
    ENCRYPTION_MODE_E2EE_PRIVATE = "e2ee_private"
    ENCRYPTION_MODE_E2EE_GROUP = "e2ee_group"
    ENCRYPTION_MODE_SERVER_VISIBLE_AI = "server_visible_ai"

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
        self._call_manager = None
        self._e2ee_service = None

        self._sessions: dict[str, Session] = {}
        self._current_session_id: Optional[str] = None
        self._current_session_active = False
        self._current_user_id = ""
        self._lock = asyncio.Lock()
        self._session_fetch_tasks: dict[str, asyncio.Task[Optional[Session]]] = {}
        self._identity_refresh_task: Optional[asyncio.Task[None]] = None
        self._hidden_sessions: dict[str, float] = {}

        self._event_subscriptions: list[tuple[str, Callable]] = []
        self._running = False
        self._initialized = False

    @staticmethod
    def _message_mentions_current_user(message: ChatMessage | None, current_user_id: str) -> bool:
        """Return whether one text message explicitly mentions the current user."""
        if message is None or not current_user_id or message.is_self:
            return False
        mentions = normalize_message_mentions(
            dict(message.extra or {}).get("mentions"),
            content=str(message.content or ""),
        )
        for mention in mentions:
            mention_type = str(mention.get("mention_type", "") or "").strip().lower()
            if mention_type == "all":
                return True
            if mention_type == "member" and str(mention.get("member_id", "") or "").strip() == current_user_id:
                return True
        return False

    def _apply_last_message_preview(self, session: Session, message: ChatMessage | None, *, current_user_id: str) -> None:
        """Project one real last message into cached session preview fields."""
        if message is None:
            session.last_message = ""
            session.extra.pop("last_message_id", None)
            session.extra.pop("last_message_type", None)
            session.extra.pop("last_message_sender_id", None)
            session.extra.pop("last_message_mentions_current_user", None)
            return

        preview = resolve_recall_notice(message) if message.status == MessageStatus.RECALLED else format_message_preview(
            message.content,
            message.message_type,
        )
        session.update_last_message(content=preview, timestamp=message.timestamp)
        session.extra["last_message_id"] = str(message.message_id or "")
        session.extra["last_message_type"] = message.message_type.value
        session.extra["last_message_sender_id"] = str(message.sender_id or "")
        mentions_current_user = self._message_mentions_current_user(message, current_user_id)
        if self._current_session_active and self._current_session_id == session.session_id:
            mentions_current_user = False
        session.extra["last_message_mentions_current_user"] = mentions_current_user

    @property
    def sessions(self) -> list[Session]:
        """Get all sessions sorted by last message time."""
        return self._get_sorted_sessions()

    def set_user_id(self, user_id: str) -> None:
        """Set the current authenticated user id for session presentation decisions."""
        normalized_user_id = str(user_id or "").strip()
        if self._current_user_id == normalized_user_id:
            return
        self._current_user_id = normalized_user_id
        self._schedule_identity_refresh()



    def _require_e2ee_service(self):
        """Lazily initialize the E2EE helper so session refreshes can annotate crypto capability."""
        if self._e2ee_service is None:
            self._e2ee_service = get_e2ee_service()
        return self._e2ee_service

    @classmethod
    def _default_encryption_mode(cls, *, session_type: str, is_ai_session: bool) -> str:
        """Return the default encryption mode for one session type."""
        normalized_session_type = str(session_type or "").strip().lower()
        if is_ai_session or normalized_session_type == "ai":
            return cls.ENCRYPTION_MODE_SERVER_VISIBLE_AI
        if normalized_session_type == "direct":
            return cls.ENCRYPTION_MODE_E2EE_PRIVATE
        if normalized_session_type == "group":
            return cls.ENCRYPTION_MODE_E2EE_GROUP
        return cls.ENCRYPTION_MODE_PLAIN

    @classmethod
    def _normalize_encryption_mode(cls, value: object, *, session_type: str, is_ai_session: bool) -> str:
        """Return one validated encryption mode, falling back to the session-type default."""
        normalized = str(value or "").strip().lower()
        allowed = {
            cls.ENCRYPTION_MODE_PLAIN,
            cls.ENCRYPTION_MODE_E2EE_PRIVATE,
            cls.ENCRYPTION_MODE_E2EE_GROUP,
            cls.ENCRYPTION_MODE_SERVER_VISIBLE_AI,
        }
        if normalized in allowed:
            return normalized
        return cls._default_encryption_mode(session_type=session_type, is_ai_session=is_ai_session)

    @staticmethod
    def _require_call_manager_instance():
        return get_call_manager()

    @classmethod
    def _default_call_capabilities(cls, *, session_type: str, is_ai_session: bool) -> dict[str, bool]:
        supports_direct_call = str(session_type or "").strip().lower() == "direct" and not is_ai_session
        return {
            "voice": supports_direct_call,
            "video": supports_direct_call,
        }

    @classmethod
    def _normalize_call_capabilities(cls, value: object, *, session_type: str, is_ai_session: bool) -> dict[str, bool]:
        defaults = cls._default_call_capabilities(session_type=session_type, is_ai_session=is_ai_session)
        if not isinstance(value, dict):
            return defaults
        return {
            "voice": bool(value.get("voice", defaults["voice"])),
            "video": bool(value.get("video", defaults["video"])),
        }

    @staticmethod
    def _idle_call_state() -> dict[str, Any]:
        return {"active": False, "status": "idle"}

    async def _annotate_session_call_state(self, sessions: list[Session]) -> None:
        active_call = self._require_call_manager_instance().active_call
        for session in sessions:
            session.extra["call_capabilities"] = self._normalize_call_capabilities(
                session.extra.get("call_capabilities"),
                session_type=session.session_type,
                is_ai_session=bool(session.is_ai_session),
            )
            if not session.supports_call():
                session.extra["call_state"] = {}
                continue
            if active_call is not None and active_call.session_id == session.session_id:
                session.extra["call_state"] = self._call_state_from_active_call(active_call)
            else:
                session.extra["call_state"] = self._idle_call_state()

    def _call_state_from_active_call(self, call) -> dict[str, Any]:
        current_user_id = self._current_user_id
        peer_user_id = call.peer_user_id(current_user_id) if current_user_id else ""
        state = {
            "active": call.status in {"inviting", "ringing", "accepted"},
            "status": str(call.status or "idle"),
            "call_id": str(call.call_id or ""),
            "media_type": str(call.media_type or ""),
            "direction": str(call.direction or ""),
            "peer_user_id": peer_user_id,
        }
        if str(call.actor_id or "").strip():
            state["actor_id"] = str(call.actor_id or "")
        if str(call.reason or "").strip():
            state["reason"] = str(call.reason or "")
        if call.created_at is not None:
            state["created_at"] = call.created_at.isoformat()
        if call.answered_at is not None:
            state["answered_at"] = call.answered_at.isoformat()
        return state

    async def _apply_call_state_event(self, payload: dict[str, Any]) -> None:
        call = payload.get("call") if isinstance(payload, dict) else None
        if call is None or not getattr(call, "session_id", ""):
            return

        async with self._lock:
            session = self._sessions.get(str(call.session_id or ""))
            if session is None:
                return
            if not session.supports_call():
                session.extra["call_state"] = {}
            else:
                session.extra["call_state"] = self._call_state_from_active_call(call)

        await self._event_bus.emit(SessionEvent.UPDATED, {"sessions": self.sessions})

    @classmethod
    def _build_session_crypto_state(
        cls,
        session: Session,
        *,
        device_summary: dict[str, Any] | None,
        existing_state: dict[str, Any] | None = None,
        group_summary: dict[str, Any] | None = None,
        peer_identity_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build one normalized runtime crypto-state snapshot for a session."""
        mode = session.encryption_mode()
        device_info = dict(device_summary or {})
        previous_state = dict(existing_state or {})
        group_key_summary = dict(group_summary or {})
        identity_summary = dict(peer_identity_summary or {})
        device_id = str(device_info.get("device_id") or previous_state.get("device_id") or "").strip()
        device_registered = bool(device_info.get("has_local_bundle") or device_id)
        uses_e2ee = mode in {cls.ENCRYPTION_MODE_E2EE_PRIVATE, cls.ENCRYPTION_MODE_E2EE_GROUP}
        can_decrypt = uses_e2ee and device_registered
        state: dict[str, Any] = {
            "enabled": uses_e2ee,
            "ready": can_decrypt,
            "can_decrypt": can_decrypt,
            "device_registered": device_registered,
        }
        if "last_message_recovery" in previous_state:
            state["last_message_recovery"] = dict(previous_state["last_message_recovery"] or {})
        if "last_message_recovery_at" in previous_state:
            state["last_message_recovery_at"] = str(previous_state["last_message_recovery_at"] or "")
        if mode == cls.ENCRYPTION_MODE_E2EE_PRIVATE:
            state["scheme"] = "x25519-aesgcm-v1"
            state["attachment_scheme"] = "aesgcm-file+x25519-v1"
            state["identity_status"] = str(
                identity_summary.get("status") or previous_state.get("identity_status") or "unavailable"
            ).strip()
            state["identity_verified"] = state["identity_status"] == "verified"
            state["identity_device_count"] = int(
                identity_summary["device_count"]
                if "device_count" in identity_summary
                else previous_state.get("identity_device_count", 0)
            )
            state["trusted_identity_device_count"] = int(
                identity_summary["trusted_device_count"]
                if "trusted_device_count" in identity_summary
                else previous_state.get("trusted_identity_device_count", 0)
            )
            state["unverified_identity_device_count"] = int(
                identity_summary["unverified_device_count"]
                if "unverified_device_count" in identity_summary
                else previous_state.get("unverified_identity_device_count", 0)
            )
            state["changed_identity_device_count"] = int(
                identity_summary["changed_device_count"]
                if "changed_device_count" in identity_summary
                else previous_state.get("changed_identity_device_count", 0)
            )
            state["unverified_identity_device_ids"] = list(
                identity_summary["unverified_device_ids"]
                if "unverified_device_ids" in identity_summary
                else previous_state.get("unverified_identity_device_ids") or []
            )
            state["changed_identity_device_ids"] = list(
                identity_summary["changed_device_ids"]
                if "changed_device_ids" in identity_summary
                else previous_state.get("changed_identity_device_ids") or []
            )
            state["identity_checked_at"] = str(
                identity_summary["checked_at"]
                if "checked_at" in identity_summary
                else previous_state.get("identity_checked_at") or ""
            )
            state["identity_change_count"] = int(
                identity_summary["change_count"]
                if "change_count" in identity_summary
                else previous_state.get("identity_change_count", 0)
            )
            state["identity_last_changed_at"] = str(
                identity_summary["last_changed_at"]
                if "last_changed_at" in identity_summary
                else previous_state.get("identity_last_changed_at") or ""
            )
            state["identity_last_trusted_at"] = str(
                identity_summary["last_trusted_at"]
                if "last_trusted_at" in identity_summary
                else previous_state.get("identity_last_trusted_at") or ""
            )
            state["identity_verification_available"] = bool(
                identity_summary["verification_available"]
                if "verification_available" in identity_summary
                else previous_state.get("identity_verification_available", False)
            )
            state["identity_primary_verification_device_id"] = str(
                identity_summary["primary_verification_device_id"]
                if "primary_verification_device_id" in identity_summary
                else previous_state.get("identity_primary_verification_device_id") or ""
            )
            state["identity_primary_verification_fingerprint"] = str(
                identity_summary["primary_verification_fingerprint"]
                if "primary_verification_fingerprint" in identity_summary
                else previous_state.get("identity_primary_verification_fingerprint") or ""
            )
            state["identity_primary_verification_fingerprint_short"] = str(
                identity_summary["primary_verification_fingerprint_short"]
                if "primary_verification_fingerprint_short" in identity_summary
                else previous_state.get("identity_primary_verification_fingerprint_short") or ""
            )
            state["identity_primary_verification_code"] = str(
                identity_summary["primary_verification_code"]
                if "primary_verification_code" in identity_summary
                else previous_state.get("identity_primary_verification_code") or ""
            )
            state["identity_primary_verification_code_short"] = str(
                identity_summary["primary_verification_code_short"]
                if "primary_verification_code_short" in identity_summary
                else previous_state.get("identity_primary_verification_code_short") or ""
            )
            state["identity_local_fingerprint_short"] = str(
                identity_summary["local_fingerprint_short"]
                if "local_fingerprint_short" in identity_summary
                else previous_state.get("identity_local_fingerprint_short") or ""
            )
            if state["identity_status"] == "identity_changed":
                state["identity_action_required"] = True
                state["identity_review_action"] = "trust_peer_identity"
                state["identity_review_blocking"] = True
                state["identity_alert_severity"] = "critical"
            elif state["identity_status"] == "unverified":
                state["identity_action_required"] = True
                state["identity_review_action"] = "trust_peer_identity"
                state["identity_review_blocking"] = False
                state["identity_alert_severity"] = "warning"
            elif state["identity_status"] == "verified":
                state["identity_action_required"] = False
                state["identity_review_action"] = ""
                state["identity_review_blocking"] = False
                state["identity_alert_severity"] = "info"
            else:
                state["identity_action_required"] = False
                state["identity_review_action"] = ""
                state["identity_review_blocking"] = False
                state["identity_alert_severity"] = "info"
        elif mode == cls.ENCRYPTION_MODE_E2EE_GROUP:
            state["scheme"] = "group-sender-key-v1"
            state["attachment_scheme"] = "aesgcm-file+group-sender-key-v1"
            state["fanout_scheme"] = "group-sender-key-fanout-v1"
            state["group_member_version"] = int(
                group_key_summary.get("member_version")
                or session.extra.get("group_member_version", 0)
                or previous_state.get("group_member_version", 0)
                or 0
            )
            state["local_sender_key_ready"] = bool(group_key_summary.get("has_local_sender_key"))
            state["local_sender_key_id"] = str(group_key_summary.get("local_sender_key_id") or "")
            state["retired_local_key_count"] = len(list(group_key_summary.get("retired_local_sender_key_ids") or []))
            state["inbound_sender_key_count"] = len(list(group_key_summary.get("inbound_sender_devices") or []))
        if device_id:
            state["device_id"] = device_id
        return state

    @staticmethod
    def _normalize_message_recovery_bucket(payload: dict[str, Any] | None) -> dict[str, int]:
        normalized = dict(payload or {})
        return {
            "text": int(normalized.get("text", 0) or 0),
            "attachments": int(normalized.get("attachments", 0) or 0),
            "direct_text": int(normalized.get("direct_text", 0) or 0),
            "group_text": int(normalized.get("group_text", 0) or 0),
            "direct_attachments": int(normalized.get("direct_attachments", 0) or 0),
            "group_attachments": int(normalized.get("group_attachments", 0) or 0),
            "other": int(normalized.get("other", 0) or 0),
        }

    @classmethod
    def _summarize_message_recovery(cls, payload: dict[str, Any] | None) -> dict[str, Any]:
        normalized = dict(payload or {})
        recovery_stats = dict(normalized.get("recovery_stats") or {})
        return {
            "updated": int(normalized.get("updated", 0) or 0),
            "remote_fetched": int(normalized.get("remote_fetched", 0) or 0),
            "remote_pages_fetched": int(normalized.get("remote_pages_fetched", 0) or 0),
            "message_count": len(list(normalized.get("message_ids") or [])),
            "cached": cls._normalize_message_recovery_bucket(dict(recovery_stats.get("cached") or {})),
            "remote": cls._normalize_message_recovery_bucket(dict(recovery_stats.get("remote") or {})),
        }

    async def _record_session_message_recovery(
        self,
        session_id: str,
        message_recovery: dict[str, Any] | None,
    ) -> None:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return

        summary = self._summarize_message_recovery(message_recovery)
        recorded_at = datetime.now().isoformat()
        async with self._lock:
            session = self._sessions.get(normalized_session_id)
            if session is None:
                return
            state = dict(session.extra.get("session_crypto_state") or {})
            state["last_message_recovery"] = summary
            state["last_message_recovery_at"] = recorded_at
            session.extra["session_crypto_state"] = state

        db = get_database()
        if db.is_connected:
            await db.replace_sessions(list(self._sessions.values()))
        await self._event_bus.emit(SessionEvent.UPDATED, {"sessions": self.sessions})

    async def _annotate_session_crypto_state(self, sessions: list[Session]) -> None:
        """Attach runtime crypto-state snapshots to a batch of sessions."""
        if not sessions:
            return
        try:
            device_summary = await self._require_e2ee_service().get_local_device_summary()
        except Exception as exc:
            logger.debug("Failed to load local E2EE device summary for sessions: %s", exc)
            device_summary = {}
        for session in sessions:
            group_summary: dict[str, Any] | None = None
            peer_identity_summary: dict[str, Any] | None = None
            session.extra["encryption_mode"] = self._normalize_encryption_mode(
                session.extra.get("encryption_mode"),
                session_type=session.session_type,
                is_ai_session=bool(session.is_ai_session),
            )
            group_summary = await self._reconcile_group_sender_key_state(session)
            if session.session_type == "direct" and not bool(session.is_ai_session):
                counterpart_id = str(session.extra.get("counterpart_id") or "").strip()
                if counterpart_id:
                    try:
                        peer_identity_summary = await self._require_e2ee_service().get_peer_identity_summary(counterpart_id)
                    except Exception as exc:
                        logger.debug("Failed to load peer identity summary for %s: %s", counterpart_id, exc)
            session.extra["session_crypto_state"] = self._build_session_crypto_state(
                session,
                device_summary=device_summary,
                existing_state=dict(session.extra.get("session_crypto_state") or {}),
                group_summary=group_summary,
                peer_identity_summary=peer_identity_summary,
            )
        await self._annotate_session_call_state(sessions)

    @staticmethod
    def _resolve_group_session_member_ids(session: Session) -> list[str]:
        member_ids: list[str] = []
        for member in list(session.extra.get("members") or []):
            member_id = str((member or {}).get("id") or "").strip() if isinstance(member, dict) else ""
            if member_id and member_id not in member_ids:
                member_ids.append(member_id)
        for participant_id in list(session.participant_ids or []):
            normalized_participant_id = str(participant_id or "").strip()
            if normalized_participant_id and normalized_participant_id not in member_ids:
                member_ids.append(normalized_participant_id)
        return member_ids

    async def _reconcile_group_sender_key_state(self, session: Session) -> dict[str, Any] | None:
        if session.session_type != "group" or bool(session.is_ai_session):
            return None
        group_member_version = int(session.extra.get("group_member_version", 0) or 0)
        member_ids = self._resolve_group_session_member_ids(session)
        if not group_member_version and not member_ids:
            return None
        try:
            return await self._require_e2ee_service().reconcile_group_session_state(
                session.session_id,
                member_version=group_member_version,
                member_user_ids=member_ids,
            )
        except Exception as exc:
            logger.debug("Failed to reconcile group sender-key state for %s: %s", session.session_id, exc)
            return None

    @staticmethod
    def _apply_message_crypto_state_to_session(session: Session, payload: dict[str, Any]) -> bool:
        state = dict(session.extra.get("session_crypto_state") or {})
        previous_state = dict(state)
        decryption_state = str(payload.get("decryption_state") or "ready").strip()
        recovery_action = str(payload.get("recovery_action") or "").strip()
        local_device_id = str(payload.get("local_device_id") or state.get("device_id") or "").strip()
        target_device_id = str(payload.get("target_device_id") or "").strip()
        can_decrypt = bool(payload.get("can_decrypt", True))

        if decryption_state == "ready":
            state["ready"] = bool(state.get("device_registered"))
            state["can_decrypt"] = bool(state.get("device_registered"))
            state.pop("decryption_state", None)
            state.pop("recovery_action", None)
            state.pop("last_failure_message_id", None)
            state.pop("target_device_id", None)
        else:
            state["ready"] = False
            state["can_decrypt"] = can_decrypt
            state["decryption_state"] = decryption_state
            state["last_failure_message_id"] = str(payload.get("message_id") or "")
            if recovery_action:
                state["recovery_action"] = recovery_action
            else:
                state.pop("recovery_action", None)
            if target_device_id:
                state["target_device_id"] = target_device_id
            else:
                state.pop("target_device_id", None)

        if local_device_id:
            state["device_id"] = local_device_id
        session.extra["session_crypto_state"] = state
        return state != previous_state

    def _schedule_identity_refresh(self) -> None:
        """Recompute cached preview state once the authenticated user identity changes."""
        if not self._initialized:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        if self._identity_refresh_task is not None and not self._identity_refresh_task.done():
            self._identity_refresh_task.cancel()

        task = loop.create_task(self._refresh_cached_preview_state_for_identity())
        self._identity_refresh_task = task
        task.add_done_callback(self._finalize_identity_refresh_task)

    def _finalize_identity_refresh_task(self, task: asyncio.Task[None]) -> None:
        """Drop completed identity-refresh work and report unexpected failures."""
        if self._identity_refresh_task is task:
            self._identity_refresh_task = None
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Failed to refresh cached preview state after identity change")

    async def _refresh_cached_preview_state_for_identity(self) -> None:
        """Recompute preview sender/mention state for all cached sessions after login changes."""
        db = get_database()
        if not db.is_connected or not self._sessions:
            return

        current_user_id = self._current_user_id
        async with self._lock:
            session_ids = list(self._sessions.keys())

        changed_sessions: list[Session] = []
        for session_id in session_ids:
            last_message = await db.get_last_message(session_id)
            async with self._lock:
                session = self._sessions.get(session_id)
                if session is None:
                    continue

                previous_preview = str(session.last_message or "")
                previous_sender_id = str(session.extra.get("last_message_sender_id", "") or "")
                previous_type = str(session.extra.get("last_message_type", "") or "")
                previous_mentions = bool(session.extra.get("last_message_mentions_current_user", False))

                self._apply_last_message_preview(session, last_message, current_user_id=current_user_id)

                if (
                    previous_preview != str(session.last_message or "")
                    or previous_sender_id != str(session.extra.get("last_message_sender_id", "") or "")
                    or previous_type != str(session.extra.get("last_message_type", "") or "")
                    or previous_mentions != bool(session.extra.get("last_message_mentions_current_user", False))
                ):
                    changed_sessions.append(session)

        for session in changed_sessions:
            await db.save_session(session)

        if changed_sessions:
            await self._event_bus.emit(SessionEvent.UPDATED, {
                "sessions": self.sessions,
            })

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
            return s.last_message_time or s.created_at or datetime.min

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
        await self._subscribe(MessageEvent.PROFILE_UPDATED, self._on_profile_updated)
        await self._subscribe(MessageEvent.GROUP_UPDATED, self._on_group_updated)
        await self._subscribe(MessageEvent.GROUP_SELF_UPDATED, self._on_group_self_updated)
        await self._subscribe(MessageEvent.DECRYPTION_STATE_CHANGED, self._on_message_decryption_state_changed)
        await self._subscribe(CallEvent.INVITE_SENT, self._apply_call_state_event)
        await self._subscribe(CallEvent.INVITE_RECEIVED, self._apply_call_state_event)
        await self._subscribe(CallEvent.RINGING, self._apply_call_state_event)
        await self._subscribe(CallEvent.ACCEPTED, self._apply_call_state_event)
        await self._subscribe(CallEvent.REJECTED, self._apply_call_state_event)
        await self._subscribe(CallEvent.ENDED, self._apply_call_state_event)
        await self._subscribe(CallEvent.BUSY, self._apply_call_state_event)
        await self._subscribe(CallEvent.FAILED, self._apply_call_state_event)

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
            current_user_id = await self._get_current_user_id()
            self._apply_last_message_preview(session, message, current_user_id=current_user_id)

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
            current_user_id = await self._get_current_user_id()
            self._apply_last_message_preview(session, message, current_user_id=current_user_id)
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
        session_type = str(data.get("session_type") or "").strip()
        if session_type not in {"direct", "group", "ai"}:
            logger.warning("Session payload missing authoritative session_type: %s", data.get("session_id") or data.get("id"))
            return None
        data["session_type"] = session_type

        current_user = await self._get_current_user_context()
        current_user_id = str(current_user.get("id", "") or "")
        authoritative_name = str(data.get("name", "") or "").strip()
        if str(data.get("last_message_status") or "") == MessageStatus.RECALLED.value:
            actor_id = str(data.get("last_message_sender_id", "") or "")
            data["last_message"] = (
                tr("message.recalled.self", "You recalled a message")
                if actor_id and actor_id == current_user_id
                else tr("message.recalled.other", "The other side recalled a message")
            )

        counterpart_name = str(data.get("counterpart_name", "") or "").strip()
        if session_type == "direct" and not data.get("is_ai_session"):
            if counterpart_name:
                data["name"] = counterpart_name
            else:
                fallback_counterpart_name = self._resolve_counterpart_name(
                    data.get("members") or [],
                    current_user_id,
                ) or self._resolve_counterpart_id(
                    data.get("participant_ids") or [],
                    current_user_id,
                )
                if fallback_counterpart_name:
                    data["name"] = fallback_counterpart_name

        if avatar and not data.get("avatar"):
            data["avatar"] = avatar

        try:
            session = Session.from_dict(data)
        except Exception as exc:
            logger.warning("Normalize session payload failed: %s", exc)
            return None

        session.extra["members"] = data.get("members") or []
        session.extra["server_name"] = authoritative_name
        if data.get("group_id"):
            session.extra["group_id"] = str(data.get("group_id") or "")
        if "group_announcement" in data:
            session.extra["group_announcement"] = str(data.get("group_announcement", "") or "")
        if "announcement_message_id" in data:
            session.extra["announcement_message_id"] = str(data.get("announcement_message_id", "") or "")
        if "announcement_author_id" in data:
            session.extra["announcement_author_id"] = str(data.get("announcement_author_id", "") or "")
        if "announcement_published_at" in data:
            session.extra["announcement_published_at"] = str(data.get("announcement_published_at", "") or "")
        if "group_note" in data:
            session.extra["group_note"] = str(data.get("group_note", "") or "")
        if "my_group_nickname" in data:
            session.extra["my_group_nickname"] = str(data.get("my_group_nickname", "") or "")
        if "group_member_version" in data or "member_version" in data:
            session.extra["group_member_version"] = int(data.get("group_member_version", data.get("member_version", 0)) or 0)
        if data.get("last_message_status"):
            session.extra["last_message_status"] = data.get("last_message_status")
        if data.get("last_message_id"):
            session.extra["last_message_id"] = str(data.get("last_message_id") or "")
        if data.get("last_message_sender_id"):
            session.extra["last_message_sender_id"] = data.get("last_message_sender_id")
        session.extra["encryption_mode"] = self._normalize_encryption_mode(
            data.get("encryption_mode"),
            session_type=session.session_type,
            is_ai_session=bool(session.is_ai_session),
        )
        session.extra["session_crypto_state"] = dict(data.get("session_crypto_state") or {})
        session.extra["call_capabilities"] = self._normalize_call_capabilities(
            data.get("call_capabilities"),
            session_type=session.session_type,
            is_ai_session=bool(session.is_ai_session),
        )
        if session_type == "direct":
            counterpart_id = str(data.get("counterpart_id", "") or "").strip()
            counterpart_username = str(data.get("counterpart_username", "") or "").strip()
            counterpart_avatar = str(data.get("counterpart_avatar", "") or "").strip()
            counterpart_gender = str(data.get("counterpart_gender", "") or "").strip()
            if counterpart_id:
                session.extra["counterpart_id"] = counterpart_id
            if counterpart_username:
                session.extra["counterpart_username"] = counterpart_username
            if counterpart_avatar:
                session.extra["counterpart_avatar"] = counterpart_avatar
            if counterpart_gender:
                session.extra["counterpart_gender"] = counterpart_gender
        await self._decorate_session_members([session], current_user)
        await self._annotate_session_crypto_state([session])
        self._normalize_session_display(session, current_user)
        return session

    async def _remember_session(self, session: Session) -> Session:
        """Insert a fetched session once and return the canonical cached object."""
        existing = self._sessions.get(session.session_id)
        if existing is not None:
            return existing

        await self.add_session(session)
        return session

    async def _build_fallback_session(self, message: ChatMessage) -> Optional[Session]:
        """Build one session snapshot only from authoritative message metadata."""
        current_user_id = await self._get_current_user_id()
        session_type = str(message.extra.get("session_type") or "").strip()
        if session_type not in {"direct", "group", "ai"}:
            logger.warning(
                "Skip fallback session bootstrap for %s: authoritative session_type missing",
                message.session_id,
            )
            return None

        participant_ids = [
            value
            for value in dict.fromkeys(
                str(item or "").strip() for item in (message.extra.get("participant_ids") or [])
            )
            if value
        ]
        if not participant_ids and session_type == "direct":
            participant_ids = [value for value in (current_user_id, message.sender_id) if value]

        session_name = str(message.extra.get("session_name", "") or "").strip()
        session_avatar = str(message.extra.get("session_avatar", "") or "").strip()
        sender_name = (
            str(message.extra.get("sender_nickname", "") or "").strip()
            or str(message.extra.get("sender_name", "") or "").strip()
            or str(message.sender_id or "").strip()
        )
        counterpart_id = self._resolve_counterpart_id(participant_ids, current_user_id)
        counterpart_username = str(message.extra.get("sender_username", "") or "").strip()
        counterpart_avatar = str(message.extra.get("sender_avatar", "") or "").strip()
        counterpart_gender = str(message.extra.get("sender_gender", "") or "").strip()

        if session_type == "group":
            display_name = session_name
            avatar = session_avatar or None
        elif session_type == "ai":
            display_name = session_name or "AI Assistant"
            avatar = session_avatar or None
        else:
            sender_is_counterpart = bool(message.sender_id and message.sender_id != current_user_id)
            display_name = sender_name if sender_is_counterpart else (counterpart_id or session_name or tr("session.private_chat", "Private Chat"))
            avatar = session_avatar or None

        session = Session(
            session_id=message.session_id,
            name=display_name or session_name or "New Chat",
            session_type=session_type,
            participant_ids=participant_ids,
            last_message=format_message_preview(message.content, message.message_type),
            last_message_time=message.timestamp,
            avatar=avatar,
            created_at=message.timestamp,
            updated_at=message.timestamp,
            is_ai_session=bool(message.extra.get("is_ai_session", False) or session_type == "ai"),
        )
        session.extra["last_message_type"] = message.message_type.value
        session.extra["last_message_id"] = str(message.message_id or "")
        session.extra["last_message_sender_id"] = str(message.sender_id or "")
        session.extra["members"] = list(message.extra.get("members") or [])
        session.extra["server_name"] = session_name
        session.extra["encryption_mode"] = self._default_encryption_mode(
            session_type=session.session_type,
            is_ai_session=bool(session.is_ai_session),
        )
        session.extra["session_crypto_state"] = {}
        session.extra["call_capabilities"] = self._default_call_capabilities(
            session_type=session.session_type,
            is_ai_session=bool(session.is_ai_session),
        )
        if session_type == "direct":
            if counterpart_id:
                session.extra["counterpart_id"] = counterpart_id
            if counterpart_username:
                session.extra["counterpart_username"] = counterpart_username
            if counterpart_avatar:
                session.extra["counterpart_avatar"] = counterpart_avatar
            if counterpart_gender:
                session.extra["counterpart_gender"] = counterpart_gender
        session.extra["avatar_seed"] = profile_avatar_seed(
            user_id=counterpart_id or message.session_id,
            username=counterpart_username,
            display_name=display_name or session_name or message.session_id,
        )
        current_user = await self._get_current_user_context()
        await self._decorate_session_members([session], current_user)
        self._normalize_session_display(session, current_user)
        return session

    async def _get_current_user_id(self) -> str:
        """Load current user id from persisted auth state."""
        if self._current_user_id:
            return self._current_user_id
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

    @staticmethod
    def _member_display_name(member: dict[str, Any]) -> str:
        """Resolve one stable display name using remark-first priority."""
        return (
            str(member.get("remark", "") or "").strip()
            or str(member.get("group_nickname", "") or "").strip()
            or str(member.get("nickname", "") or "").strip()
            or str(member.get("display_name", "") or "").strip()
            or str(member.get("username", "") or "").strip()
            or str(member.get("id", "") or "").strip()
        )

    async def _load_contact_cache_map(self, user_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Load one contact lookup map so session presentation can prefer remarks."""
        normalized_user_ids = [
            value
            for value in dict.fromkeys(str(user_id or "").strip() for user_id in user_ids)
            if value
        ]
        if not normalized_user_ids:
            return {}

        db = get_database()
        if not getattr(db, "is_connected", False):
            return {}
        loader = getattr(db, "list_contacts_cache_by_ids", None)
        if loader is None:
            return {}

        try:
            return await loader(normalized_user_ids)
        except Exception as exc:
            logger.debug("Load contact cache map failed: %s", exc)
            return {}

    async def _decorate_session_members(self, sessions: list[Session], current_user: dict[str, Any]) -> None:
        """Overlay contact remarks onto session members for all presentation rules."""
        current_user_id = str(current_user.get("id", "") or "")
        user_ids: list[str] = []
        for session in sessions:
            members = list(session.extra.get("members") or [])
            for member in members:
                member_id = str(member.get("id", "") or "").strip()
                if member_id:
                    user_ids.append(member_id)

        contacts_by_id = await self._load_contact_cache_map(user_ids)
        for session in sessions:
            members = []
            for raw_member in list(session.extra.get("members") or []):
                member = dict(raw_member or {})
                member_id = str(member.get("id", "") or "").strip()
                contact = contacts_by_id.get(member_id) or {}
                remark = str(contact.get("remark", "") or "").strip()
                if remark:
                    member["remark"] = remark
                if not str(member.get("username", "") or "").strip() and contact.get("username"):
                    member["username"] = str(contact.get("username") or "")
                if not str(member.get("nickname", "") or "").strip() and contact.get("nickname"):
                    member["nickname"] = str(contact.get("nickname") or "")
                member["display_name"] = self._member_display_name(member)
                members.append(member)
            session.extra["members"] = members
            session.extra["current_user_id"] = current_user_id
            if session.session_type == "group":
                session.extra["member_count"] = max(
                    len([item for item in session.participant_ids if str(item or "").strip()]),
                    len(members),
                    int(session.extra.get("member_count", 0) or 0),
                )

    def _normalize_session_display(self, session: Session, current_user: dict[str, Any]) -> None:
        """Normalize direct-session display fields to the counterpart profile."""
        if session.is_ai_session:
            return

        session.extra["current_user_id"] = str(current_user.get("id", "") or "")
        if session.session_type == "group":
            session.extra["member_count"] = max(
                len([item for item in session.participant_ids if str(item or "").strip()]),
                len(list(session.extra.get("members") or [])),
                int(session.extra.get("member_count", 0) or 0),
            )
            return

        counterpart = self._resolve_counterpart_profile(
            session.extra.get("members") or [],
            session.participant_ids,
            current_user,
        )
        counterpart_name = str(counterpart.get("display_name", "") or "")
        counterpart_id = str(counterpart.get("id", "") or session.extra.get("counterpart_id", "") or "")
        counterpart_username = str(counterpart.get("username", "") or session.extra.get("counterpart_username", "") or "")
        counterpart_avatar = str(counterpart.get("avatar", "") or session.extra.get("counterpart_avatar", "") or "")
        counterpart_gender = str(counterpart.get("gender", "") or session.extra.get("counterpart_gender", "") or "")

        if counterpart_name:
            session.name = counterpart_name

        current_user_id = str(current_user.get("id", "") or "")
        current_username = str(current_user.get("username", "") or "")
        current_nickname = str(current_user.get("nickname", "") or "")
        private_chat_label = tr("session.private_chat", "Private Chat")
        self_names = {value for value in {current_user_id, current_username, current_nickname, private_chat_label} if value}
        if (not session.name or session.name in self_names) and counterpart_id:
            session.name = counterpart_id

        if counterpart_id:
            session.extra["counterpart_id"] = counterpart_id
        if counterpart_username:
            session.extra["counterpart_username"] = counterpart_username
        if counterpart_avatar:
            session.extra["counterpart_avatar"] = counterpart_avatar
        if counterpart_gender:
            session.extra["counterpart_gender"] = counterpart_gender

        session.extra["avatar_seed"] = profile_avatar_seed(
            user_id=counterpart_id or session.session_id,
            username=counterpart_username,
            display_name=counterpart_name or session.name,
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
                "display_name": self._member_display_name(member) or member_username or member_id,
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

    def _resolve_counterpart_name(self, members: list[dict[str, Any]], current_user_id: str) -> str:
        """Resolve the other participant's display name for direct chats."""
        for member in members:
            member_id = str(member.get("id", "") or "")
            if current_user_id and member_id == current_user_id:
                continue
            return self._member_display_name(member) or member_id
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

        if not (
            self._current_session_active
            and self._current_session_id == message.session_id
        ):
            await self.increment_unread(message.session_id)

    async def _on_history_synced(self, data: dict) -> None:
        """Apply a synced message batch without re-emitting per-message updates."""
        messages: list[ChatMessage] = data.get("messages") or []
        if not messages:
            await self._reconcile_unread_counts()
            return
        current_user_id = await self._get_current_user_id()
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

                self._apply_last_message_preview(session, message, current_user_id=current_user_id)

                changed_sessions[session.session_id] = session

        if changed_sessions and db.is_connected:
            await db.save_sessions_batch(list(changed_sessions.values()))

        await self._reconcile_unread_counts()

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

    async def _on_message_decryption_state_changed(self, data: dict) -> None:
        session_id = str(data.get("session_id", "") or "").strip()
        if not session_id:
            return

        db = get_database()
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None or not session.uses_e2ee():
                return
            changed = self._apply_message_crypto_state_to_session(session, data)

        if not changed:
            return

        if db.is_connected:
            await db.save_session(session)
        await self._event_bus.emit(SessionEvent.UPDATED, {
            "session": session,
        })

    async def _on_profile_updated(self, data: dict) -> None:
        """Apply one user-profile update to cached session presentation state."""
        session_id = str(data.get("session_id", "") or "")
        user_id = str(data.get("user_id", "") or "")
        profile = dict(data.get("profile") or {}) if isinstance(data.get("profile"), dict) else {}
        if not session_id or not user_id or not profile:
            return

        current_user = await self._get_current_user_context()
        db = get_database()
        updated_session: Optional[Session] = None

        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return

            changed = False
            session_avatar = str(data.get("session_avatar", "") or "").strip()
            if session_avatar and session.avatar != session_avatar:
                session.avatar = session_avatar
                changed = True

            members = list(session.extra.get("members") or [])
            if members:
                updated_members = []
                for raw_member in members:
                    member = dict(raw_member or {})
                    if str(member.get("id", "") or "").strip() == user_id:
                        for key in ("username", "nickname", "avatar", "gender"):
                            new_value = str(profile.get(key, "") or "")
                            if str(member.get(key, "") or "") != new_value:
                                member[key] = new_value
                                changed = True
                    member["display_name"] = self._member_display_name(member)
                    updated_members.append(member)
                session.extra["members"] = updated_members

            counterpart_id = str(session.extra.get("counterpart_id", "") or self._resolve_counterpart_id(session.participant_ids, str(current_user.get("id", "") or "")))
            if session.session_type == "direct" and counterpart_id == user_id:
                mapping = {
                    "counterpart_username": str(profile.get("username", "") or ""),
                    "counterpart_avatar": str(profile.get("avatar", "") or ""),
                    "counterpart_gender": str(profile.get("gender", "") or ""),
                }
                for key, value in mapping.items():
                    if str(session.extra.get(key, "") or "") != value:
                        session.extra[key] = value
                        changed = True

            previous_name = session.name
            previous_seed = str(session.extra.get("avatar_seed", "") or "")
            self._normalize_session_display(session, current_user)
            if session.name != previous_name or str(session.extra.get("avatar_seed", "") or "") != previous_seed:
                changed = True

            if not changed:
                return
            updated_session = session

        if updated_session is not None and db.is_connected:
            await db.save_session(updated_session)

        if updated_session is not None:
            await self._event_bus.emit(SessionEvent.UPDATED, {"session": updated_session})

    async def _merge_group_payload_into_session(
        self,
        session: Session,
        payload: dict[str, Any],
        current_user: dict[str, Any],
        *,
        include_self_fields: bool,
    ) -> bool:
        """Apply one authoritative group payload onto a cached session."""
        changed = False
        if "name" in payload:
            group_name = str(payload.get("name", "") or "")
            if session.name != group_name:
                session.name = group_name
                changed = True
            if session.extra.get("server_name") != group_name:
                session.extra["server_name"] = group_name
                changed = True

        if "avatar" in payload:
            group_avatar = str(payload.get("avatar", "") or "")
            if str(session.avatar or "") != group_avatar:
                session.avatar = group_avatar or None
                changed = True

        shared_mapping: dict[str, Any] = {}
        if "group_id" in payload or "id" in payload:
            shared_mapping["group_id"] = str(
                payload.get("group_id", "") or payload.get("id", "") or session.extra.get("group_id", "") or ""
            )
        if "announcement" in payload:
            shared_mapping["group_announcement"] = str(payload.get("announcement", "") or "")
        if "announcement_message_id" in payload:
            shared_mapping["announcement_message_id"] = str(payload.get("announcement_message_id", "") or "")
        if "announcement_author_id" in payload:
            shared_mapping["announcement_author_id"] = str(payload.get("announcement_author_id", "") or "")
        if "announcement_published_at" in payload:
            shared_mapping["announcement_published_at"] = str(payload.get("announcement_published_at", "") or "")
        if "owner_id" in payload:
            shared_mapping["owner_id"] = str(payload.get("owner_id", "") or "")
        if "member_count" in payload:
            shared_mapping["member_count"] = int(payload.get("member_count", 0) or 0)
        if "group_member_version" in payload or "member_version" in payload:
            shared_mapping["group_member_version"] = int(payload.get("group_member_version", payload.get("member_version", 0)) or 0)
        for key, value in shared_mapping.items():
            if session.extra.get(key) != value:
                session.extra[key] = value
                changed = True

        members = payload.get("members")
        if isinstance(members, list):
            normalized_members = [dict(item or {}) for item in members if isinstance(item, dict)]
            if session.extra.get("members") != normalized_members:
                session.extra["members"] = normalized_members
                changed = True
            current_user_id = str(current_user.get("id", "") or "")
            if current_user_id:
                current_member = next((item for item in normalized_members if str(item.get("id", "") or "") == current_user_id), None)
                derived_nickname = str((current_member or {}).get("group_nickname", "") or "")
                if session.extra.get("my_group_nickname") != derived_nickname:
                    session.extra["my_group_nickname"] = derived_nickname
                    changed = True

        if include_self_fields:
            for key in ("group_note", "my_group_nickname"):
                if key not in payload:
                    continue
                value = str(payload.get(key, "") or "")
                if session.extra.get(key) != value:
                    session.extra[key] = value
                    changed = True
            current_user_id = str(current_user.get("id", "") or "")
            my_group_nickname = str(payload.get("my_group_nickname", "") or "")
            if current_user_id and "my_group_nickname" in payload:
                updated_members: list[dict[str, Any]] = []
                members_changed = False
                for raw_member in list(session.extra.get("members") or []):
                    member = dict(raw_member or {})
                    if str(member.get("id", "") or "").strip() == current_user_id:
                        if str(member.get("group_nickname", "") or "") != my_group_nickname:
                            member["group_nickname"] = my_group_nickname
                            members_changed = True
                        member["display_name"] = self._member_display_name(member)
                    updated_members.append(member)
                if members_changed:
                    session.extra["members"] = updated_members
                    changed = True

        previous_name = session.name
        previous_seed = str(session.extra.get("avatar_seed", "") or "")
        await self._decorate_session_members([session], current_user)
        self._normalize_session_display(session, current_user)
        if session.name != previous_name or str(session.extra.get("avatar_seed", "") or "") != previous_seed:
            changed = True
        return changed

    async def apply_group_payload(
        self,
        session_id: str,
        payload: dict[str, Any],
        *,
        include_self_fields: bool,
    ) -> Optional[Session]:
        """Apply one authoritative group payload through the same path used by realtime events."""
        normalized_session_id = str(session_id or "").strip()
        normalized_payload = dict(payload or {})
        if not normalized_session_id or not normalized_payload:
            return None

        current_user = await self._get_current_user_context()
        db = get_database()
        updated_session: Optional[Session] = None
        async with self._lock:
            session = self._sessions.get(normalized_session_id)
            if session is None or session.session_type != "group":
                return None
            if not await self._merge_group_payload_into_session(session, normalized_payload, current_user, include_self_fields=include_self_fields):
                return session
            updated_session = session

        if updated_session is not None and db.is_connected:
            await db.save_session(updated_session)
        if updated_session is not None:
            await self._event_bus.emit(SessionEvent.UPDATED, {"session": updated_session})
        return updated_session

    async def _on_group_updated(self, data: dict) -> None:
        """Apply one shared group-profile update to cached group sessions."""
        session_id = str(data.get("session_id", "") or "")
        payload = dict(data.get("group") or {}) if isinstance(data.get("group"), dict) else {}
        if not session_id or not payload:
            return
        await self.apply_group_payload(session_id, payload, include_self_fields=False)

    async def _on_group_self_updated(self, data: dict) -> None:
        """Apply one self-scoped group-profile update to cached group sessions."""
        session_id = str(data.get("session_id", "") or "")
        if not session_id:
            return
        payload = {
            "group_note": str(data.get("group_note", "") or ""),
            "my_group_nickname": str(data.get("my_group_nickname", "") or ""),
        }
        await self.apply_group_payload(session_id, payload, include_self_fields=True)

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
        if "is_muted" in source.extra:
            target.extra["is_muted"] = bool(source.extra.get("is_muted", False))
        if "show_member_nickname" in source.extra:
            target.extra["show_member_nickname"] = bool(source.extra.get("show_member_nickname", True))
        source_last_message_id = str(source.extra.get("last_message_id", "") or "")
        target_last_message_id = str(target.extra.get("last_message_id", "") or "")
        if source_last_message_id and source_last_message_id == target_last_message_id:
            target.extra["last_message_id"] = target_last_message_id
        if (
            "last_message_mentions_current_user" in source.extra
            and source_last_message_id
            and source_last_message_id == target_last_message_id
        ):
            target.extra["last_message_mentions_current_user"] = bool(source.extra.get("last_message_mentions_current_user", False))
        source_announcement_message_id = str(source.extra.get("announcement_message_id", "") or "")
        target_announcement_message_id = str(target.extra.get("announcement_message_id", "") or "")
        if (
            source_announcement_message_id
            and source_announcement_message_id == target_announcement_message_id
            and "last_viewed_announcement_message_id" in source.extra
        ):
            target.extra["last_viewed_announcement_message_id"] = str(
                source.extra.get("last_viewed_announcement_message_id", "") or ""
            )
        if "session_crypto_state" in source.extra and "session_crypto_state" not in target.extra:
            target.extra["session_crypto_state"] = dict(source.extra.get("session_crypto_state") or {})
        if "call_capabilities" in source.extra and "call_capabilities" not in target.extra:
            target.extra["call_capabilities"] = dict(source.extra.get("call_capabilities") or {})
        if "call_state" in source.extra and "call_state" not in target.extra:
            target.extra["call_state"] = dict(source.extra.get("call_state") or {})

    async def load_sessions(self, sessions: list[Session]) -> None:
        """Load sessions from storage."""
        current_user = await self._get_current_user_context()
        await self._decorate_session_members(sessions, current_user)
        await self._annotate_session_crypto_state(sessions)
        async with self._lock:
            self._sessions.clear()
            for session in sessions:
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
        await self._decorate_session_members(sessions, current_user)
        await self._annotate_session_crypto_state(sessions)
        hidden_changed = False
        async with self._lock:
            existing_sessions = dict(self._sessions)
            self._sessions.clear()
            for session in sessions:
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

    async def recover_session_crypto(self, session_id: str) -> dict[str, Any]:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise RuntimeError("session id is required")

        async with self._lock:
            session = self._sessions.get(normalized_session_id)
            if session is None:
                raise RuntimeError("session not found")
            crypto_state = dict(session.extra.get("session_crypto_state") or {})

        if not session.uses_e2ee():
            return {"performed": False, "reason": "session_not_e2ee"}

        recovery_action = str(crypto_state.get("recovery_action") or "").strip()
        if recovery_action != "reprovision_device":
            return {"performed": False, "reason": recovery_action or "no_recovery_action"}

        response = await self._require_e2ee_service().reprovision_local_device()
        await self._refresh_cached_session_crypto_state(after_recovery=True)
        message_recovery: dict[str, Any] = {
            "session_id": normalized_session_id,
            "attempted": False,
            "updated": 0,
            "message_ids": [],
        }
        try:
            message_recovery = dict(await self._msg_manager.recover_session_messages(normalized_session_id))
            message_recovery["attempted"] = True
        except Exception as exc:
            logger.warning("Failed to retry local message decryption for %s: %s", normalized_session_id, exc)
            message_recovery["error"] = str(exc)
        await self._record_session_message_recovery(normalized_session_id, message_recovery)
        return {
            "performed": True,
            "session_id": normalized_session_id,
            "recovery_action": recovery_action,
            "device": dict(response or {}),
            "message_recovery": message_recovery,
        }

    async def trust_session_identities(self, session_id: str) -> dict[str, Any]:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise RuntimeError("session id is required")

        async with self._lock:
            session = self._sessions.get(normalized_session_id)
            if session is None:
                raise RuntimeError("session not found")

        if session.session_type != "direct" or bool(session.is_ai_session):
            return {"performed": False, "reason": "session_not_direct_e2ee"}

        counterpart_id = str(session.extra.get("counterpart_id") or "").strip()
        if not counterpart_id:
            return {"performed": False, "reason": "missing_counterpart_id"}

        previous_identity_status = str(session.extra.get("session_crypto_state", {}).get("identity_status") or "").strip()
        trust_summary = await self._require_e2ee_service().trust_peer_identities(counterpart_id)
        await self._annotate_session_crypto_state([session])

        db = get_database()
        if db.is_connected:
            await db.replace_sessions(list(self._sessions.values()))
        await self._event_bus.emit(SessionEvent.UPDATED, {"sessions": self.sessions})
        return {
            "performed": True,
            "session_id": normalized_session_id,
            "user_id": counterpart_id,
            "previous_identity_status": previous_identity_status,
            "alert_cleared": previous_identity_status in {"identity_changed", "unverified"},
            "identity_summary": dict(trust_summary or {}),
        }

    async def get_session_security_summary(self, session_id: str) -> dict[str, Any]:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise RuntimeError("session id is required")

        async with self._lock:
            session = self._sessions.get(normalized_session_id)
            if session is None:
                raise RuntimeError("session not found")
            return session.security_summary()

    async def get_current_session_security_summary(self) -> dict[str, Any]:
        session_id = str(self._current_session_id or "").strip()
        if not session_id:
            raise RuntimeError("no current session selected")
        return await self.get_session_security_summary(session_id)

    async def get_session_identity_verification(self, session_id: str) -> dict[str, Any]:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise RuntimeError("session id is required")

        async with self._lock:
            session = self._sessions.get(normalized_session_id)
            if session is None:
                raise RuntimeError("session not found")
            security_summary = session.security_summary()

        if session.session_type != "direct" or bool(session.is_ai_session):
            return {
                "session_id": normalized_session_id,
                "available": False,
                "reason": "session_not_direct_e2ee",
                "security_summary": security_summary,
                "verification": {},
            }

        counterpart_id = str(session.extra.get("counterpart_id") or "").strip()
        if not counterpart_id:
            return {
                "session_id": normalized_session_id,
                "available": False,
                "reason": "missing_counterpart_id",
                "security_summary": security_summary,
                "verification": {},
            }

        verification = dict(await self._require_e2ee_service().get_peer_identity_summary(counterpart_id))
        return {
            "session_id": normalized_session_id,
            "user_id": counterpart_id,
            "available": bool(verification.get("verification_available")),
            "security_summary": security_summary,
            "verification": verification,
        }

    async def get_current_session_identity_verification(self) -> dict[str, Any]:
        session_id = str(self._current_session_id or "").strip()
        if not session_id:
            raise RuntimeError("no current session selected")
        return await self.get_session_identity_verification(session_id)

    @staticmethod
    def _build_identity_review_timeline(verification: dict[str, Any]) -> list[dict[str, Any]]:
        timeline: list[dict[str, Any]] = []
        first_seen_at = str(verification.get("first_seen_at") or "").strip()
        last_changed_at = str(verification.get("last_changed_at") or "").strip()
        last_trusted_at = str(verification.get("last_trusted_at") or "").strip()
        checked_at = str(verification.get("checked_at") or "").strip()
        if first_seen_at:
            timeline.append(
                {"kind": "first_seen", "at": first_seen_at, "label": "First observed on this device"}
            )
        if last_changed_at:
            timeline.append(
                {"kind": "identity_changed", "at": last_changed_at, "label": "Peer identity changed"}
            )
        if last_trusted_at:
            timeline.append(
                {"kind": "trusted", "at": last_trusted_at, "label": "Peer identity trusted locally"}
            )
        if checked_at:
            timeline.append(
                {"kind": "last_checked", "at": checked_at, "label": "Latest identity check"}
            )
        return timeline

    async def get_session_identity_review_details(self, session_id: str) -> dict[str, Any]:
        verification_result = await self.get_session_identity_verification(session_id)
        verification = dict(verification_result.get("verification") or {})
        primary_device_id = str(verification.get("primary_verification_device_id") or "").strip()
        primary_device = {}
        for device in list(verification.get("devices") or []):
            if not isinstance(device, dict):
                continue
            if str(device.get("device_id") or "").strip() == primary_device_id:
                primary_device = dict(device)
                break

        return {
            "session_id": str(verification_result.get("session_id") or ""),
            "user_id": str(verification_result.get("user_id") or ""),
            "available": bool(verification_result.get("available")),
            "reason": str(verification_result.get("reason") or ""),
            "blocking": bool(
                dict(verification_result.get("security_summary") or {}).get("identity_review_blocking", False)
            ),
            "recommended_action": str(
                dict(verification_result.get("security_summary") or {}).get("recommended_action") or ""
            ),
            "security_summary": dict(verification_result.get("security_summary") or {}),
            "verification": verification,
            "primary_device": primary_device,
            "timeline": self._build_identity_review_timeline(
                {
                    **verification,
                    "first_seen_at": str(primary_device.get("first_seen_at") or ""),
                    "last_changed_at": str(primary_device.get("last_changed_at") or verification.get("last_changed_at") or ""),
                    "last_trusted_at": str(primary_device.get("last_trusted_at") or verification.get("last_trusted_at") or ""),
                    "checked_at": str(verification.get("checked_at") or ""),
                }
            ),
        }

    async def get_current_session_identity_review_details(self) -> dict[str, Any]:
        session_id = str(self._current_session_id or "").strip()
        if not session_id:
            raise RuntimeError("no current session selected")
        return await self.get_session_identity_review_details(session_id)

    async def get_session_security_diagnostics(self, session_id: str) -> dict[str, Any]:
        summary = await self.get_session_security_summary(session_id)
        review_details = await self.get_session_identity_review_details(session_id)
        return {
            "session_id": str(summary.get("session_id") or session_id or ""),
            "headline": str(summary.get("headline") or ""),
            "recommended_action": str(summary.get("recommended_action") or ""),
            "security_summary": summary,
            "identity_review": review_details,
            "actions": list(summary.get("actions") or []),
        }

    async def get_current_session_security_diagnostics(self) -> dict[str, Any]:
        session_id = str(self._current_session_id or "").strip()
        if not session_id:
            raise RuntimeError("no current session selected")
        return await self.get_session_security_diagnostics(session_id)

    async def execute_session_security_action(self, session_id: str, action_id: str) -> dict[str, Any]:
        normalized_session_id = str(session_id or "").strip()
        normalized_action_id = str(action_id or "").strip()
        if not normalized_session_id:
            raise RuntimeError("session id is required")
        if not normalized_action_id:
            raise RuntimeError("action id is required")

        async with self._lock:
            session = self._sessions.get(normalized_session_id)
            if session is None:
                raise RuntimeError("session not found")
            security_summary = session.security_summary()
            crypto_state = dict(session.extra.get("session_crypto_state") or {})

        allowed_action_ids = {
            str(action.get("id") or "").strip()
            for action in list(security_summary.get("actions") or [])
            if isinstance(action, dict) and str(action.get("id") or "").strip()
        }
        if normalized_action_id not in allowed_action_ids:
            return {
                "performed": False,
                "session_id": normalized_session_id,
                "action_id": normalized_action_id,
                "reason": "action_not_available",
                "explanation": {
                    "code": "action_not_available",
                    "message": "The requested security action is not currently available for this session.",
                    "available_action_ids": sorted(allowed_action_ids),
                    "headline": str(security_summary.get("headline") or ""),
                },
                "security_summary": security_summary,
            }

        if normalized_action_id == "trust_peer_identity":
            result = await self.trust_session_identities(normalized_session_id)
        elif normalized_action_id == "reprovision_device":
            result = await self.recover_session_crypto(normalized_session_id)
        elif normalized_action_id == "switch_device":
            result = {
                "performed": False,
                "session_id": normalized_session_id,
                "action_id": normalized_action_id,
                "reason": "switch_device_required",
                "target_device_id": str(crypto_state.get("target_device_id") or ""),
                "explanation": {
                    "code": "switch_device_required",
                    "message": "This encrypted content is addressed to a different device and cannot be recovered on the current device.",
                },
                "external_requirement": {
                    "kind": "switch_device",
                    "target_device_id": str(crypto_state.get("target_device_id") or ""),
                    "blocking": True,
                },
            }
        else:
            result = {
                "performed": False,
                "session_id": normalized_session_id,
                "action_id": normalized_action_id,
                "reason": "unsupported_action",
                "explanation": {
                    "code": "unsupported_action",
                    "message": "The requested security action is not supported by this client.",
                },
            }

        if "session_id" not in result:
            result["session_id"] = normalized_session_id
        result["action_id"] = normalized_action_id
        result["security_summary"] = await self.get_session_security_summary(normalized_session_id)
        return result

    async def execute_current_session_security_action(self, action_id: str) -> dict[str, Any]:
        session_id = str(self._current_session_id or "").strip()
        if not session_id:
            raise RuntimeError("no current session selected")
        return await self.execute_session_security_action(session_id, action_id)

    async def _refresh_cached_session_crypto_state(self, *, after_recovery: bool = False) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())

        if not sessions:
            return

        await self._annotate_session_crypto_state(sessions)
        if after_recovery:
            recovered_at = datetime.now().isoformat()
            for session in sessions:
                state = dict(session.extra.get("session_crypto_state") or {})
                if not session.uses_e2ee():
                    continue
                state["ready"] = bool(state.get("device_registered"))
                state["can_decrypt"] = bool(state.get("device_registered"))
                state.pop("decryption_state", None)
                state.pop("recovery_action", None)
                state.pop("last_failure_message_id", None)
                state.pop("target_device_id", None)
                state["last_recovered_at"] = recovered_at
                session.extra["session_crypto_state"] = state

        db = get_database()
        if db.is_connected:
            await db.replace_sessions(sessions)
        await self._event_bus.emit(SessionEvent.UPDATED, {"sessions": self.sessions})

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

    async def _fetch_remote_unread_counts(self) -> dict[str, int] | None:
        """Fetch authoritative unread counts from the backend."""
        try:
            payload = await self._session_service.fetch_unread_counts()
        except Exception as exc:
            logger.warning("Refresh remote unread counts failed: %s", exc)
            return None

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

    async def _reconcile_unread_counts(self) -> None:
        """Refresh local unread counters from the authoritative backend snapshot."""
        if not self._sessions:
            return

        unread_count_map = await self._fetch_remote_unread_counts()
        if unread_count_map is None:
            return

        changed_sessions: list[Session] = []
        db = get_database()

        async with self._lock:
            for session in self._sessions.values():
                remote_unread = int(unread_count_map.get(session.session_id, 0))
                if session.unread_count == remote_unread:
                    continue
                session.unread_count = remote_unread
                changed_sessions.append(session)

            if db.is_connected:
                for session in changed_sessions:
                    await db.update_session_unread(session.session_id, session.unread_count)

        for session in changed_sessions:
            await self._event_bus.emit(SessionEvent.UNREAD_CHANGED, {
                "session_id": session.session_id,
                "unread_count": session.unread_count,
            })
            await self._event_bus.emit(SessionEvent.UPDATED, {
                "session": session,
            })
    async def add_session(self, session: Session) -> None:
        """Add a new session."""
        await self._annotate_session_crypto_state([session])
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

    async def set_muted(self, session_id: str, muted: bool) -> None:
        """Persist one local do-not-disturb flag for a session."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return

            current_muted = bool(session.extra.get("is_muted", False))
            if current_muted == muted:
                return

            session.extra["is_muted"] = bool(muted)

            db = get_database()
            if db.is_connected:
                await db.save_session(session)

        await self._event_bus.emit(SessionEvent.UPDATED, {
            "session": session,
        })

    async def set_group_member_nickname_visibility(self, session_id: str, enabled: bool) -> None:
        """Persist the local group member label visibility preference for one session."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session or session.session_type != "group":
                return

            normalized_enabled = bool(enabled)
            current_enabled = bool(session.extra.get("show_member_nickname", True))
            if current_enabled == normalized_enabled:
                return

            session.extra["show_member_nickname"] = normalized_enabled

            db = get_database()
            if db.is_connected:
                await db.save_session(session)

        await self._event_bus.emit(
            SessionEvent.UPDATED,
            {
                "session": session,
            },
        )

    async def mark_group_announcement_viewed(self, session_id: str, announcement_message_id: str) -> Optional[Session]:
        """Persist that the current user has opened the latest group announcement."""
        normalized_session_id = str(session_id or "").strip()
        normalized_message_id = str(announcement_message_id or "").strip()
        if not normalized_session_id or not normalized_message_id:
            return None

        updated_session: Optional[Session] = None
        db = get_database()
        async with self._lock:
            session = self._sessions.get(normalized_session_id)
            if session is None or session.session_type != "group":
                return None

            current_message_id = str(session.extra.get("announcement_message_id", "") or "").strip()
            viewed_message_id = str(session.extra.get("last_viewed_announcement_message_id", "") or "").strip()
            if current_message_id != normalized_message_id or viewed_message_id == normalized_message_id:
                return session

            session.extra["last_viewed_announcement_message_id"] = normalized_message_id
            updated_session = session

        if updated_session is not None and db.is_connected:
            await db.save_session(updated_session)
        if updated_session is not None:
            await self._event_bus.emit(SessionEvent.UPDATED, {"session": updated_session})
        return updated_session

    def is_session_muted(self, session_id: str) -> bool:
        """Return whether one session has local do-not-disturb enabled."""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        return bool(session.extra.get("is_muted", False))

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
        preview_time = last_message.timestamp if last_message else (session.last_message_time or session.created_at)
        current_user_id = await self._get_current_user_id()
        self._apply_last_message_preview(session, last_message, current_user_id=current_user_id)

        await self.update_session(
            session_id,
            last_message_time=preview_time,
            last_message=session.last_message,
            extra=dict(session.extra),
        )

    async def select_session(self, session_id: str) -> None:
        """Select a session as current."""
        old_id = self._current_session_id
        self._current_session_id = session_id
        selected_session: Optional[Session] = None

        async with self._lock:
            selected_session = self._sessions.get(session_id)
            if selected_session is not None and bool(selected_session.extra.get("last_message_mentions_current_user", False)):
                selected_session.extra["last_message_mentions_current_user"] = False
                db = get_database()
                if db.is_connected:
                    await db.save_session(selected_session)

        if selected_session is not None:
            await self._event_bus.emit(SessionEvent.UPDATED, {
                "session": selected_session,
            })

        if old_id != session_id:
            await self._event_bus.emit(SessionEvent.SELECTED, {
                "session_id": session_id,
                "previous_session_id": old_id,
            })

            if self._current_session_active:
                await self.clear_unread(session_id)

            logger.info(f"Session selected: {session_id}")

    async def clear_current_session(self) -> None:
        """Clear current session selection."""
        old_id = self._current_session_id
        self._current_session_id = None
        self._current_session_active = False

        await self._event_bus.emit(SessionEvent.SELECTED, {
            "session_id": None,
            "previous_session_id": old_id,
        })

    async def set_current_session_active(self, active: bool) -> None:
        """Mark whether the selected session is actually foreground-readable."""
        normalized_active = bool(active and self._current_session_id)
        if self._current_session_active == normalized_active:
            return

        self._current_session_active = normalized_active
        if normalized_active and self._current_session_id:
            await self.clear_unread(self._current_session_id)

    async def add_message_to_session(
            self,
            session_id: str,
            message: ChatMessage,
    ) -> None:
        """Add a message to session's last message."""
        current_user_id = await self._get_current_user_id()
        async with self._lock:
            session = self._sessions.get(session_id)

            if session:
                self._apply_last_message_preview(session, message, current_user_id=current_user_id)

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

        if self._identity_refresh_task is not None and not self._identity_refresh_task.done():
            self._identity_refresh_task.cancel()
            await asyncio.gather(self._identity_refresh_task, return_exceptions=True)
            self._identity_refresh_task = None

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












