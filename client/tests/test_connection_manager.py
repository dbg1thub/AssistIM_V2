from __future__ import annotations

import asyncio
import json
import sqlite3
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

    class _DummyQDate:
        @staticmethod
        def currentDate():
            return _DummyQDate()

        def toString(self, _fmt=None):
            return '2026-04-12'

    qtcore.QLocale = _DummyQLocale
    qtcore.QObject = _DummyQObject
    qtcore.Signal = _DummySignal
    qtcore.Slot = _DummySlot
    qtcore.QTimer = _DummyQTimer
    qtcore.QCoreApplication = _DummyQCoreApplication
    qtcore.QDate = _DummyQDate
    pyside = types.ModuleType('PySide6')
    pyside.QtCore = qtcore
    sys.modules['PySide6'] = pyside
    sys.modules['PySide6.QtCore'] = qtcore

if 'aiosqlite' not in sys.modules:
    aiosqlite = types.ModuleType('aiosqlite')

    class _Cursor:
        def __init__(self, cursor: sqlite3.Cursor) -> None:
            self._cursor = cursor
            self.rowcount = cursor.rowcount

        async def fetchone(self):
            return self._cursor.fetchone()

        async def fetchall(self):
            return self._cursor.fetchall()

    class _DummyConnection:
        def __init__(self, path: str = ':memory:') -> None:
            self._conn = sqlite3.connect(path)
            self._row_factory = None

        @property
        def row_factory(self):
            return self._row_factory

        @row_factory.setter
        def row_factory(self, value) -> None:
            self._row_factory = value
            self._conn.row_factory = value

        async def execute(self, sql: str, params=()):
            return _Cursor(self._conn.execute(sql, params))

        async def executescript(self, script: str):
            self._conn.executescript(script)

        async def commit(self) -> None:
            self._conn.commit()

        async def close(self):
            self._conn.close()

    async def _dummy_connect(path=':memory:', *args, **kwargs):
        return _DummyConnection(path)

    aiosqlite.Connection = _DummyConnection
    aiosqlite.Row = sqlite3.Row
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
    qfluentwidgets.isDarkTheme = lambda: False
    qfluentwidgets.themeColor = lambda: '#07c160'
    qfluentwidgets.qconfig = types.SimpleNamespace(load=lambda path, cfg: None)
    sys.modules['qfluentwidgets'] = qfluentwidgets

from client.managers import connection_manager as connection_manager_module
from client.storage import database as database_module


class FakeDatabase:
    def __init__(self) -> None:
        self.is_connected = True
        self.app_state: dict[str, str] = {}
        self.session_cursors: dict[str, int] = {}
        self.replace_calls: list[tuple[dict[str, str], list[str]]] = []

    async def get_app_state(self, key: str):
        return self.app_state.get(key)

    async def replace_app_state(self, values: dict[str, str] | None = None, *, delete_keys=()) -> None:
        self.replace_calls.append((dict(values or {}), [str(key) for key in list(delete_keys or [])]))
        for key in list(delete_keys or []):
            self.app_state.pop(str(key), None)
        for key, value in dict(values or {}).items():
            self.app_state[str(key)] = value

    async def set_app_state(self, key: str, value: str) -> None:
        await self.replace_app_state({key: value})

    async def delete_app_state(self, key: str) -> None:
        await self.replace_app_state(delete_keys=[key])

    async def get_session_sync_cursors(self) -> dict[str, int]:
        return dict(self.session_cursors)


class FakeWebSocketClient:
    def __init__(self) -> None:
        self.url = 'ws://example.test/ws'
        self.is_connected = True
        self.disconnect_calls = 0
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
        self.is_connected = True
        return None

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.is_connected = False
        return None

    async def close(self) -> None:
        self.is_connected = False
        return None


class FakeAuthService:
    def __init__(self, access_token: str = 'token') -> None:
        self.access_token = access_token
        self.refresh_token = 'refresh-token'
        self.refresh_calls = 0
        self.refresh_result = True
        self.refreshed_access_token = 'refreshed-token'
        self._listeners = []

    def add_token_listener(self, listener) -> None:
        self._listeners.append(listener)

    def remove_token_listener(self, listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def clear_tokens(self) -> None:
        self.access_token = None
        self.refresh_token = None
        for listener in list(self._listeners):
            listener(None, None)

    async def refresh_access_token(self) -> bool:
        self.refresh_calls += 1
        if not self.refresh_result:
            self.clear_tokens()
            return False
        self.access_token = self.refreshed_access_token
        for listener in list(self._listeners):
            listener(self.access_token, self.refresh_token)
        return True


def test_connection_manager_loads_cached_message_and_event_cursors_and_builds_sync_request(monkeypatch) -> None:
    fake_db = FakeDatabase()
    fake_db.session_cursors = {'session-1': 3}
    fake_db.app_state['last_sync_event_cursors'] = json.dumps({'session-1': 2})
    fake_ws_client = FakeWebSocketClient()

    monkeypatch.setattr(database_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: FakeAuthService())

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        manager._db = fake_db
        manager._ws_client = fake_ws_client
        manager._base_ws_url = fake_ws_client.url
        manager._ws_authenticated = True
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


def test_connection_manager_sends_canonical_message_id_for_mutation_commands(monkeypatch) -> None:
    fake_ws_client = FakeWebSocketClient()

    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: FakeAuthService())

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        manager._ws_client = fake_ws_client
        manager._ws_authenticated = True
        try:
            recall_sent = await manager.send_recall('session-1', 'message-1')
            edit_sent = await manager.send_edit('session-1', 'message-1', 'updated content')

            assert recall_sent is True
            assert edit_sent is True
            assert fake_ws_client.sent_nowait[-2]['data'] == {
                'session_id': 'session-1',
                'message_id': 'message-1',
            }
            assert fake_ws_client.sent_nowait[-1]['data'] == {
                'session_id': 'session-1',
                'message_id': 'message-1',
                'content': 'updated content',
            }
        finally:
            await manager.close()

    asyncio.run(scenario())

def test_connection_manager_rejects_business_messages_after_tokens_are_cleared(monkeypatch) -> None:
    fake_ws_client = FakeWebSocketClient()
    fake_auth_service = FakeAuthService(access_token='ws-token')

    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: fake_auth_service)

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        manager._ws_client = fake_ws_client
        manager._ws_authenticated = True
        try:
            fake_auth_service.clear_tokens()
            await asyncio.sleep(0)

            sent = await manager.send_chat_message('session-1', 'hello', 'msg-1')

            assert sent is False
            assert manager._ws_authenticated is False
            assert fake_ws_client.disconnect_calls == 1
            assert fake_ws_client.sent_nowait == []
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


def test_connection_manager_saves_message_and_event_cursors_in_one_app_state_batch(monkeypatch) -> None:
    fake_db = FakeDatabase()

    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: FakeAuthService())

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        manager._db = fake_db
        manager._session_sync_cursors = {'session-1': 4}
        manager._event_sync_cursors = {'session-1': 3}
        try:
            await manager._save_sync_state()

            values, delete_keys = fake_db.replace_calls[-1]
            assert set(values) == {manager.LAST_SYNC_SESSION_CURSORS, manager.LAST_SYNC_EVENT_CURSORS}
            assert manager.LEGACY_LAST_SYNC_TIMESTAMP in delete_keys
            assert json.loads(values[manager.LAST_SYNC_SESSION_CURSORS]) == {'session-1': 4}
            assert json.loads(values[manager.LAST_SYNC_EVENT_CURSORS]) == {'session-1': 3}
        finally:
            await manager.close()

    asyncio.run(scenario())

def test_connection_manager_uses_auth_service_token_for_auth_message_without_mutating_ws_url(monkeypatch) -> None:
    fake_auth_service = FakeAuthService(access_token='ws-token')
    fake_ws_client = FakeWebSocketClient()
    fake_ws_client.url = 'ws://example.test/ws?client=desktop'

    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: fake_auth_service)

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        manager._ws_client = fake_ws_client
        manager._base_ws_url = fake_ws_client.url
        try:
            sent = manager._authenticate_websocket_nowait()

            assert sent is True
            assert manager._ws_client.url == 'ws://example.test/ws?client=desktop'
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


def test_connection_manager_waits_for_auth_ack_before_sync_and_business_messages(monkeypatch) -> None:
    fake_ws_client = FakeWebSocketClient()

    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: FakeAuthService())

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        manager._ws_client = fake_ws_client
        try:
            pre_auth_sent = await manager.send_chat_message('session-1', 'hello', 'msg-1')
            assert pre_auth_sent is False

            manager._on_message({'type': 'auth_ack', 'data': {'success': True, 'user_id': 'user-1'}})
            await asyncio.sleep(0.05)

            assert manager._ws_authenticated is True
            assert fake_ws_client.sent_nowait[-1]['type'] == 'sync_messages'

            post_auth_sent = await manager.send_chat_message('session-1', 'hello', 'msg-2')
            assert post_auth_sent is True
            assert fake_ws_client.sent_nowait[-1]['type'] == 'chat_message'
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_connection_manager_connect_waits_for_websocket_authentication(monkeypatch) -> None:
    fake_ws_client = FakeWebSocketClient()

    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: FakeAuthService(access_token='ws-token'))

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        manager._ws_client = fake_ws_client
        manager._loop = asyncio.get_running_loop()
        fake_ws_client.is_connected = False
        try:
            connect_task = asyncio.create_task(manager.connect())
            await asyncio.sleep(0)
            assert connect_task.done() is False
            assert manager.state == connection_manager_module.ConnectionState.CONNECTING

            manager._on_connect()
            await asyncio.sleep(0.05)
            assert connect_task.done() is False
            assert manager.state == connection_manager_module.ConnectionState.AUTHENTICATING
            assert manager.is_connected is False

            manager._on_message({'type': 'auth_ack', 'data': {'success': True, 'user_id': 'user-1'}})
            await connect_task

            assert manager.state == connection_manager_module.ConnectionState.CONNECTED
            assert manager.is_connected is True
            assert fake_ws_client.sent_nowait[-1]['type'] == 'sync_messages'
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_connection_manager_wait_for_initial_sync_waits_until_history_events_listener_finishes(monkeypatch) -> None:
    fake_ws_client = FakeWebSocketClient()
    listener_events: list[str] = []

    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: FakeAuthService())

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        manager._ws_client = fake_ws_client
        manager._loop = asyncio.get_running_loop()
        release_listener = asyncio.get_running_loop().create_future()

        async def listener(message: dict) -> None:
            if message.get('type') != 'history_events':
                return
            listener_events.append('history_events_started')
            await release_listener
            listener_events.append('history_events_finished')

        manager.add_message_listener(listener)
        manager._ws_authenticated = True
        manager._sync_in_flight = True
        try:
            wait_task = asyncio.create_task(manager.wait_for_initial_sync())
            manager._on_message(
                {
                    'type': 'history_events',
                    'data': {
                        'events': [],
                    },
                }
            )

            await asyncio.sleep(0.05)
            assert listener_events == ['history_events_started']
            assert wait_task.done() is False

            release_listener.set_result(None)
            await wait_task

            assert listener_events == ['history_events_started', 'history_events_finished']
            assert manager.sync_in_flight is False
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_connection_manager_times_out_unanswered_ws_auth(monkeypatch) -> None:
    fake_ws_client = FakeWebSocketClient()
    observed_messages: list[dict] = []

    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: FakeAuthService(access_token='ws-token'))

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        manager.WS_AUTH_TIMEOUT_SECONDS = 0.01
        manager._ws_client = fake_ws_client
        manager._loop = asyncio.get_running_loop()
        manager.add_message_listener(lambda message: observed_messages.append(dict(message)))
        try:
            sent = await manager._authenticate_websocket()
            await asyncio.sleep(0.05)

            assert sent is True
            assert manager._ws_auth_in_flight is False
            assert manager._ws_authenticated is False
            assert fake_ws_client.disconnect_calls == 1
            assert observed_messages == [
                {
                    'type': 'error',
                    'data': {
                        'code': 408,
                        'reason': 'ws_auth_timeout',
                        'message': 'WebSocket authentication timed out',
                    },
                }
            ]
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_connection_manager_auth_ack_invalidates_ws_auth_timeout(monkeypatch) -> None:
    fake_ws_client = FakeWebSocketClient()
    observed_messages: list[dict] = []

    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: FakeAuthService(access_token='ws-token'))

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        manager.WS_AUTH_TIMEOUT_SECONDS = 0.01
        manager._ws_client = fake_ws_client
        manager._loop = asyncio.get_running_loop()
        manager.add_message_listener(lambda message: observed_messages.append(dict(message)))
        try:
            sent = await manager._authenticate_websocket()
            manager._on_message({'type': 'auth_ack', 'data': {'success': True}})
            await asyncio.sleep(0.05)

            assert sent is True
            assert manager._ws_auth_in_flight is False
            assert manager._ws_authenticated is True
            assert fake_ws_client.disconnect_calls == 0
            assert observed_messages == [{'type': 'auth_ack', 'data': {'success': True}}]
        finally:
            await manager.close()

    asyncio.run(scenario())




def test_connection_manager_prunes_orphan_sync_cursors(monkeypatch) -> None:
    fake_db = FakeDatabase()
    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: FakeAuthService())

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        manager._db = fake_db
        manager._session_sync_cursors = {'session-1': 5, 'session-orphan': 9}
        manager._event_sync_cursors = {'session-1': 3, 'session-orphan': 8}
        try:
            await manager.prune_sync_state(['session-1'])

            assert manager.session_sync_cursors == {'session-1': 5}
            assert manager.event_sync_cursors == {'session-1': 3}
            assert json.loads(fake_db.app_state[manager.LAST_SYNC_SESSION_CURSORS]) == {'session-1': 5}
            assert json.loads(fake_db.app_state[manager.LAST_SYNC_EVENT_CURSORS]) == {'session-1': 3}
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_connection_manager_clear_sync_state_memory_does_not_touch_persisted_cursors(monkeypatch) -> None:
    fake_db = FakeDatabase()
    fake_db.app_state['last_sync_session_cursors'] = json.dumps({'session-1': 5})
    fake_db.app_state['last_sync_event_cursors'] = json.dumps({'session-1': 3})
    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: FakeAuthService())

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        manager._db = fake_db
        manager._session_sync_cursors = {'session-1': 5}
        manager._event_sync_cursors = {'session-1': 3}
        try:
            manager.clear_sync_state_memory()

            assert manager.session_sync_cursors == {}
            assert manager.event_sync_cursors == {}
            assert json.loads(fake_db.app_state[manager.LAST_SYNC_SESSION_CURSORS]) == {'session-1': 5}
            assert json.loads(fake_db.app_state[manager.LAST_SYNC_EVENT_CURSORS]) == {'session-1': 3}
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_connection_manager_refreshes_token_and_retries_ws_auth_before_reporting_auth_loss(monkeypatch) -> None:
    fake_ws_client = FakeWebSocketClient()
    fake_auth_service = FakeAuthService(access_token='expired-token')
    observed_messages: list[dict] = []

    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: fake_auth_service)

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        manager._ws_client = fake_ws_client
        manager._loop = asyncio.get_running_loop()
        manager._ws_auth_in_flight = True
        manager.add_message_listener(lambda message: observed_messages.append(dict(message)))
        try:
            manager._on_message({'type': 'error', 'data': {'code': 401, 'message': 'expired'}})
            await asyncio.sleep(0.05)

            assert fake_auth_service.refresh_calls == 1
            assert fake_ws_client.sent_nowait[-1]['type'] == 'auth'
            assert fake_ws_client.sent_nowait[-1]['data']['token'] == 'refreshed-token'
            assert manager._ws_auth_in_flight is True
            assert observed_messages == []
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_connection_manager_reports_ws_auth_error_when_token_refresh_fails(monkeypatch) -> None:
    fake_ws_client = FakeWebSocketClient()
    fake_auth_service = FakeAuthService(access_token='expired-token')
    fake_auth_service.refresh_result = False
    observed_messages: list[dict] = []

    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: fake_auth_service)

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        manager._ws_client = fake_ws_client
        manager._loop = asyncio.get_running_loop()
        manager._ws_auth_in_flight = True
        manager.add_message_listener(lambda message: observed_messages.append(dict(message)))
        try:
            terminal_message = {'type': 'error', 'data': {'code': 401, 'message': 'expired'}}
            manager._on_message(terminal_message)
            await asyncio.sleep(0.05)

            assert fake_auth_service.refresh_calls == 1
            assert fake_ws_client.sent_nowait == []
            assert manager._ws_auth_in_flight is False
            assert observed_messages == [terminal_message]
        finally:
            await manager.close()

    asyncio.run(scenario())
def test_connection_manager_ignores_late_callbacks_from_closed_generation(monkeypatch) -> None:
    fake_ws_client = FakeWebSocketClient()
    received: list[dict] = []

    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: FakeAuthService())
    monkeypatch.setattr(connection_manager_module, 'get_websocket_client', lambda: fake_ws_client)

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        await manager.initialize()
        manager.add_message_listener(lambda message: received.append(dict(message)))
        stale_on_message = fake_ws_client.callbacks['on_message']

        await manager.close()
        stale_on_message({'type': 'chat_message', 'data': {'session_id': 'session-1', 'session_seq': 1}})
        await asyncio.sleep(0.05)

        assert received == []
        assert manager.ws_client is None
        assert manager._loop is None

    asyncio.run(scenario())


def test_connection_manager_ignores_late_auth_ack_and_events_from_closed_generation(monkeypatch) -> None:
    fake_db = FakeDatabase()
    fake_ws_client = FakeWebSocketClient()
    received: list[dict] = []

    monkeypatch.setattr(connection_manager_module, 'get_auth_service', lambda: FakeAuthService())
    monkeypatch.setattr(connection_manager_module, 'get_websocket_client', lambda: fake_ws_client)

    async def scenario() -> None:
        manager = connection_manager_module.ConnectionManager()
        manager._db = fake_db
        await manager.initialize()
        manager.add_message_listener(lambda message: received.append(dict(message)))
        stale_on_message = fake_ws_client.callbacks['on_message']

        await manager.close()
        stale_on_message({'type': 'auth_ack', 'data': {'success': True}})
        stale_on_message({'type': 'message_edit', 'data': {'session_id': 'session-1', 'event_seq': 7}})
        stale_on_message({'type': 'group_profile_update', 'data': {'session_id': 'session-2', 'event_seq': 9}})
        await asyncio.sleep(0.05)

        assert fake_ws_client.sent_nowait == []
        assert manager.session_sync_cursors == {}
        assert manager.event_sync_cursors == {}
        assert fake_db.app_state == {}
        assert received == []

    asyncio.run(scenario())
