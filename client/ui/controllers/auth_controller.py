"""Authentication controller for login, registration, and session restore."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import json
import time
from typing import Any, Optional

from client.core import logging
from client.core.exceptions import APIError, AuthExpiredError, NetworkError, ServerError
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
        self._auth_state_listeners: list[object] = []
        self._authoritative_profile_refresh_pending = False
        self._token_state_task: Optional[asyncio.Task] = None
        self._e2ee_bootstrap_task: Optional[asyncio.Task] = None
        self._suppress_token_listener_sync_depth = 0
        self._closed = False
        self._auth_service.add_token_listener(self._on_tokens_changed)

    @property
    def current_user(self) -> dict[str, Any] | None:
        return self._current_user

    def add_auth_state_listener(self, listener) -> None:
        """Subscribe one listener to committed auth-context changes."""
        if listener not in self._auth_state_listeners:
            self._auth_state_listeners.append(listener)

    def remove_auth_state_listener(self, listener) -> None:
        """Unsubscribe one auth-context listener."""
        if listener in self._auth_state_listeners:
            self._auth_state_listeners.remove(listener)

    def has_pending_authoritative_profile_refresh(self) -> bool:
        """Return whether the current runtime user still comes from one cached restore snapshot."""
        return bool(self._authoritative_profile_refresh_pending and self._runtime_user_id())

    def _runtime_user_id(self) -> str:
        """Return the current authenticated runtime user id."""
        return str((self._current_user or {}).get("id", "") or "").strip()

    def _capture_runtime_user_id(self) -> str:
        """Capture one stable runtime user id for a mutating auth task."""
        return self._runtime_user_id()

    def _ensure_runtime_user_id(self, expected_user_id: str) -> None:
        """Reject late auth mutations after logout or account switches."""
        current_user_id = self._runtime_user_id()
        if expected_user_id and current_user_id != expected_user_id:
            raise asyncio.CancelledError

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
        if normalized_target_user_id != current_user_id:
            raise RuntimeError("history recovery export is limited to same-account devices")
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
        current_user_id = str((self._current_user or {}).get("id", "") or "").strip()
        if not current_user_id:
            raise RuntimeError("authentication required")
        return dict(
            await self._e2ee_service.import_history_recovery_package(
                package,
                expected_source_user_id=current_user_id,
            )
            or {}
        )

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
        """Restore one complete persisted auth snapshot and validate it with backend."""
        access_cipher = await self._db.get_app_state(self.ACCESS_TOKEN_KEY)
        refresh_cipher = await self._db.get_app_state(self.REFRESH_TOKEN_KEY)
        stored_user_id = str(await self._db.get_app_state(self.USER_ID_KEY) or "").strip()
        stored_profile = await self._db.get_app_state(self.USER_PROFILE_KEY)

        has_any_snapshot_value = any((access_cipher, refresh_cipher, stored_user_id, stored_profile))
        has_complete_snapshot = all((access_cipher, refresh_cipher, stored_user_id, stored_profile))
        if not has_complete_snapshot:
            if has_any_snapshot_value:
                logger.warning("Persisted auth snapshot is incomplete, clearing it")
                await self.clear_session(clear_local_chat_state=False)
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
        except ServerError as exc:
            logger.warning("Transient server error while restoring auth session: %s", exc)
            return await self._restore_from_cached_profile(
                stored_profile=stored_profile,
                stored_user_id=stored_user_id,
                access_token=access_token,
                refresh_token=refresh_token,
            )
        except APIError as exc:
            if exc.status_code in {401, 403}:
                logger.info("Stored auth session is no longer valid: %s", exc)
                await self.clear_session(clear_local_chat_state=False)
                return None
            logger.warning("Transient API error while restoring auth session: %s", exc)
            return await self._restore_from_cached_profile(
                stored_profile=stored_profile,
                stored_user_id=stored_user_id,
                access_token=access_token,
                refresh_token=refresh_token,
            )
        except NetworkError as exc:
            logger.warning("Network error while restoring auth session: %s", exc)
            return await self._restore_from_cached_profile(
                stored_profile=stored_profile,
                stored_user_id=stored_user_id,
                access_token=access_token,
                refresh_token=refresh_token,
            )

        if not isinstance(user, dict) or not str(user.get("id") or "").strip():
            logger.warning("Backend returned invalid auth user payload, clearing persisted auth state")
            await self.clear_session(clear_local_chat_state=False)
            return None

        user_id = str(user.get("id") or "").strip()
        if user_id != stored_user_id:
            logger.warning("Persisted auth user_id does not match backend auth user, clearing persisted auth state")
            await self.clear_session(clear_local_chat_state=False)
            return None

        active_access_token = self._auth_service.access_token or access_token
        active_refresh_token = self._auth_service.refresh_token or refresh_token
        if not self._refresh_token_matches_user(active_refresh_token, user, access_token=active_access_token):
            logger.warning("Persisted refresh token does not match restored user, clearing persisted auth state")
            await self.clear_session(clear_local_chat_state=False)
            return None

        await self._persist_auth_state(active_access_token, active_refresh_token, user)
        self._apply_runtime_context(user)
        self._schedule_e2ee_device_bootstrap()
        return user

    async def _restore_from_cached_profile(
        self,
        *,
        stored_profile: str,
        stored_user_id: str,
        access_token: str,
        refresh_token: str,
    ) -> dict[str, Any] | None:
        """Restore from the local profile only when the persisted snapshot is internally consistent."""
        cached_user = self._load_cached_user_profile(stored_profile, expected_user_id=stored_user_id)
        if cached_user and self._refresh_token_matches_user(refresh_token, cached_user, access_token=access_token):
            self._authoritative_profile_refresh_pending = True
            self._apply_runtime_context(cached_user, authoritative=False)
            self._schedule_e2ee_device_bootstrap()
            return cached_user

        logger.warning("Persisted cached auth profile does not match token snapshot, clearing persisted auth state")
        await self.clear_session(clear_local_chat_state=False)
        return None

    async def refresh_current_user_profile_if_needed(self) -> dict[str, Any] | None:
        """Replace one cached restore profile with the backend-authoritative user snapshot when possible."""
        current_user_id = self._runtime_user_id()
        if not self._authoritative_profile_refresh_pending or not current_user_id:
            return None

        try:
            user = await self._auth_service.fetch_current_user()
        except (NetworkError, ServerError, APIError) as exc:
            logger.info("Authoritative profile refresh still unavailable: %s", exc)
            return None
        except Exception:
            logger.exception("Authoritative profile refresh failed unexpectedly")
            return None

        if not isinstance(user, dict) or str(user.get("id") or "").strip() != current_user_id:
            logger.warning("Ignoring authoritative profile refresh with mismatched user payload")
            return None

        self._ensure_runtime_user_id(current_user_id)
        self._apply_runtime_context(user)
        await self._persist_user_profile(user)
        self._ensure_runtime_user_id(current_user_id)
        return dict(user)


    @staticmethod
    def _load_cached_user_profile(stored_profile: str, *, expected_user_id: str) -> dict[str, Any] | None:
        try:
            cached_user = json.loads(stored_profile)
        except Exception:
            return None
        if not isinstance(cached_user, dict):
            return None
        cached_user_id = str(cached_user.get("id") or "").strip()
        if not cached_user_id or cached_user_id != str(expected_user_id or "").strip():
            return None
        return cached_user

    def _refresh_token_matches_user(
        self,
        refresh_token: str,
        user: dict[str, Any],
        *,
        access_token: str = "",
    ) -> bool:
        user_id = str((user or {}).get("id") or "").strip()
        refresh_payload = self._decode_jwt_payload(refresh_token)
        if not user_id or not refresh_payload or str(refresh_payload.get("sub") or "").strip() != user_id:
            return False

        if access_token:
            access_payload = self._decode_jwt_payload(access_token)
            if not access_payload or str(access_payload.get("sub") or "").strip() != user_id:
                return False
            access_version = self._token_session_version(access_payload)
            refresh_version = self._token_session_version(refresh_payload)
            if access_version is not None and refresh_version is not None and access_version != refresh_version:
                return False

        return True

    @staticmethod
    def _token_session_version(payload: dict[str, Any]) -> int | None:
        if "session_version" not in payload:
            return None
        try:
            return int(payload.get("session_version") or 0)
        except (TypeError, ValueError):
            return None

    async def login(self, username: str, password: str, *, force: bool = False) -> dict[str, Any]:
        payload = await self.request_login_payload(username, password, force=force)
        return await self.commit_auth_payload(payload, reset_local_chat_state=True)

    async def register(self, username: str, nickname: str, password: str) -> dict[str, Any]:
        payload = await self.request_register_payload(username, nickname, password)
        return await self.commit_auth_payload(payload, reset_local_chat_state=True)

    async def request_login_payload(self, username: str, password: str, *, force: bool = False) -> dict[str, Any]:
        """Fetch one backend login payload without mutating local runtime/auth state yet."""
        return await self._auth_service.login(username, password, force=force)

    async def request_register_payload(self, username: str, nickname: str, password: str) -> dict[str, Any]:
        """Fetch one backend register payload without mutating local runtime/auth state yet."""
        return await self._auth_service.register(username, nickname, password)

    async def commit_auth_payload(
        self,
        payload: dict[str, Any],
        *,
        reset_local_chat_state: bool = False,
    ) -> dict[str, Any]:
        """Commit one already-fetched auth payload into persisted auth/runtime state."""
        return await self._apply_auth_payload(payload, reset_local_chat_state=reset_local_chat_state)

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
        owner_user_id = self._capture_runtime_user_id()
        guard_required = bool(owner_user_id)
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
            owner_user_id = owner_user_id or str(user.get("id", "") or "").strip()
            if guard_required:
                self._ensure_runtime_user_id(owner_user_id)
            self._apply_runtime_context(user)
            await self._persist_user_profile(user)
            guard_required = bool(owner_user_id)

        if avatar_file_path:
            user = await self._file_service.upload_profile_avatar(avatar_file_path)
            owner_user_id = owner_user_id or str(user.get("id", "") or "").strip()
            if guard_required:
                self._ensure_runtime_user_id(owner_user_id)
            self._apply_runtime_context(user)
            await self._persist_user_profile(user)
            guard_required = bool(owner_user_id)
        elif reset_avatar:
            user = await self._file_service.reset_profile_avatar()
            owner_user_id = owner_user_id or str(user.get("id", "") or "").strip()
            if guard_required:
                self._ensure_runtime_user_id(owner_user_id)
            self._apply_runtime_context(user)
            await self._persist_user_profile(user)
            guard_required = bool(owner_user_id)

        session_snapshot = None
        if user.get("id"):
            self._ensure_runtime_user_id(owner_user_id)
            session_snapshot = await self._refresh_session_snapshot(reason="profile update")
            self._ensure_runtime_user_id(owner_user_id)

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
        self._cancel_pending_task(self._e2ee_bootstrap_task)
        self._e2ee_bootstrap_task = None
        self._authoritative_profile_refresh_pending = False
        await self._clear_persisted_auth_state()
        self._clear_http_tokens()
        self._current_user = None
        self._set_runtime_user_id("")
        self._notify_auth_state_changed()

        if clear_local_chat_state:
            await self._reset_local_chat_state()

    async def _clear_persisted_auth_state(self) -> None:
        """Remove all persisted authentication state in one transaction."""
        await self._db.delete_app_states(
            [
                self.ACCESS_TOKEN_KEY,
                self.REFRESH_TOKEN_KEY,
                self.USER_ID_KEY,
                self.USER_PROFILE_KEY,
            ]
        )

    async def _reset_local_chat_state(self) -> None:
        """Clear cached chat/session state and reset the sync cursor."""
        if self._db.is_connected:
            await self._db.clear_chat_state()

        conn_manager = peek_connection_manager()
        if conn_manager is not None:
            conn_manager.clear_sync_state_memory()

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
        self._cancel_pending_task(self._e2ee_bootstrap_task)
        self._e2ee_bootstrap_task = None

        try:
            await self._persist_auth_state(access_token, refresh_token, user)
            if reset_local_chat_state:
                await self._reset_local_chat_state()
            self._set_http_tokens(access_token, refresh_token)
            self._apply_runtime_context(user)
            self._schedule_e2ee_device_bootstrap()
        except Exception:
            self._clear_http_tokens()
            self._authoritative_profile_refresh_pending = False
            self._current_user = None
            self._set_runtime_user_id("")
            self._notify_auth_state_changed()
            await self._clear_persisted_auth_state()
            raise
        return user

    async def _persist_auth_state(self, access_token: str, refresh_token: str, user: dict[str, Any]) -> None:
        access_cipher = SecureStorage.encrypt_text(access_token)
        refresh_cipher = SecureStorage.encrypt_text(refresh_token)
        await self._db.set_app_states(
            {
                self.ACCESS_TOKEN_KEY: access_cipher,
                self.REFRESH_TOKEN_KEY: refresh_cipher,
                self.USER_ID_KEY: str(user.get("id", "") or ""),
                self.USER_PROFILE_KEY: json.dumps(user, ensure_ascii=False),
            }
        )

    async def _persist_user_profile(self, user: dict[str, Any]) -> None:
        """Persist the current user payload without touching token state."""
        await self._db.set_app_states(
            {
                self.USER_ID_KEY: str(user.get("id", "") or ""),
                self.USER_PROFILE_KEY: json.dumps(user, ensure_ascii=False),
            }
        )

    def _apply_runtime_context(self, user: dict[str, Any], *, authoritative: bool = True) -> None:
        user_id = user.get("id", "")
        if authoritative:
            self._authoritative_profile_refresh_pending = False
        self._current_user = user
        self._notify_auth_state_changed()
        logger.info("Authentication context applied for user %s", user_id)

    def _notify_auth_state_changed(self) -> None:
        """Broadcast the latest committed auth snapshot to shell/UI listeners."""
        snapshot = dict(self._current_user or {})
        for listener in list(self._auth_state_listeners):
            try:
                listener(snapshot)
            except Exception:
                logger.exception("Auth state listener failed")

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

    def _schedule_e2ee_device_bootstrap(self) -> None:
        """Start best-effort E2EE device bootstrap without blocking auth commit."""
        if not self._current_user or not self._current_user.get("id"):
            return
        self._cancel_pending_task(self._e2ee_bootstrap_task)
        task = asyncio.create_task(self._ensure_e2ee_device_registered())
        self._e2ee_bootstrap_task = task
        task.add_done_callback(self._finalize_e2ee_bootstrap_task)

    def _finalize_e2ee_bootstrap_task(self, task: asyncio.Task) -> None:
        """Drop E2EE bootstrap bookkeeping after the best-effort task finishes."""
        if self._e2ee_bootstrap_task is task:
            self._e2ee_bootstrap_task = None
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Unexpected E2EE device bootstrap task failure")

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
        bootstrap_task = self._e2ee_bootstrap_task
        self._cancel_pending_task(task)
        self._cancel_pending_task(bootstrap_task)
        self._token_state_task = None
        self._e2ee_bootstrap_task = None

        pending_tasks = [item for item in (task, bootstrap_task) if item is not None]
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)

        for service in (self._e2ee_service, self._file_service, self._user_service, self._auth_service):
            close = getattr(service, "close", None)
            if callable(close):
                await close()

        global _auth_controller
        if _auth_controller is self:
            _auth_controller = None

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
