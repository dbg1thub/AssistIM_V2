import json
from pathlib import Path


def test_ui_does_not_emit_session_updated_events_directly() -> None:
    session_panel = Path('client/ui/widgets/session_panel.py').read_text(encoding='utf-8')
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')

    assert 'emit_sync(SessionEvent.UPDATED' not in session_panel
    assert 'emit_sync(SessionEvent.UPDATED' not in chat_interface


def test_client_feature_backlog_keeps_completed_work_out_of_next_candidates() -> None:
    backlog = Path('CLIENT_FEATURE_BACKLOG.md').read_text(encoding='utf-8')

    completed_section = backlog.split('## 已完成收口', 1)[1].split('## 下一步候选', 1)[0]
    next_candidates = backlog.split('## 下一步候选', 1)[1]

    assert '联系人详情页语音 / 视频通话入口' in completed_section
    assert '联系人详情页语音 / 视频通话入口' not in next_candidates


def test_group_creation_dialogs_are_split_out_of_contact_interface() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')

    assert 'class StartGroupChatDialog' not in contact_interface
    assert 'class CreateGroupDialog' not in contact_interface
    assert 'from client.ui.windows.group_creation_dialogs import CreateGroupDialog' in contact_interface
    assert 'from client.ui.windows.contact_interface import StartGroupChatDialog' not in chat_interface
    assert 'from client.ui.windows.chat_group_flow import ChatGroupFlowCoordinator' in chat_interface


def test_sidebar_items_use_compact_consistent_spacing() -> None:
    session_delegate = Path('client/delegates/session_delegate.py').read_text(encoding='utf-8')
    contact_shared = Path('client/ui/widgets/contact_shared.py').read_text(encoding='utf-8')
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')
    update_friend_block = contact_interface.split('def _update_friend_item_view', 1)[1].split('def _create_friend_item', 1)[0]
    create_friend_block = contact_interface.split('def _create_friend_item', 1)[1].split('def _ensure_friend_section_view', 1)[0]
    remove_friend_block = contact_interface.split('def _remove_friend_item_view', 1)[1].split('def _update_blocked_item_view', 1)[0]
    upsert_contact_block = contact_interface.split('def _upsert_contact_record', 1)[1].split('def _upsert_blocked_contact_record', 1)[0]
    keyed_task_block = contact_interface.split('def _schedule_keyed_ui_task', 1)[1].split('def _clear_keyed_ui_task', 1)[0]
    update_blocked_block = contact_interface.split('def _update_blocked_item_view', 1)[1].split('def _create_blocked_item', 1)[0]
    create_blocked_block = contact_interface.split('def _create_blocked_item', 1)[1].split('def _insert_blocked_item_view', 1)[0]

    assert 'AVATAR_SIZE = 36' in session_delegate
    assert 'ITEM_HEIGHT = 64' in session_delegate
    assert 'ITEM_PADDING = 8' in session_delegate
    assert 'CONTENT_GAP = 8' in session_delegate
    assert 'card_rect.x() + self.ITEM_PADDING' in session_delegate
    assert 'avatar_rect.right() + self.CONTENT_GAP' in session_delegate
    assert 'card_rect.right() - self.ITEM_PADDING' in session_delegate
    assert 'CONTACT_SIDEBAR_AVATAR_SIZE = 36' in contact_shared
    assert 'CONTACT_SIDEBAR_ITEM_HEIGHT = 56' in contact_shared
    assert 'CONTACT_SIDEBAR_ITEM_PADDING = 8' in contact_shared
    assert 'CONTACT_SIDEBAR_CONTENT_GAP = 8' in contact_shared
    assert 'CONTACT_SIDEBAR_TEXT_TOP_OFFSET = 0' in contact_shared
    assert 'CONTACT_SIDEBAR_TEXT_SPACING = 0' in contact_shared
    assert 'title=self._friend_sidebar_title(contact)' in update_friend_block
    assert 'subtitle=""' in update_friend_block
    assert 'self._friend_assistim_line(contact)' not in update_friend_block
    assert 'self._friend_sidebar_title(contact),' in create_friend_block
    assert 'self._friend_assistim_line(contact)' not in create_friend_block
    assert 'left_padding=CONTACT_SECTION_INSET' in create_friend_block
    assert 'str(contact.remark or "").strip()' in contact_interface
    assert 'or str(contact.username or "").strip()' in contact_interface
    assert 'section_layout.removeWidget(item)' in remove_friend_block
    assert 'self.friends_layout.removeWidget(section)' in remove_friend_block
    assert 'self._build_friends_page()' in upsert_contact_block
    assert 'self._restore_selection(full_reload=False)' in upsert_contact_block
    assert 'coro_factory' in keyed_task_block
    assert 'coro_factory()' in keyed_task_block
    assert 'coro_factory()' not in keyed_task_block.split('if existing is not None and not existing.done():', 1)[1].split('self._keyed_ui_tasks[key]', 1)[0]
    assert 'title=self._friend_sidebar_title(contact)' in update_blocked_block
    assert 'subtitle=""' in update_blocked_block
    assert 'self._friend_sidebar_title(contact),' in create_blocked_block


def test_discovery_ui_wires_moment_media_and_comment_image_boundaries() -> None:
    discovery_interface = Path('client/ui/windows/discovery_interface.py').read_text(encoding='utf-8')

    assert 'from client.core.exceptions import APIError' in discovery_interface
    assert 'MOMENT_MEDIA_MAX_UPLOAD_BYTES = 100 * 1024 * 1024' in discovery_interface
    assert 'def _format_file_size(size_bytes: int) -> str:' in discovery_interface
    assert 'def _is_file_over_upload_limit(file_path: str) -> bool:' in discovery_interface
    assert 'def _oversized_media_paths(self) -> list[str]:' in discovery_interface
    assert 'self.publish_button.setEnabled(not self._oversized_media_paths())' in discovery_interface
    assert 'discovery.dialog.media_too_large' in discovery_interface
    assert 'discovery.dialog.media_too_large_details' in discovery_interface
    assert 'discovery.comments.image_too_large' in discovery_interface
    assert 'exc.status_code == 413' in discovery_interface
    assert 'discovery.publish.too_large' in discovery_interface
    assert 'from urllib.parse import urlsplit' in discovery_interface
    assert 'def _normalize_media_url_key(value: object) -> str:' in discovery_interface
    assert '_normalize_media_url_key(item.get("url")): str(item.get("local_path") or "").strip()' in discovery_interface
    assert 'normalized_url = _normalize_media_url_key(item.url)' in discovery_interface
    assert 'class CreateMomentDialog' in discovery_interface
    assert 'QFileDialog.getOpenFileNames' in discovery_interface
    assert 'QFileDialog.getOpenFileName' in discovery_interface
    assert 'submitted = Signal(str, list, str, list)' in discovery_interface
    assert 'comment_submitted = Signal(str, object)' in discovery_interface
    assert 'upload_moment_media' in discovery_interface
    assert 'upload_comment_image' in discovery_interface
    assert 'MomentMediaGrid(self.moment.media' in discovery_interface
    assert 'def set_media(self, media: list[MomentMediaRecord]) -> None:' in discovery_interface
    assert 'self.media_preview = MomentMediaGrid([], self, compact=True)' in discovery_interface
    assert 'def _sync_media_preview(self) -> None:' in discovery_interface
    assert 'self.image_preview = MomentMediaGrid([], self.surface, compact=True)' in discovery_interface
    assert 'def _sync_comment_image_preview(self) -> None:' in discovery_interface


def test_discovery_media_grid_loads_remote_media_with_auth_header() -> None:
    discovery_interface = Path('client/ui/windows/discovery_interface.py').read_text(encoding='utf-8')
    media_grid_block = discovery_interface.split('class MomentMediaGrid(QWidget):', 1)[1].split(
        'class MomentCommentItem(QWidget):',
        1,
    )[0]

    assert 'from client.network.http_client import get_http_client' in discovery_interface
    assert 'def _build_media_request(self, source: str) -> QNetworkRequest:' in media_grid_block
    assert 'token = str(get_http_client().access_token or "").strip()' in media_grid_block
    assert 'request.setRawHeader(b"Authorization", f"Bearer {token}".encode("utf-8"))' in media_grid_block
    assert 'reply = self._network_manager.get(self._build_media_request(source))' in media_grid_block


def test_image_viewer_loads_protected_uploads_with_auth_header() -> None:
    image_viewer = Path('client/ui/widgets/image_viewer.py').read_text(encoding='utf-8')

    assert 'from client.network.http_client import get_http_client' in image_viewer
    assert 'def _build_image_request(self, source: str) -> QNetworkRequest:' in image_viewer
    assert 'token = str(get_http_client().access_token or "").strip()' in image_viewer
    assert 'request.setRawHeader(b"Authorization", f"Bearer {token}".encode("utf-8"))' in image_viewer
    assert 'reply = self._network_manager.get(self._build_image_request(source))' in image_viewer


def test_moment_comment_editor_can_close_without_breaking_image_picker() -> None:
    discovery_interface = Path('client/ui/windows/discovery_interface.py').read_text(encoding='utf-8')

    section_block = discovery_interface.split('class AnimatedCommentSection(QWidget):', 1)[1].split(
        'def _contact_display_name',
        1,
    )[0]
    open_editor_block = section_block.split('def open_editor(self) -> None:', 1)[1].split('def hide_editor', 1)[0]
    hide_editor_block = section_block.split('def hide_editor(self', 1)[1].split('def _rebuild', 1)[0]
    submit_block = section_block.split('def _submit_comment(self) -> None:', 1)[1].split(
        'def _select_comment_image',
        1,
    )[0]
    event_filter_block = section_block.split('def eventFilter(self, watched, event) -> bool:', 1)[1].split(
        'def _submit_comment',
        1,
    )[0]

    assert 'self.editor_widget.installEventFilter(self)' in section_block
    assert 'self.comment_edit.installEventFilter(self)' in section_block
    assert 'self.image_button.installEventFilter(self)' in section_block
    assert 'self.send_button.installEventFilter(self)' in section_block
    assert 'if self._editor_visible:' in open_editor_block
    assert 'self.hide_editor(clear_draft=False)' in open_editor_block
    assert 'def hide_editor(self, *, clear_draft: bool = False) -> None:' in section_block
    assert 'self._editor_visible = False' in hide_editor_block
    assert 'if clear_draft:' in hide_editor_block
    assert 'self.comment_edit.clear()' in hide_editor_block
    assert 'self._selected_image_path = ""' in hide_editor_block
    assert 'self.hide_editor(clear_draft=True)' in submit_block
    assert 'QEvent.Type.KeyPress' in event_filter_block
    assert 'Qt.Key.Key_Escape' in event_filter_block
    assert 'QEvent.Type.FocusOut' in event_filter_block
    assert 'self._is_focus_inside_editor()' in event_filter_block
    assert 'self.hide_editor(clear_draft=False)' in event_filter_block


def test_discovery_video_tiles_use_existing_thumbnail_cache() -> None:
    discovery_interface = Path('client/ui/windows/discovery_interface.py').read_text(encoding='utf-8')

    assert 'from client.core.video_thumbnail_cache import get_video_thumbnail_cache' in discovery_interface
    assert 'self._video_thumbnail_cache = get_video_thumbnail_cache()' in discovery_interface
    assert 'self._video_thumbnail_cache.signals.thumbnail_ready.connect(self._on_video_thumbnail_ready)' in discovery_interface
    assert 'self._video_labels_by_source: dict[str, QLabel] = {}' in discovery_interface
    assert 'def _apply_video_placeholder(self, label: QLabel, width: int, height: int) -> None:' in discovery_interface
    assert 'def _apply_video_thumbnail(self, label: QLabel, pixmap: QPixmap, width: int, height: int) -> None:' in discovery_interface
    assert 'def _on_video_thumbnail_ready(self, source: str) -> None:' in discovery_interface
    assert 'self._video_thumbnail_cache.request_thumbnail(source)' in discovery_interface
    assert 'if source and Path(source).exists():' in discovery_interface


def test_discovery_ui_exposes_moment_privacy_entry_points() -> None:
    discovery_interface = Path('client/ui/windows/discovery_interface.py').read_text(encoding='utf-8')

    assert 'class MomentVisibilitySelectDialog(FluentDialog):' in discovery_interface
    assert 'class MomentPrivacySettingsDialog(FluentDialog):' in discovery_interface
    assert 'self.visibility_button = PushButton(tr("discovery.dialog.visibility_title", "Who can see this"), self)' in discovery_interface
    assert 'self.privacy_button = PushButton(tr("discovery.feed.privacy_button", "Moment Privacy"), self.hero_card)' in discovery_interface
    assert 'dialog.submitted.connect(self._create_moment)' in discovery_interface
    assert 'def _create_moment(self, content: str, media_paths: list | None = None, visibility_scope: str = "public", visibility_user_ids: list | None = None) -> None:' in discovery_interface
    assert 'await self._controller.update_moment_privacy_settings(' in discovery_interface
    assert 'tr("discovery.privacy.visible_time_scope", "Allow friends to view moments from")' in discovery_interface


def test_discovery_ui_loads_full_comments_from_moment_detail() -> None:
    discovery_interface = Path('client/ui/windows/discovery_interface.py').read_text(encoding='utf-8')

    assert 'detail_requested = Signal(str)' in discovery_interface
    assert 'comments_truncated' in discovery_interface
    assert 'self.comment_section.detail_requested.connect(self._request_detail)' in discovery_interface
    assert 'card.detail_requested.connect(self._request_moment_detail)' in discovery_interface
    assert 'async def _request_moment_detail_async(self, moment_id: str)' in discovery_interface
    assert 'await self._controller.load_moment_detail(moment_id)' in discovery_interface
    assert 'card.apply_detail(moment)' in discovery_interface


def test_moment_ui_mutations_keep_backing_records_in_sync() -> None:
    discovery_interface = Path('client/ui/windows/discovery_interface.py').read_text(encoding='utf-8')
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')

    assert 'def _apply_local_comment(self, moment_id: str, comment) -> None:' in discovery_interface
    assert 'existing is comment' in discovery_interface
    assert 'moment.comments.append(comment)' in discovery_interface
    assert 'moment.comment_count = max(moment.comment_count + 1, len(moment.comments))' in discovery_interface
    assert 'self._apply_local_comment(moment_id, comment)' in discovery_interface
    assert 'def _sync_moment_like_state(self, moment_id: str, liked: bool, like_count: int) -> None:' not in contact_interface
    assert 'def _sync_moment_comment(self, moment_id: str, comment) -> None:' not in contact_interface


def test_discovery_ui_wires_moment_delete_actions() -> None:
    discovery_interface = Path('client/ui/windows/discovery_interface.py').read_text(encoding='utf-8')
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')

    assert 'class DeleteMomentConfirmDialog(MessageBoxBase):' in discovery_interface
    assert 'class DeleteCommentConfirmDialog(MessageBoxBase):' in discovery_interface
    assert 'delete_requested = Signal(str)' in discovery_interface
    assert 'comment_delete_requested = Signal(str, str)' in discovery_interface
    assert 'self.delete_requested.emit(self.moment.id)' in discovery_interface
    assert 'self.comment_delete_requested.emit(moment_id, comment_id)' in discovery_interface
    assert 'card.delete_requested.connect(self._request_moment_delete)' in discovery_interface
    assert 'card.comment_delete_requested.connect(self._request_comment_delete)' in discovery_interface
    assert 'await self._controller.delete_moment(moment_id)' in discovery_interface
    assert 'await self._controller.delete_comment(moment_id, comment_id)' in discovery_interface
    assert 'self._apply_local_moment_delete(moment_id)' in discovery_interface
    assert 'self._apply_local_comment_delete(moment_id, comment_id)' in discovery_interface
    assert 'moment_delete_requested = Signal(str)' not in contact_interface
    assert 'comment_delete_requested = Signal(str, str)' not in contact_interface
    assert 'self.detail_panel.moments_panel' not in contact_interface


def test_moment_realtime_refresh_is_wired_to_visible_pages() -> None:
    discovery_interface = Path('client/ui/windows/discovery_interface.py').read_text(encoding='utf-8')
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')
    message_manager = Path('client/managers/message_manager.py').read_text(encoding='utf-8')

    assert 'from client.events.moment_events import MomentEvent' in discovery_interface
    assert 'from client.events.moment_events import MomentEvent' not in contact_interface
    assert 'from client.events.moment_events import MomentEvent' in message_manager
    assert 'elif msg_type == "moment_refresh":' in message_manager
    assert 'async def _process_moment_refresh(self, data: dict) -> None:' in message_manager
    assert 'self._event_bus.subscribe_sync(MomentEvent.SYNC_REQUIRED, self._on_moment_sync_required)' in discovery_interface
    assert 'self._event_bus.unsubscribe_sync(MomentEvent.SYNC_REQUIRED, self._on_moment_sync_required)' in discovery_interface
    assert 'def _on_moment_sync_required(self, payload: object) -> None:' in discovery_interface
    assert 'self._event_bus.subscribe_sync(MomentEvent.SYNC_REQUIRED, self._on_moment_sync_required)' not in contact_interface
    assert 'self._event_bus.unsubscribe_sync(MomentEvent.SYNC_REQUIRED, self._on_moment_sync_required)' not in contact_interface
    assert 'def _on_moment_sync_required(self, payload: object) -> None:' not in contact_interface


def test_contact_interface_no_longer_embeds_moments_panel() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')

    assert 'ContactMomentsFlowPanel' not in contact_interface
    assert 'moments_panel' not in contact_interface
    assert '_load_detail_moments' not in contact_interface
    assert 'contact.moments' not in contact_interface
    assert 'class FriendMomentPreviewStrip(QWidget):' in contact_interface
    assert 'self._discovery_controller = get_discovery_controller()' in contact_interface
    assert 'def _load_friend_moment_images(self, contact_id: str) -> None:' in contact_interface
    assert 'MomentEvent' not in contact_interface


def test_contact_detail_card_uses_wechat_like_profile_layout() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')
    app_icons = Path('client/core/app_icons.py').read_text(encoding='utf-8')
    zh_cn = json.loads(Path('client/resources/i18n/zh-CN.json').read_text(encoding='utf-8'))
    en_us = json.loads(Path('client/resources/i18n/en-US.json').read_text(encoding='utf-8'))
    ko_kr = json.loads(Path('client/resources/i18n/ko-KR.json').read_text(encoding='utf-8'))

    assert 'root_layout.addWidget(self.header, 0, Qt.AlignmentFlag.AlignHCenter)' in contact_interface
    assert 'self.gender_icon = IconWidget(AppIcon.GENDER_MALE, self.header)' in contact_interface
    assert 'self.gender_label = CaptionLabel("", self.header)' in contact_interface
    assert 'self.gender_label.show()' in contact_interface
    assert 'self.more_button = TransparentToolButton(AppIcon.MORE_HORIZONTAL, self.header)' in contact_interface
    assert 'self.edit_button = TransparentToolButton(AppIcon.EDIT, self)' in contact_interface
    assert 'self.remark_row = ContactDetailRow' in contact_interface
    assert 'self.signature_row.set_value(contact.signature or "-")' in contact_interface
    assert 'self.subtitle_label.setText(\n            f"{tr(\'contact.detail.label.assistim_id\', \'AssistIM ID\')}: ' in contact_interface
    assert 'self.region_label.setText(f"{tr(\'contact.detail.label.region\', \'Region\')}: ' in contact_interface
    assert 'self.remove_friend_button' not in contact_interface
    assert 'remove_requested = Signal(object)' not in contact_interface
    assert 'def enterEvent(self, event) -> None:' in contact_interface
    assert 'def paintEvent(self, event) -> None:' in contact_interface
    assert 'class EditFriendRemarkDialog(FluentDialog):' in contact_interface
    assert 'self.detail_panel.remark_edit_requested.connect(self._on_friend_remark_edit_requested)' in contact_interface
    assert 'async def _update_friend_remark_async(self, contact_id: str, remark: str) -> None:' in contact_interface
    assert 'GENDER_MALE = "gender_male"' in app_icons
    assert 'GENDER_FEMALE = "gender_female"' in app_icons
    assert 'MORE_HORIZONTAL = "more_horizontal"' in app_icons
    assert 'EDIT = "edit"' in app_icons
    assert zh_cn['contact.detail.label.moments'] == '朋友圈'
    assert zh_cn['contact.detail.edit_remark.title'] == '修改备注'
    assert zh_cn['contact.detail.moment_image_placeholder'] == '图片'
    assert en_us['contact.detail.label.moments'] == 'Moments'
    assert ko_kr['contact.detail.label.moments'] == '친구 소식'


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
    assert 'def _call_failure_infobar_text(self, call: ActiveCallState) -> str:' in chat_interface
    assert 'call.reason or tr(' not in chat_interface


def test_call_window_marks_connected_on_transport_connection() -> None:
    call_window = Path('client/ui/windows/call_window.py').read_text(encoding='utf-8')
    connected_block = call_window.split('if lowered == "connection connected":', 1)[1].split(
        'if lowered == "connection new":',
        1,
    )[0]

    assert 'self._mark_call_connected()' in connected_block
    assert 'self.set_status_text("Connecting...")' not in connected_block


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
    send_segments_block = chat_interface.split('async def _send_segments_async', 1)[1].split(
        'async def _send_image_message',
        1,
    )[0]
    send_image_block = chat_interface.split('async def _send_image_message', 1)[1].split(
        'def _on_send_typing',
        1,
    )[0]
    send_file_block = chat_interface.split('async def _send_file_message', 1)[1].split(
        'def _on_message_context_menu',
        1,
    )[0]

    assert 'def _is_current_message_context(self, message, generation: int) -> bool:' in chat_interface
    assert 'async def _send_image_message(self, session_id: str, file_path: str, generation: int) -> None:' in chat_interface
    assert 'if message and self._is_current_session_context(session_id, generation):' in chat_interface
    assert 'self._send_image_message(self._current_session_id, file_path, generation)' in chat_interface
    assert 'except Exception as exc:' not in send_segments_block
    assert '[send-diag] send_segment_failed' not in send_segments_block
    assert 'except Exception as exc:' not in send_image_block
    assert 'logger.error("Send image message error: %s", exc)' not in send_image_block
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
    assert 'except Exception as exc:' not in send_file_block
    assert 'logger.error("Send file message error: %s", exc)' not in send_file_block
    assert chat_interface.count('if not self._is_current_session_context(session_id, generation):') >= 8
    assert 'if not self._is_current_session_context(session_id, generation):' in chat_interface
    assert 'chat.security_pending.discard_empty' in chat_interface
    assert 'chat.security_pending.release_empty' in chat_interface


def test_voice_messages_have_send_open_and_click_paths_without_alt_shortcut() -> None:
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')
    chat_panel = Path('client/ui/widgets/chat_panel.py').read_text(encoding='utf-8')
    fluent_splitter = Path('client/ui/widgets/fluent_splitter.py').read_text(encoding='utf-8')
    message_input = Path('client/ui/widgets/message_input.py').read_text(encoding='utf-8')
    message_manager = Path('client/managers/message_manager.py').read_text(encoding='utf-8')
    message_delegate = Path('client/delegates/message_delegate.py').read_text(encoding='utf-8')

    send_segments_block = chat_interface.split('async def _send_segments_async', 1)[1].split(
        'async def _send_image_message',
        1,
    )[0]
    open_message_block = chat_interface.split('def _open_message(self, message', 1)[1].split(
        'async def _open_file_attachment',
        1,
    )[0]

    assert 'MessageType.VOICE' in send_segments_block
    assert 'MessageType.VOICE' in open_message_block
    assert 'play_voice_message' in chat_panel
    assert 'MessageType.VOICE' in chat_panel
    assert 'voice_message_button' in message_input
    assert 'voice_message_submitted = Signal(str, int)' in message_input
    assert 'Key_Alt' not in message_input
    assert 'MessageType.VOICE' in message_manager
    assert 'MessageType.VOICE' in message_delegate


def test_chat_message_input_uses_floating_card_style_without_overlay_or_cursor_override() -> None:
    chat_panel = Path('client/ui/widgets/chat_panel.py').read_text(encoding='utf-8')
    fluent_splitter = Path('client/ui/widgets/fluent_splitter.py').read_text(encoding='utf-8')
    message_input = Path('client/ui/widgets/message_input.py').read_text(encoding='utf-8')
    light_input_qss = Path('client/ui/styles/qss/light/message_input.qss').read_text(encoding='utf-8')
    dark_input_qss = Path('client/ui/styles/qss/dark/message_input.qss').read_text(encoding='utf-8')
    light_chat_qss = Path('client/ui/styles/qss/light/chat_panel.qss').read_text(encoding='utf-8')
    dark_chat_qss = Path('client/ui/styles/qss/dark/chat_panel.qss').read_text(encoding='utf-8')

    message_input_class = message_input.split('class MessageInput(QWidget):', 1)[1]
    setup_block = message_input_class.split('def _setup_ui(self) -> None:', 1)[1].split(
        'def _apply_safe_button_font',
        1,
    )[0]
    overlay_block = message_input_class.split('def _update_overlay_positions(self) -> None:', 1)[1].split(
        'def _update_send_button_state',
        1,
    )[0]

    assert 'AIAssistantFloatingComposerOverlay' not in chat_panel
    assert 'chatFloatingComposerOverlay' not in chat_panel
    assert 'self.content_splitter = FluentSplitter(Qt.Orientation.Vertical, self.chat_page)' in chat_panel
    assert 'self.content_splitter.setHandleIndicatorVisible(False)' in chat_panel
    assert 'self.content_splitter.splitterMoved.connect(self._schedule_restore_message_viewport)' in chat_panel
    assert 'MESSAGE_INPUT_FLOAT_OVERLAP' not in chat_panel
    assert 'MESSAGE_LIST_BOTTOM_MARGIN = 8' in chat_panel
    assert 'COMPOSER_MIN_HEIGHT = 180' in chat_panel
    assert 'composer_container.setObjectName("chatInputSafeArea")' in chat_panel
    assert 'composer_container.setMinimumHeight(self.COMPOSER_MIN_HEIGHT)' in chat_panel
    assert 'self._composer_input_slot.setObjectName("chatInputSlot")' in chat_panel
    assert 'self._composer_input_slot.setMinimumHeight(self.COMPOSER_MIN_HEIGHT)' in chat_panel
    assert 'self.message_input.setMinimumHeight(self.COMPOSER_MIN_HEIGHT)' in chat_panel
    assert 'composer_layout.addWidget(self._composer_input_slot, 1)' in chat_panel
    assert 'composer_layout.addWidget(self.message_input, 1)' not in chat_panel
    assert 'self.content_splitter.splitterMoved.connect(self._on_content_splitter_moved)' in chat_panel
    assert 'def _layout_message_input_overlay(self) -> None:' in chat_panel
    assert 'y = splitter_rect.y() + composer_rect.y() + banner_height' in chat_panel
    assert 'height = max(self.COMPOSER_MIN_HEIGHT, composer_rect.height() - banner_height)' in chat_panel
    assert 'self.message_input.raise_()' in chat_panel
    assert 'self.message_input.setMinimumHeight(0)' not in chat_panel
    assert 'self.message_input.setMaximumHeight(' not in chat_panel
    assert 'composer_container.setMaximumHeight(340)' in chat_panel
    assert '_ComposerResizeHandle' not in chat_panel
    assert 'def setHandleIndicatorVisible(self, visible: bool) -> None:' in fluent_splitter
    assert 'def isHandleIndicatorVisible(self) -> bool:' in fluent_splitter
    assert 'if not self.splitter().isHandleIndicatorVisible():' in fluent_splitter

    assert 'self.editor_card.setMaximumWidth(1100)' not in setup_block
    assert 'Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom' not in setup_block
    assert 'self.main_layout.setContentsMargins(8, 0, 8, 8)' in setup_block
    assert 'self.main_layout.addWidget(self.editor_card, 1)' in setup_block
    assert 'self.text_input.setViewportMargins(0, 0, 0, 0)' in setup_block
    assert 'self.toolbar_layout.setContentsMargins(8, 4, 110, 8)' in setup_block
    assert setup_block.count('setFixedSize(24, 24)') >= 7
    assert 'self.voice_message_button.setFixedSize(32, 28)' in setup_block
    assert 'self.send_button.setFixedSize(62, 28)' in setup_block
    assert setup_block.index('self.composer_layout.addWidget(self.reply_suggestion_widget, 0)') < setup_block.index(
        'self.composer_layout.addWidget(self.text_input, 1)'
    )
    assert setup_block.index('self.composer_layout.addWidget(self.text_input, 1)') < setup_block.index(
        'self.composer_layout.addWidget(self.toolbar_widget, 0)'
    )
    assert 'toolbar_rect = self.toolbar_widget.geometry()' in overlay_block
    assert 'text_rect = self.text_input.geometry()' not in overlay_block
    assert 'button_margin_right = 8' in overlay_block
    assert 'button_margin_bottom = 8' in overlay_block
    assert 'send_y = composer_rect.bottom() - button_margin_bottom - self.send_button.height()' in overlay_block
    assert 'voice_y = composer_rect.bottom() - button_margin_bottom - self.voice_message_button.height()' in overlay_block
    assert 'self.voice_message_button.raise_()' in overlay_block
    assert 'self.send_button.raise_()' in overlay_block

    assert 'setCursorWidth' not in message_input
    assert 'background-color: transparent !important' not in message_input
    assert 'transparent_base' not in message_input
    assert '_apply_editor_theme' in message_input
    assert '_apply_editor_transparency' not in message_input
    assert 'editor_base = QColor(31, 31, 31) if self._is_dark() else QColor(255, 255, 255)' in message_input
    assert 'self.text_input.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)' in message_input
    assert 'self.text_input.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)' in message_input

    light_input_card_block = light_input_qss.split('QWidget#messageInputCard {', 1)[1].split('}', 1)[0]
    dark_input_card_block = dark_input_qss.split('QWidget#messageInputCard {', 1)[1].split('}', 1)[0]
    assert 'background: rgba(255, 255, 255, 0.96);' in light_input_card_block
    assert 'background: rgba(31, 31, 31, 0.96);' in dark_input_card_block

    for qss in (light_input_qss, dark_input_qss):
        assert 'QWidget#messageInputCard {' in qss
        assert 'border-radius: 8px;' in qss
        assert 'QWidget#messageInput,\nQWidget#messageComposer,\nQWidget#messageToolbar' not in qss
        assert 'QTextEdit#chatMessageEdit,\nQWidget#chatMessageViewport,\nQTextEdit#chatMessageEdit QFrame' not in qss
        assert 'QWidget#messageToolbar {' in qss
        message_toolbar_block = qss.split('QWidget#messageToolbar {', 1)[1].split('}', 1)[0]
        assert 'border-top:' not in message_toolbar_block

    for qss in (light_chat_qss, dark_chat_qss):
        assert 'QSplitter#chatContentSplitter::handle:vertical' in qss
        assert 'background: transparent;' in qss.split('QSplitter#chatContentSplitter::handle:vertical', 1)[1].split('}', 1)[0]
        assert 'border: none;' in qss.split('QSplitter#chatContentSplitter::handle:vertical', 1)[1].split('}', 1)[0]
        assert 'QWidget#chatInputSafeArea' in qss
        assert 'QWidget#chatInputSlot' in qss


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
    assert 'payload = await self._auth_controller.request_register_payload(username, nickname, password, email, email_code)' in auth_interface
    assert 'payload = await self._auth_controller.send_email_verification(email)' in auth_interface
    assert 'self.forgot_password_button.clicked.connect(self._show_password_reset_dialog)' in auth_interface
    assert 'await self._auth_controller.send_password_reset_code(email)' in auth_interface
    assert 'await self._auth_controller.reset_password(email, email_code, new_password)' in auth_interface
    assert 'if self._submit_commit_in_progress:' in auth_interface
    assert 'event.ignore()' in auth_interface
    assert 'async def request_login_payload(self, username: str, password: str, *, force: bool = False) -> dict[str, Any]:' in auth_controller
    assert 'async def request_register_payload(' in auth_controller
    assert 'email_code: str,' in auth_controller
    assert 'async def send_email_verification(self, email: str, *, purpose: str = "register") -> dict[str, Any]:' in auth_controller
    assert 'async def send_password_reset_code(self, email: str) -> dict[str, Any]:' in auth_controller
    assert 'async def reset_password(self, email: str, email_code: str, new_password: str) -> dict[str, Any]:' in auth_controller
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


def test_user_profile_flyout_quiesce_detaches_auth_listener_before_teardown() -> None:
    flyout = Path('client/ui/widgets/user_profile_flyout.py').read_text(encoding='utf-8')
    detach_block = flyout.split('def _detach_auth_state_listener', 1)[1].split('def _close_flyout', 1)[0]
    quiesce_block = flyout.split('def quiesce', 1)[1].split('def closeEvent', 1)[0]
    destroyed_block = flyout.split('def _on_destroyed', 1)[1]

    assert 'if not self._auth_listener_attached:' in detach_block
    assert 'self._auth_controller.remove_auth_state_listener(self._handle_auth_state_changed)' in detach_block
    assert 'self._auth_listener_attached = False' in detach_block
    assert 'self._detach_auth_state_listener()' in quiesce_block
    assert quiesce_block.index('self._detach_auth_state_listener()') < quiesce_block.index(
        'self._cancel_pending_task(self._save_task)'
    )
    assert 'self._detach_auth_state_listener()' in destroyed_block
    assert 'remove_auth_state_listener' not in destroyed_block


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


def test_user_profile_flyout_requires_email_code_for_changed_email() -> None:
    flyout = Path('client/ui/widgets/user_profile_flyout.py').read_text(encoding='utf-8')
    dialog_block = flyout.split('class ProfileEditDialog', 1)[1].split('class ProfileCard', 1)[0]
    save_block = flyout.split('async def _save_profile_async', 1)[1].split('def _emit_profile_changed', 1)[0]

    assert 'self.email_code_edit = LineEdit(self)' in dialog_block
    assert 'self.email_send_code_button.clicked.connect(self._submit_email_code)' in dialog_block
    assert 'def _email_changed(self) -> bool:' in dialog_block
    assert 'await self._auth_controller.send_email_verification(email, purpose="profile_email")' in dialog_block
    assert 'if self._email_changed() and email_value:' in dialog_block
    assert '"email_code": self.email_code_edit.text().strip() if self._email_changed() and self.email_edit.text().strip() else None' in dialog_block
    assert 'email_code=str(payload.get("email_code", "") or "").strip() or None' in save_block


def test_user_profile_edit_dialog_uses_fluent_controls_and_profile_only_fields() -> None:
    flyout = Path('client/ui/widgets/user_profile_flyout.py').read_text(encoding='utf-8')
    dialog_block = flyout.split('class ProfileEditDialog', 1)[1].split('class ProfileCard', 1)[0]
    profile_fields = Path('client/core/profile_fields.py').read_text(encoding='utf-8')

    assert 'ComboBox' in dialog_block
    assert 'QFormLayout' not in dialog_block
    assert 'QDateEdit' not in dialog_block
    assert 'QComboBox' not in dialog_block
    assert 'DateEdit' not in dialog_block
    assert 'self.phone_edit' not in dialog_block
    assert 'self.birthday_edit' not in dialog_block
    assert 'self.status_combo' not in dialog_block
    assert '"status":' not in dialog_block
    assert '"phone":' not in dialog_block
    assert '"birthday":' not in dialog_block
    assert 'title = SubtitleLabel(tr("profile.edit.title"' not in dialog_block
    assert 'self.region_country_combo = ComboBox(self)' in dialog_block
    assert 'self.region_area_combo = ComboBox(self)' in dialog_block
    assert 'form_layout.addWidget(self._create_form_row(' in dialog_block
    assert 'PROFILE_GENDER_VALUES = ("female", "male")' in profile_fields


def test_fluent_dialog_title_is_centered() -> None:
    dialog = Path('client/ui/widgets/fluent_dialog.py').read_text(encoding='utf-8')

    assert 'self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)' in dialog
    assert 'title_layout.addWidget(self.title_left_spacer, 0)' in dialog
    assert 'title_layout.addWidget(self.title_label, 1, Qt.AlignmentFlag.AlignVCenter)' in dialog
    assert 'title_layout.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)' in dialog
    assert 'def _sync_title_left_spacer_width(self) -> None:' in dialog
    assert 'width = self.close_button.width() if self.close_button.width() > 0 else self.CLOSE_BUTTON_WIDTH' in dialog
    assert 'self.title_left_spacer.setFixedWidth(width)' in dialog
    assert 'sizeHint().width()' not in dialog
    assert 'sizeHint().height()' not in dialog
    assert 'self._sync_title_left_spacer_width()' in dialog


def test_fluent_exec_dialogs_cache_payload_before_accepting() -> None:
    flyout = Path('client/ui/widgets/user_profile_flyout.py').read_text(encoding='utf-8')
    profile_block = flyout.split('class ProfileEditDialog', 1)[1].split('class ProfileCard', 1)[0]
    password_block = flyout.split('class ChangePasswordDialog', 1)[1].split('class DeviceSecurityDialog', 1)[0]
    profile_open_block = flyout.split('def open_profile_editor', 1)[1].split('def open_password_change_dialog', 1)[0]
    password_open_block = flyout.split('def open_password_change_dialog', 1)[1].split('def open_device_security_dialog', 1)[0]

    assert 'self._submitted_payload: dict[str, str | bool | None] | None = None' in profile_block
    assert 'self._submitted_payload = self.profile_payload()' in profile_block
    assert 'dialog._submitted_payload or dialog.profile_payload()' in profile_open_block
    assert 'self._submitted_payload: tuple[str, str] | None = None' in password_block
    assert 'self._submitted_payload = (current_password, new_password)' in password_block
    assert 'dialog._submitted_payload or dialog.password_payload()' in password_open_block


def test_user_profile_flyout_exposes_authenticated_password_change() -> None:
    flyout = Path('client/ui/widgets/user_profile_flyout.py').read_text(encoding='utf-8')

    assert 'class ChangePasswordDialog(FluentDialog):' in flyout
    assert 'self.change_password_link = HyperlinkLabel(tr("profile.password.change.link", "Change Password"), self)' in flyout
    assert 'self.change_password_link.clicked.connect(self.passwordChangeRequested.emit)' in flyout
    assert 'view.passwordChangeRequested.connect(self._handle_password_change_from_flyout)' in flyout
    assert 'dialog = ChangePasswordDialog(self.window())' in flyout
    assert 'await self._auth_controller.change_password(current_password, new_password)' in flyout
    assert 'self._set_password_task(self._change_password_async(dialog._submitted_payload or dialog.password_payload()))' in flyout


def test_user_profile_flyout_exposes_readonly_e2ee_device_security() -> None:
    flyout = Path('client/ui/widgets/user_profile_flyout.py').read_text(encoding='utf-8')
    auth_controller = Path('client/ui/controllers/auth_controller.py').read_text(encoding='utf-8')

    assert 'import json' in flyout
    assert 'class DeviceSecurityDialog(FluentDialog):' in flyout
    assert 'self.refresh_button.clicked.connect(self.reload_devices)' in flyout
    assert 'devices = await self._auth_controller.list_my_e2ee_devices()' in flyout
    assert 'diagnostics = await self._auth_controller.get_history_recovery_diagnostics()' in flyout
    assert 'local_device_id = str(diagnostics.get("local_device_id", "") or "").strip()' in flyout
    assert 'self._render_devices(devices, local_device_id=local_device_id)' in flyout
    assert 'securityRequested = Signal()' in flyout
    assert 'self.security_link = HyperlinkLabel(tr("profile.security.link", "Account Security"), self)' in flyout
    assert 'self.security_link.clicked.connect(self.securityRequested.emit)' in flyout
    assert 'view.securityRequested.connect(self._handle_security_from_flyout)' in flyout
    assert 'def open_device_security_dialog(self) -> None:' in flyout
    assert 'dialog = DeviceSecurityDialog(self.window(), auth_controller=self._auth_controller)' in flyout
    assert 'async def list_my_e2ee_devices(self) -> list[dict[str, Any]]:' in auth_controller
    assert 'async def get_history_recovery_diagnostics(self) -> dict[str, Any]:' in auth_controller


def test_user_profile_flyout_wires_history_recovery_import_export() -> None:
    flyout = Path('client/ui/widgets/user_profile_flyout.py').read_text(encoding='utf-8')
    auth_controller = Path('client/ui/controllers/auth_controller.py').read_text(encoding='utf-8')

    assert 'self._action_task: Optional[asyncio.Task] = None' in flyout
    assert 'self.import_button = PushButton(tr("profile.security.import", "Import Recovery Package"), self)' in flyout
    assert 'self.import_button.clicked.connect(self._select_recovery_package_import)' in flyout
    assert 'export_button = PushButton(tr("profile.security.export", "Export Recovery Package"), card)' in flyout
    assert 'export_button.clicked.connect(lambda _checked=False, did=device_id: self._select_recovery_package_export(did))' in flyout
    assert 'def _select_recovery_package_export(self, device_id: str) -> None:' in flyout
    assert 'QFileDialog.getSaveFileName(' in flyout
    assert 'result = await self._auth_controller.export_history_recovery_package(device_id)' in flyout
    assert 'json.dump(result, handle, ensure_ascii=False, indent=2)' in flyout
    assert 'def _select_recovery_package_import(self) -> None:' in flyout
    assert 'QFileDialog.getOpenFileName(' in flyout
    assert 'package = self._extract_recovery_package(json.load(handle))' in flyout
    assert 'result = await self._auth_controller.import_history_recovery_package(package)' in flyout
    assert 'self.reload_devices()' in flyout
    assert 'async def export_history_recovery_package(' in auth_controller
    assert 'async def import_history_recovery_package(self, package: dict[str, Any] | None) -> dict[str, Any]:' in auth_controller



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


def test_contact_interface_profile_update_refreshes_group_member_projection_and_request_fields() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')
    apply_block = contact_interface.split('def _apply_profile_update_payload', 1)[1].split('async def _reload_data_async', 1)[0]

    assert 'def _group_member_display_name(member: dict[str, object]) -> str:' in contact_interface
    assert 'raw_members = [dict(item or {}) for item in list(merged_payload.get("members") or []) if isinstance(item, dict)]' in apply_block
    assert 'member["display_name"] = next_display_name' in apply_block
    assert 'groups_changed = False' in apply_block
    assert 'if groups_changed:' in apply_block
    assert 'self._schedule_groups_cache_persist()' in apply_block
    assert 'sender_username=request.sender_username' in apply_block
    assert 'receiver_username=request.receiver_username' in apply_block


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


def test_chat_interface_profile_update_without_session_id_refreshes_visible_messages() -> None:
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')
    profile_block = chat_interface.split('def _on_profile_updated', 1)[1].split('def load_sessions', 1)[0]

    assert 'target_session_id = session_id or str(self._current_session_id or "")' in profile_block
    assert 'self._invalidate_session_caches()' in profile_block
    assert 'self.chat_panel.apply_sender_profile_update(' in profile_block
    assert 'target_session_id,' in profile_block
    assert 'if not user_id or not profile:' in profile_block


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


def test_chat_search_and_call_entry_points_use_wired_actions_and_keep_direct_context() -> None:
    chat_header = Path('client/ui/widgets/chat_header.py').read_text(encoding='utf-8')
    chat_info_drawer = Path('client/ui/widgets/chat_info_drawer.py').read_text(encoding='utf-8')
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')
    chat_panel = Path('client/ui/widgets/chat_panel.py').read_text(encoding='utf-8')
    chat_controller = Path('client/ui/controllers/chat_controller.py').read_text(encoding='utf-8')
    message_manager = Path('client/managers/message_manager.py').read_text(encoding='utf-8')
    message_model = Path('client/models/message_model.py').read_text(encoding='utf-8')
    message_delegate = Path('client/delegates/message_delegate.py').read_text(encoding='utf-8')
    database = Path('client/storage/database.py').read_text(encoding='utf-8')
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')
    message_input = Path('client/ui/widgets/message_input.py').read_text(encoding='utf-8')
    group_dialogs = Path('client/ui/windows/group_creation_dialogs.py').read_text(encoding='utf-8')
    group_flow = Path('client/ui/windows/chat_group_flow.py').read_text(encoding='utf-8')
    search_manager = Path('client/managers/search_manager.py').read_text(encoding='utf-8')
    search_panel = Path('client/ui/widgets/global_search_panel.py').read_text(encoding='utf-8')

    assert 'self.history_button.hide()' not in chat_header
    assert 'self.history_button.setEnabled(enabled)' in chat_header
    assert 'self.search_row.hide()' not in chat_info_drawer
    assert 'self.clear_button.hide()' not in chat_info_drawer
    assert 'class ChatSessionSearchDialog(FluentDialog):' in chat_interface
    assert 'self.chat_panel.chat_history_requested.connect(self._on_chat_history_requested)' in chat_interface
    assert 'self.chat_panel.chat_info_search_requested.connect(self._on_chat_info_search_requested)' in chat_interface
    assert 'self._open_session_search_dialog(source="header")' in chat_interface
    assert 'self._open_session_search_dialog(source="info_drawer")' in chat_interface
    assert 'search_message_hits(keyword, session_id=self._session_id, limit=self.SEARCH_LIMIT)' in chat_interface
    assert 'SearchCatalogResults(messages=results, contacts=[], groups=[], message_total=len(results))' in chat_interface
    assert 'self._open_chat_search_result(payload, generation)' in chat_interface
    assert 'self.chat_panel.scroll_to_message(message_id, flash=True)' in chat_interface
    assert 'await self._chat_controller.load_cached_message_context(' in chat_interface
    assert 'tr("chat.info.search.result_missing"' in chat_interface
    assert 'def scroll_to_message(self, message_id: str, *, flash: bool = True) -> bool:' in chat_panel
    assert 'def display_row_for_message(self, message_id: str) -> int:' in message_model
    assert 'def flash_message(self, view, message_id: str, *, duration_ms: int = 1400) -> None:' in message_delegate
    assert 'async def load_cached_message_context(' in chat_controller
    assert 'async def get_cached_message_context(' in message_manager
    assert 'async def get_message_context(' in database
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


def test_contact_detail_call_entry_opens_direct_chat_before_starting_call() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')
    main_window = Path('client/ui/windows/main_window.py').read_text(encoding='utf-8')
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')

    assert 'class ContactDetailPanel(QWidget):' not in contact_interface
    assert 'contact.detail.unavailable_content' not in contact_interface
    assert 'self.voice_button.clicked.connect(self._show_unavailable)' not in contact_interface
    assert 'self.video_button.clicked.connect(self._show_unavailable)' not in contact_interface
    assert 'call_requested = Signal(object, str)' in contact_interface
    assert 'self.voice_button.clicked.connect(lambda _checked=False: self._emit_call_request("voice"))' in contact_interface
    assert 'self.video_button.clicked.connect(lambda _checked=False: self._emit_call_request("video"))' in contact_interface
    assert 'def _set_call_buttons_available(self, available: bool) -> None:' in contact_interface
    assert 'self._set_call_buttons_available(True)' in contact_interface
    assert contact_interface.count('self._set_call_buttons_available(False)') >= 4
    assert 'self.detail_panel.call_requested.connect(self.call_requested.emit)' in contact_interface
    assert 'self.contact_interface.call_requested.connect(self._on_contact_call_requested)' in main_window
    assert 'def _on_contact_call_requested(self, payload: object, media_type: str) -> None:' in main_window
    assert '"_call_media_type": media_type' in main_window
    assert 'call_media_type = str(payload.get("_call_media_type", "") or "")' in main_window
    assert 'self.chat_interface.start_current_session_call(call_media_type)' in main_window
    assert 'def start_current_session_call(self, media_type: str) -> None:' in chat_interface


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

    assert 'class ChatInfoAnnouncementDialog(FluentDialog):' in drawer
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
    assert 'class ClearChatHistoryConfirmDialog(MessageBoxBase):' in chat_interface
    assert 'self._subscribe_sync(MessageEvent.HISTORY_CLEARED, self._on_history_cleared_event)' in chat_interface
    assert 'self._session_controller.clear_session_history(session_id)' in chat_interface
    assert 'dialog = GroupMemberManagementDialog(' in chat_interface
    assert 'def _show_dialog(self, dialog: QDialog) -> None:' in chat_interface
    assert 'async def clear_session_history(self, session_id: str) -> dict[str, Any]:' in session_controller
    assert 'self._session_controller.set_group_member_nickname_visibility(session_id, _enabled)' in chat_interface
    assert 'def _group_record_payload(record) -> dict[str, object]:' in chat_interface
    assert 'class GroupManagementPermissions:' in dialogs
    assert 'class GroupMemberManagementDialog(FluentDialog):' in dialogs
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
    assert 'class IdentityReviewDialog(FluentDialog):' in chat_interface
    assert 'self.identity_row.setVisible(str(security_summary.get("encryption_mode") or "") == "e2ee_private")' in drawer
    assert 'def restore_recalled_message_to_composer(self, message_id: str) -> bool:' in chat_panel
    assert 'def replace_message(self, message: ChatMessage) -> None:' in chat_panel
    assert 'self._message_delegate.set_session(None)' in chat_panel
    assert 'layout_changed = bool(self._message_delegate and self._message_delegate.set_session(session))' in chat_panel
    assert 'class EditMessageDialog(QDialog):' not in chat_interface
    assert 'self._session_manager.set_user_id(user_id)' in Path('client/ui/controllers/chat_controller.py').read_text(encoding='utf-8')


def test_chat_info_group_delete_and_contact_remove_entries_are_wired() -> None:
    chat_interface = Path('client/ui/windows/chat_interface.py').read_text(encoding='utf-8')
    chat_panel = Path('client/ui/widgets/chat_panel.py').read_text(encoding='utf-8')
    drawer = Path('client/ui/widgets/chat_info_drawer.py').read_text(encoding='utf-8')
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')
    contact_controller = Path('client/ui/controllers/contact_controller.py').read_text(encoding='utf-8')
    contact_service = Path('client/services/contact_service.py').read_text(encoding='utf-8')

    assert 'class DeleteGroupConfirmDialog(MessageBoxBase):' in chat_interface
    assert 'chat_info_delete_group_requested = Signal()' in chat_panel
    assert 'self._chat_info_overlay.deleteGroupRequested.connect(self.chat_info_delete_group_requested.emit)' in chat_panel
    assert 'self.chat_panel.chat_info_delete_group_requested.connect(self._on_chat_info_delete_group_requested)' in chat_interface
    assert 'async def _delete_group_async(self, session_id: str, group_id: str, group_name: str) -> None:' in chat_interface
    assert 'await self._contact_controller.delete_group(group_id)' in chat_interface
    assert 'DeleteGroupConfirmDialog(session.chat_title() or session.display_name(), self.window())' in chat_interface

    assert 'deleteGroupRequested = Signal()' in drawer
    assert 'self.delete_group_button = StaticHyperlinkButton(parent=self)' in drawer
    assert 'self.delete_group_button.clicked.connect(self.deleteGroupRequested.emit)' in drawer
    assert 'self.delete_group_button.setVisible(is_owner)' in drawer
    assert 'self.leave_button.setVisible(not is_owner)' in drawer
    assert 'self.view_more_button.clicked.connect(lambda: self._emit_member_management_request("browse"))' in drawer
    assert 'add_tile.clicked.connect(lambda: self._emit_member_management_request("add"))' in drawer
    assert 'remove_tile.clicked.connect(lambda: self._emit_member_management_request("remove"))' in drawer

    assert 'class RemoveFriendConfirmDialog(MessageBoxBase):' in contact_interface
    assert 'remove_action = Action(tr("contact.detail.action.remove_friend", "Remove Friend"), self)' in contact_interface
    assert 'remove_action.triggered.connect(' in contact_interface
    assert 'self.remove_friend_button' not in contact_interface
    assert 'self.detail_panel.remove_requested.connect(self._on_remove_friend_requested)' not in contact_interface
    assert 'async def _remove_friend_async(self, contact_id: str, display_name: str) -> None:' in contact_interface
    assert 'await self._controller.remove_friend(contact_id)' in contact_interface
    assert 'async def delete_group(self, group_id: str) -> dict:' in contact_controller
    assert 'async def delete_group(self, group_id: str) -> dict[str, Any]:' in contact_service


def test_contact_friend_item_context_menu_wires_block_action() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')
    contact_controller = Path('client/ui/controllers/contact_controller.py').read_text(encoding='utf-8')
    contact_service = Path('client/services/contact_service.py').read_text(encoding='utf-8')

    assert 'class BlockFriendConfirmDialog(MessageBoxBase):' in contact_interface
    assert 'context_requested = Signal(str, QPoint)' in contact_interface
    assert 'item.context_requested.connect(self._show_friend_context_menu)' in contact_interface
    assert 'def _show_friend_context_menu(self, contact_id: str, global_pos: QPoint) -> None:' in contact_interface
    assert 'block_action = Action(tr("contact.context.block", "Block"), self)' in contact_interface
    assert 'self._on_block_friend_requested(cid)' in contact_interface
    assert 'async def _block_friend_async(self, contact_id: str, display_name: str) -> None:' in contact_interface
    assert 'await self._controller.block_user(contact_id)' in contact_interface
    assert 'self._remove_friend_item_view(contact_id)' in contact_interface
    assert 'async def block_user(self, target_user_id: str) -> dict:' in contact_controller
    assert 'async def block_user(self, target_user_id: str) -> dict[str, Any]:' in contact_service


def test_contact_block_list_tab_wires_unblock_flow() -> None:
    contact_interface = Path('client/ui/windows/contact_interface.py').read_text(encoding='utf-8')
    contact_controller = Path('client/ui/controllers/contact_controller.py').read_text(encoding='utf-8')
    contact_service = Path('client/services/contact_service.py').read_text(encoding='utf-8')

    assert 'self._blocked_contacts: list[ContactRecord] = []' in contact_interface
    assert 'self._blocked_items: dict[str, ContactListItem] = {}' in contact_interface
    assert 'self.segmented.addItem("blocked", tr("contact.sidebar.tab.blocked", "Blocked"), lambda: self._switch_page("blocked"))' in contact_interface
    assert 'self.blocked_page, self.blocked_container, self.blocked_layout = self._create_scroll_page()' in contact_interface
    assert 'blocked = await self._controller.load_blocked_contacts()' in contact_interface
    assert 'self._build_blocked_page()' in contact_interface
    assert 'def _show_blocked_context_menu(self, contact_id: str, global_pos: QPoint) -> None:' in contact_interface
    assert 'unblock_action = Action(tr("contact.context.unblock", "Unblock"), self)' in contact_interface
    assert 'async def _unblock_contact_async(self, contact_id: str, display_name: str) -> None:' in contact_interface
    assert 'await self._controller.unblock_user(contact_id)' in contact_interface
    assert 'async def load_blocked_contacts(self) -> list[ContactRecord]:' in contact_controller
    assert 'async def fetch_blocks(self) -> list[dict[str, Any]]:' in contact_service


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
    assert 'class GroupAnnouncementDialog(FluentDialog):' in dialog
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
    assert 'def _security_action_reason_code(result: dict[str, object]) -> str:' in chat_interface
    assert 'def _security_action_failure_message(self, result: dict[str, object]) -> str:' in chat_interface
    assert 'message = str(explanation.get("message") or result.get("reason") or "").strip()' not in chat_interface
    assert 'message = str(action_result.get("explanation") or action_result.get("reason") or "").strip()' not in chat_interface
    assert 'def _recall_failure_message(self, reason: str) -> str:' in chat_interface
    assert 'reason or tr("chat.recall_failed"' not in chat_interface


def test_chat_error_i18n_keys_exist() -> None:
    required_keys = {
        "chat.call.failed_generic",
        "chat.media.upload_failed",
        "chat.media.uploading",
        "chat.security.action.failed_generic",
        "chat.recall_failed_generic",
    }

    for language in ("zh-CN", "en-US", "ko-KR"):
        payload = json.loads(Path(f"client/resources/i18n/{language}.json").read_text(encoding="utf-8"))
        missing = sorted(required_keys - set(payload))
        assert missing == []


def test_completed_feature_i18n_no_longer_marks_wired_entries_as_unavailable() -> None:
    stale_keys = {
        "chat.voice_call.unavailable",
        "chat.video_call.unavailable",
        "contact.detail.unavailable_content",
        "chat.info.group.content",
        "chat.info.group.leave.unavailable",
        "chat.info.group.remove.unavailable",
        "chat.info.group.show_member_nickname.unavailable",
        "chat.info.history.unavailable",
        "chat.info.search.unavailable",
        "chat.info.add.unavailable",
    }

    for language in ("zh-CN", "en-US", "ko-KR"):
        payload = json.loads(Path(f"client/resources/i18n/{language}.json").read_text(encoding="utf-8"))
        present = sorted(stale_keys & set(payload))
        assert present == []


def test_completed_feature_docs_use_current_implemented_baseline() -> None:
    paths = {
        "ai_feature_design": Path('docs/design/ai_feature_detailed_design.md'),
        "summary_design": Path('docs/design/chat_local_summary_design.md'),
        "backend_architecture": Path('docs/architecture/backend_architecture.md'),
        "action_design": Path('docs/design/ai_action_workflow_design.md'),
    }
    if not all(path.exists() for path in paths.values()):
        return

    ai_feature_design = paths["ai_feature_design"].read_text(encoding='utf-8')
    summary_design = paths["summary_design"].read_text(encoding='utf-8')
    backend_architecture = paths["backend_architecture"].read_text(encoding='utf-8')
    action_design = paths["action_design"].read_text(encoding='utf-8')

    assert "本地 GGUF Provider 尚未落地" not in ai_feature_design
    assert "RAG、本地知识库、多模态推理、多模型自动路由。" not in ai_feature_design
    assert "本文档只输出设计，不包含本轮代码改动。" not in summary_design
    assert "后续接入私聊 E2EE 与 1:1 通话后" not in backend_architecture
    assert "当前真实发送未接入时" not in action_design


def test_message_delegate_media_state_text_is_internationalized() -> None:
    message_delegate = Path('client/delegates/message_delegate.py').read_text(encoding='utf-8')

    assert 'return tr("chat.media.uploading", "Uploading...")' in message_delegate
    assert 'return tr("chat.media.upload_failed", "Upload failed")' in message_delegate
    assert 'return "Uploading..."' not in message_delegate
    assert 'return "Upload failed"' not in message_delegate


def test_discovery_interface_tracks_image_dialogs_for_runtime_teardown() -> None:
    discovery_interface = Path('client/ui/windows/discovery_interface.py').read_text(encoding='utf-8')

    assert 'self._image_dialogs: set[QDialog] = set()' in discovery_interface
    assert 'for dialog in list(getattr(self, "_image_dialogs", ())):' in discovery_interface
    assert 'self._image_dialogs.clear()' in discovery_interface

