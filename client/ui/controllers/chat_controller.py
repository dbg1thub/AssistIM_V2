"""
Chat Controller Module

Controller for chat UI interactions.
Receives UI input and coordinates with MessageManager.
"""
import asyncio
import subprocess
import os
from typing import Any, Callable, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.events.event_bus import get_event_bus
from client.managers.message_manager import MessageEvent, get_message_manager
from client.managers.session_manager import SessionEvent, get_session_manager
from client.models.message import ChatMessage, MessageType, infer_message_type_from_path
from client.network.http_client import get_http_client

setup_logging()
logger = logging.get_logger(__name__)


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
            extra: Optional[dict] = None,
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
            extra=extra,
        )

        await self._session_manager.add_message_to_session(
            session_id=session_id,
            message=message,
        )

        logger.info(f"Message sent: {message.message_id}")

        return message

    async def send_file(
            self,
            file_path: str,
    ) -> Optional[ChatMessage]:
        """
        Send an image, video, or file message in current session.

        Args:
            file_path: Path to the file to send

        Returns:
            The sent message, or None if upload failed or no current session
        """
        session_id = self._session_manager.current_session_id

        if not session_id:
            logger.warning("No current session selected")
            return None

        if not file_path or not os.path.exists(file_path):
            logger.warning(f"File not found: {file_path}")
            return None

        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        message_type = infer_message_type_from_path(file_path)
        duration = self._probe_video_duration(file_path) if message_type == MessageType.VIDEO else None

        placeholder = await self._msg_manager.create_local_message(
            session_id=session_id,
            content=file_path,
            message_type=message_type,
            extra={
                "name": file_name,
                "size": file_size,
                "local_path": file_path,
                "uploading": True,
                **({"duration": duration} if duration is not None else {}),
            },
        )

        await self._session_manager.add_message_to_session(
            session_id=session_id,
            message=placeholder,
        )

        # Upload file via HTTP
        http_client = get_http_client()
        upload_result = await http_client.upload_file(file_path)

        if not upload_result:
            logger.error(f"Failed to upload file: {file_path}")
            await self._msg_manager.mark_message_failed(placeholder, "Upload failed")
            return placeholder

        # Get file info from upload result
        file_url = upload_result.get("url", "")

        if not file_url:
            logger.error(f"Upload result missing URL: {upload_result}")
            await self._msg_manager.mark_message_failed(placeholder, "Upload result missing URL")
            return placeholder

        message = await self._msg_manager.send_message(
            session_id=session_id,
            content=file_url,
            message_type=message_type,
            existing_message=placeholder,
            extra={
                "name": file_name,
                "size": file_size,
                "url": file_url,
                "local_path": file_path,
                "file_type": upload_result.get("file_type", ""),
                "uploading": False,
                **({"duration": duration} if duration is not None else {}),
            },
        )

        logger.info(f"File message sent: {message.message_id}, file: {file_name}")

        return message

    def _probe_video_duration(self, file_path: str) -> Optional[int]:
        """Probe local video duration in seconds using ffprobe when available."""
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    file_path,
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        if result.returncode != 0:
            return None

        try:
            return max(0, int(float((result.stdout or "").strip())))
        except (TypeError, ValueError):
            return None

    async def send_message_to(
            self,
            session_id: str,
            content: str,
            message_type: MessageType = MessageType.TEXT,
            extra: Optional[dict] = None,
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
            extra=extra,
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

    async def recall_message(self, message_id: str) -> tuple[bool, str]:
        """Recall a previously sent message."""
        return await self._msg_manager.recall_message(message_id)

    async def edit_message(self, message_id: str, new_content: str) -> bool:
        """Edit a previously sent message."""
        return await self._msg_manager.edit_message(message_id, new_content)

    async def delete_message(self, message_id: str) -> bool:
        """Delete a previously sent message."""
        return await self._msg_manager.delete_message(message_id)

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
