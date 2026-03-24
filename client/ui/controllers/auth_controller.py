"""Authentication controller for login, registration, and session restore."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any, Optional

from client.core import logging
from client.core.avatar_utils import random_default_avatar_path
from client.core.exceptions import APIError, AuthExpiredError, NetworkError
from client.core.logging import setup_logging
from client.core.secure_storage import SecureStorage, SecureStorageError
from client.managers.connection_manager import peek_connection_manager
from client.managers.message_manager import get_message_manager
from client.services.auth_service import get_auth_service
from client.services.file_service import get_file_service
from client.services.user_service import get_user_service
from client.storage.database import get_database
from client.ui.controllers.chat_controller import get_chat_controller


setup_logging()
logger = logging.get_logger(__name__)


class AuthController:
    """Coordinate auth-related API calls and local session persistence."""

    ACCESS_TOKEN_KEY = "auth.access_token"
    REFRESH_TOKEN_KEY = "auth.refresh_token"
    USER_ID_KEY = "auth.user_id"
    USER_PROFILE_KEY = "auth.user_profile"
    TOKEN_EXP_SKEW_SECONDS = 30

    def __init__(self) -> None:
        self._auth_service = get_auth_service()
        self._user_service = get_user_service()
        self._file_service = get_file_service()
        self._db = get_database()
        self._message_manager = get_message_manager()
        self._chat_controller = get_chat_controller()
        self._current_user: dict[str, Any] | None = None
        self._token_state_task: Optional[asyncio.Task] = None
        self._suppress_token_listener_sync_depth = 0
        self._closed = False
        self._auth_service.add_token_listener(self._on_tokens_changed)

    @property
    def current_user(self) -> dict[str, Any] | None:
        return self._current_user

    async def restore_session(self) -> dict[str, Any] | None:
        """Restore persisted auth state and validate it with backend."""
        access_cipher = await self._db.get_app_state(self.ACCESS_TOKEN_KEY)
        refresh_cipher = await self._db.get_app_state(self.REFRESH_TOKEN_KEY)
        stored_profile = await self._db.get_app_state(self.USER_PROFILE_KEY)

        if not access_cipher or not refresh_cipher:
            return None

        try:
            access_token = SecureStorage.decrypt_text(access_cipher)
            refresh_token = SecureStorage.decrypt_text(refresh_cipher)
        except (SecureStorageError, ValueError) as exc:
            logger.warning("Failed to decrypt persisted auth state: %s", exc)
            await self.clear_session()
            return None

        if self._is_token_expired(refresh_token):
            logger.info("Stored refresh token is expired, clearing persisted auth state")
            await self.clear_session()
            return None

        self._cancel_pending_task(self._token_state_task)
        self._set_http_tokens(access_token, refresh_token)

        try:
            user = await self._auth_service.fetch_current_user()
        except (AuthExpiredError, APIError) as exc:
            logger.info("Stored auth session is no longer valid: %s", exc)
            await self.clear_session()
            return None
        except NetworkError as exc:
            logger.warning("Network error while restoring auth session: %s", exc)
            if stored_profile and not self._is_token_expired(refresh_token):
                try:
                    cached_user = json.loads(stored_profile)
                    self._apply_runtime_context(cached_user)
                    return cached_user
                except Exception:
                    return None
            return None

        await self._persist_auth_state(
            self._auth_service.access_token or access_token,
            self._auth_service.refresh_token or refresh_token,
            user,
        )
        self._apply_runtime_context(user)
        return user

    async def login(self, username: str, password: str) -> dict[str, Any]:
        payload = await self._auth_service.login(username, password)
        return await self._apply_auth_payload(payload, reset_local_chat_state=True)

    async def register(self, username: str, nickname: str, password: str) -> dict[str, Any]:
        payload = await self._auth_service.register(username, nickname, password)
        user = await self._apply_auth_payload(payload, reset_local_chat_state=True)
        return await self._persist_registration_default_avatar(user)

    async def logout(self) -> None:
        """Best-effort backend logout followed by local session cleanup."""
        try:
            await self._auth_service.logout()
        except (AuthExpiredError, APIError, NetworkError) as exc:
            logger.info("Logout request did not complete cleanly: %s", exc)
        except Exception:
            logger.exception("Unexpected logout error")
        finally:
            await self.clear_session()

    async def update_profile(
        self,
        *,
        nickname: str | None = None,
        avatar: str | None = None,
        avatar_file_path: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        birthday: str | None = None,
        region: str | None = None,
        signature: str | None = None,
        gender: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Update the current user's profile and persist the refreshed auth context."""
        resolved_avatar = avatar
        if avatar_file_path:
            upload_result = await self._file_service.upload_avatar(avatar_file_path)
            resolved_avatar = str(upload_result["url"])

        payload = {
            key: value
            for key, value in {
                "nickname": nickname,
                "avatar": resolved_avatar,
                "email": email,
                "phone": phone,
                "birthday": birthday,
                "region": region,
                "signature": signature,
                "gender": gender,
                "status": status,
            }.items()
            if value is not None
        }

        if not payload:
            return dict(self._current_user or {})

        user = await self._user_service.update_me(payload)
        self._apply_runtime_context(user)
        await self._persist_user_profile(user)
        return user

    async def _persist_registration_default_avatar(self, user: dict[str, Any]) -> dict[str, Any]:
        """Assign and persist one random default avatar after registration when needed."""
        profile = dict(user or {})
        if not profile or str(profile.get("avatar", "") or "").strip():
            return profile

        avatar_file_path = random_default_avatar_path(gender=profile.get("gender", ""))
        if not avatar_file_path:
            return profile

        try:
            return await self.update_profile(avatar_file_path=avatar_file_path)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to persist default avatar after registration for user %s",
                profile.get("id", ""),
            )
            return dict(self._current_user or profile)

    async def clear_session(self) -> None:
        self._cancel_pending_task(self._token_state_task)
        self._clear_http_tokens()
        self._current_user = None
        self._message_manager.set_user_id("")
        self._chat_controller.set_user_id("")

        await self._reset_local_chat_state()
        await self._clear_persisted_auth_state()

    async def _clear_persisted_auth_state(self) -> None:
        """Remove all persisted authentication state."""
        for key in (
            self.ACCESS_TOKEN_KEY,
            self.REFRESH_TOKEN_KEY,
            self.USER_ID_KEY,
            self.USER_PROFILE_KEY,
        ):
            await self._db.delete_app_state(key)

    async def _reset_local_chat_state(self) -> None:
        """Clear cached chat/session state and reset the sync cursor."""
        if self._db.is_connected:
            await self._db.clear_chat_state()

        conn_manager = peek_connection_manager()
        if conn_manager is not None:
            await conn_manager.reset_sync_state()

    async def _apply_auth_payload(
        self,
        payload: dict[str, Any],
        *,
        reset_local_chat_state: bool = False,
    ) -> dict[str, Any]:
        access_token = payload.get("access_token", "")
        refresh_token = payload.get("refresh_token", "")
        user = payload.get("user", {})

        if not access_token or not refresh_token or not user.get("id"):
            raise APIError("Invalid authentication payload")

        self._cancel_pending_task(self._token_state_task)
        if reset_local_chat_state:
            await self._reset_local_chat_state()
        self._set_http_tokens(access_token, refresh_token)
        await self._persist_auth_state(access_token, refresh_token, user)
        self._apply_runtime_context(user)
        return user

    async def _persist_auth_state(self, access_token: str, refresh_token: str, user: dict[str, Any]) -> None:
        access_cipher = SecureStorage.encrypt_text(access_token)
        refresh_cipher = SecureStorage.encrypt_text(refresh_token)

        await self._db.set_app_state(self.ACCESS_TOKEN_KEY, access_cipher)
        await self._db.set_app_state(self.REFRESH_TOKEN_KEY, refresh_cipher)
        await self._persist_user_profile(user)

    async def _persist_user_profile(self, user: dict[str, Any]) -> None:
        """Persist the current user payload without touching token state."""
        await self._db.set_app_state(self.USER_ID_KEY, user.get("id", ""))
        await self._db.set_app_state(self.USER_PROFILE_KEY, json.dumps(user, ensure_ascii=False))

    def _apply_runtime_context(self, user: dict[str, Any]) -> None:
        user_id = user.get("id", "")
        self._current_user = user
        self._message_manager.set_user_id(user_id)
        self._chat_controller.set_user_id(user_id)
        logger.info("Authentication context applied for user %s", user_id)

    def _on_tokens_changed(self, access_token: Optional[str], refresh_token: Optional[str]) -> None:
        """Persist token updates so refresh rotations survive app restarts."""
        if self._closed or self._suppress_token_listener_sync_depth > 0:
            return

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return

        if access_token and refresh_token and self._current_user:
            self._set_token_state_task(
                self._persist_auth_state(
                    access_token,
                    refresh_token,
                    self._current_user,
                ),
                "persist rotated tokens",
            )
            return

        if not access_token:
            self._set_token_state_task(self._clear_persisted_auth_state(), "clear persisted auth state")

    def _set_http_tokens(self, access_token: str, refresh_token: str) -> None:
        """Update HTTP tokens without re-triggering redundant listener persistence."""
        self._suppress_token_listener_sync_depth += 1
        try:
            self._auth_service.set_tokens(access_token, refresh_token)
        finally:
            self._suppress_token_listener_sync_depth = max(0, self._suppress_token_listener_sync_depth - 1)

    def _clear_http_tokens(self) -> None:
        """Clear HTTP tokens without scheduling duplicate persisted-state cleanup."""
        self._suppress_token_listener_sync_depth += 1
        try:
            self._auth_service.clear_tokens()
        finally:
            self._suppress_token_listener_sync_depth = max(0, self._suppress_token_listener_sync_depth - 1)

    def _cancel_pending_task(self, task: Optional[asyncio.Task]) -> None:
        """Cancel one tracked background task if it is still running."""
        if task is not None and not task.done():
            task.cancel()

    def _set_token_state_task(self, coro, context: str) -> None:
        """Keep only the latest persisted-token sync task alive."""
        self._cancel_pending_task(self._token_state_task)
        task = asyncio.create_task(coro)
        self._token_state_task = task
        task.add_done_callback(lambda finished, name=context: self._finalize_token_state_task(finished, name))

    def _finalize_token_state_task(self, task: asyncio.Task, context: str) -> None:
        """Clear task bookkeeping and report background sync failures."""
        if self._token_state_task is task:
            self._token_state_task = None

        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Auth controller background task failed: %s", context)

    async def close(self) -> None:
        """Detach token listeners and stop background persistence work."""
        self._closed = True
        self._auth_service.remove_token_listener(self._on_tokens_changed)

        task = self._token_state_task
        self._cancel_pending_task(task)
        self._token_state_task = None

        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    def _is_token_expired(self, token: str) -> bool:
        """Check JWT exp locally so obviously expired sessions are cleared before restore."""
        payload = self._decode_jwt_payload(token)
        if not payload:
            return True

        exp = payload.get("exp")
        try:
            expires_at = int(exp)
        except (TypeError, ValueError):
            return True

        return expires_at <= int(time.time()) + self.TOKEN_EXP_SKEW_SECONDS

    @staticmethod
    def _decode_jwt_payload(token: str) -> dict[str, Any] | None:
        """Decode a JWT payload without verifying the signature for local expiry checks."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            payload = parts[1]
            padding = "=" * (-len(payload) % 4)
            raw = base64.urlsafe_b64decode(payload + padding)
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None


_auth_controller: Optional[AuthController] = None


def peek_auth_controller() -> Optional[AuthController]:
    """Return the existing auth controller singleton if it was created."""
    return _auth_controller


def get_auth_controller() -> AuthController:
    """Get the global auth controller instance."""
    global _auth_controller
    if _auth_controller is None:
        _auth_controller = AuthController()
    return _auth_controller




