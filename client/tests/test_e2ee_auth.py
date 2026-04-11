from __future__ import annotations

import asyncio

from client.tests import test_service_boundaries as boundaries
from client.ui.controllers import auth_controller as auth_controller_module


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

        assert user["id"] == "user-1"
        assert fake_e2ee_service.calls == 1

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
