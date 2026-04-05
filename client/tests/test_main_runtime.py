from __future__ import annotations

import asyncio
import importlib
import sys
import types


class _FakeQtApp:
    def processEvents(self) -> None:
        return None

    def quit(self) -> None:
        return None


class _FakeDatabase:
    def __init__(self, self_check: dict[str, object]) -> None:
        self.self_check = dict(self_check)
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    def get_db_encryption_self_check(self) -> dict[str, object]:
        return dict(self.self_check)


class _FakeConnectionManager:
    def __init__(self) -> None:
        self.initialized = False
        self.listeners: list[object] = []

    async def initialize(self) -> None:
        self.initialized = True

    def add_message_listener(self, listener) -> None:
        self.listeners.append(listener)


class _FakeInitializable:
    def __init__(self) -> None:
        self.initialized = False

    async def initialize(self) -> None:
        self.initialized = True


class _FakeAuthController:
    def __init__(
        self,
        restored_user: dict[str, object] | None,
        runtime_status: dict[str, object],
        e2ee_diagnostics: dict[str, object] | None = None,
    ) -> None:
        self._restored_user = restored_user
        self._runtime_status = dict(runtime_status)
        self._e2ee_diagnostics = dict(
            e2ee_diagnostics
            or {
                "authenticated": bool((restored_user or {}).get("id")),
                "user_id": str((restored_user or {}).get("id", "") or ""),
                "runtime_security": dict(runtime_status),
                "history_recovery": {"available": False, "source_device_count": 0},
                "current_session_security": {"available": False, "reason": "no current session selected"},
            }
        )
        self.restore_calls = 0

    async def restore_session(self) -> dict[str, object] | None:
        self.restore_calls += 1
        return dict(self._restored_user or {}) if self._restored_user else None

    def get_runtime_security_status(self) -> dict[str, object]:
        return dict(self._runtime_status)

    async def get_e2ee_diagnostics(self) -> dict[str, object]:
        return dict(self._e2ee_diagnostics)


def _load_main_module():
    for module_name in (
        "client.main",
        "client.storage.database",
        "client.network.http_client",
        "client.network.websocket_client",
        "client.managers.connection_manager",
        "client.managers.message_manager",
        "client.managers.session_manager",
        "client.managers.sound_manager",
        "client.ui.controllers.auth_controller",
        "client.ui.controllers.chat_controller",
        "client.ui.controllers.message_controller",
        "client.ui.controllers.session_controller",
        "client.ui.windows",
        "client.ui.windows.auth_interface",
        "client.core.config",
        "client.core.i18n",
    ):
        sys.modules.pop(module_name, None)

    qtcore = sys.modules.get("PySide6.QtCore")
    if qtcore is None:
        qtcore = types.ModuleType("PySide6.QtCore")
        sys.modules["PySide6.QtCore"] = qtcore
    if not hasattr(qtcore, "QLockFile"):
        qtcore.QLockFile = type("QLockFile", (), {})
    if not hasattr(qtcore, "QTimer"):
        qtcore.QTimer = type("QTimer", (), {"singleShot": staticmethod(lambda *args, **kwargs: None)})

    qtwidgets = sys.modules.get("PySide6.QtWidgets")
    if qtwidgets is None:
        qtwidgets = types.ModuleType("PySide6.QtWidgets")
        sys.modules["PySide6.QtWidgets"] = qtwidgets
    if not hasattr(qtwidgets, "QApplication"):
        qtwidgets.QApplication = type("QApplication", (), {})
    if not hasattr(qtwidgets, "QMessageBox"):
        qtwidgets.QMessageBox = type("QMessageBox", (), {"information": staticmethod(lambda *args, **kwargs: None)})

    pyside = sys.modules.get("PySide6")
    if pyside is None:
        pyside = types.ModuleType("PySide6")
        sys.modules["PySide6"] = pyside
    if not hasattr(pyside, "QtCore"):
        pyside.QtCore = qtcore
    if not hasattr(pyside, "QtWidgets"):
        pyside.QtWidgets = qtwidgets

    qtgui = sys.modules.get("PySide6.QtGui")
    if qtgui is None:
        qtgui = types.ModuleType("PySide6.QtGui")
        sys.modules["PySide6.QtGui"] = qtgui
    if not hasattr(pyside, "QtGui"):
        pyside.QtGui = qtgui

    qasync = sys.modules.get("qasync")
    if qasync is None:
        qasync = types.ModuleType("qasync")
        sys.modules["qasync"] = qasync
    if not hasattr(qasync, "QEventLoop"):
        qasync.QEventLoop = type("QEventLoop", (), {})

    qfluentwidgets = sys.modules.get("qfluentwidgets")
    if qfluentwidgets is None:
        qfluentwidgets = types.ModuleType("qfluentwidgets")
        sys.modules["qfluentwidgets"] = qfluentwidgets
    if not hasattr(qfluentwidgets, "InfoBar"):
        qfluentwidgets.InfoBar = type("InfoBar", (), {"success": staticmethod(lambda *args, **kwargs: None)})
    if not hasattr(qfluentwidgets, "setTheme"):
        qfluentwidgets.setTheme = lambda *args, **kwargs: None
    if not hasattr(qfluentwidgets, "setThemeColor"):
        qfluentwidgets.setThemeColor = lambda *args, **kwargs: None

    config_module = types.ModuleType("client.core.config")
    config_module.cfg = types.SimpleNamespace(get=lambda *args, **kwargs: None)
    sys.modules["client.core.config"] = config_module

    i18n_module = types.ModuleType("client.core.i18n")
    i18n_module.initialize_i18n = lambda *args, **kwargs: None
    i18n_module.tr = lambda _key, default="", *args, **kwargs: default
    sys.modules["client.core.i18n"] = i18n_module

    auth_interface_module = types.ModuleType("client.ui.windows.auth_interface")
    auth_interface_module.AuthInterface = type("AuthInterface", (), {})
    windows_package = types.ModuleType("client.ui.windows")
    windows_package.__path__ = []
    windows_package.auth_interface = auth_interface_module
    sys.modules["client.ui.windows"] = windows_package
    sys.modules["client.ui.windows.auth_interface"] = auth_interface_module

    def _install_stub(module_name: str, **attributes) -> None:
        module = types.ModuleType(module_name)
        for key, value in attributes.items():
            setattr(module, key, value)
        sys.modules[module_name] = module

    _install_stub(
        "client.storage.database",
        get_database=lambda: None,
        peek_database=lambda: None,
    )
    _install_stub(
        "client.network.http_client",
        get_http_client=lambda: None,
        peek_http_client=lambda: None,
    )
    _install_stub(
        "client.network.websocket_client",
        get_websocket_client=lambda: None,
        peek_websocket_client=lambda: None,
    )
    _install_stub(
        "client.managers.connection_manager",
        get_connection_manager=lambda: None,
        peek_connection_manager=lambda: None,
    )
    _install_stub(
        "client.managers.message_manager",
        get_message_manager=lambda: None,
        peek_message_manager=lambda: None,
    )
    _install_stub(
        "client.managers.session_manager",
        get_session_manager=lambda: None,
        peek_session_manager=lambda: None,
    )
    _install_stub(
        "client.managers.sound_manager",
        get_sound_manager=lambda: None,
        peek_sound_manager=lambda: None,
    )
    _install_stub(
        "client.ui.controllers.auth_controller",
        get_auth_controller=lambda: None,
        peek_auth_controller=lambda: None,
    )
    _install_stub(
        "client.ui.controllers.chat_controller",
        get_chat_controller=lambda: None,
        peek_chat_controller=lambda: None,
    )
    _install_stub(
        "client.ui.controllers.message_controller",
        peek_message_controller=lambda: None,
    )
    _install_stub(
        "client.ui.controllers.session_controller",
        peek_session_controller=lambda: None,
    )

    main_module = importlib.import_module("client.main")
    return importlib.reload(main_module)


def test_application_initialize_caches_startup_security_status(monkeypatch) -> None:
    main_module = _load_main_module()
    db_self_check = {
        "state": "runtime_missing",
        "severity": "warning",
        "can_start": True,
        "action_required": True,
        "message": "SQLCipher key material is ready, but the current runtime does not provide SQLCipher support",
    }
    fake_db = _FakeDatabase(db_self_check)
    fake_connection_manager = _FakeConnectionManager()
    fake_message_manager = _FakeInitializable()
    fake_session_manager = _FakeInitializable()
    fake_chat_controller = _FakeInitializable()
    fake_sound_manager = _FakeInitializable()

    monkeypatch.setattr(main_module, "get_database", lambda: fake_db)
    monkeypatch.setattr(main_module, "get_http_client", lambda: object())
    monkeypatch.setattr(main_module, "get_websocket_client", lambda: object())
    monkeypatch.setattr(main_module, "get_connection_manager", lambda: fake_connection_manager)
    monkeypatch.setattr(main_module, "get_message_manager", lambda: fake_message_manager)
    monkeypatch.setattr(main_module, "get_session_manager", lambda: fake_session_manager)
    monkeypatch.setattr(main_module, "get_chat_controller", lambda: fake_chat_controller)
    monkeypatch.setattr(main_module, "get_sound_manager", lambda: fake_sound_manager)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        await app.initialize()

        assert fake_db.connected is True
        assert fake_connection_manager.initialized is True
        assert len(fake_connection_manager.listeners) == 1
        assert fake_message_manager.initialized is True
        assert fake_session_manager.initialized is True
        assert fake_chat_controller.initialized is True
        assert fake_sound_manager.initialized is True
        assert app.get_startup_security_status() == {
            "authenticated": False,
            "user_id": "",
            "database_encryption": dict(db_self_check),
        }
        assert app.get_e2ee_runtime_diagnostics() == {
            "authenticated": False,
            "user_id": "",
            "runtime_security": {
                "authenticated": False,
                "user_id": "",
                "database_encryption": dict(db_self_check),
            },
            "history_recovery": {
                "available": False,
                "source_device_count": 0,
            },
            "current_session_security": {
                "available": False,
                "reason": "authentication required",
            },
        }
        assert app.get_exit_code() == main_module.EXIT_CODE_OK
        assert app.get_startup_preflight_result() == {
            "can_continue": True,
            "blocking": False,
            "action_required": True,
            "state": "runtime_missing",
            "severity": "warning",
            "message": db_self_check["message"],
            "runtime_security": {
                "authenticated": False,
                "user_id": "",
                "database_encryption": dict(db_self_check),
            },
        }

    asyncio.run(scenario())


def test_application_authenticate_updates_startup_security_status_from_auth_context(monkeypatch) -> None:
    main_module = _load_main_module()
    runtime_status = {
        "authenticated": True,
        "user_id": "user-1",
        "database_encryption": {
            "state": "sqlcipher_active",
            "severity": "ok",
            "can_start": True,
            "action_required": False,
            "message": "SQLCipher is active for the local database",
        },
    }
    e2ee_diagnostics = {
        "authenticated": True,
        "user_id": "user-1",
        "runtime_security": dict(runtime_status),
        "history_recovery": {
            "available": True,
            "source_device_count": 1,
            "primary_source_device_id": "device-old-1",
        },
        "current_session_security": {
            "session_id": "session-1",
            "headline": "secure",
        },
    }
    fake_auth_controller = _FakeAuthController(
        {"id": "user-1", "username": "alice"},
        runtime_status,
        e2ee_diagnostics,
    )

    monkeypatch.setattr(main_module, "get_auth_controller", lambda: fake_auth_controller)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        authenticated = await app.authenticate()

        assert authenticated is True
        assert fake_auth_controller.restore_calls == 1
        assert app.get_startup_security_status() == runtime_status
        assert app.get_e2ee_runtime_diagnostics() == e2ee_diagnostics
        assert app.get_exit_code() == main_module.EXIT_CODE_OK
        assert app.get_startup_preflight_result() == {
            "can_continue": True,
            "blocking": False,
            "action_required": False,
            "state": "sqlcipher_active",
            "severity": "ok",
            "message": "SQLCipher is active for the local database",
            "runtime_security": runtime_status,
        }

    asyncio.run(scenario())


def test_application_preflight_marks_blocking_database_state(monkeypatch) -> None:
    main_module = _load_main_module()
    db_self_check = {
        "state": "provider_mismatch",
        "severity": "error",
        "can_start": False,
        "action_required": True,
        "message": "Configured DB encryption provider does not match the current runtime provider",
    }
    fake_db = _FakeDatabase(db_self_check)
    fake_connection_manager = _FakeConnectionManager()
    fake_message_manager = _FakeInitializable()
    fake_session_manager = _FakeInitializable()
    fake_chat_controller = _FakeInitializable()
    fake_sound_manager = _FakeInitializable()

    monkeypatch.setattr(main_module, "get_database", lambda: fake_db)
    monkeypatch.setattr(main_module, "get_http_client", lambda: object())
    monkeypatch.setattr(main_module, "get_websocket_client", lambda: object())
    monkeypatch.setattr(main_module, "get_connection_manager", lambda: fake_connection_manager)
    monkeypatch.setattr(main_module, "get_message_manager", lambda: fake_message_manager)
    monkeypatch.setattr(main_module, "get_session_manager", lambda: fake_session_manager)
    monkeypatch.setattr(main_module, "get_chat_controller", lambda: fake_chat_controller)
    monkeypatch.setattr(main_module, "get_sound_manager", lambda: fake_sound_manager)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        await app.initialize()

        assert app.get_startup_preflight_result() == {
            "can_continue": False,
            "blocking": True,
            "action_required": True,
            "state": "provider_mismatch",
            "severity": "error",
            "message": db_self_check["message"],
            "runtime_security": {
                "authenticated": False,
                "user_id": "",
                "database_encryption": dict(db_self_check),
            },
        }

    asyncio.run(scenario())


def test_application_run_stops_before_auth_when_preflight_blocks(monkeypatch) -> None:
    main_module = _load_main_module()
    db_self_check = {
        "state": "provider_mismatch",
        "severity": "error",
        "can_start": False,
        "action_required": True,
        "message": "Configured DB encryption provider does not match the current runtime provider",
    }
    fake_db = _FakeDatabase(db_self_check)
    fake_connection_manager = _FakeConnectionManager()
    fake_message_manager = _FakeInitializable()
    fake_session_manager = _FakeInitializable()
    fake_chat_controller = _FakeInitializable()
    fake_sound_manager = _FakeInitializable()

    monkeypatch.setattr(main_module, "get_database", lambda: fake_db)
    monkeypatch.setattr(main_module, "get_http_client", lambda: object())
    monkeypatch.setattr(main_module, "get_websocket_client", lambda: object())
    monkeypatch.setattr(main_module, "get_connection_manager", lambda: fake_connection_manager)
    monkeypatch.setattr(main_module, "get_message_manager", lambda: fake_message_manager)
    monkeypatch.setattr(main_module, "get_session_manager", lambda: fake_session_manager)
    monkeypatch.setattr(main_module, "get_chat_controller", lambda: fake_chat_controller)
    monkeypatch.setattr(main_module, "get_sound_manager", lambda: fake_sound_manager)

    auth_calls = {"count": 0}
    show_calls = {"count": 0}

    async def fake_authenticate() -> bool:
        auth_calls["count"] += 1
        return True

    async def fake_show_main_window() -> None:
        show_calls["count"] += 1

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        app.authenticate = fake_authenticate  # type: ignore[method-assign]
        app.show_main_window = fake_show_main_window  # type: ignore[method-assign]
        await app.run()

        assert auth_calls["count"] == 0
        assert show_calls["count"] == 0
        assert app.get_startup_preflight_result()["blocking"] is True
        assert app.get_exit_code() == main_module.EXIT_CODE_STARTUP_PREFLIGHT_BLOCKED

    asyncio.run(scenario())


def test_show_startup_preflight_block_dialog_uses_preflight_message(monkeypatch) -> None:
    main_module = _load_main_module()
    recorded: dict[str, object] = {}

    class _FakeMessageBox:
        @staticmethod
        def information(parent, title: str, message: str) -> None:
            recorded["parent"] = parent
            recorded["title"] = title
            recorded["message"] = message

    monkeypatch.setattr(main_module, "QMessageBox", _FakeMessageBox)

    main_module._show_startup_preflight_block_dialog(
        {
            "state": "provider_mismatch",
            "message": "Configured DB encryption provider does not match the current runtime provider",
        }
    )

    assert recorded == {
        "parent": None,
        "title": "Startup blocked",
        "message": (
            "AssistIM could not start because one startup safety check failed.\n\n"
            "[provider_mismatch] Configured DB encryption provider does not match the current runtime provider"
        ),
    }
