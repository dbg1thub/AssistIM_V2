from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
import pytest
import sys
import types
from pathlib import Path


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

    class _DummyQUrl:
        def __init__(self, value=''):
            self.value = value

        @staticmethod
        def fromLocalFile(value):
            return _DummyQUrl(value)

    class _DummyQDate:
        def __init__(self, year=2000, month=1, day=1):
            self.year = year
            self.month = month
            self.day = day

        @staticmethod
        def currentDate():
            return _DummyQDate(2026, 3, 25)

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
    qtcore.QUrl = _DummyQUrl
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

    class _DummyTheme:
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

from client.core.exceptions import APIError, ServerError
from client.core import app_icons as app_icons_module
from client.core import avatar_utils as avatar_utils_module
from client.core import i18n as i18n_module
from client.core import message_actions as message_actions_module
from client.managers import message_manager as message_manager_module
from client.managers import session_manager as session_manager_module
from client.managers import search_manager as search_manager_module
from client.managers import sound_manager as sound_manager_module
from client.core import profile_fields as profile_fields_module
from client.models.message import ChatMessage, MessageStatus, MessageType, Session, build_remote_attachment_extra
from client.services import file_service as file_service_module
from client.storage import database as database_module
from client.ui.controllers import auth_controller as auth_controller_module
from client.ui.controllers import chat_controller as chat_controller_module
from client.ui.controllers import contact_controller as contact_controller_module
from client.ui.controllers import discovery_controller as discovery_controller_module


class FakeMessageManager:
    def __init__(self) -> None:
        self.user_ids: list[str] = []
        self.failed: list[tuple[str, str]] = []
        self.sent_messages: list[ChatMessage] = []
        self.cached_messages_calls: list[tuple[str, int, object]] = []
        self.attachment_upload_preparations: list[tuple[str, str, MessageType, str, int]] = []
        self.download_attachment_calls: list[str] = []
        self.recover_session_messages_calls: list[str] = []
        self.recover_session_messages_result: dict[str, object] = {
            'session_id': 'session-1',
            'scanned': 0,
            'updated': 0,
            'message_ids': [],
            'remote_fetched': 0,
            'remote_pages_fetched': 0,
            'recovery_stats': {
                'cached': {
                    'text': 0,
                    'attachments': 0,
                    'direct_text': 0,
                    'group_text': 0,
                    'direct_attachments': 0,
                    'group_attachments': 0,
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
            },
        }

    def set_user_id(self, user_id: str) -> None:
        self.user_ids.append(user_id)

    async def create_local_message(self, session_id: str, content: str, message_type=MessageType.TEXT, msg_id=None, extra=None):
        return ChatMessage(
            message_id='local-1',
            session_id=session_id,
            sender_id='alice',
            content=content,
            message_type=message_type,
            status=MessageStatus.SENDING,
            is_self=True,
            extra=dict(extra or {}),
        )

    async def send_message(self, session_id: str, content: str, message_type=MessageType.TEXT, msg_id=None, extra=None, existing_message=None):
        message = existing_message or ChatMessage(
            message_id='sent-1',
            session_id=session_id,
            sender_id='alice',
            content=content,
            message_type=message_type,
            status=MessageStatus.SENT,
            is_self=True,
            extra=dict(extra or {}),
        )
        message.content = content
        message.message_type = message_type
        message.extra.update(dict(extra or {}))
        self.sent_messages.append(message)
        return message

    async def mark_message_failed(self, message: ChatMessage, reason: str = 'Send failed') -> None:
        self.failed.append((message.message_id, reason))

    async def get_cached_messages(self, session_id: str, limit: int = 50, before_timestamp=None) -> list[ChatMessage]:
        self.cached_messages_calls.append((session_id, limit, before_timestamp))
        return [
            ChatMessage(
                message_id='cached-1',
                session_id=session_id,
                sender_id='alice',
                content='cached hello',
                message_type=MessageType.TEXT,
                status=MessageStatus.SENT,
                is_self=True,
            )
        ]

    async def prepare_attachment_upload(
        self,
        *,
        session_id: str,
        file_path: str,
        message_type: MessageType,
        fallback_name: str,
        fallback_size: int,
    ):
        self.attachment_upload_preparations.append(
            (session_id, file_path, message_type, fallback_name, fallback_size)
        )
        return file_path, {}, None

    async def download_attachment(self, message_id: str) -> str:
        self.download_attachment_calls.append(message_id)
        return f'D:/downloads/{message_id}.bin'

    async def recover_session_messages(self, session_id: str, *, limit: int = 500) -> dict:
        self.recover_session_messages_calls.append(session_id)
        payload = dict(self.recover_session_messages_result)
        payload.setdefault('session_id', session_id)
        return payload


class FakeSessionManager:
    def __init__(self) -> None:
        self.current_session_id = 'session-1'
        self.added: list[tuple[str, ChatMessage]] = []
        self.sessions = []
        self.current_session = None
        self.recover_calls: list[str] = []
        self.recover_result: dict[str, object] = {'performed': True, 'session_id': 'session-1'}
        self.trust_calls: list[str] = []
        self.trust_result: dict[str, object] = {'performed': True, 'session_id': 'session-1'}
        self.security_summary_calls: list[str] = []
        self.security_summary_result: dict[str, object] = {'session_id': 'session-1', 'headline': 'secure'}
        self.identity_verification_calls: list[str] = []
        self.identity_verification_result: dict[str, object] = {'session_id': 'session-1', 'available': False, 'verification': {}}
        self.identity_review_details_calls: list[str] = []
        self.identity_review_details_result: dict[str, object] = {'session_id': 'session-1', 'available': False, 'timeline': []}
        self.security_diagnostics_calls: list[str] = []
        self.security_diagnostics_result: dict[str, object] = {'session_id': 'session-1', 'headline': 'secure'}
        self.security_action_calls: list[tuple[str, str]] = []
        self.security_action_result: dict[str, object] = {'performed': True, 'session_id': 'session-1', 'action_id': 'trust_peer_identity'}

    async def add_message_to_session(self, session_id: str, message: ChatMessage) -> None:
        self.added.append((session_id, message))

    def find_direct_session(self, user_id: str):
        return None

    async def ensure_remote_session(self, session_id: str, *, fallback_name: str = 'Session', avatar: str = ''):
        return None

    async def ensure_direct_session(self, user_id: str, *, display_name: str = '', avatar: str = ''):
        return None

    async def refresh_session_preview(self, session_id: str) -> None:
        return None

    async def recover_session_crypto(self, session_id: str) -> dict:
        self.recover_calls.append(session_id)
        return dict(self.recover_result)

    async def trust_session_identities(self, session_id: str) -> dict:
        self.trust_calls.append(session_id)
        return dict(self.trust_result)

    async def get_session_security_summary(self, session_id: str) -> dict:
        self.security_summary_calls.append(session_id)
        payload = dict(self.security_summary_result)
        payload.setdefault('session_id', session_id)
        return payload

    async def get_current_session_security_summary(self) -> dict:
        payload = dict(self.security_summary_result)
        payload.setdefault('session_id', self.current_session_id)
        return payload

    async def get_session_identity_verification(self, session_id: str) -> dict:
        self.identity_verification_calls.append(session_id)
        payload = dict(self.identity_verification_result)
        payload.setdefault('session_id', session_id)
        return payload

    async def get_current_session_identity_verification(self) -> dict:
        payload = dict(self.identity_verification_result)
        payload.setdefault('session_id', self.current_session_id)
        self.identity_verification_calls.append(self.current_session_id)
        return payload

    async def get_session_identity_review_details(self, session_id: str) -> dict:
        self.identity_review_details_calls.append(session_id)
        payload = dict(self.identity_review_details_result)
        payload.setdefault('session_id', session_id)
        return payload

    async def get_current_session_identity_review_details(self) -> dict:
        payload = dict(self.identity_review_details_result)
        payload.setdefault('session_id', self.current_session_id)
        self.identity_review_details_calls.append(self.current_session_id)
        return payload

    async def get_session_security_diagnostics(self, session_id: str) -> dict:
        self.security_diagnostics_calls.append(session_id)
        payload = dict(self.security_diagnostics_result)
        payload.setdefault('session_id', session_id)
        return payload

    async def get_current_session_security_diagnostics(self) -> dict:
        payload = dict(self.security_diagnostics_result)
        payload.setdefault('session_id', self.current_session_id)
        self.security_diagnostics_calls.append(self.current_session_id)
        return payload

    async def execute_session_security_action(self, session_id: str, action_id: str) -> dict:
        self.security_action_calls.append((session_id, action_id))
        payload = dict(self.security_action_result)
        payload.setdefault('session_id', session_id)
        payload.setdefault('action_id', action_id)
        return payload

    async def execute_current_session_security_action(self, action_id: str) -> dict:
        payload = dict(self.security_action_result)
        payload.setdefault('session_id', self.current_session_id)
        payload.setdefault('action_id', action_id)
        self.security_action_calls.append((self.current_session_id, action_id))
        return payload

    def get_total_unread_count(self) -> int:
        return 0


class FakeFileService:
    def __init__(self, result: dict | None = None) -> None:
        self.result = dict(result or {})
        self.chat_uploads: list[str] = []
        self.chat_downloads: list[str] = []
        self.avatar_uploads: list[str] = []
        self.avatar_resets = 0

    async def upload_chat_attachment(self, file_path: str) -> dict:
        self.chat_uploads.append(file_path)
        return dict(self.result)

    async def download_chat_attachment(self, file_url: str) -> bytes:
        self.chat_downloads.append(file_url)
        return b''

    async def upload_profile_avatar(self, file_path: str) -> dict:
        self.avatar_uploads.append(file_path)
        return dict(self.result)

    async def reset_profile_avatar(self) -> dict:
        self.avatar_resets += 1
        return dict(self.result)


class FakeAuthService:
    def __init__(self) -> None:
        self.login_calls: list[tuple[str, str, bool]] = []
        self.register_calls: list[tuple[str, str, str]] = []
        self.logout_calls = 0
        self.listeners = []
        self.access_token = None
        self.refresh_token = None
        self.current_user_payload = {
            'id': 'user-1',
            'username': 'alice',
            'nickname': 'Alice',
        }
        self.login_payload = {
            'access_token': 'access-token',
            'refresh_token': 'refresh-token',
            'user': dict(self.current_user_payload),
        }

    def add_token_listener(self, listener) -> None:
        self.listeners.append(listener)

    def remove_token_listener(self, listener) -> None:
        if listener in self.listeners:
            self.listeners.remove(listener)

    def set_tokens(self, access_token: str, refresh_token: str) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token

    def clear_tokens(self) -> None:
        self.access_token = None
        self.refresh_token = None

    async def fetch_current_user(self) -> dict:
        return dict(self.current_user_payload)

    async def login(self, username: str, password: str, *, force: bool = False) -> dict:
        self.login_calls.append((username, password, force))
        return dict(self.login_payload)

    async def register(self, username: str, nickname: str, password: str) -> dict:
        self.register_calls.append((username, nickname, password))
        return dict(self.login_payload)

    async def logout(self) -> None:
        self.logout_calls += 1


class FakeUserService:
    def __init__(self) -> None:
        self.update_calls: list[dict] = []
        self.search_calls: list[tuple[str, int, int]] = []
        self.fetch_user_calls: list[str] = []
        self.search_payload: dict = {'items': []}
        self.user_payloads: dict[str, dict] = {}

    async def update_me(self, payload: dict) -> dict:
        self.update_calls.append(dict(payload))
        return {
            'id': 'user-1',
            'username': 'alice',
            'nickname': payload.get('nickname', 'alice'),
            'avatar': payload.get('avatar', ''),
            **dict(payload),
        }

    async def search_users(self, keyword: str, *, page: int = 1, size: int = 20) -> dict:
        self.search_calls.append((keyword, page, size))
        return dict(self.search_payload)

    async def fetch_user(self, user_id: str) -> dict:
        self.fetch_user_calls.append(user_id)
        return dict(self.user_payloads.get(user_id, {}))


class FakeDatabase:
    def __init__(self) -> None:
        self.app_state: dict[str, object] = {}
        self.is_connected = False
        self.replaced_contacts: list[list[dict]] = []
        self.replaced_groups: list[list[dict]] = []
        self.db_encryption_self_check: dict[str, object] = {
            'state': 'plain',
            'severity': 'info',
            'can_start': True,
            'action_required': False,
            'message': 'Local database encryption is disabled',
        }

    async def set_app_state(self, key: str, value) -> None:
        await self.set_app_states({key: value})

    async def set_app_states(self, values: dict[str, object]) -> None:
        self.app_state.update(dict(values))

    async def get_app_state(self, key: str):
        return self.app_state.get(key)

    async def delete_app_state(self, key: str) -> None:
        await self.delete_app_states([key])

    async def delete_app_states(self, keys) -> None:
        for key in keys:
            self.app_state.pop(key, None)

    async def clear_chat_state(self) -> None:
        return None

    async def replace_contacts_cache(self, contacts: list[dict], *, owner_user_id: str | None = None) -> None:
        self.replaced_contacts.append([dict(item) for item in contacts])

    async def replace_groups_cache(self, groups: list[dict], *, owner_user_id: str | None = None) -> None:
        self.replaced_groups.append([dict(item) for item in groups])

    def get_db_encryption_self_check(self) -> dict[str, object]:
        return dict(self.db_encryption_self_check)


class FakeChatControllerContext:
    def __init__(self) -> None:
        self.user_ids: list[str] = []
        self.refresh_calls = 0
        self.refresh_result = session_manager_module.SessionRefreshResult(
            sessions=[],
            authoritative=True,
            unread_synchronized=True,
        )
        self.refresh_exception: Exception | None = None
        self.recover_calls: list[str] = []
        self.recover_current_calls = 0
        self.recover_result: dict[str, object] = {'performed': True, 'session_id': 'session-1'}
        self.identity_verification_calls: list[str] = []
        self.identity_verification_current_calls = 0
        self.identity_verification_result: dict[str, object] = {
            'session_id': 'session-1',
            'available': False,
            'verification': {},
        }
        self.identity_review_details_calls: list[str] = []
        self.identity_review_details_current_calls = 0
        self.identity_review_details_result: dict[str, object] = {
            'session_id': 'session-1',
            'available': False,
            'timeline': [],
        }
        self.security_diagnostics_calls: list[str] = []
        self.security_diagnostics_current_calls = 0
        self.security_diagnostics_result: dict[str, object] = {
            'session_id': 'session-1',
            'headline': 'secure',
        }
        self.raise_current_security_diagnostics = False
        self.security_action_calls: list[tuple[str, str]] = []
        self.security_action_current_calls: list[str] = []
        self.security_action_result: dict[str, object] = {
            'performed': True,
            'session_id': 'session-1',
            'action_id': 'trust_peer_identity',
        }

    def set_user_id(self, user_id: str) -> None:
        self.user_ids.append(user_id)

    async def refresh_sessions_snapshot(self) -> session_manager_module.SessionRefreshResult:
        self.refresh_calls += 1
        if self.refresh_exception is not None:
            raise self.refresh_exception
        return self.refresh_result

    async def recover_session_crypto(self, session_id: str) -> dict:
        self.recover_calls.append(session_id)
        payload = dict(self.recover_result)
        payload.setdefault('session_id', session_id)
        return payload

    async def recover_current_session_crypto(self) -> dict:
        self.recover_current_calls += 1
        return dict(self.recover_result)

    async def get_session_identity_verification(self, session_id: str) -> dict:
        self.identity_verification_calls.append(session_id)
        payload = dict(self.identity_verification_result)
        payload.setdefault('session_id', session_id)
        return payload

    async def get_current_session_identity_verification(self) -> dict:
        self.identity_verification_current_calls += 1
        return dict(self.identity_verification_result)

    async def get_session_identity_review_details(self, session_id: str) -> dict:
        self.identity_review_details_calls.append(session_id)
        payload = dict(self.identity_review_details_result)
        payload.setdefault('session_id', session_id)
        return payload

    async def get_current_session_identity_review_details(self) -> dict:
        self.identity_review_details_current_calls += 1
        return dict(self.identity_review_details_result)

    async def get_session_security_diagnostics(self, session_id: str) -> dict:
        self.security_diagnostics_calls.append(session_id)
        payload = dict(self.security_diagnostics_result)
        payload.setdefault('session_id', session_id)
        return payload

    async def get_current_session_security_diagnostics(self) -> dict:
        if self.raise_current_security_diagnostics:
            raise RuntimeError('no current session selected')
        self.security_diagnostics_current_calls += 1
        return dict(self.security_diagnostics_result)

    async def execute_session_security_action(self, session_id: str, action_id: str) -> dict:
        self.security_action_calls.append((session_id, action_id))
        payload = dict(self.security_action_result)
        payload.setdefault('session_id', session_id)
        payload.setdefault('action_id', action_id)
        return payload

    async def execute_current_session_security_action(self, action_id: str) -> dict:
        self.security_action_current_calls.append(action_id)
        payload = dict(self.security_action_result)
        payload.setdefault('session_id', 'session-1')
        payload.setdefault('action_id', action_id)
        return payload
class FakeAuthContext:
    def __init__(self, user: dict | None = None) -> None:
        self.current_user = dict(user or {'id': 'user-1', 'username': 'alice', 'nickname': 'Alice', 'avatar': ''})


class FakeContactService:
    def __init__(self) -> None:
        self.fetch_friends_calls = 0
        self.fetch_groups_calls = 0
        self.fetch_friend_requests_calls = 0
        self.fetch_group_calls: list[str] = []
        self.send_friend_request_calls: list[tuple[str, str]] = []
        self.create_group_calls: list[tuple[str, list[str]]] = []
        self.update_group_profile_calls: list[tuple[str, str | None, str | None]] = []
        self.update_my_group_profile_calls: list[tuple[str, str | None, str | None]] = []
        self.leave_group_calls: list[str] = []
        self.add_group_member_calls: list[tuple[str, str, str]] = []
        self.remove_group_member_calls: list[tuple[str, str]] = []
        self.update_group_member_role_calls: list[tuple[str, str, str]] = []
        self.transfer_group_ownership_calls: list[tuple[str, str]] = []
        self.accept_calls: list[str] = []
        self.reject_calls: list[str] = []
        self.remove_calls: list[str] = []
        self.friends_payload: list[dict] = []
        self.groups_payload: list[dict] = []
        self.requests_payload: list[dict] = []
        self.group_members: list[dict] = [
            {'id': 'user-1', 'username': 'alice', 'nickname': 'Alice', 'role': 'owner'},
            {'id': 'user-2', 'username': 'bob', 'nickname': 'Bob', 'role': 'member'},
        ]
        self.group_name = 'Core Team'
        self.group_announcement = ''
        self.group_note = ''
        self.group_my_nickname = ''

    def _group_payload(self, group_id: str = 'group-1') -> dict:
        return {
            'id': group_id,
            'name': self.group_name,
            'announcement': self.group_announcement,
            'note': self.group_note,
            'my_group_nickname': self.group_my_nickname,
            'session_id': 'session-group-1',
            'owner_id': next(
                (str(member.get('id', '') or '').strip() for member in self.group_members if str(member.get('role', '') or '').strip() == 'owner'),
                'user-1',
            ),
            'members': [dict(member) for member in self.group_members],
        }

    async def fetch_friends(self) -> list[dict]:
        self.fetch_friends_calls += 1
        return [dict(item) for item in self.friends_payload]

    async def fetch_groups(self) -> list[dict]:
        self.fetch_groups_calls += 1
        return [dict(item) for item in self.groups_payload]

    async def fetch_group(self, group_id: str) -> dict:
        self.fetch_group_calls.append(group_id)
        return self._group_payload(group_id)

    async def fetch_friend_requests(self) -> list[dict]:
        self.fetch_friend_requests_calls += 1
        return [dict(item) for item in self.requests_payload]

    async def send_friend_request(self, user_id: str, message: str = '') -> dict:
        self.send_friend_request_calls.append((user_id, message))
        return {'status': 'pending'}

    async def create_group(self, name: str, member_ids: list[str]) -> dict:
        self.create_group_calls.append((name, list(member_ids)))
        self.group_name = name
        self.group_members = [{'id': 'user-1', 'username': 'alice', 'nickname': 'Alice', 'role': 'owner'}] + [
            {'id': item, 'username': item, 'nickname': item.title(), 'role': 'member'}
            for item in member_ids
        ]
        return {'group': self._group_payload('group-1'), 'mutation': {'action': 'created', 'changed': True}}

    async def update_group_profile(self, group_id: str, *, name: str | None = None, announcement: str | None = None) -> dict:
        self.update_group_profile_calls.append((group_id, name, announcement))
        if name is not None:
            self.group_name = name
        if announcement is not None:
            self.group_announcement = announcement
        return {
            'group': self._group_payload(group_id),
            'mutation': {
                'action': 'profile_updated',
                'changed': True,
                'announcement': {
                    'message_id': 'announcement-message-1' if announcement else None,
                    'created': bool(announcement),
                    'participant_count': len(self.group_members),
                },
            },
        }

    async def update_my_group_profile(self, group_id: str, *, note: str | None = None, my_group_nickname: str | None = None) -> dict:
        self.update_my_group_profile_calls.append((group_id, note, my_group_nickname))
        if note is not None:
            self.group_note = note
        if my_group_nickname is not None:
            self.group_my_nickname = my_group_nickname
        return {
            'group_id': group_id,
            'session_id': 'session-group-1',
            'group_note': self.group_note,
            'my_group_nickname': self.group_my_nickname,
            'changed': True,
        }

    async def leave_group(self, group_id: str) -> dict:
        self.leave_group_calls.append(group_id)
        return {'group': None, 'mutation': {'action': 'left', 'changed': True, 'group_id': group_id}}

    async def add_group_member(self, group_id: str, user_id: str, *, role: str = 'member') -> dict:
        self.add_group_member_calls.append((group_id, user_id, role))
        if not any(str(member.get('id', '') or '').strip() == user_id for member in self.group_members):
            self.group_members.append({'id': user_id, 'username': user_id, 'nickname': user_id.title(), 'role': role})
        return {'group': self._group_payload(group_id), 'mutation': {'action': 'member_added', 'changed': True, 'target_user_id': user_id}}

    async def remove_group_member(self, group_id: str, user_id: str) -> dict:
        self.remove_group_member_calls.append((group_id, user_id))
        self.group_members = [member for member in self.group_members if str(member.get('id', '') or '').strip() != user_id]
        return {'group': self._group_payload(group_id), 'mutation': {'action': 'member_removed', 'changed': True, 'target_user_id': user_id}}

    async def update_group_member_role(self, group_id: str, user_id: str, *, role: str) -> dict:
        self.update_group_member_role_calls.append((group_id, user_id, role))
        for member in self.group_members:
            if str(member.get('id', '') or '').strip() == user_id:
                member['role'] = role
                break
        return {'group': self._group_payload(group_id), 'mutation': {'action': 'member_role_updated', 'changed': True, 'target_user_id': user_id}}

    async def transfer_group_ownership(self, group_id: str, new_owner_id: str) -> dict:
        self.transfer_group_ownership_calls.append((group_id, new_owner_id))
        for member in self.group_members:
            member_id = str(member.get('id', '') or '').strip()
            if member_id == new_owner_id:
                member['role'] = 'owner'
            elif str(member.get('role', '') or '').strip() == 'owner':
                member['role'] = 'member'
        return {'group': self._group_payload(group_id), 'mutation': {'action': 'ownership_transferred', 'changed': True, 'new_owner_id': new_owner_id}}

    async def accept_friend_request(self, request_id: str) -> dict:
        self.accept_calls.append(request_id)
        return {'status': 'accepted'}

    async def reject_friend_request(self, request_id: str) -> dict:
        self.reject_calls.append(request_id)
        return {'status': 'rejected'}

    async def remove_friend(self, friend_id: str) -> None:
        self.remove_calls.append(friend_id)


class FakeDiscoveryService:
    def __init__(self) -> None:
        self.fetch_moments_calls: list[str | None] = []
        self.create_moment_calls: list[str] = []
        self.like_calls: list[str] = []
        self.unlike_calls: list[str] = []
        self.comment_calls: list[tuple[str, str]] = []
        self.moments_payload: list[dict] = []
        self.created_moment_payload: dict = {}
        self.comment_payload: dict = {}

    async def fetch_moments(self, *, user_id: str | None = None) -> list[dict]:
        self.fetch_moments_calls.append(user_id)
        return [dict(item) for item in self.moments_payload]

    async def create_moment(self, content: str) -> dict:
        self.create_moment_calls.append(content)
        return dict(self.created_moment_payload or {'id': 'moment-created', 'content': content})

    async def like_moment(self, moment_id: str) -> None:
        self.like_calls.append(moment_id)

    async def unlike_moment(self, moment_id: str) -> None:
        self.unlike_calls.append(moment_id)

    async def add_comment(self, moment_id: str, content: str) -> dict:
        self.comment_calls.append((moment_id, content))
        return dict(self.comment_payload or {'id': 'comment-1', 'moment_id': moment_id, 'content': content})


class FakeSearchDatabase:
    def __init__(
        self,
        messages: list[ChatMessage],
        contacts: list[dict] | None = None,
        groups: list[dict] | None = None,
    ) -> None:
        self.messages = list(messages)
        self.contacts = [dict(item) for item in (contacts or [])]
        self.groups = [dict(item) for item in (groups or [])]
        self.search_calls: list[tuple[str, str | None, int]] = []
        self.search_contact_calls: list[tuple[str, int]] = []
        self.search_group_calls: list[tuple[str, int]] = []

    async def search_messages(self, keyword: str, session_id: str | None = None, limit: int = 100) -> list[ChatMessage]:
        self.search_calls.append((keyword, session_id, limit))
        return list(self.messages)

    async def search_contacts(self, keyword: str, limit: int = 20) -> list[dict]:
        self.search_contact_calls.append((keyword, limit))
        return [dict(item) for item in self.contacts]

    async def search_groups(self, keyword: str, limit: int = 20) -> list[dict]:
        self.search_group_calls.append((keyword, limit))
        return [dict(item) for item in self.groups]

    async def execute(self, *_args, **_kwargs):
        raise AssertionError('SearchManager should not execute raw SQL directly')

    def _row_to_message(self, *_args, **_kwargs):
        raise AssertionError('SearchManager should not use Database private row helpers')


class FakeSearchCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = list(rows)

    async def fetchall(self) -> list[dict]:
        return list(self._rows)


class FakeSearchConnection:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = list(rows)
        self.execute_calls: list[tuple[str, tuple]] = []

    async def execute(self, sql: str, params: tuple):
        self.execute_calls.append((sql, params))
        return FakeSearchCursor(self.rows)


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def subscribe(self, *_args, **_kwargs) -> None:
        return None

    async def unsubscribe(self, *_args, **_kwargs) -> None:
        return None

    async def emit(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, dict(payload)))


class FakeSessionStateDatabase:
    is_connected = False


class FakeSessionUnreadDatabase:
    def __init__(self) -> None:
        self.is_connected = True
        self.updated_unread: list[tuple[str, int]] = []

    async def update_session_unread(self, session_id: str, unread_count: int) -> None:
        self.updated_unread.append((session_id, unread_count))


class FakeSessionProfileDatabase:
    def __init__(self) -> None:
        self.is_connected = True
        self.replaced_sessions = []
        self.saved_sessions = []
        self.app_state = {
            'auth.user_profile': json.dumps(
                {
                    'id': 'user-1',
                    'username': 'alice',
                    'nickname': 'Alice',
                    'avatar': '/uploads/alice.svg',
                    'gender': 'female',
                },
                ensure_ascii=False,
            ),
            'auth.user_id': 'user-1',
        }

    async def get_app_state(self, key: str):
        return self.app_state.get(key)

    async def replace_sessions(self, sessions):
        self.replaced_sessions = list(sessions)

    async def save_session(self, session) -> None:
        self.saved_sessions.append(session)


class FakeE2EEService:
    def __init__(
        self,
        summary: dict | None = None,
        reprovision_response: dict | None = None,
        peer_identity_summary: dict | None = None,
    ) -> None:
        self.summary = dict(summary or {})
        self.calls = 0
        self.reprovision_calls = 0
        self.peer_identity_calls: list[str] = []
        self.trust_peer_identity_calls: list[str] = []
        self.reconcile_group_session_state_calls: list[tuple[str, int, list[str]]] = []
        self.peer_identity_summary = dict(
            peer_identity_summary
            or {
                'local_device_id': 'device-local-1',
                'local_fingerprint': '',
                'local_fingerprint_short': '',
                'status': 'unavailable',
                'device_count': 0,
                'trusted_device_count': 0,
                'unverified_device_count': 0,
                'changed_device_count': 0,
                'unverified_device_ids': [],
                'changed_device_ids': [],
                'change_count': 0,
                'last_changed_at': '',
                'last_trusted_at': '',
                'verification_available': False,
                'primary_verification_device_id': '',
                'primary_verification_fingerprint': '',
                'primary_verification_fingerprint_short': '',
                'primary_verification_code': '',
                'primary_verification_code_short': '',
                'checked_at': '',
            }
        )
        self.group_session_summary = {
            'session_id': 'session-1',
            'has_local_sender_key': False,
            'local_sender_key_id': '',
            'member_version': 42,
            'retired_local_sender_key_ids': [],
            'inbound_sender_devices': [],
        }
        self.reprovision_response = dict(reprovision_response or {'device_id': 'device-reprovisioned-1'})

    async def get_local_device_summary(self) -> dict:
        self.calls += 1
        return dict(self.summary)

    async def get_peer_identity_summary(self, user_id: str) -> dict:
        self.peer_identity_calls.append(user_id)
        return {'user_id': user_id, **dict(self.peer_identity_summary)}

    async def trust_peer_identities(self, user_id: str, *, device_ids: list[str] | None = None) -> dict:
        self.trust_peer_identity_calls.append(user_id)
        trusted_summary = dict(self.peer_identity_summary)
        trusted_summary.update(
            {
                'status': 'verified',
                'trusted_device_count': int(trusted_summary.get('device_count', 0) or 0),
                'unverified_device_count': 0,
                'changed_device_count': 0,
                'unverified_device_ids': [],
                'changed_device_ids': [],
                'last_trusted_at': trusted_summary.get('checked_at') or '2026-04-06T12:30:00+00:00',
                'trusted_now_device_ids': list(device_ids or []),
                'checked_at': trusted_summary.get('checked_at') or '2026-04-06T12:30:00+00:00',
            }
        )
        self.peer_identity_summary = trusted_summary
        return {'user_id': user_id, **trusted_summary}

    async def reprovision_local_device(self) -> dict:
        self.reprovision_calls += 1
        device_id = str(self.reprovision_response.get('device_id') or 'device-reprovisioned-1')
        self.summary = {'device_id': device_id, 'has_local_bundle': True}
        return dict(self.reprovision_response)

    async def reconcile_group_session_state(
        self,
        session_id: str,
        *,
        member_version: int = 0,
        member_user_ids: list[str] | None = None,
    ) -> dict:
        self.reconcile_group_session_state_calls.append(
            (session_id, int(member_version or 0), list(member_user_ids or []))
        )
        return {
            **dict(self.group_session_summary),
            'session_id': session_id,
            'member_version': int(member_version or 0),
            'changed': False,
            'local_sender_key_cleared': False,
            'pruned_inbound_sender_devices': [],
        }


class FakeSessionService:
    def __init__(self) -> None:
        self.fetch_session_calls: list[str] = []
        self.fetch_sessions_calls = 0
        self.fetch_unread_counts_calls = 0
        self.create_direct_session_calls: list[tuple[str, str]] = []
        self.fetch_sessions_error: Exception | None = None
        self.fetch_unread_counts_error: Exception | None = None
        self.session_payload = {
            'id': 'session-1',
            'name': 'Core Team',
            'session_type': 'group',
            'group_id': 'group-1',
            'participant_ids': ['alice', 'bob'],
            'avatar': 'https://cdn.example/groups/core.png',
            'group_member_version': 42,
        }
        self.unread_payload = [
            {'session_id': 'session-1', 'unread': 4},
        ]
        self.direct_session_payload = {
            'id': 'session-direct-1',
            'name': 'Bob',
            'session_type': 'direct',
            'participant_ids': ['alice', 'bob'],
        }

    async def fetch_session(self, session_id: str) -> dict:
        self.fetch_session_calls.append(session_id)
        return dict(self.session_payload)

    async def fetch_sessions(self) -> list[dict]:
        self.fetch_sessions_calls += 1
        if self.fetch_sessions_error is not None:
            raise self.fetch_sessions_error
        return [dict(self.session_payload)]

    async def fetch_unread_counts(self) -> list[dict]:
        self.fetch_unread_counts_calls += 1
        if self.fetch_unread_counts_error is not None:
            raise self.fetch_unread_counts_error
        return [dict(item) for item in self.unread_payload]

    async def create_direct_session(self, user_id: str) -> dict:
        self.create_direct_session_calls.append(user_id)
        return dict(self.direct_session_payload)

class FakeMessageStoreDatabase:
    def __init__(self, messages: list[ChatMessage], session_payload: dict | None = None) -> None:
        self.is_connected = True
        self.messages = list(messages)
        self.session_payload = dict(session_payload or {})
        self.saved_batches: list[list[ChatMessage]] = []
        self.app_state = {
            'auth.user_profile': json.dumps(
                {
                    'id': 'user-1',
                    'username': 'alice',
                    'nickname': 'Alice',
                    'avatar': '/uploads/alice.svg',
                    'gender': 'female',
                },
                ensure_ascii=False,
            ),
            'auth.user_id': 'user-1',
        }

    async def get_messages(self, session_id: str, limit: int = 50, before_timestamp=None) -> list[ChatMessage]:
        return [message for message in self.messages if message.session_id == session_id][:limit]

    async def get_message(self, message_id: str):
        for message in self.messages:
            if message.message_id == message_id:
                return message
        return None

    async def get_messages_by_ids(self, message_ids: list[str]):
        return {
            message.message_id: message
            for message in self.messages
            if message.message_id in set(message_ids)
        }

    async def save_messages_batch(self, messages: list[ChatMessage]) -> None:
        self.saved_batches.append([message for message in messages])

    async def get_app_state(self, key: str):
        return self.app_state.get(key)

    async def get_session(self, session_id: str):
        if not self.session_payload or self.session_payload.get('session_id') != session_id:
            return None

        from client.models.message import Session

        session = Session.from_dict(self.session_payload)
        session.extra = dict(self.session_payload.get('extra') or {})
        return session


class FakeConnectionManager:
    def add_message_listener(self, _listener) -> None:
        return None

    def remove_message_listener(self, _listener) -> None:
        return None


class FakeChatService:
    def __init__(self) -> None:
        self.fetch_messages_calls: list[tuple[str, int, object]] = []

    async def fetch_messages(self, session_id: str, limit: int, before_seq=None) -> list[dict]:
        self.fetch_messages_calls.append((session_id, limit, before_seq))
        return []


class FakeCallService:
    def __init__(self, payload: list[dict] | None = None, *, error: Exception | None = None) -> None:
        self.payload = [dict(item) for item in list(payload or [])]
        self.error = error
        self.fetch_calls = 0

    async def fetch_ice_servers(self) -> list[dict]:
        self.fetch_calls += 1
        if self.error is not None:
            raise self.error
        return [dict(item) for item in self.payload]


class FakeNoopFileService:
    pass


def test_chat_controller_refresh_call_ice_servers_uses_backend_service(monkeypatch) -> None:
    fake_call_service = FakeCallService([{'urls': ['turn:turn.example.org:3478'], 'username': 'alice', 'credential': 'secret'}])

    monkeypatch.setattr(chat_controller_module, 'get_call_service', lambda: fake_call_service)

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        payload = await controller.refresh_call_ice_servers(force_refresh=True)

        assert fake_call_service.fetch_calls == 1
        assert payload == [{'urls': ['turn:turn.example.org:3478'], 'username': 'alice', 'credential': 'secret'}]
        assert controller.get_call_ice_servers() == payload

    asyncio.run(scenario())


def test_chat_controller_refresh_call_ice_servers_falls_back_to_local_config(monkeypatch) -> None:
    fake_call_service = FakeCallService(error=RuntimeError('network down'))
    fallback_config = types.SimpleNamespace(
        webrtc=types.SimpleNamespace(ice_servers=[{'urls': ['stun:local.example.org:3478']}])
    )

    monkeypatch.setattr(chat_controller_module, 'get_call_service', lambda: fake_call_service)
    monkeypatch.setattr(chat_controller_module, 'get_config', lambda: fallback_config)

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        payload = await controller.refresh_call_ice_servers(force_refresh=True)

        assert fake_call_service.fetch_calls == 1
        assert payload == [{'urls': ['stun:local.example.org:3478']}]
        assert controller.get_call_ice_servers() == payload

    asyncio.run(scenario())


def test_chat_controller_close_discards_call_ice_cache(monkeypatch) -> None:
    fake_call_service = FakeCallService([
        {'urls': ['turn:turn.example.org:3478'], 'username': 'alice', 'credential': 'secret'}
    ])
    fallback_config = types.SimpleNamespace(
        webrtc=types.SimpleNamespace(ice_servers=[{'urls': ['stun:local.example.org:3478']}])
    )

    class FakeCallManager:
        def __init__(self) -> None:
            self.close_calls = 0

        async def close(self) -> None:
            self.close_calls += 1

    fake_call_manager = FakeCallManager()
    monkeypatch.setattr(chat_controller_module, 'get_call_service', lambda: fake_call_service)
    monkeypatch.setattr(chat_controller_module, 'get_config', lambda: fallback_config)
    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: FakeSessionManager())
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: FakeNoopFileService())
    monkeypatch.setattr(chat_controller_module, 'get_call_manager', lambda: fake_call_manager)

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        await controller.refresh_call_ice_servers(force_refresh=True)
        assert controller.get_call_ice_servers()[0]['username'] == 'alice'

        await controller.close()

        assert fake_call_manager.close_calls == 1
        assert controller.get_call_ice_servers() == [{'urls': ['stun:local.example.org:3478']}]
        assert controller._call_ice_servers_loaded is False

    asyncio.run(scenario())

def test_chat_controller_send_file_uses_file_service(monkeypatch) -> None:
    fake_message_manager = FakeMessageManager()
    fake_session_manager = FakeSessionManager()
    fake_file_service = FakeFileService({'url': 'https://cdn.example/files/picture.png', 'mime_type': 'image/png'})

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: fake_file_service)

    workspace_tmp = Path('client/tests/.pytest_tmp')
    workspace_tmp.mkdir(parents=True, exist_ok=True)
    file_path = workspace_tmp / 'picture.png'
    file_path.write_bytes(b'png-data')

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        message = await controller.send_file(str(file_path))
        assert message is not None
        assert message.content == 'https://cdn.example/files/picture.png'
        assert fake_file_service.chat_uploads == [str(file_path)]
        assert fake_message_manager.failed == []
        assert len(fake_session_manager.added) == 1
        assert fake_session_manager.added[0][1].content == 'https://cdn.example/files/picture.png'
        assert fake_session_manager.added[0][1].extra['local_path'] == str(file_path)

    asyncio.run(scenario())


def test_message_manager_get_messages_uses_server_sender_profiles(monkeypatch) -> None:
    class RemoteMessageStoreDatabase(FakeMessageStoreDatabase):
        async def save_messages_batch(self, messages: list[ChatMessage]) -> None:
            await super().save_messages_batch(messages)
            self.messages = list(messages)

    class RemoteProfileChatService(FakeChatService):
        async def fetch_messages(self, session_id: str, limit: int, before_seq=None) -> list[dict]:
            await super().fetch_messages(session_id, limit, before_seq)
            return [
                {
                    'message_id': 'm-self',
                    'session_id': session_id,
                    'sender_id': 'user-1',
                    'content': 'hello',
                    'message_type': 'text',
                    'status': 'sent',
                    'timestamp': '2026-03-29T10:00:00',
                    'sender_profile': {
                        'id': 'user-1',
                        'username': 'alice',
                        'nickname': 'Alice',
                        'display_name': 'Alice',
                        'avatar': '/uploads/alice.svg',
                        'gender': 'female',
                    },
                },
                {
                    'message_id': 'm-other',
                    'session_id': session_id,
                    'sender_id': 'user-2',
                    'content': 'hi',
                    'message_type': 'text',
                    'status': 'received',
                    'timestamp': '2026-03-29T10:01:00',
                    'sender_profile': {
                        'id': 'user-2',
                        'username': 'bob',
                        'nickname': 'Bob',
                        'display_name': 'Bob',
                        'avatar': '/uploads/bob.svg',
                        'gender': 'male',
                    },
                },
            ]

    fake_db = RemoteMessageStoreDatabase([])

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: FakeEventBus())
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: FakeConnectionManager())
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(message_manager_module, 'get_chat_service', lambda: RemoteProfileChatService())
    monkeypatch.setattr(message_manager_module, 'get_file_service', lambda: FakeNoopFileService())

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('user-1')
        messages = await manager.get_messages('session-1', limit=2)

        assert messages[0].extra['sender_avatar'] == '/uploads/alice.svg'
        assert messages[0].extra['sender_gender'] == 'female'
        assert messages[0].extra['sender_username'] == 'alice'
        assert messages[1].extra['sender_avatar'] == '/uploads/bob.svg'
        assert messages[1].extra['sender_gender'] == 'male'
        assert messages[1].extra['sender_username'] == 'bob'
        assert len(fake_db.saved_batches) == 1

    asyncio.run(scenario())

def test_auth_controller_update_profile_uploads_avatar_via_file_service(monkeypatch) -> None:
    fake_auth_service = FakeAuthService()
    fake_user_service = FakeUserService()
    fake_db = FakeDatabase()
    fake_message_manager = FakeMessageManager()
    fake_chat_controller = FakeChatControllerContext()
    fake_file_service = FakeFileService({'id': 'user-1', 'avatar': 'https://cdn.example/files/avatar.png', 'avatar_kind': 'custom'})

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'peek_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'peek_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        result = await controller.update_profile(
            nickname='Alice',
            signature='Hello',
            avatar_file_path='D:/tmp/avatar.png',
        )
        user = result.user

        assert fake_file_service.avatar_uploads == ['D:/tmp/avatar.png']
        assert fake_user_service.update_calls == [
            {
                'nickname': 'Alice',
                'signature': 'Hello',
            }
        ]
        assert user['avatar'] == 'https://cdn.example/files/avatar.png'
        assert result.session_snapshot is not None
        assert result.session_snapshot.authoritative is True
        assert result.session_snapshot.unread_synchronized is True
        assert fake_message_manager.user_ids == []
        assert fake_chat_controller.user_ids == []
        assert fake_chat_controller.refresh_calls == 1
        assert fake_db.app_state[controller.USER_ID_KEY] == 'user-1'

    asyncio.run(scenario())


def test_auth_controller_update_profile_reports_degraded_session_snapshot_when_refresh_fails(monkeypatch) -> None:
    fake_auth_service = FakeAuthService()
    fake_user_service = FakeUserService()
    fake_db = FakeDatabase()
    fake_message_manager = FakeMessageManager()
    fake_chat_controller = FakeChatControllerContext()
    fake_chat_controller.refresh_exception = RuntimeError('refresh failed')
    fake_file_service = FakeFileService({'id': 'user-1', 'avatar': 'https://cdn.example/files/avatar.png', 'avatar_kind': 'custom'})

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'peek_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'peek_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        result = await controller.update_profile(avatar_file_path='D:/tmp/avatar.png')

        assert result.user['avatar'] == 'https://cdn.example/files/avatar.png'
        assert result.session_snapshot is not None
        assert result.session_snapshot.authoritative is False
        assert result.session_snapshot.unread_synchronized is False
        assert fake_chat_controller.refresh_calls == 1

    asyncio.run(scenario())


def test_auth_controller_constructor_does_not_materialize_chat_runtime(monkeypatch) -> None:
    fake_auth_service = FakeAuthService()
    fake_user_service = FakeUserService()
    fake_db = FakeDatabase()
    materialized: list[str] = []

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: FakeFileService())
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: materialized.append('message_manager'))
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: materialized.append('chat_controller'))
    monkeypatch.setattr(auth_controller_module, 'peek_message_manager', lambda: None)
    monkeypatch.setattr(auth_controller_module, 'peek_chat_controller', lambda: None)

    controller = auth_controller_module.AuthController()

    assert controller.current_user is None
    assert materialized == []


def test_auth_controller_login_uses_auth_service(monkeypatch) -> None:
    fake_auth_service = FakeAuthService()
    fake_user_service = FakeUserService()
    fake_db = FakeDatabase()
    fake_message_manager = FakeMessageManager()
    fake_chat_controller = FakeChatControllerContext()

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'peek_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'peek_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: FakeFileService())
    monkeypatch.setattr(auth_controller_module, 'peek_connection_manager', lambda: None)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        user = await controller.login('alice', 'secret')

        assert fake_auth_service.login_calls == [('alice', 'secret', False)]
        assert fake_auth_service.access_token == 'access-token'
        assert fake_auth_service.refresh_token == 'refresh-token'
        assert user['id'] == 'user-1'
        assert fake_message_manager.user_ids == []
        assert fake_chat_controller.user_ids == []
        assert fake_db.app_state[controller.USER_ID_KEY] == 'user-1'

    asyncio.run(scenario())


def test_auth_controller_broadcasts_auth_state_changes(monkeypatch) -> None:
    fake_auth_service = FakeAuthService()
    fake_user_service = FakeUserService()
    fake_db = FakeDatabase()
    fake_message_manager = FakeMessageManager()
    fake_chat_controller = FakeChatControllerContext()

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'peek_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'peek_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: FakeFileService())
    monkeypatch.setattr(auth_controller_module, 'peek_connection_manager', lambda: None)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        snapshots: list[dict] = []
        controller.add_auth_state_listener(lambda user: snapshots.append(dict(user or {})))

        await controller.login('alice', 'secret')
        await controller.clear_session(clear_local_chat_state=False)

        assert snapshots[0]['id'] == 'user-1'
        assert snapshots[-1] == {}

    asyncio.run(scenario())


def test_auth_controller_register_uses_backend_default_avatar_without_follow_up_upload(monkeypatch) -> None:
    fake_auth_service = FakeAuthService()
    fake_auth_service.login_payload['user'] = {
        'id': 'user-1',
        'username': 'alice',
        'nickname': 'Alice',
        'avatar': '/uploads/default_avatars/avatar_default_female_01.svg',
        'gender': None,
    }
    fake_user_service = FakeUserService()
    fake_db = FakeDatabase()
    fake_message_manager = FakeMessageManager()
    fake_chat_controller = FakeChatControllerContext()
    fake_file_service = FakeFileService({'url': 'https://cdn.example/files/default-avatar.svg'})

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'peek_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'peek_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(auth_controller_module, 'peek_connection_manager', lambda: None)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        user = await controller.register('alice', 'Alice', 'secret')

        assert fake_auth_service.register_calls == [('alice', 'Alice', 'secret')]
        assert fake_file_service.avatar_uploads == []
        assert fake_user_service.update_calls == []
        assert user['avatar'] == '/uploads/default_avatars/avatar_default_female_01.svg'
        assert user['gender'] is None
        assert fake_message_manager.user_ids == []
        assert fake_chat_controller.user_ids == []
        assert fake_db.app_state[controller.USER_ID_KEY] == 'user-1'

    asyncio.run(scenario())

def test_chat_controller_send_file_marks_failed_on_upload_error(monkeypatch) -> None:
    fake_message_manager = FakeMessageManager()
    fake_session_manager = FakeSessionManager()

    class FailingFileService:
        async def upload_chat_attachment(self, file_path: str) -> dict:
            raise APIError("Upload rejected")

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: FailingFileService())

    workspace_tmp = Path('client/tests/.pytest_tmp')
    workspace_tmp.mkdir(parents=True, exist_ok=True)
    file_path = workspace_tmp / 'reject.png'
    file_path.write_bytes(b'png-data')

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        message = await controller.send_file(str(file_path))

        assert message is not None
        assert message.message_id == 'local-1'
        assert fake_message_manager.failed == [('local-1', 'Upload rejected')]
        assert fake_message_manager.sent_messages == []

    asyncio.run(scenario())



def test_chat_controller_send_file_uses_encrypted_upload_artifact_when_message_manager_requests_it(monkeypatch) -> None:
    fake_message_manager = FakeMessageManager()
    fake_session_manager = FakeSessionManager()
    fake_file_service = FakeFileService({'url': 'https://cdn.example/files/blob.bin', 'mime_type': 'application/octet-stream'})

    workspace_tmp = Path('client/tests/.pytest_tmp')
    workspace_tmp.mkdir(parents=True, exist_ok=True)
    source_path = workspace_tmp / 'secret.pdf'
    encrypted_path = workspace_tmp / 'secret.enc'
    source_path.write_bytes(b'pdf-data')
    encrypted_path.write_bytes(b'encrypted-data')

    async def prepare_attachment_upload(*, session_id: str, file_path: str, message_type: MessageType, fallback_name: str, fallback_size: int):
        fake_message_manager.attachment_upload_preparations.append((session_id, file_path, message_type, fallback_name, fallback_size))
        return str(encrypted_path), {'attachment_encryption': {'enabled': True, 'scheme': 'aesgcm-file+x25519-v1'}}, str(encrypted_path)

    fake_message_manager.prepare_attachment_upload = prepare_attachment_upload  # type: ignore[method-assign]

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: fake_file_service)

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        message = await controller.send_file(str(source_path))

        assert message is not None
        assert fake_file_service.chat_uploads == [str(encrypted_path)]
        assert fake_message_manager.sent_messages[-1].extra['attachment_encryption']['enabled'] is True
        assert fake_message_manager.sent_messages[-1].extra['local_path'] == str(source_path)
        assert not encrypted_path.exists()

    asyncio.run(scenario())


def test_chat_controller_send_file_offloads_video_probe(monkeypatch) -> None:
    fake_message_manager = FakeMessageManager()
    fake_session_manager = FakeSessionManager()
    fake_file_service = FakeFileService({'url': 'https://cdn.example/files/video.mp4', 'mime_type': 'video/mp4'})
    to_thread_calls: list[tuple[object, str]] = []

    async def fake_to_thread(func, *args, **kwargs):
        to_thread_calls.append((func, args[0]))
        return 42

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: fake_file_service)
    monkeypatch.setattr(chat_controller_module.asyncio, 'to_thread', fake_to_thread)

    workspace_tmp = Path('client/tests/.pytest_tmp')
    workspace_tmp.mkdir(parents=True, exist_ok=True)
    file_path = workspace_tmp / 'clip.mp4'
    file_path.write_bytes(b'mp4-data')

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        message = await controller.send_file(str(file_path))

        assert message is not None
        assert to_thread_calls == [(controller._probe_video_duration, str(file_path))]
        assert fake_session_manager.added[0][1].extra['duration'] == 42
        assert fake_message_manager.sent_messages[-1].extra['duration'] == 42

    try:
        asyncio.run(scenario())
    finally:
        file_path.unlink(missing_ok=True)



def test_chat_controller_recover_session_crypto_delegates_to_session_manager(monkeypatch) -> None:
    fake_message_manager = FakeMessageManager()
    fake_session_manager = FakeSessionManager()
    fake_session_manager.recover_result = {'performed': True, 'session_id': 'session-2', 'recovery_action': 'reprovision_device'}

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: FakeFileService())

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        result = await controller.recover_session_crypto('session-2')

        assert result == {'performed': True, 'session_id': 'session-2', 'recovery_action': 'reprovision_device'}
        assert fake_session_manager.recover_calls == ['session-2']

    asyncio.run(scenario())


def test_chat_controller_recover_current_session_crypto_uses_selected_session(monkeypatch) -> None:
    fake_message_manager = FakeMessageManager()
    fake_session_manager = FakeSessionManager()

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: FakeFileService())

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        result = await controller.recover_current_session_crypto()

        assert result == {'performed': True, 'session_id': 'session-1'}
        assert fake_session_manager.recover_calls == ['session-1']

    asyncio.run(scenario())


def test_chat_controller_trust_session_identities_delegates_to_session_manager(monkeypatch) -> None:
    fake_session_manager = FakeSessionManager()

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: FakeFileService())
    monkeypatch.setattr(chat_controller_module, 'get_call_manager', lambda: types.SimpleNamespace())

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        result = await controller.trust_session_identities('session-2')

        assert fake_session_manager.trust_calls == ['session-2']
        assert result == {'performed': True, 'session_id': 'session-1'}

    asyncio.run(scenario())


def test_chat_controller_trust_current_session_identities_uses_selected_session(monkeypatch) -> None:
    fake_session_manager = FakeSessionManager()
    fake_session_manager.current_session_id = 'session-7'

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: FakeFileService())
    monkeypatch.setattr(chat_controller_module, 'get_call_manager', lambda: types.SimpleNamespace())

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        result = await controller.trust_current_session_identities()

        assert fake_session_manager.trust_calls == ['session-7']
        assert result == {'performed': True, 'session_id': 'session-1'}

    asyncio.run(scenario())


def test_chat_controller_get_session_security_summary_delegates_to_session_manager(monkeypatch) -> None:
    fake_session_manager = FakeSessionManager()
    fake_session_manager.security_summary_result = {'session_id': 'session-1', 'headline': 'identity_review_required'}

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: FakeFileService())
    monkeypatch.setattr(chat_controller_module, 'get_call_manager', lambda: types.SimpleNamespace())

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        result = await controller.get_session_security_summary('session-8')

        assert fake_session_manager.security_summary_calls == ['session-8']
        assert result == {'session_id': 'session-1', 'headline': 'identity_review_required'}

    asyncio.run(scenario())


def test_chat_controller_get_current_session_security_summary_uses_selected_session(monkeypatch) -> None:
    fake_session_manager = FakeSessionManager()
    fake_session_manager.current_session_id = 'session-9'
    fake_session_manager.security_summary_result = {'session_id': 'session-9', 'headline': 'secure'}

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: FakeFileService())
    monkeypatch.setattr(chat_controller_module, 'get_call_manager', lambda: types.SimpleNamespace())

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        result = await controller.get_current_session_security_summary()

        assert result == {'session_id': 'session-9', 'headline': 'secure'}

    asyncio.run(scenario())


def test_chat_controller_get_session_identity_verification_delegates_to_session_manager(monkeypatch) -> None:
    fake_session_manager = FakeSessionManager()
    fake_session_manager.identity_verification_result = {
        'session_id': 'session-1',
        'available': True,
        'verification': {'primary_verification_device_id': 'device-bob-1'},
    }

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: FakeFileService())
    monkeypatch.setattr(chat_controller_module, 'get_call_manager', lambda: types.SimpleNamespace())

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        result = await controller.get_session_identity_verification('session-10')

        assert fake_session_manager.identity_verification_calls == ['session-10']
        assert result == {
            'session_id': 'session-1',
            'available': True,
            'verification': {'primary_verification_device_id': 'device-bob-1'},
        }

    asyncio.run(scenario())


def test_chat_controller_get_current_session_identity_verification_uses_selected_session(monkeypatch) -> None:
    fake_session_manager = FakeSessionManager()
    fake_session_manager.current_session_id = 'session-11'
    fake_session_manager.identity_verification_result = {
        'session_id': 'session-11',
        'available': False,
        'verification': {},
    }

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: FakeFileService())
    monkeypatch.setattr(chat_controller_module, 'get_call_manager', lambda: types.SimpleNamespace())

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        result = await controller.get_current_session_identity_verification()

        assert fake_session_manager.identity_verification_calls == ['session-11']
        assert result == {
            'session_id': 'session-11',
            'available': False,
            'verification': {},
        }

    asyncio.run(scenario())


def test_chat_controller_get_session_identity_review_details_delegates_to_session_manager(monkeypatch) -> None:
    fake_session_manager = FakeSessionManager()
    fake_session_manager.identity_review_details_result = {
        'session_id': 'session-12',
        'available': True,
        'timeline': [{'kind': 'first_seen'}],
    }

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: FakeFileService())
    monkeypatch.setattr(chat_controller_module, 'get_call_manager', lambda: types.SimpleNamespace())

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        result = await controller.get_session_identity_review_details('session-12')

        assert fake_session_manager.identity_review_details_calls == ['session-12']
        assert result == {
            'session_id': 'session-12',
            'available': True,
            'timeline': [{'kind': 'first_seen'}],
        }

    asyncio.run(scenario())


def test_chat_controller_get_current_session_identity_review_details_uses_selected_session(monkeypatch) -> None:
    fake_session_manager = FakeSessionManager()
    fake_session_manager.current_session_id = 'session-13'
    fake_session_manager.identity_review_details_result = {
        'session_id': 'session-13',
        'available': False,
        'timeline': [],
    }

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: FakeFileService())
    monkeypatch.setattr(chat_controller_module, 'get_call_manager', lambda: types.SimpleNamespace())

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        result = await controller.get_current_session_identity_review_details()

        assert fake_session_manager.identity_review_details_calls == ['session-13']
        assert result == {
            'session_id': 'session-13',
            'available': False,
            'timeline': [],
        }

    asyncio.run(scenario())


def test_chat_controller_get_session_security_diagnostics_delegates_to_session_manager(monkeypatch) -> None:
    fake_session_manager = FakeSessionManager()
    fake_session_manager.security_diagnostics_result = {
        'session_id': 'session-14',
        'headline': 'identity_review_required',
    }

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: FakeFileService())
    monkeypatch.setattr(chat_controller_module, 'get_call_manager', lambda: types.SimpleNamespace())

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        result = await controller.get_session_security_diagnostics('session-14')

        assert fake_session_manager.security_diagnostics_calls == ['session-14']
        assert result == {
            'session_id': 'session-14',
            'headline': 'identity_review_required',
        }

    asyncio.run(scenario())


def test_chat_controller_get_current_session_security_diagnostics_uses_selected_session(monkeypatch) -> None:
    fake_session_manager = FakeSessionManager()
    fake_session_manager.current_session_id = 'session-15'
    fake_session_manager.security_diagnostics_result = {
        'session_id': 'session-15',
        'headline': 'secure',
    }

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: FakeFileService())
    monkeypatch.setattr(chat_controller_module, 'get_call_manager', lambda: types.SimpleNamespace())

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        result = await controller.get_current_session_security_diagnostics()

        assert fake_session_manager.security_diagnostics_calls == ['session-15']
        assert result == {
            'session_id': 'session-15',
            'headline': 'secure',
        }

    asyncio.run(scenario())


def test_chat_controller_execute_session_security_action_delegates_to_session_manager(monkeypatch) -> None:
    fake_session_manager = FakeSessionManager()
    fake_session_manager.security_action_result = {
        'performed': True,
        'session_id': 'session-1',
        'action_id': 'trust_peer_identity',
    }

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: FakeFileService())
    monkeypatch.setattr(chat_controller_module, 'get_call_manager', lambda: types.SimpleNamespace())

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        result = await controller.execute_session_security_action('session-8', 'trust_peer_identity')

        assert fake_session_manager.security_action_calls == [('session-8', 'trust_peer_identity')]
        assert result == {
            'performed': True,
            'session_id': 'session-1',
            'action_id': 'trust_peer_identity',
        }

    asyncio.run(scenario())


def test_chat_controller_execute_current_session_security_action_uses_selected_session(monkeypatch) -> None:
    fake_session_manager = FakeSessionManager()
    fake_session_manager.current_session_id = 'session-9'
    fake_session_manager.security_action_result = {
        'performed': False,
        'session_id': 'session-9',
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

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: FakeFileService())
    monkeypatch.setattr(chat_controller_module, 'get_call_manager', lambda: types.SimpleNamespace())

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        result = await controller.execute_current_session_security_action('switch_device')

        assert fake_session_manager.security_action_calls == [('session-9', 'switch_device')]
        assert result == {
            'performed': False,
            'session_id': 'session-9',
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

    asyncio.run(scenario())


def test_chat_controller_download_message_attachment_delegates_to_message_manager(monkeypatch) -> None:
    fake_message_manager = FakeMessageManager()
    fake_session_manager = FakeSessionManager()

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: FakeFileService())

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        local_path = await controller.download_message_attachment('msg-file-1')

        assert local_path == 'D:/downloads/msg-file-1.bin'
        assert fake_message_manager.download_attachment_calls == ['msg-file-1']

    asyncio.run(scenario())


def test_file_service_normalizes_backend_upload_payload(monkeypatch) -> None:
    class FakeUploadHttpClient:
        def __init__(self, payload: dict) -> None:
            self.payload = dict(payload)
            self.upload_calls: list[tuple[str, str]] = []

        async def upload_file(self, file_path: str, upload_path: str = '/files/upload') -> dict:
            self.upload_calls.append((file_path, upload_path))
            return dict(self.payload)

    fake_http = FakeUploadHttpClient({'id': 'user-1', 'avatar': '/uploads/avatar.png', 'avatar_kind': 'custom'})
    monkeypatch.setattr(file_service_module, 'get_http_client', lambda: fake_http)

    async def scenario() -> None:
        service = file_service_module.FileService()
        payload = await service.upload_profile_avatar('D:/tmp/avatar.png')

        assert payload['avatar'] == '/uploads/avatar.png'
        assert payload['avatar_kind'] == 'custom'
        assert fake_http.upload_calls == [('D:/tmp/avatar.png', '/users/me/avatar')]

    asyncio.run(scenario())



def test_file_service_drops_internal_upload_metadata_from_chat_payload(monkeypatch) -> None:
    class FakeUploadHttpClient:
        async def upload_file(self, file_path: str, upload_path: str = '/files/upload') -> dict:
            return {
                'url': '/uploads/blob.bin',
                'mime_type': 'application/octet-stream',
                'size_bytes': 8,
                'storage_provider': 'local',
                'storage_key': '2026/04/12/blob.bin',
                'checksum_sha256': 'abc123',
                'media': {
                    'url': '/uploads/blob.bin',
                    'storage_provider': 'local',
                    'storage_key': '2026/04/12/blob.bin',
                    'checksum_sha256': 'abc123',
                },
            }

    monkeypatch.setattr(file_service_module, 'get_http_client', lambda: FakeUploadHttpClient())

    async def scenario() -> None:
        service = file_service_module.FileService()
        payload = await service.upload_chat_attachment('D:/tmp/blob.bin')

        assert 'storage_provider' not in payload
        assert 'storage_key' not in payload
        assert 'checksum_sha256' not in payload
        assert payload['media'] == {
            'url': '/uploads/blob.bin',
            'original_name': 'blob.bin',
            'mime_type': 'application/octet-stream',
            'size_bytes': 8,
        }

    asyncio.run(scenario())


def test_build_remote_attachment_extra_drops_internal_media_metadata() -> None:
    extra = build_remote_attachment_extra(
        {
            'url': '/uploads/blob.bin',
            'mime_type': 'application/octet-stream',
            'size_bytes': 8,
            'media': {
                'url': '/uploads/blob.bin',
                'storage_provider': 'local',
                'storage_key': '2026/04/12/blob.bin',
                'checksum_sha256': 'abc123',
            },
        },
        fallback_name='blob.bin',
    )

    assert extra['media'] == {
        'url': '/uploads/blob.bin',
        'original_name': 'blob.bin',
        'mime_type': 'application/octet-stream',
        'size_bytes': 8,
    }


def test_file_service_downloads_chat_attachment_bytes(monkeypatch) -> None:
    class FakeDownloadHttpClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def download_bytes(self, file_url: str) -> bytes:
            self.calls.append(file_url)
            return b'cipher-bytes'

    fake_http = FakeDownloadHttpClient()
    monkeypatch.setattr(file_service_module, 'get_http_client', lambda: fake_http)

    async def scenario() -> None:
        service = file_service_module.FileService()
        payload = await service.download_chat_attachment('/uploads/blob.bin')

        assert payload == b'cipher-bytes'
        assert fake_http.calls == ['/uploads/blob.bin']

    asyncio.run(scenario())


def test_file_service_rejects_upload_payload_without_url(monkeypatch) -> None:
    class FakeUploadHttpClient:
        async def upload_file(self, file_path: str, upload_path: str = '/files/upload') -> dict:
            return {'mime_type': 'image/png'}

    monkeypatch.setattr(file_service_module, 'get_http_client', lambda: FakeUploadHttpClient())

    async def scenario() -> None:
        service = file_service_module.FileService()
        with pytest.raises(ServerError) as exc_info:
            await service.upload_chat_attachment('D:/tmp/file.png')

        assert exc_info.value.message == 'Upload response missing url'

    asyncio.run(scenario())


def test_contact_controller_load_contacts_and_search_users_use_services(monkeypatch) -> None:
    fake_contact_service = FakeContactService()
    fake_user_service = FakeUserService()
    fake_auth_context = FakeAuthContext()
    fake_contact_service.friends_payload = [
        {'id': 'user-2', 'username': 'zoe', 'nickname': 'Zoe', 'remark': '', 'avatar': ''},
        {'id': 'user-1', 'username': 'alice', 'nickname': 'Alice', 'remark': 'A Friend', 'avatar': ''},
    ]
    fake_user_service.search_payload = {
        'items': [
            {'id': 'user-3', 'username': 'bob', 'nickname': 'Bob', 'avatar': '/avatars/bob.png', 'status': 'online'},
        ]
    }

    monkeypatch.setattr(contact_controller_module, 'get_contact_service', lambda: fake_contact_service)
    monkeypatch.setattr(contact_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(contact_controller_module, 'get_auth_controller', lambda: fake_auth_context)

    async def scenario() -> None:
        controller = contact_controller_module.ContactController()
        contacts = await controller.load_contacts()
        users = await controller.search_users('bob', limit=5)

        assert fake_contact_service.fetch_friends_calls == 1
        assert fake_user_service.search_calls == [('bob', 1, 5)]
        assert [item.display_name for item in contacts] == ['A Friend', 'Zoe']
        assert [item.id for item in users] == ['user-3']

    asyncio.run(scenario())


def test_message_manager_get_cached_messages_skips_remote_backfill(monkeypatch) -> None:
    stored_messages = [
        ChatMessage(
            message_id='m-self',
            session_id='session-1',
            sender_id='user-1',
            content='hello',
            message_type=MessageType.TEXT,
            status=MessageStatus.SENT,
            is_self=True,
            extra={},
        ),
    ]
    fake_db = FakeMessageStoreDatabase(stored_messages)
    fake_chat_service = FakeChatService()

    monkeypatch.setattr(message_manager_module, 'get_event_bus', lambda: FakeEventBus())
    monkeypatch.setattr(message_manager_module, 'get_connection_manager', lambda: FakeConnectionManager())
    monkeypatch.setattr(message_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(message_manager_module, 'get_chat_service', lambda: fake_chat_service)
    monkeypatch.setattr(message_manager_module, 'get_file_service', lambda: FakeNoopFileService())

    async def scenario() -> None:
        manager = message_manager_module.MessageManager()
        manager.set_user_id('user-1')
        messages = await manager.get_cached_messages('session-1', limit=20)

        assert len(messages) == 1
        assert fake_chat_service.fetch_messages_calls == []
        assert len(fake_db.saved_batches) == 0

    asyncio.run(scenario())


def test_chat_controller_load_cached_messages_uses_message_manager_boundary(monkeypatch) -> None:
    fake_message_manager = FakeMessageManager()
    fake_session_manager = FakeSessionManager()
    fake_file_service = FakeFileService()

    monkeypatch.setattr(chat_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(chat_controller_module, 'get_session_manager', lambda: fake_session_manager)
    monkeypatch.setattr(chat_controller_module, 'get_file_service', lambda: fake_file_service)

    async def scenario() -> None:
        controller = chat_controller_module.ChatController()
        messages = await controller.load_cached_messages('session-42', limit=12)

        assert fake_message_manager.cached_messages_calls == [('session-42', 12, None)]
        assert len(messages) == 1
        assert messages[0].message_id == 'cached-1'

    asyncio.run(scenario())


def test_contact_controller_load_contacts_and_groups_persist_local_search_cache(monkeypatch) -> None:
    fake_contact_service = FakeContactService()
    fake_user_service = FakeUserService()
    fake_auth_context = FakeAuthContext()
    fake_db = FakeDatabase()
    fake_db.is_connected = True
    fake_contact_service.friends_payload = [
        {'id': 'user-2', 'username': 'zoe', 'nickname': 'Zoe', 'remark': '', 'avatar': '', 'region': 'Seoul'},
        {'id': 'user-1', 'username': 'alice', 'nickname': 'Alice', 'remark': 'A Friend', 'avatar': '', 'region': 'Shenzhen'},
    ]
    fake_contact_service.groups_payload = [
        {'id': 'group-2', 'name': 'Zeta Squad', 'member_count': 8, 'session_id': 'session-group-2'},
        {
            'id': 'group-1',
            'name': 'Core Team',
            'member_count': 3,
            'session_id': 'session-group-1',
            'members': [
                {'nickname': 'Alice', 'region': 'Shenzhen'},
            ],
        },
    ]

    monkeypatch.setattr(contact_controller_module, 'get_contact_service', lambda: fake_contact_service)
    monkeypatch.setattr(contact_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(contact_controller_module, 'get_auth_controller', lambda: fake_auth_context)
    monkeypatch.setattr(contact_controller_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        controller = contact_controller_module.ContactController()
        contacts = await controller.load_contacts()
        groups = await controller.load_groups()

        assert [item.display_name for item in contacts] == ['A Friend', 'Zoe']
        assert [item.name for item in groups] == ['Core Team', 'Zeta Squad']
        assert len(fake_db.replaced_contacts) == 1
        assert len(fake_db.replaced_groups) == 1
        assert [item['id'] for item in fake_db.replaced_contacts[0]] == ['user-1', 'user-2']
        assert [item['display_name'] for item in fake_db.replaced_contacts[0]] == ['A Friend', 'Zoe']
        assert [item['region'] for item in fake_db.replaced_contacts[0]] == ['Shenzhen', 'Seoul']
        assert [item['id'] for item in fake_db.replaced_groups[0]] == ['group-1', 'group-2']
        assert fake_db.replaced_groups[0][0]['member_search_text'] == 'Alice Shenzhen'
        assert fake_db.replaced_groups[0][0]['extra']['member_previews'] == ['Alice Shenzhen']
        assert fake_db.replaced_contacts[0][0]['extra'] == {
            'id': 'user-1',
            'display_name': 'A Friend',
            'username': 'alice',
            'nickname': 'Alice',
            'avatar': '',
            'gender': '',
            'status': '',
            'profile_event_id': '',
        }

    asyncio.run(scenario())


def test_contact_controller_load_requests_resolves_counterpart_names(monkeypatch) -> None:
    fake_contact_service = FakeContactService()
    fake_user_service = FakeUserService()
    fake_auth_context = FakeAuthContext()
    outgoing_target_id = '11111111-2222-3333-4444-555555555555'
    incoming_sender_id = '66666666-7777-8888-9999-000000000000'
    fake_contact_service.requests_payload = [
        {
            'request_id': 'req-1',
            'message': 'hello',
            'status': 'accepted',
            'created_at': '2026-03-27T10:00:00Z',
            'sender': {'id': 'user-1', 'nickname': 'Alice', 'username': 'alice'},
            'receiver': {'id': outgoing_target_id, 'nickname': 'Test 2', 'username': 'test2', 'avatar': '/uploads/test2.png', 'gender': 'female'},
        },
        {
            'request_id': 'req-2',
            'message': 'hi',
            'status': 'pending',
            'created_at': '2026-03-26T09:00:00Z',
            'sender': {'id': incoming_sender_id, 'nickname': 'Test 3', 'username': 'test3', 'avatar': '/uploads/test3.png', 'gender': 'male'},
            'receiver': {'id': 'user-1', 'nickname': 'Alice', 'username': 'alice'},
        },
    ]
    monkeypatch.setattr(contact_controller_module, 'get_contact_service', lambda: fake_contact_service)
    monkeypatch.setattr(contact_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(contact_controller_module, 'get_auth_controller', lambda: fake_auth_context)

    async def scenario() -> None:
        controller = contact_controller_module.ContactController()
        requests = await controller.load_requests()

        assert fake_user_service.fetch_user_calls == []
        assert [item.id for item in requests] == ['req-1', 'req-2']
        assert requests[0].counterpart_name('user-1') == 'Test 2'
        assert requests[0].counterpart_avatar('user-1') == '/uploads/test2.png'
        assert requests[0].counterpart_gender('user-1') == 'female'
        assert requests[1].counterpart_name('user-1') == 'Test 3'
        assert requests[1].counterpart_avatar('user-1') == '/uploads/test3.png'
        assert requests[1].counterpart_gender('user-1') == 'male'

    asyncio.run(scenario())


def test_contact_controller_persist_contacts_cache_uses_minimal_search_payload(monkeypatch) -> None:
    fake_contact_service = FakeContactService()
    fake_user_service = FakeUserService()
    fake_auth_context = FakeAuthContext()
    fake_db = FakeDatabase()
    fake_db.is_connected = True

    monkeypatch.setattr(contact_controller_module, 'get_contact_service', lambda: fake_contact_service)
    monkeypatch.setattr(contact_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(contact_controller_module, 'get_auth_controller', lambda: fake_auth_context)
    monkeypatch.setattr(contact_controller_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        controller = contact_controller_module.ContactController()
        await controller.persist_contacts_cache(
            [
                contact_controller_module.ContactRecord(
                    id='user-2',
                    name='bob',
                    username='bob',
                    nickname='Bobby',
                    avatar='/avatars/bob.png',
                    region='Busan',
                    gender='male',
                    status='busy',
                    extra={'email': 'private@example.com', 'profile_event_id': 'evt-1'},
                )
            ]
        )

        assert fake_db.replaced_contacts == [[
            {
                'id': 'user-2',
                'name': 'bob',
                'display_name': 'Bobby',
                'username': 'bob',
                'nickname': 'Bobby',
                'remark': '',
                'assistim_id': '',
                'region': 'Busan',
                'avatar': '/avatars/bob.png',
                'signature': '',
                'category': 'friend',
                'status': 'busy',
                'extra': {
                    'id': 'user-2',
                    'display_name': 'Bobby',
                    'username': 'bob',
                    'nickname': 'Bobby',
                    'avatar': '/avatars/bob.png',
                    'gender': 'male',
                    'status': 'busy',
                    'profile_event_id': 'evt-1',
                },
            }
        ]]

    asyncio.run(scenario())


def test_contact_controller_mutations_use_contact_service(monkeypatch) -> None:
    fake_contact_service = FakeContactService()
    fake_user_service = FakeUserService()
    fake_auth_context = FakeAuthContext()

    monkeypatch.setattr(contact_controller_module, 'get_contact_service', lambda: fake_contact_service)
    monkeypatch.setattr(contact_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(contact_controller_module, 'get_auth_controller', lambda: fake_auth_context)

    async def scenario() -> None:
        controller = contact_controller_module.ContactController()
        request_payload = await controller.send_friend_request('user-2', 'hello')
        group = await controller.create_group('Core Team', ['user-2', 'user-3'])
        fetched_group = await controller.fetch_group('group-1')
        shared_group = await controller.update_group_profile('group-1', name='Renamed Team', announcement='Ship tonight')
        self_group = await controller.update_my_group_profile('group-1', note='private note', my_group_nickname='lead')
        group_after_add = await controller.add_group_member('group-1', 'user-4')
        group_after_role = await controller.update_group_member_role('group-1', 'user-2', role='admin')
        group_after_remove = await controller.remove_group_member('group-1', 'user-4')
        group_after_transfer = await controller.transfer_group_ownership('group-1', 'user-2')
        leave_result = await controller.leave_group('group-1')
        accepted = await controller.accept_request('req-1')
        rejected = await controller.reject_request('req-2')
        await controller.remove_friend('user-2')

        assert request_payload['status'] == 'pending'
        assert fake_contact_service.send_friend_request_calls == [('user-2', 'hello')]
        assert fake_contact_service.create_group_calls == [('Core Team', ['user-2', 'user-3'])]
        assert group.session_id == 'session-group-1'
        assert group.member_count == 3
        assert fetched_group.id == 'group-1'
        assert shared_group.name == 'Renamed Team'
        assert shared_group.extra['announcement'] == 'Ship tonight'
        assert self_group.extra['group_note'] == 'private note'
        assert self_group.extra['my_group_nickname'] == 'lead'
        assert group_after_add.member_count == 4
        assert any(member.get('id') == 'user-4' for member in group_after_add.extra['members'])
        assert any(member.get('id') == 'user-2' and member.get('role') == 'admin' for member in group_after_role.extra['members'])
        assert all(member.get('id') != 'user-4' for member in group_after_remove.extra['members'])
        assert group_after_transfer.owner_id == 'user-2'
        assert leave_result['mutation']['action'] == 'left'
        assert fake_contact_service.fetch_group_calls == ['group-1']
        assert fake_contact_service.update_group_profile_calls == [('group-1', 'Renamed Team', 'Ship tonight')]
        assert fake_contact_service.update_my_group_profile_calls == [('group-1', 'private note', 'lead')]
        assert fake_contact_service.add_group_member_calls == [('group-1', 'user-4', 'member')]
        assert fake_contact_service.update_group_member_role_calls == [('group-1', 'user-2', 'admin')]
        assert fake_contact_service.remove_group_member_calls == [('group-1', 'user-4')]
        assert fake_contact_service.transfer_group_ownership_calls == [('group-1', 'user-2')]
        assert fake_contact_service.leave_group_calls == ['group-1']
        assert accepted['status'] == 'accepted'
        assert rejected['status'] == 'rejected'
        assert fake_contact_service.accept_calls == ['req-1']
        assert fake_contact_service.reject_calls == ['req-2']
        assert fake_contact_service.remove_calls == ['user-2']

    asyncio.run(scenario())


def test_discovery_controller_load_moments_uses_services(monkeypatch) -> None:
    fake_discovery_service = FakeDiscoveryService()
    fake_user_service = FakeUserService()
    fake_auth_context = FakeAuthContext({'id': 'user-1', 'username': 'alice', 'nickname': 'Alice', 'avatar': '/avatars/alice.png'})
    fake_discovery_service.moments_payload = [
        {
            'id': 'moment-1',
            'user_id': 'user-2',
            'content': 'hello',
            'created_at': '2026-03-23T10:00:00Z',
            'comments': [
                {'id': 'comment-1', 'user_id': 'user-3', 'content': 'nice', 'created_at': '2026-03-23T10:01:00Z'},
            ],
        }
    ]
    fake_user_service.user_payloads = {
        'user-2': {'id': 'user-2', 'username': 'bob', 'nickname': 'Bob', 'avatar': '/avatars/bob.png'},
        'user-3': {'id': 'user-3', 'username': 'charlie', 'nickname': 'Charlie', 'avatar': '/avatars/charlie.png'},
    }

    monkeypatch.setattr(discovery_controller_module, 'get_discovery_service', lambda: fake_discovery_service)
    monkeypatch.setattr(discovery_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(discovery_controller_module, 'get_auth_controller', lambda: fake_auth_context)

    async def scenario() -> None:
        controller = discovery_controller_module.DiscoveryController()
        moments = await controller.load_moments()

        assert fake_discovery_service.fetch_moments_calls == [None]
        assert set(fake_user_service.fetch_user_calls) == {'user-2', 'user-3'}
        assert len(moments) == 1
        assert moments[0].display_name == 'Bob'
        assert moments[0].comments[0].display_name == 'Charlie'

    asyncio.run(scenario())


def test_discovery_controller_mutations_use_discovery_service(monkeypatch) -> None:
    fake_discovery_service = FakeDiscoveryService()
    fake_user_service = FakeUserService()
    fake_auth_context = FakeAuthContext({'id': 'user-1', 'username': 'alice', 'nickname': 'Alice', 'avatar': '/avatars/alice.png'})
    fake_discovery_service.created_moment_payload = {
        'id': 'moment-2',
        'user_id': 'user-1',
        'content': 'new post',
        'created_at': '2026-03-23T11:00:00Z',
    }
    fake_discovery_service.comment_payload = {
        'id': 'comment-2',
        'moment_id': 'moment-2',
        'user_id': 'user-1',
        'content': 'thanks',
        'created_at': '2026-03-23T11:01:00Z',
    }

    monkeypatch.setattr(discovery_controller_module, 'get_discovery_service', lambda: fake_discovery_service)
    monkeypatch.setattr(discovery_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(discovery_controller_module, 'get_auth_controller', lambda: fake_auth_context)

    async def scenario() -> None:
        controller = discovery_controller_module.DiscoveryController()
        moment = await controller.create_moment('new post')
        liked = await controller.set_liked('moment-2', True, like_count=3)
        unliked = await controller.set_liked('moment-2', False, like_count=2)
        comment = await controller.add_comment('moment-2', 'thanks')

        assert fake_discovery_service.create_moment_calls == ['new post']
        assert moment.id == 'moment-2'
        assert liked is True
        assert unliked is False
        assert fake_discovery_service.like_calls == ['moment-2']
        assert fake_discovery_service.unlike_calls == ['moment-2']
        assert fake_discovery_service.comment_calls == [('moment-2', 'thanks')]
        assert comment.content == 'thanks'

    asyncio.run(scenario())


def test_search_manager_uses_database_search_boundary(monkeypatch) -> None:
    fake_db = FakeSearchDatabase(
        [
            ChatMessage(
                message_id='msg-1',
                session_id='session-1',
                sender_id='user-1',
                content='discount 100%_off now',
                message_type=MessageType.TEXT,
                status=MessageStatus.SENT,
                is_self=True,
            )
        ]
    )

    monkeypatch.setattr(search_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = search_manager_module.SearchManager()
        results = await manager.search('100%_off', session_id='session-1', limit=5)

        assert fake_db.search_calls == [('100%_off', 'session-1', 20)]
        assert len(results) == 1
        assert results[0].message.message_id == 'msg-1'
        assert results[0].matched_text == 'discount 100%_off now'
        assert results[0].highlight_ranges == [(9, 17)]

    asyncio.run(scenario())


def test_search_manager_search_all_uses_storage_boundaries(monkeypatch) -> None:
    fake_db = FakeSearchDatabase(
        [
            ChatMessage(
                message_id='msg-1',
                session_id='session-1',
                sender_id='user-1',
                content='Core roadmap is ready',
                message_type=MessageType.TEXT,
                status=MessageStatus.SENT,
                is_self=True,
            )
            ,
            ChatMessage(
                message_id='msg-2',
                session_id='session-1',
                sender_id='user-2',
                content='Second core update for roadmap',
                message_type=MessageType.TEXT,
                status=MessageStatus.SENT,
                is_self=False,
            )
        ],
        contacts=[
            {
                'id': 'user-2',
                'display_name': 'Alice',
                'username': 'alice',
                'nickname': 'Alice',
                'remark': '',
                'assistim_id': 'alice',
                'region': 'Core City',
                'signature': '',
            }
        ],
        groups=[
            {
                'id': 'group-1',
                'name': 'Core Team',
                'session_id': 'session-group-1',
                'member_search_text': 'Alice Shenzhen',
                'extra': {'member_previews': ['Alice Shenzhen']},
            }
        ],
    )

    monkeypatch.setattr(search_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = search_manager_module.SearchManager()
        results = await manager.search_all(
            'core',
            session_id='session-1',
            message_limit=3,
            contact_limit=4,
            group_limit=5,
        )

        assert fake_db.search_calls == [('core', 'session-1', 12)]
        assert fake_db.search_contact_calls == [('core', 4)]
        assert fake_db.search_group_calls == [('core', 5)]
        assert len(results.messages) == 1
        assert len(results.contacts) == 1
        assert len(results.groups) == 1
        assert results.messages[0].message.message_id == 'msg-1'
        assert results.messages[0].match_count == 2
        assert results.contacts[0].contact['id'] == 'user-2'
        assert results.groups[0].group['id'] == 'group-1'
        assert manager.last_catalog_results == results

    asyncio.run(scenario())


def test_search_manager_group_member_match_uses_cached_member_previews(monkeypatch) -> None:
    fake_db = FakeSearchDatabase(
        [],
        groups=[
            {
                'id': 'group-1',
                'name': 'Weekend Club',
                'session_id': 'session-group-1',
                'member_search_text': 'Alice Shenzhen',
                'extra': {'member_previews': ['Alice Shenzhen']},
            }
        ],
    )

    monkeypatch.setattr(search_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = search_manager_module.SearchManager()
        results = await manager.search_groups('shenzhen', limit=5)

        assert fake_db.search_group_calls == [('shenzhen', 5)]
        assert len(results) == 1
        assert results[0].matched_field == 'member'
        assert 'Shenzhen' in results[0].matched_text

    asyncio.run(scenario())


def test_search_manager_contact_display_name_and_message_catalog_state_are_isolated(monkeypatch) -> None:
    fake_db = FakeSearchDatabase(
        [
            ChatMessage(
                message_id='msg-1',
                session_id='session-1',
                sender_id='user-1',
                content='roadmap update',
                message_type=MessageType.TEXT,
                status=MessageStatus.SENT,
                is_self=True,
            )
        ],
        contacts=[
            {
                'id': 'user-2',
                'display_name': 'Alice Cooper',
                'username': 'alice',
                'nickname': '',
                'remark': '',
                'assistim_id': 'alice',
                'region': '',
                'signature': '',
            }
        ],
    )

    monkeypatch.setattr(search_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = search_manager_module.SearchManager()
        message_results = await manager.search('roadmap', session_id='session-1', limit=3)
        catalog_results = await manager.search_all('cooper', contact_limit=5, group_limit=5, message_limit=2)

        assert message_results[0].message.message_id == 'msg-1'
        assert manager.get_result_at(0).message.message_id == 'msg-1'
        assert catalog_results.contacts[0].matched_field == 'display_name'
        assert catalog_results.contacts[0].contact['id'] == 'user-2'
        assert manager.get_result_at(0).message.message_id == 'msg-1'

    asyncio.run(scenario())


def test_database_search_messages_escapes_like_wildcards() -> None:
    fake_connection = FakeSearchConnection(
        [
            {
                'message_id': 'msg-1',
                'session_id': 'session-1',
                'sender_id': 'user-1',
                'content': 'literal 100%_off keyword',
                'message_type': 'text',
                'status': 'sent',
                'timestamp': 1700000000,
                'updated_at': 1700000001,
                'is_self': 1,
                'is_ai': 0,
                'extra': '{}',
            }
        ]
    )

    async def scenario() -> None:
        db = database_module.Database(db_path='client/tests/.pytest_tmp/search-test.db')
        db._db = fake_connection

        messages = await db.search_messages('100%_off', session_id='session-1', limit=25)

        assert len(messages) == 1
        assert messages[0].content == 'literal 100%_off keyword'
        assert len(fake_connection.execute_calls) == 2

        sql, params = fake_connection.execute_calls[-1]
        assert "content LIKE ? ESCAPE '\\'" in sql
        assert params == ('session-1', '%100\\%\\_off%', 25)

    asyncio.run(scenario())


def test_session_manager_refresh_remote_sessions_uses_session_service(monkeypatch) -> None:
    fake_session_service = FakeSessionService()
    fake_e2ee_service = FakeE2EEService({'device_id': 'device-local-1', 'has_local_bundle': True})

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: fake_session_service)
    monkeypatch.setattr(session_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: FakeEventBus())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: FakeSessionStateDatabase())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        result = await manager.refresh_remote_sessions()
        sessions = result.sessions

        assert fake_session_service.fetch_sessions_calls == 1
        assert fake_session_service.fetch_unread_counts_calls == 1
        assert fake_e2ee_service.calls >= 1
        assert result.authoritative is True
        assert result.unread_synchronized is True
        assert len(sessions) == 1
        assert sessions[0].session_id == 'session-1'
        assert sessions[0].extra['group_id'] == 'group-1'
        assert sessions[0].extra['group_member_version'] == 42
        assert fake_e2ee_service.reconcile_group_session_state_calls == []
        assert sessions[0].extra['encryption_mode'] == 'plain'
        assert sessions[0].extra['call_capabilities'] == {'voice': False, 'video': False}
        assert sessions[0].extra['call_state'] == {}
        assert sessions[0].extra['session_crypto_state'] == {
            'enabled': False,
            'ready': False,
            'can_decrypt': False,
            'device_registered': True,
            'device_id': 'device-local-1',
        }
        assert sessions[0].uses_e2ee() is False
        assert sessions[0].unread_count == 4

    asyncio.run(scenario())


def test_session_manager_fetches_new_group_session_from_group_event(monkeypatch) -> None:
    fake_session_service = FakeSessionService()
    fake_event_bus = FakeEventBus()

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: fake_session_service)
    monkeypatch.setattr(session_manager_module, 'get_e2ee_service', lambda: FakeE2EEService())
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: FakeSessionStateDatabase())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        await manager._on_group_updated(
            {
                'session_id': 'session-1',
                'group_id': 'group-1',
                'group': {
                    'id': 'group-1',
                    'session_id': 'session-1',
                    'name': 'Core Team',
                },
            }
        )

        assert fake_session_service.fetch_session_calls == ['session-1']
        assert manager.sessions[0].session_id == 'session-1'
        assert any(event == session_manager_module.SessionEvent.ADDED for event, _ in fake_event_bus.events)

    asyncio.run(scenario())


def test_session_manager_lifecycle_contact_refresh_reloads_sessions(monkeypatch) -> None:
    fake_session_service = FakeSessionService()

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: fake_session_service)
    monkeypatch.setattr(session_manager_module, 'get_e2ee_service', lambda: FakeE2EEService())
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: FakeEventBus())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: FakeSessionStateDatabase())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        await manager._on_contact_sync_required({'reason': 'session_lifecycle_changed'})

        assert fake_session_service.fetch_sessions_calls == 1
        assert manager.sessions[0].session_id == 'session-1'

    asyncio.run(scenario())



def test_session_manager_refresh_remote_sessions_prunes_connection_sync_state(monkeypatch) -> None:
    from client.managers import connection_manager as connection_manager_module

    fake_session_service = FakeSessionService()
    fake_e2ee_service = FakeE2EEService({'device_id': 'device-local-1', 'has_local_bundle': True})
    fake_db = FakeSessionProfileDatabase()

    class _FakeConnectionManager:
        def __init__(self) -> None:
            self.pruned: list[list[str]] = []

        async def prune_sync_state(self, active_session_ids) -> None:
            self.pruned.append(list(active_session_ids))

    fake_connection_manager = _FakeConnectionManager()

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: fake_session_service)
    monkeypatch.setattr(session_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: FakeEventBus())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(connection_manager_module, 'peek_connection_manager', lambda: fake_connection_manager)

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()

        result = await manager.refresh_remote_sessions()

        assert result.authoritative is True
        assert fake_connection_manager.pruned == [['session-1']]
        assert [session.session_id for session in fake_db.replaced_sessions] == ['session-1']

    asyncio.run(scenario())
def test_session_manager_refresh_remote_sessions_prefers_counterpart_profile(monkeypatch) -> None:
    fake_session_service = FakeSessionService()
    fake_e2ee_service = FakeE2EEService(
        {'device_id': 'device-local-1', 'has_local_bundle': True},
        peer_identity_summary={
            'status': 'identity_changed',
            'device_count': 2,
            'trusted_device_count': 1,
            'unverified_device_count': 0,
            'changed_device_count': 1,
            'unverified_device_ids': [],
            'changed_device_ids': ['device-bob-2'],
            'change_count': 1,
            'last_changed_at': '2026-04-06T12:15:00+00:00',
            'last_trusted_at': '2026-04-06T11:45:00+00:00',
            'checked_at': '2026-04-06T12:00:00+00:00',
        },
    )
    fake_db = FakeSessionProfileDatabase()
    fake_session_service.session_payload = {
        'id': 'session-1',
        'name': 'Private Chat',
        'session_type': 'direct',
        'participant_ids': ['user-1', 'user-2'],
        'members': [
            {
                'id': 'user-1',
                'username': 'alice',
                'nickname': 'Alice',
                'avatar': '/uploads/alice.svg',
                'gender': 'female',
            },
            {
                'id': 'user-2',
                'username': 'bob',
                'nickname': 'Bobby',
                'avatar': '/uploads/bob.svg',
                'gender': 'male',
            },
        ],
    }

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: fake_session_service)
    monkeypatch.setattr(session_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: FakeEventBus())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        result = await manager.refresh_remote_sessions()

        assert result.authoritative is True
        assert result.unread_synchronized is True
        assert len(result.sessions) == 1
        session = result.sessions[0]
        assert session.name == 'Bobby'
        assert session.avatar is None
        assert session.display_avatar() == '/uploads/bob.svg'
        assert session.extra['counterpart_gender'] == 'male'
        assert session.extra['counterpart_avatar'] == '/uploads/bob.svg'
        assert session.extra['counterpart_id'] == 'user-2'
        assert session.extra['counterpart_username'] == 'bob'
        assert session.extra['encryption_mode'] == 'plain'
        assert session.extra['call_capabilities'] == {'voice': True, 'video': True}
        assert session.extra['call_state'] == {'active': False, 'status': 'idle'}
        assert fake_e2ee_service.peer_identity_calls == []
        assert session.extra['session_crypto_state'] == {
            'enabled': False,
            'ready': False,
            'can_decrypt': False,
            'device_registered': True,
            'device_id': 'device-local-1',
        }
        assert session.uses_e2ee() is False
        assert session.extra['avatar_seed'] == session_manager_module.profile_avatar_seed(
            user_id='user-2',
            username='bob',
            display_name='Bobby',
        )
        assert len(fake_db.replaced_sessions) == 1

    asyncio.run(scenario())


def test_session_manager_refresh_remote_sessions_reports_non_authoritative_failure(monkeypatch) -> None:
    fake_session_service = FakeSessionService()
    fake_session_service.fetch_sessions_error = RuntimeError('sessions unavailable')
    fake_event_bus = FakeEventBus()

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: fake_session_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: FakeSessionStateDatabase())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        existing = Session(
            session_id='session-1',
            name='Cached Session',
            session_type='group',
            participant_ids=['alice', 'bob'],
            unread_count=7,
        )
        manager._sessions[existing.session_id] = existing

        result = await manager.refresh_remote_sessions()

        assert fake_session_service.fetch_sessions_calls == 1
        assert fake_session_service.fetch_unread_counts_calls == 0
        assert result.authoritative is False
        assert result.unread_synchronized is False
        assert result.sessions == [existing]
        assert manager.sessions == [existing]
        assert fake_event_bus.events == []

    asyncio.run(scenario())



def test_session_manager_refresh_remote_sessions_preserves_local_unread_when_unread_snapshot_fails(monkeypatch) -> None:
    fake_session_service = FakeSessionService()
    fake_session_service.fetch_unread_counts_error = RuntimeError('unread unavailable')
    fake_event_bus = FakeEventBus()
    fake_db = FakeSessionProfileDatabase()

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: fake_session_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        existing = Session(
            session_id='session-1',
            name='Cached Session',
            session_type='group',
            participant_ids=['alice', 'bob'],
            unread_count=7,
        )
        manager._sessions[existing.session_id] = existing

        result = await manager.refresh_remote_sessions()

        assert fake_session_service.fetch_sessions_calls == 1
        assert fake_session_service.fetch_unread_counts_calls == 1
        assert result.authoritative is True
        assert result.unread_synchronized is False
        assert len(result.sessions) == 1
        assert result.sessions[0].session_id == 'session-1'
        assert result.sessions[0].unread_count == 7
        assert result.sessions[0].name == 'Core Team'
        assert fake_db.replaced_sessions[0].unread_count == 7
        assert any(
            event_type == session_manager_module.SessionEvent.UPDATED
            and payload.get('sessions') == result.sessions
            for event_type, payload in fake_event_bus.events
        )

    asyncio.run(scenario())



def test_session_manager_call_events_update_runtime_call_state(monkeypatch) -> None:
    from client.models.call import ActiveCallState

    fake_event_bus = FakeEventBus()

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: FakeSessionService())
    monkeypatch.setattr(session_manager_module, 'get_e2ee_service', lambda: FakeE2EEService({'device_id': 'device-local-1', 'has_local_bundle': True}))
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: FakeSessionStateDatabase())
    monkeypatch.setattr(session_manager_module, 'get_call_manager', lambda: types.SimpleNamespace(active_call=None))

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = Session(
            session_id='session-1',
            name='Bob',
            session_type='direct',
            participant_ids=['user-1', 'user-2'],
        )
        session.extra['call_capabilities'] = {'voice': True, 'video': True}
        session.extra['call_state'] = {'active': False, 'status': 'idle'}
        manager._sessions[session.session_id] = session
        manager._current_user_id = 'user-1'

        await manager._apply_call_state_event(
            {
                'call': ActiveCallState(
                    call_id='call-1',
                    session_id='session-1',
                    initiator_id='user-1',
                    recipient_id='user-2',
                    media_type='video',
                    direction='outgoing',
                    status='accepted',
                )
            }
        )

        assert session.extra['call_state'] == {
            'active': True,
            'status': 'accepted',
            'call_id': 'call-1',
            'media_type': 'video',
            'direction': 'outgoing',
            'peer_user_id': 'user-2',
        }

        await manager._apply_call_state_event(
            {
                'call': ActiveCallState(
                    call_id='call-1',
                    session_id='session-1',
                    initiator_id='user-1',
                    recipient_id='user-2',
                    media_type='video',
                    direction='outgoing',
                    status='ended',
                    reason='hangup',
                )
            }
        )

        assert session.extra['call_state'] == {
            'active': False,
            'status': 'ended',
            'call_id': 'call-1',
            'media_type': 'video',
            'direction': 'outgoing',
            'peer_user_id': 'user-2',
            'reason': 'hangup',
        }
        assert any(event == session_manager_module.SessionEvent.UPDATED for event, _ in fake_event_bus.events)

    asyncio.run(scenario())


def test_session_manager_message_decryption_state_updates_session_crypto_state(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: FakeSessionService())
    monkeypatch.setattr(session_manager_module, 'get_e2ee_service', lambda: FakeE2EEService({'device_id': 'device-local-1', 'has_local_bundle': True}))
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: FakeSessionStateDatabase())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = Session(
            session_id='session-1',
            name='Bob',
            session_type='direct',
            participant_ids=['user-1', 'user-2'],
        )
        session.extra['encryption_mode'] = 'e2ee_private'
        session.extra['session_crypto_state'] = {
            'enabled': True,
            'ready': True,
            'can_decrypt': True,
            'device_registered': True,
            'scheme': 'x25519-aesgcm-v1',
            'attachment_scheme': 'aesgcm-file+x25519-v1',
            'device_id': 'device-local-1',
        }
        manager._sessions[session.session_id] = session

        await manager._on_message_decryption_state_changed(
            {
                'session_id': 'session-1',
                'message_id': 'm-1',
                'decryption_state': 'missing_private_key',
                'recovery_action': 'reprovision_device',
                'can_decrypt': False,
                'local_device_id': 'device-local-1',
                'target_device_id': 'device-local-1',
            }
        )

        assert session.extra['session_crypto_state']['ready'] is False
        assert session.extra['session_crypto_state']['can_decrypt'] is False
        assert session.extra['session_crypto_state']['decryption_state'] == 'missing_private_key'
        assert session.extra['session_crypto_state']['recovery_action'] == 'reprovision_device'
        assert session.extra['session_crypto_state']['last_failure_message_id'] == 'm-1'

        await manager._on_message_decryption_state_changed(
            {
                'session_id': 'session-1',
                'message_id': 'm-1',
                'decryption_state': 'ready',
                'can_decrypt': True,
                'local_device_id': 'device-local-1',
                'target_device_id': 'device-local-1',
            }
        )

        assert session.extra['session_crypto_state']['ready'] is True
        assert session.extra['session_crypto_state']['can_decrypt'] is True
        assert 'decryption_state' not in session.extra['session_crypto_state']
        assert 'recovery_action' not in session.extra['session_crypto_state']
        assert 'last_failure_message_id' not in session.extra['session_crypto_state']
        assert any(event == session_manager_module.SessionEvent.UPDATED for event, _ in fake_event_bus.events)

    asyncio.run(scenario())


def test_session_manager_recover_session_crypto_reprovisions_local_device(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_db = FakeSessionProfileDatabase()
    fake_e2ee_service = FakeE2EEService(
        {'device_id': 'device-local-1', 'has_local_bundle': True},
        reprovision_response={'device_id': 'device-local-2'},
    )
    fake_message_manager = FakeMessageManager()
    fake_message_manager.recover_session_messages_result = {
        'session_id': 'session-1',
        'scanned': 3,
        'updated': 2,
        'message_ids': ['m-1', 'm-2'],
        'remote_fetched': 4,
        'remote_pages_fetched': 2,
        'recovery_stats': {
            'cached': {
                'text': 2,
                'attachments': 0,
                'direct_text': 2,
                'group_text': 0,
                'direct_attachments': 0,
                'group_attachments': 0,
                'other': 0,
            },
            'remote': {
                'text': 4,
                'attachments': 0,
                'direct_text': 4,
                'group_text': 0,
                'direct_attachments': 0,
                'group_attachments': 0,
                'other': 0,
            },
        },
    }

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: FakeSessionService())
    monkeypatch.setattr(session_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = Session(
            session_id='session-1',
            name='Bob',
            session_type='direct',
            participant_ids=['user-1', 'user-2'],
        )
        session.extra['encryption_mode'] = 'e2ee_private'
        session.extra['session_crypto_state'] = {
            'enabled': True,
            'ready': False,
            'can_decrypt': False,
            'device_registered': True,
            'scheme': 'x25519-aesgcm-v1',
            'attachment_scheme': 'aesgcm-file+x25519-v1',
            'device_id': 'device-local-1',
            'decryption_state': 'missing_private_key',
            'recovery_action': 'reprovision_device',
            'last_failure_message_id': 'm-1',
            'target_device_id': 'device-local-1',
        }
        manager._sessions[session.session_id] = session

        result = await manager.recover_session_crypto('session-1')

        assert result == {
            'performed': True,
            'session_id': 'session-1',
            'recovery_action': 'reprovision_device',
            'device': {'device_id': 'device-local-2'},
            'message_recovery': {
                'session_id': 'session-1',
                'scanned': 3,
                'updated': 2,
                'message_ids': ['m-1', 'm-2'],
                'remote_fetched': 4,
                'remote_pages_fetched': 2,
                'recovery_stats': {
                    'cached': {
                        'text': 2,
                        'attachments': 0,
                        'direct_text': 2,
                        'group_text': 0,
                        'direct_attachments': 0,
                        'group_attachments': 0,
                        'other': 0,
                    },
                    'remote': {
                        'text': 4,
                        'attachments': 0,
                        'direct_text': 4,
                        'group_text': 0,
                        'direct_attachments': 0,
                        'group_attachments': 0,
                        'other': 0,
                    },
                },
                'attempted': True,
            },
        }
        assert fake_e2ee_service.reprovision_calls == 1
        assert fake_message_manager.recover_session_messages_calls == ['session-1']
        assert session.extra['session_crypto_state']['ready'] is True
        assert session.extra['session_crypto_state']['can_decrypt'] is True
        assert session.extra['session_crypto_state']['device_id'] == 'device-local-2'
        assert 'decryption_state' not in session.extra['session_crypto_state']
        assert 'recovery_action' not in session.extra['session_crypto_state']
        assert 'last_failure_message_id' not in session.extra['session_crypto_state']
        assert 'last_recovered_at' in session.extra['session_crypto_state']
        assert session.extra['session_crypto_state']['last_message_recovery'] == {
            'updated': 2,
            'remote_fetched': 4,
            'remote_pages_fetched': 2,
            'message_count': 2,
            'cached': {
                'text': 2,
                'attachments': 0,
                'direct_text': 2,
                'group_text': 0,
                'direct_attachments': 0,
                'group_attachments': 0,
                'other': 0,
            },
            'remote': {
                'text': 4,
                'attachments': 0,
                'direct_text': 4,
                'group_text': 0,
                'direct_attachments': 0,
                'group_attachments': 0,
                'other': 0,
            },
        }
        assert 'last_message_recovery_at' in session.extra['session_crypto_state']
        assert len(fake_db.replaced_sessions) == 1
        assert any(event == session_manager_module.SessionEvent.UPDATED for event, _ in fake_event_bus.events)

    asyncio.run(scenario())


def test_session_manager_trust_session_identities_updates_direct_session_crypto_state(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_db = FakeSessionProfileDatabase()
    fake_e2ee_service = FakeE2EEService(
        {'device_id': 'device-local-1', 'has_local_bundle': True},
        peer_identity_summary={
            'local_device_id': 'device-local-1',
            'local_fingerprint': 'LOCALFINGERPRINT1234567890',
            'local_fingerprint_short': 'LOCALFINGERP',
            'status': 'unverified',
            'device_count': 2,
            'trusted_device_count': 0,
            'unverified_device_count': 2,
            'changed_device_count': 0,
            'unverified_device_ids': ['device-bob-1', 'device-bob-2'],
            'changed_device_ids': [],
            'change_count': 0,
            'last_changed_at': '',
            'last_trusted_at': '',
            'verification_available': True,
            'primary_verification_device_id': 'device-bob-1',
            'primary_verification_fingerprint': 'REMOTEFINGERPRINT1234567890',
            'primary_verification_fingerprint_short': 'REMOTEFINGER',
            'primary_verification_code': '12345 67890 11111 22222 33333 44444 55555 66666 77777 88888 99999 00000',
            'primary_verification_code_short': '12345 67890 11111',
            'checked_at': '2026-04-06T12:00:00+00:00',
        },
    )

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: FakeSessionService())
    monkeypatch.setattr(session_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = Session(
            session_id='session-1',
            name='Bob',
            session_type='direct',
            participant_ids=['user-1', 'user-2'],
        )
        session.extra['counterpart_id'] = 'user-2'
        session.extra['encryption_mode'] = 'e2ee_private'
        session.extra['session_crypto_state'] = {
            'enabled': True,
            'ready': True,
            'can_decrypt': True,
            'device_registered': True,
            'scheme': 'x25519-aesgcm-v1',
            'attachment_scheme': 'aesgcm-file+x25519-v1',
            'identity_status': 'unverified',
            'identity_verified': False,
            'identity_device_count': 2,
            'trusted_identity_device_count': 0,
            'unverified_identity_device_count': 2,
            'changed_identity_device_count': 0,
            'unverified_identity_device_ids': ['device-bob-1', 'device-bob-2'],
            'changed_identity_device_ids': [],
            'identity_checked_at': '2026-04-06T12:00:00+00:00',
            'identity_change_count': 0,
            'identity_last_changed_at': '',
            'identity_last_trusted_at': '',
            'device_id': 'device-local-1',
        }
        manager._sessions[session.session_id] = session

        result = await manager.trust_session_identities('session-1')

        assert result['performed'] is True
        assert result['user_id'] == 'user-2'
        assert result['previous_identity_status'] == 'unverified'
        assert result['alert_cleared'] is True
        assert fake_e2ee_service.trust_peer_identity_calls == ['user-2']
        assert session.extra['session_crypto_state']['identity_status'] == 'verified'
        assert session.extra['session_crypto_state']['identity_verified'] is True
        assert session.extra['session_crypto_state']['trusted_identity_device_count'] == 2
        assert session.extra['session_crypto_state']['unverified_identity_device_count'] == 0
        assert session.extra['session_crypto_state']['changed_identity_device_count'] == 0
        assert session.extra['session_crypto_state']['unverified_identity_device_ids'] == []
        assert session.extra['session_crypto_state']['changed_identity_device_ids'] == []
        assert session.extra['session_crypto_state']['identity_action_required'] is False
        assert session.extra['session_crypto_state']['identity_review_action'] == ''
        assert session.extra['session_crypto_state']['identity_review_blocking'] is False
        assert session.extra['session_crypto_state']['identity_alert_severity'] == 'info'
        assert session.extra['session_crypto_state']['identity_change_count'] == 0
        assert session.extra['session_crypto_state']['identity_last_changed_at'] == ''
        assert session.extra['session_crypto_state']['identity_last_trusted_at'] == '2026-04-06T12:00:00+00:00'
        assert session.extra['session_crypto_state']['identity_verification_available'] is True
        assert session.extra['session_crypto_state']['identity_primary_verification_device_id'] == 'device-bob-1'
        assert session.extra['session_crypto_state']['identity_primary_verification_fingerprint_short'] == 'REMOTEFINGER'
        assert session.extra['session_crypto_state']['identity_primary_verification_code_short'] == '12345 67890 11111'
        assert session.extra['session_crypto_state']['identity_local_fingerprint_short'] == 'LOCALFINGERP'
        assert len(fake_db.replaced_sessions) == 1
        assert any(event == session_manager_module.SessionEvent.UPDATED for event, _ in fake_event_bus.events)

    asyncio.run(scenario())


def test_session_manager_get_session_security_summary_returns_identity_review_headline(monkeypatch) -> None:
    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: FakeSessionService())
    monkeypatch.setattr(
        session_manager_module,
        'get_e2ee_service',
        lambda: FakeE2EEService({'device_id': 'device-local-1', 'has_local_bundle': True}),
    )
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: FakeEventBus())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: FakeSessionProfileDatabase())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = Session(
            session_id='session-1',
            name='Bob',
            session_type='direct',
            participant_ids=['user-1', 'user-2'],
        )
        session.extra['encryption_mode'] = 'e2ee_private'
        session.extra['call_capabilities'] = {'voice': True, 'video': True}
        session.extra['call_state'] = {'active': False, 'status': 'idle'}
        session.extra['session_crypto_state'] = {
            'enabled': True,
            'ready': True,
            'can_decrypt': True,
            'device_registered': True,
            'scheme': 'x25519-aesgcm-v1',
            'attachment_scheme': 'aesgcm-file+x25519-v1',
            'identity_status': 'identity_changed',
            'identity_verified': False,
            'identity_action_required': True,
            'identity_review_action': 'trust_peer_identity',
            'identity_review_blocking': True,
            'identity_alert_severity': 'critical',
            'identity_change_count': 1,
            'identity_last_changed_at': '2026-04-06T12:15:00+00:00',
            'identity_last_trusted_at': '2026-04-06T11:45:00+00:00',
            'identity_verification_available': True,
            'identity_primary_verification_device_id': 'device-bob-1',
            'identity_primary_verification_fingerprint_short': 'REMOTEFINGER',
            'identity_primary_verification_code': '12345 67890 11111 22222 33333 44444 55555 66666 77777 88888 99999 00000',
            'identity_primary_verification_code_short': '12345 67890 11111',
            'identity_local_fingerprint_short': 'LOCALFINGERP',
            'device_id': 'device-local-1',
        }
        manager._sessions[session.session_id] = session
        manager._current_session_id = 'session-1'

        summary = await manager.get_session_security_summary('session-1')
        current_summary = await manager.get_current_session_security_summary()

        assert summary == {
            'session_id': 'session-1',
            'encryption_mode': 'e2ee_private',
            'uses_e2ee': True,
            'crypto_ready': True,
            'device_registered': True,
            'identity_status': 'identity_changed',
            'identity_action_required': True,
            'identity_review_action': 'trust_peer_identity',
            'identity_review_blocking': True,
            'identity_alert_severity': 'critical',
            'identity_change_count': 1,
            'identity_last_changed_at': '2026-04-06T12:15:00+00:00',
            'identity_last_trusted_at': '2026-04-06T11:45:00+00:00',
            'identity_verification_available': True,
            'identity_primary_verification_device_id': 'device-bob-1',
            'identity_primary_verification_fingerprint_short': 'REMOTEFINGER',
            'identity_primary_verification_code': '12345 67890 11111 22222 33333 44444 55555 66666 77777 88888 99999 00000',
            'identity_primary_verification_code_short': '12345 67890 11111',
            'identity_local_fingerprint_short': 'LOCALFINGERP',
            'decryption_state': '',
            'recovery_action': '',
            'supports_call': True,
            'call_active': False,
            'call_status': 'idle',
            'headline': 'identity_review_required',
            'recommended_action': 'trust_peer_identity',
            'actions': [
                {
                    'id': 'trust_peer_identity',
                    'kind': 'identity_review',
                    'label': 'Trust peer identity',
                    'title': 'Trust peer identity',
                    'description': 'Confirm the peer device identity before sending more encrypted messages.',
                    'blocking': True,
                    'primary': True,
                    'available': True,
                }
            ],
        }
        assert current_summary == summary

    asyncio.run(scenario())


def test_session_manager_get_session_identity_verification_returns_peer_snapshot(monkeypatch) -> None:
    fake_e2ee_service = FakeE2EEService(
        {'device_id': 'device-local-1', 'has_local_bundle': True},
        peer_identity_summary={
            'local_device_id': 'device-local-1',
            'local_fingerprint': 'LOCALFINGERPRINT1234567890',
            'local_fingerprint_short': 'LOCALFINGERP',
            'status': 'unverified',
            'device_count': 1,
            'trusted_device_count': 0,
            'unverified_device_count': 1,
            'changed_device_count': 0,
            'unverified_device_ids': ['device-bob-1'],
            'changed_device_ids': [],
            'change_count': 0,
            'last_changed_at': '',
            'last_trusted_at': '',
            'verification_available': True,
            'primary_verification_device_id': 'device-bob-1',
            'primary_verification_fingerprint': 'REMOTEFINGERPRINT1234567890',
            'primary_verification_fingerprint_short': 'REMOTEFINGER',
            'primary_verification_code': '12345 67890 11111 22222 33333 44444 55555 66666 77777 88888 99999 00000',
            'primary_verification_code_short': '12345 67890 11111',
            'checked_at': '2026-04-06T12:00:00+00:00',
        },
    )

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: FakeSessionService())
    monkeypatch.setattr(session_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: FakeEventBus())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: FakeSessionProfileDatabase())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = Session(
            session_id='session-verify-1',
            name='Bob',
            session_type='direct',
            participant_ids=['user-1', 'user-2'],
        )
        session.extra['counterpart_id'] = 'user-2'
        session.extra['encryption_mode'] = 'e2ee_private'
        session.extra['session_crypto_state'] = {
            'enabled': True,
            'ready': True,
            'can_decrypt': True,
            'device_registered': True,
            'scheme': 'x25519-aesgcm-v1',
            'attachment_scheme': 'aesgcm-file+x25519-v1',
            'identity_status': 'unverified',
            'identity_action_required': True,
            'identity_review_action': 'trust_peer_identity',
            'identity_review_blocking': False,
            'identity_alert_severity': 'warning',
        }
        manager._sessions[session.session_id] = session
        manager._current_session_id = session.session_id

        verification = await manager.get_session_identity_verification(session.session_id)
        current_verification = await manager.get_current_session_identity_verification()

        assert fake_e2ee_service.peer_identity_calls == ['user-2', 'user-2']
        assert verification['session_id'] == 'session-verify-1'
        assert verification['user_id'] == 'user-2'
        assert verification['available'] is True
        assert verification['verification']['primary_verification_device_id'] == 'device-bob-1'
        assert verification['verification']['primary_verification_code_short'] == '12345 67890 11111'
        assert verification['security_summary']['headline'] == 'identity_unverified'
        assert current_verification == verification

    asyncio.run(scenario())


def test_session_manager_get_session_identity_review_details_builds_timeline(monkeypatch) -> None:
    fake_e2ee_service = FakeE2EEService(
        {'device_id': 'device-local-1', 'has_local_bundle': True},
        peer_identity_summary={
            'local_device_id': 'device-local-1',
            'local_fingerprint': 'LOCALFINGERPRINT1234567890',
            'local_fingerprint_short': 'LOCALFINGERP',
            'status': 'identity_changed',
            'device_count': 1,
            'trusted_device_count': 0,
            'unverified_device_count': 0,
            'changed_device_count': 1,
            'unverified_device_ids': [],
            'changed_device_ids': ['device-bob-1'],
            'change_count': 2,
            'last_changed_at': '2026-04-06T12:15:00+00:00',
            'last_trusted_at': '2026-04-05T12:00:00+00:00',
            'verification_available': True,
            'primary_verification_device_id': 'device-bob-1',
            'primary_verification_fingerprint': 'REMOTEFINGERPRINT1234567890',
            'primary_verification_fingerprint_short': 'REMOTEFINGER',
            'primary_verification_code': '12345 67890 11111 22222 33333 44444 55555 66666 77777 88888 99999 00000',
            'primary_verification_code_short': '12345 67890 11111',
            'checked_at': '2026-04-06T12:30:00+00:00',
            'devices': [
                {
                    'device_id': 'device-bob-1',
                    'device_name': 'Bob Desktop',
                    'fingerprint': 'REMOTEFINGERPRINT1234567890',
                    'fingerprint_short': 'REMOTEFINGER',
                    'verification_code': '12345 67890 11111 22222 33333 44444 55555 66666 77777 88888 99999 00000',
                    'verification_code_short': '12345 67890 11111',
                    'trust_status': 'identity_changed',
                    'first_seen_at': '2026-04-01T12:00:00+00:00',
                    'last_seen_at': '2026-04-06T12:30:00+00:00',
                    'last_changed_at': '2026-04-06T12:15:00+00:00',
                    'last_trusted_at': '2026-04-05T12:00:00+00:00',
                    'change_count': 2,
                }
            ],
        },
    )

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: FakeSessionService())
    monkeypatch.setattr(session_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: FakeEventBus())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: FakeSessionProfileDatabase())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = Session(
            session_id='session-review-1',
            name='Bob',
            session_type='direct',
            participant_ids=['user-1', 'user-2'],
        )
        session.extra['counterpart_id'] = 'user-2'
        session.extra['encryption_mode'] = 'e2ee_private'
        session.extra['session_crypto_state'] = {
            'enabled': True,
            'ready': True,
            'can_decrypt': True,
            'device_registered': True,
            'scheme': 'x25519-aesgcm-v1',
            'attachment_scheme': 'aesgcm-file+x25519-v1',
            'identity_status': 'identity_changed',
            'identity_action_required': True,
            'identity_review_action': 'trust_peer_identity',
            'identity_review_blocking': True,
            'identity_alert_severity': 'critical',
        }
        manager._sessions[session.session_id] = session
        manager._current_session_id = session.session_id

        details = await manager.get_session_identity_review_details(session.session_id)
        current_details = await manager.get_current_session_identity_review_details()

        assert details['session_id'] == 'session-review-1'
        assert details['user_id'] == 'user-2'
        assert details['available'] is True
        assert details['blocking'] is True
        assert details['recommended_action'] == 'trust_peer_identity'
        assert details['primary_device']['device_id'] == 'device-bob-1'
        assert details['primary_device']['change_count'] == 2
        assert details['timeline'] == [
            {'kind': 'first_seen', 'at': '2026-04-01T12:00:00+00:00', 'label': 'First observed on this device'},
            {'kind': 'identity_changed', 'at': '2026-04-06T12:15:00+00:00', 'label': 'Peer identity changed'},
            {'kind': 'trusted', 'at': '2026-04-05T12:00:00+00:00', 'label': 'Peer identity trusted locally'},
            {'kind': 'last_checked', 'at': '2026-04-06T12:30:00+00:00', 'label': 'Latest identity check'},
        ]
        assert current_details == details

    asyncio.run(scenario())


def test_session_manager_get_session_security_diagnostics_unifies_summary_and_review(monkeypatch) -> None:
    fake_e2ee_service = FakeE2EEService(
        {'device_id': 'device-local-1', 'has_local_bundle': True},
        peer_identity_summary={
            'local_device_id': 'device-local-1',
            'local_fingerprint': 'LOCALFINGERPRINT1234567890',
            'local_fingerprint_short': 'LOCALFINGERP',
            'status': 'identity_changed',
            'device_count': 1,
            'trusted_device_count': 0,
            'unverified_device_count': 0,
            'changed_device_count': 1,
            'unverified_device_ids': [],
            'changed_device_ids': ['device-bob-1'],
            'change_count': 2,
            'last_changed_at': '2026-04-06T12:15:00+00:00',
            'last_trusted_at': '2026-04-05T12:00:00+00:00',
            'verification_available': True,
            'primary_verification_device_id': 'device-bob-1',
            'primary_verification_fingerprint': 'REMOTEFINGERPRINT1234567890',
            'primary_verification_fingerprint_short': 'REMOTEFINGER',
            'primary_verification_code': '12345 67890 11111 22222 33333 44444 55555 66666 77777 88888 99999 00000',
            'primary_verification_code_short': '12345 67890 11111',
            'checked_at': '2026-04-06T12:30:00+00:00',
            'devices': [
                {
                    'device_id': 'device-bob-1',
                    'device_name': 'Bob Desktop',
                    'fingerprint': 'REMOTEFINGERPRINT1234567890',
                    'fingerprint_short': 'REMOTEFINGER',
                    'verification_code': '12345 67890 11111 22222 33333 44444 55555 66666 77777 88888 99999 00000',
                    'verification_code_short': '12345 67890 11111',
                    'trust_status': 'identity_changed',
                    'first_seen_at': '2026-04-01T12:00:00+00:00',
                    'last_seen_at': '2026-04-06T12:30:00+00:00',
                    'last_changed_at': '2026-04-06T12:15:00+00:00',
                    'last_trusted_at': '2026-04-05T12:00:00+00:00',
                    'change_count': 2,
                }
            ],
        },
    )

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: FakeSessionService())
    monkeypatch.setattr(session_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: FakeEventBus())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: FakeSessionProfileDatabase())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = Session(
            session_id='session-diagnostics-1',
            name='Bob',
            session_type='direct',
            participant_ids=['user-1', 'user-2'],
        )
        session.extra['counterpart_id'] = 'user-2'
        session.extra['encryption_mode'] = 'e2ee_private'
        session.extra['session_crypto_state'] = {
            'enabled': True,
            'ready': True,
            'can_decrypt': True,
            'device_registered': True,
            'scheme': 'x25519-aesgcm-v1',
            'attachment_scheme': 'aesgcm-file+x25519-v1',
            'identity_status': 'identity_changed',
            'identity_action_required': True,
            'identity_review_action': 'trust_peer_identity',
            'identity_review_blocking': True,
            'identity_alert_severity': 'critical',
            'identity_change_count': 2,
            'identity_last_changed_at': '2026-04-06T12:15:00+00:00',
            'identity_last_trusted_at': '2026-04-05T12:00:00+00:00',
            'identity_verification_available': True,
            'identity_primary_verification_device_id': 'device-bob-1',
            'identity_primary_verification_fingerprint_short': 'REMOTEFINGER',
            'identity_primary_verification_code': '12345 67890 11111 22222 33333 44444 55555 66666 77777 88888 99999 00000',
            'identity_primary_verification_code_short': '12345 67890 11111',
            'identity_local_fingerprint_short': 'LOCALFINGERP',
        }
        manager._sessions[session.session_id] = session
        manager._current_session_id = session.session_id

        diagnostics = await manager.get_session_security_diagnostics(session.session_id)
        current_diagnostics = await manager.get_current_session_security_diagnostics()

        assert diagnostics['session_id'] == 'session-diagnostics-1'
        assert diagnostics['headline'] == 'identity_review_required'
        assert diagnostics['recommended_action'] == 'trust_peer_identity'
        assert diagnostics['security_summary']['headline'] == 'identity_review_required'
        assert diagnostics['identity_review']['primary_device']['device_id'] == 'device-bob-1'
        assert diagnostics['actions'] == diagnostics['security_summary']['actions']
        assert current_diagnostics == diagnostics

    asyncio.run(scenario())


def test_session_manager_execute_session_security_action_routes_actions(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_db = FakeSessionProfileDatabase()
    fake_e2ee_service = FakeE2EEService(
        {'device_id': 'device-local-1', 'has_local_bundle': True},
        peer_identity_summary={
            'status': 'identity_changed',
            'device_count': 1,
            'trusted_device_count': 0,
            'unverified_device_count': 0,
            'changed_device_count': 1,
            'unverified_device_ids': [],
            'changed_device_ids': ['device-bob-1'],
            'change_count': 1,
            'last_changed_at': '2026-04-06T12:15:00+00:00',
            'last_trusted_at': '2026-04-06T11:45:00+00:00',
            'checked_at': '2026-04-06T12:00:00+00:00',
        },
    )

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: FakeSessionService())
    monkeypatch.setattr(session_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = Session(
            session_id='session-1',
            name='Bob',
            session_type='direct',
            participant_ids=['user-1', 'user-2'],
        )
        session.extra['counterpart_id'] = 'user-2'
        session.extra['encryption_mode'] = 'e2ee_private'
        session.extra['session_crypto_state'] = {
            'enabled': True,
            'ready': True,
            'can_decrypt': True,
            'device_registered': True,
            'scheme': 'x25519-aesgcm-v1',
            'attachment_scheme': 'aesgcm-file+x25519-v1',
            'identity_status': 'identity_changed',
            'identity_verified': False,
            'identity_action_required': True,
            'identity_review_action': 'trust_peer_identity',
            'identity_review_blocking': True,
            'identity_alert_severity': 'critical',
            'device_id': 'device-local-1',
        }
        manager._sessions[session.session_id] = session
        manager._current_session_id = 'session-1'

        trusted = await manager.execute_session_security_action('session-1', 'trust_peer_identity')
        unavailable = await manager.execute_session_security_action('session-1', 'reprovision_device')
        unavailable_summary = dict(unavailable.get('security_summary') or {})

        session.extra['session_crypto_state'] = {
            'enabled': True,
            'ready': False,
            'can_decrypt': False,
            'device_registered': True,
            'scheme': 'x25519-aesgcm-v1',
            'attachment_scheme': 'aesgcm-file+x25519-v1',
            'decryption_state': 'not_for_current_device',
            'recovery_action': 'switch_device',
            'target_device_id': 'device-bob-2',
            'device_id': 'device-local-1',
        }
        switched = await manager.execute_current_session_security_action('switch_device')

        assert trusted['performed'] is True
        assert trusted['action_id'] == 'trust_peer_identity'
        assert trusted['security_summary']['headline'] == 'secure'
        assert unavailable == {
            'performed': False,
            'session_id': 'session-1',
            'action_id': 'reprovision_device',
            'reason': 'action_not_available',
            'explanation': {
                'code': 'action_not_available',
                'message': 'The requested security action is not currently available for this session.',
                'available_action_ids': [],
                'headline': 'secure',
            },
            'security_summary': unavailable_summary,
        }
        assert switched == {
            'performed': False,
            'session_id': 'session-1',
            'action_id': 'switch_device',
            'reason': 'switch_device_required',
            'target_device_id': 'device-bob-2',
            'explanation': {
                'code': 'switch_device_required',
                'message': 'This encrypted content is addressed to a different device and cannot be recovered on the current device.',
            },
            'external_requirement': {
                'kind': 'switch_device',
                'target_device_id': 'device-bob-2',
                'blocking': True,
            },
            'security_summary': session.security_summary(),
        }

    asyncio.run(scenario())


def test_session_security_summary_exposes_recovery_actions() -> None:
    session = Session(
        session_id='session-2',
        name='Bob',
        session_type='direct',
        participant_ids=['user-1', 'user-2'],
    )
    session.extra['encryption_mode'] = 'e2ee_private'
    session.extra['session_crypto_state'] = {
        'enabled': True,
        'ready': False,
        'can_decrypt': False,
        'device_registered': True,
        'scheme': 'x25519-aesgcm-v1',
        'attachment_scheme': 'aesgcm-file+x25519-v1',
        'decryption_state': 'missing_private_key',
        'recovery_action': 'reprovision_device',
    }

    summary = session.security_summary()

    assert summary['headline'] == 'decryption_recovery_required'
    assert summary['recommended_action'] == 'reprovision_device'
    assert summary['actions'] == [
        {
            'id': 'reprovision_device',
            'kind': 'crypto_recovery',
            'label': 'reprovision device',
            'title': 'reprovision device',
            'description': 'Run the recommended encrypted-session recovery flow on this device.',
            'blocking': False,
            'primary': True,
            'available': True,
        }
    ]


def test_session_security_summary_exposes_switch_device_external_requirement() -> None:
    session = Session(
        session_id='session-3',
        name='Bob',
        session_type='direct',
        participant_ids=['user-1', 'user-2'],
    )
    session.extra['encryption_mode'] = 'e2ee_private'
    session.extra['session_crypto_state'] = {
        'enabled': True,
        'ready': False,
        'can_decrypt': False,
        'device_registered': True,
        'scheme': 'x25519-aesgcm-v1',
        'attachment_scheme': 'aesgcm-file+x25519-v1',
        'decryption_state': 'not_for_current_device',
        'recovery_action': 'switch_device',
        'target_device_id': 'device-bob-2',
    }

    summary = session.security_summary()

    assert summary['headline'] == 'decryption_recovery_required'
    assert summary['recommended_action'] == 'switch_device'
    assert summary['actions'] == [
        {
            'id': 'switch_device',
            'kind': 'crypto_recovery',
            'label': 'Switch device',
            'title': 'Switch device',
            'description': 'Open the device that owns this encrypted history to continue recovery.',
            'blocking': True,
            'primary': True,
            'available': False,
            'external_requirement': {
                'kind': 'switch_device',
                'target_device_id': 'device-bob-2',
                'blocking': True,
            },
        }
    ]


def test_session_manager_history_sync_reconciles_authoritative_unread_counts(monkeypatch) -> None:
    fake_session_service = FakeSessionService()
    fake_session_service.unread_payload = [{'session_id': 'session-1', 'unread': 4}]
    fake_event_bus = FakeEventBus()
    fake_db = FakeSessionUnreadDatabase()

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: fake_session_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = Session(
            session_id='session-1',
            name='Core Team',
            session_type='group',
            unread_count=1,
            created_at=datetime(2026, 3, 27, 18, 0, 0),
            updated_at=datetime(2026, 3, 27, 18, 0, 0),
            last_message_time=datetime(2026, 3, 27, 18, 0, 0),
        )
        manager._sessions[session.session_id] = session

        await manager._on_history_synced({'count': 0, 'messages': []})

        assert fake_session_service.fetch_unread_counts_calls == 1
        assert session.unread_count == 4
        assert fake_db.updated_unread == [('session-1', 4)]
        assert (
            session_manager_module.SessionEvent.UNREAD_CHANGED,
            {'session_id': 'session-1', 'unread_count': 4},
        ) in fake_event_bus.events

    asyncio.run(scenario())



def test_session_manager_ensure_direct_session_uses_session_service(monkeypatch) -> None:
    fake_session_service = FakeSessionService()

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: fake_session_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: FakeEventBus())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: FakeSessionStateDatabase())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = await manager.ensure_direct_session('bob', display_name='Bob')

        assert fake_session_service.create_direct_session_calls == ['bob']
        assert session is not None
        assert session.session_id == 'session-direct-1'

    asyncio.run(scenario())




class HiddenSessionRuntimeDatabase:
    def __init__(self) -> None:
        self.is_connected = True
        self.saved_sessions = []
        self.saved_batches = []
        self.updated_unread: list[tuple[str, int]] = []
        self.app_state = {
            'auth.user_profile': json.dumps({'id': 'alice', 'username': 'alice', 'nickname': 'Alice'}),
        }

    async def get_app_state(self, key: str):
        return self.app_state.get(key)

    async def save_session(self, session) -> None:
        self.saved_sessions.append(session)

    async def save_sessions_batch(self, sessions) -> None:
        self.saved_batches.append(list(sessions))

    async def update_session_unread(self, session_id: str, unread_count: int) -> None:
        self.updated_unread.append((session_id, unread_count))

    async def set_app_state(self, key: str, value: str) -> None:
        self.app_state[key] = value

    async def delete_app_state(self, key: str) -> None:
        self.app_state.pop(key, None)


def test_session_manager_ensure_remote_session_does_not_revive_hidden_session(monkeypatch) -> None:
    fake_session_service = FakeSessionService()
    fake_event_bus = FakeEventBus()
    fake_db = HiddenSessionRuntimeDatabase()

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: fake_session_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        manager._hidden_sessions['session-1'] = datetime(2026, 3, 27, 18, 0, 0).timestamp()

        session = await manager.ensure_remote_session('session-1', fallback_name='Core Team')

        assert session is None
        assert manager._sessions == {}
        assert fake_db.saved_sessions == []
        assert fake_event_bus.events == []

    asyncio.run(scenario())


def test_session_manager_ensure_direct_session_does_not_revive_hidden_session(monkeypatch) -> None:
    fake_session_service = FakeSessionService()
    fake_event_bus = FakeEventBus()
    fake_db = HiddenSessionRuntimeDatabase()

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: fake_session_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        manager._hidden_sessions['session-direct-1'] = datetime(2026, 3, 27, 18, 0, 0).timestamp()

        session = await manager.ensure_direct_session('bob', display_name='Bob')

        assert session is None
        assert manager._sessions == {}
        assert fake_db.saved_sessions == []
        assert fake_event_bus.events == []

    asyncio.run(scenario())


def test_session_manager_history_sync_does_not_restore_hidden_session_from_old_messages(monkeypatch) -> None:
    fake_session_service = FakeSessionService()
    fake_session_service.session_payload = {
        **fake_session_service.session_payload,
        'created_at': '2026-03-27T17:30:00',
        'updated_at': '2026-03-27T17:30:00',
        'last_message_time': '2026-03-27T17:30:00',
    }
    fake_event_bus = FakeEventBus()
    fake_db = HiddenSessionRuntimeDatabase()

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: fake_session_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        hidden_at = datetime(2026, 3, 27, 18, 0, 0)
        manager._hidden_sessions['session-1'] = hidden_at.timestamp()

        await manager._on_history_synced({
            'messages': [
                ChatMessage(
                    message_id='msg-old-1',
                    session_id='session-1',
                    sender_id='bob',
                    content='older message',
                    timestamp=hidden_at - timedelta(minutes=5),
                    is_self=False,
                )
            ]
        })

        assert 'session-1' not in manager._sessions
        assert manager._hidden_sessions['session-1'] == hidden_at.timestamp()
        assert fake_db.saved_sessions == []
        assert fake_db.saved_batches == []
        assert fake_event_bus.events == []

    asyncio.run(scenario())


def test_session_manager_live_message_restores_hidden_session_only_after_new_activity(monkeypatch) -> None:
    fake_session_service = FakeSessionService()
    fake_session_service.session_payload = {
        **fake_session_service.session_payload,
        'created_at': '2026-03-27T17:30:00',
        'updated_at': '2026-03-27T17:30:00',
        'last_message_time': '2026-03-27T17:30:00',
    }
    fake_event_bus = FakeEventBus()
    fake_db = HiddenSessionRuntimeDatabase()

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: fake_session_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        hidden_at = datetime(2026, 3, 27, 18, 0, 0)
        manager._hidden_sessions['session-1'] = hidden_at.timestamp()

        await manager._on_message_received({
            'message': ChatMessage(
                message_id='msg-new-1',
                session_id='session-1',
                sender_id='bob',
                content='new message',
                timestamp=hidden_at + timedelta(minutes=5),
                is_self=False,
            )
        })

        session = manager._sessions.get('session-1')
        assert session is not None
        assert session.unread_count == 1
        assert 'session-1' not in manager._hidden_sessions
        assert fake_db.updated_unread == [('session-1', 1)]
        assert any(event == session_manager_module.SessionEvent.ADDED for event, _ in fake_event_bus.events)

    asyncio.run(scenario())


def test_session_manager_refresh_session_preview_preserves_last_message_time_without_local_message(monkeypatch) -> None:
    fake_session_service = FakeSessionService()
    fake_event_bus = FakeEventBus()
    saved_sessions = []

    class PreviewDatabase:
        is_connected = True

        async def get_last_message(self, session_id: str):
            return None

        async def save_session(self, session):
            saved_sessions.append(session)

    fake_db = PreviewDatabase()

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: fake_session_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        preserved_time = datetime(2026, 3, 20, 8, 30, 0)
        session = Session(
            session_id='session-1',
            name='Core Team',
            last_message='hello',
            last_message_time=preserved_time,
            created_at=datetime(2026, 3, 18, 9, 0, 0),
            updated_at=datetime(2026, 3, 26, 23, 59, 0),
            extra={},
        )
        manager._sessions[session.session_id] = session

        await manager.refresh_session_preview(session.session_id)

        assert session.last_message_time == preserved_time
        assert saved_sessions[-1].last_message_time == preserved_time

    asyncio.run(scenario())


def test_session_manager_hidden_current_session_still_increments_unread(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: FakeSessionService())
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: FakeSessionStateDatabase())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = Session(
            session_id='session-1',
            name='Bob',
            last_message='',
            last_message_time=datetime(2026, 3, 27, 18, 0, 0),
            created_at=datetime(2026, 3, 27, 18, 0, 0),
            updated_at=datetime(2026, 3, 27, 18, 0, 0),
            extra={},
        )
        manager._sessions[session.session_id] = session

        await manager.select_session(session.session_id)
        await manager.set_current_session_active(False)
        await manager._on_message_received({
            'message': ChatMessage(
                message_id='msg-1',
                session_id='session-1',
                sender_id='user-2',
                content='hello',
                timestamp=datetime(2026, 3, 27, 18, 4, 0),
                is_self=False,
            )
        })

        assert session.unread_count == 1

    asyncio.run(scenario())


def test_session_manager_activating_selected_session_clears_unread(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: FakeSessionService())
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: FakeSessionStateDatabase())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = Session(
            session_id='session-1',
            name='Bob',
            last_message='',
            last_message_time=datetime(2026, 3, 27, 18, 0, 0),
            created_at=datetime(2026, 3, 27, 18, 0, 0),
            updated_at=datetime(2026, 3, 27, 18, 0, 0),
            extra={},
        )
        session.unread_count = 2
        manager._sessions[session.session_id] = session

        await manager.select_session(session.session_id)
        await manager.set_current_session_active(True)

        assert session.unread_count == 0
        assert (
            session_manager_module.SessionEvent.UNREAD_CHANGED,
            {'session_id': 'session-1', 'unread_count': 0},
        ) in fake_event_bus.events

    asyncio.run(scenario())


def test_normalize_profile_gender_preserves_supported_values() -> None:
    assert profile_fields_module.normalize_profile_gender('female') == 'female'
    assert profile_fields_module.normalize_profile_gender('male') == 'male'
    assert profile_fields_module.normalize_profile_gender('non_binary') == 'non_binary'
    assert profile_fields_module.normalize_profile_gender('OTHER') == 'other'
    assert profile_fields_module.normalize_profile_gender('  ') == ''
    assert profile_fields_module.normalize_profile_gender('woman') == ''


def test_profile_avatar_seed_prefers_stable_identity_fields() -> None:
    original = avatar_utils_module.profile_avatar_seed(
        user_id='user-1',
        username='alice',
        display_name='Alice',
    )
    renamed = avatar_utils_module.profile_avatar_seed(
        user_id='user-1',
        username='alice',
        display_name='Alice Cooper',
    )

    assert original == renamed


def test_resolve_avatar_source_keeps_remote_url() -> None:
    remote_avatar = 'https://cdn.example.com/avatar.png'

    assert avatar_utils_module.resolve_avatar_source(
        remote_avatar,
        gender='female',
        seed='user-1',
    ) == remote_avatar


def test_app_icon_paths_point_to_generated_svg_assets() -> None:
    add_path = Path(app_icons_module.AppIcon.ADD.path())
    people_path = Path(app_icons_module.AppIcon.PEOPLE.path())

    assert add_path.suffix == '.svg'
    assert people_path.suffix == '.svg'
    assert add_path.is_file()
    assert people_path.is_file()
    assert 'client/resources/icons/iconfont_51777' in add_path.as_posix()
    assert 'client/resources/icons/iconfont_51777' in people_path.as_posix()


def test_app_icon_render_scale_is_applied_at_runtime() -> None:
    original_scale = app_icons_module.get_icon_render_scale()

    try:
        app_icons_module.set_icon_render_scale(1.0)
        raw_path = Path(app_icons_module.AppIcon.ADD.path())
        assert 'client/resources/icons/iconfont_51777' in raw_path.as_posix()
        assert raw_path.name == 'add.svg'

        app_icons_module.set_icon_render_scale(1.28)
        scaled_svg = app_icons_module._render_svg_markup('add', fill='#101010')
        assert 'scale(1.28)' in scaled_svg
        assert '#101010' in scaled_svg
        assert 'currentColor' not in scaled_svg
    finally:
        app_icons_module.set_icon_render_scale(original_scale)


def test_collection_icon_library_is_downloaded_and_addressable() -> None:
    available_names = app_icons_module.available_collection_icon_names()
    group_path = Path(app_icons_module.CollectionIcon('group').path())

    assert len(available_names) >= 1504
    assert 'group' in available_names
    assert group_path.suffix == '.svg'
    assert group_path.is_file()
    assert 'client/resources/icons/iconfont_51777' in group_path.as_posix()


def test_app_icon_default_theme_colors_match_fluent_icon_palette() -> None:
    light_svg = app_icons_module._render_svg_markup('add', theme=app_icons_module.Theme.LIGHT)
    dark_svg = app_icons_module._render_svg_markup('add', theme=app_icons_module.Theme.DARK)
    explicit_fill_svg = app_icons_module._render_svg_markup('add', fill='#202020')

    assert '#797979' in light_svg
    assert '#929292' in dark_svg
    assert '#202020' in explicit_fill_svg
    assert 'opacity=' not in light_svg
    assert 'opacity=' not in dark_svg
    assert 'opacity=' not in explicit_fill_svg


def test_message_actions_offer_recall_before_two_minute_limit() -> None:
    now = datetime(2026, 3, 27, 14, 0, 0)
    message = ChatMessage(
        message_id='msg-1',
        session_id='session-1',
        sender_id='user-1',
        content='hello',
        status=MessageStatus.SENT,
        timestamp=now - timedelta(seconds=119),
        is_self=True,
    )

    assert message_actions_module.should_offer_recall(message, now=now) is True
    assert message_actions_module.should_offer_delete(message, now=now) is False


def test_message_actions_switch_self_message_to_delete_after_recall_window() -> None:
    now = datetime(2026, 3, 27, 14, 0, 0)
    message = ChatMessage(
        message_id='msg-2',
        session_id='session-1',
        sender_id='user-1',
        content='hello',
        status=MessageStatus.DELIVERED,
        timestamp=now - timedelta(seconds=121),
        is_self=True,
    )

    assert message_actions_module.should_offer_recall(message, now=now) is False
    assert message_actions_module.should_offer_delete(message, now=now) is True


def test_format_session_timestamp_uses_yesterday_with_time(monkeypatch) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 3, 27, 14, 0, 0)

    monkeypatch.setattr(i18n_module, 'datetime', FrozenDateTime)
    monkeypatch.setattr(i18n_module, '_localized_time_text', lambda moment: f'{moment.hour:02d}:{moment.minute:02d}')
    from client.core.config import Language
    i18n_module.initialize_i18n(Language.ENGLISH)

    assert i18n_module.format_session_timestamp(datetime(2026, 3, 26, 9, 30, 0)) == 'Yesterday 09:30'


def test_format_session_timestamp_uses_full_year_date_for_older_year(monkeypatch) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 3, 27, 14, 0, 0)

    monkeypatch.setattr(i18n_module, 'datetime', FrozenDateTime)
    monkeypatch.setattr(i18n_module, '_localized_time_text', lambda moment: f'{moment.hour:02d}:{moment.minute:02d}')
    from client.core.config import Language
    i18n_module.initialize_i18n(Language.ENGLISH)

    assert i18n_module.format_session_timestamp(datetime(2025, 12, 31, 9, 30, 0)) == '2025/12/31'


def test_coerce_local_datetime_keeps_naive_iso_wall_clock_time() -> None:
    from client.core.datetime_utils import coerce_local_datetime

    parsed = coerce_local_datetime('2026-03-27T18:04:00')

    assert parsed == datetime(2026, 3, 27, 18, 4, 0)


def test_sound_manager_loads_manifest_and_plays_registered_sound(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    created_effects = []

    class DummySoundEffect:
        def __init__(self, source_path: str, volume: float) -> None:
            self.source_path = source_path
            self.volume = volume
            self.play_calls = 0
            self.stop_calls = 0
            self._playing = False

        def setVolume(self, value: float) -> None:
            self.volume = value

        def isPlaying(self) -> bool:
            return self._playing

        def play(self) -> None:
            self.play_calls += 1
            self._playing = True

        def stop(self) -> None:
            self.stop_calls += 1
            self._playing = False

    def build_effect(path: Path, volume: float, *, loop: bool = False):
        effect = DummySoundEffect(str(path), volume)
        effect.loop = loop
        created_effects.append(effect)
        return effect

    monkeypatch.setattr(sound_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(sound_manager_module, '_create_sound_effect', build_effect)

    async def scenario() -> None:
        manager = sound_manager_module.SoundManager()
        await manager.initialize()

        assert sound_manager_module.AppSound.MESSAGE_INCOMING.value in manager.available_sounds()
        assert sound_manager_module.AppSound.CALL_OUTGOING_RING.value in manager.available_sounds()
        assert manager.play(sound_manager_module.AppSound.MESSAGE_INCOMING) is True
        assert len(created_effects) >= 1
        assert any(effect.play_calls == 1 for effect in created_effects)
        assert any(
            'client\\resources\\audio\\notifications\\windows_notify_messaging_' in effect.source_path
            for effect in created_effects
        )

        await manager.close()

    asyncio.run(scenario())


def test_sound_manager_handles_incoming_message_event(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    played = []

    monkeypatch.setattr(sound_manager_module, 'get_event_bus', lambda: fake_event_bus)

    async def scenario() -> None:
        manager = sound_manager_module.SoundManager()
        monkeypatch.setattr(manager, 'play', lambda sound_id, force=False: played.append(sound_id) or True)
        await manager.initialize()
        await manager._on_message_received({'message': object()})

        assert played == [sound_manager_module.AppSound.MESSAGE_INCOMING]

        await manager.close()

    asyncio.run(scenario())






def test_file_service_reset_profile_avatar_uses_dedicated_endpoint(monkeypatch) -> None:
    class FakeUploadHttpClient:
        def __init__(self) -> None:
            self.delete_calls: list[str] = []

        async def delete(self, path: str) -> dict:
            self.delete_calls.append(path)
            return {'id': 'user-1', 'avatar': '/uploads/default-avatar.svg', 'avatar_kind': 'default'}

    fake_http = FakeUploadHttpClient()
    monkeypatch.setattr(file_service_module, 'get_http_client', lambda: fake_http)

    async def scenario() -> None:
        service = file_service_module.FileService()
        payload = await service.reset_profile_avatar()

        assert payload['avatar_kind'] == 'default'
        assert fake_http.delete_calls == ['/users/me/avatar']

    asyncio.run(scenario())


def test_auth_controller_update_profile_can_reset_avatar(monkeypatch) -> None:
    fake_auth_service = FakeAuthService()
    fake_user_service = FakeUserService()
    fake_db = FakeDatabase()
    fake_message_manager = FakeMessageManager()
    fake_chat_controller = FakeChatControllerContext()
    fake_file_service = FakeFileService({'id': 'user-1', 'avatar': '/uploads/default-avatar.svg', 'avatar_kind': 'default'})

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        result = await controller.update_profile(reset_avatar=True)
        user = result.user

        assert fake_file_service.avatar_resets == 1
        assert fake_file_service.avatar_uploads == []
        assert fake_user_service.update_calls == []
        assert user['avatar_kind'] == 'default'
        assert result.session_snapshot is not None
        assert result.session_snapshot.authoritative is True
        assert result.session_snapshot.unread_synchronized is True
        assert fake_chat_controller.refresh_calls == 1
        assert fake_db.app_state[controller.USER_ID_KEY] == 'user-1'

    asyncio.run(scenario())









def test_session_manager_profile_update_refreshes_direct_counterpart_presentation(monkeypatch) -> None:
    class FakeSessionDb:
        is_connected = True

        def __init__(self) -> None:
            self.saved_sessions: list[Session] = []

        async def save_session(self, session: Session) -> None:
            self.saved_sessions.append(session)

        async def get_app_state(self, key: str):
            if key == 'auth.user_profile':
                return json.dumps({'id': 'alice', 'username': 'alice', 'nickname': 'Alice'})
            if key == 'auth.user_id':
                return 'alice'
            return None

    fake_db = FakeSessionDb()
    fake_event_bus = FakeEventBus()

    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = Session(
            session_id='session-1',
            name='Bob',
            session_type='direct',
            participant_ids=['alice', 'bob'],
            avatar=None,
            extra={
                'counterpart_id': 'bob',
                'counterpart_username': 'bob',
                'counterpart_avatar': '/uploads/bob-old.png',
                'counterpart_gender': 'male',
                'members': [
                    {'id': 'alice', 'username': 'alice', 'nickname': 'Alice', 'avatar': '/uploads/alice.png', 'gender': 'female'},
                    {'id': 'bob', 'username': 'bob', 'nickname': 'Bob', 'avatar': '/uploads/bob-old.png', 'gender': 'male'},
                ],
            },
        )
        manager._sessions[session.session_id] = session

        await manager._on_profile_updated(
            {
                'session_id': 'session-1',
                'user_id': 'bob',
                'profile': {
                    'id': 'bob',
                    'username': 'bob',
                    'nickname': 'Bobby',
                    'display_name': 'Bobby',
                    'avatar': '/uploads/bob-new.png',
                    'gender': 'male',
                },
            }
        )

        assert session.name == 'Bobby'
        assert session.extra['counterpart_avatar'] == '/uploads/bob-new.png'
        assert session.extra['members'][1]['nickname'] == 'Bobby'
        assert fake_db.saved_sessions and fake_db.saved_sessions[-1].session_id == 'session-1'
        assert any(event == session_manager_module.SessionEvent.UPDATED for event, _ in fake_event_bus.events)

    asyncio.run(scenario())


def test_contact_controller_normalize_group_record_supports_object_payloads(monkeypatch) -> None:
    fake_contact_service = FakeContactService()
    fake_user_service = FakeUserService()
    fake_auth_context = FakeAuthContext()
    fake_db = FakeDatabase()

    monkeypatch.setattr(contact_controller_module, 'get_contact_service', lambda: fake_contact_service)
    monkeypatch.setattr(contact_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(contact_controller_module, 'get_auth_controller', lambda: fake_auth_context)
    monkeypatch.setattr(contact_controller_module, 'get_database', lambda: fake_db)

    class _Payload:
        id = 'group-9'
        name = 'Ops'
        avatar = 'ops.png'
        owner_id = 'owner-9'
        session_id = 'session-group-9'
        member_count = 2
        created_at = '2026-04-03T09:00:00Z'
        extra = {'announcement': 'ready'}

    controller = contact_controller_module.ContactController()
    record = controller.normalize_group_record(_Payload())

    assert record is not None
    assert record.id == 'group-9'
    assert record.name == 'Ops'
    assert record.extra['announcement'] == 'ready'


def test_contact_controller_group_merge_helpers_preserve_extra_and_sort(monkeypatch) -> None:
    fake_contact_service = FakeContactService()
    fake_user_service = FakeUserService()
    fake_auth_context = FakeAuthContext()
    fake_db = FakeDatabase()
    fake_db.is_connected = True

    monkeypatch.setattr(contact_controller_module, 'get_contact_service', lambda: fake_contact_service)
    monkeypatch.setattr(contact_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(contact_controller_module, 'get_auth_controller', lambda: fake_auth_context)
    monkeypatch.setattr(contact_controller_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        controller = contact_controller_module.ContactController()
        existing = [
            contact_controller_module.GroupRecord(
                id='group-2',
                name='Zeta Squad',
                avatar='zeta.png',
                owner_id='owner-2',
                session_id='session-group-2',
                member_count=8,
                created_at='2026-04-01T00:00:00Z',
                extra={'id': 'group-2', 'name': 'Zeta Squad', 'group_note': 'keep me'},
            )
        ]

        updated_groups, updated_record, rebuild = controller.merge_group_record(
            existing,
            {
                'id': 'group-1',
                'name': 'Core Team',
                'avatar': 'core.png',
                'owner_id': 'owner-1',
                'session_id': 'session-group-1',
                'member_count': 3,
                'members': [{'nickname': 'Alice', 'region': 'Shenzhen'}],
            },
        )
        assert rebuild is True
        assert updated_record is not None
        assert [item.id for item in updated_groups] == ['group-1', 'group-2']

        second_groups, second_record, rebuild_again = controller.merge_group_record(
            updated_groups,
            {
                'group_id': 'group-1',
                'announcement': 'Ship tonight',
                'member_count': 4,
            },
        )
        assert rebuild_again is False
        assert second_record is not None
        assert second_record.extra['announcement'] == 'Ship tonight'
        assert second_record.member_count == 4

        final_groups, final_record = controller.apply_group_self_profile_update(
            second_groups,
            {'group_id': 'group-1', 'group_note': 'private note', 'my_group_nickname': 'lead'},
        )
        assert final_record is not None
        assert final_record.extra['group_note'] == 'private note'
        assert final_record.extra['my_group_nickname'] == 'lead'

        await controller.persist_groups_cache(final_groups)
        assert fake_db.replaced_groups[-1][0]['id'] == 'group-1'
        assert fake_db.replaced_groups[-1][0]['extra']['member_previews'] == ['Alice Shenzhen']

    asyncio.run(scenario())


def test_contact_controller_skips_cache_writes_when_auth_context_changes(monkeypatch) -> None:
    fake_contact_service = FakeContactService()
    fake_contact_service.friends_payload = [{'id': 'user-2', 'username': 'bob', 'nickname': 'Bob'}]
    fake_contact_service.groups_payload = [{'id': 'group-1', 'name': 'Core Team'}]
    fake_user_service = FakeUserService()
    fake_auth_context = FakeAuthContext()
    fake_db = FakeDatabase()
    fake_db.is_connected = True

    async def stale_fetch_friends():
        fake_auth_context.current_user = {}
        return list(fake_contact_service.friends_payload)

    async def stale_fetch_groups():
        fake_auth_context.current_user = {}
        return list(fake_contact_service.groups_payload)

    fake_contact_service.fetch_friends = stale_fetch_friends
    fake_contact_service.fetch_groups = stale_fetch_groups

    monkeypatch.setattr(contact_controller_module, 'get_contact_service', lambda: fake_contact_service)
    monkeypatch.setattr(contact_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(contact_controller_module, 'get_auth_controller', lambda: fake_auth_context)
    monkeypatch.setattr(contact_controller_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        controller = contact_controller_module.ContactController()

        try:
            await controller.load_contacts()
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError('stale contact reload must be cancelled')

        fake_auth_context.current_user = {'id': 'user-1', 'username': 'alice'}
        try:
            await controller.load_groups()
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError('stale group reload must be cancelled')

        assert fake_db.replaced_contacts == []
        assert fake_db.replaced_groups == []

    asyncio.run(scenario())


def test_discovery_controller_clears_caches_on_close(monkeypatch) -> None:
    fake_discovery_service = FakeDiscoveryService()
    fake_user_service = FakeUserService()
    fake_auth_context = FakeAuthContext()

    monkeypatch.setattr(discovery_controller_module, 'get_discovery_service', lambda: fake_discovery_service)
    monkeypatch.setattr(discovery_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(discovery_controller_module, 'get_auth_controller', lambda: fake_auth_context)

    async def scenario() -> None:
        controller = discovery_controller_module.DiscoveryController()
        controller._user_cache['user-2'] = {'id': 'user-2'}
        controller._comment_cache['moment-1'] = []
        controller._like_state_cache['moment-1'] = True
        controller._like_count_cache['moment-1'] = 3
        discovery_controller_module._discovery_controller = controller

        await controller.close()

        assert controller._user_cache == {}
        assert controller._comment_cache == {}
        assert controller._like_state_cache == {}
        assert controller._like_count_cache == {}
        assert discovery_controller_module.peek_discovery_controller() is None

    asyncio.run(scenario())


def test_discovery_controller_ignores_late_results_after_auth_context_change(monkeypatch) -> None:
    fake_discovery_service = FakeDiscoveryService()
    fake_discovery_service.moments_payload = [
        {'id': 'moment-1', 'user_id': 'user-2', 'content': 'hello', 'comments': []},
    ]
    fake_user_service = FakeUserService()
    fake_user_service.user_payloads = {'user-2': {'id': 'user-2', 'username': 'bob'}}
    fake_auth_context = FakeAuthContext({'id': 'user-1', 'username': 'alice'})

    async def stale_fetch_moments(user_id=None):
        fake_auth_context.current_user = {'id': 'user-2', 'username': 'bob'}
        return list(fake_discovery_service.moments_payload)

    fake_discovery_service.fetch_moments = stale_fetch_moments

    monkeypatch.setattr(discovery_controller_module, 'get_discovery_service', lambda: fake_discovery_service)
    monkeypatch.setattr(discovery_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(discovery_controller_module, 'get_auth_controller', lambda: fake_auth_context)

    async def scenario() -> None:
        controller = discovery_controller_module.DiscoveryController()

        try:
            await controller.load_moments()
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError('stale discovery load must be cancelled')

        assert controller._user_cache == {}
        assert controller._comment_cache == {}
        assert controller._like_state_cache == {}
        assert controller._like_count_cache == {}

    asyncio.run(scenario())


def test_auth_controller_update_profile_ignores_late_result_after_auth_clear(monkeypatch) -> None:
    fake_auth_service = FakeAuthService()
    fake_user_service = FakeUserService()
    fake_db = FakeDatabase()
    fake_message_manager = FakeMessageManager()
    fake_chat_controller = FakeChatControllerContext()
    fake_file_service = FakeFileService()

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'peek_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'peek_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        controller._current_user = {'id': 'user-1', 'username': 'alice'}

        async def stale_update_me(payload: dict) -> dict:
            controller._current_user = None
            return {
                'id': 'user-1',
                'username': 'alice',
                'nickname': payload.get('nickname', 'alice'),
            }

        fake_user_service.update_me = stale_update_me

        try:
            await controller.update_profile(nickname='Alice')
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError('stale profile save must be cancelled')

        assert controller.current_user is None
        assert fake_chat_controller.refresh_calls == 0
        assert controller.USER_PROFILE_KEY not in fake_db.app_state

    asyncio.run(scenario())


def test_session_manager_execute_security_action_ignores_late_logout(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()
    fake_db = FakeSessionProfileDatabase()
    fake_e2ee_service = FakeE2EEService(
        {'device_id': 'device-local-1', 'has_local_bundle': True},
        peer_identity_summary={
            'local_device_id': 'device-local-1',
            'status': 'unverified',
            'device_count': 1,
            'trusted_device_count': 0,
            'unverified_device_count': 1,
            'changed_device_count': 0,
            'unverified_device_ids': ['device-bob-1'],
            'changed_device_ids': [],
            'change_count': 0,
            'last_changed_at': '',
            'last_trusted_at': '',
            'verification_available': True,
            'primary_verification_device_id': 'device-bob-1',
            'primary_verification_fingerprint': '',
            'primary_verification_fingerprint_short': '',
            'primary_verification_code': '',
            'primary_verification_code_short': '',
            'checked_at': '2026-04-06T12:00:00+00:00',
        },
    )

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: FakeSessionService())
    monkeypatch.setattr(session_manager_module, 'get_e2ee_service', lambda: fake_e2ee_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        manager._current_user_id = 'user-1'
        session = Session(
            session_id='session-1',
            name='Bob',
            session_type='direct',
            participant_ids=['user-1', 'user-2'],
        )
        session.extra['counterpart_id'] = 'user-2'
        session.extra['encryption_mode'] = 'e2ee_private'
        session.extra['session_crypto_state'] = {
            'enabled': True,
            'ready': True,
            'can_decrypt': True,
            'device_registered': True,
            'scheme': 'x25519-aesgcm-v1',
            'attachment_scheme': 'aesgcm-file+x25519-v1',
            'identity_status': 'unverified',
            'identity_verified': False,
            'identity_action_required': True,
            'identity_review_action': 'trust_peer_identity',
            'identity_review_blocking': True,
            'identity_alert_severity': 'critical',
            'device_id': 'device-local-1',
        }
        manager._sessions[session.session_id] = session

        async def stale_trust(user_id: str, *, device_ids: list[str] | None = None) -> dict:
            manager._current_user_id = ''
            return await FakeE2EEService(
                {'device_id': 'device-local-1', 'has_local_bundle': True},
                peer_identity_summary=fake_e2ee_service.peer_identity_summary,
            ).trust_peer_identities(user_id, device_ids=device_ids)

        fake_e2ee_service.trust_peer_identities = stale_trust

        try:
            await manager.execute_session_security_action('session-1', 'trust_peer_identity')
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError('stale session security action must be cancelled')

        assert fake_db.replaced_sessions == []
        assert fake_event_bus.events == []

    asyncio.run(scenario())


def test_session_manager_remove_session_ignores_late_logout_write(monkeypatch) -> None:
    fake_event_bus = FakeEventBus()

    class LogoutRaceDatabase:
        def __init__(self) -> None:
            self.is_connected = True
            self.app_state: dict[str, object] = {}
            self.deleted_sessions: list[str] = []

        async def set_app_state(self, key: str, value) -> None:
            self.app_state[key] = value

        async def delete_app_state(self, key: str) -> None:
            self.app_state.pop(key, None)

        async def delete_session(self, session_id: str) -> None:
            self.deleted_sessions.append(session_id)

    fake_db = LogoutRaceDatabase()

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: FakeSessionService())
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        manager._current_user_id = 'user-1'
        session = Session(session_id='session-1', name='Bob', session_type='direct')
        manager._sessions[session.session_id] = session

        original_save_hidden_sessions = manager._save_hidden_sessions

        async def stale_save_hidden_sessions(*, owner_user_id: str | None = None) -> None:
            manager._current_user_id = ''
            await original_save_hidden_sessions(owner_user_id=owner_user_id)

        manager._save_hidden_sessions = stale_save_hidden_sessions  # type: ignore[method-assign]

        try:
            await manager.remove_session('session-1')
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError('stale remove_session must be cancelled')

        assert fake_db.app_state == {}
        assert fake_db.deleted_sessions == []
        assert fake_event_bus.events == []

    asyncio.run(scenario())
