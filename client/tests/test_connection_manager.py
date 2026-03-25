from __future__ import annotations

import asyncio
import json
import sys
import types
from enum import Enum


if 'PySide6.QtCore' not in sys.modules:
    qtcore = types.ModuleType('PySide6.QtCore')

    class _DummyQLocale:
        class Language:
            Chinese = 'Chinese'
            English = 'English'
            Korean = 'Korean'

        class Country:
            China = 'China'
            UnitedStates = 'UnitedStates'
            SouthKorea = 'SouthKorea'

        _default = None

        def __init__(self, language=None, country=None):
            self._language = language or self.Language.English
            self._country = country or self.Country.UnitedStates

        @classmethod
        def system(cls):
            return cls(cls.Language.English, cls.Country.UnitedStates)

        @classmethod
        def setDefault(cls, locale):
            cls._default = locale

        def language(self):
            return self._language

        def name(self):
            if self._language == self.Language.Chinese:
                return 'zh_CN'
            if self._language == self.Language.Korean:
                return 'ko_KR'
            return 'en_US'

        def toString(self, value, fmt=None):
            return str(value)

        def __eq__(self, other):
            return isinstance(other, _DummyQLocale) and self._language == other._language and self._country == other._country

    class _DummyQObject:
        def __init__(self, *args, **kwargs):
            pass

    class _DummySignalInstance:
        def connect(self, callback):
            self._callback = callback

        def emit(self, *args, **kwargs):
            callback = getattr(self, '_callback', None)
            if callback is not None:
                callback(*args, **kwargs)

    def _DummySignal(*args, **kwargs):
        return _DummySignalInstance()

    def _DummySlot(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    class _DummyQTimer:
        def __init__(self, *args, **kwargs):
            self.timeout = _DummySignalInstance()

        def setInterval(self, interval):
            self._interval = interval

        def start(self):
            return None

    class _DummyQCoreApplication:
        @staticmethod
        def instance():
            return None

    qtcore.QLocale = _DummyQLocale
    qtcore.QObject = _DummyQObject
    qtcore.Signal = _DummySignal
    qtcore.Slot = _DummySlot
    qtcore.QTimer = _DummyQTimer
    qtcore.QCoreApplication = _DummyQCoreApplication
    pyside = types.ModuleType('PySide6')
    pyside.QtCore = qtcore
    sys.modules['PySide6'] = pyside
    sys.modules['PySide6.QtCore'] = qtcore

if 'aiosqlite' not in sys.modules:
    aiosqlite = types.ModuleType('aiosqlite')

    class _DummyConnection:
        row_factory = None

        async def close(self):
            return None

    class _DummyRow(dict):
        pass

    async def _dummy_connect(*args, **kwargs):
        return _DummyConnection()

    aiosqlite.Connection = _DummyConnection
    aiosqlite.Row = _DummyRow
    aiosqlite.connect = _dummy_connect
    sys.modules['aiosqlite'] = aiosqlite

if 'websockets' not in sys.modules:
    websockets = types.ModuleType('websockets')
    legacy = types.ModuleType('websockets.legacy')
    legacy_client = types.ModuleType('websockets.legacy.client')
    exceptions = types.ModuleType('websockets.exceptions')

    class _DummyWebSocketClientProtocol:
        pass

    class _DummyConnectionClosed(Exception):
        pass

    class _DummyWebSocketException(Exception):
        pass

    legacy_client.WebSocketClientProtocol = _DummyWebSocketClientProtocol
    exceptions.ConnectionClosed = _DummyConnectionClosed
    exceptions.WebSocketException = _DummyWebSocketException
    legacy.client = legacy_client
    websockets.legacy = legacy
    websockets.exceptions = exceptions
    sys.modules['websockets'] = websockets
    sys.modules['websockets.legacy'] = legacy
    sys.modules['websockets.legacy.client'] = legacy_client
    sys.modules['websockets.exceptions'] = exceptions

if 'aiohttp' not in sys.modules:
    aiohttp = types.ModuleType('aiohttp')

    class _DummyClientError(Exception):
        pass

    class _DummyClientTimeout:
        def __init__(self, total=None):
            self.total = total

    class _DummyFormData:
        def __init__(self):
            self.fields = []

        def add_field(self, name, value, **kwargs):
            self.fields.append({'name': name, 'value': value, **kwargs})

    class _DummyClientSession:
        def __init__(self, *args, **kwargs):
            self.closed = False

        async def close(self):
            self.closed = True

    class _DummyClientResponse:
        status = 200

        async def json(self):
            return {}

        async def text(self):
            return ''

    aiohttp.ClientError = _DummyClientError
    aiohttp.FormData = _DummyFormData
    aiohttp.ClientTimeout = _DummyClientTimeout
    aiohttp.ClientSession = _DummyClientSession
    aiohttp.ClientResponse = _DummyClientResponse
    sys.modules['aiohttp'] = aiohttp

if 'qfluentwidgets' not in sys.modules:
    qfluentwidgets = types.ModuleType('qfluentwidgets')

    class _DummyConfigSerializer:
        def serialize(self, value):
            return value

        def deserialize(self, value):
            return value

    class _DummyConfigItem:
        def __init__(self, *args, **kwargs):
            self.default = args[2] if len(args) > 2 else None

    class _DummyOptionsConfigItem(_DummyConfigItem):
        pass

    class _DummyColorConfigItem(_DummyConfigItem):
        pass

    class _DummyValidator:
        def __init__(self, *args, **kwargs):
            pass

    class _DummyQConfig:
        def get(self, item):
            return getattr(item, 'default', None)

        def save(self):
            return None

    class _DummyTheme(Enum):
        LIGHT = 'light'
        DARK = 'dark'
        AUTO = 'auto'

    class _DummyFluentIconBase:
        def icon(self, *args, **kwargs):
            return self

        def path(self, theme=None):
            return ''

    qfluentwidgets.BoolValidator = _DummyValidator
    qfluentwidgets.ColorConfigItem = _DummyColorConfigItem
    qfluentwidgets.ConfigItem = _DummyConfigItem
    qfluentwidgets.ConfigSerializer = _DummyConfigSerializer
    qfluentwidgets.FluentIconBase = _DummyFluentIconBase
    qfluentwidgets.OptionsConfigItem = _DummyOptionsConfigItem
    qfluentwidgets.OptionsValidator = _DummyValidator
    qfluentwidgets.QConfig = _DummyQConfig
    qfluentwidgets.Theme = _DummyTheme
    qfluentwidgets.getIconColor = lambda theme: 'black'
    qfluentwidgets.qconfig = types.SimpleNamespace(load=lambda path, cfg: None)
    sys.modules['qfluentwidgets'] = qfluentwidgets

from client.managers import connection_manager as connection_manager_module
from client.storage import database as database_module


class FakeDatabase:
    def __init__(self) -> None:
        self.is_connected = True
        self.app_state: dict[str, str] = {}
        self.session_cursors: dict[str, int] = {}

    async def get_app_state(self, key: str):
        return self.app_state.get(key)

    async def set_app_state(self, key: str, value: str) -> None:
        self.app_state[key] = value

    async def delete_app_state(self, key: str) -> None:
        self.app_state.pop(key, None)

    async def get_session_sync_cursors(self) -> dict[str, int]:
        return dict(self.session_cursors)


class FakeWebSocketClient:
    def __init__(self) -> None:
        self.url = 'ws://example.test/ws'
        self.is_connected = True
        self.sent_nowait: list[dict] = []

    def set_callbacks(self, **kwargs) -> None:
        self.callbacks = kwargs

    def send_nowait(self, payload: dict) -> bool:
        self.sent_nowait.append(payload)
        return True

    async def send(self, payload: dict, timeout: float = 10.0) -> bool:
        self.sent_nowait.append(payload)
        return True

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeAuthService:
    def __init__(self, access_token: str = 'token') -> None:
        self.access_token = access_token


def test_connection_manager_loads_cached_message_and_event_cursors_and_builds_sync_request(monkeypatch) -> None:
    fake_db = FakeDatabase()
    fake_db.session_cursors = {'session-1': 3}
    fake_db.app_state['last_sync_event_cursors'] = json.dumps({'session-1': 2})
    fake_ws_client = FakeWebSocketClient()

    monkeypatch.setattr(database_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: FakeAuthService())

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        manager._ws_client = fake_ws_client
        manager._base_ws_url = fake_ws_client.url
        try:
            await manager.reload_sync_timestamp()
            assert manager.session_sync_cursors == {'session-1': 3}
            assert manager.event_sync_cursors == {'session-1': 2}

            manager._send_sync_request_nowait()
            payload = fake_ws_client.sent_nowait[-1]
            assert payload['type'] == 'sync_messages'
            assert payload['data']['session_cursors'] == {'session-1': 3}
            assert payload['data']['event_cursors'] == {'session-1': 2}
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_connection_manager_advances_message_and_event_cursors_from_ws_payloads(monkeypatch) -> None:
    fake_db = FakeDatabase()

    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: FakeAuthService())

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        manager._db = fake_db
        try:
            manager._on_message(
                {
                    'type': 'message_ack',
                    'data': {
                        'message': {
                            'session_id': 'session-1',
                            'session_seq': 4,
                        },
                    },
                }
            )
            manager._on_message(
                {
                    'type': 'history_messages',
                    'data': {
                        'messages': [
                            {'session_id': 'session-1', 'session_seq': 2},
                            {'session_id': 'session-2', 'session_seq': 5},
                        ],
                    },
                }
            )
            manager._on_message(
                {
                    'type': 'read',
                    'data': {
                        'session_id': 'session-1',
                        'last_read_seq': 4,
                        'event_seq': 3,
                    },
                }
            )
            manager._on_message(
                {
                    'type': 'history_events',
                    'data': {
                        'events': [
                            {'type': 'message_edit', 'data': {'session_id': 'session-1', 'event_seq': 2}},
                            {'type': 'message_delete', 'data': {'session_id': 'session-2', 'event_seq': 6}},
                        ],
                    },
                }
            )

            await asyncio.sleep(0.05)

            assert manager.session_sync_cursors == {'session-1': 4, 'session-2': 5}
            assert manager.event_sync_cursors == {'session-1': 3, 'session-2': 6}
            assert json.loads(fake_db.app_state[manager.LAST_SYNC_SESSION_CURSORS]) == {
                'session-1': 4,
                'session-2': 5,
            }
            assert json.loads(fake_db.app_state[manager.LAST_SYNC_EVENT_CURSORS]) == {
                'session-1': 3,
                'session-2': 6,
            }
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_connection_manager_uses_auth_service_token_for_ws_url_and_auth_message(monkeypatch) -> None:
    fake_auth_service = FakeAuthService(access_token='ws-token')
    fake_ws_client = FakeWebSocketClient()

    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: fake_auth_service)

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        manager._ws_client = fake_ws_client
        manager._base_ws_url = 'ws://example.test/ws?client=desktop'
        try:
            manager._apply_authenticated_ws_url()
            assert manager._ws_client.url == 'ws://example.test/ws?client=desktop&token=ws-token'

            sent = manager._authenticate_websocket_nowait()

            assert sent is True
            assert fake_ws_client.sent_nowait[-1] == {
                'type': 'auth',
                'seq': 0,
                'msg_id': '',
                'timestamp': 0,
                'data': {
                    'token': 'ws-token',
                },
            }
        finally:
            await manager.close()

    asyncio.run(scenario())
