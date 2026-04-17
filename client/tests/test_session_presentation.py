from __future__ import annotations

import asyncio

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication

from client.managers import session_manager as session_manager_module
from client.delegates.session_delegate import SessionDelegate
from client.delegates.message_delegate import MessageDelegate
from client.models.message_model import MessageModel
from client.models.message import ChatMessage, MessageStatus, MessageType, Session, resolve_recall_notice
from client.core.i18n import tr


class _FakeDatabase:
    is_connected = True

    def __init__(self, contacts_by_id, messages_by_session=None):
        self._contacts_by_id = contacts_by_id
        self._messages_by_session = dict(messages_by_session or {})
        self.saved_sessions: list[Session] = []

    async def list_contacts_cache_by_ids(self, contact_ids):
        return {contact_id: self._contacts_by_id[contact_id] for contact_id in contact_ids if contact_id in self._contacts_by_id}

    async def save_session(self, _session) -> None:
        self.saved_sessions.append(_session)
        return None

    async def get_last_message(self, session_id: str):
        return self._messages_by_session.get(session_id)


class _FakeEventBus:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict]] = []

    async def emit(self, event_type: str, payload: dict) -> None:
        self.emitted.append((event_type, payload))


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


def test_group_session_preview_sender_name_omits_current_user_prefix() -> None:
    session = Session(
        session_id='group-1',
        name='',
        session_type='group',
        participant_ids=['me', 'user-2'],
        extra={
            'current_user_id': 'me',
            'last_message_sender_id': 'me',
            'members': [
                {'id': 'me', 'nickname': 'Me'},
                {'id': 'user-2', 'nickname': 'Nick 2'},
            ],
        },
    )

    assert session.preview_sender_name() == ''


def test_group_session_preview_sender_name_uses_cached_sender_name_when_member_snapshot_missing() -> None:
    session = Session(
        session_id='group-1',
        name='',
        session_type='group',
        participant_ids=['me', 'user-2'],
        extra={
            'current_user_id': 'me',
            'last_message_sender_id': 'user-2',
            'last_message_sender_name': 'test1',
            'members': [],
        },
    )

    assert session.preview_sender_name() == 'test1'


def test_session_delegate_group_preview_does_not_prefix_self_message() -> None:
    delegate = SessionDelegate()
    session = Session(
        session_id='group-1',
        name='',
        session_type='group',
        participant_ids=['me', 'user-2'],
        last_message='hello',
        extra={
            'current_user_id': 'me',
            'last_message_sender_id': 'me',
            'last_message_status': MessageStatus.SENT.value,
            'members': [
                {'id': 'me', 'nickname': 'Me'},
                {'id': 'user-2', 'nickname': 'Nick 2'},
            ],
        },
    )

    assert delegate._format_preview_text(session) == 'hello'


def test_group_recall_notice_uses_quoted_member_name_in_content_and_preview() -> None:
    delegate = SessionDelegate()
    session = Session(
        session_id='group-1',
        name='',
        session_type='group',
        participant_ids=['me', 'user-2'],
        last_message='对方撤回了一条消息',
        extra={
            'current_user_id': 'me',
            'last_message_sender_id': 'user-2',
            'last_message_status': MessageStatus.RECALLED.value,
            'members': [
                {'id': 'me', 'nickname': 'Me'},
                {'id': 'user-2', 'remark': 'test1', 'nickname': 'Nick 2'},
            ],
        },
    )
    message = ChatMessage(
        message_id='msg-1',
        session_id='group-1',
        sender_id='user-2',
        content='',
        message_type=MessageType.TEXT,
        status=MessageStatus.RECALLED,
        extra={
            'session_type': 'group',
            'sender_name': 'test1',
        },
    )
    expected = tr("message.recalled.by", "{name} recalled a message", name='“test1”')

    assert resolve_recall_notice(message) == expected
    assert delegate._format_preview_text(session) == expected


def test_group_session_preview_mentions_current_user_flag_is_explicit() -> None:
    session = Session(
        session_id='group-1',
        name='',
        session_type='group',
        participant_ids=['me', 'user-2'],
        extra={'last_message_mentions_current_user': True},
    )

    assert session.preview_mentions_current_user() is True


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


def test_session_manager_direct_session_prefers_counterpart_username_over_uuid_when_members_missing(monkeypatch) -> None:
    fake_db = _FakeDatabase({})

    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: object())

    manager = session_manager_module.SessionManager()
    session = Session(
        session_id='session-1',
        name='Private Chat',
        session_type='direct',
        participant_ids=['me', 'user-2'],
        extra={
            'members': [],
            'counterpart_id': 'user-2',
            'counterpart_username': 'test2',
        },
    )

    manager._normalize_session_display(
        session,
        {
            'id': 'me',
            'username': 'me',
            'nickname': 'Me',
        },
    )

    assert session.name == 'test2'
    assert session.extra.get('counterpart_name') == 'test2'


def test_session_manager_last_message_preview_caches_sender_name_from_message_extra(monkeypatch) -> None:
    fake_db = _FakeDatabase({})

    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: object())

    manager = session_manager_module.SessionManager()
    session = Session(
        session_id='group-1',
        name='Core Team',
        session_type='group',
        participant_ids=['me', 'user-2'],
    )
    message = ChatMessage(
        message_id='msg-1',
        session_id='group-1',
        sender_id='user-2',
        content='hello',
        message_type=MessageType.TEXT,
        status=MessageStatus.SENT,
        extra={'sender_name': 'test1'},
    )

    manager._apply_last_message_preview(session, message, current_user_id='me')

    assert session.extra.get('last_message_sender_name') == 'test1'


def test_session_manager_last_message_preview_infers_encryption_mode_from_session_metadata(monkeypatch) -> None:
    fake_db = _FakeDatabase({})

    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: object())

    manager = session_manager_module.SessionManager()
    session = Session(
        session_id='direct-1',
        name='test2',
        session_type='direct',
        participant_ids=['me', 'user-2'],
    )
    message = ChatMessage(
        message_id='msg-1',
        session_id='direct-1',
        sender_id='user-2',
        content='secret',
        message_type=MessageType.TEXT,
        status=MessageStatus.SENT,
        extra={'session_encryption_mode': 'e2ee_private'},
    )

    manager._apply_last_message_preview(session, message, current_user_id='me')

    assert session.extra.get('encryption_mode') == 'e2ee_private'


def test_session_manager_add_message_to_session_skips_duplicate_preview_updates(monkeypatch) -> None:
    fake_db = _FakeDatabase({})
    fake_event_bus = _FakeEventBus()

    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: object())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = Session(
            session_id='group-1',
            name='Core Team',
            session_type='group',
            participant_ids=['me', 'user-2'],
        )
        manager._sessions[session.session_id] = session
        message = ChatMessage(
            message_id='msg-dup',
            session_id='group-1',
            sender_id='user-2',
            content='hello',
            message_type=MessageType.TEXT,
            status=MessageStatus.SENT,
            extra={'sender_name': 'test1'},
        )

        await manager.add_message_to_session(session.session_id, message)
        await manager.add_message_to_session(session.session_id, message)

        assert len(fake_db.saved_sessions) == 1
        message_added_events = [event for event, _payload in fake_event_bus.emitted if event == session_manager_module.SessionEvent.MESSAGE_ADDED]
        updated_events = [event for event, _payload in fake_event_bus.emitted if event == session_manager_module.SessionEvent.UPDATED]
        assert len(message_added_events) == 1
        assert len(updated_events) == 1

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


def test_group_session_authoritative_metadata_is_separate_from_generated_display_name() -> None:
    session = Session(
        session_id='group-1',
        name='',
        session_type='group',
        participant_ids=['me', 'user-2', 'user-3'],
        extra={
            'group_id': 'group-42',
            'server_name': '',
            'current_user_id': 'me',
            'members': [
                {'id': 'me', 'nickname': 'Me'},
                {'id': 'user-2', 'remark': 'test1', 'nickname': 'Nick 1'},
                {'id': 'user-3', 'group_nickname': 'test2', 'nickname': 'Nick 2'},
            ],
        },
    )

    assert session.authoritative_group_id() == 'group-42'
    assert session.authoritative_group_name() == ''
    assert session.display_name() == 'test1、test2'


def test_message_delegate_group_sender_label_shares_avatar_top_baseline_for_self_and_others() -> None:
    app = QApplication.instance() or QApplication([])
    delegate = MessageDelegate()
    session = Session(
        session_id='group-1',
        name='',
        session_type='group',
        participant_ids=['me', 'user-2'],
        extra={
            'current_user_id': 'me',
            'show_member_nickname': True,
            'members': [
                {'id': 'me', 'group_nickname': 'Leader', 'nickname': 'Me'},
                {'id': 'user-2', 'group_nickname': 'Mate', 'nickname': 'Nick 2'},
            ],
        },
    )
    delegate.set_session(session)

    other_message = ChatMessage(
        message_id='msg-1',
        session_id='group-1',
        sender_id='user-2',
        content='hello',
        message_type=MessageType.TEXT,
        status=MessageStatus.SENT,
    )
    self_message = ChatMessage(
        message_id='msg-2',
        session_id='group-1',
        sender_id='me',
        content='hi',
        message_type=MessageType.TEXT,
        status=MessageStatus.SENT,
        is_self=True,
    )

    other_layout = delegate._layout_rects(QRect(0, 0, 360, 120), other_message)
    self_layout = delegate._layout_rects(QRect(0, 0, 360, 120), self_message)

    assert app is not None
    assert delegate._group_sender_label_text(other_message) == 'Mate'
    assert delegate._group_sender_label_text(self_message) == 'Leader'
    assert other_layout.sender_label_rect is not None
    assert self_layout.sender_label_rect is not None
    assert other_layout.sender_label_rect.top() == other_layout.avatar_rect.top()
    assert self_layout.sender_label_rect.top() == self_layout.avatar_rect.top()
    assert other_layout.bubble_rect.top() - other_layout.avatar_rect.top() == delegate._group_sender_label_height() + delegate.GROUP_SENDER_LABEL_GAP
    assert self_layout.bubble_rect.top() - self_layout.avatar_rect.top() == delegate._group_sender_label_height() + delegate.GROUP_SENDER_LABEL_GAP


def test_message_delegate_group_recall_notice_prefers_group_nickname_over_remark() -> None:
    delegate = MessageDelegate()
    session = Session(
        session_id='group-1',
        name='',
        session_type='group',
        participant_ids=['me', 'user-2'],
        extra={
            'current_user_id': 'me',
            'show_member_nickname': True,
            'members': [
                {'id': 'me', 'nickname': 'Me'},
                {'id': 'user-2', 'group_nickname': '群内名', 'remark': '备注名', 'nickname': '用户昵称'},
            ],
        },
    )
    delegate.set_session(session)
    message = ChatMessage(
        message_id='msg-1',
        session_id='group-1',
        sender_id='user-2',
        content='对方撤回了一条消息',
        message_type=MessageType.SYSTEM,
        status=MessageStatus.RECALLED,
        extra={
            'sender_name': '备注名',
            'sender_nickname': '用户昵称',
        },
    )

    assert delegate._recall_notice_text(message) == tr(
        "message.recalled.by",
        "{name} recalled a message",
        name='“群内名”',
    )


def test_session_manager_self_group_profile_updates_current_member_nickname(monkeypatch) -> None:
    fake_db = _FakeDatabase({})

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
                    {'id': 'me', 'nickname': 'Me', 'group_nickname': ''},
                    {'id': 'user-2', 'nickname': 'Nick 2'},
                ],
            },
        )

        changed = await manager._merge_group_payload_into_session(
            session,
            {'my_group_nickname': 'Lead'},
            {'id': 'me'},
            include_self_fields=True,
        )

        assert changed is True
        assert session.extra['my_group_nickname'] == 'Lead'
        assert session.extra['members'][0]['group_nickname'] == 'Lead'

    asyncio.run(scenario())


def test_session_manager_self_group_profile_update_preserves_shared_group_metadata(monkeypatch) -> None:
    fake_db = _FakeDatabase({})

    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: object())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = Session(
            session_id='group-1',
            name='Core Team',
            session_type='group',
            participant_ids=['me', 'user-2'],
            avatar='/uploads/group.png',
            extra={
                'group_id': 'group-42',
                'server_name': 'Core Team',
                'members': [
                    {'id': 'me', 'nickname': 'Me', 'group_nickname': ''},
                    {'id': 'user-2', 'nickname': 'Nick 2'},
                ],
            },
        )

        changed = await manager._merge_group_payload_into_session(
            session,
            {'group_note': 'private note', 'my_group_nickname': 'Lead'},
            {'id': 'me'},
            include_self_fields=True,
        )

        assert changed is True
        assert session.name == 'Core Team'
        assert session.avatar == '/uploads/group.png'
        assert session.extra['server_name'] == 'Core Team'
        assert session.extra['group_id'] == 'group-42'
        assert session.extra['group_note'] == 'private note'
        assert session.extra['my_group_nickname'] == 'Lead'

    asyncio.run(scenario())


def test_session_manager_select_session_clears_group_mention_attention(monkeypatch) -> None:
    fake_db = _FakeDatabase({})
    fake_event_bus = _FakeEventBus()

    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: object())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = Session(
            session_id='group-1',
            name='Core Team',
            session_type='group',
            participant_ids=['me', 'user-2'],
            extra={'last_message_mentions_current_user': True},
        )
        manager._sessions[session.session_id] = session

        await manager.select_session(session.session_id)

        assert session.extra['last_message_mentions_current_user'] is False
        assert any(event == session_manager_module.SessionEvent.UPDATED for event, _payload in fake_event_bus.emitted)

    asyncio.run(scenario())


def test_session_manager_active_session_does_not_keep_group_mention_attention(monkeypatch) -> None:
    fake_db = _FakeDatabase({})

    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: _FakeEventBus())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: object())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        manager._current_session_id = 'group-1'
        manager._current_session_active = True
        session = Session(
            session_id='group-1',
            name='Core Team',
            session_type='group',
            participant_ids=['me', 'user-2'],
        )
        message = ChatMessage(
            message_id='msg-mention',
            session_id='group-1',
            sender_id='user-2',
            content='@Me hello',
            message_type=MessageType.TEXT,
            status=MessageStatus.SENT,
            extra={'mentions': [{'start': 0, 'end': 3, 'display_name': 'Me', 'mention_type': 'member', 'member_id': 'me'}]},
        )

        manager._apply_last_message_preview(session, message, current_user_id='me')

        assert session.extra['last_message_mentions_current_user'] is False

    asyncio.run(scenario())


def test_session_manager_uses_runtime_user_id_for_group_mentions(monkeypatch) -> None:
    fake_db = _FakeDatabase({})

    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: _FakeEventBus())
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: object())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        manager.set_user_id('me')
        session = Session(
            session_id='group-1',
            name='Core Team',
            session_type='group',
            participant_ids=['me', 'user-2'],
        )
        message = ChatMessage(
            message_id='msg-mention',
            session_id='group-1',
            sender_id='user-2',
            content='@Me hello',
            message_type=MessageType.TEXT,
            status=MessageStatus.SENT,
            extra={'mentions': [{'start': 0, 'end': 3, 'display_name': 'Me', 'mention_type': 'member', 'member_id': 'me'}]},
        )

        manager._apply_last_message_preview(session, message, current_user_id=await manager._get_current_user_id())

        assert session.extra['last_message_mentions_current_user'] is True

    asyncio.run(scenario())


def test_session_manager_set_user_id_recomputes_cached_group_mentions(monkeypatch) -> None:
    mention_message = ChatMessage(
        message_id='msg-mention',
        session_id='group-1',
        sender_id='user-2',
        content='@Me hello',
        message_type=MessageType.TEXT,
        status=MessageStatus.RECEIVED,
        extra={'mentions': [{'start': 0, 'end': 3, 'display_name': 'Me', 'mention_type': 'member', 'member_id': 'me'}]},
    )
    fake_db = _FakeDatabase({}, messages_by_session={'group-1': mention_message})
    fake_event_bus = _FakeEventBus()

    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: object())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        manager._initialized = True
        session = Session(
            session_id='group-1',
            name='Core Team',
            session_type='group',
            participant_ids=['me', 'user-2'],
            extra={'last_message_mentions_current_user': False},
        )
        manager._sessions[session.session_id] = session

        manager.set_user_id('me')
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert session.extra['last_message_mentions_current_user'] is True
        assert any(event == session_manager_module.SessionEvent.UPDATED for event, _payload in fake_event_bus.emitted)

    asyncio.run(scenario())


def test_session_manager_carries_group_mention_state_by_last_message_id() -> None:
    source = Session(
        session_id='group-1',
        name='Source',
        session_type='group',
        participant_ids=['me', 'user-2'],
        last_message='old preview',
        extra={
            'last_message_id': 'msg-1',
            'last_message_sender_id': 'user-2',
            'last_message_mentions_current_user': True,
        },
    )
    target = Session(
        session_id='group-1',
        name='Target',
        session_type='group',
        participant_ids=['me', 'user-2'],
        last_message='new preview text',
        extra={
            'last_message_id': 'msg-1',
            'last_message_sender_id': 'user-2',
        },
    )

    session_manager_module.SessionManager._carry_local_session_state(target, source)

    assert target.extra['last_message_mentions_current_user'] is True


def test_message_model_replace_message_rebuilds_recall_notice_with_recalled_content() -> None:
    model = MessageModel()
    message = ChatMessage(
        message_id='msg-1',
        session_id='session-1',
        sender_id='me',
        content='hello world',
        message_type=MessageType.TEXT,
        status=MessageStatus.SENT,
        is_self=True,
    )
    model.set_messages([message])

    recalled = ChatMessage(
        message_id='msg-1',
        session_id='session-1',
        sender_id='me',
        content='你撤回了一条消息',
        message_type=MessageType.TEXT,
        status=MessageStatus.RECALLED,
        is_self=True,
        extra={'recalled_content': 'hello world', 'recall_notice': '你撤回了一条消息'},
    )

    model.replace_message(recalled)

    display_item = model.data(model.index(1, 0), MessageModel.MessageRole)
    display_message = model.data(model.index(1, 0),  Qt.ItemDataRole.UserRole)
    assert display_item['status'] == MessageStatus.RECALLED.value
    assert display_message.extra['recalled_content'] == 'hello world'

def test_group_announcement_view_state_tracks_announcement_message_version() -> None:
    session = Session(
        session_id='group-announce',
        name='Core Team',
        session_type='group',
        extra={
            'group_announcement': 'Ship 2.0 tonight',
            'announcement_message_id': 'msg-announce-1',
        },
    )

    assert session.group_announcement_needs_view() is True
    session.extra['last_viewed_announcement_message_id'] = 'msg-announce-1'
    assert session.group_announcement_needs_view() is False


def test_session_manager_marks_group_announcement_viewed(monkeypatch) -> None:
    fake_db = _FakeDatabase({})
    fake_event_bus = _FakeEventBus()

    monkeypatch.setattr(session_manager_module, 'get_database', lambda: fake_db)
    monkeypatch.setattr(session_manager_module, 'get_session_service', lambda: object())
    monkeypatch.setattr(session_manager_module, 'get_event_bus', lambda: fake_event_bus)
    monkeypatch.setattr(session_manager_module, 'get_message_manager', lambda: object())

    async def scenario() -> None:
        manager = session_manager_module.SessionManager()
        session = Session(
            session_id='group-announce',
            name='Core Team',
            session_type='group',
            extra={
                'group_announcement': 'Ship 2.0 tonight',
                'announcement_message_id': 'msg-announce-1',
            },
        )
        manager._sessions[session.session_id] = session

        updated = await manager.mark_group_announcement_viewed(session.session_id, 'msg-announce-1')

        assert updated is session
        assert session.extra['last_viewed_announcement_message_id'] == 'msg-announce-1'
        assert fake_db.saved_sessions[-1] is session
        assert any(event == session_manager_module.SessionEvent.UPDATED for event, _payload in fake_event_bus.emitted)

    asyncio.run(scenario())
