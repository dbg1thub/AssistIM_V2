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
        lambda: service.send_ws_message(
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


def test_message_service_rejects_encrypted_payload_when_session_mode_plain() -> None:
    service = MessageService(db=None)
    service.sessions = _FakeSessionRepo(session_exists=True, has_member=True)

    with pytest.raises(AppError) as exc_info:
        service._normalize_message_extra(
            sender_id='alice',
            session_id='session-1',
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
            session_id='session-1',
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

    payload = service._normalize_message_extra(
        sender_id='alice',
        session_id='session-1',
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