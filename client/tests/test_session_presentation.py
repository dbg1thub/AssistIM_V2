from __future__ import annotations

import asyncio

from client.managers import session_manager as session_manager_module
from client.models.message import Session


class _FakeDatabase:
    is_connected = True

    def __init__(self, contacts_by_id):
        self._contacts_by_id = contacts_by_id

    async def list_contacts_cache_by_ids(self, contact_ids):
        return {contact_id: self._contacts_by_id[contact_id] for contact_id in contact_ids if contact_id in self._contacts_by_id}


def test_group_session_display_name_and_chat_title_follow_default_rule() -> None:
    session = Session(
        session_id='group-1',
        name='',
        session_type='group',
        participant_ids=['me', 'user-2', 'user-3', 'user-4', 'user-5'],
        extra={
            'current_user_id': 'me',
            'member_count': 5,
            'members': [
                {'id': 'me', 'nickname': 'Me'},
                {'id': 'user-2', 'remark': 'test1', 'nickname': 'Nick 1'},
                {'id': 'user-3', 'group_nickname': 'test2', 'nickname': 'Nick 2'},
                {'id': 'user-4', 'nickname': 'test3'},
                {'id': 'user-5', 'nickname': 'test4'},
            ],
        },
    )

    assert session.display_name() == 'test1、test2、test3...'
    assert session.chat_title() == 'test1、test2、test3(5)'


def test_group_session_preview_sender_name_uses_remark_priority() -> None:
    session = Session(
        session_id='group-1',
        name='',
        session_type='group',
        participant_ids=['me', 'user-2'],
        extra={
            'current_user_id': 'me',
            'member_count': 2,
            'last_message_sender_id': 'user-2',
            'members': [
                {'id': 'me', 'nickname': 'Me'},
                {'id': 'user-2', 'remark': 'test1', 'group_nickname': 'group name', 'nickname': 'Nick 1'},
            ],
        },
    )

    assert session.preview_sender_name() == 'test1'


def test_session_manager_decorates_members_with_contact_remarks(monkeypatch) -> None:
    fake_db = _FakeDatabase(
        {
            'user-2': {
                'id': 'user-2',
                'username': 'test2',
                'nickname': 'Nick 2',
                'remark': 'test1',
            }
        }
    )

    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: object())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = Session(
            session_id='group-1',
            name='',
            session_type='group',
            participant_ids=['me', 'user-2'],
            extra={
                'members': [
                    {'id': 'me', 'nickname': 'Me'},
                    {'id': 'user-2', 'username': 'test2', 'nickname': 'Nick 2'},
                ],
            },
        )

        await manager._decorate_session_members([session], {'id': 'me'})

        assert session.extra['members'][1]['remark'] == 'test1'
        assert session.extra['members'][1]['display_name'] == 'test1'
        assert session.extra['current_user_id'] == 'me'

    asyncio.run(scenario())


def test_legacy_generated_group_name_is_treated_as_default_name() -> None:
    session = Session(
        session_id='group-legacy',
        name='test1、test2、test3...',
        session_type='group',
        participant_ids=['me', 'user-2', 'user-3', 'user-4', 'user-5'],
        extra={
            'current_user_id': 'me',
            'member_count': 5,
            'members': [
                {'id': 'me', 'nickname': 'Me'},
                {'id': 'user-2', 'remark': 'test1', 'nickname': 'Nick 1'},
                {'id': 'user-3', 'group_nickname': 'test2', 'nickname': 'Nick 2'},
                {'id': 'user-4', 'nickname': 'test3'},
                {'id': 'user-5', 'nickname': 'test4'},
            ],
        },
    )

    assert session.has_custom_group_name() is False
    assert session.chat_title() == 'test1、test2、test3(5)'
