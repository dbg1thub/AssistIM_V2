from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.errors import AppError
from app.services.message_service import MessageService


class _FakeSessionRepo:
    def __init__(
        self,
        *,
        session_exists: bool,
        has_member: bool,
        session_type: str = 'private',
        is_ai_session: bool = False,
        encryption_mode: str = 'plain',
    ) -> None:
        self._session_exists = session_exists
        self._has_member = has_member
        self._session_type = session_type
        self._is_ai_session = is_ai_session
        self._encryption_mode = encryption_mode

    def get_by_id(self, session_id: str):
        if not self._session_exists:
            return None
        return SimpleNamespace(
            id=session_id,
            type=self._session_type,
            is_ai_session=self._is_ai_session,
            encryption_mode=self._encryption_mode,
        )

    def has_member(self, session_id: str, user_id: str) -> bool:
        return self._has_member

    def list_member_ids(self, session_id: str):
        return ['alice'] if self._has_member else []

    def list_members(self, session_id: str):
        return [SimpleNamespace(user_id='alice')] if self._has_member else []



class _HiddenPrivateSessionRepo:
    def __init__(self) -> None:
        self._sessions = {
            'hidden-direct': SimpleNamespace(
                id='hidden-direct',
                type='private',
                is_ai_session=False,
                encryption_mode='plain',
                name='',
                avatar=None,
            ),
            'visible-group': SimpleNamespace(
                id='visible-group',
                type='group',
                is_ai_session=False,
                encryption_mode='plain',
                name='',
                avatar=None,
            ),
        }

    def get_by_id(self, session_id: str):
        return self._sessions.get(session_id)

    def list_member_ids(self, session_id: str):
        if session_id == 'hidden-direct':
            return ['alice', 'alice']
        if session_id == 'visible-group':
            return ['alice', 'bob']
        return []

    def list_members(self, session_id: str):
        return [SimpleNamespace(user_id=user_id) for user_id in self.list_member_ids(session_id)]


class _FakeDeviceRepo:
    def get_device_for_user(self, user_id: str, device_id: str):
        if (user_id, device_id) in {('alice', 'device-alice'), ('bob', 'device-bob')}:
            return SimpleNamespace(user_id=user_id, device_id=device_id, is_active=True)
        return None


class _ForbiddenHiddenMessageRepo:
    def list_session_messages(self, *args, **kwargs):
        raise AssertionError('hidden private session should fail before listing messages')

    def create(self, *args, **kwargs):
        raise AssertionError('hidden private session should fail before creating messages')

    def get_by_id(self, message_id: str):
        return SimpleNamespace(
            id=message_id,
            session_id='hidden-direct',
            sender_id='alice',
            created_at=None,
            updated_at=None,
            status='sent',
            type='text',
            content='hello',
            session_seq=1,
        )

    def mark_read(self, *args, **kwargs):
        raise AssertionError('hidden private session should fail before marking read')

    def mark_read_batch(self, *args, **kwargs):
        raise AssertionError('hidden private session should fail before batch read')

    def update_status(self, *args, **kwargs):
        raise AssertionError('hidden private session should fail before mutation')

    def update_content(self, *args, **kwargs):
        raise AssertionError('hidden private session should fail before mutation')

    def delete(self, *args, **kwargs):
        raise AssertionError('hidden private session should fail before mutation')


class _SyncMessageRepo:
    def list_missing_messages_for_user(self, session_cursors: dict, user_id: str):
        return [
            SimpleNamespace(id='hidden-message', session_id='hidden-direct'),
            SimpleNamespace(id='visible-message', session_id='visible-group'),
        ]

    def list_missing_events_for_user(self, event_cursors: dict, user_id: str):
        return [
            SimpleNamespace(id='hidden-event', session_id='hidden-direct'),
            SimpleNamespace(id='visible-event', session_id='visible-group'),
        ]


def _hidden_private_message_service() -> MessageService:
    service = MessageService(db=None)
    service.sessions = _HiddenPrivateSessionRepo()
    service.messages = _ForbiddenHiddenMessageRepo()
    return service


def _assert_hidden_private_404(action) -> None:
    with pytest.raises(AppError) as exc_info:
        action()

    assert exc_info.value.status_code == 404


def _alice():
    return SimpleNamespace(id='alice')


def _fake_session(encryption_mode: str = 'plain'):
    return SimpleNamespace(
        id='session-1',
        type='private',
        is_ai_session=False,
        encryption_mode=encryption_mode,
    )


def _fake_session_member_ids() -> list[str]:
    return ['alice', 'bob']


def test_message_service_list_messages_returns_404_for_missing_session() -> None:
    service = MessageService(db=None)
    service.sessions = _FakeSessionRepo(session_exists=False, has_member=False)

    with pytest.raises(AppError) as exc_info:
        service.list_messages(SimpleNamespace(id='alice'), 'missing-session')

    assert exc_info.value.status_code == 404


def test_message_service_list_messages_returns_403_for_existing_session_without_membership() -> None:
    service = MessageService(db=None)
    service.sessions = _FakeSessionRepo(session_exists=True, has_member=False)

    with pytest.raises(AppError) as exc_info:
        service.list_messages(SimpleNamespace(id='alice'), 'session-1')

    assert exc_info.value.status_code == 403

def test_message_service_hidden_private_session_blocks_session_scoped_entries() -> None:
    service = _hidden_private_message_service()

    _assert_hidden_private_404(lambda: service.list_messages(_alice(), 'hidden-direct'))
    _assert_hidden_private_404(lambda: service.send_message(_alice(), 'hidden-direct', 'hello'))
    _assert_hidden_private_404(
        lambda: service.send_websocket_message(
            sender_id='alice',
            session_id='hidden-direct',
            content='hello',
            message_id='msg-1',
        )
    )
    _assert_hidden_private_404(lambda: service.batch_read(_alice(), 'hidden-direct', 'msg-1'))
    _assert_hidden_private_404(lambda: service.get_session_member_ids('hidden-direct', 'alice'))


def test_message_service_hidden_private_session_blocks_message_scoped_mutations() -> None:
    service = _hidden_private_message_service()

    _assert_hidden_private_404(lambda: service.mark_read(_alice(), 'msg-1'))
    _assert_hidden_private_404(lambda: service.recall(_alice(), 'msg-1'))
    _assert_hidden_private_404(lambda: service.edit(_alice(), 'msg-1', 'updated'))
    _assert_hidden_private_404(lambda: service.delete(_alice(), 'msg-1'))


def test_message_service_sync_missing_messages_filters_hidden_private_sessions() -> None:
    service = MessageService(db=None)
    service.sessions = _HiddenPrivateSessionRepo()
    service.messages = _SyncMessageRepo()
    service._serialize_messages = lambda items, current_user_id: [item.id for item in items]

    payload = service.sync_missing_messages({}, 'alice')

    assert payload == ['visible-message']


def test_message_service_sync_missing_events_filters_hidden_private_sessions() -> None:
    service = MessageService(db=None)
    service.sessions = _HiddenPrivateSessionRepo()
    service.messages = _SyncMessageRepo()
    service.serialize_session_event = lambda item: {'id': item.id}

    payload = service.sync_missing_events({}, 'alice')

    assert payload == [{'id': 'visible-event'}]


def test_message_service_get_session_member_ids_returns_visible_session_members() -> None:
    service = MessageService(db=None)
    service.sessions = _HiddenPrivateSessionRepo()

    payload = service.get_session_member_ids('visible-group', 'alice')

    assert payload == ['alice', 'bob']


def test_message_service_recalled_message_content_uses_formal_placeholder() -> None:
    service = MessageService(db=None)
    message = SimpleNamespace(status='recalled', content='original content')

    payload = service._serialize_message_content(message, 'alice')

    assert payload == MessageService.RECALLED_MESSAGE_PLACEHOLDER

def _direct_text_encryption_extra() -> dict:
    return {
        'encryption': {
            'enabled': True,
            'scheme': 'x25519-aesgcm-v1',
            'sender_device_id': 'device-alice',
            'sender_identity_key_public': 'identity-alice',
            'recipient_user_id': 'bob',
            'recipient_device_id': 'device-bob',
            'content_ciphertext': 'ciphertext',
            'nonce': 'nonce',
            'recipient_prekey_id': 1,
            'recipient_prekey_type': 'signed',
            'local_plaintext': 'hello',
        },
    }


def test_message_service_recall_rejects_non_user_message_types() -> None:
    service = MessageService(db=None)

    service._ensure_message_type_allows_recall(SimpleNamespace(type='image'))

    with pytest.raises(AppError) as exc_info:
        service._ensure_message_type_allows_recall(SimpleNamespace(type='system'))

    assert exc_info.value.status_code == 422
    assert exc_info.value.message == 'message type does not support recall'

def test_message_service_rejects_structured_values_for_envelope_scalar_fields() -> None:
    def assert_invalid(callback, field_name: str) -> None:
        with pytest.raises(AppError) as exc_info:
            callback()
        assert exc_info.value.status_code == 422
        assert field_name in exc_info.value.message

    direct_text = dict(_direct_text_encryption_extra()['encryption'])
    direct_text['recipient_device_id'] = {'device_id': 'device-bob'}
    assert_invalid(lambda: MessageService._validate_direct_text_envelope(direct_text), 'recipient_device_id')

    direct_attachment = {
        'sender_device_id': 'device-alice',
        'sender_identity_key_public': 'identity-alice',
        'recipient_user_id': 'bob',
        'recipient_device_id': 'device-bob',
        'metadata_ciphertext': ['metadata-ciphertext'],
        'nonce': 'nonce',
        'recipient_prekey_id': 1,
        'recipient_prekey_type': 'signed',
    }
    assert_invalid(lambda: MessageService._validate_direct_attachment_envelope(direct_attachment), 'metadata_ciphertext')

    fanout_item = {
        'recipient_user_id': 'bob',
        'recipient_device_id': 'device-bob',
        'sender_device_id': 'device-alice',
        'sender_key_id': 'sender-key-1',
        'ciphertext': 'fanout-ciphertext',
        'nonce': 'fanout-nonce',
        'scheme': 'group-sender-key-fanout-v1',
    }
    group_text = {
        'session_id': 'session-group-1',
        'sender_device_id': 'device-alice',
        'sender_key_id': ['sender-key-1'],
        'content_ciphertext': 'ciphertext',
        'nonce': 'nonce',
        'fanout': [dict(fanout_item)],
    }
    assert_invalid(lambda: MessageService._validate_group_text_envelope(group_text), 'sender_key_id')

    group_attachment = {
        'session_id': 'session-group-1',
        'sender_device_id': 'device-alice',
        'sender_key_id': 'sender-key-1',
        'metadata_ciphertext': {'ciphertext': 'metadata'},
        'nonce': 'nonce',
        'fanout': [dict(fanout_item)],
    }
    assert_invalid(lambda: MessageService._validate_group_attachment_envelope(group_attachment), 'metadata_ciphertext')

    invalid_fanout = dict(fanout_item)
    invalid_fanout['ciphertext'] = {'ciphertext': 'fanout'}
    group_text_with_invalid_fanout = dict(group_text)
    group_text_with_invalid_fanout['sender_key_id'] = 'sender-key-1'
    group_text_with_invalid_fanout['fanout'] = [invalid_fanout]
    assert_invalid(lambda: MessageService._validate_group_text_envelope(group_text_with_invalid_fanout), 'ciphertext')

def test_message_service_rejects_encrypted_payload_when_session_mode_plain() -> None:
    service = MessageService(db=None)
    service.sessions = _FakeSessionRepo(session_exists=True, has_member=True)

    with pytest.raises(AppError) as exc_info:
        service._normalize_message_extra(
            sender_id='alice',
            session=_fake_session(),
            session_member_ids=_fake_session_member_ids(),
            content='hello',
            message_type='text',
            extra=_direct_text_encryption_extra(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.message == 'session encryption is not enabled'


def test_message_service_rejects_plaintext_text_in_e2ee_private_session() -> None:
    service = MessageService(db=None)
    service.sessions = _FakeSessionRepo(
        session_exists=True,
        has_member=True,
        encryption_mode='e2ee_private',
    )

    with pytest.raises(AppError) as exc_info:
        service._normalize_message_extra(
            sender_id='alice',
            session=_fake_session(encryption_mode='e2ee_private'),
            session_member_ids=_fake_session_member_ids(),
            content='hello',
            message_type='text',
            extra=None,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.message == 'end-to-end encrypted text messages require text encryption'


def test_message_service_accepts_encrypted_text_in_e2ee_private_session() -> None:
    service = MessageService(db=None)
    service.sessions = _FakeSessionRepo(
        session_exists=True,
        has_member=True,
        encryption_mode='e2ee_private',
    )
    service.devices = _FakeDeviceRepo()

    payload = service._normalize_message_extra(
        sender_id='alice',
        session=_fake_session(encryption_mode='e2ee_private'),
        session_member_ids=_fake_session_member_ids(),
        content='hello',
        message_type='text',
        extra=_direct_text_encryption_extra(),
    )

    assert payload is not None
    assert payload['encryption']['scheme'] == 'x25519-aesgcm-v1'
    assert 'local_plaintext' not in payload['encryption']


class _UnreadSessionRepo:
    def __init__(self) -> None:
        self._sessions = [
            SimpleNamespace(id='hidden-direct', type='private', is_ai_session=False),
            SimpleNamespace(id='visible-group', type='group', is_ai_session=False),
        ]

    def list_user_sessions(self, user_id: str):
        return list(self._sessions)

    def list_member_ids(self, session_id: str):
        if session_id == 'hidden-direct':
            return ['alice', 'alice']
        if session_id == 'visible-group':
            return ['alice', 'bob', 'charlie']
        return []


class _UnreadMessageRepo:
    def unread_by_session_for_user(self, user_id: str) -> list[dict]:
        return [
            {'session_id': 'hidden-direct', 'unread': 4},
            {'session_id': 'visible-group', 'unread': 2},
        ]


def test_message_service_session_unread_counts_filters_hidden_private_sessions() -> None:
    service = MessageService(db=None)
    service.sessions = _UnreadSessionRepo()
    service.messages = _UnreadMessageRepo()

    payload = service.session_unread_counts(SimpleNamespace(id='alice'))

    assert payload == [{'session_id': 'visible-group', 'unread': 2}]


def test_message_service_unread_summary_excludes_hidden_private_sessions() -> None:
    service = MessageService(db=None)
    service.sessions = _UnreadSessionRepo()
    service.messages = _UnreadMessageRepo()

    payload = service.unread_summary(SimpleNamespace(id='alice'))

    assert payload == {'total': 2}
