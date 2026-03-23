from __future__ import annotations

import asyncio
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

    class _DummyTheme:
        LIGHT = 'light'
        DARK = 'dark'
        AUTO = 'auto'

    qfluentwidgets.BoolValidator = _DummyValidator
    qfluentwidgets.ColorConfigItem = _DummyColorConfigItem
    qfluentwidgets.ConfigItem = _DummyConfigItem
    qfluentwidgets.ConfigSerializer = _DummyConfigSerializer
    qfluentwidgets.OptionsConfigItem = _DummyOptionsConfigItem
    qfluentwidgets.OptionsValidator = _DummyValidator
    qfluentwidgets.QConfig = _DummyQConfig
    qfluentwidgets.Theme = _DummyTheme
    qfluentwidgets.qconfig = types.SimpleNamespace(load=lambda path, cfg: None)
    sys.modules['qfluentwidgets'] = qfluentwidgets

from client.core.exceptions import APIError, ServerError
from client.managers import session_manager as session_manager_module
from client.managers import search_manager as search_manager_module
from client.models.message import ChatMessage, MessageStatus, MessageType
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


class FakeSessionManager:
    def __init__(self) -> None:
        self.current_session_id = 'session-1'
        self.added: list[tuple[str, ChatMessage]] = []
        self.sessions = []
        self.current_session = None

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

    def get_total_unread_count(self) -> int:
        return 0


class FakeFileService:
    def __init__(self, result: dict | None = None) -> None:
        self.result = dict(result or {})
        self.chat_uploads: list[str] = []
        self.avatar_uploads: list[str] = []

    async def upload_chat_attachment(self, file_path: str) -> dict:
        self.chat_uploads.append(file_path)
        return dict(self.result)

    async def upload_avatar(self, file_path: str) -> dict:
        self.avatar_uploads.append(file_path)
        return dict(self.result)


class FakeAuthService:
    def __init__(self) -> None:
        self.login_calls: list[tuple[str, str]] = []
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

    async def login(self, username: str, password: str) -> dict:
        self.login_calls.append((username, password))
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

    async def set_app_state(self, key: str, value) -> None:
        self.app_state[key] = value

    async def get_app_state(self, key: str):
        return self.app_state.get(key)

    async def delete_app_state(self, key: str) -> None:
        self.app_state.pop(key, None)

    async def clear_chat_state(self) -> None:
        return None


class FakeChatControllerContext:
    def __init__(self) -> None:
        self.user_ids: list[str] = []

    def set_user_id(self, user_id: str) -> None:
        self.user_ids.append(user_id)


class FakeAuthContext:
    def __init__(self, user: dict | None = None) -> None:
        self.current_user = dict(user or {'id': 'user-1', 'username': 'alice', 'nickname': 'Alice', 'avatar': ''})


class FakeContactService:
    def __init__(self) -> None:
        self.fetch_friends_calls = 0
        self.fetch_groups_calls = 0
        self.fetch_friend_requests_calls = 0
        self.send_friend_request_calls: list[tuple[str, str]] = []
        self.create_group_calls: list[tuple[str, list[str]]] = []
        self.accept_calls: list[str] = []
        self.reject_calls: list[str] = []
        self.remove_calls: list[str] = []
        self.friends_payload: list[dict] = []
        self.groups_payload: list[dict] = []
        self.requests_payload: list[dict] = []

    async def fetch_friends(self) -> list[dict]:
        self.fetch_friends_calls += 1
        return [dict(item) for item in self.friends_payload]

    async def fetch_groups(self) -> list[dict]:
        self.fetch_groups_calls += 1
        return [dict(item) for item in self.groups_payload]

    async def fetch_friend_requests(self) -> list[dict]:
        self.fetch_friend_requests_calls += 1
        return [dict(item) for item in self.requests_payload]

    async def send_friend_request(self, user_id: str, message: str = '') -> dict:
        self.send_friend_request_calls.append((user_id, message))
        return {'status': 'pending'}

    async def create_group(self, name: str, member_ids: list[str]) -> dict:
        self.create_group_calls.append((name, list(member_ids)))
        return {
            'id': 'group-1',
            'name': name,
            'owner_id': 'user-1',
            'session_id': 'session-group-1',
            'members': [{'id': 'user-1'}, *({'id': item} for item in member_ids)],
        }

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
    def __init__(self, messages: list[ChatMessage]) -> None:
        self.messages = list(messages)
        self.search_calls: list[tuple[str, str | None, int]] = []

    async def search_messages(self, keyword: str, session_id: str | None = None, limit: int = 100) -> list[ChatMessage]:
        self.search_calls.append((keyword, session_id, limit))
        return list(self.messages)

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


class FakeSessionService:
    def __init__(self) -> None:
        self.fetch_session_calls: list[str] = []
        self.fetch_sessions_calls = 0
        self.fetch_unread_counts_calls = 0
        self.create_direct_session_calls: list[tuple[str, str]] = []
        self.session_payload = {
            'id': 'session-1',
            'name': 'Core Team',
            'session_type': 'group',
            'participant_ids': ['alice', 'bob'],
            'avatar': 'https://cdn.example/groups/core.png',
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
        return [dict(self.session_payload)]

    async def fetch_unread_counts(self) -> list[dict]:
        self.fetch_unread_counts_calls += 1
        return [dict(item) for item in self.unread_payload]

    async def create_direct_session(self, user_id: str, *, display_name: str) -> dict:
        self.create_direct_session_calls.append((user_id, display_name))
        return dict(self.direct_session_payload)


def test_chat_controller_send_file_uses_file_service(monkeypatch) -> None:
    fake_message_manager = FakeMessageManager()
    fake_session_manager = FakeSessionManager()
    fake_file_service = FakeFileService({'url': 'https://cdn.example/files/picture.png', 'file_type': 'image/png'})

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



def test_auth_controller_update_profile_uploads_avatar_via_file_service(monkeypatch) -> None:
    fake_auth_service = FakeAuthService()
    fake_user_service = FakeUserService()
    fake_db = FakeDatabase()
    fake_message_manager = FakeMessageManager()
    fake_chat_controller = FakeChatControllerContext()
    fake_file_service = FakeFileService({'url': 'https://cdn.example/files/avatar.png'})

    monkeypatch.setattr(auth_controller_module, 'get_auth_service', lambda: fake_auth_service)
    monkeypatch.setattr(auth_controller_module, 'get_user_service', lambda: fake_user_service)
    monkeypatch.setattr(auth_controller_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(auth_controller_module, 'get_message_manager', lambda: fake_message_manager)
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: fake_file_service)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        user = await controller.update_profile(
            nickname='Alice',
            signature='Hello',
            avatar_file_path='D:/tmp/avatar.png',
        )

        assert fake_file_service.avatar_uploads == ['D:/tmp/avatar.png']
        assert fake_user_service.update_calls == [
            {
                'nickname': 'Alice',
                'avatar': 'https://cdn.example/files/avatar.png',
                'signature': 'Hello',
            }
        ]
        assert user['avatar'] == 'https://cdn.example/files/avatar.png'
        assert fake_message_manager.user_ids[-1] == 'user-1'
        assert fake_chat_controller.user_ids[-1] == 'user-1'
        assert fake_db.app_state[controller.USER_ID_KEY] == 'user-1'

    asyncio.run(scenario())


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
    monkeypatch.setattr(auth_controller_module, 'get_chat_controller', lambda: fake_chat_controller)
    monkeypatch.setattr(auth_controller_module, 'get_file_service', lambda: FakeFileService())
    monkeypatch.setattr(auth_controller_module, 'peek_connection_manager', lambda: None)

    async def scenario() -> None:
        controller = auth_controller_module.AuthController()
        user = await controller.login('alice', 'secret')

        assert fake_auth_service.login_calls == [('alice', 'secret')]
        assert fake_auth_service.access_token == 'access-token'
        assert fake_auth_service.refresh_token == 'refresh-token'
        assert user['id'] == 'user-1'
        assert fake_message_manager.user_ids[-1] == 'user-1'
        assert fake_chat_controller.user_ids[-1] == 'user-1'
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



def test_file_service_normalizes_backend_upload_payload(monkeypatch) -> None:
    class FakeUploadHttpClient:
        def __init__(self, payload: dict) -> None:
            self.payload = dict(payload)
            self.upload_calls: list[tuple[str, str]] = []

        async def upload_file(self, file_path: str, upload_path: str = '/files/upload') -> dict:
            self.upload_calls.append((file_path, upload_path))
            return dict(self.payload)

    fake_http = FakeUploadHttpClient({'file_url': '/uploads/avatar.png', 'file_type': 'image/png'})
    monkeypatch.setattr(file_service_module, 'get_http_client', lambda: fake_http)

    async def scenario() -> None:
        service = file_service_module.FileService()
        payload = await service.upload_avatar('D:/tmp/avatar.png')

        assert payload['url'] == '/uploads/avatar.png'
        assert payload['file_url'] == '/uploads/avatar.png'
        assert fake_http.upload_calls == [('D:/tmp/avatar.png', '/files/upload')]

    asyncio.run(scenario())



def test_file_service_rejects_upload_payload_without_url(monkeypatch) -> None:
    class FakeUploadHttpClient:
        async def upload_file(self, file_path: str, upload_path: str = '/files/upload') -> dict:
            return {'file_type': 'image/png'}

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
        accepted = await controller.accept_request('req-1')
        rejected = await controller.reject_request('req-2')
        await controller.remove_friend('user-2')

        assert request_payload['status'] == 'pending'
        assert fake_contact_service.send_friend_request_calls == [('user-2', 'hello')]
        assert fake_contact_service.create_group_calls == [('Core Team', ['user-2', 'user-3'])]
        assert group.session_id == 'session-group-1'
        assert group.member_count == 3
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

        assert fake_db.search_calls == [('100%_off', 'session-1', 5)]
        assert len(results) == 1
        assert results[0].message.message_id == 'msg-1'
        assert results[0].matched_text == 'discount 100%_off now'
        assert results[0].highlight_ranges == [(9, 17)]

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
        assert len(fake_connection.execute_calls) == 1

        sql, params = fake_connection.execute_calls[0]
        assert "content LIKE ? ESCAPE '\\'" in sql
        assert params == ('session-1', '%100\\%\\_off%', 25)

    asyncio.run(scenario())


def test_session_manager_refresh_remote_sessions_uses_session_service(monkeypatch) -> None:
    fake_session_service = FakeSessionService()

    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: fake_session_service)
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: FakeEventBus())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: FakeMessageManager())
    monkeypatch.setattr(session_manager_module, 'get_database', lambda: FakeSessionStateDatabase())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        sessions = await manager.refresh_remote_sessions()

        assert fake_session_service.fetch_sessions_calls == 1
        assert fake_session_service.fetch_unread_counts_calls == 1
        assert len(sessions) == 1
        assert sessions[0].session_id == 'session-1'
        assert sessions[0].unread_count == 4

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

        assert fake_session_service.create_direct_session_calls == [('bob', 'Bob')]
        assert session is not None
        assert session.session_id == 'session-direct-1'

    asyncio.run(scenario())



