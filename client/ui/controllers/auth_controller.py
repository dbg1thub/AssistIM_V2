"""Authentication controller for login, registration, and session restore."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any, Optional

from client.core import logging
from client.core.exceptions import APIError, AuthExpiredError, NetworkError
from client.core.logging import setup_logging
from client.core.secure_storage import SecureStorage, SecureStorageError
from client.managers.message_manager import get_message_manager
from client.network.http_client import get_http_client
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
        self._http = get_http_client()
        self._db = get_database()
        self._message_manager = get_message_manager()
        self._chat_controller = get_chat_controller()
        self._current_user: dict[str, Any] | None = None
        self._http.add_token_listener(self._on_tokens_changed)

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

        self._http.set_tokens(access_token, refresh_token)

        try:
            user = await self._http.get("/auth/me")
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

        await self._persist_auth_state(self._http.access_token or access_token, self._http.refresh_token or refresh_token, user)
        self._apply_runtime_context(user)
        return user

    async def login(self, username: str, password: str) -> dict[str, Any]:
        payload = await self._http.post(
            "/auth/login",
            json={
                "username": username,
                "password": password,
            },
        )
        return await self._apply_auth_payload(payload)

    async def register(self, username: str, nickname: str, password: str) -> dict[str, Any]:
        payload = await self._http.post(
            "/auth/register",
            json={
                "username": username,
                "password": password,
                "nickname": nickname,
            },
        )
        return await self._apply_auth_payload(payload)

    async def clear_session(self) -> None:
        self._http.clear_tokens()
        self._current_user = None
        self._message_manager.set_user_id("")
        self._chat_controller.set_user_id("")

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

    async def _apply_auth_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        access_token = payload.get("access_token", "")
        refresh_token = payload.get("refresh_token", "")
        user = payload.get("user", {})

        if not access_token or not refresh_token or not user.get("id"):
            raise APIError("Invalid authentication payload")

        self._http.set_tokens(access_token, refresh_token)
        await self._persist_auth_state(access_token, refresh_token, user)
        self._apply_runtime_context(user)
        return user

    async def _persist_auth_state(self, access_token: str, refresh_token: str, user: dict[str, Any]) -> None:
        access_cipher = SecureStorage.encrypt_text(access_token)
        refresh_cipher = SecureStorage.encrypt_text(refresh_token)

        await self._db.set_app_state(self.ACCESS_TOKEN_KEY, access_cipher)
        await self._db.set_app_state(self.REFRESH_TOKEN_KEY, refresh_cipher)
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
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        if access_token and refresh_token and self._current_user:
            loop.create_task(
                self._persist_auth_state(
                    access_token,
                    refresh_token,
                    self._current_user,
                )
            )
            return

        if not access_token:
            loop.create_task(self._clear_persisted_auth_state())

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


def get_auth_controller() -> AuthController:
    """Get the global auth controller instance."""
    global _auth_controller
    if _auth_controller is None:
        _auth_controller = AuthController()
    return _auth_controller
