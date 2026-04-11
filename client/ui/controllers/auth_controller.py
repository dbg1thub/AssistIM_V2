"""Authentication controller for login, registration, and session restore."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import json
import time
from typing import Any, Optional

from client.core import logging
from client.core.exceptions import APIError, AuthExpiredError, NetworkError
from client.core.logging import setup_logging
from client.core.secure_storage import SecureStorage, SecureStorageError
from client.managers.connection_manager import peek_connection_manager
from client.managers.message_manager import get_message_manager, peek_message_manager
from client.managers.session_manager import SessionRefreshResult
from client.services.auth_service import get_auth_service
from client.services.e2ee_service import get_e2ee_service
from client.services.file_service import get_file_service
from client.services.user_service import get_user_service
from client.storage.database import get_database
from client.ui.controllers.chat_controller import get_chat_controller, peek_chat_controller


setup_logging()
logger = logging.get_logger(__name__)


@dataclass(frozen=True)
class ProfileUpdateResult:
    """User-profile mutation result plus session-snapshot refresh state."""

    user: dict[str, Any]
    session_snapshot: SessionRefreshResult | None


class AuthController:
    """Coordinate auth-related API calls and local session persistence."""

    ACCESS_TOKEN_KEY = "auth.access_token"
    REFRESH_TOKEN_KEY = "auth.refresh_token"
    USER_ID_KEY = "auth.user_id"
    USER_PROFILE_KEY = "auth.user_profile"
    TOKEN_EXP_SKEW_SECONDS = 30

    def __init__(self) -> None:
        self._auth_service = get_auth_service()
        self._e2ee_service = get_e2ee_service()
        self._user_service = get_user_service()
        self._file_service = get_file_service()
        self._db = get_database()
        self._current_user: dict[str, Any] | None = None
        self._token_state_task: Optional[asyncio.Task] = None
        self._suppress_token_listener_sync_depth = 0
        self._closed = False
        self._auth_service.add_token_listener(self._on_tokens_changed)

    @property
    def current_user(self) -> dict[str, Any] | None:
        return self._current_user

    def get_runtime_security_status(self) -> dict[str, Any]:
        """Expose one stable auth/runtime security snapshot for startup and diagnostics."""
        db_self_check_getter = getattr(self._db, "get_db_encryption_self_check", None)
        if callable(db_self_check_getter):
            database_encryption = dict(db_self_check_getter() or {})
        else:
            database_encryption = {
                "state": "unknown",
                "severity": "info",
                "can_start": True,
                "action_required": False,
                "message": "Local database encryption status is unavailable",
            }
        return {
            "authenticated": bool((self._current_user or {}).get("id")),
            "user_id": str((self._current_user or {}).get("id", "") or ""),
            "database_encryption": database_encryption,
        }

    async def get_history_recovery_diagnostics(self) -> dict[str, Any]:
        """Return one authenticated device-level history-recovery diagnostics snapshot."""
        if not self._current_user or not self._current_user.get("id"):
            raise RuntimeError("authentication required")
        return dict(await self._e2ee_service.get_history_recovery_diagnostics())

    async def list_my_e2ee_devices(self) -> list[dict[str, Any]]:
        """Return one authenticated snapshot of this account's registered E2EE devices."""
        if not self._current_user or not self._current_user.get("id"):
            raise RuntimeError("authentication required")
        return [dict(item) for item in await self._e2ee_service.list_my_devices() if isinstance(item, dict)]

    async def export_history_recovery_package(
        self,
        target_device_id: str,
        *,
        target_user_id: str | None = None,
    ) -> dict[str, Any]:
        """Export one history-recovery package for another device on the same account by default."""
        current_user_id = str((self._current_user or {}).get("id", "") or "").strip()
        if not current_user_id:
            raise RuntimeError("authentication required")
        normalized_target_device_id = str(target_device_id or "").strip()
        if not normalized_target_device_id:
            raise RuntimeError("target device id is required")
        normalized_target_user_id = str(target_user_id or current_user_id).strip()
        package = dict(
            await self._e2ee_service.export_history_recovery_package(
                normalized_target_user_id,
                normalized_target_device_id,
                source_user_id=current_user_id,
            )
            or {}
        )
        return {
            "target_user_id": normalized_target_user_id,
            "target_device_id": normalized_target_device_id,
            "package": package,
        }

    async def import_history_recovery_package(self, package: dict[str, Any] | None) -> dict[str, Any]:
        """Import one history-recovery package into the currently authenticated device."""
        if not self._current_user or not self._current_user.get("id"):
            raise RuntimeError("authentication required")
        return dict(await self._e2ee_service.import_history_recovery_package(package) or {})

    async def get_e2ee_diagnostics(self) -> dict[str, Any]:
        """Return one authenticated E2EE diagnostics snapshot for runtime, device recovery, and session state."""
        if not self._current_user or not self._current_user.get("id"):
            raise RuntimeError("authentication required")

        runtime_security = self.get_runtime_security_status()
        history_recovery = await self.get_history_recovery_diagnostics()
        current_session_security: dict[str, Any]
        try:
            current_session_security = await self.get_current_session_security_diagnostics()
        except RuntimeError as exc:
            current_session_security = {
                "available": False,
                "reason": str(exc),
            }

        return {
            "authenticated": True,
            "user_id": str((self._current_user or {}).get("id", "") or ""),
            "runtime_security": runtime_security,
            "history_recovery": history_recovery,
            "current_session_security": current_session_security,
        }

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
            await self.clear_session(clear_local_chat_state=False)
            return None

        if self._is_token_expired(refresh_token):
            logger.info("Stored refresh token is expired, clearing persisted auth state")
            await self.clear_session(clear_local_chat_state=False)
            return None

        self._cancel_pending_task(self._token_state_task)
        self._set_http_tokens(access_token, refresh_token)

        try:
            user = await self._auth_service.fetch_current_user()
        except AuthExpiredError as exc:
            logger.info("Stored auth session is no longer valid: %s", exc)
            await self.clear_session(clear_local_chat_state=False)
            return None
        except APIError as exc:
            if exc.status_code in {401, 403}:
                logger.info("Stored auth session is no longer valid: %s", exc)
                await self.clear_session(clear_local_chat_state=False)
                return None
            logger.warning("Transient API error while restoring auth session: %s", exc)
            if stored_profile and not self._is_token_expired(refresh_token):
                try:
                    cached_user = json.loads(stored_profile)
                    if isinstance(cached_user, dict) and cached_user.get("id"):
                        self._apply_runtime_context(cached_user)
                        return cached_user
                except Exception:
                    return None
            return None
        except NetworkError as exc:
            logger.warning("Network error while restoring auth session: %s", exc)
            if stored_profile and not self._is_token_expired(refresh_token):
                try:
                    cached_user = json.loads(stored_profile)
                    if isinstance(cached_user, dict) and cached_user.get("id"):
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
        await self._ensure_e2ee_device_registered()
        return user

    async def login(self, username: str, password: str, *, force: bool = False) -> dict[str, Any]:
        payload = await self._auth_service.login(username, password, force=force)
        return await self._apply_auth_payload(payload, reset_local_chat_state=True)

    async def register(self, username: str, nickname: str, password: str) -> dict[str, Any]:
        payload = await self._auth_service.register(username, nickname, password)
        return await self._apply_auth_payload(payload, reset_local_chat_state=True)

    async def logout(self, *, clear_local_chat_state: bool = True) -> None:
        """Best-effort backend logout followed by local session cleanup."""
        try:
            await self._auth_service.logout()
        except (AuthExpiredError, APIError, NetworkError) as exc:
            logger.info("Logout request did not complete cleanly: %s", exc)
        except Exception:
            logger.exception("Unexpected logout error")
        finally:
            await self.clear_session(clear_local_chat_state=clear_local_chat_state)

    async def update_profile(
        self,
        *,
        nickname: str | None = None,
        avatar_file_path: str | None = None,
        reset_avatar: bool = False,
        email: str | None = None,
        phone: str | None = None,
        birthday: str | None = None,
        region: str | None = None,
        signature: str | None = None,
        gender: str | None = None,
        status: str | None = None,
    ) -> ProfileUpdateResult:
        """Update the current user's profile and persist the refreshed auth context."""
        user = dict(self._current_user or {})
        profile_payload = {
            key: value
            for key, value in {
                "nickname": nickname,
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

        if profile_payload:
            user = await self._user_service.update_me(profile_payload)
            self._apply_runtime_context(user)
            await self._persist_user_profile(user)

        if avatar_file_path:
            user = await self._file_service.upload_profile_avatar(avatar_file_path)
            self._apply_runtime_context(user)
            await self._persist_user_profile(user)
        elif reset_avatar:
            user = await self._file_service.reset_profile_avatar()
            self._apply_runtime_context(user)
            await self._persist_user_profile(user)

        session_snapshot = None
        if user.get("id"):
            session_snapshot = await self._refresh_session_snapshot(reason="profile update")

        return ProfileUpdateResult(
            user=dict(user or {}),
            session_snapshot=session_snapshot,
        )

    async def recover_session_crypto(self, session_id: str) -> dict[str, Any]:
        """Run one session-level E2EE recovery flow from the authenticated app context."""
        if not self._current_user or not self._current_user.get("id"):
            raise RuntimeError("authentication required")
        result = await self._require_chat_controller().recover_session_crypto(session_id)
        return await self._finalize_session_security_result(result, refresh_reason="E2EE recovery")

    async def recover_current_session_crypto(self) -> dict[str, Any]:
        """Recover the currently selected session and refresh cached session state when successful."""
        if not self._current_user or not self._current_user.get("id"):
            raise RuntimeError("authentication required")
        result = await self._require_chat_controller().recover_current_session_crypto()
        return await self._finalize_session_security_result(result, refresh_reason="E2EE recovery")

    async def execute_session_security_action(self, session_id: str, action_id: str) -> dict[str, Any]:
        """Execute one session security action from the authenticated app context."""
        if not self._current_user or not self._current_user.get("id"):
            raise RuntimeError("authentication required")
        result = await self._require_chat_controller().execute_session_security_action(session_id, action_id)
        return await self._finalize_session_security_result(result, refresh_reason="session security action")

    async def execute_current_session_security_action(self, action_id: str) -> dict[str, Any]:
        """Execute one security action for the currently selected session."""
        if not self._current_user or not self._current_user.get("id"):
            raise RuntimeError("authentication required")
        result = await self._require_chat_controller().execute_current_session_security_action(action_id)
        return await self._finalize_session_security_result(result, refresh_reason="session security action")

    async def get_session_identity_verification(self, session_id: str) -> dict[str, Any]:
        """Return one authenticated identity-verification snapshot for a specific session."""
        if not self._current_user or not self._current_user.get("id"):
            raise RuntimeError("authentication required")
        return await self._require_chat_controller().get_session_identity_verification(session_id)

    async def get_current_session_identity_verification(self) -> dict[str, Any]:
        """Return one authenticated identity-verification snapshot for the selected session."""
        if not self._current_user or not self._current_user.get("id"):
            raise RuntimeError("authentication required")
        return await self._require_chat_controller().get_current_session_identity_verification()

    async def get_session_identity_review_details(self, session_id: str) -> dict[str, Any]:
        """Return one authenticated identity-review details payload for a specific session."""
        if not self._current_user or not self._current_user.get("id"):
            raise RuntimeError("authentication required")
        return await self._require_chat_controller().get_session_identity_review_details(session_id)

    async def get_current_session_identity_review_details(self) -> dict[str, Any]:
        """Return one authenticated identity-review details payload for the selected session."""
        if not self._current_user or not self._current_user.get("id"):
            raise RuntimeError("authentication required")
        return await self._require_chat_controller().get_current_session_identity_review_details()

    async def get_session_security_diagnostics(self, session_id: str) -> dict[str, Any]:
        """Return one authenticated unified security diagnostics payload for a specific session."""
        if not self._current_user or not self._current_user.get("id"):
            raise RuntimeError("authentication required")
        return await self._require_chat_controller().get_session_security_diagnostics(session_id)

    async def get_current_session_security_diagnostics(self) -> dict[str, Any]:
        """Return one authenticated unified security diagnostics payload for the selected session."""
        if not self._current_user or not self._current_user.get("id"):
            raise RuntimeError("authentication required")
        return await self._require_chat_controller().get_current_session_security_diagnostics()

    async def _refresh_session_snapshot(self, *, reason: str) -> SessionRefreshResult:
        """Refresh one chat-session snapshot and surface degraded results explicitly."""
        try:
            snapshot = await self._require_chat_controller().refresh_sessions_snapshot()
        except Exception:
            logger.warning("Failed to refresh session snapshot after %s", reason, exc_info=True)
            return SessionRefreshResult(
                sessions=[],
                authoritative=False,
                unread_synchronized=False,
            )

        if not snapshot.authoritative:
            logger.warning("Session snapshot after %s is non-authoritative", reason)
        elif not snapshot.unread_synchronized:
            logger.warning("Session snapshot after %s has stale unread counters", reason)
        return snapshot

    @staticmethod
    def _session_snapshot_payload(snapshot: SessionRefreshResult | None) -> dict[str, bool] | None:
        """Serialize one session-refresh status for controller callers."""
        if snapshot is None:
            return None
        return {
            "authoritative": bool(snapshot.authoritative),
            "unread_synchronized": bool(snapshot.unread_synchronized),
        }

    async def _finalize_session_security_result(
        self,
        result: dict[str, Any] | None,
        *,
        refresh_reason: str,
    ) -> dict[str, Any]:
        """Attach explicit session-snapshot status after successful session-security mutations."""
        normalized = dict(result or {})
        if not normalized.get("performed"):
            normalized["session_snapshot"] = None
            return normalized

        snapshot = await self._refresh_session_snapshot(reason=refresh_reason)
        normalized["session_snapshot"] = self._session_snapshot_payload(snapshot)
        return normalized

    async def clear_session(self, *, clear_local_chat_state: bool = True) -> None:
        self._cancel_pending_task(self._token_state_task)
        self._clear_http_tokens()
        self._current_user = None
        self._set_runtime_user_id("")

        if clear_local_chat_state:
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
        await self._ensure_e2ee_device_registered()
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
        self._set_runtime_user_id(user_id)
        logger.info("Authentication context applied for user %s", user_id)

    @staticmethod
    def _require_chat_controller():
        """Get the authenticated chat runtime on demand."""
        return get_chat_controller()

    @staticmethod
    def _set_runtime_user_id(user_id: str) -> None:
        """Propagate auth context only into runtime objects that already exist."""
        message_manager = peek_message_manager()
        if message_manager is not None:
            message_manager.set_user_id(user_id)

        chat_controller = peek_chat_controller()
        if chat_controller is not None:
            chat_controller.set_user_id(user_id)

    async def _ensure_e2ee_device_registered(self) -> None:
        """Best-effort device bootstrap for future private-chat E2EE."""
        if not self._current_user or not self._current_user.get("id"):
            return
        try:
            await self._e2ee_service.ensure_registered_device()
        except Exception as exc:
            logger.warning("E2EE device bootstrap failed: %s", exc)

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
