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


def test_session_ui_uses_local_added_event_instead_of_created_lifecycle_name() -> None:
    session_manager = Path('client/managers/session_manager.py').read_text(encoding='utf-8')
    session_panel = Path('client/ui/widgets/session_panel.py').read_text(encoding='utf-8')
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')

    assert 'ADDED = "session_added"' in session_manager
    assert 'CREATED = "session_created"' not in session_manager
    assert 'SessionEvent.ADDED' in session_panel
    assert 'SessionEvent.CREATED' not in session_panel
    assert 'SessionEvent.ADDED' in chat_interface
    assert 'SessionEvent.CREATED' not in chat_interface


def test_session_ui_applies_authoritative_empty_snapshots_instead_of_ignoring_them() -> None:
    session_panel = Path('client/ui/widgets/session_panel.py').read_text(encoding='utf-8')
    session_block = session_panel.split('def _on_session_updated', 1)[1].split('def _on_session_deleted', 1)[0]

    assert 'if isinstance(sessions, list):' in session_block
    assert 'if sessions:' not in session_block



def test_chat_interface_clears_stale_current_session_after_authoritative_snapshot_drop() -> None:
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')
    session_block = chat_interface.split('def _on_session_event', 1)[1].split('def _on_message_sent', 1)[0]

    assert 'if isinstance(sessions, list):' in session_block
    assert 'current_session = next(' in session_block
    assert 'if current_session is None:' in session_block
    assert 'self._current_session_id = None' in session_block
    assert 'self.chat_panel.show_welcome()' in session_block



def test_chat_interface_group_creation_flow_is_delegated_to_coordinator() -> None:
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')

    assert 'self._group_flow = ChatGroupFlowCoordinator(' in chat_interface
    assert 'def _show_start_group_dialog' not in chat_interface
    assert 'def _on_group_chat_created' not in chat_interface
    assert 'def _open_created_group_session' not in chat_interface


def test_call_result_messages_are_sent_as_text_not_client_system_messages() -> None:
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')
    call_result_block = chat_interface.split('async def _send_call_result_message', 1)[1].split(
        'def _call_duration_seconds',
        1,
    )[0]

    assert 'message_type=MessageType.TEXT' in call_result_block
    assert 'message_type=MessageType.SYSTEM' not in call_result_block


def test_call_result_message_dedupe_cache_is_bounded() -> None:
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')

    assert 'CALL_RESULT_DEDUPE_LIMIT = 256' in chat_interface
    assert 'CALL_RESULT_DEDUPE_TTL_SECONDS = 3600' in chat_interface
    assert 'def _prune_call_result_messages_sent(self) -> None:' in chat_interface
    assert 'while len(self._call_result_messages_sent) > self.CALL_RESULT_DEDUPE_LIMIT:' in chat_interface


def test_chat_interface_typing_indicator_ignores_self_and_hides_on_explicit_stop() -> None:
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')
    typing_block = chat_interface.split('def _on_typing_event', 1)[1].split('def _on_read_event', 1)[0]

    assert 'if user_id == self._current_user_id():' in typing_block
    assert 'if typing:' in typing_block
    assert 'self._typing_indicator_timer.stop()' in typing_block
    assert 'self.chat_panel.hide_typing_indicator()' in typing_block


def test_chat_interface_session_open_and_history_tasks_are_generation_guarded() -> None:
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')

    assert 'self._session_focus_generation = 0' in chat_interface
    assert 'def _advance_session_focus_generation(self) -> int:' in chat_interface
    assert 'def _is_session_focus_generation_current(self, generation: int) -> bool:' in chat_interface
    assert 'def _is_current_session_context(self, session_id: str, generation: int) -> bool:' in chat_interface
    assert 'generation = self._advance_session_focus_generation()' in chat_interface
    assert 'async def _open_sidebar_search_result(self, payload: object, generation: int) -> None:' in chat_interface
    assert 'opened = await self.open_group_session(session_id, generation=generation)' in chat_interface
    assert 'opened = await self.open_session(session_id, generation=generation)' in chat_interface
    assert 'generation=generation,' in chat_interface
    assert 'self._set_load_task(self._select_session_only(session_id, generation), f"select session {session_id}")' in chat_interface
    assert 'self._set_load_task(self._load_session_messages(session_id, generation), f"load session {session_id}")' in chat_interface
    assert 'async def _load_session_messages(self, session_id: str, generation: int) -> None:' in chat_interface
    assert 'async def _select_session_only(self, session_id: str, generation: int) -> None:' in chat_interface
    assert 'async def _load_older_messages(self, session_id: str, generation: int) -> None:' in chat_interface
    assert 'generation = self._session_focus_generation' in chat_interface
    assert 'async def _send_read_receipt_for(self, session_id: str, message_id: str, generation: int) -> None:' in chat_interface
    assert 'async def open_session(self, session_id: str, *, generation: int | None = None) -> bool:' in chat_interface
    assert 'async def open_group_session(self, session_id: str, *, generation: int | None = None) -> bool:' in chat_interface
    assert 'generation: int | None = None,' in chat_interface
    assert 'if not self._is_session_focus_generation_current(open_generation):' in chat_interface
    assert chat_interface.count('if not self._is_current_session_context(session_id, generation):') >= 6


def test_chat_interface_call_dialog_and_menu_callbacks_are_instance_guarded() -> None:
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')

    assert 'self._ui_callback_generation = 0' in chat_interface
    assert 'def _invalidate_ui_callback_generation(self) -> None:' in chat_interface
    assert 'def _make_generation_bound_ui_callback(self, callback, *, generation: int | None = None):' in chat_interface
    assert 'def _schedule_ui_single_shot(self, delay: int, callback, *, generation: int | None = None) -> None:' in chat_interface
    assert chat_interface.count('QTimer.singleShot(') == 1
    assert 'self._schedule_ui_single_shot(0, self.session_panel._relayout_session_list)' in chat_interface
    assert 'self._schedule_ui_single_shot(0, self.chat_panel._relayout_message_list)' in chat_interface
    assert 'overlay.captured.connect(lambda file_path, current=overlay: self._handle_screenshot_captured(file_path, current))' in chat_interface
    assert 'overlay.canceled.connect(lambda current=overlay: self._discard_screenshot_overlay(current))' in chat_interface
    assert 'def _handle_screenshot_captured(self, file_path: str, source_overlay: ScreenshotOverlay) -> None:' in chat_interface
    assert 'if source_overlay not in self._screenshot_overlays:' in chat_interface
    assert 'toast.accepted.connect(lambda active_call=call, ref=toast: self._accept_incoming_call_from_toast(active_call, ref))' in chat_interface
    assert 'toast.rejected.connect(lambda cid=call.call_id, ref=toast: self._reject_incoming_call_from_toast(cid, ref))' in chat_interface
    assert 'def _accept_incoming_call_from_toast(self, call: ActiveCallState, source_toast: IncomingCallToast) -> None:' in chat_interface
    assert 'def _reject_incoming_call_from_toast(self, call_id: str, source_toast: IncomingCallToast) -> None:' in chat_interface
    assert 'self._schedule_ui_single_shot(self.CALL_INCOMING_RING_RETRY_MS, self._retry_incoming_ring_sound)' in chat_interface
    assert '_prepare_current_call_window_media' not in chat_interface
    assert '_prepare_incoming_call_window' not in chat_interface
    assert 'window.hangup_requested.connect(lambda call_id, ref=window: self._on_call_window_hangup_requested(call_id, ref))' in chat_interface
    assert 'def _on_call_window_hangup_requested(self, call_id: str, source_window: CallWindow) -> None:' in chat_interface
    assert 'def _on_call_window_signal_generated(self, event_type: str, payload: object, source_window: CallWindow) -> None:' in chat_interface
    assert chat_interface.count('if self._call_window is not source_window:') == 2
    assert 'if self._message_context_menu is not menu:' in chat_interface


def test_chat_interface_async_message_action_results_are_session_generation_guarded() -> None:
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')

    assert 'def _is_current_message_context(self, message, generation: int) -> bool:' in chat_interface
    assert 'async def _send_image_message(self, session_id: str, file_path: str, generation: int) -> None:' in chat_interface
    assert 'if message and self._is_current_session_context(session_id, generation):' in chat_interface
    assert 'self._send_image_message(self._current_session_id, file_path, generation)' in chat_interface
    assert 'def _open_message(self, message, generation: int | None = None) -> None:' in chat_interface
    assert 'current_generation = self._session_focus_generation if generation is None else generation' in chat_interface
    assert 'if not self._is_current_message_context(message, current_generation):' in chat_interface
    assert 'async def _open_file_attachment(self, message, generation: int) -> None:' in chat_interface
    assert chat_interface.count('if not self._is_current_message_context(message, generation):') >= 4
    assert 'async def _retry_message(self, message_id: str, session_id: str, generation: int) -> None:' in chat_interface
    assert 'async def _recall_message(self, message_id: str, session_id: str, generation: int) -> None:' in chat_interface
    assert 'def _confirm_delete_message(self, message, generation: int) -> None:' in chat_interface
    assert 'async def _delete_message(self, message, generation: int) -> None:' in chat_interface
    assert 'self._delete_message(message, generation)' in chat_interface
    assert 'async def _confirm_security_pending_messages(self, session_id: str, action_id: str, generation: int) -> None:' in chat_interface
    assert 'async def _discard_security_pending_messages(self, session_id: str, generation: int) -> None:' in chat_interface
    assert chat_interface.count('if not self._is_current_session_context(session_id, generation):') >= 8
    assert 'if not self._is_current_session_context(session_id, generation):' in chat_interface
    assert 'chat.security_pending.discard_empty' in chat_interface
    assert 'chat.security_pending.release_empty' in chat_interface


def test_contact_interface_request_and_group_actions_avoid_full_reload() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')

    assert contact_interface.count('self.reload_data()') == 2
    assert 'self._controller.merge_group_record(self._groups, group)' in contact_interface
    assert 'self._build_groups_page()' in contact_interface
    assert 'def _refresh_contacts_and_requests(' not in contact_interface
    assert 'def _refresh_requests_only(' not in contact_interface
    assert 'await self._refresh_contacts_and_requests(focus_page="friends", focus_friend_id=counterpart_id)' not in contact_interface
    assert 'await self._refresh_requests_only()' not in contact_interface


def test_auth_success_feedback_moves_to_main_window() -> None:
    auth_interface = Path('client/ui/windows/auth_interface.py').read_text(encoding='utf-8')
    app_main = Path('client/main.py').read_text(encoding='utf-8')
    main_window = Path('client/ui/windows/main_window.py').read_text(encoding='utf-8')
    warmup_block = app_main.split('async def _warm_authenticated_runtime', 1)[1].split('async def show_main_window', 1)[0]
    show_block = app_main.split('async def show_main_window', 1)[1].split('def _on_main_window_closed', 1)[0]

    assert 'InfoBar.success(tr("auth.feedback.title", "Authentication"), message, parent=self.form_card)' not in auth_interface
    assert 'self.last_success_message =' in auth_interface
    assert 'self._pending_auth_success_message' in app_main
    assert 'InfoBar.success(' in warmup_block
    assert 'InfoBar.warning(' in warmup_block
    assert 'retry_button = QPushButton(tr("common.retry", "Retry"), self.main_window)' in warmup_block
    assert 'main_window.runtimeRefreshRequested.connect(' in app_main
    assert 'lambda window=main_window: self.retry_authenticated_runtime(source_window=window)' in app_main
    assert 'InfoBar.success(' not in show_block
    assert 'self.contact_interface.reload_data()' not in main_window
    assert 'self.contact_interface.refresh_profile_related_slices()' in main_window
    assert 'runtimeRefreshRequested = Signal()' in main_window
    assert 'Action(AppIcon.SYNC, tr("main_window.refresh_connection", "Refresh Connection"), self)' in main_window
    assert 'self._make_generation_bound_main_window_callback' in app_main
    assert 'main_window.closed.connect(lambda window=main_window: self._on_main_window_closed(window))' in app_main
    assert 'main_window.logoutRequested.connect(lambda window=main_window: self._on_logout_requested(window))' in app_main
    assert 'self.main_window.quiesce()' in app_main
    assert 'def quiesce(self) -> None:' in main_window


def test_shell_transition_uses_formal_close_path_and_blocks_tray_restore() -> None:
    auth_interface = Path('client/ui/windows/auth_interface.py').read_text(encoding='utf-8')
    app_main = Path('client/main.py').read_text(encoding='utf-8')
    main_window = Path('client/ui/windows/main_window.py').read_text(encoding='utf-8')

    assert 'self.authenticated.emit(user)\n            self.close()' not in auth_interface
    assert 'if not self._auth_committed:\n                self._set_busy(None)' in auth_interface
    assert 'if self._shell_transition_active or self._teardown_started:' in main_window
    assert 'def begin_runtime_transition(self) -> None:' in main_window
    assert 'def close_for_runtime_transition(self) -> None:' in main_window
    assert 'self._request_close("runtime_transition")' in main_window
    assert 'if self._close_reason != "runtime_transition":\n                self.closed.emit()' in main_window
    assert 'self.main_window.begin_runtime_transition()' in app_main
    assert 'self.main_window.close_for_runtime_transition()' in app_main


def test_auth_commit_is_two_phase_and_login_close_is_blocked_during_commit() -> None:
    auth_interface = Path('client/ui/windows/auth_interface.py').read_text(encoding='utf-8')
    auth_controller = Path('client/ui/controllers/auth_controller.py').read_text(encoding='utf-8')

    assert 'self._submit_commit_in_progress = False' in auth_interface
    assert 'payload = await self._auth_controller.request_login_payload(username, password, force=force)' in auth_interface
    assert 'user = await self._auth_controller.commit_auth_payload(payload, reset_local_chat_state=True)' in auth_interface
    assert 'payload = await self._auth_controller.request_register_payload(username, nickname, password)' in auth_interface
    assert 'if self._submit_commit_in_progress:' in auth_interface
    assert 'event.ignore()' in auth_interface
    assert 'async def request_login_payload(self, username: str, password: str, *, force: bool = False) -> dict[str, Any]:' in auth_controller
    assert 'async def request_register_payload(self, username: str, nickname: str, password: str) -> dict[str, Any]:' in auth_controller
    assert 'async def commit_auth_payload(' in auth_controller


def test_auth_commit_no_longer_pushes_user_id_into_closed_runtime_singletons() -> None:
    auth_controller = Path('client/ui/controllers/auth_controller.py').read_text(encoding='utf-8')

    apply_runtime_context = auth_controller.split('def _apply_runtime_context', 1)[1].split('def _notify_auth_state_changed', 1)[0]
    assert 'self._set_runtime_user_id(user_id)' not in apply_runtime_context
    assert 'def _set_runtime_user_id(user_id: str) -> None:' in auth_controller
    assert 'self._set_runtime_user_id("")' in auth_controller


def test_startup_runtime_failure_now_has_user_visible_dialog() -> None:
    app_main = Path('client/main.py').read_text(encoding='utf-8')

    assert 'EXIT_CODE_STARTUP_RUNTIME_FAILED = 3' in app_main
    assert 'def _show_startup_runtime_failure_dialog(stage: str, detail: str = "") -> None:' in app_main
    assert 'startup_stage in {"authenticate", "authenticated_runtime"} and self.main_window is None' in app_main
    assert '_show_startup_runtime_failure_dialog(' in app_main


def test_logout_quiesce_is_pushed_down_into_shell_widgets() -> None:
    main_window = Path('client/ui/windows/main_window.py').read_text(encoding='utf-8')
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')
    discovery_interface = Path('client/ui/windows/discovery_interface.py').read_text(encoding='utf-8')
    session_panel = Path('client/ui/widgets/session_panel.py').read_text(encoding='utf-8')
    profile_flyout = Path('client/ui/widgets/user_profile_flyout.py').read_text(encoding='utf-8')

    assert 'self.user_profile.quiesce()' in main_window
    assert 'self.chat_interface.quiesce()' in main_window
    assert 'self.contact_interface.quiesce()' in main_window
    assert 'self.discovery_interface.quiesce()' in main_window
    assert 'def quiesce(self) -> None:' in chat_interface
    assert 'self.session_panel.quiesce()' in chat_interface
    assert 'def quiesce(self) -> None:' in contact_interface
    assert 'def quiesce(self) -> None:' in discovery_interface
    assert 'def quiesce(self) -> None:' in session_panel
    assert 'def quiesce(self) -> None:' in profile_flyout


def test_user_profile_flyout_surfaces_degraded_session_snapshot_after_profile_save() -> None:
    flyout = Path('client/ui/widgets/user_profile_flyout.py').read_text(encoding='utf-8')
    save_block = flyout.split('async def _save_profile_async', 1)[1].split('def _emit_profile_changed', 1)[0]

    assert 'update_result = await self._auth_controller.update_profile(' in save_block
    assert 'user = dict(update_result.user or {})' in save_block
    assert 'snapshot = update_result.session_snapshot' in save_block
    assert 'if snapshot is not None and not snapshot.authoritative:' in save_block
    assert 'elif snapshot is not None and not snapshot.unread_synchronized:' in save_block
    assert 'InfoBar.warning(' in save_block
    assert 'InfoBar.info(' in save_block
    assert 'InfoBar.success(' in save_block



def test_message_delegate_uses_live_auth_profile_for_self_avatar_rendering() -> None:
    message_delegate = Path('client/delegates/message_delegate.py').read_text(encoding='utf-8')

    assert 'if message.is_self:' in message_delegate
    assert 'sender_avatar = str(current_user.get("avatar", "") or "")' in message_delegate
    assert 'sender_gender = str(current_user.get("gender", "") or "")' in message_delegate
    assert 'sender_username = str(current_user.get("username", "") or "")' in message_delegate


def test_contact_interface_handles_user_profile_update_incrementally() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')

    assert 'if reason == "user_profile_update":' in contact_interface
    assert 'if reason == "group_profile_update":' in contact_interface
    assert 'if reason == "group_self_profile_update":' in contact_interface
    assert 'self._apply_profile_update_payload(dict(event_payload.get("payload") or {}))' in contact_interface
    assert 'self._apply_group_update_payload(dict(event_payload.get("payload") or {}))' in contact_interface
    assert 'self._apply_group_self_profile_update_payload(dict(event_payload.get("payload") or {}))' in contact_interface
    assert 'def refresh_profile_related_slices(self) -> None:' in contact_interface
    assert 'def _apply_profile_update_payload(self, payload: dict[str, object]) -> None:' in contact_interface
    assert 'def _apply_group_update_payload(self, payload: dict[str, object]) -> None:' in contact_interface
    assert 'def _apply_group_self_profile_update_payload(self, payload: dict[str, object]) -> None:' in contact_interface
    assert 'async def _refresh_profile_related_slices_async(self) -> None:' in contact_interface
    assert 'async def _refresh_contacts_and_requests_slices_async(self) -> None:' in contact_interface
    assert 'async def _refresh_requests_slice_async(self) -> None:' in contact_interface
    assert 'def _schedule_groups_cache_persist(self) -> None:' in contact_interface
    assert 'def _schedule_contacts_cache_persist(self) -> None:' in contact_interface
    assert 'self._controller.merge_group_record(self._groups, group_payload)' in contact_interface
    assert 'self._controller.apply_group_self_profile_update(self._groups, payload)' in contact_interface


def test_contact_interface_profile_update_avoids_unneeded_page_rebuilds() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')

    assert 'def _friend_sort_key(self, contact: ContactRecord) -> tuple[str, str]:' in contact_interface
    assert 'def _insert_friend_item_view(self, contact: ContactRecord) -> None:' in contact_interface
    assert 'def _remove_friend_item_view(self, contact_id: str) -> None:' in contact_interface
    assert 'def _remove_group_item_view(self, group_id: str) -> None:' in contact_interface
    assert 'if previous_sort_key != self._friend_sort_key(updated):' in contact_interface
    assert 'self._remove_friend_item_view(updated.id)' in contact_interface
    assert 'self._insert_friend_item_view(updated)' in contact_interface
    assert 'self._build_groups_page()' not in contact_interface.split('def _sync_group_record_view(self, group: GroupRecord, *, rebuild: bool) -> None:')[1].split('def _apply_group_update_payload', 1)[0]
    assert 'self._remove_group_item_view(group.id)' in contact_interface
    assert 'self._insert_group_item_view(group)' in contact_interface
    assert 'if groups_changed and self._current_page == "groups":' not in contact_interface
    assert 'if requests_changed and self._current_page == "requests":' not in contact_interface


def test_contact_interface_request_actions_update_locally() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')

    assert 'def _request_record_from_payload(payload: dict[str, object]) -> FriendRequestRecord:' in contact_interface
    assert 'def _upsert_request_record(self, request: FriendRequestRecord) -> None:' in contact_interface
    assert 'def _upsert_contact_record(self, contact: ContactRecord, *, select_after_upsert: bool = False) -> None:' in contact_interface
    assert 'payload = await self._controller.accept_request(request_id)' in contact_interface
    assert 'payload = await self._controller.reject_request(request_id)' in contact_interface
    assert 'await self._refresh_contacts_and_requests(focus_page="friends", focus_friend_id=counterpart_id)' not in contact_interface
    assert 'await self._refresh_requests_only()' not in contact_interface
    assert 'self._requests = self._ordered_requests()' in contact_interface


def test_contact_interface_reloads_contact_domain_after_reconnect() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')

    assert 'self._connection_manager.add_state_listener(self._on_connection_state_changed)' in contact_interface
    assert 'def _on_connection_state_changed(self, old_state: ConnectionState, new_state: ConnectionState) -> None:' in contact_interface
    assert 'if old_state == ConnectionState.CONNECTED or new_state != ConnectionState.CONNECTED:' in contact_interface
    assert 'self.reload_data()' in contact_interface.split('def _on_connection_state_changed', 1)[1].split('def _can_update_contact_ui', 1)[0]
    assert 'self._connection_manager.remove_state_listener(self._on_connection_state_changed)' in contact_interface


def test_search_flyout_close_no_longer_clears_keywords() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')
    session_panel = Path('client/ui/widgets/session_panel.py').read_text(encoding='utf-8')

    contact_close_block = contact_interface.split('def _on_search_flyout_closed', 1)[1].split('@staticmethod', 1)[0]
    session_close_block = session_panel.split('def _on_search_flyout_closed', 1)[1].split('def _on_session_clicked', 1)[0]

    assert 'self.search_box.clear()' not in contact_close_block
    assert 'self.search_box.clear()' not in session_close_block


def test_request_list_item_rebuilds_actions_on_status_change() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')

    assert 'self.action_layout = QVBoxLayout()' in contact_interface
    assert 'def _render_actions(self) -> None:' in contact_interface
    assert 'self._render_actions()' in contact_interface


def test_contact_interface_add_friend_and_group_creation_insert_locally() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')

    assert 'def _insert_group_item_view(self, group: GroupRecord) -> None:' in contact_interface
    assert 'def _remove_group_item_view(self, group_id: str) -> None:' in contact_interface
    assert 'def _insert_request_item_view(self, request: FriendRequestRecord) -> None:' in contact_interface
    assert 'self._build_requests_page()' in contact_interface
    assert 'self._controller.merge_group_record(self._groups, group)' in contact_interface
    assert 'self._sync_group_record_view(created_group, rebuild=rebuild)' in contact_interface
    assert 'self._activate_page("requests")' in contact_interface


def test_add_friend_dialog_defers_close_until_inflight_mutation_finishes() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')

    add_friend_block = contact_interface.split('class AddFriendDialog', 1)[1].split('class ContactSidebar', 1)[0]
    assert 'self._deferred_close_requested = False' in add_friend_block
    assert 'if self._action_task is not None and not self._action_task.done():' in add_friend_block
    assert 'self.hide()' in add_friend_block
    assert 'event.ignore()' in add_friend_block
    assert 'def _finalize_deferred_close_if_needed(self) -> None:' in add_friend_block
    assert 'self._build_groups_page()' not in contact_interface.split('def _on_group_created(self, group: object) -> None:')[1]


def test_add_friend_dialog_emits_request_payload() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')

    assert 'friend_request_sent = Signal(object)' in contact_interface
    assert 'self.friend_request_sent.emit(dict(payload or {}))' in contact_interface


def test_contact_interface_friend_list_uses_sectioned_incremental_updates() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')

    assert 'self._friend_section_widgets: dict[str, QWidget] = {}' in contact_interface
    assert 'self._friend_section_layouts: dict[str, QVBoxLayout] = {}' in contact_interface
    assert 'self._friend_item_sections: dict[str, str] = {}' in contact_interface
    assert 'def _ensure_friend_section_view(self, letter: str) -> QVBoxLayout:' in contact_interface
    assert 'if not self._friend_items and not self._friend_section_widgets:' in contact_interface


def test_contact_interface_removes_dead_search_helper_and_reuses_item_factories() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')

    assert 'def _clear_search_results_view(self) -> None:' not in contact_interface
    assert 'item = self._create_group_item(group)' in contact_interface
    assert 'item = self._create_request_item(request)' in contact_interface


def test_contact_interface_search_and_tab_state_follow_local_domain_contracts() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')
    main_window = Path('client/ui/windows/main_window.py').read_text(encoding='utf-8')

    assert 'if key != self._current_page:\n            self._clear_active_selection()' in contact_interface
    assert 'def _clear_active_selection(self) -> None:' in contact_interface
    assert 'self._contacts = await self._controller.load_contacts()' not in contact_interface.split('async def _reload_data_async', 1)[1].split('def _rebuild_current_page', 1)[0]
    assert 'contacts = await self._controller.load_contacts()' in contact_interface
    assert 'groups = await self._controller.load_groups()' in contact_interface
    assert 'requests = await self._controller.load_requests()' in contact_interface
    assert 'if self._current_page == "requests":' in contact_interface.split('def _on_search_text_changed', 1)[1].split('def _trigger_global_search', 1)[0]
    assert 'self._build_requests_page()' in contact_interface.split('def _on_search_text_changed', 1)[1].split('def _trigger_global_search', 1)[0]
    assert 'self._activate_page("friends")' in contact_interface.split('def _on_search_result_activated', 1)[1]
    assert 'self._activate_page("groups")' in contact_interface.split('def _on_search_result_activated', 1)[1]
    assert 'routed_payload["_clear_contact_search"] = True' in contact_interface
    open_target_block = main_window.split('async def _open_contact_target', 1)[1].split('def _on_contact_message_requested', 1)[0]
    assert 'if hasattr(self, "switchTo"):' in open_target_block
    assert open_target_block.index('if not opened:') < open_target_block.index('if hasattr(self, "switchTo"):')
    assert 'self.contact_interface.clear_search()' in open_target_block


def test_request_detail_and_dialog_entry_points_use_authoritative_contact_semantics() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')
    contact_controller = Path('client/ui/controllers/contact_controller.py').read_text(encoding='utf-8')

    assert 'sender_username: str = ""' in contact_controller
    assert 'receiver_username: str = ""' in contact_controller
    assert 'sender_username=str(sender.get("username", "") or "")' in contact_controller
    assert 'receiver_username=str(receiver.get("username", "") or "")' in contact_controller
    assert 'request.sender_username if current_user_is_receiver else request.receiver_username' in contact_interface
    assert 'counterpart_username = (' in contact_interface
    assert 'self.message_button.setEnabled(self._entity is not None)' in contact_interface
    assert 'self._add_friend_dialog: AddFriendDialog | None = None' in contact_interface
    assert 'self._create_group_dialog: CreateGroupDialog | None = None' in contact_interface
    assert 'if self._raise_existing_dialog(self._add_friend_dialog):' in contact_interface
    assert 'if self._raise_existing_dialog(self._create_group_dialog):' in contact_interface


def test_chat_search_and_call_entry_points_hide_unwired_actions_and_keep_direct_context() -> None:
    chat_header = Path('client/ui/widgets/chat_header.py').read_text(encoding='utf-8')
    chat_info_drawer = Path('client/ui/widgets/chat_info_drawer.py').read_text(encoding='utf-8')
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')
    message_input = Path('client/ui/widgets/message_input.py').read_text(encoding='utf-8')
    group_dialogs = Path('client/ui/windows/group_creation_dialogs.py').read_text(encoding='utf-8')
    group_flow = Path('client/ui/windows/chat_group_flow.py').read_text(encoding='utf-8')
    search_manager = Path('client/managers/search_manager.py').read_text(encoding='utf-8')
    search_panel = Path('client/ui/widgets/global_search_panel.py').read_text(encoding='utf-8')

    assert 'self.history_button.hide()' in chat_header
    assert 'self.search_row.hide()' in chat_info_drawer
    assert 'self.clear_button.hide()' in chat_info_drawer
    assert 'self.summary_label.hide()' not in contact_interface
    assert 'def _update_call_buttons(self) -> None:' in message_input
    assert 'session.session_type == "direct"' in message_input
    assert 'not session.is_ai_session' in message_input
    assert 'self.voice_button.setVisible(supports_call)' in message_input
    assert 'self.video_button.setVisible(supports_call)' in message_input
    assert 'fixed_contact: ContactRecord | None' in group_dialogs
    assert 'self.refresh_button = PushButton(tr("common.refresh", "Refresh"), self.search_bar)' in group_dialogs
    assert 'self.refresh_button = PushButton(tr("common.refresh", "Refresh"), self)' in group_dialogs
    assert 'def _refresh_contacts_async(self) -> None:' in group_dialogs
    assert 'selected_ids.add(self._fixed_contact.id)' in group_dialogs
    assert 'removable = not (self._fixed_contact is not None and contact.id == self._fixed_contact.id)' in group_dialogs
    assert 'self._dialog_loading = False' in group_flow
    assert 'if self._raise_existing_dialog():' in group_flow
    assert 'fixed_contact = next((contact for contact in contacts if contact.id == counterpart_id), None)' in group_flow
    assert 'fixed_contact=fixed_contact' in group_flow
    assert 'count_messages = getattr(self._db, "count_search_message_sessions", None)' not in search_manager
    assert 'catalog.message_total = len(messages)' in search_manager
    assert 'catalog.contact_total = len(contacts)' in search_manager
    assert 'catalog.group_total = len(groups)' in search_manager
    assert 'meta=tr("search.message.total"' not in search_panel


def test_main_window_tray_alerts_respect_authoritative_mute_state() -> None:
    main_window = Path('client/ui/windows/main_window.py').read_text(encoding='utf-8')

    assert 'from client.managers.session_manager import SessionEvent, peek_session_manager' in main_window
    assert 'def _is_session_muted(self, session_id: str, session) -> bool:' in main_window
    assert 'return manager.is_session_muted(session_id)' in main_window
    assert 'if self._is_session_muted(session_id, session):' in main_window


def test_main_window_internal_delayed_callbacks_are_generation_and_instance_guarded() -> None:
    main_window = Path('client/ui/windows/main_window.py').read_text(encoding='utf-8')

    assert 'self._ui_callback_generation = 0' in main_window
    assert 'def _invalidate_ui_callback_generation(self) -> None:' in main_window
    assert 'def _make_generation_bound_ui_callback(self, callback, *, generation: int | None = None):' in main_window
    assert 'def _is_ui_callback_generation_current(self, generation: int) -> bool:' in main_window
    assert 'def _schedule_ui_single_shot(self, delay: int, callback, *, generation: int | None = None) -> None:' in main_window
    assert 'self._schedule_ui_single_shot(0, self.chat_interface.load_sessions)' in main_window
    assert 'self._schedule_ui_single_shot(0, self._sync_chat_session_activity)' in main_window
    assert main_window.count('self._schedule_ui_single_shot(100, lambda: self.windowEffect.setMicaEffect(self.winId(), isDarkTheme()))') == 2
    assert main_window.count('self._invalidate_ui_callback_generation()') >= 2
    assert 'self._force_logout_timer.timeout.connect(self._make_generation_bound_ui_callback(self._request_forced_exit))' in main_window
    assert 'self._force_logout_info_bar.closedSignal.connect(' in main_window
    assert 'view.hoverEntered.connect(lambda current=flyout: self._on_tray_flyout_hover_entered(current))' in main_window
    assert 'view.hoverLeft.connect(lambda current=flyout: self._on_tray_flyout_hover_left(current))' in main_window
    assert 'flyout.closed.connect(lambda current=flyout: self._clear_tray_flyout(current))' in main_window
    assert 'if source_flyout is not None and source_flyout is not self._tray_flyout:' in main_window
    assert 'if source_flyout is not None and not self._is_current_tray_flyout(source_flyout):' in main_window
    assert 'async def _open_tray_session(self, session_id: str, generation: int) -> None:' in main_window
    assert 'async def _open_contact_target(self, payload: object, generation: int) -> None:' in main_window
    assert 'self._create_ui_task(' in main_window
    assert 'generation=generation,' in main_window
    assert 'if generation is not None and not self._is_ui_callback_generation_current(generation):' in main_window
    assert main_window.count('if not self._is_ui_callback_generation_current(generation):') >= 4
    assert main_window.count('self._consume_ui_task_result(task, context)') >= 2


def test_session_delegate_reserves_preview_space_for_mute_icon() -> None:
    session_delegate = Path('client/delegates/session_delegate.py').read_text(encoding='utf-8')
    session_manager = Path('client/managers/session_manager.py').read_text(encoding='utf-8')
    server_session_schema = Path('server/app/schemas/session.py').read_text(encoding='utf-8')
    server_session_service = Path('server/app/services/session_service.py').read_text(encoding='utf-8')

    assert 'mute_slot_width = mute_icon_size + 8 if muted else 0' in session_delegate
    assert 'unread_badge_fm = QFontMetrics(unread_badge_font)' in session_delegate
    assert 'def _unread_badge_font() -> QFont:' in session_delegate
    assert 'def _attention_preview_prefix(self, session) -> str:' in session_delegate
    assert 'tr("session.preview.mentioned", "[Mentioned]")' in session_delegate
    assert 'avatar_rect.right() - unread_width + 7' in session_delegate
    assert 'QRect(content_left, preview_y - 1, preview_available, 28)' in session_delegate
    assert 'QRect(content_left + prefix_width, preview_y - 1, body_available, 28)' in session_delegate
    assert 'return "99+"' in session_delegate
    assert 'session.extra["last_message_id"] = str(message.message_id or "")' in session_manager
    assert 'source_last_message_id = str(source.extra.get("last_message_id", "") or "")' in session_manager
    assert 'last_message_id: str | None = None' in server_session_schema
    assert '"last_message_id": str(last_message.id or "") if last_message else None,' in server_session_service


def test_message_input_uses_acrylic_group_mention_flyout() -> None:
    message_input = Path('client/ui/widgets/message_input.py').read_text(encoding='utf-8')
    chat_panel = Path('client/ui/widgets/chat_panel.py').read_text(encoding='utf-8')
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')
    message_delegate = Path('client/delegates/message_delegate.py').read_text(encoding='utf-8')

    assert 'class GroupMentionFlyoutView(QWidget):' in message_input
    assert 'class GroupMentionPopupOverlay(QWidget):' in message_input
    assert 'class AcrylicTailSurface(QWidget):' not in message_input
    assert 'class AcrylicBridgeSurface(QWidget):' not in message_input
    assert 'class MentionAvatarWidget(QWidget):' in message_input
    assert 'self.surface = AcrylicDrawerSurface(self, radius=7)' in message_input
    assert 'self.surface.setObjectName("groupMentionSurface")' in message_input
    assert 'self.surface.set_border_object_name("groupMentionSurfaceBorder")' in message_input
    assert 'class MentionCandidateRow(QWidget):' in message_input
    assert 'AVATAR_RADIUS = 8' in message_input
    assert 'self.leading = MentionAvatarWidget(' in message_input
    assert 'self.setFixedWidth(self.PANEL_WIDTH)' in message_input
    assert 'PANEL_WIDTH = 116' in message_input
    assert 'class MentionToken:' in message_input
    assert 'def set_session(self, session: Session | None) -> None:' in message_input
    assert 'def _active_mention_context(self) -> tuple[int, int, str] | None:' in message_input
    assert 'def _handle_mention_key_event(self, event) -> bool:' in message_input
    assert 'def _insert_structured_mention(' in message_input
    assert 'segment["extra"] = {"mentions": mentions}' in message_input
    assert 'if event.type() == QEvent.Type.FocusOut:' not in message_input
    assert 'self._mention_flyout = AcrylicFlyout(self._mention_view, None)' not in message_input
    assert 'self._mention_flyout = GroupMentionPopupOverlay(host)' in message_input
    assert 'if mention_start > 0 and not prefix[mention_start - 1].isspace():' not in message_input
    assert 'self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)' in message_input
    assert 'QScrollArea#groupMentionScrollArea { background: transparent; border: none; }' in message_input
    assert 'self._mention_flyout.setFocusPolicy(Qt.FocusPolicy.NoFocus)' not in message_input
    assert 'self._mention_flyout.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)' not in message_input
    assert 'self._mention_flyout.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)' not in message_input
    assert 'if event.type() == QEvent.Type.FocusIn:' not in message_input
    assert 'center_x = anchor.x() + cursor_rect.width() // 2' not in message_input
    assert 'return QPoint(center_x - flyout_size.width() // 2, anchor.y() - flyout_size.height() - 12)' not in message_input
    assert 'self._mention_flyout.show_for_editor(self.text_input, self._mention_view)' in message_input
    assert 'self.document().contentsChange.connect(self._on_document_contents_change)' in message_input
    assert 'def _refresh_mention_selections(self) -> None:' in message_input
    assert 'def _mentions_for_segment(self, text: str, segment_fragments: list[dict[str, object]]) -> list[dict[str, object]]:' in message_input
    assert 'def _find_invalid_mention_fragment(self) -> tuple[int, str] | None:' not in message_input
    assert 'self.textChanged.connect(self._schedule_mention_format_sync)' not in message_input
    assert 'self.section_host = QWidget(self)' in message_input
    assert 'self.section_label = CaptionLabel(tr("composer.mention.members", "群成员"), self.section_host)' in message_input
    assert 'self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)' in message_input
    assert 'self.scroll_area.verticalScrollBar().installEventFilter(self)' in message_input
    assert 'def _set_scrollbar_visible(self, visible: bool) -> None:' in message_input
    assert 'self._show_everyone_row = False' in message_input
    assert 'self._show_member_label = False' in message_input
    assert 'self._visible_row_count = 0' in message_input
    assert 'everyone_height = self.ROW_HEIGHT if self._show_everyone_row else 0' in message_input
    assert 'self.tail = AcrylicTailSurface(self)' not in message_input
    assert 'self.bridge = AcrylicBridgeSurface(self)' not in message_input
    assert 'def _calculate_bridge_rect(self, panel_rect: QRect, tail_rect: QRect | None) -> QRect | None:' not in message_input
    assert 'self.bridge.capture_backdrop(' not in message_input
    assert 'self.tail.capture_backdrop(' not in message_input
    assert 'self._mention_view.set_candidates(filtered, show_member_label=show_member_label)' in message_input
    assert 'def set_selected(' not in message_input
    assert 'IconWidget(AppIcon.PEOPLE' not in message_input
    assert 'owner_id = str(getattr(session, "extra", {}).get("owner_id", "") or "").strip()' in message_input
    assert 'can_mention_everyone = current_role in {"owner", "admin"} or bool(owner_id and owner_id == current_user_id)' in message_input
    assert 'avatar=str(session.display_avatar() or session.avatar or "")' in message_input
    assert 'if normalized_query and matched_members:' in message_input
    assert 'filtered = ([everyone] if everyone is not None else []) + members' in message_input
    assert 'self.message_input.set_session(None)' in chat_panel
    assert 'self.message_input.set_session(session)' in chat_panel
    assert 'extra=segment.get("extra")' in chat_interface
    assert 'def _message_mention_ranges(message: ChatMessage) -> list[tuple[int, int]]:' in message_delegate


def test_chat_file_open_flow_routes_downloads_through_controller_boundary() -> None:
    chat_panel = Path('client/ui/widgets/chat_panel.py').read_text(encoding='utf-8')
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')
    chat_controller = Path('client/ui/controllers/chat_controller.py').read_text(encoding='utf-8')
    message_delegate = Path('client/delegates/message_delegate.py').read_text(encoding='utf-8')

    assert 'self._attachment_open_callback: Optional[Callable[[ChatMessage], None]] = None' in chat_panel
    assert 'def set_attachment_open_callback(self, callback: Callable[[ChatMessage], None] | None) -> None:' in chat_panel
    assert 'attachment_encryption = dict((message.extra or {}).get("attachment_encryption") or {})' in chat_panel
    assert 'if attachment_encryption.get("enabled") and self._attachment_open_callback is not None:' in chat_panel
    assert 'self.chat_panel.set_attachment_open_callback(self._open_message)' in chat_interface
    assert 'if attachment_encryption.get("enabled") and message.message_type in {' in chat_interface
    assert 'async def _open_file_attachment(self, message, generation: int) -> None:' in chat_interface
    assert 'await self._chat_controller.download_message_attachment(message.message_id)' in chat_interface
    assert 'async def download_message_attachment(self, message_id: str) -> str:' in chat_controller
    assert message_delegate.count('if attachment_encryption.get("enabled"):\n            return ""') >= 2
    assert 'self._subscribe_sync(MessageEvent.MEDIA_READY, self._on_media_ready)' in chat_interface
    assert 'self._subscribe_sync(MessageEvent.SECURITY_PENDING, self._on_message_sent)' in chat_interface
    assert 'def _on_media_ready(self, data: dict) -> None:' in chat_interface


def test_code_uses_half_width_parentheses_in_reviewed_paths() -> None:
    targets = [
        Path('client/models/message.py'),
        Path('client/ui/controllers/contact_controller.py'),
        Path('client/ui/widgets/message_input.py'),
        Path('client/ui/windows/main_window.py'),
        Path('client/delegates/session_delegate.py'),
    ]

    for path in targets:
        content = path.read_text(encoding='utf-8')
        assert '\uFF08' not in content
        assert '\uFF09' not in content


def test_chat_info_drawer_uses_hover_scrollbar_and_removes_group_fold_rows() -> None:
    drawer = Path('client/ui/widgets/chat_info_drawer.py').read_text(encoding='utf-8')

    assert 'self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)' in drawer
    assert 'self.scroll_area.setViewportMargins(0, 0, 0, 0)' in drawer
    assert 'self.scroll_area.setObjectName("chatInfoDrawerScrollArea")' in drawer
    assert 'self.scroll_area.viewport().setObjectName("chatInfoDrawerScrollViewport")' in drawer
    assert 'self.drawer.installEventFilter(self)' in drawer
    assert 'self.scroll_area.viewport().installEventFilter(self)' in drawer
    assert 'self.scroll_area.verticalScrollBar().installEventFilter(self)' in drawer
    assert 'def _set_scrollbar_visible(self, visible: bool) -> None:' in drawer
    assert 'def _sync_scrollbar_hover_state(self) -> None:' in drawer
    assert 'self.fold_row = ChatInfoActionRow' not in drawer
    assert 'self.save_contact_row = ChatInfoActionRow' not in drawer
    assert 'layout.addWidget(self.fold_row)' not in drawer
    assert 'layout.addWidget(self.save_contact_row)' not in drawer
    assert 'self.fold_row.set_checked' not in drawer
    assert 'self.save_contact_row.set_checked' not in drawer


def test_chat_info_drawer_avatars_are_rounded_rect_and_action_tiles_are_dashed() -> None:
    drawer = Path('client/ui/widgets/chat_info_drawer.py').read_text(encoding='utf-8')
    light_qss = Path('client/ui/styles/qss/light/chat_panel.qss').read_text(encoding='utf-8')
    dark_qss = Path('client/ui/styles/qss/dark/chat_panel.qss').read_text(encoding='utf-8')

    assert 'class ChatInfoAvatarWidget(QWidget):' in drawer
    assert 'class ChatInfoTileCard(QFrame):' in drawer
    assert 'def paintEvent(self, event) -> None:' in drawer.split('class ChatInfoTileCard(QFrame):', 1)[1]
    assert 'pen.setStyle(Qt.PenStyle.DashLine)' in drawer
    assert 'self.avatar = ChatInfoAvatarWidget(parent=self.card, size=44, radius=8)' in drawer
    assert 'self.avatar = ChatInfoAvatarWidget(parent=self, size=44, radius=9)' in drawer
    assert 'self.setFixedWidth(60)' in drawer
    assert 'self.card.setFixedSize(44, 44)' in drawer
    assert 'action_label=tr("chat.info.group.remove", "Remove")' in drawer
    assert 'remove_tile = ChatInfoParticipantTile(' in drawer
    assert 'QFrame#chatInfoParticipantCard {' in light_qss
    assert 'background: transparent;' in light_qss.split('QFrame#chatInfoParticipantCard {', 1)[1]
    assert 'border: none;' in light_qss.split('QFrame#chatInfoParticipantCard {', 1)[1]
    assert 'border-radius: 8px;' in light_qss.split('QFrame#chatInfoParticipantCard {', 1)[1]
    assert 'QFrame#chatInfoAddGlyph {' in light_qss
    assert 'border: 1px dashed rgba(0, 0, 0, 0.18);' in light_qss
    assert 'border-radius: 8px;' in light_qss.split('QFrame#chatInfoAddGlyph {', 1)[1]
    assert 'QFrame#chatInfoParticipantCard {' in dark_qss
    assert 'background: transparent;' in dark_qss.split('QFrame#chatInfoParticipantCard {', 1)[1]
    assert 'border: none;' in dark_qss.split('QFrame#chatInfoParticipantCard {', 1)[1]
    assert 'border-radius: 8px;' in dark_qss.split('QFrame#chatInfoParticipantCard {', 1)[1]
    assert 'border: 1px dashed rgba(255, 255, 255, 0.16);' in dark_qss
    assert 'border-radius: 8px;' in dark_qss.split('QFrame#chatInfoAddGlyph {', 1)[1]


def test_chat_info_detail_field_styles_match_drawer_requirements() -> None:
    drawer = Path('client/ui/widgets/chat_info_drawer.py').read_text(encoding='utf-8')
    light_qss = Path('client/ui/styles/qss/light/chat_panel.qss').read_text(encoding='utf-8')
    dark_qss = Path('client/ui/styles/qss/dark/chat_panel.qss').read_text(encoding='utf-8')

    assert 'class ChatInfoAnnouncementDialog(QDialog):' in drawer
    assert 'class ChatInfoAnnouncementPreview(CaptionLabel):' in drawer
    assert 'class ChatInfoAnnouncementField(QWidget):' in drawer
    assert 'valueCommitted = Signal(str)' in drawer
    assert 'self.editor = LineEdit(self)' in drawer
    assert 'self.editor.installEventFilter(self)' in drawer
    assert 'def eventFilter(self, watched, event) -> bool:' in drawer
    assert 'def _begin_edit(self) -> None:' in drawer
    assert 'def _commit_edit(self) -> None:' in drawer
    assert 'def set_editable(self, editable: bool) -> None:' in drawer
    assert 'self.title_label = BodyLabel(title, self)' in drawer
    assert 'self.value_label.installEventFilter(self)' in drawer
    assert 'self.title_label.setStyleSheet(' not in drawer
    assert 'self.group_name_field.valueCommitted.connect(self._emit_group_name_update)' in drawer
    assert 'self.announcement_field = ChatInfoAnnouncementField(tr("chat.info.group.announcement", "Announcement"), parent=self)' in drawer
    assert 'self.announcement_field.activated.connect(self._open_announcement_editor)' in drawer
    assert 'def _open_announcement_editor(self) -> None:' in drawer
    assert 'def _apply_announcement_value(self, value: str) -> None:' in drawer
    assert 'self.note_field.valueCommitted.connect(self._emit_note_update)' in drawer
    assert 'self.nickname_field.valueCommitted.connect(self._emit_nickname_update)' in drawer
    assert 'QLabel#chatInfoDetailFieldValue {' in light_qss
    assert 'color: #8A8A8A;' in light_qss
    assert 'QLineEdit#chatInfoDetailFieldEditor {' in light_qss
    assert 'QLabel#chatInfoDetailFieldValue {' in dark_qss
    assert 'color: rgba(196, 196, 196, 220);' in dark_qss
    assert 'QLineEdit#chatInfoDetailFieldEditor {' in dark_qss


def test_chat_info_action_rows_and_search_overlay_follow_drawer_rules() -> None:
    drawer = Path('client/ui/widgets/chat_info_drawer.py').read_text(encoding='utf-8')

    assert 'self.setCursor(Qt.PointingHandCursor)' in drawer
    assert 'self.title_label.setCursor(Qt.PointingHandCursor)' in drawer
    assert 'self.chevron_icon.setCursor(Qt.PointingHandCursor)' in drawer
    assert 'if self.chevron_icon is not None:' in drawer
    assert 'self.content_stack = QStackedWidget(self)' in drawer
    assert 'self.default_page = QWidget(self)' in drawer
    assert 'self.search_page = QWidget(self)' in drawer
    assert 'default_layout.setContentsMargins(0, 6, 0, 0)' in drawer
    assert 'layout.addWidget(self.content_stack, 1)' in drawer
    assert 'self.content_stack.setCurrentWidget(self.default_page)' in drawer
    assert 'self.content_stack.setCurrentWidget(self.search_page)' in drawer
    assert 'self.content_widget.refresh_visual_styles()' not in drawer
    assert 'self.search_row = ChatInfoActionRow(tr("chat.info.search", "Find Chat Content"), parent=self)' in drawer
    assert 'self.identity_row = ChatInfoActionRow(tr("chat.info.security", "Identity Verification"), parent=self)' in drawer
    assert 'self.clear_button.setText(tr("chat.info.clear", "Clear Chat History"))' in drawer
    assert 'self.show_nickname_row = ChatInfoActionRow(' in drawer
    assert 'self.view_more_button.setText(tr("chat.info.group.view_more", "View More Members"))' in drawer
    assert 'GroupMemberManagementRequest(' in drawer


def test_group_profile_realtime_pipeline_is_wired() -> None:
    message_manager = Path('client/managers/message_manager.py').read_text(encoding='utf-8')
    session_manager = Path('client/managers/session_manager.py').read_text(encoding='utf-8')
    connection_manager = Path('client/managers/connection_manager.py').read_text(encoding='utf-8')
    groups_api = Path('server/app/api/v1/groups.py').read_text(encoding='utf-8')
    group_service = Path('server/app/services/group_service.py').read_text(encoding='utf-8')

    assert 'GROUP_UPDATED = "message_group_updated"' in message_manager
    assert 'GROUP_SELF_UPDATED = "message_group_self_updated"' in message_manager
    assert 'elif msg_type == "group_profile_update":' in message_manager
    assert 'elif msg_type == "group_self_profile_update":' in message_manager
    assert 'await self._subscribe(MessageEvent.GROUP_UPDATED, self._on_group_updated)' in session_manager
    assert 'await self._subscribe(MessageEvent.GROUP_SELF_UPDATED, self._on_group_self_updated)' in session_manager
    assert 'elif msg_type in {"message_edit", "message_recall", "message_delete", "read", "group_profile_update", "group_self_profile_update"}:' in connection_manager
    assert 'async def _broadcast_group_profile_update' in groups_api
    assert 'async def _broadcast_group_self_profile_update' in groups_api
    assert 'def record_group_profile_update_event(' in group_service
    assert 'def build_group_self_profile_payload(' in group_service




def test_message_repo_event_sync_uses_uuid_column_comparisons() -> None:
    message_repo = Path('server/app/repositories/message_repo.py').read_text(encoding='utf-8')
    session_repo = Path('server/app/repositories/session_repo.py').read_text(encoding='utf-8')

    assert 'from sqlalchemy import and_, case, desc, func, select, update' in message_repo
    assert 'cast(' not in message_repo
    assert 'SessionEvent.session_id.in_(list(session_cursor_by_id))' in message_repo
    assert 'UserSessionEvent.session_id.in_(list(session_cursor_by_id))' in message_repo
    assert 'shared_cursor_expr = case(' in message_repo
    assert 'private_cursor_expr = case(' in message_repo
    assert 'UserSessionEvent.user_id == normalized_user_id' in message_repo
    assert 'from sqlalchemy import delete, select' in session_repo
    assert 'from app.models.session import ChatSession, SessionEvent, SessionMember, UserSessionEvent' in session_repo
    assert 'cast(' not in session_repo
    assert 'delete(SessionEvent).where(SessionEvent.session_id == normalized_session_id)' in session_repo
    assert 'delete(UserSessionEvent).where(UserSessionEvent.session_id == normalized_session_id)' in session_repo


def test_chat_interface_group_profile_updates_use_session_controller_boundary() -> None:
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')
    session_controller = Path('client/ui/controllers/session_controller.py').read_text(encoding='utf-8')
    session_manager = Path('client/managers/session_manager.py').read_text(encoding='utf-8')
    drawer = Path('client/ui/widgets/chat_info_drawer.py').read_text(encoding='utf-8')

    assert 'async def apply_group_payload(self, session_id: str, payload: dict[str, Any], *, include_self_fields: bool)' in session_controller
    assert 'async def apply_group_payload(' in session_manager
    assert 'class GroupProfileUpdateRequest:' in drawer
    assert 'class GroupSelfProfileUpdateRequest:' in drawer
    assert 'class GroupMemberManagementRequest:' in drawer
    assert 'await self._apply_group_record(request.session_id, record, include_self_fields=True)' in chat_interface
    assert 'def _on_chat_info_member_management_requested(self, payload: object) -> None:' in chat_interface
    assert 'async def _apply_group_management_record(self, session_id: str, record) -> None:' in chat_interface
    assert 'await self._session_controller.apply_group_payload(' in chat_interface
    assert 'ContactEvent.SYNC_REQUIRED' in chat_interface
    assert 'self._session_controller._session_manager.update_session(' not in chat_interface
    assert 'self.session_panel.update_session(' not in chat_interface.split('def _apply_group_record(', 1)[1]
    assert 'self.chat_panel.set_session(updated_session)' not in chat_interface.split('def _apply_group_record(', 1)[1]


def test_chat_info_member_management_uses_formal_dialog_boundary() -> None:
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')
    dialogs = Path('client/ui/windows/group_member_management_dialogs.py').read_text(encoding='utf-8')
    chat_panel = Path('client/ui/widgets/chat_panel.py').read_text(encoding='utf-8')
    drawer = Path('client/ui/widgets/chat_info_drawer.py').read_text(encoding='utf-8')
    session_controller = Path('client/ui/controllers/session_controller.py').read_text(encoding='utf-8')
    message_delegate = Path('client/delegates/message_delegate.py').read_text(encoding='utf-8')

    assert 'from client.ui.windows.group_member_management_dialogs import GroupMemberManagementDialog' in chat_interface
    assert 'self.chat_panel.chat_info_search_requested.connect(self._on_chat_info_search_requested)' in chat_interface
    assert 'self.chat_panel.chat_info_identity_review_requested.connect(self._on_chat_info_identity_review_requested)' in chat_interface
    assert 'self.chat_panel.chat_info_clear_requested.connect(self._on_chat_info_clear_requested)' in chat_interface
    assert 'self.chat_panel.chat_info_show_nickname_toggled.connect(self._on_chat_info_show_nickname_toggled)' in chat_interface
    assert 'self.chat_panel.chat_info_member_management_requested.connect(self._on_chat_info_member_management_requested)' in chat_interface
    assert 'dialog = GroupMemberManagementDialog(' in chat_interface
    assert 'def _show_dialog(self, dialog: QDialog) -> None:' in chat_interface
    assert 'self._session_controller.set_group_member_nickname_visibility(session_id, _enabled)' in chat_interface
    assert 'def _group_record_payload(record) -> dict[str, object]:' in chat_interface
    assert 'class GroupManagementPermissions:' in dialogs
    assert 'class GroupMemberManagementDialog(QDialog):' in dialogs
    assert 'can_add_members=is_owner' in dialogs
    assert 'can_manage_member_roles=is_owner' in dialogs
    assert 'can_transfer_owner=is_owner' in dialogs
    assert 'return self._session.authoritative_group_id()' in drawer
    assert 'self.group_name_field.set_value(session.authoritative_group_name())' in drawer
    assert 'self.announcement_field.set_preview_text(announcement_text)' in drawer
    assert 'self.preview_label = ChatInfoAnnouncementPreview(self)' in drawer
    assert 'async def set_group_member_nickname_visibility(self, session_id: str, enabled: bool) -> None:' in session_controller
    assert 'def set_session(self, session) -> bool:' in message_delegate
    assert 'class _MessageRowLayout:' in message_delegate
    assert 'def recall_notice_action_source_at(self, view, index: QModelIndex, position: QPoint) -> str | None:' in message_delegate
    assert 'def update_recall_notice_action_hover(self, view, index: QModelIndex, position: QPoint) -> bool:' in message_delegate
    assert 'action_font.setUnderline(' not in message_delegate
    assert 'def _group_sender_label_text(self, message: ChatMessage) -> str:' in message_delegate
    assert 'chat_info_search_requested = Signal()' in chat_panel
    assert 'chat_info_identity_review_requested = Signal()' in chat_panel
    assert 'chat_info_clear_requested = Signal()' in chat_panel
    assert 'chat_info_show_nickname_toggled = Signal(bool)' in chat_panel
    assert 'chat_info_member_management_requested = Signal(object)' in chat_panel
    assert 'class IdentityReviewDialog(QDialog):' in chat_interface
    assert 'self.identity_row.setVisible(str(security_summary.get("encryption_mode") or "") == "e2ee_private")' in drawer
    assert 'def restore_recalled_message_to_composer(self, message_id: str) -> bool:' in chat_panel
    assert 'def replace_message(self, message: ChatMessage) -> None:' in chat_panel
    assert 'self._message_delegate.set_session(None)' in chat_panel
    assert 'layout_changed = bool(self._message_delegate and self._message_delegate.set_session(session))' in chat_panel
    assert 'class EditMessageDialog(QDialog):' not in chat_interface
    assert 'self._session_manager.set_user_id(user_id)' in Path('client/ui/controllers/chat_controller.py').read_text(encoding='utf-8')


def test_contact_controller_owns_group_record_merge_rules() -> None:
    contact_controller = Path('client/ui/controllers/contact_controller.py').read_text(encoding='utf-8')
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')

    assert 'def _group_record_id(' in contact_controller
    assert 'def group_sort_key(group: GroupRecord) -> str:' in contact_controller
    assert 'def normalize_group_record(' in contact_controller
    assert 'def merge_group_record(' in contact_controller
    assert 'def apply_group_self_profile_update(' in contact_controller
    assert 'async def persist_groups_cache(self, groups: list[GroupRecord]) -> None:' in contact_controller
    assert 'async def persist_contacts_cache(self, contacts: list[ContactRecord]) -> None:' in contact_controller
    assert 'def _group_record_from_payload(' not in contact_interface
    assert 'def _upsert_group_record(' not in contact_interface
    assert 'def _coerce_group_record(' not in contact_interface
    assert 'GroupRecord(' not in contact_interface




def test_group_announcement_flow_uses_formal_banner_dialog_and_version_state() -> None:
    chat_panel = Path('client/ui/widgets/chat_panel.py').read_text(encoding='utf-8')
    chat_header = Path('client/ui/widgets/chat_header.py').read_text(encoding='utf-8')
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')
    session_controller = Path('client/ui/controllers/session_controller.py').read_text(encoding='utf-8')
    session_manager = Path('client/managers/session_manager.py').read_text(encoding='utf-8')
    groups_api = Path('server/app/api/v1/groups.py').read_text(encoding='utf-8')
    group_service = Path('server/app/services/group_service.py').read_text(encoding='utf-8')
    session_service = Path('server/app/services/session_service.py').read_text(encoding='utf-8')
    banner = Path('client/ui/widgets/group_announcement_banner.py').read_text(encoding='utf-8')
    dialog = Path('client/ui/windows/group_announcement_dialog.py').read_text(encoding='utf-8')

    assert 'group_announcement_requested = Signal()' in chat_panel
    assert 'from client.ui.widgets.group_announcement_banner import GroupAnnouncementBanner' in chat_header
    assert 'self.group_announcement_banner = GroupAnnouncementBanner(self.info_widget)' in chat_header
    assert 'self.chat_header.group_announcement_widget().clicked.connect(self.group_announcement_requested.emit)' in chat_panel
    assert 'self.chat_header.set_group_announcement_session(session if show_group_announcement else None)' in chat_panel
    assert 'from client.ui.windows.group_announcement_dialog import GroupAnnouncementDialog' in chat_interface
    assert 'def _on_group_announcement_requested(self) -> None:' in chat_interface
    assert 'mark_announcement_viewed: bool = False' in chat_interface
    assert 'async def mark_group_announcement_viewed(self, session_id: str, announcement_message_id: str)' in session_controller
    assert 'async def mark_group_announcement_viewed(self, session_id: str, announcement_message_id: str) -> Optional[Session]:' in session_manager
    assert 'class GroupAnnouncementBanner(CardWidget):' in banner
    assert 'class GroupAnnouncementDialog(QDialog):' in dialog
    assert 'async def _broadcast_group_announcement_message(' in groups_api
    assert 'announcement_message_id' in group_service
    assert '"announcement_message_id": announcement_message_id or None' in session_service


def test_chat_header_security_badges_are_driven_from_session_summary() -> None:
    chat_header = Path('client/ui/widgets/chat_header.py').read_text(encoding='utf-8')
    chat_panel = Path('client/ui/widgets/chat_panel.py').read_text(encoding='utf-8')

    assert 'from qfluentwidgets import BodyLabel, CaptionLabel, InfoBadge, InfoLevel, TransparentToolButton' in chat_header
    assert 'def set_security_badges(self, badges: list[dict[str, str]]) -> None:' in chat_header
    assert 'widget = InfoBadge(self.badge_container' in chat_header
    assert 'def _session_security_badges(session: Session | None) -> list[dict[str, str]]:' in chat_panel
    assert 'self.chat_header.set_security_badges(_session_security_badges(session))' in chat_panel
    assert 'self.chat_header.set_security_badges([])' in chat_panel


def test_chat_panel_security_pending_banner_is_wired_to_current_session_actions() -> None:
    chat_panel = Path('client/ui/widgets/chat_panel.py').read_text(encoding='utf-8')
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')

    assert 'class SecurityPendingBanner(QFrame):' in chat_panel
    assert 'security_pending_confirm_requested = Signal(str, str)' in chat_panel
    assert 'security_pending_discard_requested = Signal(str)' in chat_panel
    assert 'self._security_pending_banner = SecurityPendingBanner(self.chat_page)' in chat_panel
    assert 'self._security_pending_banner.confirm_requested.connect(self._on_security_pending_confirm_requested)' in chat_panel
    assert 'self._security_pending_banner.discard_requested.connect(self._on_security_pending_discard_requested)' in chat_panel
    assert 'self.security_pending_confirm_requested.emit(self._current_session.session_id' in chat_panel
    assert 'self.chat_panel.security_pending_confirm_requested.connect(self._on_security_pending_confirm_requested)' in chat_interface
    assert 'async def _confirm_security_pending_messages(self, session_id: str, action_id: str, generation: int) -> None:' in chat_interface
    assert 'await self._chat_controller.release_session_security_pending_messages(session_id)' in chat_interface
