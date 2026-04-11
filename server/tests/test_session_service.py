from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.core.errors import AppError
from app.services.session_service import SessionService


class _ForbiddenSingleSessionRepo:
    def list_member_ids(self, session_id: str):
        raise AssertionError('list_member_ids should not be used in batch list_sessions path')

    def list_members(self, session_id: str):
        raise AssertionError('list_members should not be used in batch list_sessions path')


class FakeSessionRepo(_ForbiddenSingleSessionRepo):
    def __init__(self) -> None:
        now = datetime(2026, 3, 29, 12, 0, 0)
        self.session_items = [
            SimpleNamespace(
                id='session-1',
                type='private',
                is_ai_session=False,
                name='Alice & Bob',
                avatar='/uploads/direct.png',
                updated_at=now,
                created_at=now,
            ),
            SimpleNamespace(
                id='session-2',
                type='group',
                is_ai_session=False,
                name='Core Team',
                avatar='/uploads/group.png',
                updated_at=now,
                created_at=now,
            ),
        ]
        self.members_by_session = {
            'session-1': [
                SimpleNamespace(session_id='session-1', user_id='alice', joined_at=now),
                SimpleNamespace(session_id='session-1', user_id='bob', joined_at=now),
            ],
            'session-2': [
                SimpleNamespace(session_id='session-2', user_id='alice', joined_at=now),
                SimpleNamespace(session_id='session-2', user_id='bob', joined_at=now),
                SimpleNamespace(session_id='session-2', user_id='charlie', joined_at=now),
            ],
        }
        self.list_members_for_sessions_calls: list[list[str]] = []

    def list_user_sessions(self, user_id: str):
        assert user_id == 'alice'
        return list(self.session_items)

    def list_members_for_sessions(self, session_ids: list[str]):
        self.list_members_for_sessions_calls.append(list(session_ids))
        return {session_id: list(self.members_by_session.get(session_id, [])) for session_id in session_ids}


class FakeMessageRepo:
    def __init__(self) -> None:
        now = datetime(2026, 3, 29, 12, 1, 0)
        self.last_messages_by_session = {
            'session-1': SimpleNamespace(
                id='message-1',
                session_id='session-1',
                status='sent',
                sender_id='alice',
                created_at=now,
                content='hello bob',
            ),
            'session-2': SimpleNamespace(
                id='message-2',
                session_id='session-2',
                status='sent',
                sender_id='charlie',
                created_at=now,
                content='hello team',
            ),
        }
        self.list_last_messages_for_sessions_calls: list[list[str]] = []

    def list_last_messages_for_sessions(self, session_ids: list[str]):
        self.list_last_messages_for_sessions_calls.append(list(session_ids))
        return {session_id: self.last_messages_by_session[session_id] for session_id in session_ids}

    def list_session_messages(self, session_id: str, limit: int = 1):
        raise AssertionError('list_session_messages should not be used in batch list_sessions path')


class FakeUserRepo:
    def __init__(self) -> None:
        self.users_by_id = {
            'alice': SimpleNamespace(id='alice', nickname='Alice', username='alice', avatar='/uploads/alice.png', gender='female', avatar_kind='default'),
            'bob': SimpleNamespace(id='bob', nickname='Bob', username='bob', avatar='/uploads/bob.png', gender='male', avatar_kind='custom'),
            'charlie': SimpleNamespace(id='charlie', nickname='Charlie', username='charlie', avatar='/uploads/charlie.png', gender='male', avatar_kind='custom'),
        }
        self.list_users_by_ids_calls: list[list[str]] = []

    def list_users_by_ids(self, user_ids: list[str]):
        self.list_users_by_ids_calls.append(list(user_ids))
        return {user_id: self.users_by_id[user_id] for user_id in user_ids}

    def get_by_id(self, user_id: str):
        raise AssertionError('get_by_id should not be used in batch list_sessions path')


class FakeGroupRepo:
    def get_by_session_id(self, session_id: str):
        if session_id != 'session-2':
            return None
        return SimpleNamespace(
            id='group-1',
            owner_id='alice',
            avatar='/uploads/group.png',
            announcement='',
        )

    def list_members(self, group_id: str):
        assert group_id == 'group-1'
        return [
            SimpleNamespace(group_id='group-1', user_id='alice', role='owner', group_nickname='', note=''),
            SimpleNamespace(group_id='group-1', user_id='bob', role='member', group_nickname='', note=''),
            SimpleNamespace(group_id='group-1', user_id='charlie', role='member', group_nickname='', note=''),
        ]

class FakeAvatarService:
    def backfill_user_avatar_state(self, user):
        return user

    def resolve_user_avatar_url(self, user):
        return getattr(user, 'avatar', None)

    def ensure_group_avatar(self, group):
        return getattr(group, 'avatar', None)


def test_session_service_list_sessions_uses_batch_repository_loaders() -> None:
    service = SessionService(db=None)
    fake_sessions = FakeSessionRepo()
    fake_messages = FakeMessageRepo()
    fake_users = FakeUserRepo()

    service.sessions = fake_sessions
    service.messages = fake_messages
    service.users = fake_users
    service.groups = FakeGroupRepo()
    service.avatars = FakeAvatarService()

    payload = service.list_sessions(SimpleNamespace(id='alice'))

    assert [item['session_id'] for item in payload] == ['session-1', 'session-2']
    assert payload[0]['session_type'] == 'direct'
    assert payload[0]['encryption_mode'] == 'plain'
    assert payload[0]['session_crypto_state'] == {}
    assert payload[0]['call_capabilities'] == {'voice': True, 'video': True}
    assert payload[0]['participant_ids'] == ['alice', 'bob']
    assert payload[0]['avatar'] == '/uploads/direct.png'
    assert payload[0]['counterpart_id'] == 'bob'
    assert payload[0]['counterpart_name'] == 'Bob'
    assert payload[0]['counterpart_username'] == 'bob'
    assert payload[0]['counterpart_avatar'] == '/uploads/bob.png'
    assert payload[0]['counterpart_gender'] == 'male'
    assert payload[0]['last_message'] == 'hello bob'
    assert [member['id'] for member in payload[0]['members']] == ['alice', 'bob']
    assert payload[1]['session_type'] == 'group'
    assert payload[1]['encryption_mode'] == 'plain'
    assert payload[1]['session_crypto_state'] == {}
    assert payload[1]['call_capabilities'] == {'voice': False, 'video': False}
    assert payload[1]['group_id'] == 'group-1'
    assert payload[1]['group_member_version'] == service._group_member_version(['alice', 'bob', 'charlie'])
    assert payload[1]['participant_ids'] == ['alice', 'bob', 'charlie']
    assert payload[1]['last_message'] == 'hello team'
    assert payload[1]['counterpart_id'] is None
    assert [member['id'] for member in payload[1]['members']] == ['alice', 'bob', 'charlie']

    assert fake_sessions.list_members_for_sessions_calls == [['session-1', 'session-2']]
    assert fake_messages.list_last_messages_for_sessions_calls == [['session-1', 'session-2']]
    assert fake_users.list_users_by_ids_calls == [['alice', 'bob', 'charlie']]

class _HiddenPrivateSessionRepo:
    def __init__(self) -> None:
        now = datetime(2026, 3, 29, 12, 0, 0)
        self.existing = SimpleNamespace(
            id='session-hidden',
            type='private',
            is_ai_session=False,
            name='Ghost DM',
            avatar='/uploads/ghost.png',
            updated_at=now,
            created_at=now,
            direct_key='alice|bob',
        )
        self.deleted_session_id = None

    def build_private_direct_key(self, members: list[str]) -> str:
        return '|'.join(sorted(str(member) for member in members))

    def get_private_session_by_direct_key(self, direct_key: str):
        return self.existing if direct_key == 'alice|bob' else None

    def get_by_id(self, session_id: str):
        return self.existing if session_id == self.existing.id else None

    def list_member_ids(self, session_id: str):
        if session_id != self.existing.id:
            return []
        return ['alice', 'alice']

    def delete_session(self, session_id: str) -> None:
        self.deleted_session_id = session_id


class _NullGroupRepo:
    def get_by_session_id(self, session_id: str):
        return None


def test_session_service_serialize_session_uses_persisted_encryption_mode() -> None:
    now = datetime(2026, 3, 29, 12, 0, 0)
    member_rows = [
        SimpleNamespace(session_id='direct-1', user_id='alice', joined_at=now),
        SimpleNamespace(session_id='direct-1', user_id='bob', joined_at=now),
    ]
    service = SessionService(db=None)
    service.messages = SimpleNamespace(list_session_messages=lambda session_id, limit=1: [])
    service.sessions = SimpleNamespace(
        list_member_ids=lambda session_id: ['alice', 'bob'],
        list_members=lambda session_id: list(member_rows),
    )
    service.users = SimpleNamespace(list_users_by_ids=lambda user_ids: {})
    service.groups = _NullGroupRepo()
    service.avatars = FakeAvatarService()
    direct_session = SimpleNamespace(
        id='direct-1',
        type='private',
        is_ai_session=False,
        name='Direct',
        avatar=None,
        updated_at=now,
        created_at=now,
        encryption_mode='e2ee_private',
    )
    group_session = SimpleNamespace(
        id='group-1',
        type='group',
        is_ai_session=False,
        name='Group',
        avatar=None,
        updated_at=now,
        created_at=now,
        encryption_mode='e2ee_group',
    )
    ai_session = SimpleNamespace(
        id='ai-1',
        type='private',
        is_ai_session=True,
        name='AI',
        avatar=None,
        updated_at=now,
        created_at=now,
        encryption_mode='plain',
    )

    direct_payload = service.serialize_session(
        direct_session,
        include_members=False,
        participant_ids=['alice', 'bob'],
    )
    group_payload = service.serialize_session(
        group_session,
        include_members=False,
        participant_ids=['alice', 'bob'],
    )
    ai_payload = service.serialize_session(
        ai_session,
        include_members=False,
        participant_ids=['alice', 'bot'],
    )

    assert direct_payload['encryption_mode'] == 'e2ee_private'
    assert group_payload['encryption_mode'] == 'e2ee_group'
    assert ai_payload['encryption_mode'] == 'server_visible_ai'


def test_session_service_create_private_rejects_hidden_existing_direct_session() -> None:
    service = SessionService(db=None)
    fake_sessions = _HiddenPrivateSessionRepo()
    service.sessions = fake_sessions
    service.groups = _NullGroupRepo()
    service.users = SimpleNamespace(get_by_id=lambda user_id: SimpleNamespace(id=user_id) if user_id == 'bob' else None)

    with pytest.raises(AppError) as exc_info:
        service.create_private(SimpleNamespace(id='alice'), ['bob'])

    assert exc_info.value.status_code == 404


def test_session_service_delete_session_rejects_hidden_existing_direct_session() -> None:
    service = SessionService(db=None)
    fake_sessions = _HiddenPrivateSessionRepo()
    service.sessions = fake_sessions
    service.groups = _NullGroupRepo()

    with pytest.raises(AppError) as exc_info:
        service.delete_session(SimpleNamespace(id='alice'), 'session-hidden')

    assert exc_info.value.status_code == 404
    assert fake_sessions.deleted_session_id is None
