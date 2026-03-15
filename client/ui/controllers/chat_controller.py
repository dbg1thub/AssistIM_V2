"""
Chat Controller Module

Controller for chat UI interactions.
Receives UI input and coordinates with MessageManager.
"""
import asyncio
import logging
from typing import Any, Callable, Optional

from events.event_bus import get_event_bus
from managers.message_manager import MessageEvent, get_message_manager
from managers.session_manager import SessionEvent, get_session_manager
from models.message import ChatMessage, MessageType


logger = logging.getLogger(__name__)


class ChatController:
    """
    Controller for chat UI.
    
    Responsibilities:
        - Receive UI input
        - Call MessageManager to send messages
        - Handle message events
        - Coordinate session context
    """
    
    def __init__(self):
        self._event_bus = get_event_bus()
        self._msg_manager = get_message_manager()
        self._session_manager = get_session_manager()
        
        self._tasks: set[asyncio.Task] = set()
        self._handlers: dict[str, Callable] = {}
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize chat controller."""
        if self._initialized:
            return
        
        await self._msg_manager.initialize()
        await self._session_manager.initialize()
        
        await self._event_bus.subscribe(
            MessageEvent.SENT,
            self._on_message_sent,
        )
        await self._event_bus.subscribe(
            MessageEvent.RECEIVED,
            self._on_message_received,
        )
        await self._event_bus.subscribe(
            MessageEvent.ACK,
            self._on_message_ack,
        )
        await self._event_bus.subscribe(
            MessageEvent.FAILED,
            self._on_message_failed,
        )
        await self._event_bus.subscribe(
            MessageEvent.TYPING,
            self._on_typing,
        )
        
        self._initialized = True
        
        logger.info("Chat controller initialized")
    
    def set_user_id(self, user_id: str) -> None:
        """Set current user ID."""
        self._msg_manager.set_user_id(user_id)
    
    async def send_message(
        self,
        content: str,
        message_type: MessageType = MessageType.TEXT,
    ) -> Optional[ChatMessage]:
        """
        Send a message in current session.
        
        Args:
            content: Message content
            message_type: Message type
        
        Returns:
            The sent message, or None if no current session
        """
        session_id = self._session_manager.current_session_id
        
        if not session_id:
            logger.warning("No current session selected")
            return None
        
        if not content or not content.strip():
            logger.warning("Empty message content")
            return None
        
        message = await self._msg_manager.send_message(
            session_id=session_id,
            content=content.strip(),
            message_type=message_type,
        )
        
        await self._session_manager.add_message_to_session(
            session_id=session_id,
            message=message,
        )
        
        logger.info(f"Message sent: {message.message_id}")
        
        return message
    
    async def send_message_to(
        self,
        session_id: str,
        content: str,
        message_type: MessageType = MessageType.TEXT,
    ) -> Optional[ChatMessage]:
        """
        Send a message to a specific session.
        
        Args:
            session_id: Target session ID
            content: Message content
            message_type: Message type
        
        Returns:
            The sent message
        """
        if not content or not content.strip():
            logger.warning("Empty message content")
            return None
        
        message = await self._msg_manager.send_message(
            session_id=session_id,
            content=content.strip(),
            message_type=message_type,
        )
        
        await self._session_manager.add_message_to_session(
            session_id=session_id,
            message=message,
        )
        
        logger.info(f"Message sent to {session_id}: {message.message_id}")
        
        return message
    
    async def send_typing(self) -> None:
        """Send typing indicator for current session."""
        session_id = self._session_manager.current_session_id
        
        if not session_id:
            return
        
        await self._msg_manager.send_typing(session_id)
    
    async def send_read_receipt(self, message_id: str) -> None:
        """Send read receipt for a message."""
        session_id = self._session_manager.current_session_id
        
        if not session_id:
            return
        
        await self._msg_manager.send_read_receipt(session_id, message_id)
    
    async def retry_message(self, message_id: str) -> bool:
        """Retry sending a failed message."""
        return await self._msg_manager.retry_message(message_id)
    
    async def load_messages(
        self,
        session_id: str,
        limit: int = 50,
        before_timestamp: Optional[float] = None,
    ) -> list[ChatMessage]:
        """Load messages for a session."""
        return await self._msg_manager.get_messages(
            session_id=session_id,
            limit=limit,
            before_timestamp=before_timestamp,
        )
    
    async def load_more_messages(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[ChatMessage]:
        """Load older messages for a session."""
        messages = await self._msg_manager.get_messages(
            session_id=session_id,
            limit=limit,
        )
        
        return list(reversed(messages))
    
    async def select_session(self, session_id: str) -> None:
        """Select a session."""
        await self._session_manager.select_session(session_id)
    
    async def clear_current_session(self) -> None:
        """Clear current session selection."""
        await self._session_manager.clear_current_session()
    
    def get_current_session_id(self) -> Optional[str]:
        """Get current session ID."""
        return self._session_manager.current_session_id
    
    def get_current_session(self) -> Optional[Any]:
        """Get current session."""
        return self._session_manager.current_session
    
    def get_sessions(self) -> list[Any]:
        """Get all sessions."""
        return self._session_manager.sessions
    
    def get_total_unread(self) -> int:
        """Get total unread count."""
        return self._session_manager.get_total_unread_count()
    
    def _on_message_sent(self, data: dict) -> None:
        """Handle message sent event."""
        handler = self._handlers.get("message_sent")
        if handler:
            try:
                handler(data)
            except Exception as e:
                logger.error(f"Handler error: {e}")
    
    def _on_message_received(self, data: dict) -> None:
        """Handle message received event."""
        handler = self._handlers.get("message_received")
        if handler:
            try:
                handler(data)
            except Exception as e:
                logger.error(f"Handler error: {e}")
    
    def _on_message_ack(self, data: dict) -> None:
        """Handle message ACK event."""
        handler = self._handlers.get("message_ack")
        if handler:
            try:
                handler(data)
            except Exception as e:
                logger.error(f"Handler error: {e}")
    
    def _on_message_failed(self, data: dict) -> None:
        """Handle message failed event."""
        handler = self._handlers.get("message_failed")
        if handler:
            try:
                handler(data)
            except Exception as e:
                logger.error(f"Handler error: {e}")
    
    def _on_typing(self, data: dict) -> None:
        """Handle typing event."""
        handler = self._handlers.get("typing")
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
    
    async def close(self) -> None:
        """Close chat controller."""
        logger.info("Closing chat controller")
        
        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        self._handlers.clear()
        
        logger.info("Chat controller closed")


_chat_controller: Optional[ChatController] = None


def get_chat_controller() -> ChatController:
    """Get the global chat controller instance."""
    global _chat_controller
    if _chat_controller is None:
        _chat_controller = ChatController()
    return _chat_controller
