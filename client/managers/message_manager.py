"""
Message Manager Module

Manager for message handling, ACK processing, and caching.
"""
import asyncio
import json
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
from client.models.message import ChatMessage, MessageStatus, MessageType, build_attachment_extra, sanitize_outbound_message_extra
from client.services.chat_service import get_chat_service
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
            self._worker_task.cancel()
            try:
                await asyncio.wait_for(self._worker_task, timeout=self.STOP_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("Timed out waiting for message send queue worker to stop")
            except asyncio.CancelledError:
                pass
            self._worker_task = None

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

        while self._running:
            try:
                queued = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._send_message(queued)
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
        except Exception as e:
            logger.error(f"Send message error for {queued.message_id}: {e}")

        await self._on_send_result(queued, success)


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
        self._file_service = get_file_service()

        # Send queue
        self._send_queue: Optional[MessageSendQueue] = None

        self._pending_messages: dict[str, PendingMessage] = {}
        self._pending_lock = asyncio.Lock()
        self._incoming_message_guard = asyncio.Lock()
        self._incoming_message_inflight: set[str] = set()
        self._recent_incoming_message_ids: dict[str, float] = {}
        self._incoming_message_dedupe_ttl = 300.0

        self._ack_check_task: Optional[asyncio.Task] = None
        self._running = False
        self._initialized = False

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
            merged_extra = dict(fallback_message.extra or {})
            merged_extra.update(dict(normalized.get("extra") or {}))
            normalized["extra"] = merged_extra
        else:
            normalized.setdefault("sender_id", self._user_id)
            normalized.setdefault("is_self", True)

        normalized.setdefault("message_id", msg_id)
        return self._normalize_loaded_message(
            normalized,
            default_session_id=str(normalized.get("session_id", "") or ""),
        )
    
    async def _handle_ws_message(self, data: dict) -> None:
        """Handle incoming WebSocket message."""
        msg_type = data.get("type")

        if msg_type == "message_ack":
            await self._process_ack(data)

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

        else:
            logger.debug(f"Unknown message type: {msg_type}")
    
    async def _process_ack(self, data: dict) -> None:
        """Process message acknowledgment."""
        ack_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        msg_id = ack_data.get("msg_id") or data.get("msg_id", "")
        success = bool(ack_data.get("success", False))
        ack_message_payload = ack_data.get("message")

        async with self._pending_lock:
            pending = self._pending_messages.pop(msg_id, None)

        fallback_message = pending.message if pending is not None else await self._db.get_message(msg_id)

        if success:
            message = self._merge_ack_message(msg_id, ack_message_payload, fallback_message)
            if message is None:
                logger.warning("ACK received for unknown message: %s", msg_id)
                return

            await self._hydrate_message_sender_profile(message)

            if message.status in {MessageStatus.PENDING, MessageStatus.SENDING, MessageStatus.FAILED}:
                message.status = MessageStatus.SENT
                message.updated_at = datetime.now()

            await self._db.save_message(message)
            logger.info(f"Message ACK received: {msg_id}")

            await self._event_bus.emit(MessageEvent.ACK, {
                "message_id": msg_id,
                "message": message,
            })
            return

        if fallback_message is None:
            logger.warning("Message rejection received for unknown message: %s", msg_id)
            return

        fallback_message.status = MessageStatus.FAILED
        fallback_message.updated_at = datetime.now()
        logger.warning(f"Message rejected: {msg_id}")

        await self._event_bus.emit(MessageEvent.FAILED, {
            "message_id": msg_id,
            "message": fallback_message,
            "reason": ack_data.get("reason", "Unknown"),
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
        payload.setdefault("timestamp", msg_data.get("timestamp") or data.get("timestamp") or time.time())
        payload.setdefault("created_at", msg_data.get("created_at") or data.get("timestamp"))
        payload.setdefault("updated_at", msg_data.get("updated_at") or msg_data.get("created_at") or data.get("timestamp"))
        payload.setdefault("status", msg_data.get("status") or MessageStatus.RECEIVED.value)

        message = self._normalize_loaded_message(
            payload,
            default_session_id=str(msg_data.get("session_id", "") or ""),
        )
        await self._hydrate_message_sender_profile(message)
        if not message.is_self and message.status in {MessageStatus.PENDING, MessageStatus.SENDING, MessageStatus.SENT}:
            message.status = MessageStatus.RECEIVED
        if not await self._reserve_incoming_message(message.message_id):
            logger.info("Concurrent duplicate incoming message ignored: %s", message.message_id)
            return

        processed = False
        try:
            existing_message = await self._db.get_message(message.message_id)
            if existing_message is not None:
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

    def _default_recall_notice_for_sender(self, sender_id: str) -> str:
        """Return a safe fallback recall notice for history payloads."""
        if sender_id and sender_id == self._user_id:
            return tr("message.recalled.self", "You recalled a message")
        return tr("message.recalled.other", "The other side recalled a message")

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

    async def _get_session_member_context(
        self,
        session_id: str,
        sender_id: str,
        *,
        current_user_id: str = "",
    ) -> dict[str, Any]:
        """Resolve one sender profile from the cached session member list when possible."""
        if not self._db.is_connected or not session_id or not sender_id:
            return {}

        try:
            session = await self._db.get_session(session_id)
        except Exception as exc:
            logger.debug("Failed to load session %s for sender hydration: %s", session_id, exc)
            return {}

        if session is None:
            return {}

        for member in session.extra.get("members") or []:
            if str(member.get("id", "") or "") == sender_id:
                return dict(member)

        if session.session_type != "group" and sender_id != current_user_id:
            return {
                "id": sender_id,
                "nickname": session.name,
                "avatar": session.avatar,
            }

        return {}

    async def _hydrate_message_sender_profile(self, message: ChatMessage) -> bool:
        """Align one message sender snapshot with the latest local profile/session identity."""
        if not message.sender_id:
            return False

        extra = dict(message.extra or {})
        current_user = await self._get_current_user_context()
        current_user_id = str(current_user.get("id", "") or "")

        profile: dict[str, Any] = {}
        if message.is_self or (current_user_id and message.sender_id == current_user_id):
            profile = dict(current_user or {})
        else:
            profile = await self._get_session_member_context(
                message.session_id,
                message.sender_id,
                current_user_id=current_user_id,
            )
            if not profile and current_user_id and message.sender_id == current_user_id:
                profile = dict(current_user or {})

        if not profile:
            return False

        changed = False
        mapping = {
            "sender_avatar": profile.get("avatar", ""),
            "sender_gender": profile.get("gender", ""),
            "sender_username": profile.get("username", ""),
            "sender_nickname": profile.get("nickname", ""),
        }
        for key, raw_value in mapping.items():
            value = str(raw_value or "").strip()
            if not value:
                continue
            if str(extra.get(key, "") or "").strip() != value:
                extra[key] = value
                changed = True

        sender_name = (
            str(profile.get("nickname", "") or "").strip()
            or str(profile.get("username", "") or "").strip()
            or str(profile.get("name", "") or "").strip()
        )
        if sender_name and str(extra.get("sender_name", "") or "").strip() != sender_name:
            extra["sender_name"] = sender_name
            changed = True

        if changed:
            message.extra = extra
        return changed

    async def _hydrate_messages_sender_profiles(
        self,
        messages: list[ChatMessage],
        *,
        persist: bool = False,
    ) -> list[ChatMessage]:
        """Align a message batch with the latest local sender identity snapshots."""
        changed_messages: list[ChatMessage] = []
        for message in messages:
            if await self._hydrate_message_sender_profile(message):
                changed_messages.append(message)

        if persist and changed_messages:
            await self._db.save_messages_batch(changed_messages)

        return messages

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

        status, extra = self._apply_read_metadata(sender_id, status, extra)

        content = str(data.get("content", "") or "")
        if status == MessageStatus.RECALLED:
            extra.setdefault("recall_notice", self._default_recall_notice_for_sender(sender_id))
            content = extra["recall_notice"]

        return ChatMessage(
            message_id=str(data.get("message_id") or ""),
            session_id=str(data.get("session_id", "") or default_session_id),
            sender_id=sender_id,
            content=content,
            message_type=message_type,
            status=status,
            timestamp=data.get("timestamp") or data.get("created_at") or time.time(),
            updated_at=data.get("updated_at") or data.get("timestamp") or data.get("created_at") or time.time(),
            is_self=bool(data.get("is_self", sender_id == self._user_id)),
            is_ai=bool(data.get("is_ai", False)),
            extra=extra,
        )

    async def _process_history_messages(self, data: dict) -> None:
        """Process history messages from sync response."""
        started = time.perf_counter()
        await asyncio.sleep(0)
        msg_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        messages_data = msg_data.get("messages", [])

        if not messages_data:
            logger.info("History message processing finished in %.1fms (0 messages)", (time.perf_counter() - started) * 1000)
            await self._event_bus.emit(MessageEvent.SYNC_COMPLETED, {
                "count": 0,
            })
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
                self._normalize_loaded_message(
                    msg_item,
                    default_session_id=str(msg_item.get("session_id", "") or ""),
                )
            )

        await self._hydrate_messages_sender_profiles(saved_messages)

        if saved_messages:
            await self._db.save_messages_batch(saved_messages)

        await self._event_bus.emit(MessageEvent.SYNC_COMPLETED, {
            "count": len(saved_messages),
            "messages": saved_messages,
            "skipped": skipped_count,
        })

        logger.info(f"History messages synced: {len(saved_messages)} new, {skipped_count} skipped")
        logger.info("History message processing finished in %.1fms", (time.perf_counter() - started) * 1000)

    async def _process_history_events(self, data: dict) -> None:
        """Replay a batch of offline mutation events in order."""
        msg_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        events = msg_data.get("events", [])
        if not isinstance(events, list):
            return

        for event_payload in events:
            if not isinstance(event_payload, dict):
                continue
            await self._handle_ws_message(event_payload)

    async def _process_typing(self, data: dict) -> None:
        """Process typing indicator."""
        session_id = data.get("data", {}).get("session_id", "")
        user_id = data.get("data", {}).get("user_id", "")
        
        await self._event_bus.emit(MessageEvent.TYPING, {
            "session_id": session_id,
            "user_id": user_id,
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
            logger.warning(f"Message not found for recall event: {message_id}")
            return

        notice = await self._build_recall_notice(message, user_id)
        updated_extra = dict(message.extra or {})
        updated_extra.setdefault("recalled_content", message.content)
        updated_extra["recall_notice"] = notice
        message.extra = updated_extra
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

        await self._db.update_message_content(message_id, new_content)
        await self._db.update_message_status(message_id, MessageStatus.EDITED)

        message = await self._db.get_message(message_id)

        await self._event_bus.emit(MessageEvent.EDITED, {
            "message_id": message_id,
            "session_id": session_id,
            "user_id": user_id,
            "content": new_content,
            "message": message,
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
                extra=extra or {},
            )
            await self._hydrate_message_sender_profile(message)

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
            merged_extra = dict(message.extra)
            if extra:
                merged_extra.update(extra)
            message.extra = merged_extra
            await self._hydrate_message_sender_profile(message)
            msg_id = message.message_id
            await self._db.save_message(message)
            await self._event_bus.emit(MessageEvent.SENT, {
                "message": message,
            })

        pending = self._build_pending_message(
            message,
            session_id,
            content,
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
        await self._hydrate_message_sender_profile(message)

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
    
    async def send_typing(self, session_id: str) -> bool:
        """Send typing indicator."""
        return await self._conn_manager.send_typing(session_id)

    async def send_read_receipt(self, session_id: str, message_id: str) -> bool:
        """Send read receipt."""
        http_success = False
        try:
            await self._chat_service.persist_read_receipt(session_id, message_id)
            http_success = True
        except Exception as exc:
            logger.warning("Failed to persist read receipt for %s/%s: %s", session_id, message_id, exc)

        ws_success = await self._conn_manager.send_read_ack(session_id, message_id)
        return http_success or ws_success

    async def _build_recall_notice(self, message: ChatMessage, actor_user_id: str | None = None) -> str:
        """Build a viewer-specific recall notice for a message."""
        actor_id = str(actor_user_id or message.sender_id or "")
        if message.is_self or (actor_id and actor_id == self._user_id):
            return tr("message.recalled.self", "You recalled a message")
        return tr("message.recalled.other", "The other side recalled a message")

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

        success = False
        try:
            await self._chat_service.edit_message(message_id, new_content)
            success = True
        except Exception as exc:
            logger.error(f"Failed to send edit request: {message_id}, error: {exc}")

        if success:
            # Optimistically update
            message.content = new_content
            message.status = MessageStatus.EDITED
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
            try:
                upload_result = await self._file_service.upload_chat_attachment(message.extra.get("local_path", ""))
            except AppError as exc:
                logger.warning("Media retry upload failed: %s (%s)", msg_id, exc)
                return False

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
            message.content,
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

    async def _fetch_remote_messages(
        self,
        session_id: str,
        limit: int,
        before_timestamp: Optional[float] = None,
    ) -> list[ChatMessage]:
        """Fetch one message page from the backend and persist it locally."""
        payload = await self._chat_service.fetch_messages(
            session_id,
            limit=limit,
            before_timestamp=before_timestamp,
        )
        remote_messages: list[ChatMessage] = []

        for item in payload:
            if not isinstance(item, dict):
                continue

            message_id = str(item.get("message_id") or "")
            if not message_id:
                logger.warning("Remote history message missing canonical message_id; ignored")
                continue

            remote_messages.append(
                self._normalize_loaded_message(
                    item,
                    default_session_id=session_id,
                )
            )

        await self._hydrate_messages_sender_profiles(remote_messages)

        if remote_messages:
            await self._db.save_messages_batch(remote_messages)

        return remote_messages

    async def get_messages(
        self,
        session_id: str,
        limit: int = 50,
        before_timestamp: Optional[float] = None,
    ) -> list[ChatMessage]:
        """Get messages from local cache, backfilling from the backend when needed."""
        messages = await self._db.get_messages(
            session_id,
            limit=limit,
            before_timestamp=before_timestamp,
        )
        await self._hydrate_messages_sender_profiles(messages, persist=True)

        should_fetch_remote = before_timestamp is None or len(messages) < limit
        if should_fetch_remote:
            try:
                remote_messages = await self._fetch_remote_messages(
                    session_id,
                    limit=limit,
                    before_timestamp=before_timestamp,
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
        await self._hydrate_messages_sender_profiles(messages, persist=True)
        return messages

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

        self._conn_manager.remove_message_listener(self._handle_ws_message)
        self._send_queue = None
        async with self._pending_lock:
            self._pending_messages.clear()
        async with self._incoming_message_guard:
            self._incoming_message_inflight.clear()
            self._recent_incoming_message_ids.clear()
        self._initialized = False

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












