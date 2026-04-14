"""
Message Manager Module

Manager for message handling, ACK processing, and caching.
"""
import asyncio
from copy import deepcopy
import hashlib
import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from client.core import logging
from client.core.exceptions import AppError
from client.core.i18n import tr
from client.core.logging import setup_logging
from client.events.contact_events import ContactEvent
from client.events.event_bus import get_event_bus
from client.managers.connection_manager import get_connection_manager
from client.models.message import ChatMessage, MessageStatus, MessageType, build_attachment_extra, build_recall_notice, merge_sender_profile_extra, resolve_recall_notice, sanitize_outbound_message_extra
from client.services.chat_service import get_chat_service
from client.services.e2ee_service import get_e2ee_service
from client.services.file_service import get_file_service
from client.storage.database import get_database


setup_logging()
logger = logging.get_logger(__name__)


# Event types
class MessageEvent:
    """Message event types."""

    SENT = "message_sent"
    RECEIVED = "message_received"
    ACK = "message_ack"
    FAILED = "message_failed"
    TYPING = "message_typing"
    READ = "message_read"
    DELIVERED = "message_delivered"
    SYNC_COMPLETED = "message_sync_completed"
    RECALLED = "message_recalled"
    EDITED = "message_edited"
    DELETED = "message_deleted"
    PROFILE_UPDATED = "message_profile_updated"
    GROUP_UPDATED = "message_group_updated"
    GROUP_SELF_UPDATED = "message_group_self_updated"
    MEDIA_READY = "message_media_ready"
    DECRYPTION_STATE_CHANGED = "message_decryption_state_changed"
    RECOVERED = "message_recovered"


@dataclass
class PendingMessage:
    """Pending outbound message tracked across transport attempts and ACKs."""

    message: ChatMessage
    session_id: str
    content: str
    message_type: str
    extra: dict[str, Any]
    created_at: float
    attempt_count: int = 0
    max_attempts: int = 3
    ack_timeout: float = 10.0
    last_attempt_at: float = 0.0
    awaiting_ack: bool = False


@dataclass
class QueuedMessage:
    """One transport attempt queued for websocket delivery."""

    message_id: str
    session_id: str
    content: str
    message_type: str
    extra: dict[str, Any]


class MessageSendQueue:
    """
    Async message send queue.

    Responsibilities:
        - Queue outbound websocket sends
        - Preserve message ordering
        - Report each transport attempt result back to MessageManager
    """

    QUEUE_TIMEOUT = 30.0
    STOP_TIMEOUT = 1.5

    def __init__(
        self,
        conn_manager,
        on_send_result: Callable[[QueuedMessage, bool], Awaitable[None]],
    ):
        self._conn_manager = conn_manager
        self._on_send_result = on_send_result

        self._queue: asyncio.Queue[QueuedMessage] = asyncio.Queue()
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._inflight: QueuedMessage | None = None

    async def start(self) -> None:
        """Start the queue worker."""
        if self._running:
            return

        self._running = True
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("Message send queue started")

    async def stop(self) -> None:
        """Stop the queue worker."""
        self._running = False

        if self._worker_task:
            try:
                await asyncio.wait_for(asyncio.shield(self._worker_task), timeout=self.STOP_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("Timed out waiting for message send queue worker to stop")
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass
            self._worker_task = None

        await self._fail_unprocessed_messages()
        logger.info("Message send queue stopped")

    async def enqueue(
        self,
        message_id: str,
        session_id: str,
        content: str,
        message_type: str,
        extra: dict[str, Any],
    ) -> None:
        """Add one outbound transport attempt to the queue."""
        queued = QueuedMessage(
            message_id=message_id,
            session_id=session_id,
            content=content,
            message_type=message_type,
            extra=sanitize_outbound_message_extra(extra),
        )

        await asyncio.wait_for(self._queue.put(queued), timeout=self.QUEUE_TIMEOUT)
        logger.debug("Message queued for websocket send: %s", message_id)

    async def _worker(self) -> None:
        """Background worker that processes queued transport attempts."""
        logger.debug("Message send queue worker started")

        while self._running or not self._queue.empty():
            try:
                queued = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                self._inflight = queued
                try:
                    await self._send_message(queued)
                finally:
                    self._inflight = None
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Queue worker error: {e}")

        logger.debug("Message send queue worker stopped")

    async def _send_message(self, queued: QueuedMessage) -> None:
        """Execute one websocket send attempt and report the result."""
        success = False
        try:
            success = await self._conn_manager.send_chat_message(
                session_id=queued.session_id,
                content=queued.content,
                msg_id=queued.message_id,
                message_type=queued.message_type,
                extra=queued.extra,
            )
        except asyncio.CancelledError:
            await self._on_send_result(queued, False)
            raise
        except Exception as e:
            logger.error(f"Send message error for {queued.message_id}: {e}")

        await self._on_send_result(queued, success)

    async def _fail_unprocessed_messages(self) -> None:
        if self._inflight is not None:
            queued = self._inflight
            self._inflight = None
            await self._on_send_result(queued, False)

        while not self._queue.empty():
            queued = self._queue.get_nowait()
            await self._on_send_result(queued, False)


class MessageManager:
    """
    Manager for message lifecycle.
    
    Responsibilities:
        - Send messages via WebSocket using queue
        - Handle incoming messages
        - Process ACK
        - Cache messages locally
        - Emit events to UI via EventBus
    """

    def __init__(self):
        self._event_bus = get_event_bus()
        self._conn_manager = get_connection_manager()
        self._db = get_database()
        self._chat_service = get_chat_service()
        self._e2ee_service = None
        self._file_service = get_file_service()

        # Send queue
        self._send_queue: Optional[MessageSendQueue] = None

        self._pending_messages: dict[str, PendingMessage] = {}
        self._pending_lock = asyncio.Lock()
        self._incoming_message_guard = asyncio.Lock()
        self._incoming_message_inflight: set[str] = set()
        self._recent_incoming_message_ids: dict[str, float] = {}
        self._incoming_message_dedupe_ttl = 300.0
        self._media_prefetch_tasks: dict[str, asyncio.Task] = {}

        self._ack_check_task: Optional[asyncio.Task] = None
        self._running = False
        self._initialized = False
        self._pending_sync_completion: Optional[dict[str, Any]] = None

        self._user_id: str = ""
        self._ack_timeout = 10.0
        self._max_attempts = 3
        self._transport_retry_delay = 2.0
        self._close_timeout = 1.5

    async def initialize(self) -> None:
        """Initialize message manager."""
        if self._initialized:
            logger.debug("Message manager already initialized")
            return

        # Initialize send queue
        self._send_queue = MessageSendQueue(
            self._conn_manager,
            self._handle_send_attempt_result,
        )
        await self._send_queue.start()

        logger.info("Message manager: adding listener")
        self._conn_manager.add_message_listener(self._handle_ws_message)

        logger.info("Message manager: setting running=True")
        self._running = True

        logger.info("Message manager: getting event loop")
        loop = asyncio.get_event_loop()
        logger.info(f"Message manager: got loop {loop}")

        logger.info("Message manager: creating ack check task")
        self._ack_check_task = asyncio.create_task(self._ack_check_loop())

        self._initialized = True
        logger.info("Message manager initialized")
    
    def set_user_id(self, user_id: str) -> None:
        """Set current user ID."""
        self._user_id = user_id

    def _build_pending_message(
        self,
        message: ChatMessage,
        session_id: str,
        content: str,
        message_type: str,
        extra: dict[str, Any],
    ) -> PendingMessage:
        """Build one authoritative outbound state entry for retries and ACK tracking."""
        return PendingMessage(
            message=message,
            session_id=session_id,
            content=content,
            message_type=message_type,
            extra=sanitize_outbound_message_extra(extra),
            created_at=time.time(),
            max_attempts=self._max_attempts,
            ack_timeout=self._ack_timeout,
        )

    async def _enqueue_pending_message(self, pending: PendingMessage) -> None:
        """Queue the next websocket transport attempt for one pending message."""
        if self._send_queue is None:
            raise RuntimeError("message send queue is not initialized")

        await self._send_queue.enqueue(
            message_id=pending.message.message_id,
            session_id=pending.session_id,
            content=pending.content,
            message_type=pending.message_type,
            extra=pending.extra,
        )

    async def _handle_send_attempt_result(self, queued: QueuedMessage, success: bool) -> None:
        """Update pending state after one websocket transport attempt."""
        if success:
            async with self._pending_lock:
                pending = self._pending_messages.get(queued.message_id)
                if pending is None:
                    logger.debug("Transport success ignored for unknown message: %s", queued.message_id)
                    return
                pending.attempt_count += 1
                pending.awaiting_ack = True
                pending.last_attempt_at = time.time()

            logger.debug("Message sent, waiting for ACK: %s", queued.message_id)
            return

        await self._handle_transport_failure(queued.message_id)

    async def _handle_transport_failure(self, message_id: str) -> None:
        """Retry or fail one outbound message after transport send failure."""
        retry_pending: Optional[PendingMessage] = None
        failed_pending: Optional[PendingMessage] = None

        async with self._pending_lock:
            pending = self._pending_messages.get(message_id)
            if pending is None:
                logger.debug("Transport failure ignored for unknown message: %s", message_id)
                return

            pending.attempt_count += 1
            pending.awaiting_ack = False
            pending.last_attempt_at = 0.0

            if pending.attempt_count < pending.max_attempts:
                retry_pending = pending
            else:
                failed_pending = self._pending_messages.pop(message_id)

        if retry_pending is not None:
            logger.warning(
                "Message transport failed (attempt %s/%s), retrying: %s",
                retry_pending.attempt_count,
                retry_pending.max_attempts,
                message_id,
            )
            await asyncio.sleep(self._transport_retry_delay)
            async with self._pending_lock:
                current_pending = self._pending_messages.get(message_id)
                if current_pending is not retry_pending:
                    return
            await self._enqueue_pending_message(retry_pending)
            return

        if failed_pending is not None:
            logger.error("Message send failed after %s attempts: %s", failed_pending.max_attempts, message_id)
            await self._finalize_pending_failure(failed_pending, "Transport send failed")

    async def _finalize_pending_failure(self, pending: PendingMessage, reason: str) -> None:
        """Persist one terminal outbound failure and notify the UI."""
        pending.message.status = MessageStatus.FAILED
        pending.message.updated_at = datetime.now()
        await self._db.save_message(pending.message)
        await self._event_bus.emit(MessageEvent.FAILED, {
            "message_id": pending.message.message_id,
            "message": pending.message,
            "reason": reason,
        })

    def _merge_ack_message(
        self,
        msg_id: str,
        ack_payload: Any,
        fallback_message: Optional[ChatMessage],
    ) -> Optional[ChatMessage]:
        """Merge canonical ACK payload from the server with local-only message metadata."""
        if not isinstance(ack_payload, dict) or not ack_payload:
            return fallback_message

        normalized = dict(ack_payload)
        if fallback_message is not None:
            normalized.setdefault("session_id", fallback_message.session_id)
            normalized.setdefault("sender_id", fallback_message.sender_id or self._user_id)
            normalized.setdefault("message_type", fallback_message.message_type.value)
            normalized.setdefault("content", fallback_message.content)
            normalized.setdefault("status", fallback_message.status.value)
            normalized.setdefault("is_self", True)
            merged_extra = self._merge_ack_extra(
                dict(fallback_message.extra or {}),
                dict(normalized.get("extra") or {}),
            )
            normalized["extra"] = merged_extra
        else:
            normalized.setdefault("sender_id", self._user_id)
            normalized.setdefault("is_self", True)

        normalized.setdefault("message_id", msg_id)
        return self._normalize_loaded_message(
            normalized,
            default_session_id=str(normalized.get("session_id", "") or ""),
        )

    @staticmethod
    def _merge_ack_extra(local_extra: dict[str, Any], ack_extra: dict[str, Any]) -> dict[str, Any]:
        """Merge canonical ACK extra fields without dropping local-only decrypted caches."""
        merged_extra = dict(local_extra or {})
        merged_extra.update(dict(ack_extra or {}))

        local_encryption = dict(local_extra.get("encryption") or {})
        ack_encryption = dict(ack_extra.get("encryption") or {})
        if local_encryption and ack_encryption:
            merged_encryption = dict(local_encryption)
            merged_encryption.update(ack_encryption)
            merged_extra["encryption"] = merged_encryption

        local_attachment = dict(local_extra.get("attachment_encryption") or {})
        ack_attachment = dict(ack_extra.get("attachment_encryption") or {})
        if local_attachment and ack_attachment:
            merged_attachment = dict(local_attachment)
            merged_attachment.update(ack_attachment)
            merged_extra["attachment_encryption"] = merged_attachment

        return merged_extra
    
    async def _handle_ws_message(self, data: dict) -> None:
        """Handle incoming WebSocket message."""
        msg_type = data.get("type")

        if msg_type == "message_ack":
            await self._process_ack(data)

        elif msg_type == "error":
            await self._process_error(data)

        elif msg_type == "chat_message":
            await self._process_incoming_message(data)

        elif msg_type == "history_messages":
            await self._process_history_messages(data)

        elif msg_type == "history_events":
            await self._process_history_events(data)

        elif msg_type == "typing":
            await self._process_typing(data)

        elif msg_type == "read":
            await self._process_read(data)

        elif msg_type == "message_delivered":
            await self._process_delivered(data)

        elif msg_type == "message_recall":
            await self._process_recall(data)

        elif msg_type == "message_edit":
            await self._process_edit(data)

        elif msg_type == "message_delete":
            await self._process_delete(data)

        elif msg_type == "contact_refresh":
            await self._process_contact_refresh(data)

        elif msg_type == "user_profile_update":
            await self._process_user_profile_update(data)

        elif msg_type == "group_profile_update":
            await self._process_group_profile_update(data)

        elif msg_type == "group_self_profile_update":
            await self._process_group_self_profile_update(data)

        else:
            logger.debug(f"Unknown message type: {msg_type}")
    
    async def _process_ack(self, data: dict) -> None:
        """Process message acknowledgment."""
        ack_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        msg_id = ack_data.get("msg_id") or data.get("msg_id", "")
        if ack_data.get("success") is not True:
            logger.warning("Ignoring non-success message_ack for %s; websocket failures use error events", msg_id)
            return
        ack_message_payload = ack_data.get("message")

        async with self._pending_lock:
            pending = self._pending_messages.pop(msg_id, None)

        fallback_message = pending.message if pending is not None else await self._db.get_message(msg_id)

        message = self._merge_ack_message(msg_id, ack_message_payload, fallback_message)
        if message is None:
            logger.warning("ACK received for unknown message: %s", msg_id)
            return

        message = await self._decrypt_message_for_display(message)

        if message.status in {MessageStatus.PENDING, MessageStatus.SENDING, MessageStatus.FAILED}:
            message.status = MessageStatus.SENT
            message.updated_at = datetime.now()

        await self._db.save_message(message)
        self._maybe_schedule_encrypted_media_prefetch(message)
        logger.info(f"Message ACK received: {msg_id}")

        await self._event_bus.emit(MessageEvent.ACK, {
            "message_id": msg_id,
            "message": message,
        })

    async def _process_error(self, data: dict) -> None:
        """Process one authoritative websocket error event."""
        error_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        msg_id = str(error_data.get("msg_id") or data.get("msg_id", "") or "")
        reason = str(error_data.get("message") or error_data.get("reason") or "WebSocket command failed")
        if not msg_id:
            logger.warning("WebSocket error without msg_id: %s", reason)
            return

        async with self._pending_lock:
            pending = self._pending_messages.pop(msg_id, None)

        fallback_message = pending.message if pending is not None else await self._db.get_message(msg_id)
        if fallback_message is None:
            logger.warning("WebSocket error received for unknown command: %s (%s)", msg_id, reason)
            return

        fallback_message.status = MessageStatus.FAILED
        fallback_message.updated_at = datetime.now()
        logger.warning("Message failed from websocket error: %s (%s)", msg_id, reason)

        await self._event_bus.emit(MessageEvent.FAILED, {
            "message_id": msg_id,
            "message": fallback_message,
            "reason": reason,
            "code": error_data.get("code"),
        })
        await self._db.save_message(fallback_message)
    
    async def _process_incoming_message(self, data: dict) -> None:
        """Process incoming chat message."""
        msg_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        payload = dict(msg_data)
        message_id = str(payload.get("message_id") or "")
        if not message_id:
            logger.warning("Incoming chat message missing canonical message_id; ignored")
            return

        payload.setdefault("message_id", message_id)
        message_created_at = msg_data.get("created_at") or data.get("created_at")
        payload.setdefault("timestamp", msg_data.get("timestamp") or message_created_at or data.get("timestamp") or time.time())
        payload.setdefault("created_at", message_created_at or data.get("timestamp"))
        payload.setdefault("updated_at", msg_data.get("updated_at") or message_created_at or data.get("updated_at") or data.get("timestamp"))
        payload.setdefault("status", msg_data.get("status") or MessageStatus.RECEIVED.value)

        message = self._normalize_loaded_message(
            payload,
            default_session_id=str(msg_data.get("session_id", "") or ""),
        )
        message = await self._decrypt_message_for_display(message)
        if not message.is_self and message.status in {MessageStatus.PENDING, MessageStatus.SENDING, MessageStatus.SENT}:
            message.status = MessageStatus.RECEIVED
        if not await self._reserve_incoming_message(message.message_id):
            logger.info("Concurrent duplicate incoming message ignored: %s", message.message_id)
            return

        processed = False
        try:
            existing_message = await self._db.get_message(message.message_id)
            if existing_message is not None:
                message = self._merge_local_encryption_cache(existing_message, message)
                # Websocket reconnects or duplicate server fan-out may deliver the
                # same chat payload more than once. Persist the freshest payload, but
                # do not re-emit a second RECEIVED event for the same logical message
                # because that would double-count unread state downstream.
                existing_version = existing_message.updated_at or existing_message.timestamp
                incoming_version = message.updated_at or message.timestamp
                should_refresh_existing = (
                    (incoming_version or existing_version) != existing_version
                    or existing_message.status != message.status
                    or existing_message.content != message.content
                    or existing_message.extra != message.extra
                )
                if should_refresh_existing:
                    await self._db.save_message(message)
                processed = True
                logger.info("Duplicate incoming message ignored: %s", message.message_id)
                return

            await self._db.save_message(message)
            self._maybe_schedule_encrypted_media_prefetch(message)

            await self._event_bus.emit(MessageEvent.RECEIVED, {
                "message": message,
            })

            processed = True
            logger.info(f"Message received: {message.message_id}")
        finally:
            await self._release_incoming_message(message.message_id, processed=processed)

    async def _reserve_incoming_message(self, message_id: str) -> bool:
        """Reserve one inbound message id so duplicate deliveries stay idempotent."""
        if not message_id:
            return True

        now = time.monotonic()
        async with self._incoming_message_guard:
            expired_ids = [
                existing_id
                for existing_id, seen_at in self._recent_incoming_message_ids.items()
                if now - seen_at > self._incoming_message_dedupe_ttl
            ]
            for existing_id in expired_ids:
                self._recent_incoming_message_ids.pop(existing_id, None)

            if message_id in self._incoming_message_inflight:
                return False
            if message_id in self._recent_incoming_message_ids:
                return False

            self._incoming_message_inflight.add(message_id)
            return True

    async def _release_incoming_message(self, message_id: str, *, processed: bool) -> None:
        """Release one inbound message reservation after processing finishes."""
        if not message_id:
            return

        async with self._incoming_message_guard:
            self._incoming_message_inflight.discard(message_id)
            if processed:
                self._recent_incoming_message_ids[message_id] = time.monotonic()

    @staticmethod
    def _coerce_read_int(value: Any) -> int:
        """Coerce read-receipt counters into safe non-negative integers."""
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _normalize_read_user_ids(value: Any) -> list[str]:
        """Normalize reader id payloads into a stable unique list."""
        if not isinstance(value, (list, tuple, set)):
            return []

        normalized: list[str] = []
        for item in value:
            user_id = str(item or "").strip()
            if user_id and user_id not in normalized:
                normalized.append(user_id)
        return normalized

    def _apply_read_metadata(self, sender_id: str, status: MessageStatus, extra: dict[str, Any]) -> tuple[MessageStatus, dict[str, Any]]:
        """Normalize read-receipt metadata and derive the UI-facing status for self messages."""
        read_by_user_ids = self._normalize_read_user_ids(extra.get("read_by_user_ids"))
        read_count = max(self._coerce_read_int(extra.get("read_count")), len(read_by_user_ids))
        read_target_count = self._coerce_read_int(extra.get("read_target_count"))

        extra["session_seq"] = self._coerce_read_int(extra.get("session_seq"))
        extra["read_by_user_ids"] = read_by_user_ids
        extra["read_count"] = read_count
        extra["read_target_count"] = read_target_count
        extra["is_read_by_me"] = bool(extra.get("is_read_by_me", sender_id == self._user_id))

        if sender_id == self._user_id and read_count > 0 and status in {MessageStatus.SENT, MessageStatus.DELIVERED, MessageStatus.READ}:
            status = MessageStatus.READ if read_target_count <= 1 else MessageStatus.DELIVERED

        return status, extra

    async def _get_current_user_context(self) -> dict[str, Any]:
        """Load the current authenticated user profile from persisted auth state."""
        if not self._db.is_connected:
            return {}

        try:
            stored_user = await self._db.get_app_state("auth.user_profile")
            if stored_user:
                parsed = json.loads(stored_user)
                if isinstance(parsed, dict):
                    return parsed
        except Exception as exc:
            logger.debug("Failed to load current user profile for message hydration: %s", exc)

        try:
            user_id = str(await self._db.get_app_state("auth.user_id") or "")
        except Exception:
            user_id = ""
        return {"id": user_id} if user_id else {}

    def _merge_sender_profile_into_extra(
        self,
        extra: dict[str, Any],
        sender_profile: Any,
    ) -> dict[str, Any]:
        """Merge one authoritative sender profile into message extra fields."""
        return merge_sender_profile_extra(extra, sender_profile if isinstance(sender_profile, dict) else None)

    async def _apply_current_user_sender_profile(self, message: ChatMessage) -> None:
        """Stamp one local self message with the current authenticated user profile."""
        if not message.sender_id:
            return

        current_user = await self._get_current_user_context()
        current_user_id = str(current_user.get("id", "") or "")
        if not current_user_id or message.sender_id != current_user_id:
            return

        message.extra = self._merge_sender_profile_into_extra(message.extra, current_user)

    async def _load_session_context(self, session_id: str):
        """Load one cached session for routing decisions such as private-chat E2EE."""
        if not session_id:
            return None
        try:
            return await self._db.get_session(session_id)
        except Exception as exc:
            logger.warning("Failed to load session context for %s: %s", session_id, exc)
            return None

    def _require_e2ee_service(self):
        """Lazily initialize the E2EE helper so non-encrypted code paths stay lightweight."""
        if self._e2ee_service is None:
            self._e2ee_service = get_e2ee_service()
        return self._e2ee_service

    def _should_encrypt_message(self, session, message_type: MessageType) -> bool:
        """Return whether one outbound text message should use E2EE."""
        if session is None:
            return False
        if bool(getattr(session, "is_ai_session", False)):
            return False
        if message_type != MessageType.TEXT:
            return False
        if not callable(getattr(session, "uses_e2ee", None)):
            return False
        return bool(session.uses_e2ee())

    @staticmethod
    def _resolve_group_member_ids(session, current_user_id: str) -> list[str]:
        member_ids: list[str] = []
        for member in list(getattr(session, "extra", {}).get("members") or []):
            member_id = str((member or {}).get("id") or "").strip() if isinstance(member, dict) else ""
            if member_id and member_id != current_user_id and member_id not in member_ids:
                member_ids.append(member_id)
        for participant_id in list(getattr(session, "participant_ids", []) or []):
            normalized_participant_id = str(participant_id or "").strip()
            if normalized_participant_id and normalized_participant_id != current_user_id and normalized_participant_id not in member_ids:
                member_ids.append(normalized_participant_id)
        return member_ids

    @staticmethod
    def _resolve_group_member_version(session, member_ids: list[str]) -> int:
        explicit_version = getattr(session, "extra", {}).get("group_member_version")
        try:
            if explicit_version is not None:
                return max(0, int(explicit_version))
        except (TypeError, ValueError):
            pass
        payload = json.dumps(sorted(member_ids), ensure_ascii=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return int(digest[:16], 16)

    async def _resolve_group_recipient_bundles(self, session) -> list[dict[str, Any]]:
        recipient_bundles: list[dict[str, Any]] = []
        seen_device_ids: set[str] = set()
        for member_id in self._resolve_group_member_ids(session, self._user_id):
            try:
                bundles = await self._require_e2ee_service().fetch_prekey_bundle(member_id)
            except Exception as exc:
                logger.warning("Failed to load group member E2EE bundle for %s: %s", member_id, exc)
                continue
            for bundle in bundles:
                device_id = str(dict(bundle or {}).get("device_id") or "").strip()
                if not device_id or device_id in seen_device_ids:
                    continue
                seen_device_ids.add(device_id)
                recipient_bundles.append(dict(bundle or {}))
        return recipient_bundles

    def _should_encrypt_attachment(self, session, message_type: MessageType) -> bool:
        """Return whether one outbound attachment should be uploaded in encrypted form."""
        if session is None:
            return False
        if bool(getattr(session, "is_ai_session", False)):
            return False
        if not callable(getattr(session, "uses_e2ee", None)) or not session.uses_e2ee():
            return False
        return message_type in {MessageType.FILE, MessageType.IMAGE, MessageType.VIDEO}

    def _resolve_direct_counterpart_id(self, session) -> str:
        """Resolve the other participant in one direct chat session."""
        participant_ids = [
            str(item or "").strip()
            for item in list(getattr(session, "participant_ids", []) or [])
            if str(item or "").strip()
        ]
        for participant_id in participant_ids:
            if participant_id != self._user_id:
                return participant_id

        session_extra = dict(getattr(session, "extra", {}) or {})
        counterpart_id = str(session_extra.get("counterpart_id", "") or "").strip()
        if counterpart_id and counterpart_id != self._user_id:
            return counterpart_id
        return ""

    @staticmethod
    def _pending_outbound_security_review(session, message_type: MessageType) -> dict[str, str] | None:
        """Return one local-only hold reason when outbound sends should wait for user review."""
        if session is None or message_type != MessageType.TEXT:
            return None
        if bool(getattr(session, "is_ai_session", False)):
            return None
        if not callable(getattr(session, "uses_e2ee", None)) or not session.uses_e2ee():
            return None
        if str(getattr(session, "session_type", "") or "").strip() != "direct":
            return None
        state = dict(getattr(session, "extra", {}).get("session_crypto_state") or {})
        if not bool(state.get("identity_review_blocking")):
            return None
        review_action = str(state.get("identity_review_action") or "trust_peer_identity").strip()
        return {
            "reason": "identity_review_required",
            "action_id": review_action or "trust_peer_identity",
            "headline": str(state.get("identity_status") or "identity_changed").strip() or "identity_changed",
        }

    @staticmethod
    def _assert_session_identity_safe_for_outbound(session) -> None:
        """Block new direct E2EE sends when the peer identity changed and requires re-trust."""
        if session is None:
            return
        if bool(getattr(session, "is_ai_session", False)):
            return
        if not callable(getattr(session, "uses_e2ee", None)) or not session.uses_e2ee():
            return
        if str(getattr(session, "session_type", "") or "").strip() != "direct":
            return
        state = dict(getattr(session, "extra", {}).get("session_crypto_state") or {})
        if not bool(state.get("identity_review_blocking")):
            return
        review_action = str(state.get("identity_review_action") or "trust_peer_identity").strip()
        raise RuntimeError(
            f"peer identity changed and must be reviewed before sending ({review_action})"
        )

    @staticmethod
    def _build_security_pending_extra(extra: dict[str, Any] | None, pending: dict[str, str] | None) -> dict[str, Any]:
        """Attach one local-only outbound security hold descriptor to message extra."""
        normalized = dict(extra or {})
        if not pending:
            normalized.pop("security_pending", None)
            return normalized
        normalized["security_pending"] = {
            "reason": str(pending.get("reason") or "identity_review_required"),
            "action_id": str(pending.get("action_id") or "trust_peer_identity"),
            "headline": str(pending.get("headline") or "identity_changed"),
            "queued_at": time.time(),
        }
        return normalized

    async def _prepare_outbound_encryption(
        self,
        *,
        session_id: str,
        content: str,
        message_type: MessageType,
        extra: dict[str, Any] | None,
    ) -> tuple[str, dict[str, Any]]:
        """Encrypt one outbound text message and keep local display metadata."""
        normalized_extra = dict(extra or {})
        session = await self._load_session_context(session_id)
        if not self._should_encrypt_message(session, message_type):
            return str(content or ""), normalized_extra

        session_type = str(getattr(session, "session_type", "") or "").strip()
        if session_type == "direct":
            self._assert_session_identity_safe_for_outbound(session)
            counterpart_id = self._resolve_direct_counterpart_id(session)
            if not counterpart_id:
                raise RuntimeError("direct session counterpart could not be resolved for E2EE")

            ciphertext, encryption = await self._require_e2ee_service().encrypt_text_for_user(counterpart_id, str(content or ""))
            normalized_extra["encryption"] = encryption
            return ciphertext, normalized_extra

        if session_type == "group":
            member_ids = self._resolve_group_member_ids(session, self._user_id)
            if not member_ids:
                raise RuntimeError("group session members could not be resolved for E2EE")
            recipient_bundles = await self._resolve_group_recipient_bundles(session)
            if not recipient_bundles:
                raise RuntimeError("group session has no registered recipient devices for E2EE")
            ciphertext, encryption = await self._require_e2ee_service().encrypt_text_for_group_session(
                session_id,
                str(content or ""),
                recipient_bundles,
                member_version=self._resolve_group_member_version(session, member_ids),
                owner_user_id=self._user_id,
            )
            normalized_extra["encryption"] = encryption
            return ciphertext, normalized_extra

        return str(content or ""), normalized_extra

    async def _decrypt_message_for_display(self, message: ChatMessage) -> ChatMessage:
        """Hydrate one encrypted message back into UI-friendly plaintext when possible."""
        encryption = dict((message.extra or {}).get("encryption") or {})
        if not encryption.get("enabled"):
            return await self._hydrate_attachment_metadata_for_display(message)

        encryption.setdefault("content_ciphertext", str(encryption.get("content_ciphertext") or message.content or ""))
        try:
            plaintext = await self._require_e2ee_service().decrypt_text_content(message.content, message.extra)
        except Exception as exc:
            logger.warning("Failed to decrypt message %s: %s", message.message_id, exc)
            encryption["decryption_error"] = str(exc)
            await self._apply_text_decryption_diagnostics(encryption, message.extra)
            message.extra["encryption"] = encryption
            if not message.content or message.content == encryption["content_ciphertext"]:
                message.content = tr("message.encrypted.placeholder", "[Encrypted message]")
            await self._emit_decryption_state_changed(message, encryption, attachment=False)
            return message

        if plaintext is None:
            await self._apply_text_decryption_diagnostics(encryption, message.extra)
            if not message.content or message.content == encryption["content_ciphertext"]:
                message.content = tr("message.encrypted.placeholder", "[Encrypted message]")
            message.extra["encryption"] = encryption
            await self._emit_decryption_state_changed(message, encryption, attachment=False)
            return message

        encryption["local_plaintext"] = self._require_e2ee_service().protect_local_plaintext(plaintext)
        encryption["local_plaintext_version"] = self._require_e2ee_service().LOCAL_PLAINTEXT_VERSION
        self._clear_local_decryption_diagnostics(encryption)
        message.extra["encryption"] = encryption
        message.content = plaintext
        await self._emit_decryption_state_changed(message, encryption, attachment=False)
        return await self._hydrate_attachment_metadata_for_display(message)

    async def _hydrate_attachment_metadata_for_display(self, message: ChatMessage) -> ChatMessage:
        """Hydrate encrypted attachment metadata into local-only display fields."""
        attachment_encryption = dict((message.extra or {}).get("attachment_encryption") or {})
        if not attachment_encryption.get("enabled"):
            return message

        try:
            metadata = await self._require_e2ee_service().decrypt_attachment_metadata(attachment_encryption)
        except Exception as exc:
            logger.warning("Failed to decrypt attachment metadata for %s: %s", message.message_id, exc)
            attachment_encryption["decryption_error"] = str(exc)
            await self._apply_attachment_decryption_diagnostics(attachment_encryption)
            message.extra["attachment_encryption"] = attachment_encryption
            message.extra.setdefault("name", tr("attachment.encrypted", "Encrypted attachment"))
            message.extra.setdefault("url", message.content)
            await self._emit_decryption_state_changed(message, attachment_encryption, attachment=True)
            return message

        if not metadata:
            await self._apply_attachment_decryption_diagnostics(attachment_encryption)
            message.extra["attachment_encryption"] = attachment_encryption
            message.extra.setdefault("name", tr("attachment.encrypted", "Encrypted attachment"))
            message.extra.setdefault("url", message.content)
            await self._emit_decryption_state_changed(message, attachment_encryption, attachment=True)
            return message

        attachment_encryption["local_metadata"] = self._require_e2ee_service().protect_local_plaintext(
            json.dumps(metadata, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        )
        attachment_encryption["local_plaintext_version"] = self._require_e2ee_service().LOCAL_PLAINTEXT_VERSION
        self._clear_local_decryption_diagnostics(attachment_encryption)
        message.extra["attachment_encryption"] = attachment_encryption
        await self._emit_decryption_state_changed(message, attachment_encryption, attachment=True)

        original_name = str(metadata.get("original_name") or "").strip()
        mime_type = str(metadata.get("mime_type") or "").strip()
        try:
            size_bytes = max(0, int(metadata.get("size_bytes") or 0))
        except (TypeError, ValueError):
            size_bytes = 0

        if original_name:
            message.extra["name"] = original_name
        message.extra["file_type"] = mime_type
        message.extra["size"] = size_bytes
        message.extra["url"] = message.content
        media = dict(message.extra.get("media") or {})
        media["url"] = message.content
        if original_name:
            media["original_name"] = original_name
        if mime_type:
            media["mime_type"] = mime_type
        media["size_bytes"] = size_bytes
        message.extra["media"] = media
        return message

    @staticmethod
    def _clear_local_decryption_diagnostics(envelope: dict[str, Any]) -> None:
        envelope.pop("decryption_error", None)
        envelope.pop("decryption_state", None)
        envelope.pop("recovery_action", None)
        envelope.pop("local_device_id", None)
        envelope.pop("target_device_id", None)
        envelope.pop("can_decrypt", None)

    async def _emit_decryption_state_changed(self, message: ChatMessage, envelope: dict[str, Any], *, attachment: bool) -> None:
        await self._event_bus.emit(
            MessageEvent.DECRYPTION_STATE_CHANGED,
            {
                "message_id": str(message.message_id or ""),
                "session_id": str(message.session_id or ""),
                "attachment": bool(attachment),
                "decryption_state": str(envelope.get("decryption_state") or "ready"),
                "recovery_action": str(envelope.get("recovery_action") or ""),
                "can_decrypt": bool(envelope.get("can_decrypt", True)),
                "local_device_id": str(envelope.get("local_device_id") or ""),
                "target_device_id": str(envelope.get("target_device_id") or ""),
                "message": message,
            },
        )

    async def _apply_text_decryption_diagnostics(self, encryption: dict[str, Any], extra: dict[str, Any] | None) -> None:
        state = await self._require_e2ee_service().describe_text_decryption_state(extra)
        self._store_local_decryption_diagnostics(encryption, state)

    async def _apply_attachment_decryption_diagnostics(self, attachment_encryption: dict[str, Any]) -> None:
        state = await self._require_e2ee_service().describe_attachment_decryption_state(attachment_encryption)
        self._store_local_decryption_diagnostics(attachment_encryption, state)

    @staticmethod
    def _store_local_decryption_diagnostics(envelope: dict[str, Any], state: dict[str, Any] | None) -> None:
        normalized_state = dict(state or {})
        state_name = str(normalized_state.get("state") or "").strip()
        if state_name:
            envelope["decryption_state"] = state_name
        else:
            envelope.pop("decryption_state", None)

        can_decrypt = normalized_state.get("can_decrypt")
        if can_decrypt is not None:
            envelope["can_decrypt"] = bool(can_decrypt)
        else:
            envelope.pop("can_decrypt", None)

        local_device_id = str(normalized_state.get("local_device_id") or "").strip()
        if local_device_id:
            envelope["local_device_id"] = local_device_id
        else:
            envelope.pop("local_device_id", None)

        target_device_id = str(normalized_state.get("target_device_id") or "").strip()
        if target_device_id:
            envelope["target_device_id"] = target_device_id
        else:
            envelope.pop("target_device_id", None)

        if normalized_state.get("reprovision_required"):
            envelope["recovery_action"] = "reprovision_device"
        elif state_name == "not_for_current_device":
            envelope["recovery_action"] = "switch_device"
        else:
            envelope.pop("recovery_action", None)

    async def prepare_attachment_upload(
        self,
        *,
        session_id: str,
        file_path: str,
        message_type: MessageType,
        fallback_name: str,
        fallback_size: int,
    ) -> tuple[str, dict[str, Any], Optional[str]]:
        """Prepare one attachment upload, optionally encrypting the file before transfer."""
        session = await self._load_session_context(session_id)
        if not self._should_encrypt_attachment(session, message_type):
            return file_path, {}, None

        session_type = str(getattr(session, "session_type", "") or "").strip()
        if session_type == "direct":
            self._assert_session_identity_safe_for_outbound(session)
            counterpart_id = self._resolve_direct_counterpart_id(session)
            if not counterpart_id:
                raise RuntimeError("direct session counterpart could not be resolved for attachment encryption")

            encrypted_upload = await self._require_e2ee_service().encrypt_attachment_for_user(
                counterpart_id,
                file_path,
                fallback_name=fallback_name,
                size_bytes=fallback_size,
            )
        elif session_type == "group":
            member_ids = self._resolve_group_member_ids(session, self._user_id)
            if not member_ids:
                raise RuntimeError("group session members could not be resolved for attachment encryption")
            recipient_bundles = await self._resolve_group_recipient_bundles(session)
            if not recipient_bundles:
                raise RuntimeError("group session has no registered recipient devices for attachment encryption")
            encrypted_upload = await self._require_e2ee_service().encrypt_attachment_for_group_session(
                session_id,
                file_path,
                recipient_bundles,
                fallback_name=fallback_name,
                size_bytes=fallback_size,
                member_version=self._resolve_group_member_version(session, member_ids),
                owner_user_id=self._user_id,
            )
        else:
            return file_path, {}, None
        return (
            encrypted_upload.upload_file_path,
            {"attachment_encryption": dict(encrypted_upload.attachment_encryption)},
            encrypted_upload.cleanup_file_path,
        )

    async def download_attachment(self, message_id: str) -> str:
        """Ensure one file attachment exists locally, downloading and decrypting it when needed."""
        normalized_message_id = str(message_id or "").strip()
        if not normalized_message_id:
            raise RuntimeError("message id is required")

        message = await self._db.get_message(normalized_message_id)
        if message is None:
            raise RuntimeError("message not found")
        if message.message_type not in {MessageType.FILE, MessageType.IMAGE, MessageType.VIDEO}:
            raise RuntimeError("message is not a downloadable attachment")

        local_path = str((message.extra or {}).get("local_path") or "").strip()
        if local_path and os.path.exists(local_path):
            return local_path

        current_task = asyncio.current_task()
        existing_task = self._media_prefetch_tasks.get(normalized_message_id)
        if existing_task is not None and existing_task is not current_task and not existing_task.done():
            await asyncio.shield(existing_task)
            refreshed_message = await self._db.get_message(normalized_message_id)
            if refreshed_message is not None:
                refreshed_local_path = str((refreshed_message.extra or {}).get("local_path") or "").strip()
                if refreshed_local_path and os.path.exists(refreshed_local_path):
                    return refreshed_local_path

        remote_source = self._attachment_remote_source(message)
        if not remote_source:
            raise RuntimeError("attachment download URL is unavailable")

        payload_bytes = await self._file_service.download_chat_attachment(remote_source)
        attachment_encryption = dict((message.extra or {}).get("attachment_encryption") or {})

        file_name = self._attachment_file_name(message)
        if attachment_encryption.get("enabled"):
            payload_bytes, metadata = await self._require_e2ee_service().decrypt_attachment_bytes(
                payload_bytes,
                attachment_encryption,
            )
            metadata_name = str(metadata.get("original_name") or "").strip()
            metadata_mime_type = str(metadata.get("mime_type") or "").strip()
            if metadata_name:
                file_name = metadata_name
                message.extra["name"] = metadata_name
            if metadata_mime_type:
                message.extra["file_type"] = metadata_mime_type

        target_path = self._attachment_download_path(message.message_id, file_name)
        with open(target_path, "wb") as file_handle:
            file_handle.write(payload_bytes)

        message.extra["local_path"] = target_path
        await self._db.save_message(message)
        return target_path

    @staticmethod
    def _should_prefetch_encrypted_media(message: ChatMessage) -> bool:
        """Return whether one message should download media in the background for inline preview."""
        if message.message_type not in {MessageType.IMAGE, MessageType.VIDEO}:
            return False
        attachment_encryption = dict((message.extra or {}).get("attachment_encryption") or {})
        if not attachment_encryption.get("enabled"):
            return False
        local_path = str((message.extra or {}).get("local_path") or "").strip()
        if local_path and os.path.exists(local_path):
            return False
        return bool(MessageManager._attachment_remote_source(message))

    def _maybe_schedule_encrypted_media_prefetch(self, message: ChatMessage) -> None:
        """Schedule one background media download so encrypted images/videos regain inline preview."""
        if not self._running or not self._should_prefetch_encrypted_media(message):
            return

        message_id = str(message.message_id or "").strip()
        if not message_id:
            return

        existing_task = self._media_prefetch_tasks.get(message_id)
        if existing_task is not None and not existing_task.done():
            return

        task = asyncio.create_task(self._prefetch_encrypted_media(message_id))
        self._media_prefetch_tasks[message_id] = task
        task.add_done_callback(lambda finished_task, msg_id=message_id: self._finalize_media_prefetch_task(msg_id, finished_task))

    def _finalize_media_prefetch_task(self, message_id: str, task: asyncio.Task) -> None:
        """Drop one completed prefetch task from local bookkeeping and log failures."""
        current_task = self._media_prefetch_tasks.get(message_id)
        if current_task is task:
            self._media_prefetch_tasks.pop(message_id, None)

        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("Encrypted media prefetch failed for %s: %s", message_id, exc)

    async def _prefetch_encrypted_media(self, message_id: str) -> None:
        """Download and decrypt one encrypted image/video, then notify the UI to refresh it."""
        local_path = await self.download_attachment(message_id)
        if not local_path:
            return

        message = await self._db.get_message(message_id)
        if message is None:
            return

        await self._event_bus.emit(MessageEvent.MEDIA_READY, {
            "message_id": message_id,
            "message": message,
            "session_id": message.session_id,
        })

    @staticmethod
    def _attachment_remote_source(message: ChatMessage) -> str:
        """Return the best remote URL/path for one stored attachment message."""
        extra = dict(message.extra or {})
        return str(extra.get("url") or message.content or "").strip()

    @staticmethod
    def _attachment_file_name(message: ChatMessage) -> str:
        """Return one safe attachment filename for local download storage."""
        extra = dict(message.extra or {})
        preferred_name = str(extra.get("name") or "").strip()
        if preferred_name:
            candidate = os.path.basename(preferred_name)
        else:
            source = str(extra.get("url") or message.content or "").strip().split("?", 1)[0].rstrip("/\\")
            candidate = os.path.basename(source) or "attachment.bin"

        sanitized = "".join(
            character if character not in '<>:"/\\|?*' else "_"
            for character in candidate
        ).strip(" .")
        return sanitized or "attachment.bin"

    @staticmethod
    def _attachment_download_path(message_id: str, file_name: str) -> str:
        """Return one stable local cache path for a downloaded attachment."""
        downloads_dir = os.path.join(tempfile.gettempdir(), "assistim_downloads")
        os.makedirs(downloads_dir, exist_ok=True)
        return os.path.join(downloads_dir, f"{str(message_id or '').strip() or 'attachment'}_{file_name}")

    def _merge_local_encryption_cache(self, existing_message: ChatMessage | None, incoming_message: ChatMessage) -> ChatMessage:
        """Preserve local-only decrypted plaintext when a remote payload refreshes one encrypted message."""
        if existing_message is None:
            return incoming_message

        existing_encryption = dict((existing_message.extra or {}).get("encryption") or {})
        incoming_encryption = dict((incoming_message.extra or {}).get("encryption") or {})
        local_plaintext = str(existing_encryption.get("local_plaintext") or "").strip()
        if not incoming_encryption.get("enabled") or not local_plaintext or incoming_encryption.get("local_plaintext"):
            return incoming_message

        incoming_encryption["local_plaintext"] = local_plaintext
        incoming_encryption["local_plaintext_version"] = str(
            existing_encryption.get("local_plaintext_version")
            or incoming_encryption.get("local_plaintext_version")
            or self._require_e2ee_service().LOCAL_PLAINTEXT_VERSION
        )
        incoming_message.extra["encryption"] = incoming_encryption
        if existing_message.content and incoming_message.content == tr("message.encrypted.placeholder", "[Encrypted message]"):
            incoming_message.content = existing_message.content

        existing_attachment = dict((existing_message.extra or {}).get("attachment_encryption") or {})
        incoming_attachment = dict((incoming_message.extra or {}).get("attachment_encryption") or {})
        local_metadata = str(existing_attachment.get("local_metadata") or "").strip()
        if incoming_attachment.get("enabled") and local_metadata and not incoming_attachment.get("local_metadata"):
            incoming_attachment["local_metadata"] = local_metadata
            incoming_attachment["local_plaintext_version"] = str(
                existing_attachment.get("local_plaintext_version")
                or incoming_attachment.get("local_plaintext_version")
                or self._require_e2ee_service().LOCAL_PLAINTEXT_VERSION
            )
            incoming_message.extra["attachment_encryption"] = incoming_attachment
            for field_name in ("name", "file_type", "size", "url", "media"):
                if field_name in existing_message.extra and field_name not in incoming_message.extra:
                    incoming_message.extra[field_name] = existing_message.extra[field_name]
        return incoming_message

    @staticmethod
    def _transport_content_for_message(message: ChatMessage) -> str:
        """Return the canonical websocket payload content for one message object."""
        encryption = dict((message.extra or {}).get("encryption") or {})
        ciphertext = str(encryption.get("content_ciphertext") or "").strip()
        if encryption.get("enabled") and ciphertext:
            return ciphertext
        return str(message.content or "")

    @staticmethod
    def _drop_encryption_state(message: ChatMessage) -> None:
        """Remove encryption metadata once a message becomes a local notice instead of ciphertext."""
        updated_extra = dict(message.extra or {})
        updated_extra.pop("encryption", None)
        message.extra = updated_extra

    def _normalize_loaded_message(
        self,
        payload: dict[str, Any],
        *,
        default_session_id: str = "",
    ) -> ChatMessage:
        """Normalize one backend payload into a safe local message model."""
        data = dict(payload or {})
        sender_id = str(data.get("sender_id", "") or "")
        raw_type = str(data.get("message_type") or "text")
        raw_status = str(data.get("status") or ("sent" if sender_id == self._user_id else "received"))

        try:
            message_type = MessageType(raw_type)
        except ValueError:
            message_type = MessageType.TEXT

        try:
            status = MessageStatus(raw_status)
        except ValueError:
            status = MessageStatus.SENT if sender_id == self._user_id else MessageStatus.RECEIVED

        extra = dict(data.get("extra") or {})
        for key in ("session_seq", "read_count", "read_target_count", "read_by_user_ids", "is_read_by_me"):
            if key in data and key not in extra:
                extra[key] = data[key]

        session_type = str(data.get("session_type") or extra.get("session_type") or "").strip()
        if session_type in {"direct", "group", "ai"}:
            extra["session_type"] = session_type

        session_name = str(data.get("session_name") or extra.get("session_name") or "").strip()
        if session_name:
            extra["session_name"] = session_name

        session_avatar = data.get("session_avatar")
        if session_avatar:
            extra["session_avatar"] = session_avatar

        raw_participant_ids = data.get("participant_ids")
        if isinstance(raw_participant_ids, list):
            participant_ids = [
                value
                for value in dict.fromkeys(str(item or "").strip() for item in raw_participant_ids)
                if value
            ]
            if participant_ids:
                extra["participant_ids"] = participant_ids

        if "is_ai_session" in data and "is_ai_session" not in extra:
            extra["is_ai_session"] = bool(data.get("is_ai_session"))

        extra = self._merge_sender_profile_into_extra(extra, data.get("sender_profile"))
        status, extra = self._apply_read_metadata(sender_id, status, extra)

        content = str(data.get("content", "") or "")
        message = ChatMessage(
            message_id=str(data.get("message_id") or ""),
            session_id=str(data.get("session_id", "") or default_session_id),
            sender_id=sender_id,
            content=content,
            message_type=message_type,
            status=status,
            timestamp=data.get("timestamp") or data.get("created_at") or time.time(),
            updated_at=data.get("updated_at") or data.get("timestamp") or data.get("created_at") or time.time(),
            is_self=(sender_id == self._user_id) if sender_id else bool(data.get("is_self", False)),
            is_ai=bool(data.get("is_ai", False)),
            extra=extra,
        )
        if status == MessageStatus.RECALLED:
            message.extra.setdefault("recall_notice", resolve_recall_notice(message))
            message.content = str(message.extra.get("recall_notice", "") or "")
        return message

    async def _process_history_messages(self, data: dict) -> None:
        """Process history messages from sync response."""
        started = time.perf_counter()
        await asyncio.sleep(0)
        msg_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        messages_data = msg_data.get("messages", [])

        if not messages_data:
            logger.info("History message processing finished in %.1fms (0 messages)", (time.perf_counter() - started) * 1000)
            self._pending_sync_completion = {
                "count": 0,
                "messages": [],
                "skipped": 0,
            }
            return

        candidate_ids = [
            str(msg_item.get("message_id") or "")
            for msg_item in messages_data
            if isinstance(msg_item, dict) and str(msg_item.get("message_id") or "")
        ]
        query_started = time.perf_counter()
        existing_ids = await self._db.get_existing_message_ids(candidate_ids)
        logger.info(
            "History existing-id query finished in %.1fms (%d candidates)",
            (time.perf_counter() - query_started) * 1000,
            len(candidate_ids),
        )

        saved_messages: list[ChatMessage] = []
        skipped_count = 0

        for msg_item in messages_data:
            if not isinstance(msg_item, dict):
                skipped_count += 1
                continue

            message_id = str(msg_item.get("message_id") or "")
            if not message_id:
                skipped_count += 1
                logger.warning("History message missing canonical message_id; ignored")
                continue

            if message_id in existing_ids:
                skipped_count += 1
                continue

            saved_messages.append(
                await self._decrypt_message_for_display(
                    self._normalize_loaded_message(
                        msg_item,
                        default_session_id=str(msg_item.get("session_id", "") or ""),
                    )
                )
            )

        if saved_messages:
            await self._db.save_messages_batch(saved_messages)
            for message in saved_messages:
                self._maybe_schedule_encrypted_media_prefetch(message)

        self._pending_sync_completion = {
            "count": len(saved_messages),
            "messages": saved_messages,
            "skipped": skipped_count,
        }

        logger.info(f"History messages synced: {len(saved_messages)} new, {skipped_count} skipped")
        logger.info("History message processing finished in %.1fms", (time.perf_counter() - started) * 1000)

    async def _process_history_events(self, data: dict) -> None:
        """Replay a batch of offline mutation events in order."""
        msg_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        events = msg_data.get("events", [])
        if not isinstance(events, list):
            events = []

        for event_payload in events:
            if not isinstance(event_payload, dict):
                continue
            await self._handle_ws_message(event_payload)

        sync_summary = dict(self._pending_sync_completion or {})
        sync_summary.setdefault("count", 0)
        sync_summary.setdefault("messages", [])
        sync_summary.setdefault("skipped", 0)
        sync_summary["events_replayed"] = len(events)
        self._pending_sync_completion = None
        await self._event_bus.emit(MessageEvent.SYNC_COMPLETED, sync_summary)

    async def _process_typing(self, data: dict) -> None:
        """Process typing indicator."""
        payload = data.get("data", {})
        if not isinstance(payload, dict):
            return
        typing = payload.get("typing")
        if not isinstance(typing, bool):
            return
        session_id = payload.get("session_id", "")
        user_id = payload.get("user_id", "")

        await self._event_bus.emit(MessageEvent.TYPING, {
            "session_id": session_id,
            "user_id": user_id,
            "typing": typing,
        })

    async def _process_read(self, data: dict) -> None:
        """Process cumulative read-receipt cursor updates."""
        read_data = data.get("data", {})
        session_id = read_data.get("session_id", "")
        message_id = read_data.get("message_id", "")
        user_id = read_data.get("user_id", "")
        last_read_seq = self._coerce_read_int(read_data.get("last_read_seq"))

        changed_message_ids = await self._db.apply_read_receipt(session_id, user_id, message_id, last_read_seq)

        await self._event_bus.emit(MessageEvent.READ, {
            "session_id": session_id,
            "message_id": message_id,
            "user_id": user_id,
            "last_read_seq": last_read_seq,
            "changed_message_ids": changed_message_ids,
        })

    async def _process_delivered(self, data: dict) -> None:
        """Process delivery receipt for a sent message."""
        delivered_data = data.get("data", {})
        message_id = delivered_data.get("message_id", "")
        session_id = delivered_data.get("session_id", "")
        user_ids = delivered_data.get("user_ids", [])

        if not message_id:
            logger.warning("Delivery event missing canonical message_id; ignored")
            return

        message = await self._db.get_message(message_id)
        if message is None:
            return

        if message.status not in {MessageStatus.READ, MessageStatus.RECALLED, MessageStatus.FAILED}:
            message.status = MessageStatus.DELIVERED
            await self._db.save_message(message)

        await self._event_bus.emit(MessageEvent.DELIVERED, {
            "message_id": message_id,
            "session_id": session_id or message.session_id,
            "user_ids": user_ids,
            "message": message,
        })

    @staticmethod
    def _mutation_event_extra(event_data: dict) -> dict[str, Any]:
        extra = dict(event_data.get("extra") or {}) if isinstance(event_data.get("extra"), dict) else {}
        for key in ("session_seq", "read_count", "read_target_count", "read_by_user_ids", "is_read_by_me"):
            if key in event_data and key not in extra:
                extra[key] = event_data[key]
        return extra

    async def _process_recall(self, data: dict) -> None:
        """Process message recall."""
        recall_data = data.get("data", {})
        message_id = recall_data.get("message_id", "")
        session_id = recall_data.get("session_id", "")
        user_id = recall_data.get("user_id", "")

        if not message_id:
            logger.warning("Recall event missing canonical message_id; ignored")
            return

        message = await self._db.get_message(message_id)
        if message is None:
            message = ChatMessage(
                message_id=message_id,
                session_id=session_id,
                sender_id=user_id,
                content="",
                message_type=MessageType.TEXT,
                status=MessageStatus.SENT,
                timestamp=recall_data.get("updated_at") or time.time(),
                updated_at=recall_data.get("updated_at") or time.time(),
                is_self=(user_id == self._user_id) if user_id else False,
                extra=self._mutation_event_extra(recall_data),
            )

        notice = await self._build_recall_notice(message, user_id)
        updated_extra = dict(message.extra or {})
        updated_extra.setdefault("recalled_content", message.content)
        updated_extra["recall_notice"] = notice
        message.extra = updated_extra
        self._drop_encryption_state(message)
        message.status = MessageStatus.RECALLED
        message.content = notice
        message.updated_at = datetime.now()
        await self._db.save_message(message)

        await self._event_bus.emit(MessageEvent.RECALLED, {
            "message_id": message_id,
            "session_id": session_id or message.session_id,
            "user_id": user_id,
            "content": message.content,
            "message": message,
        })

        logger.info(f"Message recalled: {message_id}")

    async def _process_edit(self, data: dict) -> None:
        """Process message edit."""
        edit_data = data.get("data", {})
        message_id = edit_data.get("message_id", "")
        session_id = edit_data.get("session_id", "")
        user_id = edit_data.get("user_id", "")
        new_content = edit_data.get("content", "")

        if not message_id:
            logger.warning("Edit event missing canonical message_id; ignored")
            return

        message = await self._db.get_message(message_id)
        source_message = message or ChatMessage(
            message_id=message_id,
            session_id=session_id,
            sender_id=user_id,
            content="",
            message_type=MessageType.TEXT,
            status=MessageStatus.SENT,
            timestamp=edit_data.get("updated_at") or time.time(),
            updated_at=edit_data.get("updated_at") or time.time(),
            is_self=(user_id == self._user_id) if user_id else False,
            extra=self._mutation_event_extra(edit_data),
        )

        updated_message = ChatMessage(
            message_id=source_message.message_id,
            session_id=session_id or source_message.session_id,
            sender_id=source_message.sender_id,
            content=str(new_content or ""),
            message_type=source_message.message_type,
            status=MessageStatus.EDITED,
            timestamp=source_message.timestamp,
            updated_at=edit_data.get("updated_at") or datetime.now(),
            is_self=source_message.is_self,
            is_ai=source_message.is_ai,
            extra=dict(source_message.extra or {}),
        )
        incoming_extra = dict(edit_data.get("extra") or {}) if isinstance(edit_data.get("extra"), dict) else {}
        if incoming_extra:
            updated_message.extra.update(incoming_extra)
        updated_message = await self._decrypt_message_for_display(updated_message)
        if message is not None:
            updated_message = self._merge_local_encryption_cache(message, updated_message)
        await self._db.save_message(updated_message)

        await self._event_bus.emit(MessageEvent.EDITED, {
            "message_id": message_id,
            "session_id": session_id or updated_message.session_id,
            "user_id": user_id,
            "content": updated_message.content,
            "message": updated_message,
        })

        logger.info(f"Message edited: {message_id}")

    async def _process_delete(self, data: dict) -> None:
        """Process message deletion."""
        delete_data = data.get("data", {})
        message_id = delete_data.get("message_id", "")
        session_id = delete_data.get("session_id", "")
        user_id = delete_data.get("user_id", "")

        if not message_id:
            logger.warning("Delete event missing canonical message_id; ignored")
            return

        await self._db.delete_message(message_id)

        await self._event_bus.emit(MessageEvent.DELETED, {
            "message_id": message_id,
            "session_id": session_id,
            "user_id": user_id,
        })

        logger.info(f"Message deleted: {message_id}")

    async def _process_contact_refresh(self, data: dict) -> None:
        """Process realtime contact-domain mutations that require UI refresh."""
        payload = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        await self._event_bus.emit(
            ContactEvent.SYNC_REQUIRED,
            {
                "reason": str(payload.get("reason", "") or "contact_refresh"),
                "payload": dict(payload),
                "message": dict(data or {}),
            },
        )

    async def _process_user_profile_update(self, data: dict) -> None:
        """Apply one authoritative user-profile update across cached messages and UI listeners."""
        payload = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        session_id = str(payload.get("session_id", "") or "")
        user_id = str(payload.get("user_id", "") or "")
        profile = dict(payload.get("profile") or {}) if isinstance(payload.get("profile"), dict) else {}
        if not user_id or not profile:
            return

        changed_message_ids = await self._db.apply_sender_profile_update(session_id, user_id, profile)
        event_payload = {
            "session_id": session_id,
            "user_id": user_id,
            "profile": profile,
            "event_seq": int(payload.get("event_seq", 0) or 0),
            "changed_message_ids": changed_message_ids,
        }
        await self._event_bus.emit(MessageEvent.PROFILE_UPDATED, event_payload)
        await self._event_bus.emit(
            ContactEvent.SYNC_REQUIRED,
            {
                "reason": "user_profile_update",
                "payload": dict(event_payload),
                "message": dict(data or {}),
            },
        )

    async def _process_group_profile_update(self, data: dict) -> None:
        """Apply one shared group-profile update across session and contact views."""
        payload = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        session_id = str(payload.get("session_id", "") or "")
        group_id = str(payload.get("group_id", "") or payload.get("id", "") or "")
        if not session_id or not group_id:
            return

        event_payload = {
            "session_id": session_id,
            "group_id": group_id,
            "group": dict(payload),
            "event_seq": int(payload.get("event_seq", 0) or 0),
        }
        await self._event_bus.emit(MessageEvent.GROUP_UPDATED, event_payload)
        await self._event_bus.emit(
            ContactEvent.SYNC_REQUIRED,
            {
                "reason": "group_profile_update",
                "payload": dict(event_payload),
                "message": dict(data or {}),
            },
        )

    async def _process_group_self_profile_update(self, data: dict) -> None:
        """Apply one self-scoped group-profile update for the current user's other clients."""
        payload = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        session_id = str(payload.get("session_id", "") or "")
        group_id = str(payload.get("group_id", "") or "")
        if not session_id or not group_id:
            return

        event_payload = {
            "session_id": session_id,
            "group_id": group_id,
            "group_note": str(payload.get("group_note", "") or ""),
            "my_group_nickname": str(payload.get("my_group_nickname", "") or ""),
            "event_seq": int(payload.get("event_seq", 0) or 0),
        }
        await self._event_bus.emit(MessageEvent.GROUP_SELF_UPDATED, event_payload)
        await self._event_bus.emit(
            ContactEvent.SYNC_REQUIRED,
            {
                "reason": "group_self_profile_update",
                "payload": dict(event_payload),
                "message": dict(data or {}),
            },
        )

    async def send_message(
        self,
        session_id: str,
        content: str,
        message_type: MessageType = MessageType.TEXT,
        msg_id: Optional[str] = None,
        extra: Optional[dict] = None,
        existing_message: Optional[ChatMessage] = None,
    ) -> ChatMessage:
        """
        Send a message via queue.

        Args:
            session_id: Target session ID
            content: Message content
            message_type: Message type
            msg_id: Optional message ID
            extra: Additional fields (e.g., for file messages: name, size, url)

        Returns:
            The sent message
        """
        merged_extra = dict(extra or {})
        security_pending: dict[str, str] | None = None
        if existing_message is None:
            session = await self._load_session_context(session_id)
            security_pending = self._pending_outbound_security_review(session, message_type)
            if security_pending:
                message = ChatMessage(
                    message_id=msg_id or str(uuid.uuid4()),
                    session_id=session_id,
                    sender_id=self._user_id,
                    content=content,
                    message_type=message_type,
                    status=MessageStatus.AWAITING_SECURITY_CONFIRMATION,
                    timestamp=time.time(),
                    is_self=True,
                    extra=self._build_security_pending_extra(merged_extra, security_pending),
                )
                await self._apply_current_user_sender_profile(message)
                await self._db.save_message(message)
                await self._event_bus.emit(MessageEvent.SENT, {"message": message})
                logger.info("Queued local security-pending message: %s", message.message_id)
                return message

        transport_content = str(content or "")
        try:
            transport_content, merged_extra = await self._prepare_outbound_encryption(
                session_id=session_id,
                content=content,
                message_type=message_type,
                extra=merged_extra,
            )
        except Exception as exc:
            logger.warning("Failed to prepare outbound encryption for %s: %s", session_id, exc)
            if existing_message is None:
                failed_message = ChatMessage(
                    message_id=msg_id or str(uuid.uuid4()),
                    session_id=session_id,
                    sender_id=self._user_id,
                    content=content,
                    message_type=message_type,
                    status=MessageStatus.FAILED,
                    timestamp=time.time(),
                    is_self=True,
                    extra=merged_extra,
                )
                await self._apply_current_user_sender_profile(failed_message)
                await self._db.save_message(failed_message)
                await self._event_bus.emit(MessageEvent.SENT, {"message": failed_message})
                await self._event_bus.emit(
                    MessageEvent.FAILED,
                    {
                        "message_id": failed_message.message_id,
                        "message": failed_message,
                        "reason": str(exc),
                    },
                )
                return failed_message

            existing_message.status = MessageStatus.FAILED
            existing_message.updated_at = datetime.now()
            await self._db.save_message(existing_message)
            await self._event_bus.emit(
                MessageEvent.FAILED,
                {
                    "message_id": existing_message.message_id,
                    "message": existing_message,
                    "reason": str(exc),
                },
            )
            return existing_message

        if existing_message is None:
            if not msg_id:
                msg_id = str(uuid.uuid4())

            message = ChatMessage(
                message_id=msg_id,
                session_id=session_id,
                sender_id=self._user_id,
                content=content,
                message_type=message_type,
                status=MessageStatus.SENDING,
                timestamp=time.time(),
                is_self=True,
                extra=merged_extra,
            )
            await self._apply_current_user_sender_profile(message)

            await self._db.save_message(message)

            await self._event_bus.emit(MessageEvent.SENT, {
                "message": message,
            })
        else:
            message = existing_message
            message.session_id = session_id
            message.sender_id = self._user_id
            message.content = content
            message.message_type = message_type
            message.status = MessageStatus.SENDING
            message.updated_at = datetime.now()
            updated_extra = dict(message.extra or {})
            updated_extra.pop("security_pending", None)
            updated_extra.update(merged_extra)
            message.extra = updated_extra
            await self._apply_current_user_sender_profile(message)
            msg_id = message.message_id
            await self._db.save_message(message)
            await self._event_bus.emit(MessageEvent.SENT, {
                "message": message,
            })

        pending = self._build_pending_message(
            message,
            session_id,
            transport_content,
            message_type.value,
            message.extra,
        )
        async with self._pending_lock:
            self._pending_messages[msg_id] = pending

        try:
            await self._enqueue_pending_message(pending)
        except Exception as exc:
            async with self._pending_lock:
                self._pending_messages.pop(msg_id, None)
            logger.error("Failed to enqueue outbound message %s: %s", msg_id, exc)
            await self._finalize_pending_failure(pending, "Transport queue failure")

        logger.info(f"Message enqueued: {msg_id}")

        return message

    async def _collect_security_pending_messages(self, session_id: str, *, limit: int = 200) -> list[ChatMessage]:
        """Load local outbound messages that are waiting for security confirmation."""
        messages = await self._db.get_messages(session_id, limit=limit)
        return [
            message
            for message in messages
            if message.is_self and message.status == MessageStatus.AWAITING_SECURITY_CONFIRMATION
        ]

    async def release_security_pending_messages(self, session_id: str) -> dict[str, Any]:
        """Send one batch of locally held messages after the required security action succeeded."""
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise RuntimeError("session id is required")

        pending_messages = await self._collect_security_pending_messages(normalized_session_id)
        released_ids: list[str] = []
        failed_ids: list[str] = []
        for message in pending_messages:
            pending_extra = dict(message.extra or {})
            pending_extra.pop("security_pending", None)
            released = await self.send_message(
                session_id=normalized_session_id,
                content=message.content,
                message_type=message.message_type,
                existing_message=message,
                extra=pending_extra,
            )
            if released.status == MessageStatus.FAILED:
                failed_ids.append(released.message_id)
            else:
                released_ids.append(released.message_id)

        return {
            "session_id": normalized_session_id,
            "released": len(released_ids),
            "failed": len(failed_ids),
            "message_ids": released_ids,
            "failed_message_ids": failed_ids,
        }

    async def discard_security_pending_messages(self, session_id: str) -> dict[str, Any]:
        """Delete one batch of locally held messages that have not been sent yet."""
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise RuntimeError("session id is required")

        pending_messages = await self._collect_security_pending_messages(normalized_session_id)
        removed_ids: list[str] = []
        for message in pending_messages:
            await self._db.delete_message(message.message_id)
            removed_ids.append(message.message_id)
            await self._event_bus.emit(
                MessageEvent.DELETED,
                {
                    "message_id": message.message_id,
                    "session_id": normalized_session_id,
                },
            )

        return {
            "session_id": normalized_session_id,
            "removed": len(removed_ids),
            "message_ids": removed_ids,
        }

    async def create_local_message(
        self,
        session_id: str,
        content: str,
        message_type: MessageType = MessageType.TEXT,
        msg_id: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> ChatMessage:
        """Create and emit a local self message before remote upload/send completes."""
        if not msg_id:
            msg_id = str(uuid.uuid4())

        message = ChatMessage(
            message_id=msg_id,
            session_id=session_id,
            sender_id=self._user_id,
            content=content,
            message_type=message_type,
            status=MessageStatus.SENDING,
            timestamp=time.time(),
            is_self=True,
            extra=extra or {},
        )
        await self._apply_current_user_sender_profile(message)

        await self._db.save_message(message)
        await self._event_bus.emit(MessageEvent.SENT, {
            "message": message,
        })
        return message

    async def mark_message_failed(self, message: ChatMessage, reason: str = "Send failed") -> None:
        """Mark a local message as failed and notify the UI."""
        message.status = MessageStatus.FAILED
        message.updated_at = datetime.now()
        await self._db.save_message(message)
        await self._event_bus.emit(MessageEvent.FAILED, {
            "message_id": message.message_id,
            "message": message,
            "reason": reason,
        })
    
    async def send_typing(self, session_id: str, *, typing: bool = True) -> bool:
        """Send typing indicator."""
        return await self._conn_manager.send_typing(session_id, typing=typing)

    async def send_read_receipt(self, session_id: str, message_id: str) -> bool:
        """Send read receipt."""
        try:
            await self._chat_service.persist_read_receipt(session_id, message_id)
        except Exception as exc:
            logger.warning("Failed to persist read receipt for %s/%s: %s", session_id, message_id, exc)
            return False
        return True

    async def _build_recall_notice(self, message: ChatMessage, actor_user_id: str | None = None) -> str:
        """Build a viewer-specific recall notice for a message."""
        actor_id = str(actor_user_id or message.sender_id or "")
        extra = dict(message.extra or {})
        return build_recall_notice(
            is_self=bool(message.is_self or (actor_id and actor_id == self._user_id)),
            session_type=str(extra.get("session_type", "") or ""),
            sender_name=(
                str(extra.get("sender_name", "") or "").strip()
                or str(extra.get("sender_nickname", "") or "").strip()
                or str(extra.get("sender_username", "") or "").strip()
            ),
            sender_id=str(message.sender_id or actor_id or ""),
        )

    async def recall_message(self, message_id: str) -> tuple[bool, str]:
        """
        Recall a sent message.

        Args:
            message_id: Message ID to recall

        Returns:
            ``(success, reason)`` where reason is non-empty on failure.
        """
        if not message_id:
            logger.warning("Recall request missing canonical message_id; ignored")
            return False, tr("message.error.not_found", "Message not found")

        message = await self._db.get_message(message_id)

        if not message:
            logger.warning(f"Message not found for recall: {message_id}")
            return False, tr("message.error.not_found", "Message not found")

        if not message.is_self:
            logger.warning(f"Cannot recall other user's message: {message_id}")
            return False, tr("message.error.cannot_recall_other", "You can only recall your own messages")

        if message.status == MessageStatus.RECALLED:
            logger.warning(f"Message already recalled: {message_id}")
            return False, tr("message.error.already_recalled", "This message has already been recalled")

        try:
            await self._chat_service.recall_message(message_id)
        except Exception as exc:
            logger.error(f"Failed to send recall request: {message_id}, error: {exc}")
            return False, str(exc) or tr("chat.recall_failed", "Recall failed.")

        notice = await self._build_recall_notice(message, self._user_id)
        updated_extra = dict(message.extra or {})
        updated_extra.setdefault("recalled_content", message.content)
        updated_extra["recall_notice"] = notice
        message.extra = updated_extra
        self._drop_encryption_state(message)
        message.status = MessageStatus.RECALLED
        message.content = notice
        message.updated_at = datetime.now()
        await self._db.save_message(message)

        await self._event_bus.emit(MessageEvent.RECALLED, {
            "message_id": message_id,
            "session_id": message.session_id,
            "user_id": self._user_id,
            "content": message.content,
            "message": message,
        })
        logger.info(f"Message recall sent: {message_id}")
        return True, ""

    EDIT_TIME_LIMIT = 120  # 2 minutes in seconds

    async def edit_message(self, message_id: str, new_content: str) -> bool:
        """
        Edit a sent message.

        Args:
            message_id: Message ID to edit
            new_content: New message content

        Returns:
            True if edit request sent successfully
        """
        import time

        # Get message from database
        if not message_id:
            logger.warning("Edit request missing canonical message_id; ignored")
            return False

        message = await self._db.get_message(message_id)

        if not message:
            logger.warning(f"Message not found for edit: {message_id}")
            return False

        # Only can edit own messages
        if not message.is_self:
            logger.warning(f"Cannot edit other user's message: {message_id}")
            return False

        # Check if message can be edited
        if message.status == MessageStatus.RECALLED:
            logger.warning(f"Cannot edit recalled message: {message_id}")
            return False

        if message.status == MessageStatus.EDITED:
            logger.warning(f"Message already edited: {message_id}")
            return False

        # Check time limit (2 minutes)
        message_time = message.timestamp
        if isinstance(message_time, datetime):
            message_age = (datetime.now() - message_time).total_seconds()
        else:
            current_time = time.time()
            message_age = current_time - float(message_time or 0)

        if message_age > self.EDIT_TIME_LIMIT:
            logger.warning(f"Message edit time limit exceeded: {message_id}")
            return False

        outbound_content = str(new_content or "")
        outbound_extra: dict[str, Any] | None = None
        if self._require_e2ee_service().is_encrypted_extra(message.extra):
            existing_extra = dict(message.extra or {})
            existing_encryption = dict(existing_extra.get("encryption") or {})
            existing_extra.pop("encryption", None)
            try:
                encrypted_content, encrypted_extra = await self._prepare_outbound_encryption(
                    session_id=message.session_id,
                    content=new_content,
                    message_type=message.message_type,
                    extra=existing_extra,
                )
            except Exception as exc:
                logger.error(f"Failed to encrypt edit request: {message_id}, error: {exc}")
                return False
            updated_encryption = dict(encrypted_extra.get("encryption") or {})
            if not updated_encryption:
                updated_encryption = existing_encryption
            outbound_content = encrypted_content
            message.extra = {**existing_extra, **encrypted_extra}
            outbound_extra = sanitize_outbound_message_extra(message.extra)
        else:
            outbound_extra = None

        success = False
        try:
            await self._chat_service.edit_message(message_id, outbound_content, extra=outbound_extra)
            success = True
        except Exception as exc:
            logger.error(f"Failed to send edit request: {message_id}, error: {exc}")

        if success:
            # Optimistically update
            message.content = new_content
            message.status = MessageStatus.EDITED
            message.updated_at = datetime.now()
            await self._db.save_message(message)

            await self._event_bus.emit(MessageEvent.EDITED, {
                "message_id": message_id,
                "session_id": message.session_id,
                "user_id": self._user_id,
                "content": new_content,
                "message": message,
            })

            logger.info(f"Message edit sent: {message_id}")

        return success

    async def delete_message(self, message_id: str) -> bool:
        """Delete a message locally without affecting other participants."""
        if not message_id:
            logger.warning("Delete request missing canonical message_id; ignored")
            return False

        message = await self._db.get_message(message_id)

        if not message:
            logger.warning(f"Message not found for delete: {message_id}")
            return False

        await self._db.delete_message(message_id)
        logger.info(f"Message deleted locally: {message_id}")
        return True

    async def _ack_check_loop(self) -> None:
        """Periodically check for pending messages that need retry."""
        logger.debug("ACK check loop started")
        while self._running:
            try:
                await asyncio.sleep(2)
                if self._running:
                    await self._check_pending_messages()
            except asyncio.CancelledError:
                logger.debug("ACK check loop cancelled")
                break
            except RuntimeError as e:
                logger.error(f"ACK check runtime error: {e}")
                # Break on event loop errors to prevent infinite error loop
                break
            except Exception as e:
                logger.error(f"ACK check error: {e}")
    
    async def _check_pending_messages(self) -> None:
        """Check pending ACKs and resend timed-out messages using the same msg_id."""
        now = time.time()
        to_retry: list[PendingMessage] = []
        to_fail: list[PendingMessage] = []

        async with self._pending_lock:
            for msg_id, pending in list(self._pending_messages.items()):
                if not pending.awaiting_ack or pending.last_attempt_at <= 0:
                    continue
                if now - pending.last_attempt_at <= pending.ack_timeout:
                    continue

                pending.awaiting_ack = False
                pending.last_attempt_at = 0.0

                if pending.attempt_count < pending.max_attempts:
                    to_retry.append(pending)
                else:
                    removed = self._pending_messages.pop(msg_id, None)
                    if removed is not None:
                        to_fail.append(removed)

        for pending in to_retry:
            logger.warning(
                "Message ACK timeout, retrying attempt %s/%s: %s",
                pending.attempt_count + 1,
                pending.max_attempts,
                pending.message.message_id,
            )
            await self._enqueue_pending_message(pending)

        for pending in to_fail:
            logger.warning(f"Message ACK timeout exhausted retries: {pending.message.message_id}")
            await self._finalize_pending_failure(pending, "ACK timeout")
    
    async def retry_message(self, msg_id: str) -> bool:
        """
        Manually retry a failed message via queue.

        Args:
            msg_id: Message ID to retry

        Returns:
            True if retry initiated
        """
        message = await self._db.get_message(msg_id)

        if not message:
            logger.warning(f"Message not found for retry: {msg_id}")
            return False

        if message.status != MessageStatus.FAILED:
            logger.warning(f"Message not in failed state: {msg_id}")
            return False

        if self._needs_media_upload(message):
            upload_path = str(message.extra.get("local_path", "") or "")
            cleanup_upload_path: str | None = None
            try:
                upload_path, encryption_extra, cleanup_upload_path = await self.prepare_attachment_upload(
                    session_id=message.session_id,
                    file_path=upload_path,
                    message_type=message.message_type,
                    fallback_name=str(
                        message.extra.get("name")
                        or os.path.basename(upload_path)
                        or "upload.bin"
                    ),
                    fallback_size=int(message.extra.get("size") or 0),
                )
                if encryption_extra:
                    message.extra.update(encryption_extra)
                upload_result = await self._file_service.upload_chat_attachment(upload_path)
            except AppError as exc:
                logger.warning("Media retry upload failed: %s (%s)", msg_id, exc)
                return False
            except Exception as exc:
                logger.warning("Encrypted media retry upload failed: %s (%s)", msg_id, exc)
                return False
            finally:
                if cleanup_upload_path:
                    try:
                        os.unlink(cleanup_upload_path)
                    except OSError:
                        pass

            file_url = str(upload_result["url"])
            message.content = file_url
            duration_value = message.extra.get("duration")
            try:
                normalized_duration = int(duration_value) if duration_value is not None else None
            except (TypeError, ValueError):
                normalized_duration = None
            message.extra.update(
                build_attachment_extra(
                    upload_result,
                    local_path=str(message.extra.get("local_path", "") or ""),
                    fallback_name=str(
                        message.extra.get("name")
                        or message.extra.get("local_path", "").rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
                        or "upload.bin"
                    ),
                    fallback_size=int(message.extra.get("size") or 0),
                    uploading=False,
                    duration=normalized_duration,
                )
            )

        message.status = MessageStatus.SENDING
        message.updated_at = datetime.now()
        await self._db.save_message(message)

        pending = self._build_pending_message(
            message,
            message.session_id,
            self._transport_content_for_message(message),
            message.message_type.value,
            message.extra,
        )
        async with self._pending_lock:
            self._pending_messages[msg_id] = pending

        try:
            await self._enqueue_pending_message(pending)
        except Exception as exc:
            async with self._pending_lock:
                self._pending_messages.pop(msg_id, None)
            logger.error("Failed to enqueue retry message %s: %s", msg_id, exc)
            await self._finalize_pending_failure(pending, "Transport queue failure")
            return False

        await self._event_bus.emit(MessageEvent.SENT, {
            "message": message,
        })

        logger.info(f"Message re-enqueued for retry: {msg_id}")

        return True

    @staticmethod
    def _needs_media_upload(message: ChatMessage) -> bool:
        """Return whether a failed media message still needs HTTP upload before send."""
        if message.message_type not in {MessageType.IMAGE, MessageType.FILE, MessageType.VIDEO}:
            return False

        local_path = str(message.extra.get("local_path", "") or "")
        if not local_path:
            return False

        media = dict(message.extra.get("media") or {})
        remote_url = str(media.get("url") or message.extra.get("url", "") or "")
        if remote_url:
            return False

        content = (message.content or "").strip()
        return not content.startswith(("http://", "https://", "/uploads/"))

    @staticmethod
    def _message_needs_persist(existing: ChatMessage, incoming: ChatMessage) -> bool:
        return (
            existing.session_id != incoming.session_id
            or existing.sender_id != incoming.sender_id
            or existing.content != incoming.content
            or existing.message_type != incoming.message_type
            or existing.status != incoming.status
            or existing.is_self != incoming.is_self
            or existing.is_ai != incoming.is_ai
            or dict(existing.extra or {}) != dict(incoming.extra or {})
        )

    async def _fetch_remote_messages(
        self,
        session_id: str,
        limit: int,
        before_seq: Optional[int] = None,
    ) -> list[ChatMessage]:
        """Fetch one message page from the backend and persist it locally."""
        payload = await self._chat_service.fetch_messages(
            session_id,
            limit=limit,
            before_seq=before_seq,
        )
        remote_messages: list[ChatMessage] = []
        remote_items: list[dict] = []
        message_ids: list[str] = []

        for item in payload:
            if not isinstance(item, dict):
                continue

            message_id = str(item.get("message_id") or "")
            if not message_id:
                logger.warning("Remote history message missing canonical message_id; ignored")
                continue

            remote_items.append(item)
            message_ids.append(message_id)

        existing_messages = await self._db.get_messages_by_ids(message_ids)
        messages_to_save: list[ChatMessage] = []

        for item in remote_items:
            message_id = str(item.get("message_id") or "")
            existing_message = existing_messages.get(message_id)
            message = await self._decrypt_message_for_display(
                self._normalize_loaded_message(
                    item,
                    default_session_id=session_id,
                )
            )
            message = self._merge_local_encryption_cache(existing_message, message)
            remote_messages.append(message)
            if existing_message is None or self._message_needs_persist(existing_message, message):
                messages_to_save.append(message)

        if messages_to_save:
            await self._db.save_messages_batch(messages_to_save)
            for message in messages_to_save:
                self._maybe_schedule_encrypted_media_prefetch(message)

        return remote_messages

    async def get_messages(
        self,
        session_id: str,
        limit: int = 50,
        before_timestamp: Optional[float] = None,
        before_seq: Optional[int] = None,
        force_remote: bool = False,
    ) -> list[ChatMessage]:
        """Get messages from local cache, backfilling from the backend when needed."""
        messages = await self._db.get_messages(
            session_id,
            limit=limit,
            before_timestamp=before_timestamp,
        )

        should_fetch_remote = bool(force_remote) or before_seq is not None or len(messages) < limit
        if should_fetch_remote:
            try:
                remote_messages = await self._fetch_remote_messages(
                    session_id,
                    limit=limit,
                    before_seq=before_seq,
                )
            except Exception as exc:
                logger.warning("Remote history fetch failed for %s: %s", session_id, exc)
            else:
                if remote_messages:
                    messages = await self._db.get_messages(
                        session_id,
                        limit=limit,
                        before_timestamp=before_timestamp,
                    )

        return messages

    async def get_cached_messages(
        self,
        session_id: str,
        limit: int = 50,
        before_timestamp: Optional[float] = None,
    ) -> list[ChatMessage]:
        """Get one local-only message page without triggering remote backfill."""
        messages = await self._db.get_messages(
            session_id,
            limit=limit,
            before_timestamp=before_timestamp,
        )
        return messages

    @staticmethod
    def _empty_recovery_stats() -> dict[str, int]:
        return {
            "text": 0,
            "attachments": 0,
            "direct_text": 0,
            "group_text": 0,
            "direct_attachments": 0,
            "group_attachments": 0,
            "other": 0,
        }

    @classmethod
    def _accumulate_recovery_stats(cls, stats: dict[str, int], message: ChatMessage) -> None:
        if message.message_type == MessageType.TEXT:
            stats["text"] += 1
            encryption = dict((message.extra or {}).get("encryption") or {})
            scheme = str(encryption.get("scheme") or "").strip()
            if scheme == "group-sender-key-v1":
                stats["group_text"] += 1
            elif encryption:
                stats["direct_text"] += 1
            else:
                stats["other"] += 1
            return

        if message.message_type in {MessageType.FILE, MessageType.IMAGE, MessageType.VIDEO}:
            stats["attachments"] += 1
            attachment_encryption = dict((message.extra or {}).get("attachment_encryption") or {})
            scheme = str(attachment_encryption.get("scheme") or "").strip()
            if scheme == "aesgcm-file+group-sender-key-v1":
                stats["group_attachments"] += 1
            elif attachment_encryption:
                stats["direct_attachments"] += 1
            else:
                stats["other"] += 1
            return

        stats["other"] += 1

    async def recover_session_messages(
        self,
        session_id: str,
        *,
        limit: int = 500,
        remote_pages: int = 3,
    ) -> dict[str, Any]:
        """Retry local decryption for one session after device recovery."""
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise RuntimeError("session id is required")

        effective_limit = max(1, int(limit or 1))
        effective_remote_pages = max(0, int(remote_pages or 0))
        cached_messages = await self._db.get_messages(normalized_session_id, limit=effective_limit)
        updated_messages: list[ChatMessage] = []
        recovered_ids: list[str] = []
        recovered_seen: set[str] = set()
        cached_recovery_stats = self._empty_recovery_stats()

        for stored_message in cached_messages:
            candidate = ChatMessage(
                message_id=stored_message.message_id,
                session_id=stored_message.session_id,
                sender_id=stored_message.sender_id,
                content=stored_message.content,
                message_type=stored_message.message_type,
                status=stored_message.status,
                timestamp=stored_message.timestamp,
                updated_at=stored_message.updated_at,
                is_self=stored_message.is_self,
                is_ai=stored_message.is_ai,
                extra=deepcopy(dict(stored_message.extra or {})),
            )
            recovered = await self._decrypt_message_for_display(candidate)
            if recovered.content == stored_message.content and recovered.extra == stored_message.extra:
                continue
            updated_messages.append(recovered)
            self._accumulate_recovery_stats(cached_recovery_stats, recovered)
            message_id = str(recovered.message_id or "")
            if message_id and message_id not in recovered_seen:
                recovered_ids.append(message_id)
                recovered_seen.add(message_id)
            self._maybe_schedule_encrypted_media_prefetch(recovered)

        if updated_messages:
            await self._db.save_messages_batch(updated_messages)

        remote_messages: list[ChatMessage] = []
        remote_error = ""
        remote_pages_fetched = 0
        next_before_seq: int | None = None
        remote_recovery_stats = self._empty_recovery_stats()
        try:
            for _ in range(effective_remote_pages):
                page = await self._fetch_remote_messages(
                    normalized_session_id,
                    limit=effective_limit,
                    before_seq=next_before_seq,
                )
                if not page:
                    break
                remote_pages_fetched += 1
                remote_messages.extend(page)
                for message in page:
                    self._accumulate_recovery_stats(remote_recovery_stats, message)

                oldest_session_seq: int | None = None
                for message in page:
                    message_id = str(message.message_id or "")
                    if message_id and message_id not in recovered_seen:
                        recovered_ids.append(message_id)
                        recovered_seen.add(message_id)
                    message_seq = self._coerce_read_int(dict(message.extra or {}).get("session_seq"))
                    if message_seq <= 0:
                        continue
                    if oldest_session_seq is None or message_seq < oldest_session_seq:
                        oldest_session_seq = message_seq

                if oldest_session_seq is None:
                    break
                if next_before_seq is not None and oldest_session_seq >= next_before_seq:
                    break
                next_before_seq = oldest_session_seq
        except Exception as exc:
            remote_error = str(exc)
            logger.warning("Remote message recovery fetch failed for %s: %s", normalized_session_id, exc)

        result = {
            "session_id": normalized_session_id,
            "scanned": len(cached_messages),
            "updated": len(updated_messages),
            "message_ids": recovered_ids,
            "remote_fetched": len(remote_messages),
            "remote_pages_fetched": remote_pages_fetched,
            "recovery_stats": {
                "cached": cached_recovery_stats,
                "remote": remote_recovery_stats,
            },
        }
        if remote_error:
            result["remote_error"] = remote_error
        await self._event_bus.emit(MessageEvent.RECOVERED, {
            "session_id": normalized_session_id,
            "count": len(updated_messages),
            "message_ids": recovered_ids,
            "messages": updated_messages,
            "remote_messages": remote_messages,
            "recovery_stats": dict(result["recovery_stats"]),
            "result": dict(result),
        })
        return result
    async def close(self) -> None:
        """Close message manager."""
        logger.info("Closing message manager")

        self._running = False

        # Stop send queue
        if self._send_queue:
            await self._send_queue.stop()

        if self._ack_check_task:
            self._ack_check_task.cancel()
            try:
                await asyncio.wait_for(self._ack_check_task, timeout=self._close_timeout)
            except asyncio.TimeoutError:
                logger.warning("Timed out waiting for ACK check loop to stop")
            except asyncio.CancelledError:
                pass
            self._ack_check_task = None

        media_prefetch_tasks = list(self._media_prefetch_tasks.values())
        self._media_prefetch_tasks.clear()
        for task in media_prefetch_tasks:
            task.cancel()
        for task in media_prefetch_tasks:
            try:
                await asyncio.wait_for(task, timeout=self._close_timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        self._conn_manager.remove_message_listener(self._handle_ws_message)
        self._send_queue = None
        self._user_id = ""
        async with self._pending_lock:
            self._pending_messages.clear()
        async with self._incoming_message_guard:
            self._incoming_message_inflight.clear()
            self._recent_incoming_message_ids.clear()
        self._initialized = False
        global _message_manager
        if _message_manager is self:
            _message_manager = None

        logger.info("Message manager closed")


_message_manager: Optional[MessageManager] = None


def peek_message_manager() -> Optional[MessageManager]:
    """Return the existing message manager singleton if it was created."""
    return _message_manager


def get_message_manager() -> MessageManager:
    """Get the global message manager instance."""
    global _message_manager
    if _message_manager is None:
        _message_manager = MessageManager()
    return _message_manager
