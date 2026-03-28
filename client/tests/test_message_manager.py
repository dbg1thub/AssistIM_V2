from __future__ import annotations

import asyncio
import sys
import time
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

from client.events.contact_events import ContactEvent
from client.managers import message_manager as message_manager_module
from client.models.message import ChatMessage, MessageStatus, MessageType


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event: str, data: dict) -> None:
        self.events.append((event, data))


class FakeConnectionManager:
    def __init__(self, send_results: list[bool]) -> None:
        self._send_results = list(send_results)
        self._listeners = []
        self.sent_payloads: list[dict] = []

    def add_message_listener(self, listener) -> None:
        self._listeners.append(listener)

    def remove_message_listener(self, listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    async def send_chat_message(self, session_id: str, content: str, msg_id: str, message_type: str = 'text', extra=None) -> bool:
        self.sent_payloads.append(
            {
                'session_id': session_id,
                'content': content,
                'msg_id': msg_id,
                'message_type': message_type,
                'extra': dict(extra or {}),
            }
        )
        await asyncio.sleep(0)
        if self._send_results:
            return self._send_results.pop(0)
        return True

    async def send_typing(self, session_id: str) -> bool:
        return True

    async def send_read_ack(self, session_id: str, message_id: str) -> bool:
        return True


class FakeDatabase:
    def __init__(self) -> None:
        self.is_connected = False
        self.messages: dict[str, ChatMessage] = {}
        self.saved_batches: list[list[ChatMessage]] = []

    async def save_message(self, message: ChatMessage) -> None:
        self.messages[message.message_id] = message

    async def get_message(self, message_id: str) -> ChatMessage | None:
        return self.messages.get(message_id)

    async def get_existing_message_ids(self, message_ids: list[str]) -> set[str]:
        return {message_id for message_id in message_ids if message_id in self.messages}

    async def get_messages(self, session_id: str, limit: int = 50, before_timestamp=None) -> list[ChatMessage]:
        return [message for message in self.messages.values() if message.session_id == session_id][:limit]

    async def apply_read_receipt(self, session_id: str, reader_id: str, message_id: str, last_read_seq: int) -> list[str]:
        return []

    async def update_message_content(self, message_id: str, content: str) -> None:
        message = self.messages.get(message_id)
        if message is not None:
            message.content = content

    async def update_message_status(self, message_id: str, status) -> None:
        message = self.messages.get(message_id)
        if message is not None:
            message.status = status

    async def delete_message(self, message_id: str) -> None:
        self.messages.pop(message_id, None)

    async def save_messages_batch(self, messages: list[ChatMessage]) -> None:
        self.saved_batches.append(list(messages))
        for message in messages:
            self.messages[message.message_id] = message


async def _wait_until(predicate, *, timeout: float = 0.5) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError('condition was not met before timeout')


def test_message_manager_retries_on_ack_timeout_and_merges_canonical_ack(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([True, True])
    fake_db = FakeDatabase()

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('alice')
        manager._ack_timeout = 0.01
        manager._transport_retry_delay = 0.01
        manager._max_attempts = 3
        await manager.initialize()
        try:
            message = await manager.send_message('session-1', 'hello world')
            await _wait_until(lambda: len(fake_conn_manager.sent_payloads) == 1)

            pending = manager._pending_messages[message.message_id]
            assert pending.attempt_count == 1
            assert pending.awaiting_ack is True

            pending.last_attempt_at = time.time() - 1
            await manager._check_pending_messages()
            await _wait_until(lambda: len(fake_conn_manager.sent_payloads) == 2)

            await manager._process_ack(
                {
                    'type': 'message_ack',
                    'msg_id': message.message_id,
                    'data': {
                        'msg_id': message.message_id,
                        'success': True,
                        'message': {
                            'message_id': message.message_id,
                            'session_id': 'session-1',
                            'sender_id': 'alice',
                            'content': 'hello world',
                            'message_type': 'text',
                            'status': 'sent',
                            'session_seq': 7,
                            'read_count': 0,
                            'read_target_count': 1,
                            'read_by_user_ids': [],
                            'is_read_by_me': True,
                            'extra': {'session_seq': 7},
                        },
                    },
                }
            )

            stored = await fake_db.get_message(message.message_id)
            assert stored is not None
            assert stored.status == MessageStatus.SENT
            assert stored.extra['session_seq'] == 7
            assert message.message_id not in manager._pending_messages
            assert len(fake_conn_manager.sent_payloads) == 2
            assert any(event == message_manager_module.MessageEvent.ACK for event, _ in fake_event_bus.events)
        finally:
            await manager.close()

    asyncio.run(scenario())






def test_message_manager_bridges_contact_refresh_events(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('alice')
        await manager.initialize()
        try:
            await manager._handle_ws_message(
                {
                    'type': 'contact_refresh',
                    'data': {
                        'reason': 'friend_request_created',
                        'request_id': 'req-1',
                        'sender_id': 'bob',
                        'receiver_id': 'alice',
                    },
                }
            )

            assert fake_event_bus.events == [
                (
                    ContactEvent.SYNC_REQUIRED,
                    {
                        'reason': 'friend_request_created',
                        'payload': {
                            'reason': 'friend_request_created',
                            'request_id': 'req-1',
                            'sender_id': 'bob',
                            'receiver_id': 'alice',
                        },
                        'message': {
                            'type': 'contact_refresh',
                            'data': {
                                'reason': 'friend_request_created',
                                'request_id': 'req-1',
                                'sender_id': 'bob',
                                'receiver_id': 'alice',
                            },
                        },
                    },
                )
            ]
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_replays_history_events(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_db.messages['m-1'] = ChatMessage(
        message_id='m-1',
        session_id='session-1',
        sender_id='alice',
        content='original',
        status=MessageStatus.SENT,
        is_self=False,
    )

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('bob')
        await manager.initialize()
        try:
            await manager._handle_ws_message(
                {
                    'type': 'history_events',
                    'data': {
                        'events': [
                            {
                                'type': 'message_edit',
                                'data': {
                                    'session_id': 'session-1',
                                    'message_id': 'm-1',
                                    'user_id': 'alice',
                                    'content': 'edited',
                                    'status': 'edited',
                                    'event_seq': 1,
                                },
                            },
                            {
                                'type': 'message_recall',
                                'data': {
                                    'session_id': 'session-1',
                                    'message_id': 'm-1',
                                    'user_id': 'alice',
                                    'status': 'recalled',
                                    'event_seq': 2,
                                },
                            },
                        ],
                    },
                }
            )

            stored = await fake_db.get_message('m-1')
            assert stored is not None
            assert stored.status == MessageStatus.RECALLED
            assert stored.content != 'edited'
            assert 'recall_notice' in stored.extra
            assert any(event == message_manager_module.MessageEvent.EDITED for event, _ in fake_event_bus.events)
            assert any(event == message_manager_module.MessageEvent.RECALLED for event, _ in fake_event_bus.events)
        finally:
            await manager.close()

    asyncio.run(scenario())



def test_message_manager_normalize_loaded_message_ignores_legacy_aliases(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('alice')
        await manager.initialize()
        try:
            message = manager._normalize_loaded_message(
                {
                    'id': 'legacy-id',
                    'msg_id': 'legacy-msg-id',
                    'type': 'image',
                    'sender_id': 'bob',
                    'content': 'legacy payload',
                },
                default_session_id='session-1',
            )

            assert message.message_id == ''
            assert message.message_type == MessageType.TEXT
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_history_messages_deduplicates_by_canonical_message_id(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_db.messages['m-1'] = ChatMessage(
        message_id='m-1',
        session_id='session-1',
        sender_id='alice',
        content='existing',
        status=MessageStatus.SENT,
        is_self=False,
    )

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('bob')
        await manager.initialize()
        try:
            await manager._handle_ws_message(
                {
                    'type': 'history_messages',
                    'data': {
                        'messages': [
                            {
                                'message_id': 'm-1',
                                'session_id': 'session-1',
                                'sender_id': 'alice',
                                'content': 'duplicate',
                                'message_type': 'text',
                            }
                        ],
                    },
                }
            )

            assert fake_db.saved_batches == []
            assert fake_event_bus.events[-1][0] == message_manager_module.MessageEvent.SYNC_COMPLETED
            assert fake_event_bus.events[-1][1]['count'] == 0
            assert fake_event_bus.events[-1][1]['skipped'] == 1
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_ignores_legacy_mutation_event_message_id_alias(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_db.messages['m-1'] = ChatMessage(
        message_id='m-1',
        session_id='session-1',
        sender_id='alice',
        content='original',
        status=MessageStatus.SENT,
        is_self=False,
    )

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('bob')
        await manager.initialize()
        try:
            await manager._handle_ws_message(
                {
                    'type': 'message_recall',
                    'data': {
                        'session_id': 'session-1',
                        'msg_id': 'm-1',
                        'user_id': 'alice',
                    },
                }
            )

            stored = await fake_db.get_message('m-1')
            assert stored is not None
            assert stored.status == MessageStatus.SENT
            assert all(event != message_manager_module.MessageEvent.RECALLED for event, _ in fake_event_bus.events)
        finally:
            await manager.close()

    asyncio.run(scenario())

def test_message_manager_ignores_incoming_chat_message_without_canonical_message_id(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('bob')
        await manager.initialize()
        try:
            await manager._handle_ws_message(
                {
                    'type': 'chat_message',
                    'msg_id': 'legacy-envelope-id',
                    'data': {
                        'session_id': 'session-1',
                        'sender_id': 'alice',
                        'content': 'hello',
                        'message_type': 'text',
                    },
                }
            )

            assert fake_db.messages == {}
            assert all(event != message_manager_module.MessageEvent.RECEIVED for event, _ in fake_event_bus.events)
        finally:
            await manager.close()

    asyncio.run(scenario())

def test_message_manager_remote_history_skips_payloads_without_canonical_message_id(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()

    class FakeChatService:
        async def fetch_messages(self, session_id: str, limit: int, before_timestamp=None) -> list[dict]:
            return [
                {
                    'session_id': session_id,
                    'sender_id': 'alice',
                    'content': 'remote legacy payload',
                    'message_type': 'text',
                }
            ]

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(message_manager_module, 'get_chat_service', lambda: FakeChatService())

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('bob')
        await manager.initialize()
        try:
            messages = await manager.get_messages('session-1', limit=10)

            assert messages == []
            assert fake_db.saved_batches == []
        finally:
            await manager.close()

    asyncio.run(scenario())

def test_message_manager_ignores_legacy_read_event_message_id_alias(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()

    apply_calls: list[tuple[str, str, str, int]] = []

    async def apply_read_receipt(session_id: str, reader_id: str, message_id: str, last_read_seq: int) -> list[str]:
        apply_calls.append((session_id, reader_id, message_id, last_read_seq))
        return []

    fake_db.apply_read_receipt = apply_read_receipt  # type: ignore[method-assign]

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('alice')
        await manager.initialize()
        try:
            await manager._handle_ws_message(
                {
                    'type': 'read',
                    'data': {
                        'session_id': 'session-1',
                        'last_read_message_id': 'legacy-message-id',
                        'user_id': 'bob',
                        'last_read_seq': 3,
                    },
                }
            )

            assert apply_calls == [('session-1', 'bob', '', 3)]
            assert fake_event_bus.events[-1] == (
                message_manager_module.MessageEvent.READ,
                {
                    'session_id': 'session-1',
                    'message_id': '',
                    'user_id': 'bob',
                    'last_read_seq': 3,
                    'changed_message_ids': [],
                },
            )
        finally:
            await manager.close()

    asyncio.run(scenario())
