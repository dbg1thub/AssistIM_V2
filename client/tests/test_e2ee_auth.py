from __future__ import annotations

import asyncio
import base64
import json
import time

from client.core.exceptions import NetworkError, ServerError
from client.tests import test_service_boundaries as boundaries
from client.ui.controllers import auth_controller as auth_controller_module


def _jwt(user_id: str, *, session_version: int = 1, expires_in: int = 3600) -> str:
    header = {"alg": "none", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "session_version": session_version,
        "exp": int(time.time()) + expires_in,
    }

    def encode(data: dict[str, object]) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{encode(header)}.{encode(payload)}.signature"


async def _persist_restore_snapshot(
    db,
    controller,
    *,
    stored_user_id: str = "user-1",
    profile: dict[str, object] | None = None,
    access_user_id: str = "user-1",
    refresh_user_id: str = "user-1",
    access_session_version: int = 1,
    refresh_session_version: int = 1,
) -> tuple[str, str]:
    access_token = _jwt(access_user_id, session_version=access_session_version)
    refresh_token = _jwt(refresh_user_id, session_version=refresh_session_version)
    await db.set_app_states(
        {
            controller.ACCESS_TOKEN_KEY: auth_controller_module.SecureStorage.encrypt_text(access_token),
            controller.REFRESH_TOKEN_KEY: auth_controller_module.SecureStorage.encrypt_text(refresh_token),
            controller.USER_ID_KEY: stored_user_id,
            controller.USER_PROFILE_KEY: json.dumps(profile or {"id": stored_user_id, "username": stored_user_id}),
        }
    )
    return access_token, refresh_token


def _wire_auth_controller(monkeypatch, fake_auth_service, fake_db, fake_e2ee_service=None):
    fake_e2ee_service = fake_e2ee_service or FakeE2EEService()
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    monkeypatch.setattr(auth_controller_module, "get_auth_service", lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, "get_user_service", lambda: boundaries.FakeUserService())
    monkeypatch.setattr(auth_controller_module, "get_database", lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, "get_message_manager", lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, "peek_message_manager", lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, "get_chat_controller", lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, "peek_chat_controller", lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, "get_file_service", lambda: boundaries.FakeFileService())
    monkeypatch.setattr(auth_controller_module, "get_e2ee_service", lambda: fake_e2ee_service)
    monkeypatch.setattr(auth_controller_module, "peek_connection_manager", lambda: None)
    return fake_e2ee_service, fake_message_manager, fake_chat_controller


class FakeE2EEService:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls = 0
        self.history_recovery_diagnostics_calls = 0
        self.list_my_devices_calls = 0
        self.export_history_recovery_package_calls: list[tuple[str, str, str]] = []
        self.import_history_recovery_package_calls: list[dict[str, object]] = []
        self.history_recovery_diagnostics_result = {
            "local_device_id": "device-1",
            "available": False,
            "source_device_count": 0,
        }
        self.list_my_devices_result = [
            {"device_id": "device-1", "device_name": "Desktop"},
        ]
        self.export_history_recovery_package_result = {
            "scheme": "device-history-recovery-v1",
            "recipient_device_id": "device-2",
        }
        self.import_history_recovery_package_result = {
            "source_device_id": "device-old-1",
            "available": True,
        }

    async def ensure_registered_device(self) -> dict:
        self.calls += 1
        if self.should_fail:
            raise RuntimeError("device bootstrap failed")
        return {"device_id": "device-1"}

    async def get_history_recovery_diagnostics(self) -> dict:
        self.history_recovery_diagnostics_calls += 1
        return dict(self.history_recovery_diagnostics_result)

    async def list_my_devices(self) -> list[dict]:
        self.list_my_devices_calls += 1
        return [dict(item) for item in self.list_my_devices_result]

    async def export_history_recovery_package(
        self,
        target_user_id: str,
        target_device_id: str,
        *,
        source_user_id: str = "",
    ) -> dict:
        self.export_history_recovery_package_calls.append((target_user_id, target_device_id, source_user_id))
        result = dict(self.export_history_recovery_package_result)
        result.setdefault("recipient_device_id", target_device_id)
        return result

    async def import_history_recovery_package(self, package: dict | None) -> dict:
        self.import_history_recovery_package_calls.append(dict(package or {}))
        return dict(self.import_history_recovery_package_result)


class OrderedAuthDatabase(boundaries.FakeDatabase):
    def __init__(self, events: list[str], *, fail_on_key: str = "") -> None:
        super().__init__()
        self.events = events
        self.fail_on_key = fail_on_key
        self.is_connected = True

    async def set_app_state(self, key: str, value) -> None:
        await self.set_app_states({key: value})

    async def set_app_states(self, values: dict[str, object]) -> None:
        keys = list(values.keys())
        self.events.append(f"set_app_states({','.join(keys)})")
        if self.fail_on_key in values:
            raise RuntimeError(f"failed to persist {self.fail_on_key}")
        await super().set_app_states(values)

    async def delete_app_state(self, key: str) -> None:
        await self.delete_app_states([key])

    async def delete_app_states(self, keys) -> None:
        normalized = [str(key) for key in keys]
        self.events.append(f"delete_app_states({','.join(normalized)})")
        await super().delete_app_states(normalized)

    async def clear_chat_state(self) -> None:
        self.events.append("clear_chat_state")


class OrderedAuthService(boundaries.FakeAuthService):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def set_tokens(self, access_token: str, refresh_token: str) -> None:
        self.events.append("set_tokens")
        super().set_tokens(access_token, refresh_token)

    def clear_tokens(self) -> None:
        self.events.append("clear_tokens")
        super().clear_tokens()


class RuntimeSyncStateSpy:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.clear_memory_calls = 0

    def clear_sync_state_memory(self) -> None:
        self.clear_memory_calls += 1
        self.events.append("clear_sync_state_memory")

    async def reset_sync_state(self) -> None:
        raise AssertionError("clear_session must not delete persisted sync cursors twice")


def test_auth_controller_login_registers_e2ee_device(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()

    monkeypatch.setattr(auth_controller_module, "get_auth_service", lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, "get_user_service", lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, "get_database", lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, "get_message_manager", lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, "get_chat_controller", lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, "get_file_service", lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, "get_e2ee_service", lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        user = await controller.login("alice", "secret123")
        await asyncio.sleep(0)

        assert user["id"] == "user-1"
        assert fake_e2ee_service.calls == 1

    asyncio.run(scenario())


def test_auth_controller_login_tolerates_e2ee_bootstrap_failure(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService(should_fail=True)

    monkeypatch.setattr(auth_controller_module, "get_auth_service", lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, "get_user_service", lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, "get_database", lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, "get_message_manager", lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, "get_chat_controller", lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, "get_file_service", lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, "get_e2ee_service", lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        user = await controller.login("alice", "secret123")
        await asyncio.sleep(0)

        assert user["id"] == "user-1"
        assert fake_e2ee_service.calls == 1

    asyncio.run(scenario())


def test_auth_controller_login_commits_auth_before_destructive_chat_reset(monkeypatch) -> None:
    events: list[str] = []
    fake_auth_service = OrderedAuthService(events)
    fake_user_service = boundaries.FakeUserService()
    fake_db = OrderedAuthDatabase(events)
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()

    monkeypatch.setattr(auth_controller_module, "get_auth_service", lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, "get_user_service", lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, "get_database", lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, "get_message_manager", lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, "get_chat_controller", lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, "get_file_service", lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, "get_e2ee_service", lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        user = await controller.login("alice", "secret123")
        await asyncio.sleep(0)

        assert user["id"] == "user-1"
        assert events[:2] == [
            "set_app_states(auth.access_token,auth.refresh_token,auth.user_id,auth.user_profile)",
            "clear_chat_state",
        ]
        assert "set_tokens" in events
        assert events.index("clear_chat_state") < events.index("set_tokens")
        assert fake_e2ee_service.calls == 1

    asyncio.run(scenario())


def test_auth_controller_login_persist_failure_rolls_back_auth_runtime(monkeypatch) -> None:
    events: list[str] = []
    fake_auth_service = OrderedAuthService(events)
    fake_user_service = boundaries.FakeUserService()
    fake_db = OrderedAuthDatabase(events, fail_on_key="auth.refresh_token")
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()

    monkeypatch.setattr(auth_controller_module, "get_auth_service", lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, "get_user_service", lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, "get_database", lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, "get_message_manager", lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, "get_chat_controller", lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, "peek_message_manager", lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, "peek_chat_controller", lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, "get_file_service", lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, "get_e2ee_service", lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()

        try:
            await controller.login("alice", "secret123")
        except RuntimeError as exc:
            assert "auth.refresh_token" in str(exc)
        else:
            raise AssertionError("login should fail when auth state cannot be persisted")

        assert fake_auth_service.access_token is None
        assert fake_auth_service.refresh_token is None
        assert controller.current_user is None
        assert "clear_chat_state" not in events
        assert "set_tokens" not in events
        assert fake_e2ee_service.calls == 0
        assert fake_message_manager.user_ids == [""]
        assert fake_chat_controller.user_ids == [""]

    asyncio.run(scenario())


def test_auth_controller_close_clears_global_singleton(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_db = boundaries.FakeDatabase()
    _wire_auth_controller(monkeypatch, fake_auth_service, fake_db)

    async def scenario() -> None:
        auth_controller_module._auth_controller = None
        controller = auth_controller_module.get_auth_controller()

        await controller.close()

        assert auth_controller_module.peek_auth_controller() is None
        assert fake_auth_service.listeners == []

    asyncio.run(scenario())


def test_auth_controller_clear_session_deletes_auth_snapshot_before_runtime_reset(monkeypatch) -> None:
    events: list[str] = []
    fake_auth_service = OrderedAuthService(events)
    fake_db = OrderedAuthDatabase(events)
    _wire_auth_controller(monkeypatch, fake_auth_service, fake_db)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()

        await controller.clear_session(clear_local_chat_state=True)

        assert events[:3] == [
            "delete_app_states(auth.access_token,auth.refresh_token,auth.user_id,auth.user_profile)",
            "clear_tokens",
            "clear_chat_state",
        ]

    asyncio.run(scenario())


def test_auth_controller_clear_session_clears_connection_sync_memory_once(monkeypatch) -> None:
    events: list[str] = []
    fake_auth_service = OrderedAuthService(events)
    fake_db = OrderedAuthDatabase(events)
    fake_connection_manager = RuntimeSyncStateSpy(events)
    _wire_auth_controller(monkeypatch, fake_auth_service, fake_db)
    monkeypatch.setattr(auth_controller_module, "peek_connection_manager", lambda: fake_connection_manager)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()

        await controller.clear_session(clear_local_chat_state=True)

        assert events[:4] == [
            "delete_app_states(auth.access_token,auth.refresh_token,auth.user_id,auth.user_profile)",
            "clear_tokens",
            "clear_chat_state",
            "clear_sync_state_memory",
        ]
        assert fake_connection_manager.clear_memory_calls == 1

    asyncio.run(scenario())


def test_auth_controller_restore_rejects_refresh_token_for_different_user(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_db = boundaries.FakeDatabase()
    fake_e2ee_service, _, _ = _wire_auth_controller(monkeypatch, fake_auth_service, fake_db)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await _persist_restore_snapshot(
            fake_db,
            controller,
            stored_user_id="user-1",
            profile={"id": "user-1", "username": "alice"},
            access_user_id="user-1",
            refresh_user_id="user-2",
        )

        restored = await controller.restore_session()

        assert restored is None
        assert controller.current_user is None
        assert fake_auth_service.access_token is None
        assert fake_auth_service.refresh_token is None
        assert fake_e2ee_service.calls == 0
        assert fake_db.app_state == {}

    asyncio.run(scenario())


def test_auth_controller_restore_recovers_from_server_error_with_consistent_cached_profile(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_db = boundaries.FakeDatabase()
    fake_e2ee_service, fake_message_manager, fake_chat_controller = _wire_auth_controller(
        monkeypatch,
        fake_auth_service,
        fake_db,
    )

    async def fail_fetch_current_user():
        raise ServerError("temporary outage", status_code=503)

    fake_auth_service.fetch_current_user = fail_fetch_current_user

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        access_token, refresh_token = await _persist_restore_snapshot(
            fake_db,
            controller,
            stored_user_id="user-1",
            profile={"id": "user-1", "username": "alice"},
            access_user_id="user-1",
            refresh_user_id="user-1",
        )

        restored = await controller.restore_session()
        await asyncio.sleep(0)

        assert restored == {"id": "user-1", "username": "alice"}
        assert fake_auth_service.access_token == access_token
        assert fake_auth_service.refresh_token == refresh_token
        assert controller.current_user == {"id": "user-1", "username": "alice"}
        assert fake_message_manager.user_ids == []
        assert fake_chat_controller.user_ids == []
        assert fake_e2ee_service.calls == 1

    asyncio.run(scenario())


def test_auth_controller_refreshes_cached_restore_profile_when_network_recovers(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_db = boundaries.FakeDatabase()
    fake_e2ee_service, fake_message_manager, fake_chat_controller = _wire_auth_controller(
        monkeypatch,
        fake_auth_service,
        fake_db,
    )

    async def fail_fetch_current_user():
        raise NetworkError("offline")

    fake_auth_service.fetch_current_user = fail_fetch_current_user

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        access_token, refresh_token = await _persist_restore_snapshot(
            fake_db,
            controller,
            stored_user_id="user-1",
            profile={"id": "user-1", "username": "alice", "nickname": "Cached Alice"},
            access_user_id="user-1",
            refresh_user_id="user-1",
        )

        restored = await controller.restore_session()
        await asyncio.sleep(0)

        assert restored == {"id": "user-1", "username": "alice", "nickname": "Cached Alice"}
        assert controller.has_pending_authoritative_profile_refresh() is True
        assert fake_auth_service.access_token == access_token
        assert fake_auth_service.refresh_token == refresh_token
        assert fake_message_manager.user_ids == []
        assert fake_chat_controller.user_ids == []
        assert fake_e2ee_service.calls == 1

        async def fetch_authoritative_user():
            return {"id": "user-1", "username": "alice", "nickname": "Alice Updated"}

        fake_auth_service.fetch_current_user = fetch_authoritative_user
        refreshed = await controller.refresh_current_user_profile_if_needed()

        assert refreshed == {"id": "user-1", "username": "alice", "nickname": "Alice Updated"}
        assert controller.current_user == {"id": "user-1", "username": "alice", "nickname": "Alice Updated"}
        assert controller.has_pending_authoritative_profile_refresh() is False
        assert json.loads(fake_db.app_state[controller.USER_PROFILE_KEY])["nickname"] == "Alice Updated"

    asyncio.run(scenario())


def test_auth_controller_restore_clears_invalid_cached_profile_and_http_tokens(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_db = boundaries.FakeDatabase()
    _wire_auth_controller(monkeypatch, fake_auth_service, fake_db)

    async def fail_fetch_current_user():
        raise NetworkError("offline")

    fake_auth_service.fetch_current_user = fail_fetch_current_user

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await _persist_restore_snapshot(
            fake_db,
            controller,
            stored_user_id="user-1",
            profile={"username": "missing-id"},
            access_user_id="user-1",
            refresh_user_id="user-1",
        )

        restored = await controller.restore_session()

        assert restored is None
        assert controller.current_user is None
        assert fake_auth_service.access_token is None
        assert fake_auth_service.refresh_token is None
        assert fake_db.app_state == {}

    asyncio.run(scenario())


def test_auth_controller_restore_clears_mixed_cached_profile_and_token_snapshot(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_db = boundaries.FakeDatabase()
    _wire_auth_controller(monkeypatch, fake_auth_service, fake_db)

    async def fail_fetch_current_user():
        raise NetworkError("offline")

    fake_auth_service.fetch_current_user = fail_fetch_current_user

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await _persist_restore_snapshot(
            fake_db,
            controller,
            stored_user_id="user-2",
            profile={"id": "user-2", "username": "bob"},
            access_user_id="user-1",
            refresh_user_id="user-1",
        )

        restored = await controller.restore_session()

        assert restored is None
        assert controller.current_user is None
        assert fake_auth_service.access_token is None
        assert fake_auth_service.refresh_token is None
        assert fake_db.app_state == {}

    asyncio.run(scenario())

def test_auth_controller_recover_session_crypto_refreshes_sessions_after_recovery(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()
    fake_chat_controller.recover_result = {
        'performed': True,
        'session_id': 'session-2',
        'recovery_action': 'reprovision_device',
    }

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await controller.login('alice', 'secret123')

        result = await controller.recover_session_crypto('session-2')

        assert fake_chat_controller.recover_calls == ['session-2']
        assert fake_chat_controller.refresh_calls == 1
        assert result == {
            'performed': True,
            'session_id': 'session-2',
            'recovery_action': 'reprovision_device',
            'session_snapshot': {
                'authoritative': True,
                'unread_synchronized': True,
            },
        }

    asyncio.run(scenario())


def test_auth_controller_recover_current_session_crypto_skips_refresh_when_not_performed(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()
    fake_chat_controller.recover_result = {
        'performed': False,
        'reason': 'no_recovery_action',
    }

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await controller.login('alice', 'secret123')

        result = await controller.recover_current_session_crypto()

        assert fake_chat_controller.recover_current_calls == 1
        assert fake_chat_controller.refresh_calls == 0
        assert result == {
            'performed': False,
            'reason': 'no_recovery_action',
            'session_snapshot': None,
        }

    asyncio.run(scenario())


def test_auth_controller_execute_session_security_action_refreshes_sessions_after_success(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()
    fake_chat_controller.security_action_result = {
        'performed': True,
        'session_id': 'session-2',
        'action_id': 'trust_peer_identity',
    }
    fake_chat_controller.refresh_result = boundaries.session_manager_module.SessionRefreshResult(
        sessions=[],
        authoritative=True,
        unread_synchronized=False,
    )

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await controller.login('alice', 'secret123')

        result = await controller.execute_session_security_action('session-2', 'trust_peer_identity')

        assert fake_chat_controller.security_action_calls == [('session-2', 'trust_peer_identity')]
        assert fake_chat_controller.refresh_calls == 1
        assert result == {
            'performed': True,
            'session_id': 'session-2',
            'action_id': 'trust_peer_identity',
            'session_snapshot': {
                'authoritative': True,
                'unread_synchronized': False,
            },
        }

    asyncio.run(scenario())


def test_auth_controller_execute_current_session_security_action_skips_refresh_when_not_performed(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()
    fake_chat_controller.security_action_result = {
        'performed': False,
        'session_id': 'session-1',
        'action_id': 'switch_device',
        'reason': 'switch_device_required',
        'explanation': {
            'code': 'switch_device_required',
            'message': 'This encrypted content is addressed to a different device and cannot be recovered on the current device.',
        },
        'external_requirement': {
            'kind': 'switch_device',
            'target_device_id': 'device-bob-2',
            'blocking': True,
        },
    }

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await controller.login('alice', 'secret123')

        result = await controller.execute_current_session_security_action('switch_device')

        assert fake_chat_controller.security_action_current_calls == ['switch_device']
        assert fake_chat_controller.refresh_calls == 0
        assert result == {
            'performed': False,
            'session_id': 'session-1',
            'action_id': 'switch_device',
            'reason': 'switch_device_required',
            'explanation': {
                'code': 'switch_device_required',
                'message': 'This encrypted content is addressed to a different device and cannot be recovered on the current device.',
            },
            'external_requirement': {
                'kind': 'switch_device',
                'target_device_id': 'device-bob-2',
                'blocking': True,
            },
            'session_snapshot': None,
        }

    asyncio.run(scenario())


def test_auth_controller_get_session_identity_verification_requires_auth_and_delegates(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()
    fake_chat_controller.identity_verification_result = {
        'session_id': 'session-2',
        'available': True,
        'verification': {'primary_verification_code_short': '12345 67890 11111'},
    }

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await controller.login('alice', 'secret123')

        result = await controller.get_session_identity_verification('session-2')

        assert fake_chat_controller.identity_verification_calls == ['session-2']
        assert result == {
            'session_id': 'session-2',
            'available': True,
            'verification': {'primary_verification_code_short': '12345 67890 11111'},
        }

    asyncio.run(scenario())


def test_auth_controller_get_current_session_identity_verification_delegates(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()
    fake_chat_controller.identity_verification_result = {
        'session_id': 'session-1',
        'available': False,
        'verification': {},
    }

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await controller.login('alice', 'secret123')

        result = await controller.get_current_session_identity_verification()

        assert fake_chat_controller.identity_verification_current_calls == 1
        assert result == {
            'session_id': 'session-1',
            'available': False,
            'verification': {},
        }

    asyncio.run(scenario())


def test_auth_controller_get_session_identity_review_details_delegates(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()
    fake_chat_controller.identity_review_details_result = {
        'session_id': 'session-2',
        'available': True,
        'timeline': [{'kind': 'trusted'}],
    }

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await controller.login('alice', 'secret123')

        result = await controller.get_session_identity_review_details('session-2')

        assert fake_chat_controller.identity_review_details_calls == ['session-2']
        assert result == {
            'session_id': 'session-2',
            'available': True,
            'timeline': [{'kind': 'trusted'}],
        }

    asyncio.run(scenario())


def test_auth_controller_get_current_session_identity_review_details_delegates(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()
    fake_chat_controller.identity_review_details_result = {
        'session_id': 'session-1',
        'available': False,
        'timeline': [],
    }

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await controller.login('alice', 'secret123')

        result = await controller.get_current_session_identity_review_details()

        assert fake_chat_controller.identity_review_details_current_calls == 1
        assert result == {
            'session_id': 'session-1',
            'available': False,
            'timeline': [],
        }

    asyncio.run(scenario())


def test_auth_controller_get_session_security_diagnostics_delegates(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()
    fake_chat_controller.security_diagnostics_result = {
        'session_id': 'session-2',
        'headline': 'identity_review_required',
    }

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await controller.login('alice', 'secret123')

        result = await controller.get_session_security_diagnostics('session-2')

        assert fake_chat_controller.security_diagnostics_calls == ['session-2']
        assert result == {
            'session_id': 'session-2',
            'headline': 'identity_review_required',
        }

    asyncio.run(scenario())


def test_auth_controller_get_current_session_security_diagnostics_delegates(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()
    fake_chat_controller.security_diagnostics_result = {
        'session_id': 'session-1',
        'headline': 'secure',
    }

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await controller.login('alice', 'secret123')

        result = await controller.get_current_session_security_diagnostics()

        assert fake_chat_controller.security_diagnostics_current_calls == 1
        assert result == {
            'session_id': 'session-1',
            'headline': 'secure',
        }

    asyncio.run(scenario())


def test_auth_controller_get_history_recovery_diagnostics_uses_e2ee_service(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()
    fake_e2ee_service.history_recovery_diagnostics_result = {
        "local_device_id": "device-1",
        "available": True,
        "source_device_count": 1,
        "primary_source_device_id": "device-old-1",
    }

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await controller.login('alice', 'secret123')

        result = await controller.get_history_recovery_diagnostics()

        assert fake_e2ee_service.history_recovery_diagnostics_calls == 1
        assert result == {
            "local_device_id": "device-1",
            "available": True,
            "source_device_count": 1,
            "primary_source_device_id": "device-old-1",
        }

    asyncio.run(scenario())


def test_auth_controller_list_my_e2ee_devices_delegates_to_service(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()
    fake_e2ee_service.list_my_devices_result = [
        {"device_id": "device-1", "device_name": "Desktop"},
        {"device_id": "device-2", "device_name": "Laptop"},
    ]

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await controller.login('alice', 'secret123')
        result = await controller.list_my_e2ee_devices()

        assert fake_e2ee_service.list_my_devices_calls == 1
        assert result == [
            {"device_id": "device-1", "device_name": "Desktop"},
            {"device_id": "device-2", "device_name": "Laptop"},
        ]

    asyncio.run(scenario())


def test_auth_controller_export_history_recovery_package_defaults_to_current_user(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()
    fake_e2ee_service.export_history_recovery_package_result = {
        "scheme": "device-history-recovery-v1",
        "recipient_device_id": "device-new-1",
    }
    fake_e2ee_service.history_recovery_diagnostics_result = {
        "local_device_id": "device-1",
        "available": True,
        "source_device_count": 1,
    }

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await controller.login('alice', 'secret123')
        result = await controller.export_history_recovery_package('device-new-1')

        assert fake_e2ee_service.export_history_recovery_package_calls == [('user-1', 'device-new-1', 'user-1')]
        assert result == {
            'target_user_id': 'user-1',
            'target_device_id': 'device-new-1',
            'package': {
                'scheme': 'device-history-recovery-v1',
                'recipient_device_id': 'device-new-1',
            },
        }
        assert fake_e2ee_service.history_recovery_diagnostics_calls == 0

    asyncio.run(scenario())


def test_auth_controller_import_history_recovery_package_returns_import_result(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()
    fake_e2ee_service.import_history_recovery_package_result = {
        "source_device_id": "device-old-1",
        "available": True,
    }
    fake_e2ee_service.history_recovery_diagnostics_result = {
        "local_device_id": "device-1",
        "available": True,
        "source_device_count": 1,
    }

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await controller.login('alice', 'secret123')
        result = await controller.import_history_recovery_package({'scheme': 'device-history-recovery-v1'})

        assert fake_e2ee_service.import_history_recovery_package_calls == [{'scheme': 'device-history-recovery-v1'}]
        assert result == {
            'source_device_id': 'device-old-1',
            'available': True,
        }
        assert fake_e2ee_service.history_recovery_diagnostics_calls == 0

    asyncio.run(scenario())


def test_auth_controller_get_e2ee_diagnostics_aggregates_runtime_history_and_session(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_db.db_encryption_self_check = {
        'state': 'plain',
        'severity': 'info',
        'can_start': True,
        'action_required': False,
        'message': 'Local database encryption is disabled',
    }
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_chat_controller.security_diagnostics_result = {
        'session_id': 'session-1',
        'headline': 'identity_review_required',
    }
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()
    fake_e2ee_service.history_recovery_diagnostics_result = {
        "local_device_id": "device-1",
        "available": True,
        "source_device_count": 1,
        "primary_source_device_id": "device-old-1",
    }

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await controller.login('alice', 'secret123')

        result = await controller.get_e2ee_diagnostics()

        assert fake_e2ee_service.history_recovery_diagnostics_calls == 1
        assert fake_chat_controller.security_diagnostics_current_calls == 1
        assert result == {
            'authenticated': True,
            'user_id': 'user-1',
            'runtime_security': {
                'authenticated': True,
                'user_id': 'user-1',
                'database_encryption': dict(fake_db.db_encryption_self_check),
            },
            'history_recovery': {
                "local_device_id": "device-1",
                "available": True,
                "source_device_count": 1,
                "primary_source_device_id": "device-old-1",
            },
            'current_session_security': {
                'session_id': 'session-1',
                'headline': 'identity_review_required',
            },
        }

    asyncio.run(scenario())


def test_auth_controller_get_e2ee_diagnostics_tolerates_missing_current_session(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_chat_controller.raise_current_security_diagnostics = True
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        await controller.login('alice', 'secret123')

        result = await controller.get_e2ee_diagnostics()

        assert result['current_session_security'] == {
            'available': False,
            'reason': 'no current session selected',
        }

    asyncio.run(scenario())


def test_auth_controller_runtime_security_status_exposes_database_self_check(monkeypatch) -> None:
    fake_auth_service = boundaries.FakeAuthService()
    fake_user_service = boundaries.FakeUserService()
    fake_db = boundaries.FakeDatabase()
    fake_db.db_encryption_self_check = {
        'state': 'runtime_missing',
        'severity': 'warning',
        'can_start': True,
        'action_required': True,
        'message': 'SQLCipher key material is ready, but the current runtime does not provide SQLCipher support',
    }
    fake_message_manager = boundaries.FakeMessageManager()
    fake_chat_controller = boundaries.FakeChatControllerContext()
    fake_file_service = boundaries.FakeFileService()
    fake_e2ee_service = FakeE2EEService()

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        before_login = controller.get_runtime_security_status()
        await controller.login('alice', 'secret123')
        after_login = controller.get_runtime_security_status()

        assert before_login == {
            'authenticated': False,
            'user_id': '',
            'database_encryption': dict(fake_db.db_encryption_self_check),
        }
        assert after_login == {
            'authenticated': True,
            'user_id': 'user-1',
            'database_encryption': dict(fake_db.db_encryption_self_check),
        }

    asyncio.run(scenario())
