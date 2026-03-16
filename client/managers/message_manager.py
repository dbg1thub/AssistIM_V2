"""
Message Manager Module

Manager for message handling, ACK processing, and caching.
"""
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.events.event_bus import get_event_bus
from client.managers.connection_manager import get_connection_manager
from client.models.message import ChatMessage, MessageStatus, MessageType
from client.network.http_client import get_http_client
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
    SYNC_COMPLETED = "message_sync_completed"
    RECALLED = "message_recalled"
    EDITED = "message_edited"
    DELETED = "message_deleted"


@dataclass
class PendingMessage:
    """Pending message waiting for ACK."""

    message: ChatMessage
    created_at: float
    retry_count: int = 0
    max_retries: int = 3
    ack_timeout: float = 10.0


@dataclass
class QueuedMessage:
    """Message in send queue."""

    message: ChatMessage
    session_id: str
    content: str
    message_type: str
    extra: dict
    retry_count: int = 0
    max_retries: int = 3


class MessageSendQueue:
    """
    Async message send queue with retry mechanism.

    Responsibilities:
        - Queue messages for sending
        - Process queue in background
        - Retry failed messages (max 3 times)
        - Update message status on success/failure
    """

    MAX_RETRY = 3
    RETRY_DELAY = 2.0  # seconds
    QUEUE_TIMEOUT = 30.0  # seconds

    def __init__(self, conn_manager, event_bus, db):
        self._conn_manager = conn_manager
        self._event_bus = event_bus
        self._db = db

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
                await self._worker_task
            except asyncio.CancelledError:
                pass

        logger.info("Message send queue stopped")

    async def enqueue(
        self,
        message: ChatMessage,
        session_id: str,
        content: str,
        message_type: str,
        extra: dict,
    ) -> None:
        """Add a message to the send queue."""
        queued = QueuedMessage(
            message=message,
            session_id=session_id,
            content=content,
            message_type=message_type,
            extra=extra,
            retry_count=0,
            max_retries=self.MAX_RETRY,
        )

        await asyncio.wait_for(
            self._queue.put(queued),
            timeout=self.QUEUE_TIMEOUT
        )

        logger.debug(f"Message enqueued: {message.message_id}")

    async def _worker(self) -> None:
        """Background worker that processes the queue."""
        logger.debug("Message send queue worker started")

        while self._running:
            try:
                # Wait for message with timeout
                queued = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0
                )

                await self._send_message(queued)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Queue worker error: {e}")

        logger.debug("Message send queue worker stopped")

    async def _send_message(self, queued: QueuedMessage) -> None:
        """Send a single message with retry logic."""
        message = queued.message

        try:
            success = await self._conn_manager.send_chat_message(
                session_id=queued.session_id,
                content=queued.content,
                msg_id=message.message_id,
                message_type=queued.message_type,
                extra=queued.extra,
            )

            if success:
                # Add to pending for ACK tracking
                logger.debug(f"Message sent, waiting for ACK: {message.message_id}")
            else:
                # Send failed, handle retry
                await self._handle_send_failure(queued)

        except Exception as e:
            logger.error(f"Send message error: {e}")
            await self._handle_send_failure(queued)

    async def _handle_send_failure(self, queued: QueuedMessage) -> None:
        """Handle send failure with retry."""
        message = queued.message
        queued.retry_count += 1

        if queued.retry_count < queued.max_retries:
            # Retry after delay
            logger.warning(
                f"Message send failed (retry {queued.retry_count}/{queued.max_retries}): "
                f"{message.message_id}"
            )

            await asyncio.sleep(self.RETRY_DELAY)
            await self._queue.put(queued)

        else:
            # Max retries exceeded, mark as failed
            logger.error(f"Message send failed after {queued.max_retries} retries: {message.message_id}")

            message.status = MessageStatus.FAILED
            await self._db.save_message(message)

            await self._event_bus.emit(MessageEvent.FAILED, {
                "message_id": message.message_id,
                "message": message,
                "reason": "Max retries exceeded",
            })


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

        # Send queue
        self._send_queue: Optional[MessageSendQueue] = None

        self._pending_messages: dict[str, PendingMessage] = {}
        self._pending_lock = asyncio.Lock()

        self._tasks: set[asyncio.Task] = set()
        self._ack_check_task: Optional[asyncio.Task] = None
        self._running = False
        self._initialized = False

        self._user_id: str = ""
        self._ack_timeout = 10.0
        self._max_retries = 3

    async def initialize(self) -> None:
        """Initialize message manager."""
        if self._initialized:
            logger.debug("Message manager already initialized")
            return

        # Initialize send queue
        self._send_queue = MessageSendQueue(
            self._conn_manager,
            self._event_bus,
            self._db
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
    
    async def _handle_ws_message(self, data: dict) -> None:
        """Handle incoming WebSocket message."""
        msg_type = data.get("type")
        msg_id = data.get("msg_id", "")

        if msg_type == "message_ack":
            await self._process_ack(data)

        elif msg_type == "chat_message":
            await self._process_incoming_message(data)

        elif msg_type == "history_messages":
            await self._process_history_messages(data)

        elif msg_type == "typing":
            await self._process_typing(data)

        elif msg_type == "read":
            await self._process_read(data)

        elif msg_type == "message_recall":
            await self._process_recall(data)

        elif msg_type == "message_edit":
            await self._process_edit(data)

        elif msg_type == "message_delete":
            await self._process_delete(data)

        else:
            logger.debug(f"Unknown message type: {msg_type}")
    
    async def _process_ack(self, data: dict) -> None:
        """Process message acknowledgment."""
        msg_id = data.get("data", {}).get("msg_id", "")
        success = data.get("data", {}).get("success", False)
        
        async with self._pending_lock:
            pending = self._pending_messages.pop(msg_id, None)
        
        if pending:
            if success:
                pending.message.status = MessageStatus.SENT
                logger.info(f"Message ACK received: {msg_id}")
                
                await self._event_bus.emit(MessageEvent.ACK, {
                    "message_id": msg_id,
                    "message": pending.message,
                })
            else:
                pending.message.status = MessageStatus.FAILED
                logger.warning(f"Message rejected: {msg_id}")
                
                await self._event_bus.emit(MessageEvent.FAILED, {
                    "message_id": msg_id,
                    "message": pending.message,
                    "reason": data.get("data", {}).get("reason", "Unknown"),
                })
            
            await self._db.save_message(pending.message)
    
    async def _process_incoming_message(self, data: dict) -> None:
        """Process incoming chat message."""
        msg_data = data.get("data", {})

        message = ChatMessage(
            message_id=data.get("msg_id", str(uuid.uuid4())),
            session_id=msg_data.get("session_id", ""),
            sender_id=msg_data.get("sender_id", ""),
            content=msg_data.get("content", ""),
            message_type=MessageType(msg_data.get("message_type", "text")),
            status=MessageStatus.RECEIVED,
            timestamp=time.time(),
            is_self=msg_data.get("sender_id") == self._user_id,
            extra=msg_data.get("extra", {}),
        )

        await self._db.save_message(message)

        await self._event_bus.emit(MessageEvent.RECEIVED, {
            "message": message,
        })

        logger.info(f"Message received: {message.message_id}")

    async def _process_history_messages(self, data: dict) -> None:
        """Process history messages from sync response."""
        msg_data = data.get("data", {})
        messages_data = msg_data.get("messages", [])

        if not messages_data:
            await self._event_bus.emit(MessageEvent.SYNC_COMPLETED, {
                "count": 0,
            })
            return

        saved_messages = []
        skipped_count = 0

        for msg_item in messages_data:
            msg_id = msg_item.get("msg_id")

            # Skip if message already exists (avoid duplicates)
            existing = await self._db.get_message(msg_id)
            if existing:
                skipped_count += 1
                continue

            message = ChatMessage(
                message_id=msg_id or str(uuid.uuid4()),
                session_id=msg_item.get("session_id", ""),
                sender_id=msg_item.get("sender_id", ""),
                content=msg_item.get("content", ""),
                message_type=MessageType(msg_item.get("message_type", "text")),
                status=MessageStatus.RECEIVED,
                timestamp=msg_item.get("timestamp", time.time()),
                is_self=msg_item.get("sender_id") == self._user_id,
                extra=msg_item.get("extra", {}),
            )

            await self._db.save_message(message)
            saved_messages.append(message)

            # Also emit RECEIVED event for each message (for session updates)
            await self._event_bus.emit(MessageEvent.RECEIVED, {
                "message": message,
            })

        await self._event_bus.emit(MessageEvent.SYNC_COMPLETED, {
            "count": len(saved_messages),
            "messages": saved_messages,
            "skipped": skipped_count,
        })

        logger.info(f"History messages synced: {len(saved_messages)} new, {skipped_count} skipped")
    
    async def _process_typing(self, data: dict) -> None:
        """Process typing indicator."""
        session_id = data.get("data", {}).get("session_id", "")
        user_id = data.get("data", {}).get("user_id", "")
        
        await self._event_bus.emit(MessageEvent.TYPING, {
            "session_id": session_id,
            "user_id": user_id,
        })
    
    async def _process_read(self, data: dict) -> None:
        """Process read receipt."""
        session_id = data.get("data", {}).get("session_id", "")
        message_id = data.get("data", {}).get("message_id", "")
        user_id = data.get("data", {}).get("user_id", "")

        await self._db.update_message_status(message_id, MessageStatus.READ)

        await self._event_bus.emit(MessageEvent.READ, {
            "session_id": session_id,
            "message_id": message_id,
            "user_id": user_id,
        })

    async def _process_recall(self, data: dict) -> None:
        """Process message recall."""
        recall_data = data.get("data", {})
        message_id = recall_data.get("msg_id", "")
        session_id = recall_data.get("session_id", "")
        user_id = recall_data.get("user_id", "")

        # Update message status in database
        await self._db.update_message_status(message_id, MessageStatus.RECALLED)

        # Get the original message
        message = await self._db.get_message(message_id)

        # Emit recall event
        await self._event_bus.emit(MessageEvent.RECALLED, {
            "message_id": message_id,
            "session_id": session_id,
            "user_id": user_id,
            "message": message,
        })

        logger.info(f"Message recalled: {message_id}")

    async def _process_edit(self, data: dict) -> None:
        """Process message edit."""
        edit_data = data.get("data", {})
        message_id = edit_data.get("msg_id", "")
        session_id = edit_data.get("session_id", "")
        user_id = edit_data.get("user_id", "")
        new_content = edit_data.get("content", "")

        # Update message content in database
        await self._db.update_message_content(message_id, new_content)
        await self._db.update_message_status(message_id, MessageStatus.EDITED)

        # Get the updated message
        message = await self._db.get_message(message_id)

        # Emit edit event
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
        message_id = delete_data.get("msg_id", "")
        session_id = delete_data.get("session_id", "")
        user_id = delete_data.get("user_id", "")

        await self._db.delete_message(message_id)

        await self._event_bus.emit(MessageEvent.DELETED, {
            "message_id": message_id,
            "session_id": session_id,
            "user_id": user_id,
        })

        logger.info(f"Message deleted: {message_id}")

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
            msg_id = message.message_id
            await self._db.save_message(message)
            await self._event_bus.emit(MessageEvent.SENT, {
                "message": message,
            })

        # Add to send queue
        await self._send_queue.enqueue(
            message=message,
            session_id=session_id,
            content=content,
            message_type=message_type.value,
            extra=message.extra,
        )

        # Add to pending for ACK tracking
        async with self._pending_lock:
            self._pending_messages[msg_id] = PendingMessage(
                message=message,
                created_at=time.time(),
                max_retries=self._max_retries,
                ack_timeout=self._ack_timeout,
            )

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
        return await self._conn_manager.send_read_ack(session_id, message_id)

    async def recall_message(self, message_id: str) -> tuple[bool, str]:
        """
        Recall a sent message.

        Args:
            message_id: Message ID to recall

        Returns:
            ``(success, reason)`` where reason is non-empty on failure.
        """
        message = await self._db.get_message(message_id)

        if not message:
            logger.warning(f"Message not found for recall: {message_id}")
            return False, "message not found"

        if not message.is_self:
            logger.warning(f"Cannot recall other user's message: {message_id}")
            return False, "cannot recall other user's message"

        if message.status == MessageStatus.RECALLED:
            logger.warning(f"Message already recalled: {message_id}")
            return False, "message already recalled"

        try:
            await get_http_client().post(f"/messages/{message_id}/recall")
        except Exception as exc:
            logger.error(f"Failed to send recall request: {message_id}, error: {exc}")
            return False, str(exc) or "recall failed"

        message.status = MessageStatus.RECALLED
        message.content = "[消息已撤回]"
        await self._db.save_message(message)

        await self._event_bus.emit(MessageEvent.RECALLED, {
            "message_id": message_id,
            "session_id": message.session_id,
            "user_id": self._user_id,
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
            await get_http_client().put(f"/messages/{message_id}", json={"content": new_content})
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
        """Delete a sent message via HTTP API and local cache."""
        message = await self._db.get_message(message_id)

        if not message:
            logger.warning(f"Message not found for delete: {message_id}")
            return False, "message not found"

        if not message.is_self:
            logger.warning(f"Cannot delete other user's message: {message_id}")
            return False, "cannot recall other user's message"

        try:
            await get_http_client().delete(f"/messages/{message_id}")
        except Exception as exc:
            logger.error(f"Failed to delete message: {message_id}, error: {exc}")
            return False, "message already recalled"

        await self._db.delete_message(message_id)
        logger.info(f"Message deleted: {message_id}")
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
        """Check and retry pending messages."""
        now = time.time()
        
        async with self._pending_lock:
            to_retry = []
            to_remove = []
            
            for msg_id, pending in self._pending_messages.items():
                if now - pending.created_at > pending.ack_timeout:
                    if pending.retry_count < pending.max_retries:
                        to_retry.append(pending)
                    else:
                        to_remove.append(msg_id)
            
            for msg_id in to_remove:
                pending = self._pending_messages.pop(msg_id)
                pending.message.status = MessageStatus.FAILED
                await self._db.save_message(pending.message)
                
                await self._event_bus.emit(MessageEvent.FAILED, {
                    "message_id": msg_id,
                    "message": pending.message,
                    "reason": "Timeout",
                })
                
                logger.warning(f"Message timeout: {msg_id}")
    
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
            upload_result = await get_http_client().upload_file(message.extra.get("local_path", ""))
            file_url = upload_result.get("url", "") if upload_result else ""
            if not file_url:
                logger.warning(f"Media retry upload failed: {msg_id}")
                return False

            message.content = file_url
            message.extra.update({
                "url": file_url,
                "name": message.extra.get("name") or message.extra.get("local_path", "").rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
                "file_type": upload_result.get("file_type", ""),
                "uploading": False,
            })

        message.status = MessageStatus.SENDING
        message.updated_at = datetime.now()
        await self._db.save_message(message)

        # Re-enqueue via send queue
        await self._send_queue.enqueue(
            message=message,
            session_id=message.session_id,
            content=message.content,
            message_type=message.message_type.value,
            extra=message.extra,
        )

        # Add to pending for ACK tracking
        async with self._pending_lock:
            self._pending_messages[msg_id] = PendingMessage(
                message=message,
                created_at=time.time(),
                max_retries=self._max_retries,
                ack_timeout=self._ack_timeout,
            )

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

        remote_url = str(message.extra.get("url", "") or "")
        if remote_url:
            return False

        content = (message.content or "").strip()
        return not content.startswith(("http://", "https://", "/uploads/"))

    async def get_messages(
        self,
        session_id: str,
        limit: int = 50,
        before_timestamp: Optional[float] = None,
    ) -> list[ChatMessage]:
        """Get messages from local cache."""
        return await self._db.get_messages(
            session_id,
            limit=limit,
            before_timestamp=before_timestamp,
        )
    
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
                await self._ack_check_task
            except asyncio.CancelledError:
                pass

        for task in self._tasks:
            if not task.done():
                task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._conn_manager.remove_message_listener(self._handle_ws_message)

        logger.info("Message manager closed")


_message_manager: Optional[MessageManager] = None


def get_message_manager() -> MessageManager:
    """Get the global message manager instance."""
    global _message_manager
    if _message_manager is None:
        _message_manager = MessageManager()
    return _message_manager
