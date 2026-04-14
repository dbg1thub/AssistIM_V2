from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
import time
import types
from datetime import datetime
from enum import Enum
from pathlib import Path

import pytest


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
        def __init__(self, year=2000, month=1, day=1):
            self.year = year
            self.month = month
            self.day = day

        @staticmethod
        def currentDate():
            return _DummyQDate(2026, 4, 3)

        def toString(self, _fmt=None):
            return f'{self.year:04d}-{self.month:02d}-{self.day:02d}'

        def __eq__(self, other):
            return isinstance(other, _DummyQDate) and (self.year, self.month, self.day) == (other.year, other.month, other.day)

    qtcore.QLocale = _DummyQLocale
    qtcore.QDate = _DummyQDate
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

from client.events.contact_events import ContactEvent
from client.managers import message_manager as message_manager_module
from client.managers import session_manager as session_manager_module
from client.ui.controllers import chat_controller as chat_controller_module
from client.models.message import ChatMessage, MessageStatus, MessageType, Session


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

    async def send_typing(self, session_id: str, *, typing: bool = True) -> bool:
        self.sent_payloads.append(
            {
                'type': 'typing',
                'session_id': session_id,
                'typing': typing,
            }
        )
        return True

class FakeDatabase:
    def __init__(self) -> None:
        self.is_connected = False
        self.messages: dict[str, ChatMessage] = {}
        self.sessions: dict[str, Session] = {}
        self.saved_batches: list[list[ChatMessage]] = []
        self.profile_update_calls: list[tuple[str, str, dict]] = []

    async def save_message(self, message: ChatMessage) -> None:
        self.messages[message.message_id] = message

    async def get_message(self, message_id: str) -> ChatMessage | None:
        return self.messages.get(message_id)

    async def get_existing_message_ids(self, message_ids: list[str]) -> set[str]:
        return {message_id for message_id in message_ids if message_id in self.messages}

    async def get_messages_by_ids(self, message_ids: list[str]) -> dict[str, ChatMessage]:
        return {message_id: self.messages[message_id] for message_id in message_ids if message_id in self.messages}

    async def get_messages(self, session_id: str, limit: int = 50, before_timestamp=None) -> list[ChatMessage]:
        return [message for message in self.messages.values() if message.session_id == session_id][:limit]

    async def get_session(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

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

    async def apply_sender_profile_update(self, session_id: str, user_id: str, sender_profile: dict) -> list[str]:
        self.profile_update_calls.append((session_id, user_id, dict(sender_profile)))
        changed: list[str] = []
        for message in self.messages.values():
            if message.session_id != session_id or message.sender_id != user_id:
                continue
            message.extra["sender_avatar"] = str(sender_profile.get("avatar", "") or "")
            message.extra["sender_nickname"] = str(sender_profile.get("nickname", "") or "")
            changed.append(message.message_id)
        return changed


class FakeE2EEService:
    LOCAL_PLAINTEXT_VERSION = 'dpapi-text-v1'
    GROUP_SENDER_KEY_SCHEME = 'group-sender-key-v1'
    GROUP_FANOUT_SCHEME = 'group-sender-key-fanout-v1'

    def __init__(self) -> None:
        self.encrypt_calls: list[tuple[str, str]] = []
        self.group_encrypt_calls: list[tuple[str, str, int, str, int]] = []
        self.group_attachment_encrypt_calls: list[tuple[str, str, int, str, int, str, int | None]] = []
        self.fetch_prekey_bundle_calls: list[str] = []
        self.group_prekey_bundles: dict[str, list[dict]] = {}
        self.decrypt_calls: list[tuple[str, dict]] = []
        self.decrypt_attachment_calls: list[tuple[bytes, dict]] = []
        self.text_decryption_state: dict[str, object] = {
            'state': 'ready',
            'can_decrypt': True,
            'reprovision_required': False,
            'local_device_id': 'device-bob',
            'target_device_id': 'device-bob',
        }
        self.attachment_decryption_state: dict[str, object] = {
            'state': 'ready',
            'can_decrypt': True,
            'reprovision_required': False,
            'local_device_id': 'device-bob',
            'target_device_id': 'device-bob',
        }

    @staticmethod
    def is_encrypted_extra(extra: dict | None) -> bool:
        return bool(dict((extra or {}).get('encryption') or {}).get('enabled'))

    @staticmethod
    def protect_local_plaintext(plaintext: str) -> str:
        return f'local:{plaintext}'

    @staticmethod
    def recover_local_plaintext(protected_text: str) -> str:
        return str(protected_text or '').removeprefix('local:')

    async def encrypt_text_for_user(self, recipient_user_id: str, plaintext: str) -> tuple[str, dict]:
        self.encrypt_calls.append((recipient_user_id, plaintext))
        ciphertext = f'cipher:{plaintext}'
        return (
            ciphertext,
            {
                'enabled': True,
                'scheme': 'x25519-aesgcm-v1',
                'sender_device_id': 'device-alice',
                'recipient_device_id': 'device-bob',
                'recipient_user_id': recipient_user_id,
                'recipient_prekey_type': 'signed',
                'recipient_prekey_id': 1,
                'content_ciphertext': ciphertext,
                'nonce': 'nonce-1',
                'sender_identity_key_public': 'pub-alice',
                'local_plaintext': self.protect_local_plaintext(plaintext),
                'local_plaintext_version': self.LOCAL_PLAINTEXT_VERSION,
            },
        )

    async def fetch_prekey_bundle(self, user_id: str) -> list[dict]:
        self.fetch_prekey_bundle_calls.append(user_id)
        return [dict(item) for item in self.group_prekey_bundles.get(user_id, [])]

    async def encrypt_text_for_group_session(
        self,
        session_id: str,
        plaintext: str,
        recipient_bundles: list[dict],
        *,
        member_version: int = 0,
        owner_user_id: str = '',
        force_rotate: bool = False,
    ) -> tuple[str, dict]:
        self.group_encrypt_calls.append((session_id, plaintext, member_version, owner_user_id, len(recipient_bundles)))
        ciphertext = f'groupcipher:{plaintext}'
        fanout = [
            {
                'enabled': True,
                'scheme': self.GROUP_FANOUT_SCHEME,
                'session_id': session_id,
                'recipient_device_id': str(dict(bundle).get('device_id') or ''),
            }
            for bundle in recipient_bundles
        ]
        return (
            ciphertext,
            {
                'enabled': True,
                'scheme': self.GROUP_SENDER_KEY_SCHEME,
                'session_id': session_id,
                'sender_device_id': 'device-alice',
                'sender_key_id': 'group-key-1',
                'member_version': member_version,
                'owner_user_id': owner_user_id,
                'content_ciphertext': ciphertext,
                'nonce': 'group-nonce-1',
                'fanout': fanout,
                'local_plaintext': self.protect_local_plaintext(plaintext),
                'local_plaintext_version': self.LOCAL_PLAINTEXT_VERSION,
            },
        )

    async def decrypt_text_content(self, content: str, extra: dict | None) -> str | None:
        normalized_extra = dict(extra or {})
        self.decrypt_calls.append((content, normalized_extra))
        encryption = dict(normalized_extra.get('encryption') or {})
        protected_plaintext = str(encryption.get('local_plaintext') or '')
        if protected_plaintext:
            return self.recover_local_plaintext(protected_plaintext)
        ciphertext = str(encryption.get('content_ciphertext') or content or '')
        if str(encryption.get('scheme') or '') == self.GROUP_SENDER_KEY_SCHEME:
            return ciphertext.removeprefix('groupcipher:')
        return ciphertext.removeprefix('cipher:')

    async def decrypt_attachment_bytes(self, ciphertext_bytes: bytes, attachment_encryption: dict | None) -> tuple[bytes, dict]:
        normalized = dict(attachment_encryption or {})
        self.decrypt_attachment_calls.append((bytes(ciphertext_bytes), normalized))
        metadata = {
            'original_name': 'secret.pdf',
            'mime_type': 'application/pdf',
            'size_bytes': 9,
        }
        return b'plain-pdf', metadata

    async def describe_text_decryption_state(self, extra: dict | None) -> dict:
        return dict(self.text_decryption_state)

    async def describe_attachment_decryption_state(self, attachment_encryption: dict | None) -> dict:
        return dict(self.attachment_decryption_state)

    async def encrypt_attachment_for_user(
        self,
        recipient_user_id: str,
        file_path: str,
        *,
        fallback_name: str = '',
        size_bytes: int | None = None,
        mime_type: str = '',
    ):
        target = Path(tempfile.gettempdir()) / 'assistim_test_encrypted_attachment.bin'
        target.write_bytes(b'encrypted-upload')
        return types.SimpleNamespace(
            upload_file_path=str(target),
            cleanup_file_path=str(target),
            attachment_encryption={
                'enabled': True,
                'scheme': 'aesgcm-file+x25519-v1',
                'recipient_user_id': recipient_user_id,
                'original_name': fallback_name,
                'size_bytes': size_bytes,
                'mime_type': mime_type,
            },
        )

    async def encrypt_attachment_for_group_session(
        self,
        session_id: str,
        file_path: str,
        recipient_bundles: list[dict],
        *,
        fallback_name: str = '',
        size_bytes: int | None = None,
        mime_type: str = '',
        member_version: int = 0,
        owner_user_id: str = '',
        force_rotate: bool = False,
    ):
        del file_path, force_rotate
        self.group_attachment_encrypt_calls.append(
            (session_id, fallback_name, member_version, owner_user_id, len(recipient_bundles), mime_type, size_bytes)
        )
        target = Path(tempfile.gettempdir()) / 'assistim_test_group_encrypted_attachment.bin'
        target.write_bytes(b'group-encrypted-upload')
        return types.SimpleNamespace(
            upload_file_path=str(target),
            cleanup_file_path=str(target),
            attachment_encryption={
                'enabled': True,
                'scheme': 'aesgcm-file+group-sender-key-v1',
                'session_id': session_id,
                'sender_device_id': 'device-alice',
                'sender_key_id': 'group-key-1',
                'member_version': member_version,
                'owner_user_id': owner_user_id,
                'fanout': [
                    {
                        'enabled': True,
                        'scheme': self.GROUP_FANOUT_SCHEME,
                        'session_id': session_id,
                        'recipient_device_id': str(dict(bundle).get('device_id') or ''),
                    }
                    for bundle in recipient_bundles
                ],
                'metadata_ciphertext': 'meta:cipher',
                'nonce': 'group-meta-nonce-1',
                'local_metadata': self.protect_local_plaintext(
                    json.dumps(
                        {
                            'original_name': fallback_name,
                            'mime_type': mime_type,
                            'size_bytes': size_bytes,
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                    )
                ),
                'local_plaintext_version': self.LOCAL_PLAINTEXT_VERSION,
            },
        )


async def _wait_until(predicate, *, timeout: float = 0.5) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError('condition was not met before timeout')


def test_message_send_queue_marks_unprocessed_message_failed_on_stop_timeout() -> None:
    results = []

    class SlowConnectionManager:
        async def send_chat_message(self, **kwargs):
            await asyncio.sleep(10)
            return True

    async def on_send_result(queued, success: bool) -> None:
        results.append((queued.message_id, success))

    async def scenario() -> None:
        queue = message_manager_module.MessageSendQueue(SlowConnectionManager(), on_send_result)
        queue.STOP_TIMEOUT = 0.01
        await queue.start()
        await queue.enqueue('m-queued', 'session-1', 'hello', 'text', {})
        await queue.stop()

    asyncio.run(scenario())

    assert results == [('m-queued', False)]


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






def test_message_manager_marks_pending_message_failed_on_ws_error(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([True])
    fake_db = FakeDatabase()

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('alice')
        await manager.initialize()
        try:
            message = await manager.send_message('session-1', 'hello world')
            await _wait_until(lambda: message.message_id in manager._pending_messages)

            await manager._handle_ws_message(
                {
                    'type': 'error',
                    'msg_id': message.message_id,
                    'data': {
                        'code': 422,
                        'message': 'content is required',
                    },
                }
            )

            stored = await fake_db.get_message(message.message_id)
            assert stored is not None
            assert stored.status == MessageStatus.FAILED
            assert message.message_id not in manager._pending_messages
            failed_events = [
                payload
                for event, payload in fake_event_bus.events
                if event == message_manager_module.MessageEvent.FAILED
            ]
            assert failed_events[-1]['reason'] == 'content is required'
            assert failed_events[-1]['code'] == 422
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
                    'type': 'history_messages',
                    'data': {
                        'messages': [],
                    },
                }
            )
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
            assert fake_event_bus.events[-1] == (
                message_manager_module.MessageEvent.SYNC_COMPLETED,
                {
                    'count': 0,
                    'messages': [],
                    'skipped': 0,
                    'events_replayed': 2,
                },
            )
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_replays_history_mutations_without_cached_message(monkeypatch) -> None:
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
                    'type': 'history_messages',
                    'data': {'messages': []},
                }
            )
            await manager._handle_ws_message(
                {
                    'type': 'history_events',
                    'data': {
                        'events': [
                            {
                                'type': 'message_edit',
                                'data': {
                                    'session_id': 'session-1',
                                    'message_id': 'm-missing',
                                    'user_id': 'alice',
                                    'content': 'edited from replay',
                                    'status': 'edited',
                                    'session_seq': 3,
                                    'event_seq': 11,
                                },
                            },
                            {
                                'type': 'message_recall',
                                'data': {
                                    'session_id': 'session-1',
                                    'message_id': 'm-missing',
                                    'user_id': 'alice',
                                    'status': 'recalled',
                                    'event_seq': 12,
                                },
                            },
                        ],
                    },
                }
            )

            stored = await fake_db.get_message('m-missing')
            assert stored is not None
            assert stored.session_id == 'session-1'
            assert stored.sender_id == 'alice'
            assert stored.status == MessageStatus.RECALLED
            assert stored.extra['session_seq'] == 3
            assert 'recall_notice' in stored.extra
            assert any(event == message_manager_module.MessageEvent.EDITED for event, _ in fake_event_bus.events)
            assert any(event == message_manager_module.MessageEvent.RECALLED for event, _ in fake_event_bus.events)
        finally:
            await manager.close()

    asyncio.run(scenario())



def test_message_manager_edits_encrypted_message_with_sanitized_transport_extra(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()

    class FakeChatService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict | None]] = []

        async def edit_message(self, message_id: str, new_content: str, *, extra=None) -> None:
            self.calls.append((message_id, new_content, dict(extra) if isinstance(extra, dict) else None))

    fake_chat_service = FakeChatService()
    fake_db.sessions['session-1'] = Session(
        session_id='session-1',
        name='Bob',
        session_type='direct',
        participant_ids=['alice', 'bob'],
        extra={'encryption_mode': 'e2ee_private'},
    )
    fake_db.messages['m-enc-1'] = ChatMessage(
        message_id='m-enc-1',
        session_id='session-1',
        sender_id='alice',
        content='old secret',
        message_type=MessageType.TEXT,
        status=MessageStatus.SENT,
        is_self=True,
        extra={
            'session_type': 'direct',
            'participant_ids': ['alice', 'bob'],
            'encryption': {
                'enabled': True,
                'content_ciphertext': 'cipher:old secret',
                'local_plaintext': 'local:old secret',
            },
        },
    )

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(message_manager_module, 'get_chat_service', lambda: fake_chat_service)
    monkeypatch.setattr(message_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('alice')
        await manager.initialize()
        try:
            success = await manager.edit_message('m-enc-1', 'edited secret')

            assert success is True
            assert fake_e2ee_service.encrypt_calls == [('bob', 'edited secret')]
            assert fake_chat_service.calls == [
                (
                    'm-enc-1',
                    'cipher:edited secret',
                    {
                        'session_type': 'direct',
                        'participant_ids': ['alice', 'bob'],
                        'encryption': {
                            'enabled': True,
                            'scheme': 'x25519-aesgcm-v1',
                            'sender_device_id': 'device-alice',
                            'recipient_device_id': 'device-bob',
                            'recipient_user_id': 'bob',
                            'recipient_prekey_type': 'signed',
                            'recipient_prekey_id': 1,
                            'content_ciphertext': 'cipher:edited secret',
                            'nonce': 'nonce-1',
                            'sender_identity_key_public': 'pub-alice',
                            'local_plaintext_version': 'dpapi-text-v1',
                        },
                    },
                )
            ]
            stored = await fake_db.get_message('m-enc-1')
            assert stored is not None
            assert stored.content == 'edited secret'
            assert stored.status == MessageStatus.EDITED
            assert stored.extra['encryption']['local_plaintext'] == 'local:edited secret'
            assert any(event == message_manager_module.MessageEvent.EDITED for event, _ in fake_event_bus.events)
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_processes_encrypted_edit_event(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()
    fake_db.messages['m-enc-2'] = ChatMessage(
        message_id='m-enc-2',
        session_id='session-1',
        sender_id='alice',
        content='old secret',
        message_type=MessageType.TEXT,
        status=MessageStatus.SENT,
        is_self=False,
        extra={'session_type': 'direct'},
    )

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(message_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('bob')
        await manager.initialize()
        try:
            await manager._handle_ws_message(
                {
                    'type': 'message_edit',
                    'data': {
                        'session_id': 'session-1',
                        'message_id': 'm-enc-2',
                        'user_id': 'alice',
                        'content': 'cipher:edited secret',
                        'status': 'edited',
                        'extra': {
                            'session_type': 'direct',
                            'encryption': {
                                'enabled': True,
                                'content_ciphertext': 'cipher:edited secret',
                                'sender_device_id': 'device-alice',
                                'recipient_device_id': 'device-bob',
                                'sender_identity_key_public': 'pub-alice',
                                'nonce': 'nonce-1',
                            },
                        },
                    },
                }
            )

            stored = await fake_db.get_message('m-enc-2')
            assert stored is not None
            assert stored.content == 'edited secret'
            assert stored.status == MessageStatus.EDITED
            assert stored.extra['encryption']['local_plaintext'] == 'local:edited secret'
            assert fake_e2ee_service.decrypt_calls
            assert any(event == message_manager_module.MessageEvent.EDITED for event, _ in fake_event_bus.events)
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_ack_preserves_local_plaintext_for_direct_e2ee_sender(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([True])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()
    fake_db.sessions['session-1'] = Session(
        session_id='session-1',
        name='Bob',
        session_type='direct',
        participant_ids=['alice', 'bob'],
        extra={'encryption_mode': 'e2ee_private'},
    )

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('alice')
        manager._e2ee_service = fake_e2ee_service
        await manager.initialize()
        try:
            message = await manager.send_message('session-1', 'hello bob', MessageType.TEXT)
            await _wait_until(lambda: len(fake_conn_manager.sent_payloads) == 1)

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
                            'content': 'cipher:hello bob',
                            'message_type': 'text',
                            'status': 'sent',
                            'extra': {
                                'encryption': {
                                    'enabled': True,
                                    'scheme': 'x25519-aesgcm-v1',
                                    'sender_device_id': 'device-alice',
                                    'recipient_device_id': 'device-bob',
                                    'recipient_user_id': 'bob',
                                    'recipient_prekey_type': 'signed',
                                    'recipient_prekey_id': 1,
                                    'content_ciphertext': 'cipher:hello bob',
                                    'nonce': 'nonce-1',
                                    'sender_identity_key_public': 'pub-alice',
                                }
                            },
                        },
                    },
                }
            )

            stored = await fake_db.get_message(message.message_id)
            assert stored is not None
            assert stored.status == MessageStatus.SENT
            assert stored.content == 'hello bob'
            assert stored.extra['encryption']['local_plaintext'] == 'local:hello bob'
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_edits_group_encrypted_message_with_sender_key_transport(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()
    class FakeChatService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict | None]] = []

        async def edit_message(self, message_id: str, new_content: str, *, extra=None) -> None:
            self.calls.append((message_id, new_content, extra))

    fake_chat_service = FakeChatService()
    fake_e2ee_service.group_prekey_bundles = {
        'bob': [{'device_id': 'device-bob'}],
        'charlie': [{'device_id': 'device-charlie'}],
    }
    fake_db.sessions['session-group-1'] = Session(
        session_id='session-group-1',
        name='Team',
        session_type='group',
        participant_ids=['alice', 'bob', 'charlie'],
        extra={
            'encryption_mode': 'e2ee_group',
            'members': [
                {'id': 'alice'},
                {'id': 'bob'},
                {'id': 'charlie'},
            ],
            'group_member_version': 9,
        },
    )
    fake_db.messages['m-group-edit-1'] = ChatMessage(
        message_id='m-group-edit-1',
        session_id='session-group-1',
        sender_id='alice',
        content='old group secret',
        message_type=MessageType.TEXT,
        status=MessageStatus.SENT,
        is_self=True,
        extra={
            'session_type': 'group',
            'participant_ids': ['alice', 'bob', 'charlie'],
            'members': [{'id': 'alice'}, {'id': 'bob'}, {'id': 'charlie'}],
            'group_member_version': 9,
            'encryption': {
                'enabled': True,
                'scheme': 'group-sender-key-v1',
                'session_id': 'session-group-1',
                'sender_device_id': 'device-alice',
                'sender_key_id': 'group-key-1',
                'member_version': 9,
                'content_ciphertext': 'groupcipher:old group secret',
                'local_plaintext': 'local:old group secret',
            },
        },
    )

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(message_manager_module, 'get_chat_service', lambda: fake_chat_service)
    monkeypatch.setattr(message_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('alice')
        await manager.initialize()
        try:
            success = await manager.edit_message('m-group-edit-1', 'edited team secret')

            assert success is True
            assert fake_e2ee_service.fetch_prekey_bundle_calls == ['bob', 'charlie']
            assert fake_e2ee_service.group_encrypt_calls == [
                ('session-group-1', 'edited team secret', 9, 'alice', 2)
            ]
            assert fake_chat_service.calls == [
                (
                    'm-group-edit-1',
                    'groupcipher:edited team secret',
                    {
                        'session_type': 'group',
                        'participant_ids': ['alice', 'bob', 'charlie'],
                        'members': [{'id': 'alice'}, {'id': 'bob'}, {'id': 'charlie'}],
                        'group_member_version': 9,
                        'encryption': {
                            'enabled': True,
                            'scheme': 'group-sender-key-v1',
                            'session_id': 'session-group-1',
                            'sender_device_id': 'device-alice',
                            'sender_key_id': 'group-key-1',
                            'member_version': 9,
                            'owner_user_id': 'alice',
                            'content_ciphertext': 'groupcipher:edited team secret',
                            'nonce': 'group-nonce-1',
                            'fanout': [
                                {
                                    'enabled': True,
                                    'scheme': 'group-sender-key-fanout-v1',
                                    'session_id': 'session-group-1',
                                    'recipient_device_id': 'device-bob',
                                },
                                {
                                    'enabled': True,
                                    'scheme': 'group-sender-key-fanout-v1',
                                    'session_id': 'session-group-1',
                                    'recipient_device_id': 'device-charlie',
                                },
                            ],
                            'local_plaintext_version': 'dpapi-text-v1',
                        },
                    },
                )
            ]
            stored = await fake_db.get_message('m-group-edit-1')
            assert stored is not None
            assert stored.content == 'edited team secret'
            assert stored.status == MessageStatus.EDITED
            assert stored.extra['encryption']['local_plaintext'] == 'local:edited team secret'
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_processes_group_encrypted_edit_event(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()
    fake_db.messages['m-group-edit-2'] = ChatMessage(
        message_id='m-group-edit-2',
        session_id='session-group-1',
        sender_id='alice',
        content='old group secret',
        message_type=MessageType.TEXT,
        status=MessageStatus.SENT,
        is_self=False,
        extra={'session_type': 'group'},
    )

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(message_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('bob')
        await manager.initialize()
        try:
            await manager._handle_ws_message(
                {
                    'type': 'message_edit',
                    'data': {
                        'session_id': 'session-group-1',
                        'message_id': 'm-group-edit-2',
                        'user_id': 'alice',
                        'content': 'groupcipher:edited team secret',
                        'status': 'edited',
                        'extra': {
                            'session_type': 'group',
                            'encryption': {
                                'enabled': True,
                                'scheme': 'group-sender-key-v1',
                                'session_id': 'session-group-1',
                                'sender_device_id': 'device-alice',
                                'sender_key_id': 'group-key-1',
                                'member_version': 9,
                                'content_ciphertext': 'groupcipher:edited team secret',
                                'nonce': 'group-nonce-1',
                                'fanout': [
                                    {
                                        'enabled': True,
                                        'scheme': 'group-sender-key-fanout-v1',
                                        'session_id': 'session-group-1',
                                        'recipient_device_id': 'device-bob',
                                    }
                                ],
                            },
                        },
                    },
                }
            )

            stored = await fake_db.get_message('m-group-edit-2')
            assert stored is not None
            assert stored.content == 'edited team secret'
            assert stored.status == MessageStatus.EDITED
            assert stored.extra['encryption']['scheme'] == 'group-sender-key-v1'
            assert stored.extra['encryption']['local_plaintext'] == 'local:edited team secret'
            assert fake_e2ee_service.decrypt_calls
            assert any(event == message_manager_module.MessageEvent.EDITED for event, _ in fake_event_bus.events)
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_marks_missing_private_key_for_encrypted_text(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()
    fake_e2ee_service.text_decryption_state = {
        'state': 'missing_private_key',
        'can_decrypt': False,
        'reprovision_required': True,
        'local_device_id': 'device-bob',
        'target_device_id': 'device-bob',
    }

    async def failing_decrypt(content: str, extra: dict | None) -> str | None:
        raise RuntimeError('local device does not have the required private prekey')

    fake_e2ee_service.decrypt_text_content = failing_decrypt  # type: ignore[method-assign]

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(message_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('bob')
        await manager.initialize()
        try:
            message = ChatMessage(
                message_id='m-missing-key',
                session_id='session-1',
                sender_id='alice',
                content='cipher:secret',
                message_type=MessageType.TEXT,
                status=MessageStatus.RECEIVED,
                is_self=False,
                extra={
                    'encryption': {
                        'enabled': True,
                        'content_ciphertext': 'cipher:secret',
                        'sender_device_id': 'device-alice',
                        'recipient_device_id': 'device-bob',
                    },
                },
            )

            updated = await manager._decrypt_message_for_display(message)

            assert updated.content == '[Encrypted message]'
            assert updated.extra['encryption']['decryption_state'] == 'missing_private_key'
            assert updated.extra['encryption']['recovery_action'] == 'reprovision_device'
            assert updated.extra['encryption']['can_decrypt'] is False
            assert updated.extra['encryption']['local_device_id'] == 'device-bob'
            assert updated.extra['encryption']['target_device_id'] == 'device-bob'
            assert 'decryption_error' in updated.extra['encryption']
            assert any(event == message_manager_module.MessageEvent.DECRYPTION_STATE_CHANGED for event, _ in fake_event_bus.events)
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_marks_attachment_for_other_device(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()
    fake_e2ee_service.attachment_decryption_state = {
        'state': 'not_for_current_device',
        'can_decrypt': False,
        'reprovision_required': False,
        'local_device_id': 'device-laptop',
        'target_device_id': 'device-phone',
    }

    async def missing_metadata(attachment_encryption: dict | None) -> dict | None:
        return None

    fake_e2ee_service.decrypt_attachment_metadata = missing_metadata  # type: ignore[method-assign]

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(message_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('bob')
        await manager.initialize()
        try:
            message = ChatMessage(
                message_id='m-attachment-switch-device',
                session_id='session-1',
                sender_id='alice',
                content='https://cdn.example/files/blob.bin',
                message_type=MessageType.FILE,
                status=MessageStatus.RECEIVED,
                is_self=False,
                extra={
                    'attachment_encryption': {
                        'enabled': True,
                        'scheme': 'aesgcm-file+x25519-v1',
                        'sender_device_id': 'device-alice',
                        'recipient_device_id': 'device-phone',
                    },
                },
            )

            updated = await manager._hydrate_attachment_metadata_for_display(message)

            assert updated.extra['name'] == 'Encrypted attachment'
            assert updated.extra['attachment_encryption']['decryption_state'] == 'not_for_current_device'
            assert updated.extra['attachment_encryption']['recovery_action'] == 'switch_device'
            assert updated.extra['attachment_encryption']['can_decrypt'] is False
            assert updated.extra['attachment_encryption']['local_device_id'] == 'device-laptop'
            assert updated.extra['attachment_encryption']['target_device_id'] == 'device-phone'
            assert any(event == message_manager_module.MessageEvent.DECRYPTION_STATE_CHANGED for event, _ in fake_event_bus.events)
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_download_attachment_decrypts_and_caches_local_file(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()

    class FakeFileService:
        def __init__(self) -> None:
            self.download_calls: list[str] = []

        async def download_chat_attachment(self, file_url: str) -> bytes:
            self.download_calls.append(file_url)
            return b'cipher-bytes'

    fake_file_service = FakeFileService()
    fake_db.messages['m-file-1'] = ChatMessage(
        message_id='m-file-1',
        session_id='session-1',
        sender_id='bob',
        content='https://cdn.example/files/blob.bin',
        message_type=MessageType.FILE,
        status=MessageStatus.SENT,
        is_self=False,
        extra={
            'attachment_encryption': {
                'enabled': True,
                'scheme': 'aesgcm-file+x25519-v1',
            },
            'url': 'https://cdn.example/files/blob.bin',
        },
    )

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(message_manager_module, 'get_file_service', lambda: fake_file_service)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('alice')
        manager._e2ee_service = fake_e2ee_service
        local_path = ''
        try:
            local_path = await manager.download_attachment('m-file-1')

            assert fake_file_service.download_calls == ['https://cdn.example/files/blob.bin']
            assert fake_e2ee_service.decrypt_attachment_calls == [
                (
                    b'cipher-bytes',
                    {
                        'enabled': True,
                        'scheme': 'aesgcm-file+x25519-v1',
                    },
                )
            ]
            assert local_path.endswith('m-file-1_secret.pdf')
            assert Path(local_path).read_bytes() == b'plain-pdf'

            stored = await fake_db.get_message('m-file-1')
            assert stored is not None
            assert stored.extra['local_path'] == local_path
            assert stored.extra['name'] == 'secret.pdf'
            assert stored.extra['file_type'] == 'application/pdf'
        finally:
            if local_path:
                Path(local_path).unlink(missing_ok=True)

    asyncio.run(scenario())


def test_message_manager_prepare_attachment_upload_encrypts_direct_image_messages(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()
    workspace_tmp = Path('client/tests/.pytest_tmp')
    workspace_tmp.mkdir(parents=True, exist_ok=True)
    source_path = workspace_tmp / 'encrypted-image.png'
    source_path.write_bytes(b'png-data')
    fake_db.sessions['session-1'] = Session(
        session_id='session-1',
        name='Bob',
        session_type='direct',
        participant_ids=['alice', 'bob'],
        extra={'encryption_mode': 'e2ee_private'},
    )

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('alice')
        manager._e2ee_service = fake_e2ee_service
        cleanup_path = ''
        try:
            upload_path, extra, cleanup_path = await manager.prepare_attachment_upload(
                session_id='session-1',
                file_path=str(source_path),
                message_type=MessageType.IMAGE,
                fallback_name='encrypted-image.png',
                fallback_size=8,
            )

            assert upload_path == cleanup_path
            assert Path(upload_path).exists()
            assert extra['attachment_encryption']['enabled'] is True
            assert extra['attachment_encryption']['recipient_user_id'] == 'bob'
        finally:
            if cleanup_path:
                Path(cleanup_path).unlink(missing_ok=True)
            source_path.unlink(missing_ok=True)

    asyncio.run(scenario())


def test_message_manager_blocks_direct_sends_when_identity_review_is_required(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()
    fake_db.sessions['session-1'] = Session(
        session_id='session-1',
        name='Bob',
        session_type='direct',
        participant_ids=['alice', 'bob'],
        extra={
            'encryption_mode': 'e2ee_private',
            'session_crypto_state': {
                'identity_status': 'identity_changed',
                'identity_action_required': True,
                'identity_review_action': 'trust_peer_identity',
                'identity_review_blocking': True,
                'identity_alert_severity': 'critical',
            }
        },
    )

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('alice')
        manager._e2ee_service = fake_e2ee_service

        message = await manager.send_message(
            session_id='session-1',
            content='should fail',
            message_type=MessageType.TEXT,
        )

        assert message.status == MessageStatus.AWAITING_SECURITY_CONFIRMATION
        assert message.content == 'should fail'
        assert dict(message.extra.get('security_pending') or {}).get('action_id') == 'trust_peer_identity'
        assert fake_e2ee_service.encrypt_calls == []
        assert fake_conn_manager.sent_payloads == []
        sent_payloads = [
            payload
            for event, payload in fake_event_bus.events
            if event == message_manager_module.MessageEvent.SENT
        ]
        assert sent_payloads
        assert sent_payloads[0]['message'].status == MessageStatus.AWAITING_SECURITY_CONFIRMATION

    asyncio.run(scenario())


def test_message_manager_release_security_pending_messages_sends_after_confirmation(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([True])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()
    fake_db.sessions['session-1'] = Session(
        session_id='session-1',
        name='Bob',
        session_type='direct',
        participant_ids=['alice', 'bob'],
        extra={
            'encryption_mode': 'e2ee_private',
            'session_crypto_state': {
                'identity_status': 'identity_changed',
                'identity_action_required': True,
                'identity_review_action': 'trust_peer_identity',
                'identity_review_blocking': True,
                'identity_alert_severity': 'critical',
            }
        },
    )

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('alice')
        manager._e2ee_service = fake_e2ee_service
        await manager.initialize()
        try:
            message = await manager.send_message(
                session_id='session-1',
                content='hold then send',
                message_type=MessageType.TEXT,
            )

            assert message.status == MessageStatus.AWAITING_SECURITY_CONFIRMATION
            assert fake_conn_manager.sent_payloads == []

            fake_db.sessions['session-1'].extra['session_crypto_state'] = {
                'identity_status': 'verified',
                'identity_review_blocking': False,
            }
            result = await manager.release_security_pending_messages('session-1')
            await asyncio.sleep(0.05)

            assert result['released'] == 1
            assert result['failed'] == 0
            stored = await fake_db.get_message(message.message_id)
            assert stored is not None
            assert stored.status == MessageStatus.SENDING
            assert 'security_pending' not in stored.extra
            assert fake_e2ee_service.encrypt_calls == [('bob', 'hold then send')]
            assert len(fake_conn_manager.sent_payloads) == 1
            assert fake_conn_manager.sent_payloads[0]['msg_id'] == message.message_id
            assert fake_conn_manager.sent_payloads[0]['content'] == 'cipher:hold then send'
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_discard_security_pending_messages_removes_local_only_messages(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()
    fake_db.sessions['session-1'] = Session(
        session_id='session-1',
        name='Bob',
        session_type='direct',
        participant_ids=['alice', 'bob'],
        extra={
            'encryption_mode': 'e2ee_private',
            'session_crypto_state': {
                'identity_status': 'identity_changed',
                'identity_action_required': True,
                'identity_review_action': 'trust_peer_identity',
                'identity_review_blocking': True,
                'identity_alert_severity': 'critical',
            }
        },
    )

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('alice')
        manager._e2ee_service = fake_e2ee_service

        message = await manager.send_message(
            session_id='session-1',
            content='discard me',
            message_type=MessageType.TEXT,
        )

        result = await manager.discard_security_pending_messages('session-1')
        assert result['removed'] == 1
        assert result['message_ids'] == [message.message_id]
        assert await fake_db.get_message(message.message_id) is None
        deleted_payloads = [
            payload
            for event, payload in fake_event_bus.events
            if event == message_manager_module.MessageEvent.DELETED
        ]
        assert deleted_payloads
        assert deleted_payloads[-1]['message_id'] == message.message_id

    asyncio.run(scenario())


def test_message_manager_blocks_direct_attachment_encryption_when_identity_review_is_required(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()
    workspace_tmp = Path('client/tests/.pytest_tmp')
    workspace_tmp.mkdir(parents=True, exist_ok=True)
    source_path = workspace_tmp / 'identity-blocked.png'
    source_path.write_bytes(b'png-data')
    fake_db.sessions['session-1'] = Session(
        session_id='session-1',
        name='Bob',
        session_type='direct',
        participant_ids=['alice', 'bob'],
        extra={
            'encryption_mode': 'e2ee_private',
            'session_crypto_state': {
                'identity_status': 'identity_changed',
                'identity_action_required': True,
                'identity_review_action': 'trust_peer_identity',
                'identity_review_blocking': True,
                'identity_alert_severity': 'critical',
            }
        },
    )

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('alice')
        manager._e2ee_service = fake_e2ee_service

        with pytest.raises(RuntimeError) as exc_info:
            await manager.prepare_attachment_upload(
                session_id='session-1',
                file_path=str(source_path),
                message_type=MessageType.IMAGE,
                fallback_name='identity-blocked.png',
                fallback_size=8,
            )

        assert 'identity changed' in str(exc_info.value)
        assert fake_e2ee_service.group_attachment_encrypt_calls == []

    try:
        asyncio.run(scenario())
    finally:
        source_path.unlink(missing_ok=True)


def test_message_manager_prepare_attachment_upload_encrypts_group_image_messages(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()
    fake_e2ee_service.group_prekey_bundles = {
        'bob': [{'device_id': 'device-bob'}],
        'charlie': [{'device_id': 'device-charlie'}],
    }
    workspace_tmp = Path('client/tests/.pytest_tmp')
    workspace_tmp.mkdir(parents=True, exist_ok=True)
    source_path = workspace_tmp / 'group-encrypted-image.png'
    source_path.write_bytes(b'group-png-data')
    fake_db.sessions['session-group-attach-1'] = Session(
        session_id='session-group-attach-1',
        name='Team',
        session_type='group',
        participant_ids=['alice', 'bob', 'charlie'],
        extra={
            'encryption_mode': 'e2ee_group',
            'members': [
                {'id': 'alice'},
                {'id': 'bob'},
                {'id': 'charlie'},
            ],
            'group_member_version': 5,
        },
    )

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('alice')
        manager._e2ee_service = fake_e2ee_service
        cleanup_path = ''
        try:
            upload_path, extra, cleanup_path = await manager.prepare_attachment_upload(
                session_id='session-group-attach-1',
                file_path=str(source_path),
                message_type=MessageType.IMAGE,
                fallback_name='group-encrypted-image.png',
                fallback_size=14,
            )

            assert upload_path == cleanup_path
            assert Path(upload_path).exists()
            assert fake_e2ee_service.fetch_prekey_bundle_calls == ['bob', 'charlie']
            assert fake_e2ee_service.group_attachment_encrypt_calls == [
                ('session-group-attach-1', 'group-encrypted-image.png', 5, 'alice', 2, '', 14)
            ]
            assert extra['attachment_encryption']['enabled'] is True
            assert extra['attachment_encryption']['scheme'] == 'aesgcm-file+group-sender-key-v1'
            assert extra['attachment_encryption']['sender_key_id'] == 'group-key-1'
            assert len(extra['attachment_encryption']['fanout']) == 2
        finally:
            if cleanup_path:
                Path(cleanup_path).unlink(missing_ok=True)
            source_path.unlink(missing_ok=True)

    asyncio.run(scenario())


def test_message_manager_prefetches_encrypted_incoming_image_and_emits_media_ready(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()

    class FakeFileService:
        def __init__(self) -> None:
            self.download_calls: list[str] = []

        async def download_chat_attachment(self, file_url: str) -> bytes:
            self.download_calls.append(file_url)
            return b'cipher-image'

    fake_file_service = FakeFileService()

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(message_manager_module, 'get_file_service', lambda: fake_file_service)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('alice')
        manager._e2ee_service = fake_e2ee_service
        await manager.initialize()
        local_path = ''
        try:
            await manager._process_incoming_message(
                {
                    'data': {
                        'message_id': 'm-img-1',
                        'session_id': 'session-1',
                        'sender_id': 'bob',
                        'content': 'https://cdn.example/files/blob.bin',
                        'message_type': 'image',
                        'status': 'received',
                        'extra': {
                            'attachment_encryption': {
                                'enabled': True,
                                'scheme': 'aesgcm-file+x25519-v1',
                            },
                            'url': 'https://cdn.example/files/blob.bin',
                        },
                    }
                }
            )

            await _wait_until(
                lambda: any(event == message_manager_module.MessageEvent.MEDIA_READY for event, _ in fake_event_bus.events)
            )

            stored = await fake_db.get_message('m-img-1')
            assert stored is not None
            local_path = str(stored.extra.get('local_path') or '')
            assert local_path.endswith('m-img-1_secret.pdf')
            assert Path(local_path).read_bytes() == b'plain-pdf'
            assert fake_file_service.download_calls == ['https://cdn.example/files/blob.bin']
        finally:
            if local_path:
                Path(local_path).unlink(missing_ok=True)
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


def test_message_manager_normalize_loaded_message_captures_authoritative_session_metadata(monkeypatch) -> None:
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
                    'message_id': 'm-1',
                    'session_id': 'session-group-1',
                    'sender_id': 'bob',
                    'content': 'hello team',
                    'message_type': 'text',
                    'session_type': 'group',
                    'session_name': 'Core Team',
                    'session_avatar': '/uploads/team.png',
                    'participant_ids': ['alice', 'bob', 'charlie', 'alice'],
                    'is_ai_session': False,
                }
            )

            assert message.extra['session_type'] == 'group'
            assert message.extra['session_name'] == 'Core Team'
            assert message.extra['session_avatar'] == '/uploads/team.png'
            assert message.extra['participant_ids'] == ['alice', 'bob', 'charlie']
            assert message.extra['is_ai_session'] is False
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
            assert fake_event_bus.events == []

            await manager._handle_ws_message(
                {
                    'type': 'history_events',
                    'data': {
                        'events': [],
                    },
                }
            )

            assert fake_event_bus.events[-1][0] == message_manager_module.MessageEvent.SYNC_COMPLETED
            assert fake_event_bus.events[-1][1]['count'] == 0
            assert fake_event_bus.events[-1][1]['skipped'] == 1
            assert fake_event_bus.events[-1][1]['events_replayed'] == 0
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


def test_message_manager_incoming_chat_message_derives_is_self_from_sender_id(monkeypatch) -> None:
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
                    'data': {
                        'message_id': 'm-remote-self-1',
                        'session_id': 'session-1',
                        'sender_id': 'alice',
                        'content': 'hello from alice',
                        'message_type': 'text',
                        'status': 'sent',
                        'created_at': '2026-04-12T01:02:03+00:00',
                        'is_self': True,
                    },
                }
            )

            stored = await fake_db.get_message('m-remote-self-1')
            assert stored is not None
            assert stored.sender_id == 'alice'
            assert stored.is_self is False
            assert stored.timestamp is not None
            assert stored.timestamp.isoformat().startswith('2026-04-12T10:02:03')
        finally:
            await manager.close()

    asyncio.run(scenario())

def test_message_manager_remote_history_skips_payloads_without_canonical_message_id(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()

    class FakeChatService:
        async def fetch_messages(self, session_id: str, limit: int, before_seq=None) -> list[dict]:
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


def test_message_manager_remote_history_uses_batch_existing_lookup_and_delta_write(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_db.messages['m-existing'] = ChatMessage(
        message_id='m-existing',
        session_id='session-1',
        sender_id='alice',
        content='already cached',
        message_type=MessageType.TEXT,
        status=MessageStatus.SENT,
        is_self=False,
        extra={'session_seq': 1, 'read_by_user_ids': [], 'read_count': 0, 'read_target_count': 0, 'is_read_by_me': False},
    )

    async def forbidden_get_message(message_id: str):
        raise AssertionError('remote history should use batch existing-message lookup')

    fake_db.get_message = forbidden_get_message

    class FakeChatService:
        async def fetch_messages(self, session_id: str, limit: int, before_seq=None) -> list[dict]:
            return [
                {
                    'message_id': 'm-existing',
                    'session_id': session_id,
                    'sender_id': 'alice',
                    'content': 'already cached',
                    'message_type': 'text',
                    'status': 'sent',
                    'is_self': False,
                    'extra': {'session_seq': 1},
                },
                {
                    'message_id': 'm-new',
                    'session_id': session_id,
                    'sender_id': 'alice',
                    'content': 'new from remote',
                    'message_type': 'text',
                    'status': 'sent',
                    'is_self': False,
                    'extra': {'session_seq': 2},
                },
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
            remote_messages = await manager._fetch_remote_messages('session-1', limit=10)

            assert [message.message_id for message in remote_messages] == ['m-existing', 'm-new']
            assert len(fake_db.saved_batches) == 1
            assert [message.message_id for message in fake_db.saved_batches[0]] == ['m-new']
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_get_messages_uses_explicit_remote_freshness(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_db.messages['m-local-1'] = ChatMessage(
        message_id='m-local-1',
        session_id='session-1',
        sender_id='alice',
        content='local one',
    )
    fake_db.messages['m-local-2'] = ChatMessage(
        message_id='m-local-2',
        session_id='session-1',
        sender_id='alice',
        content='local two',
    )

    class FakeChatService:
        def __init__(self) -> None:
            self.fetch_calls: list[tuple[str, int, int | None]] = []

        async def fetch_messages(self, session_id: str, limit: int, before_seq=None) -> list[dict]:
            self.fetch_calls.append((session_id, limit, before_seq))
            return []

    fake_chat_service = FakeChatService()

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(message_manager_module, 'get_chat_service', lambda: fake_chat_service)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('bob')
        await manager.initialize()
        try:
            local_messages = await manager.get_messages('session-1', limit=2)
            assert [message.message_id for message in local_messages] == ['m-local-1', 'm-local-2']
            assert fake_chat_service.fetch_calls == []

            await manager.get_messages('session-1', limit=2, force_remote=True)
            await manager.get_messages('session-1', limit=2, before_seq=2)

            assert fake_chat_service.fetch_calls == [
                ('session-1', 2, None),
                ('session-1', 2, 2),
            ]
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_emits_strict_typing_state(monkeypatch) -> None:
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
                    'type': 'typing',
                    'data': {
                        'session_id': 'session-1',
                        'user_id': 'bob',
                        'typing': False,
                    },
                }
            )

            assert fake_event_bus.events[-1] == (
                message_manager_module.MessageEvent.TYPING,
                {
                    'session_id': 'session-1',
                    'user_id': 'bob',
                    'typing': False,
                },
            )
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


def test_session_manager_build_fallback_group_session_uses_authoritative_metadata(monkeypatch) -> None:
    class FakeSessionDatabase:
        is_connected = True

        async def get_app_state(self, key: str):
            if key == 'auth.user_profile':
                return json.dumps({'id': 'alice'})
            if key == 'auth.user_id':
                return 'alice'
            return None

    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: FakeEventBus())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: FakeSessionDatabase())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = await manager._build_fallback_session(
            ChatMessage(
                message_id='m-group-1',
                session_id='session-group-1',
                sender_id='bob',
                content='group hello',
                message_type=MessageType.TEXT,
                status=MessageStatus.RECEIVED,
                timestamp=datetime(2026, 3, 29, 9, 0, 0),
                extra={
                    'session_type': 'group',
                    'session_name': 'Core Team',
                    'session_avatar': '/uploads/core-team.png',
                    'participant_ids': ['alice', 'bob', 'charlie'],
                },
            )
        )

        assert session is not None
        assert session.session_type == 'group'
        assert session.name == 'Core Team'
        assert session.avatar == '/uploads/core-team.png'
        assert session.participant_ids == ['alice', 'bob', 'charlie']

    asyncio.run(scenario())


def test_session_manager_skips_fallback_session_without_authoritative_session_type(monkeypatch) -> None:
    class FakeSessionDatabase:
        is_connected = True

        async def get_app_state(self, key: str):
            if key == 'auth.user_profile':
                return json.dumps({'id': 'alice'})
            if key == 'auth.user_id':
                return 'alice'
            return None

    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: FakeEventBus())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: FakeSessionDatabase())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = await manager._build_fallback_session(
            ChatMessage(
                message_id='m-unknown-1',
                session_id='session-unknown-1',
                sender_id='bob',
                content='hello',
                message_type=MessageType.TEXT,
                status=MessageStatus.RECEIVED,
                timestamp=datetime(2026, 3, 29, 9, 5, 0),
                extra={
                    'sender_nickname': 'Bobby',
                    'sender_avatar': '/uploads/bob.png',
                },
            )
        )

        assert session is None

    asyncio.run(scenario())


def test_chat_controller_load_messages_forwards_history_cursors(monkeypatch) -> None:
    class FakeBoundaryMessageManager:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int, float | None, int | None, bool]] = []

        async def get_messages(self, session_id: str, limit: int = 50, before_timestamp=None, before_seq=None, force_remote=False):
            self.calls.append((session_id, limit, before_timestamp, before_seq, force_remote))
            return ['page']

    fake_message_manager = FakeBoundaryMessageManager()

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: object())
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: object())

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        messages = await controller.load_messages('session-1', limit=20, before_timestamp=123.45, before_seq=42)

        assert messages == ['page']
        assert fake_message_manager.calls == [('session-1', 20, 123.45, 42, False)]

    asyncio.run(scenario())


def test_message_manager_applies_user_profile_update_events(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_db.messages['m-1'] = ChatMessage(
        message_id='m-1',
        session_id='session-1',
        sender_id='alice',
        content='hello',
        status=MessageStatus.SENT,
        is_self=False,
        extra={'sender_avatar': '/uploads/old.png', 'sender_nickname': 'Alice'},
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
                    'type': 'user_profile_update',
                    'data': {
                        'session_id': 'session-1',
                        'user_id': 'alice',
                        'event_seq': 3,
                        'profile': {
                            'id': 'alice',
                            'username': 'alice',
                            'nickname': 'Alice Prime',
                            'display_name': 'Alice Prime',
                            'avatar': '/uploads/alice-new.png',
                            'gender': 'female',
                        },
                    },
                }
            )

            assert fake_db.profile_update_calls == [
                (
                    'session-1',
                    'alice',
                    {
                        'id': 'alice',
                        'username': 'alice',
                        'nickname': 'Alice Prime',
                        'display_name': 'Alice Prime',
                        'avatar': '/uploads/alice-new.png',
                        'gender': 'female',
                    },
                )
            ]
            assert fake_db.messages['m-1'].extra['sender_avatar'] == '/uploads/alice-new.png'
            assert any(event == message_manager_module.MessageEvent.PROFILE_UPDATED for event, _ in fake_event_bus.events)
            assert any(event == ContactEvent.SYNC_REQUIRED for event, _ in fake_event_bus.events)
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_applies_group_profile_update_events(monkeypatch) -> None:
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
                    'type': 'group_profile_update',
                    'data': {
                        'session_id': 'session-group-1',
                        'group_id': 'group-1',
                        'id': 'group-1',
                        'name': 'Ops',
                        'announcement': 'Ship at 18:00',
                        'avatar': '/uploads/group_avatars/ops.png',
                        'member_count': 3,
                        'members': [{'id': 'alice', 'group_nickname': 'lead'}],
                        'event_seq': 9,
                    },
                }
            )

            assert any(event == message_manager_module.MessageEvent.GROUP_UPDATED for event, _ in fake_event_bus.events)
            assert any(
                event == ContactEvent.SYNC_REQUIRED and data.get('reason') == 'group_profile_update'
                for event, data in fake_event_bus.events
            )
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_applies_group_self_profile_update_events(monkeypatch) -> None:
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
                    'type': 'group_self_profile_update',
                    'data': {
                        'session_id': 'session-group-1',
                        'group_id': 'group-1',
                        'group_note': 'only me',
                        'my_group_nickname': 'lead',
                    },
                }
            )

            assert any(event == message_manager_module.MessageEvent.GROUP_SELF_UPDATED for event, _ in fake_event_bus.events)
            assert any(
                event == ContactEvent.SYNC_REQUIRED and data.get('reason') == 'group_self_profile_update'
                for event, data in fake_event_bus.events
            )
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_recover_session_messages_retries_cached_e2ee_payloads(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()

    class FakeChatService:
        def __init__(self) -> None:
            self.fetch_calls: list[tuple[str, int, int | None]] = []

        async def fetch_messages(self, session_id: str, limit: int, before_seq=None) -> list[dict]:
            self.fetch_calls.append((session_id, limit, before_seq))
            if before_seq is None:
                return [
                    {
                        'message_id': 'm-remote-text',
                        'session_id': session_id,
                        'sender_id': 'alice',
                        'content': 'cipher:remote restored',
                        'message_type': 'text',
                        'status': 'received',
                        'timestamp': 1700000200.0,
                        'updated_at': 1700000200.0,
                        'session_seq': 2,
                        'extra': {
                            'encryption': {
                                'enabled': True,
                                'content_ciphertext': 'cipher:remote restored',
                                'sender_device_id': 'device-alice',
                                'recipient_device_id': 'device-bob',
                            },
                        },
                    }
                ]
            if before_seq == 2:
                return [
                    {
                        'message_id': 'm-remote-older',
                        'session_id': session_id,
                        'sender_id': 'alice',
                        'content': 'cipher:older restored',
                        'message_type': 'text',
                        'status': 'received',
                        'timestamp': 1699990000.0,
                        'updated_at': 1699990000.0,
                        'session_seq': 1,
                        'extra': {
                            'encryption': {
                                'enabled': True,
                                'content_ciphertext': 'cipher:older restored',
                                'sender_device_id': 'device-alice',
                                'recipient_device_id': 'device-bob',
                            },
                        },
                    }
                ]
            return []

    fake_chat_service = FakeChatService()

    async def decrypted_attachment_metadata(attachment_encryption: dict | None) -> dict | None:
        return {
            'original_name': 'secret.pdf',
            'mime_type': 'application/pdf',
            'size_bytes': 9,
        }

    fake_e2ee_service.decrypt_attachment_metadata = decrypted_attachment_metadata  # type: ignore[method-assign]

    fake_db.messages['m-recover-text'] = ChatMessage(
        message_id='m-recover-text',
        session_id='session-1',
        sender_id='alice',
        content='cipher:restored secret',
        message_type=MessageType.TEXT,
        status=MessageStatus.RECEIVED,
        is_self=False,
        extra={
            'encryption': {
                'enabled': True,
                'content_ciphertext': 'cipher:restored secret',
                'sender_device_id': 'device-alice',
                'recipient_device_id': 'device-bob',
                'decryption_state': 'missing_private_key',
                'recovery_action': 'reprovision_device',
            },
        },
    )
    fake_db.messages['m-recover-file'] = ChatMessage(
        message_id='m-recover-file',
        session_id='session-1',
        sender_id='alice',
        content='https://cdn.example/files/blob.bin',
        message_type=MessageType.FILE,
        status=MessageStatus.RECEIVED,
        is_self=False,
        extra={
            'attachment_encryption': {
                'enabled': True,
                'scheme': 'aesgcm-file+x25519-v1',
                'sender_device_id': 'device-alice',
                'recipient_device_id': 'device-bob',
                'decryption_state': 'missing_private_key',
                'recovery_action': 'reprovision_device',
            },
            'url': 'https://cdn.example/files/blob.bin',
        },
    )

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(message_manager_module, 'get_chat_service', lambda: fake_chat_service)
    monkeypatch.setattr(message_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('bob')
        await manager.initialize()
        try:
            result = await manager.recover_session_messages('session-1')

            assert result == {
                'session_id': 'session-1',
                'scanned': 2,
                'updated': 2,
                'message_ids': ['m-recover-text', 'm-recover-file', 'm-remote-text', 'm-remote-older'],
                'remote_fetched': 2,
                'remote_pages_fetched': 2,
                'recovery_stats': {
                    'cached': {
                        'text': 1,
                        'attachments': 1,
                        'direct_text': 1,
                        'group_text': 0,
                        'direct_attachments': 1,
                        'group_attachments': 0,
                        'other': 0,
                    },
                    'remote': {
                        'text': 2,
                        'attachments': 0,
                        'direct_text': 2,
                        'group_text': 0,
                        'direct_attachments': 0,
                        'group_attachments': 0,
                        'other': 0,
                    },
                },
            }
            assert fake_chat_service.fetch_calls == [('session-1', 500, None), ('session-1', 500, 2), ('session-1', 500, 1)]

            stored_text = await fake_db.get_message('m-recover-text')
            assert stored_text is not None
            assert stored_text.content == 'restored secret'
            assert stored_text.extra['encryption']['local_plaintext'] == 'local:restored secret'
            assert 'decryption_state' not in stored_text.extra['encryption']
            assert 'recovery_action' not in stored_text.extra['encryption']

            stored_file = await fake_db.get_message('m-recover-file')
            assert stored_file is not None
            assert stored_file.extra['name'] == 'secret.pdf'
            assert stored_file.extra['file_type'] == 'application/pdf'
            assert stored_file.extra['size'] == 9
            assert stored_file.extra['attachment_encryption']['local_metadata'].startswith('local:')
            assert 'decryption_state' not in stored_file.extra['attachment_encryption']
            assert 'recovery_action' not in stored_file.extra['attachment_encryption']

            stored_remote = await fake_db.get_message('m-remote-text')
            assert stored_remote is not None
            assert stored_remote.content == 'remote restored'
            assert stored_remote.extra['encryption']['local_plaintext'] == 'local:remote restored'

            stored_remote_older = await fake_db.get_message('m-remote-older')
            assert stored_remote_older is not None
            assert stored_remote_older.content == 'older restored'
            assert stored_remote_older.extra['encryption']['local_plaintext'] == 'local:older restored'

            recovered_events = [data for event, data in fake_event_bus.events if event == message_manager_module.MessageEvent.RECOVERED]
            assert len(recovered_events) == 1
            assert recovered_events[0]['count'] == 2
            assert recovered_events[0]['message_ids'] == ['m-recover-text', 'm-recover-file', 'm-remote-text', 'm-remote-older']
            assert len(recovered_events[0]['remote_messages']) == 2
            assert recovered_events[0]['recovery_stats']['cached']['direct_text'] == 1
            assert recovered_events[0]['recovery_stats']['cached']['direct_attachments'] == 1
            assert recovered_events[0]['recovery_stats']['remote']['direct_text'] == 2
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_recover_session_messages_reports_group_recovery_breakdown(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()

    class FakeChatService:
        async def fetch_messages(self, session_id: str, limit: int, before_seq=None) -> list[dict]:
            assert session_id == 'session-group-1'
            assert limit == 500
            assert before_seq is None
            return []

    fake_db.messages['m-group-recover-text'] = ChatMessage(
        message_id='m-group-recover-text',
        session_id='session-group-1',
        sender_id='alice',
        content='groupcipher:restored team secret',
        message_type=MessageType.TEXT,
        status=MessageStatus.RECEIVED,
        is_self=False,
        extra={
            'encryption': {
                'enabled': True,
                'scheme': 'group-sender-key-v1',
                'content_ciphertext': 'groupcipher:restored team secret',
                'sender_device_id': 'device-alice',
                'sender_key_id': 'group-key-1',
                'decryption_state': 'missing_group_sender_key',
            },
        },
    )
    fake_db.messages['m-group-recover-file'] = ChatMessage(
        message_id='m-group-recover-file',
        session_id='session-group-1',
        sender_id='alice',
        content='https://cdn.example/files/group-blob.bin',
        message_type=MessageType.FILE,
        status=MessageStatus.RECEIVED,
        is_self=False,
        extra={
            'attachment_encryption': {
                'enabled': True,
                'scheme': 'aesgcm-file+group-sender-key-v1',
                'sender_device_id': 'device-alice',
                'sender_key_id': 'group-key-1',
                'decryption_state': 'missing_group_sender_key',
            },
            'url': 'https://cdn.example/files/group-blob.bin',
        },
    )

    async def decrypted_group_attachment_metadata(attachment_encryption: dict | None) -> dict | None:
        normalized = dict(attachment_encryption or {})
        if str(normalized.get('scheme') or '') != 'aesgcm-file+group-sender-key-v1':
            return None
        return {
            'original_name': 'team-plan.pdf',
            'mime_type': 'application/pdf',
            'size_bytes': 21,
        }

    fake_e2ee_service.decrypt_attachment_metadata = decrypted_group_attachment_metadata  # type: ignore[method-assign]

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(message_manager_module, 'get_chat_service', lambda: FakeChatService())
    monkeypatch.setattr(message_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('bob')
        await manager.initialize()
        try:
            result = await manager.recover_session_messages('session-group-1', remote_pages=1)

            assert result['recovery_stats'] == {
                'cached': {
                    'text': 1,
                    'attachments': 1,
                    'direct_text': 0,
                    'group_text': 1,
                    'direct_attachments': 0,
                    'group_attachments': 1,
                    'other': 0,
                },
                'remote': {
                    'text': 0,
                    'attachments': 0,
                    'direct_text': 0,
                    'group_text': 0,
                    'direct_attachments': 0,
                    'group_attachments': 0,
                    'other': 0,
                },
            }

            stored_text = await fake_db.get_message('m-group-recover-text')
            assert stored_text is not None
            assert stored_text.content == 'restored team secret'

            stored_file = await fake_db.get_message('m-group-recover-file')
            assert stored_file is not None
            assert stored_file.extra['name'] == 'team-plan.pdf'
            assert stored_file.extra['attachment_encryption']['local_metadata'].startswith('local:')
        finally:
            await manager.close()

    asyncio.run(scenario())









def test_message_manager_sends_group_text_with_sender_key_encryption(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([True])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()
    fake_e2ee_service.group_prekey_bundles = {
        'bob': [{'device_id': 'device-bob', 'user_id': 'bob'}],
        'charlie': [{'device_id': 'device-charlie', 'user_id': 'charlie'}],
    }
    fake_db.sessions['session-group-1'] = Session(
        session_id='session-group-1',
        name='Ops',
        session_type='group',
        participant_ids=['alice', 'bob', 'charlie'],
        extra={
            'encryption_mode': 'e2ee_group',
            'members': [
                {'id': 'alice', 'username': 'alice'},
                {'id': 'bob', 'username': 'bob'},
                {'id': 'charlie', 'username': 'charlie'},
            ],
        },
    )

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(message_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('alice')
        manager._ack_timeout = 0.01
        await manager.initialize()
        try:
            message = await manager.send_message('session-group-1', 'group secret')
            await _wait_until(lambda: len(fake_conn_manager.sent_payloads) == 1)

            assert message.content == 'group secret'
            assert fake_e2ee_service.fetch_prekey_bundle_calls == ['bob', 'charlie']
            assert fake_e2ee_service.group_encrypt_calls and fake_e2ee_service.group_encrypt_calls[0][:2] == ('session-group-1', 'group secret')
            payload = fake_conn_manager.sent_payloads[0]
            assert payload['content'] == 'groupcipher:group secret'
            assert payload['extra']['encryption']['scheme'] == 'group-sender-key-v1'
            assert payload['extra']['encryption']['sender_key_id'] == 'group-key-1'
            assert len(payload['extra']['encryption']['fanout']) == 2
            assert 'local_plaintext' not in payload['extra']['encryption']

            stored = await fake_db.get_message(message.message_id)
            assert stored is not None
            assert stored.content == 'group secret'
            assert stored.extra['encryption']['local_plaintext'] == 'local:group secret'
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_receives_group_text_and_decrypts_sender_key_payload(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()
    fake_e2ee_service = FakeE2EEService()

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(message_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('bob')
        await manager.initialize()
        try:
            await manager._handle_ws_message(
                {
                    'type': 'chat_message',
                    'data': {
                        'message_id': 'm-group-enc-1',
                        'session_id': 'session-group-1',
                        'sender_id': 'alice',
                        'content': 'groupcipher:hello team',
                        'message_type': 'text',
                        'status': 'received',
                        'extra': {
                            'session_type': 'group',
                            'participant_ids': ['alice', 'bob', 'charlie'],
                            'encryption': {
                                'enabled': True,
                                'scheme': 'group-sender-key-v1',
                                'session_id': 'session-group-1',
                                'sender_device_id': 'device-alice',
                                'sender_key_id': 'group-key-1',
                                'content_ciphertext': 'groupcipher:hello team',
                                'nonce': 'group-nonce-1',
                                'fanout': [
                                    {
                                        'enabled': True,
                                        'scheme': 'group-sender-key-fanout-v1',
                                        'session_id': 'session-group-1',
                                        'recipient_device_id': 'device-bob',
                                    }
                                ],
                            },
                        },
                    },
                }
            )

            stored = await fake_db.get_message('m-group-enc-1')
            assert stored is not None
            assert stored.content == 'hello team'
            assert stored.extra['encryption']['scheme'] == 'group-sender-key-v1'
            assert stored.extra['encryption']['local_plaintext'] == 'local:hello team'
            assert any(event == message_manager_module.MessageEvent.RECEIVED for event, _ in fake_event_bus.events)
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_message_manager_close_clears_authenticated_user_context(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_conn_manager = FakeConnectionManager([])
    fake_db = FakeDatabase()

    class FakeChatService:
        async def fetch_messages(self, session_id: str, limit: int = 50, before_seq=None) -> list[dict]:
            return []

    class FakeFileService:
        pass

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: fake_conn_manager)
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(message_manager_module, 'get_chat_service', lambda: FakeChatService())
    monkeypatch.setattr(message_manager_module, 'get_file_service', lambda: FakeFileService())

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('alice')
        await manager.initialize()
        await manager.close()

        assert manager._user_id == ''
        assert fake_conn_manager._listeners == []

    asyncio.run(scenario())
