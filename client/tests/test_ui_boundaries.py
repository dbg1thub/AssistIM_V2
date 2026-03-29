from pathlib import Path


def test_ui_does_not_emit_session_updated_events_directly() -> None:
    session_panel = Path('client/ui/widgets/session_panel.py').read_text(encoding='utf-8')
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')

    assert 'emit_sync(SessionEvent.UPDATED' not in session_panel
    assert 'emit_sync(SessionEvent.UPDATED' not in chat_interface


def test_group_creation_dialogs_are_split_out_of_contact_interface() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')

    assert 'class StartGroupChatDialog' not in contact_interface
    assert 'class CreateGroupDialog' not in contact_interface
    assert 'from client.ui.windows.group_creation_dialogs import CreateGroupDialog' in contact_interface
    assert 'from client.ui.windows.contact_interface import StartGroupChatDialog' not in chat_interface
    assert 'from client.ui.windows.chat_group_flow import ChatGroupFlowCoordinator' in chat_interface


def test_group_flow_no_longer_writes_local_group_avatar_metadata() -> None:
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')
    group_flow = Path('client/ui/windows/chat_group_flow.py').read_text(encoding='utf-8')
    group_dialogs = Path('client/ui/windows/group_creation_dialogs.py').read_text(encoding='utf-8')

    assert 'session_controller=self._session_controller' not in chat_interface
    assert 'update_group_session_metadata' not in group_flow
    assert 'build_group_avatar_path' not in group_dialogs
    assert 'extra["avatar"]' not in group_dialogs


def test_chat_interface_group_creation_flow_is_delegated_to_coordinator() -> None:
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')

    assert 'self._group_flow = ChatGroupFlowCoordinator(' in chat_interface
    assert 'def _show_start_group_dialog' not in chat_interface
    assert 'def _on_group_chat_created' not in chat_interface
    assert 'def _open_created_group_session' not in chat_interface


def test_contact_interface_request_and_group_actions_avoid_full_reload() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')

    assert contact_interface.count('self.reload_data()') == 1
    assert 'await self._refresh_contacts_and_requests(' in contact_interface
    assert 'await self._refresh_requests_only(' in contact_interface
    assert 'self._groups.append(created_group)' in contact_interface


def test_auth_success_feedback_moves_to_main_window() -> None:
    auth_interface = Path('client/ui/windows/auth_interface.py').read_text(encoding='utf-8')
    app_main = Path('client/main.py').read_text(encoding='utf-8')

    assert 'InfoBar.success(tr("auth.feedback.title", "Authentication"), message, parent=self.form_card)' not in auth_interface
    assert 'self.last_success_message =' in auth_interface
    assert 'self._pending_auth_success_message' in app_main
    assert 'InfoBar.success(' in app_main
