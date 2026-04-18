from __future__ import annotations

import asyncio
import importlib
import sys
import types

import pytest


_MISSING_MODULE = object()
_MAIN_RUNTIME_STUB_MODULES = (
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
)


@pytest.fixture(autouse=True)
def _restore_main_runtime_stubs():
    original_modules = {
        module_name: sys.modules.get(module_name, _MISSING_MODULE)
        for module_name in _MAIN_RUNTIME_STUB_MODULES
    }
    yield
    for module_name, module in original_modules.items():
        if module is _MISSING_MODULE:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = module


class _FakeQtApp:
    def __init__(self) -> None:
        self.process_events_calls = 0
        self.quit_calls = 0

    def processEvents(self) -> None:
        self.process_events_calls += 1

    def quit(self) -> None:
        self.quit_calls += 1


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
        self.state_listeners: list[object] = []
        self.connect_calls = 0
        self.wait_for_initial_sync_calls = 0
        self.connect_gate: asyncio.Future[None] | None = None
        self.sync_gate: asyncio.Future[None] | None = None

    async def initialize(self) -> None:
        self.initialized = True

    def add_message_listener(self, listener) -> None:
        self.listeners.append(listener)

    def add_state_listener(self, listener) -> None:
        self.state_listeners.append(listener)

    async def connect(self) -> bool:
        self.connect_calls += 1
        if self.connect_gate is not None:
            await self.connect_gate
        return True

    async def wait_for_initial_sync(self) -> None:
        self.wait_for_initial_sync_calls += 1
        if self.sync_gate is not None:
            await self.sync_gate


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
        self.current_user = dict(restored_user or {}) if restored_user else None
        self._runtime_status = dict(runtime_status)
        self.pending_authoritative_profile_refresh = False
        self.authoritative_profile_refresh_calls = 0
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

    async def refresh_current_user_profile_if_needed(self) -> dict[str, object] | None:
        self.authoritative_profile_refresh_calls += 1
        if not self.pending_authoritative_profile_refresh:
            return None
        self.pending_authoritative_profile_refresh = False
        refreshed_user = dict(self.current_user or {"id": "user-1"})
        refreshed_user.setdefault("username", "alice")
        refreshed_user["nickname"] = str(refreshed_user.get("nickname") or "Alice authoritative")
        self.current_user = dict(refreshed_user)
        return refreshed_user


class _FakeAuthControllerForLogout:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def logout(self, *, clear_local_chat_state: bool = True) -> None:
        self._events.append(f"logout(clear_local_chat_state={clear_local_chat_state})")

    async def clear_session(self, *, clear_local_chat_state: bool = True) -> None:
        self._events.append(f"clear_session(clear_local_chat_state={clear_local_chat_state})")

    async def close(self) -> None:
        self._events.append("auth_controller.close")

class _FakeSignal:
    def __init__(self) -> None:
        self._callbacks: list[object] = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args, **kwargs) -> None:
        for callback in list(self._callbacks):
            callback(*args, **kwargs)


class _FakeAuthInterfaceWindow:
    instances: list["_FakeAuthInterfaceWindow"] = []

    def __init__(self) -> None:
        self.authenticated = _FakeSignal()
        self.closed = _FakeSignal()
        self.last_success_message = ""
        self._auth_committed = False
        self.deleted = False
        self.closed_via_close = False
        self.shown = False
        _FakeAuthInterfaceWindow.instances.append(self)

    def show(self) -> None:
        self.shown = True

    def raise_(self) -> None:
        return None

    def activateWindow(self) -> None:
        return None

    def deleteLater(self) -> None:
        self.deleted = True

    def close(self) -> None:
        self.closed_via_close = True

    def has_committed_auth(self) -> bool:
        return self._auth_committed


class _DeferredRestoreAuthController(_FakeAuthController):
    def __init__(self, runtime_status: dict[str, object]) -> None:
        super().__init__(None, runtime_status)
        self.restore_waiters: list[asyncio.Future] = []

    async def restore_session(self) -> dict[str, object] | None:
        self.restore_calls += 1
        waiter = asyncio.get_running_loop().create_future()
        self.restore_waiters.append(waiter)
        return await waiter


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
    if not hasattr(qtcore, "QDate"):
        class _FakeQDate:
            @staticmethod
            def currentDate():
                return _FakeQDate()

            def toString(self, _fmt=None):
                return "2026-04-12"

        qtcore.QDate = _FakeQDate

    qtwidgets = sys.modules.get("PySide6.QtWidgets")
    if qtwidgets is None:
        qtwidgets = types.ModuleType("PySide6.QtWidgets")
        sys.modules["PySide6.QtWidgets"] = qtwidgets
    if not hasattr(qtwidgets, "QApplication"):
        qtwidgets.QApplication = type("QApplication", (), {})
    if not hasattr(qtwidgets, "QMessageBox"):
        qtwidgets.QMessageBox = type("QMessageBox", (), {"information": staticmethod(lambda *args, **kwargs: None)})
    if not hasattr(qtwidgets, "QPushButton"):
        class _FakeButtonSignal:
            def connect(self, callback):
                self._callback = callback

        class _FakePushButton:
            def __init__(self, *args, **kwargs):
                self.clicked = _FakeButtonSignal()

        qtwidgets.QPushButton = _FakePushButton

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
        qfluentwidgets.InfoBar = type(
            "InfoBar",
            (),
            {
                "success": staticmethod(lambda *args, **kwargs: None),
                "warning": staticmethod(lambda *args, **kwargs: None),
            },
        )
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


def _auth_result(main_module, *, attempt: int = 1, runtime_generation: int | None = None, authenticated: bool) -> object:
    generation = runtime_generation if runtime_generation is not None else (attempt if authenticated else 0)
    return main_module.AuthAttemptResult(
        attempt_generation=attempt,
        runtime_generation=generation,
        authenticated=authenticated,
    )


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
        assert fake_connection_manager.initialized is False
        assert fake_connection_manager.listeners == []
        assert fake_message_manager.initialized is False
        assert fake_session_manager.initialized is False
        assert fake_chat_controller.initialized is False
        assert fake_sound_manager.initialized is False
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


def test_application_initialize_authenticated_runtime_builds_chat_stack_after_auth(monkeypatch) -> None:
    main_module = _load_main_module()
    fake_connection_manager = _FakeConnectionManager()
    fake_sound_manager = _FakeInitializable()
    fake_auth_controller = _FakeAuthController(
        {"id": "user-1", "username": "alice"},
        {
            "authenticated": True,
            "user_id": "user-1",
            "database_encryption": {
                "state": "sqlcipher_active",
                "severity": "ok",
                "can_start": True,
                "action_required": False,
                "message": "SQLCipher is active for the local database",
            },
        },
    )

    class _FakeChatRuntime(_FakeInitializable):
        def __init__(self) -> None:
            super().__init__()
            self.user_ids: list[str] = []

        def set_user_id(self, user_id: str) -> None:
            self.user_ids.append(user_id)

    fake_chat_runtime = _FakeChatRuntime()

    monkeypatch.setattr(main_module, "get_websocket_client", lambda: object())
    monkeypatch.setattr(main_module, "get_connection_manager", lambda: fake_connection_manager)
    monkeypatch.setattr(main_module, "get_auth_controller", lambda: fake_auth_controller)
    monkeypatch.setattr(main_module, "get_chat_controller", lambda: fake_chat_runtime)
    monkeypatch.setattr(main_module, "get_sound_manager", lambda: fake_sound_manager)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        generation = app._start_new_runtime_generation()
        await app.initialize_authenticated_runtime(generation=generation)

        assert fake_connection_manager.initialized is True
        assert len(fake_connection_manager.listeners) == 1
        assert len(fake_connection_manager.state_listeners) == 1
        assert fake_chat_runtime.user_ids == ["user-1"]
        assert fake_chat_runtime.initialized is True
        assert fake_sound_manager.initialized is True

    asyncio.run(scenario())


def test_application_connection_state_listener_degrades_ready_runtime() -> None:
    main_module = _load_main_module()

    class _State:
        def __init__(self, name: str) -> None:
            self.name = name

        def __str__(self) -> str:
            return self.name

    app = main_module.Application(_FakeQtApp())
    app._set_lifecycle_state("authenticated_ready")

    app._handle_connection_state_change(_State("CONNECTED"), _State("DISCONNECTED"))

    assert app._realtime_connection_state == "disconnected"
    assert app._lifecycle_state == "authenticated_degraded"


def test_application_start_background_services_waits_for_initial_sync(monkeypatch) -> None:
    main_module = _load_main_module()
    fake_connection_manager = _FakeConnectionManager()

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        fake_connection_manager.connect_gate = loop.create_future()
        fake_connection_manager.sync_gate = loop.create_future()
        monkeypatch.setattr(main_module, "get_connection_manager", lambda: fake_connection_manager)

        app = main_module.Application(_FakeQtApp())
        generation = app._start_new_runtime_generation()
        task = asyncio.create_task(app.start_background_services(generation=generation))

        await asyncio.sleep(0)
        assert task.done() is False
        assert fake_connection_manager.connect_calls == 1
        assert fake_connection_manager.wait_for_initial_sync_calls == 0

        fake_connection_manager.connect_gate.set_result(None)
        await asyncio.sleep(0)
        assert task.done() is False
        assert fake_connection_manager.wait_for_initial_sync_calls == 1

        fake_connection_manager.sync_gate.set_result(None)
        await task

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
        auth_result = await app.authenticate()

        assert auth_result.authenticated is True
        assert auth_result.attempt_generation == 1
        assert auth_result.runtime_generation == 1
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


def test_application_e2ee_diagnostics_clear_when_auth_context_is_unauthenticated(monkeypatch) -> None:
    main_module = _load_main_module()
    runtime_status = {
        "authenticated": False,
        "user_id": "",
        "database_encryption": {
            "state": "sqlcipher_active",
            "severity": "ok",
            "can_start": True,
            "action_required": False,
            "message": "SQLCipher is active for the local database",
        },
    }
    stale_diagnostics = {
        "authenticated": True,
        "user_id": "old-user",
        "runtime_security": {
            "authenticated": True,
            "user_id": "old-user",
            "database_encryption": dict(runtime_status["database_encryption"]),
        },
        "history_recovery": {"available": True, "source_device_count": 2},
        "current_session_security": {"session_id": "old-session", "headline": "secure"},
    }
    fake_auth_controller = _FakeAuthController(None, runtime_status, stale_diagnostics)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        app._startup_security_status = {
            "authenticated": True,
            "user_id": "old-user",
            "database_encryption": dict(runtime_status["database_encryption"]),
        }
        app._e2ee_runtime_diagnostics = dict(stale_diagnostics)

        diagnostics = await app._update_e2ee_runtime_diagnostics(auth_controller=fake_auth_controller)

        assert diagnostics == {
            "authenticated": False,
            "user_id": "",
            "runtime_security": runtime_status,
            "history_recovery": {
                "available": False,
                "source_device_count": 0,
            },
            "current_session_security": {
                "available": False,
                "reason": "authentication required",
            },
        }
        assert app.get_startup_security_status() == runtime_status

    asyncio.run(scenario())


def test_application_authenticate_ignores_stale_auth_window_callbacks(monkeypatch) -> None:
    main_module = _load_main_module()
    _FakeAuthInterfaceWindow.instances.clear()
    runtime_status = {
        "authenticated": False,
        "user_id": "",
        "database_encryption": {
            "state": "plain",
            "severity": "info",
            "can_start": True,
            "action_required": False,
            "message": "Local database encryption is disabled",
        },
    }
    fake_auth_controller = _FakeAuthController(None, runtime_status)

    monkeypatch.setattr(main_module, "get_auth_controller", lambda: fake_auth_controller)
    monkeypatch.setattr(main_module, "AuthInterface", _FakeAuthInterfaceWindow)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())

        first_attempt = asyncio.create_task(app.authenticate())
        await asyncio.sleep(0)
        first_window = _FakeAuthInterfaceWindow.instances[-1]
        first_window.closed.emit()

        first_result = await first_attempt
        assert first_result.authenticated is False
        assert first_result.attempt_generation == 1
        assert app.auth_window is None
        assert first_window.deleted is True

        second_attempt = asyncio.create_task(app.authenticate())
        await asyncio.sleep(0)
        second_window = _FakeAuthInterfaceWindow.instances[-1]
        second_window.last_success_message = "second-attempt-message"

        first_window.authenticated.emit({"id": "user-stale"})
        await asyncio.sleep(0)

        assert app._pending_auth_success_message == ""
        assert second_attempt.done() is False

        second_window.closed.emit()
        second_result = await second_attempt
        assert second_result.authenticated is False
        assert second_result.attempt_generation == 2
        assert app._pending_auth_success_message == ""

    asyncio.run(scenario())


def test_application_authenticate_ignores_stale_restore_success_after_newer_attempt(monkeypatch) -> None:
    main_module = _load_main_module()
    _FakeAuthInterfaceWindow.instances.clear()
    runtime_status = {
        "authenticated": False,
        "user_id": "",
        "database_encryption": {
            "state": "plain",
            "severity": "info",
            "can_start": True,
            "action_required": False,
            "message": "Local database encryption is disabled",
        },
    }
    fake_auth_controller = _DeferredRestoreAuthController(runtime_status)

    monkeypatch.setattr(main_module, "get_auth_controller", lambda: fake_auth_controller)
    monkeypatch.setattr(main_module, "AuthInterface", _FakeAuthInterfaceWindow)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())

        first_attempt = asyncio.create_task(app.authenticate())
        await asyncio.sleep(0)
        assert len(fake_auth_controller.restore_waiters) == 1

        second_attempt = asyncio.create_task(app.authenticate())
        await asyncio.sleep(0)
        assert len(fake_auth_controller.restore_waiters) == 2

        fake_auth_controller.restore_waiters[0].set_result({"id": "user-stale", "username": "stale"})
        first_result = await first_attempt
        assert first_result.authenticated is False
        assert first_result.attempt_generation == 1
        assert app._active_runtime_generation == 0
        assert app._pending_auth_success_message == ""

        fake_auth_controller.restore_waiters[1].set_result(None)
        await asyncio.sleep(0)
        second_window = _FakeAuthInterfaceWindow.instances[-1]
        assert second_window.shown is True

        second_window.closed.emit()
        second_result = await second_attempt
        assert second_result.authenticated is False
        assert second_result.attempt_generation == 2
        assert app._active_runtime_generation == 0
        assert app._pending_auth_success_message == ""

    asyncio.run(scenario())


def test_application_authenticate_ignores_close_after_auth_commit(monkeypatch) -> None:
    main_module = _load_main_module()
    _FakeAuthInterfaceWindow.instances.clear()
    runtime_status = {
        "authenticated": True,
        "user_id": "user-1",
        "database_encryption": {
            "state": "plain",
            "severity": "info",
            "can_start": True,
            "action_required": False,
            "message": "Local database encryption is disabled",
        },
    }
    fake_auth_controller = _FakeAuthController(None, runtime_status)

    monkeypatch.setattr(main_module, "get_auth_controller", lambda: fake_auth_controller)
    monkeypatch.setattr(main_module, "AuthInterface", _FakeAuthInterfaceWindow)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())

        attempt = asyncio.create_task(app.authenticate())
        await asyncio.sleep(0)
        auth_window = _FakeAuthInterfaceWindow.instances[-1]
        auth_window.last_success_message = "welcome"
        auth_window._auth_committed = True
        fake_auth_controller.current_user = {"id": "user-1", "username": "alice"}

        auth_window.closed.emit()
        await asyncio.sleep(0)
        assert attempt.done() is False

        auth_window.authenticated.emit({"id": "user-1", "username": "alice"})
        result = await attempt

        assert result.authenticated is True
        assert app._pending_auth_success_message == "welcome"
        assert app.auth_window is auth_window
        assert auth_window.deleted is False

    asyncio.run(scenario())


def test_application_auth_shell_stays_visible_until_main_window_is_shown(monkeypatch) -> None:
    main_module = _load_main_module()
    _FakeAuthInterfaceWindow.instances.clear()
    runtime_status = {
        "authenticated": True,
        "user_id": "user-1",
        "database_encryption": {
            "state": "plain",
            "severity": "info",
            "can_start": True,
            "action_required": False,
            "message": "Local database encryption is disabled",
        },
    }
    fake_auth_controller = _FakeAuthController(None, runtime_status)
    scheduled_callbacks: list[object] = []

    class _FakeMainWindow:
        def __init__(self) -> None:
            self.closed = _FakeSignal()
            self.logoutRequested = _FakeSignal()
            self.runtimeRefreshRequested = _FakeSignal()

        def restore_default_geometry(self) -> None:
            return None

        def show(self) -> None:
            return None

        def showNormal(self) -> None:
            return None

        def raise_(self) -> None:
            return None

        def activateWindow(self) -> None:
            return None

    class _FakeQTimer:
        @staticmethod
        def singleShot(_delay: int, callback) -> None:
            scheduled_callbacks.append(callback)

    fake_main_window_module = types.ModuleType("client.ui.windows.main_window")
    fake_main_window_module.MainWindow = _FakeMainWindow

    monkeypatch.setattr(main_module, "get_auth_controller", lambda: fake_auth_controller)
    monkeypatch.setattr(main_module, "AuthInterface", _FakeAuthInterfaceWindow)
    monkeypatch.setitem(sys.modules, "client.ui.windows.main_window", fake_main_window_module)
    monkeypatch.setattr(main_module, "QTimer", _FakeQTimer)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())

        attempt = asyncio.create_task(app.authenticate())
        await asyncio.sleep(0)
        auth_window = _FakeAuthInterfaceWindow.instances[-1]
        auth_window.last_success_message = "welcome"
        auth_window._auth_committed = True

        auth_window.authenticated.emit({"id": "user-1", "username": "alice"})
        result = await attempt

        assert result.authenticated is True
        assert app.auth_window is auth_window
        assert auth_window.closed_via_close is False
        assert auth_window.deleted is False

        def fake_create_task(coro):
            coro.close()
            return "warm-task"

        app.create_task = fake_create_task  # type: ignore[method-assign]
        await app.show_main_window(generation=result.runtime_generation)

        assert auth_window.closed_via_close is True
        assert auth_window.deleted is True
        assert app.auth_window is None
        assert len(scheduled_callbacks) == 4

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

    async def fake_authenticate():
        auth_calls["count"] += 1
        return _auth_result(main_module, authenticated=True)

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


def test_application_run_shows_startup_preflight_dialog_before_shutdown(monkeypatch) -> None:
    main_module = _load_main_module()
    db_self_check = {
        "state": "provider_mismatch",
        "severity": "error",
        "can_start": False,
        "action_required": True,
        "message": "Configured DB encryption provider does not match the current runtime provider",
    }
    fake_db = _FakeDatabase(db_self_check)
    events: list[str] = []

    monkeypatch.setattr(main_module, "get_database", lambda: fake_db)
    monkeypatch.setattr(main_module, "get_http_client", lambda: object())
    monkeypatch.setattr(
        main_module,
        "_show_startup_preflight_block_dialog",
        lambda preflight: events.append(f"dialog({preflight.get('state')})"),
    )

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())

        async def fail_authenticate():
            events.append("authenticate")
            raise AssertionError("authenticate should not run when preflight blocks")

        async def fake_shutdown() -> None:
            events.append("shutdown")

        app.authenticate = fail_authenticate  # type: ignore[method-assign]
        app.shutdown = fake_shutdown  # type: ignore[method-assign]

        await app.run()

        assert events == ["dialog(provider_mismatch)", "shutdown"]
        assert app.get_exit_code() == main_module.EXIT_CODE_STARTUP_PREFLIGHT_BLOCKED

    asyncio.run(scenario())


def test_application_run_initializes_authenticated_runtime_only_after_auth(monkeypatch) -> None:
    main_module = _load_main_module()
    db_self_check = {
        "state": "plain",
        "severity": "info",
        "can_start": True,
        "action_required": False,
        "message": "Local database encryption is disabled",
    }
    fake_db = _FakeDatabase(db_self_check)
    fake_connection_manager = _FakeConnectionManager()
    events: list[str] = []

    monkeypatch.setattr(main_module, "get_database", lambda: fake_db)
    monkeypatch.setattr(main_module, "get_http_client", lambda: object())
    monkeypatch.setattr(main_module, "get_connection_manager", lambda: fake_connection_manager)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())

        async def fake_authenticate():
            assert fake_connection_manager.initialized is False
            events.append("authenticate")
            attempt = app._start_new_auth_attempt()
            generation = app._start_new_runtime_generation()
            return _auth_result(
                main_module,
                attempt=attempt,
                runtime_generation=generation,
                authenticated=True,
            )

        async def fake_initialize_authenticated_runtime(*, generation: int | None = None) -> None:
            events.append(f"initialize_authenticated_runtime({generation})")

        async def fake_show_main_window(*, generation: int | None = None) -> None:
            events.append(f"show_main_window({generation})")
            app._quit_event.set()

        async def fake_shutdown() -> None:
            events.append("shutdown")

        app.authenticate = fake_authenticate  # type: ignore[method-assign]
        app.initialize_authenticated_runtime = fake_initialize_authenticated_runtime  # type: ignore[method-assign]
        app.show_main_window = fake_show_main_window  # type: ignore[method-assign]
        app.shutdown = fake_shutdown  # type: ignore[method-assign]

        await app.run()

        assert events == [
            "authenticate",
            "initialize_authenticated_runtime(1)",
            "show_main_window(1)",
            "shutdown",
        ]

    asyncio.run(scenario())


def test_application_continue_authenticated_runtime_ignores_stale_auth_result() -> None:
    main_module = _load_main_module()
    events: list[str] = []

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        app._active_auth_attempt_generation = 2
        app._active_runtime_generation = 1

        async def fake_initialize_authenticated_runtime(*, generation: int | None = None) -> None:
            events.append(f"initialize_authenticated_runtime({generation})")

        async def fake_show_main_window(*, generation: int | None = None) -> None:
            events.append(f"show_main_window({generation})")

        app.initialize_authenticated_runtime = fake_initialize_authenticated_runtime  # type: ignore[method-assign]
        app.show_main_window = fake_show_main_window  # type: ignore[method-assign]

        continued = await app._continue_authenticated_runtime(
            main_module.AuthAttemptResult(
                attempt_generation=1,
                runtime_generation=1,
                authenticated=True,
            )
        )

        assert continued is False
        assert events == []

    asyncio.run(scenario())


def test_application_continue_authenticated_runtime_rechecks_startup_preflight(monkeypatch) -> None:
    main_module = _load_main_module()
    events: list[str] = []

    monkeypatch.setattr(
        main_module,
        "_show_startup_preflight_block_dialog",
        lambda preflight: events.append(f"dialog({preflight.get('state')})"),
    )

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        attempt = app._start_new_auth_attempt()
        generation = app._start_new_runtime_generation()
        app._startup_security_status = {
            "authenticated": True,
            "user_id": "user-1",
            "database_encryption": {
                "state": "provider_mismatch",
                "severity": "error",
                "can_start": False,
                "action_required": True,
                "message": "Configured DB encryption provider does not match the current runtime provider",
            },
        }

        async def fake_initialize_authenticated_runtime(*, generation: int | None = None) -> None:
            events.append(f"initialize_authenticated_runtime({generation})")

        async def fake_show_main_window(*, generation: int | None = None) -> None:
            events.append(f"show_main_window({generation})")

        app.initialize_authenticated_runtime = fake_initialize_authenticated_runtime  # type: ignore[method-assign]
        app.show_main_window = fake_show_main_window  # type: ignore[method-assign]

        continued = await app._continue_authenticated_runtime(
            main_module.AuthAttemptResult(
                attempt_generation=attempt,
                runtime_generation=generation,
                authenticated=True,
            )
        )

        assert continued is False
        assert events == ["dialog(provider_mismatch)"]
        assert app.get_exit_code() == main_module.EXIT_CODE_STARTUP_PREFLIGHT_BLOCKED
        assert app._quit_event.is_set() is True

    asyncio.run(scenario())


def test_application_show_main_window_ignores_stale_window_signals_and_delayed_callbacks(monkeypatch) -> None:
    main_module = _load_main_module()
    scheduled_callbacks: list[object] = []
    events: list[str] = []

    class _FakeMainWindow:
        def __init__(self) -> None:
            self.closed = _FakeSignal()
            self.logoutRequested = _FakeSignal()
            self.runtimeRefreshRequested = _FakeSignal()
            self.raise_calls = 0
            self.activate_calls = 0
            self.show_calls = 0
            self.show_normal_calls = 0
            self.restore_calls = 0

        def restore_default_geometry(self) -> None:
            self.restore_calls += 1

        def show(self) -> None:
            self.show_calls += 1

        def showNormal(self) -> None:
            self.show_normal_calls += 1

        def raise_(self) -> None:
            self.raise_calls += 1

        def activateWindow(self) -> None:
            self.activate_calls += 1

    class _FakeQTimer:
        @staticmethod
        def singleShot(_delay: int, callback) -> None:
            scheduled_callbacks.append(callback)

    fake_main_window_module = types.ModuleType("client.ui.windows.main_window")
    fake_main_window_module.MainWindow = _FakeMainWindow

    monkeypatch.setitem(sys.modules, "client.ui.windows.main_window", fake_main_window_module)
    monkeypatch.setattr(main_module, "QTimer", _FakeQTimer)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        generation = app._start_new_runtime_generation()

        def fake_create_task(coro):
            events.append("schedule_warmup")
            coro.close()
            return "warm-task"

        app.create_task = fake_create_task  # type: ignore[method-assign]
        await app.show_main_window(generation=generation)

        old_window = app.main_window
        assert isinstance(old_window, _FakeMainWindow)
        assert old_window.raise_calls == 1
        assert old_window.activate_calls == 1
        assert len(scheduled_callbacks) == 4

        app.main_window = None
        app._active_runtime_generation = 0

        old_window.closed.emit()
        old_window.logoutRequested.emit()
        old_window.runtimeRefreshRequested.emit()
        for callback in scheduled_callbacks:
            callback()

        assert app._quit_event.is_set() is False
        assert app._logout_task is None
        assert old_window.raise_calls == 1
        assert old_window.activate_calls == 1
        assert events == ["schedule_warmup"]

    asyncio.run(scenario())


def test_application_show_main_window_triggers_startup_ai_status_and_warmup(monkeypatch) -> None:
    main_module = _load_main_module()

    class _FakeChatInterface:
        def __init__(self) -> None:
            self.status_calls = 0
            self.warmup_calls = 0

        def show_startup_ai_status(self) -> None:
            self.status_calls += 1

        def warmup_startup_ai(self) -> None:
            self.warmup_calls += 1

    class _FakeMainWindow:
        def __init__(self) -> None:
            self.closed = _FakeSignal()
            self.logoutRequested = _FakeSignal()
            self.runtimeRefreshRequested = _FakeSignal()
            self.chat_interface = _FakeChatInterface()

        def restore_default_geometry(self) -> None:
            return None

        def show(self) -> None:
            return None

        def showNormal(self) -> None:
            return None

        def raise_(self) -> None:
            return None

        def activateWindow(self) -> None:
            return None

    class _FakeQTimer:
        @staticmethod
        def singleShot(_delay: int, callback) -> None:
            callback()

    fake_main_window_module = types.ModuleType("client.ui.windows.main_window")
    fake_main_window_module.MainWindow = _FakeMainWindow

    monkeypatch.setitem(sys.modules, "client.ui.windows.main_window", fake_main_window_module)
    monkeypatch.setattr(main_module, "QTimer", _FakeQTimer)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        generation = app._start_new_runtime_generation()

        def fake_create_task(coro):
            coro.close()
            return "warm-task"

        app.create_task = fake_create_task  # type: ignore[method-assign]
        await app.show_main_window(generation=generation)

        assert app.main_window.chat_interface.status_calls == 1
        assert app.main_window.chat_interface.warmup_calls == 1

    asyncio.run(scenario())


def test_application_warm_authenticated_runtime_promotes_ready_and_defers_auth_success_feedback(monkeypatch) -> None:
    main_module = _load_main_module()
    recorded: list[tuple[str, str, str, int]] = []
    events: list[str] = []

    class _FakeInfoBar:
        @staticmethod
        def success(title: str, message: str, *, parent=None, duration: int = 0) -> None:
            recorded.append(("success", title, message, duration))

        @staticmethod
        def warning(title: str, message: str, *, parent=None, duration: int = 0) -> None:
            recorded.append(("warning", title, message, duration))

    class _FakeChatInterface:
        def __init__(self) -> None:
            self.load_calls = 0

        def load_sessions(self) -> None:
            self.load_calls += 1

    class _FakeMainWindow:
        def __init__(self) -> None:
            self.chat_interface = _FakeChatInterface()

    monkeypatch.setattr(main_module, "InfoBar", _FakeInfoBar)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        generation = app._start_new_runtime_generation()
        app.main_window = _FakeMainWindow()
        app._pending_auth_success_message = "Signed in"
        app._set_lifecycle_state("main_shell_visible")

        async def fake_sync(runtime_generation: int) -> None:
            events.append(f"sync({runtime_generation})")

        async def fake_background_services(*, generation: int | None = None) -> None:
            events.append(f"background({generation})")

        app._synchronize_authenticated_runtime = fake_sync  # type: ignore[method-assign]
        app.start_background_services = fake_background_services  # type: ignore[method-assign]

        await app._warm_authenticated_runtime(generation)

        assert events == ["sync(1)", "background(1)"]
        assert app.main_window.chat_interface.load_calls == 1
        assert recorded == [("success", "Authentication", "Signed in", 1800)]
        assert app._pending_auth_success_message == ""
        assert app._lifecycle_state == "authenticated_ready"

    asyncio.run(scenario())


def test_application_warm_authenticated_runtime_surfaces_degraded_state_on_failure(monkeypatch) -> None:
    main_module = _load_main_module()
    recorded: list[tuple[str, str, str, int]] = []

    class _FakeInfoBar:
        @staticmethod
        def success(title: str, message: str, *, parent=None, duration: int = 0) -> None:
            recorded.append(("success", title, message, duration))

        @staticmethod
        def warning(title: str, message: str, *, parent=None, duration: int = 0) -> None:
            recorded.append(("warning", title, message, duration))

    class _FakeChatInterface:
        def __init__(self) -> None:
            self.load_calls = 0

        def load_sessions(self) -> None:
            self.load_calls += 1

    class _FakeMainWindow:
        def __init__(self) -> None:
            self.chat_interface = _FakeChatInterface()

    monkeypatch.setattr(main_module, "InfoBar", _FakeInfoBar)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        generation = app._start_new_runtime_generation()
        app.main_window = _FakeMainWindow()
        app._pending_auth_success_message = "Signed in"
        app._set_lifecycle_state("main_shell_visible")

        async def fake_sync(runtime_generation: int) -> None:
            raise RuntimeError(f"sync failed for generation {runtime_generation}")

        app._synchronize_authenticated_runtime = fake_sync  # type: ignore[method-assign]

        await app._warm_authenticated_runtime(generation)

        assert app.main_window.chat_interface.load_calls == 0
        assert recorded == [
            (
                "warning",
                "Connection incomplete",
                "Some data could not be refreshed. Messages and sessions may stay stale until the next retry.",
                5000,
            )
        ]
        assert app._pending_auth_success_message == ""
        assert app._lifecycle_state == "authenticated_degraded"

    asyncio.run(scenario())


def test_application_warm_authenticated_runtime_recovers_from_degraded_state(monkeypatch) -> None:
    main_module = _load_main_module()
    recorded: list[tuple[str, str, str, int]] = []

    class _FakeInfoBar:
        @staticmethod
        def success(title: str, message: str, *, parent=None, duration: int = 0) -> None:
            recorded.append(("success", title, message, duration))

        @staticmethod
        def warning(title: str, message: str, *, parent=None, duration: int = 0):
            recorded.append(("warning", title, message, duration))
            return None

    class _FakeChatInterface:
        def __init__(self) -> None:
            self.load_calls = 0

        def load_sessions(self) -> None:
            self.load_calls += 1

    class _FakeMainWindow:
        def __init__(self) -> None:
            self.chat_interface = _FakeChatInterface()

    monkeypatch.setattr(main_module, "InfoBar", _FakeInfoBar)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        generation = app._start_new_runtime_generation()
        app.main_window = _FakeMainWindow()
        app._set_lifecycle_state("authenticated_degraded")

        async def fake_sync(runtime_generation: int) -> None:
            return None

        async def fake_background_services(*, generation: int | None = None) -> None:
            return None

        app._synchronize_authenticated_runtime = fake_sync  # type: ignore[method-assign]
        app.start_background_services = fake_background_services  # type: ignore[method-assign]

        await app._warm_authenticated_runtime(generation)

        assert app.main_window.chat_interface.load_calls == 1
        assert recorded == [
            ("success", "Connection restored", "Messages and sessions are refreshed again.", 1800)
        ]
        assert app._lifecycle_state == "authenticated_ready"

    asyncio.run(scenario())


def test_application_warm_authenticated_runtime_refreshes_cached_profile_when_needed(monkeypatch) -> None:
    main_module = _load_main_module()
    runtime_status = {
        "authenticated": True,
        "user_id": "user-1",
        "database_encryption": {
            "state": "plain",
            "severity": "info",
            "can_start": True,
            "action_required": False,
            "message": "Local database encryption is disabled",
        },
    }
    fake_auth_controller = _FakeAuthController({"id": "user-1", "username": "alice"}, runtime_status)
    fake_auth_controller.pending_authoritative_profile_refresh = True

    monkeypatch.setattr(main_module, "get_auth_controller", lambda: fake_auth_controller)

    class _FakeChatInterface:
        def __init__(self) -> None:
            self.load_calls = 0

        def load_sessions(self) -> None:
            self.load_calls += 1

    class _FakeMainWindow:
        def __init__(self) -> None:
            self.chat_interface = _FakeChatInterface()

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        generation = app._start_new_runtime_generation()
        app.main_window = _FakeMainWindow()
        app._set_lifecycle_state("authenticated_bootstrapping")

        async def fake_sync(runtime_generation: int) -> None:
            return None

        async def fake_background_services(*, generation: int | None = None) -> None:
            return None

        app._synchronize_authenticated_runtime = fake_sync  # type: ignore[method-assign]
        app.start_background_services = fake_background_services  # type: ignore[method-assign]

        await app._warm_authenticated_runtime(generation)

        assert fake_auth_controller.authoritative_profile_refresh_calls == 1
        assert fake_auth_controller.pending_authoritative_profile_refresh is False
        assert app.main_window.chat_interface.load_calls == 1
        assert app._lifecycle_state == "authenticated_ready"

    asyncio.run(scenario())


def test_application_retry_authenticated_runtime_reschedules_warmup(monkeypatch) -> None:
    main_module = _load_main_module()
    events: list[str] = []

    class _FakeWarningBar:
        def __init__(self) -> None:
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    class _FakeTask:
        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            events.append("cancel_old_task")

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        generation = app._start_new_runtime_generation()
        app.main_window = object()
        app._set_lifecycle_state("authenticated_degraded")
        warning_bar = _FakeWarningBar()
        app._runtime_warmup_warning_bar = warning_bar

        async def fake_warm(runtime_generation: int):
            events.append(f"warm({runtime_generation})")

        def fake_create_task(coro):
            events.append("schedule")
            coro.close()
            return "scheduled-task"

        app._warm_runtime_task = _FakeTask()
        app._warm_authenticated_runtime = fake_warm  # type: ignore[method-assign]
        app.create_task = fake_create_task  # type: ignore[method-assign]

        app.retry_authenticated_runtime()

        assert warning_bar.close_calls == 1
        assert app._runtime_warmup_warning_bar is None
        assert app._warm_runtime_task == "scheduled-task"
        assert app._lifecycle_state == "authenticated_bootstrapping"
        assert events == ["cancel_old_task", "schedule"]

    asyncio.run(scenario())


def test_application_authenticate_skips_when_quit_is_already_requested(monkeypatch) -> None:
    main_module = _load_main_module()

    def fail_get_auth_controller():
        raise AssertionError("auth controller should not be touched after quit")

    monkeypatch.setattr(main_module, "get_auth_controller", fail_get_auth_controller)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        app._quit_event.set()

        result = await app.authenticate()

        assert result.authenticated is False
        assert result.runtime_generation == 0
        assert app._active_auth_attempt_generation == 0
        assert app._active_runtime_generation == 0

    asyncio.run(scenario())


def test_application_show_main_window_skips_when_quit_is_already_requested() -> None:
    main_module = _load_main_module()

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        generation = app._start_new_runtime_generation()
        app._quit_event.set()

        await app.show_main_window(generation=generation)

        assert app.main_window is None
        assert app._warm_runtime_task is None

    asyncio.run(scenario())


def test_application_logout_flow_failure_sets_explicit_quit(monkeypatch) -> None:
    main_module = _load_main_module()
    events: list[str] = []

    class _FakeMainWindow:
        def begin_runtime_transition(self) -> None:
            events.append("main_window.begin_runtime_transition")

    monkeypatch.setattr(main_module, "get_auth_controller", lambda: object())

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        app.main_window = _FakeMainWindow()
        app._active_runtime_generation = 3
        app._pending_auth_success_message = "stale success"

        async def fail_quiesce() -> None:
            events.append("quiesce")
            raise RuntimeError("teardown failed")

        app._quiesce_authenticated_runtime = fail_quiesce  # type: ignore[method-assign]

        await app._perform_logout_flow()

        assert events == ["main_window.begin_runtime_transition", "quiesce"]
        assert app._quit_event.is_set() is True
        assert app._pending_auth_success_message == ""
        assert app._active_auth_attempt_generation == 0
        assert app._active_runtime_generation == 0
        assert app._lifecycle_state == "unauthenticated"

    asyncio.run(scenario())


def test_application_logout_does_not_reauth_when_runtime_teardown_is_incomplete(monkeypatch) -> None:
    main_module = _load_main_module()
    events: list[str] = []

    class _FailingCloseable:
        async def close(self) -> None:
            events.append("message_manager.close")
            raise RuntimeError("close failed")

    fake_auth_controller = _FakeAuthControllerForLogout(events)

    monkeypatch.setattr(main_module, "get_auth_controller", lambda: fake_auth_controller)
    monkeypatch.setattr(main_module, "peek_chat_controller", lambda: None)
    monkeypatch.setattr(main_module, "peek_message_controller", lambda: None)
    monkeypatch.setattr(main_module, "peek_session_controller", lambda: None)
    monkeypatch.setattr(main_module, "_peek_discovery_controller", lambda: None)
    monkeypatch.setattr(main_module, "peek_message_manager", lambda: _FailingCloseable())
    monkeypatch.setattr(main_module, "peek_session_manager", lambda: None)
    monkeypatch.setattr(main_module, "peek_connection_manager", lambda: None)
    monkeypatch.setattr(main_module, "peek_websocket_client", lambda: None)
    monkeypatch.setattr(main_module, "peek_sound_manager", lambda: None)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())

        async def fake_authenticate():
            events.append("authenticate")
            return _auth_result(main_module, authenticated=False)

        app.authenticate = fake_authenticate  # type: ignore[method-assign]

        await app._perform_logout_flow()

        assert events == ["message_manager.close"]
        assert app._quit_event.is_set() is True
        assert app._active_auth_attempt_generation == 0
        assert app._active_runtime_generation == 0
        assert app._lifecycle_state == "unauthenticated"

    asyncio.run(scenario())


def test_application_run_handles_authenticate_failure_without_propagating() -> None:
    main_module = _load_main_module()
    events: list[str] = []
    dialogs: list[tuple[str, str]] = []

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        app._active_auth_attempt_generation = 2
        app._active_runtime_generation = 3
        app._pending_auth_success_message = "stale success"

        async def fake_initialize() -> None:
            events.append("initialize")

        async def fail_authenticate():
            events.append("authenticate")
            raise RuntimeError("restore exploded")

        async def fake_shutdown() -> None:
            events.append("shutdown")

        def fake_dialog(stage: str, detail: str = "") -> None:
            dialogs.append((stage, detail))

        app.initialize = fake_initialize  # type: ignore[method-assign]
        app.authenticate = fail_authenticate  # type: ignore[method-assign]
        app.shutdown = fake_shutdown  # type: ignore[method-assign]
        main_module._show_startup_runtime_failure_dialog = fake_dialog  # type: ignore[attr-defined]

        await app.run()

        assert events == ["initialize", "authenticate", "shutdown"]
        assert dialogs == [("authenticate", "restore exploded")]
        assert app._quit_event.is_set() is True
        assert app._pending_auth_success_message == ""
        assert app._active_auth_attempt_generation == 0
        assert app._active_runtime_generation == 0
        assert app.get_exit_code() == main_module.EXIT_CODE_STARTUP_RUNTIME_FAILED

    asyncio.run(scenario())


def test_application_run_surfaces_main_window_bootstrap_failure(monkeypatch) -> None:
    main_module = _load_main_module()
    events: list[str] = []
    dialogs: list[tuple[str, str]] = []

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())

        async def fake_initialize() -> None:
            events.append("initialize")

        async def fake_authenticate():
            events.append("authenticate")
            attempt = app._start_new_auth_attempt()
            generation = app._start_new_runtime_generation()
            return _auth_result(main_module, attempt=attempt, runtime_generation=generation, authenticated=True)

        async def fake_initialize_authenticated_runtime(*, generation: int | None = None) -> None:
            events.append(f"initialize_authenticated_runtime({generation})")

        async def fail_show_main_window(*, generation: int | None = None) -> None:
            events.append(f"show_main_window({generation})")
            raise RuntimeError("shell build failed")

        async def fake_shutdown() -> None:
            events.append("shutdown")

        def fake_dialog(stage: str, detail: str = "") -> None:
            dialogs.append((stage, detail))

        app.initialize = fake_initialize  # type: ignore[method-assign]
        app.authenticate = fake_authenticate  # type: ignore[method-assign]
        app.initialize_authenticated_runtime = fake_initialize_authenticated_runtime  # type: ignore[method-assign]
        app.show_main_window = fail_show_main_window  # type: ignore[method-assign]
        app.shutdown = fake_shutdown  # type: ignore[method-assign]
        main_module._show_startup_runtime_failure_dialog = fake_dialog  # type: ignore[attr-defined]

        await app.run()

        assert events == [
            "initialize",
            "authenticate",
            "initialize_authenticated_runtime(1)",
            "show_main_window(1)",
            "shutdown",
        ]
        assert dialogs == [("authenticated_runtime", "shell build failed")]
        assert app.get_exit_code() == main_module.EXIT_CODE_STARTUP_RUNTIME_FAILED
        assert app._quit_event.is_set() is True

    asyncio.run(scenario())


def test_application_shutdown_closes_websocket_even_when_connection_manager_exists(monkeypatch) -> None:
    main_module = _load_main_module()
    events: list[str] = []

    class _Closeable:
        def __init__(self, name: str) -> None:
            self.name = name
            self._intentional_disconnect = False

        async def close(self) -> None:
            events.append(f"{self.name}.close")

    connection_manager = _Closeable("connection_manager")
    websocket_client = _Closeable("websocket")
    monkeypatch.setattr(main_module, "peek_connection_manager", lambda: connection_manager)
    monkeypatch.setattr(main_module, "peek_websocket_client", lambda: websocket_client)

    async def scenario() -> None:
        qt_app = _FakeQtApp()
        app = main_module.Application(qt_app)

        await app.shutdown()

        assert events == ["connection_manager.close", "websocket.close"]
        assert websocket_client._intentional_disconnect is True
        assert qt_app.process_events_calls == 0
        assert qt_app.quit_calls == 1

    asyncio.run(scenario())


def test_application_teardown_runtime_closes_websocket_even_when_connection_manager_exists(monkeypatch) -> None:
    main_module = _load_main_module()
    events: list[str] = []

    class _Closeable:
        async def close(self) -> None:
            events.append(self.name)

    connection_manager = _Closeable()
    connection_manager.name = "connection_manager"
    websocket_client = _Closeable()
    websocket_client.name = "websocket"
    monkeypatch.setattr(main_module, "_peek_discovery_controller", lambda: None)
    monkeypatch.setattr(main_module, "peek_connection_manager", lambda: connection_manager)
    monkeypatch.setattr(main_module, "peek_websocket_client", lambda: websocket_client)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())

        await app._teardown_authenticated_runtime()

        assert events == ["connection_manager", "websocket"]

    asyncio.run(scenario())


def test_application_teardown_runtime_closes_main_window_via_runtime_transition(monkeypatch) -> None:
    main_module = _load_main_module()
    events: list[str] = []

    class _FakeMainWindow:
        def close_for_runtime_transition(self) -> None:
            events.append("main_window.close_for_runtime_transition")

        def deleteLater(self) -> None:
            events.append("main_window.deleteLater")

    monkeypatch.setattr(main_module, "peek_chat_controller", lambda: None)
    monkeypatch.setattr(main_module, "peek_message_controller", lambda: None)
    monkeypatch.setattr(main_module, "peek_session_controller", lambda: None)
    monkeypatch.setattr(main_module, "_peek_discovery_controller", lambda: None)
    monkeypatch.setattr(main_module, "peek_message_manager", lambda: None)
    monkeypatch.setattr(main_module, "peek_session_manager", lambda: None)
    monkeypatch.setattr(main_module, "peek_connection_manager", lambda: None)
    monkeypatch.setattr(main_module, "peek_websocket_client", lambda: None)
    monkeypatch.setattr(main_module, "peek_sound_manager", lambda: None)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        app.main_window = _FakeMainWindow()

        await app._teardown_authenticated_runtime()

        assert events == [
            "main_window.close_for_runtime_transition",
            "main_window.deleteLater",
        ]
        assert app.main_window is None

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


def test_application_logout_quiesces_runtime_before_clearing_auth_state(monkeypatch) -> None:
    main_module = _load_main_module()
    events: list[str] = []
    fake_auth_controller = _FakeAuthControllerForLogout(events)

    class _FakeMainWindow:
        def begin_runtime_transition(self) -> None:
            events.append("main_window.begin_runtime_transition")

    monkeypatch.setattr(main_module, "get_auth_controller", lambda: fake_auth_controller)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        app.main_window = _FakeMainWindow()

        async def fake_quiesce() -> None:
            events.append("quiesce")

        async def fake_authenticate():
            events.append("authenticate")
            attempt = app._start_new_auth_attempt()
            return _auth_result(main_module, attempt=attempt, authenticated=False)

        app._quiesce_authenticated_runtime = fake_quiesce  # type: ignore[method-assign]
        app.authenticate = fake_authenticate  # type: ignore[method-assign]
        await app._perform_logout_flow()

        assert events == [
            "main_window.begin_runtime_transition",
            "quiesce",
            "logout(clear_local_chat_state=True)",
            "auth_controller.close",
            "authenticate",
        ]
        assert app._quit_event.is_set() is True

    asyncio.run(scenario())


def test_application_quiesce_invalidates_runtime_generation_before_teardown() -> None:
    main_module = _load_main_module()
    events: list[str] = []

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        generation = app._start_new_runtime_generation()
        assert app._is_runtime_generation_current(generation) is True

        async def fake_teardown() -> None:
            events.append(f"teardown(active_generation={app._active_runtime_generation})")

        app._teardown_authenticated_runtime = fake_teardown  # type: ignore[method-assign]
        await app._quiesce_authenticated_runtime()

        assert events == ["teardown(active_generation=0)"]
        assert app._is_runtime_generation_current(generation) is False
        assert app._lifecycle_state == "unauthenticated"

    asyncio.run(scenario())


def test_application_quiesce_calls_main_window_quiesce_before_teardown() -> None:
    main_module = _load_main_module()
    events: list[str] = []

    class _FakeMainWindow:
        def quiesce(self) -> None:
            events.append("main_window.quiesce")

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        app.main_window = _FakeMainWindow()

        async def fake_teardown() -> None:
            events.append("teardown")

        app._teardown_authenticated_runtime = fake_teardown  # type: ignore[method-assign]
        await app._quiesce_authenticated_runtime()

        assert events == ["main_window.quiesce", "teardown"]

    asyncio.run(scenario())


def test_application_auth_loss_uses_single_flow_without_purging_local_chat(monkeypatch) -> None:
    main_module = _load_main_module()
    events: list[str] = []
    fake_auth_controller = _FakeAuthControllerForLogout(events)

    class _FakeMainWindow:
        def begin_runtime_transition(self) -> None:
            events.append("main_window.begin_runtime_transition")

    monkeypatch.setattr(main_module, "get_auth_controller", lambda: fake_auth_controller)

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        app.main_window = _FakeMainWindow()
        app._set_lifecycle_state("authenticated_ready")

        async def fake_quiesce() -> None:
            events.append("quiesce")
            app._active_runtime_generation = 0
            app._set_lifecycle_state("unauthenticated")

        async def fake_authenticate():
            events.append("authenticate")
            attempt = app._start_new_auth_attempt()
            generation = app._start_new_runtime_generation()
            return _auth_result(
                main_module,
                attempt=attempt,
                runtime_generation=generation,
                authenticated=True,
            )

        async def fake_initialize_authenticated_runtime(*, generation: int | None = None) -> None:
            events.append(f"initialize_authenticated_runtime({generation})")

        async def fake_show_main_window(*, generation: int | None = None) -> None:
            events.append(f"show_main_window({generation})")

        app._quiesce_authenticated_runtime = fake_quiesce  # type: ignore[method-assign]
        app.authenticate = fake_authenticate  # type: ignore[method-assign]
        app.initialize_authenticated_runtime = fake_initialize_authenticated_runtime  # type: ignore[method-assign]
        app.show_main_window = fake_show_main_window  # type: ignore[method-assign]

        await app._handle_auth_lost("refresh_rejected")

        assert events == [
            "main_window.begin_runtime_transition",
            "quiesce",
            "clear_session(clear_local_chat_state=False)",
            "auth_controller.close",
            "authenticate",
            "initialize_authenticated_runtime(1)",
            "show_main_window(1)",
        ]

    asyncio.run(scenario())



def test_application_ws_auth_error_triggers_auth_loss() -> None:
    main_module = _load_main_module()
    reasons: list[str] = []

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        app._on_auth_loss = reasons.append  # type: ignore[method-assign]

        await app._handle_transport_message(
            {
                "type": "error",
                "data": {
                    "code": 401,
                    "message": "websocket auth expired",
                },
            }
        )

        assert reasons == ["ws_auth_error"]

    asyncio.run(scenario())


def test_application_force_logout_logout_reason_uses_auth_loss_flow() -> None:
    main_module = _load_main_module()
    reasons: list[str] = []

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())

        async def fake_handle_auth_lost(reason: str) -> None:
            reasons.append(reason)

        app._handle_auth_lost = fake_handle_auth_lost  # type: ignore[method-assign]

        await app._handle_transport_message(
            {
                "type": "force_logout",
                "data": {
                    "reason": "logout",
                },
            }
        )

        assert reasons == ["force_logout:logout"]
        assert app._forced_logout_in_progress is False

    asyncio.run(scenario())
def test_application_ws_business_forbidden_error_does_not_trigger_auth_loss() -> None:
    main_module = _load_main_module()
    reasons: list[str] = []

    async def scenario() -> None:
        app = main_module.Application(_FakeQtApp())
        app._on_auth_loss = reasons.append  # type: ignore[method-assign]

        await app._handle_transport_message(
            {
                "type": "error",
                "data": {
                    "code": 403,
                    "message": "not a session member",
                },
            }
        )

        assert reasons == []

    asyncio.run(scenario())
