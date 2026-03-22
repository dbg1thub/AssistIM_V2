"""
Message Controller Module

Controller for message list interactions.
"""

from typing import Optional

from client.core import logging
from client.core.logging import setup_logging
from client.managers.message_manager import get_message_manager
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
        self._msg_manager = get_message_manager()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize message controller."""
        if self._initialized:
            return

        self._initialized = True
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

    async def close(self) -> None:
        """Close the lightweight message controller state."""
        self._initialized = False


_message_controller: Optional[MessageController] = None


def peek_message_controller() -> Optional[MessageController]:
    """Return the existing message controller singleton if it was created."""
    return _message_controller


def get_message_controller() -> MessageController:
    """Get the global message controller instance."""
    global _message_controller
    if _message_controller is None:
        _message_controller = MessageController()
    return _message_controller
