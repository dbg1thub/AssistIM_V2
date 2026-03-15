"""
Message Manager Module

Manager for message handling, ACK processing, and caching.
"""
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.events.event_bus import get_event_bus
from client.managers.connection_manager import get_connection_manager
from client.models.message import ChatMessage, MessageStatus, MessageType
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


@dataclass
class PendingMessage:
    """Pending message waiting for ACK."""
    
    message: ChatMessage
    created_at: float
    retry_count: int = 0
    max_retries: int = 3
    ack_timeout: float = 10.0


class MessageManager:
    """
    Manager for message lifecycle.
    
    Responsibilities:
        - Send messages via WebSocket
        - Handle incoming messages
        - Process ACK
        - Cache messages locally
        - Emit events to UI via EventBus
    """
    
    def __init__(self):
        self._event_bus = get_event_bus()
        self._conn_manager = get_connection_manager()
        self._db = get_database()
        
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
        
        logger.info("Message manager: adding listener")
        self._conn_manager.add_message_listener(self._handle_ws_message)
        
        logger.info("Message manager: setting running=True")
        self._running = True
        
        logger.info("Message manager: getting event loop")
        # Use get_event_loop() instead of get_running_loop() in qasync context
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
        
        elif msg_type == "typing":
            await self._process_typing(data)
        
        elif msg_type == "read":
            await self._process_read(data)
        
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
        )
        
        await self._db.save_message(message)
        
        await self._event_bus.emit(MessageEvent.RECEIVED, {
            "message": message,
        })
        
        logger.info(f"Message received: {message.message_id}")
    
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
    
    async def send_message(
        self,
        session_id: str,
        content: str,
        message_type: MessageType = MessageType.TEXT,
        msg_id: Optional[str] = None,
    ) -> ChatMessage:
        """
        Send a message.
        
        Args:
            session_id: Target session ID
            content: Message content
            message_type: Message type
            msg_id: Optional message ID
        
        Returns:
            The sent message
        """
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
        )
        
        await self._db.save_message(message)
        
        await self._event_bus.emit(MessageEvent.SENT, {
            "message": message,
        })
        
        success = await self._conn_manager.send_chat_message(
            session_id=session_id,
            content=content,
            msg_id=msg_id,
        )
        
        if success:
            async with self._pending_lock:
                self._pending_messages[msg_id] = PendingMessage(
                    message=message,
                    created_at=time.time(),
                    max_retries=self._max_retries,
                    ack_timeout=self._ack_timeout,
                )
        else:
            message.status = MessageStatus.FAILED
            await self._db.save_message(message)
            
            await self._event_bus.emit(MessageEvent.FAILED, {
                "message_id": msg_id,
                "message": message,
                "reason": "Failed to send",
            })
            
            logger.error(f"Failed to send message: {msg_id}")
        
        return message
    
    async def send_typing(self, session_id: str) -> bool:
        """Send typing indicator."""
        return await self._conn_manager.send_typing(session_id)
    
    async def send_read_receipt(self, session_id: str, message_id: str) -> bool:
        """Send read receipt."""
        return await self._conn_manager.send_read_ack(session_id, message_id)
    
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
        Manually retry a failed message.
        
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
        
        message.status = MessageStatus.SENDING
        await self._db.save_message(message)
        
        success = await self._conn_manager.send_chat_message(
            session_id=message.session_id,
            content=message.content,
            msg_id=msg_id,
        )
        
        if success:
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
            
            return True
        
        return False
    
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
