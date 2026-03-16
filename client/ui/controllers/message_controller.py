"""
Message Controller Module

Controller for message list interactions.
"""

from typing import Any, Callable, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.events.event_bus import get_event_bus
from client.managers.message_manager import MessageEvent, get_message_manager
from client.models.message import ChatMessage, MessageType

setup_logging()
logger = logging.get_logger(__name__)


class MessageController:
    """
    Controller for message list.

    Responsibilities:
        - Handle message sending
        - Handle message loading
        - Coordinate with MessageManager
    """

    def __init__(self):
        self._event_bus = get_event_bus()
        self._msg_manager = get_message_manager()
        self._handlers: dict[str, Callable] = {}

    async def initialize(self) -> None:
        """Initialize message controller."""
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
        logger.info("Message controller initialized")

    async def send_message(
        self,
        session_id: str,
        content: str,
        message_type: MessageType = MessageType.TEXT,
    ) -> Optional[ChatMessage]:
        """Send a message."""
        message = await self._msg_manager.send_message(
            session_id=session_id,
            content=content,
            message_type=message_type,
        )
        logger.info(f"Message sent: {message.message_id if message else None}")
        return message

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

    async def retry_message(self, message_id: str) -> bool:
        """Retry sending a failed message."""
        return await self._msg_manager.retry_message(message_id)

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

    def set_handler(self, event: str, handler: Callable) -> None:
        """Set event handler."""
        self._handlers[event] = handler

    def remove_handler(self, event: str) -> None:
        """Remove event handler."""
        self._handlers.pop(event, None)


_message_controller: Optional[MessageController] = None


def get_message_controller() -> MessageController:
    """Get the global message controller instance."""
    global _message_controller
    if _message_controller is None:
        _message_controller = MessageController()
    return _message_controller
