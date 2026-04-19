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
from client.core.config_backend import get_config
from client.core.exceptions import AppError
from client.core.logging import setup_logging
from client.managers.call_manager import get_call_manager
from client.managers.conversation_summary_manager import get_conversation_summary_manager
from client.managers.message_manager import MessageFailureCode, get_message_manager
from client.managers.session_manager import SessionRefreshResult, get_session_manager
from client.models.message import ChatMessage, MessageStatus, MessageType, Session, build_attachment_extra, infer_message_type_from_path
from client.services.call_service import get_call_service
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
        self._call_manager = get_call_manager()
        self._summary_manager = get_conversation_summary_manager()
        self._call_service = None
        self._file_service = get_file_service()
        self._call_ice_servers = self._clone_ice_servers(get_config().webrtc.ice_servers)
        self._fallback_call_ice_servers = self._clone_ice_servers(self._call_ice_servers)
        self._call_ice_servers_loaded = False
        self._initialized = False

    ATTACHMENT_UPLOAD_FAILED_CODE = MessageFailureCode.ATTACHMENT_UPLOAD_FAILED

    @staticmethod
    def _clone_ice_servers(servers: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        return [dict(server) for server in list(servers or []) if isinstance(server, dict)]

    def get_call_ice_servers(self) -> list[dict[str, Any]]:
        """Return the current cached ICE server list for call windows."""
        return self._clone_ice_servers(self._call_ice_servers)

    async def refresh_call_ice_servers(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Refresh runtime ICE server config from the backend with local fallback."""
        if self._call_ice_servers_loaded and not force_refresh:
            return self.get_call_ice_servers()

        try:
            if self._call_service is None:
                self._call_service = get_call_service()
            self._call_ice_servers = self._clone_ice_servers(await self._call_service.fetch_ice_servers())
            self._call_ice_servers_loaded = True
        except Exception:
            logger.warning("Failed to refresh call ICE servers; using local fallback", exc_info=True)
            self._call_ice_servers = self._clone_ice_servers(self._fallback_call_ice_servers)
        return self.get_call_ice_servers()

    async def initialize(self) -> None:
        """Initialize chat controller."""
        if self._initialized:
            return

        await self._msg_manager.initialize()
        await self._session_manager.initialize()
        await self._call_manager.initialize()
        await self._summary_manager.initialize()

        self._initialized = True
        logger.info("Chat controller initialized")

    def set_user_id(self, user_id: str) -> None:
        """Set current user ID."""
        self._msg_manager.set_user_id(user_id)
        self._session_manager.set_user_id(user_id)
        self._call_manager.set_user_id(user_id)

    async def refresh_sessions_snapshot(self) -> SessionRefreshResult:
        """Refresh the authoritative session snapshot after profile-affecting changes."""
        return await self._session_manager.refresh_remote_sessions()

    async def recover_session_crypto(self, session_id: str) -> dict[str, Any]:
        """Execute one non-UI E2EE recovery action for a specific session."""
        return await self._session_manager.recover_session_crypto(session_id)

    async def recover_current_session_crypto(self) -> dict[str, Any]:
        """Execute one non-UI E2EE recovery action for the currently selected session."""
        session_id = str(self._session_manager.current_session_id or "").strip()
        if not session_id:
            raise RuntimeError("no current session selected")
        return await self.recover_session_crypto(session_id)

    async def trust_session_identities(self, session_id: str) -> dict[str, Any]:
        """Trust the current remote E2EE device identities for a specific session."""
        return await self._session_manager.trust_session_identities(session_id)

    async def trust_current_session_identities(self) -> dict[str, Any]:
        """Trust the current remote E2EE device identities for the selected session."""
        session_id = str(self._session_manager.current_session_id or "").strip()
        if not session_id:
            raise RuntimeError("no current session selected")
        return await self.trust_session_identities(session_id)

    async def get_session_security_summary(self, session_id: str) -> dict[str, Any]:
        """Return one normalized security summary for a specific session."""
        return await self._session_manager.get_session_security_summary(session_id)

    async def get_current_session_security_summary(self) -> dict[str, Any]:
        """Return one normalized security summary for the selected session."""
        return await self._session_manager.get_current_session_security_summary()

    async def get_session_identity_verification(self, session_id: str) -> dict[str, Any]:
        """Return one direct-session identity verification snapshot for a specific session."""
        return await self._session_manager.get_session_identity_verification(session_id)

    async def get_current_session_identity_verification(self) -> dict[str, Any]:
        """Return one direct-session identity verification snapshot for the selected session."""
        return await self._session_manager.get_current_session_identity_verification()

    async def get_session_identity_review_details(self, session_id: str) -> dict[str, Any]:
        """Return one richer identity-review payload for a specific session."""
        return await self._session_manager.get_session_identity_review_details(session_id)

    async def get_current_session_identity_review_details(self) -> dict[str, Any]:
        """Return one richer identity-review payload for the selected session."""
        return await self._session_manager.get_current_session_identity_review_details()

    async def get_session_security_diagnostics(self, session_id: str) -> dict[str, Any]:
        """Return one unified session security diagnostics payload for a specific session."""
        return await self._session_manager.get_session_security_diagnostics(session_id)

    async def get_current_session_security_diagnostics(self) -> dict[str, Any]:
        """Return one unified session security diagnostics payload for the selected session."""
        return await self._session_manager.get_current_session_security_diagnostics()

    async def execute_session_security_action(self, session_id: str, action_id: str) -> dict[str, Any]:
        """Execute one normalized security action for a specific session."""
        return await self._session_manager.execute_session_security_action(session_id, action_id)

    async def execute_current_session_security_action(self, action_id: str) -> dict[str, Any]:
        """Execute one normalized security action for the selected session."""
        return await self._session_manager.execute_current_session_security_action(action_id)

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

        if message.status not in {MessageStatus.AWAITING_SECURITY_CONFIRMATION, MessageStatus.FAILED}:
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

        upload_path = file_path
        cleanup_upload_path: str | None = None
        try:
            upload_path, encryption_extra, cleanup_upload_path = await self._msg_manager.prepare_attachment_upload(
                session_id=session_id,
                file_path=file_path,
                message_type=message_type,
                fallback_name=file_name,
                fallback_size=file_size,
            )
            if encryption_extra:
                placeholder.extra.update(encryption_extra)

            upload_result = await self._file_service.upload_chat_attachment(upload_path)
        except AppError as exc:
            logger.error("Failed to upload file %s: %s", file_path, exc)
            await self._msg_manager.mark_message_failed(placeholder, self.ATTACHMENT_UPLOAD_FAILED_CODE)
            raise
        except Exception as exc:
            logger.error("Failed to prepare/upload encrypted file %s: %s", file_path, exc)
            await self._msg_manager.mark_message_failed(placeholder, self.ATTACHMENT_UPLOAD_FAILED_CODE)
            raise
        finally:
            if cleanup_upload_path:
                try:
                    os.unlink(cleanup_upload_path)
                except OSError:
                    pass

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

    async def send_typing(self, *, typing: bool = True) -> None:
        """Send typing indicator for current session."""
        session_id = self._session_manager.current_session_id
        if session_id:
            await self._msg_manager.send_typing(session_id, typing=typing)

    async def send_read_receipt(self, message_id: str, session_id: Optional[str] = None) -> bool:
        """Send read receipt for a message."""
        session_id = session_id or self._session_manager.current_session_id
        if not session_id:
            return False
        return await self._msg_manager.send_read_receipt(session_id, message_id)

    async def retry_message(self, message_id: str) -> bool:
        """Retry sending a failed message."""
        return await self._msg_manager.retry_message(message_id)

    async def release_session_security_pending_messages(self, session_id: str) -> dict[str, Any]:
        """Release one session's locally held messages after the user confirms the security action."""
        result = await self._msg_manager.release_security_pending_messages(session_id)
        await self._session_manager.refresh_session_preview(session_id)
        return result

    async def discard_session_security_pending_messages(self, session_id: str) -> dict[str, Any]:
        """Delete one session's locally held messages that were never sent."""
        result = await self._msg_manager.discard_security_pending_messages(session_id)
        await self._session_manager.refresh_session_preview(session_id)
        return result

    async def download_message_attachment(self, message_id: str) -> str:
        """Ensure one file attachment is downloaded locally and return the local path."""
        return await self._msg_manager.download_attachment(message_id)

    async def recall_message(self, message_id: str) -> tuple[bool, str]:
        """Recall a previously sent message."""
        return await self._msg_manager.recall_message(message_id)

    async def edit_message(self, message_id: str, new_content: str) -> bool:
        """Edit a previously sent message."""
        return await self._msg_manager.edit_message(message_id, new_content)

    async def delete_message(self, message_id: str) -> bool:
        """Delete a previously sent message."""
        return await self._msg_manager.delete_message(message_id)

    async def update_message_translation(self, message_id: str, translation: dict[str, Any]) -> Optional[ChatMessage]:
        """Persist one local AI translation payload for a message."""
        return await self._msg_manager.update_message_translation(message_id, translation)

    async def load_messages(
        self,
        session_id: str,
        limit: int = 50,
        before_timestamp: Optional[float] = None,
        before_seq: Optional[int] = None,
        force_remote: bool = False,
    ) -> list[ChatMessage]:
        """Load messages for a session."""
        return await self._msg_manager.get_messages(
            session_id=session_id,
            limit=limit,
            before_timestamp=before_timestamp,
            before_seq=before_seq,
            force_remote=force_remote,
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

    async def set_current_session_active(self, active: bool, *, session_id: str | None = None) -> None:
        """Mark whether the selected session is currently foreground-readable."""
        await self._session_manager.set_current_session_active(active, session_id=session_id)

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
        allow_hidden: bool = False,
    ) -> Optional[Session]:
        """Ensure a remote session exists locally for the UI to open."""
        return await self._session_manager.ensure_remote_session(
            session_id,
            fallback_name=fallback_name,
            avatar=avatar,
            allow_hidden=allow_hidden,
        )

    async def ensure_direct_session(
        self,
        user_id: str,
        *,
        display_name: str = "",
        avatar: str = "",
        allow_hidden: bool = False,
    ) -> Optional[Session]:
        """Ensure a direct session exists for the given contact."""
        return await self._session_manager.ensure_direct_session(
            user_id,
            display_name=display_name,
            avatar=avatar,
            allow_hidden=allow_hidden,
        )

    async def refresh_session_preview(self, session_id: str) -> None:
        """Refresh the cached session preview from local storage."""
        await self._session_manager.refresh_session_preview(session_id)

    async def start_call(self, session: Session, media_type: str):
        """Start one outbound call for the given direct session."""
        await self.refresh_call_ice_servers(force_refresh=True)
        return await self._call_manager.start_call(session, media_type)

    async def accept_call(self, call_id: str) -> bool:
        """Accept one inbound call invite."""
        await self.refresh_call_ice_servers(force_refresh=True)
        return await self._call_manager.accept_call(call_id)

    async def reject_call(self, call_id: str) -> bool:
        """Reject one inbound call invite."""
        return await self._call_manager.reject_call(call_id)

    async def hangup_call(self, call_id: str, *, reason: str | None = None) -> bool:
        """Hang up one current call."""
        return await self._call_manager.hangup_call(call_id, reason=reason)

    async def send_call_ringing(self, call_id: str) -> bool:
        """Notify the caller that the incoming dialog is visible."""
        return await self._call_manager.send_ringing(call_id)

    async def send_call_offer(self, call_id: str, sdp: dict[str, Any]) -> bool:
        """Forward one WebRTC offer."""
        return await self._call_manager.send_offer(call_id, sdp)

    async def send_call_answer(self, call_id: str, sdp: dict[str, Any]) -> bool:
        """Forward one WebRTC answer."""
        return await self._call_manager.send_answer(call_id, sdp)

    async def send_call_ice_candidate(self, call_id: str, candidate: dict[str, Any]) -> bool:
        """Forward one ICE candidate."""
        return await self._call_manager.send_ice_candidate(call_id, candidate)

    def get_active_call(self):
        """Return the current active or pending call state."""
        return self._call_manager.active_call

    def get_total_unread(self) -> int:
        """Get total unread count."""
        return self._session_manager.get_total_unread_count()

    async def close(self) -> None:
        """Close chat controller and discard account-scoped call runtime cache."""
        logger.info("Closing chat controller")
        await self._call_manager.close()
        self._call_service = None
        self._call_ice_servers = self._clone_ice_servers(self._fallback_call_ice_servers)
        self._call_ice_servers_loaded = False
        self._initialized = False
        global _chat_controller
        if _chat_controller is self:
            _chat_controller = None
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
