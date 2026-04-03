"""
Chat Controller Module

Controller for chat UI interactions.
Receives UI input and coordinates with MessageManager.
"""

import asyncio
import os
import subprocess
from typing import Any, Optional

from client.core import logging
from client.core.exceptions import AppError
from client.core.logging import setup_logging
from client.managers.message_manager import get_message_manager
from client.managers.session_manager import get_session_manager
from client.models.message import ChatMessage, MessageType, Session, build_attachment_extra, infer_message_type_from_path
from client.services.file_service import get_file_service


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
        self._msg_manager = get_message_manager()
        self._session_manager = get_session_manager()
        self._file_service = get_file_service()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize chat controller."""
        if self._initialized:
            return

        await self._msg_manager.initialize()
        await self._session_manager.initialize()

        self._initialized = True
        logger.info("Chat controller initialized")

    def set_user_id(self, user_id: str) -> None:
        """Set current user ID."""
        self._msg_manager.set_user_id(user_id)

    async def refresh_sessions_snapshot(self) -> list[Session]:
        """Refresh the authoritative session snapshot after profile-affecting changes."""
        return await self._session_manager.refresh_remote_sessions()

    async def send_message(
        self,
        content: str,
        message_type: MessageType = MessageType.TEXT,
        extra: Optional[dict] = None,
    ) -> Optional[ChatMessage]:
        """Send a message in the current session."""
        session_id = self._session_manager.current_session_id

        if not session_id:
            logger.warning("No current session selected")
            return None

        if not content or not content.strip():
            logger.warning("Empty message content")
            return None

        normalized_extra = dict(extra or {})
        if message_type == MessageType.TEXT and normalized_extra.get("mentions"):
            normalized_extra["content"] = content.strip()

        message = await self._msg_manager.send_message(
            session_id=session_id,
            content=content.strip(),
            message_type=message_type,
            extra=normalized_extra,
        )

        await self._session_manager.add_message_to_session(
            session_id=session_id,
            message=message,
        )

        logger.info("Message sent: %s", message.message_id)
        return message

    async def send_file(
        self,
        file_path: str,
        session_id: Optional[str] = None,
    ) -> Optional[ChatMessage]:
        """Send an image, video, or file message in the current session."""
        session_id = session_id or self._session_manager.current_session_id

        if not session_id:
            logger.warning("No current session selected")
            return None

        if not file_path or not os.path.exists(file_path):
            logger.warning("File not found: %s", file_path)
            return None

        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        message_type = infer_message_type_from_path(file_path)
        duration = (
            await asyncio.to_thread(self._probe_video_duration, file_path)
            if message_type == MessageType.VIDEO
            else None
        )

        placeholder = await self._msg_manager.create_local_message(
            session_id=session_id,
            content=file_path,
            message_type=message_type,
            extra=build_attachment_extra(
                {},
                local_path=file_path,
                fallback_name=file_name,
                fallback_size=file_size,
                uploading=True,
                duration=duration,
            ),
        )

        await self._session_manager.add_message_to_session(
            session_id=session_id,
            message=placeholder,
        )

        try:
            upload_result = await self._file_service.upload_chat_attachment(file_path)
        except AppError as exc:
            reason = str(exc) or "Upload failed"
            logger.error("Failed to upload file %s: %s", file_path, exc)
            await self._msg_manager.mark_message_failed(placeholder, reason)
            return placeholder

        file_url = str(upload_result["url"])

        message = await self._msg_manager.send_message(
            session_id=session_id,
            content=file_url,
            message_type=message_type,
            existing_message=placeholder,
            extra=build_attachment_extra(
                upload_result,
                local_path=file_path,
                fallback_name=file_name,
                fallback_size=file_size,
                uploading=False,
                duration=duration,
            ),
        )

        logger.info("File message sent: %s, file: %s", message.message_id, file_name)
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
        """Send a message to a specific session."""
        if not content or not content.strip():
            logger.warning("Empty message content")
            return None

        normalized_extra = dict(extra or {})
        if message_type == MessageType.TEXT and normalized_extra.get("mentions"):
            normalized_extra["content"] = content.strip()

        message = await self._msg_manager.send_message(
            session_id=session_id,
            content=content.strip(),
            message_type=message_type,
            extra=normalized_extra,
        )

        await self._session_manager.add_message_to_session(
            session_id=session_id,
            message=message,
        )

        logger.info("Message sent to %s: %s", session_id, message.message_id)
        return message

    async def send_typing(self) -> None:
        """Send typing indicator for current session."""
        session_id = self._session_manager.current_session_id
        if session_id:
            await self._msg_manager.send_typing(session_id)

    async def send_read_receipt(self, message_id: str, session_id: Optional[str] = None) -> bool:
        """Send read receipt for a message."""
        session_id = session_id or self._session_manager.current_session_id
        if not session_id:
            return False
        return await self._msg_manager.send_read_receipt(session_id, message_id)

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

    async def load_cached_messages(
        self,
        session_id: str,
        limit: int = 50,
        before_timestamp: Optional[float] = None,
    ) -> list[ChatMessage]:
        """Load one local-only message page for optimistic first paint."""
        return await self._msg_manager.get_cached_messages(
            session_id=session_id,
            limit=limit,
            before_timestamp=before_timestamp,
        )

    async def select_session(self, session_id: str) -> None:
        """Select a session."""
        await self._session_manager.select_session(session_id)

    async def clear_current_session(self) -> None:
        """Clear current session selection."""
        await self._session_manager.clear_current_session()

    async def set_current_session_active(self, active: bool) -> None:
        """Mark whether the selected session is currently foreground-readable."""
        await self._session_manager.set_current_session_active(active)

    def get_current_session_id(self) -> Optional[str]:
        """Get current session ID."""
        return self._session_manager.current_session_id

    def get_current_session(self) -> Optional[Any]:
        """Get current session."""
        return self._session_manager.current_session

    def get_sessions(self) -> list[Any]:
        """Get all sessions."""
        return self._session_manager.sessions

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get one cached session by id."""
        for session in self._session_manager.sessions:
            if session.session_id == session_id:
                return session
        return None

    def find_direct_session(self, user_id: str) -> Optional[Session]:
        """Find an existing direct session for one user."""
        return self._session_manager.find_direct_session(user_id)

    async def ensure_session_loaded(
        self,
        session_id: str,
        *,
        fallback_name: str = "Session",
        avatar: str = "",
    ) -> Optional[Session]:
        """Ensure a remote session exists locally for the UI to open."""
        return await self._session_manager.ensure_remote_session(
            session_id,
            fallback_name=fallback_name,
            avatar=avatar,
        )

    async def ensure_direct_session(
        self,
        user_id: str,
        *,
        display_name: str = "",
        avatar: str = "",
    ) -> Optional[Session]:
        """Ensure a direct session exists for the given contact."""
        return await self._session_manager.ensure_direct_session(
            user_id,
            display_name=display_name,
            avatar=avatar,
        )

    async def refresh_session_preview(self, session_id: str) -> None:
        """Refresh the cached session preview from local storage."""
        await self._session_manager.refresh_session_preview(session_id)

    def get_total_unread(self) -> int:
        """Get total unread count."""
        return self._session_manager.get_total_unread_count()

    async def close(self) -> None:
        """Close chat controller."""
        logger.info("Closing chat controller")
        self._initialized = False
        logger.info("Chat controller closed")


_chat_controller: Optional[ChatController] = None


def peek_chat_controller() -> Optional[ChatController]:
    """Return the existing chat controller singleton if it was created."""
    return _chat_controller


def get_chat_controller() -> ChatController:
    """Get the global chat controller instance."""
    global _chat_controller
    if _chat_controller is None:
        _chat_controller = ChatController()
    return _chat_controller
