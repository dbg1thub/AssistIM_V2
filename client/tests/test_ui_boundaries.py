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

    assert 'InfoBar.success(tr("auth.feedback.title", "Authentication"), message, parent=self.form_card)' not in auth_interface
    assert 'self.last_success_message =' in auth_interface
    assert 'self._pending_auth_success_message' in app_main
    assert 'InfoBar.success(' in app_main
    assert 'self.contact_interface.reload_data()' not in main_window
    assert 'self.contact_interface.refresh_groups_after_profile_change()' in main_window


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
    assert 'def refresh_groups_after_profile_change(self) -> None:' in contact_interface
    assert 'def _apply_profile_update_payload(self, payload: dict[str, object]) -> None:' in contact_interface
    assert 'def _apply_group_update_payload(self, payload: dict[str, object]) -> None:' in contact_interface
    assert 'def _apply_group_self_profile_update_payload(self, payload: dict[str, object]) -> None:' in contact_interface
    assert 'def _schedule_groups_cache_persist(self) -> None:' in contact_interface
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
    assert 'self._insert_request_item_view(request)' in contact_interface
    assert 'self._controller.merge_group_record(self._groups, group)' in contact_interface
    assert 'self._sync_group_record_view(created_group, rebuild=rebuild)' in contact_interface
    assert 'self._activate_page("requests")' in contact_interface
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


def test_main_window_tray_alerts_respect_authoritative_mute_state() -> None:
    main_window = Path('client/ui/windows/main_window.py').read_text(encoding='utf-8')

    assert 'from client.managers.session_manager import SessionEvent, peek_session_manager' in main_window
    assert 'def _is_session_muted(self, session_id: str, session) -> bool:' in main_window
    assert 'return manager.is_session_muted(session_id)' in main_window
    assert 'if self._is_session_muted(session_id, session):' in main_window


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
    assert 'async def _open_file_attachment(self, message) -> None:' in chat_interface
    assert 'await self._chat_controller.download_message_attachment(message.message_id)' in chat_interface
    assert 'async def download_message_attachment(self, message_id: str) -> str:' in chat_controller
    assert message_delegate.count('if attachment_encryption.get("enabled"):\n            return ""') >= 2
    assert 'self._subscribe_sync(MessageEvent.MEDIA_READY, self._on_media_ready)' in chat_interface
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




def test_message_repo_event_sync_casts_ids_for_runtime_varchar_tables() -> None:
    message_repo = Path('server/app/repositories/message_repo.py').read_text(encoding='utf-8')
    session_repo = Path('server/app/repositories/session_repo.py').read_text(encoding='utf-8')

    assert 'from sqlalchemy import String, and_, cast, desc, func, or_, select, update' in message_repo
    assert 'cast(SessionEvent.session_id, String()) == str(session_id or "").strip()' in message_repo
    assert 'cast(UserSessionEvent.session_id, String()) == str(session_id or "").strip()' in message_repo
    assert 'cast(UserSessionEvent.user_id, String()) == normalized_user_id' in message_repo
    assert 'from sqlalchemy import String, cast, delete, select' in session_repo
    assert 'from app.models.session import ChatSession, SessionEvent, SessionMember, UserSessionEvent' in session_repo
    assert 'delete(SessionEvent).where(cast(SessionEvent.session_id, String()) == normalized_session_id)' in session_repo
    assert 'delete(UserSessionEvent).where(cast(UserSessionEvent.session_id, String()) == normalized_session_id)' in session_repo
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
    assert 'chat_info_clear_requested = Signal()' in chat_panel
    assert 'chat_info_show_nickname_toggled = Signal(bool)' in chat_panel
    assert 'chat_info_member_management_requested = Signal(object)' in chat_panel
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
    assert 'async def _confirm_security_pending_messages(self, session_id: str, action_id: str) -> None:' in chat_interface
    assert 'await self._chat_controller.release_session_security_pending_messages(session_id)' in chat_interface
