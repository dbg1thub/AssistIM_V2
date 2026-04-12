"""Chat window container that keeps the new architecture but migrates old UI styling."""

from __future__ import annotations

import asyncio
import logging
import os
from collections import OrderedDict
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPalette, QPixmap
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from qfluentwidgets import (
    Action,
    BodyLabel,
    InfoBar,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    RoundMenu,
    SubtitleLabel,
    isDarkTheme,
)
from qfluentwidgets.components.widgets.menu import MenuAnimationType

from client.core.avatar_utils import profile_avatar_seed
from client.core.datetime_utils import coerce_local_datetime
from client.core.exceptions import AppError
from client.core.i18n import tr
from client.events.contact_events import ContactEvent
from client.core.message_actions import should_offer_delete, should_offer_recall
from client.events.event_bus import get_event_bus
from client.managers.call_manager import CallEvent
from client.managers.message_manager import MessageEvent
from client.managers.session_manager import SessionEvent
from client.managers.sound_manager import AppSound, get_sound_manager
from client.models.call import ActiveCallState, CallMediaType
from client.models.message import ChatMessage, MessageStatus, MessageType, format_message_preview
from client.ui.controllers.auth_controller import get_auth_controller
from client.ui.controllers.chat_controller import get_chat_controller
from client.ui.controllers.contact_controller import get_contact_controller
from client.ui.controllers.session_controller import get_session_controller
from client.ui.styles import StyleSheet
from client.ui.windows.chat_group_flow import ChatGroupFlowCoordinator
from client.ui.windows.call_window import CallWindow
from client.ui.widgets.chat_panel import ChatPanel
from client.ui.widgets.incoming_call_toast import IncomingCallToast
from client.ui.widgets.chat_info_drawer import (
    GroupMemberManagementRequest,
    GroupProfileUpdateRequest,
    GroupSelfProfileUpdateRequest,
)
from client.ui.widgets.fluent_splitter import FluentSplitter
from client.ui.widgets.screenshot_overlay import ScreenshotOverlay
from client.ui.widgets.session_panel import SessionPanel
from client.ui.windows.group_member_management_dialogs import GroupMemberManagementDialog
from client.ui.windows.group_announcement_dialog import GroupAnnouncementDialog


logger = logging.getLogger(__name__)


def _apply_themed_dialog_surface(dialog: QDialog, object_name: str, *, radius: int = 14) -> None:
    """Apply one stable theme-aware palette to plain chat dialogs."""
    dialog.setObjectName(object_name)
    dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    dialog.setAutoFillBackground(True)
    background = QColor(39, 43, 48) if isDarkTheme() else QColor(255, 255, 255)
    palette = dialog.palette()
    palette.setColor(QPalette.ColorRole.Window, background)
    palette.setColor(QPalette.ColorRole.Base, background)
    dialog.setPalette(palette)


def _prepare_transparent_scroll_area(area: QScrollArea) -> None:
    """Keep plain Qt scroll areas transparent so dialog surfaces show through."""
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    area.setAutoFillBackground(False)
    area.setStyleSheet("QScrollArea{background: transparent; border: none;} QAbstractScrollArea{background: transparent; border: none;}")
    viewport = area.viewport()
    if viewport is not None:
        viewport.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        viewport.setAutoFillBackground(False)
        viewport.setStyleSheet("background: transparent; border: none;")


class ScreenshotPreviewDialog(QDialog):
    """Preview a captured screenshot before sending it."""

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.setWindowTitle(tr("chat.screenshot.preview_title", "Preview Screenshot"))
        self.resize(760, 560)
        self.setModal(True)
        _apply_themed_dialog_surface(self, "ScreenshotPreviewDialog")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _prepare_transparent_scroll_area(self.scroll_area)

        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setText(tr("chat.screenshot.unavailable", "Unable to load screenshot"))
        self.scroll_area.setWidget(self.image_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.cancel_button = PushButton(tr("common.cancel", "Cancel"), self)
        self.confirm_button = PrimaryPushButton(tr("common.send", "Send"), self)
        self.cancel_button.clicked.connect(self.reject)
        self.confirm_button.clicked.connect(self.accept)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.confirm_button)

        layout.addWidget(self.scroll_area, 1)
        layout.addLayout(button_row)

        pixmap = QPixmap(file_path)
        if not pixmap.isNull():
            self.image_label.setPixmap(pixmap)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in {
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.StyleChange,
        }:
            _apply_themed_dialog_surface(self, "ScreenshotPreviewDialog")


class DeleteMessageConfirmDialog(MessageBoxBase):
    """Ask for confirmation before deleting one local chat message."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        title = SubtitleLabel(tr("chat.delete.confirm_title", "Delete Message"), self.widget)
        content = BodyLabel(
            tr(
                "chat.delete.confirm_content",
                "Delete this message from the current device? This action won't affect the other participant.",
            ),
            self.widget,
        )
        content.setWordWrap(True)
        self.viewLayout.addWidget(title)
        self.viewLayout.addWidget(content)
        self.viewLayout.addStretch(1)
        self.yesButton.setText(tr("chat.delete.confirm_action", "Delete"))
        self.cancelButton.setText(tr("common.cancel", "Cancel"))
        self.widget.setMinimumWidth(360)


class LeaveGroupConfirmDialog(MessageBoxBase):
    """Ask for confirmation before leaving one group chat."""

    def __init__(self, group_name: str, parent=None):
        super().__init__(parent=parent)
        title = SubtitleLabel(tr("chat.info.group.leave.title", "Leave Group Chat"), self.widget)
        content = BodyLabel(
            tr(
                "chat.info.group.leave.confirm",
                "Leave {name}? You will stop receiving new messages from this group.",
                name=group_name or tr("session.unnamed", "Untitled Session"),
            ),
            self.widget,
        )
        content.setWordWrap(True)
        self.viewLayout.addWidget(title)
        self.viewLayout.addWidget(content)
        self.viewLayout.addStretch(1)
        self.yesButton.setText(tr("chat.info.group.leave.action", "Leave"))
        self.cancelButton.setText(tr("common.cancel", "Cancel"))
        self.widget.setMinimumWidth(380)


class IncomingCallDialog(MessageBoxBase):
    """Prompt the user to accept or reject one incoming call invite."""

    def __init__(self, title: str, content: str, *, accept_label: str, reject_label: str, parent=None):
        super().__init__(parent=parent)
        title_label = SubtitleLabel(title, self.widget)
        content_label = BodyLabel(content, self.widget)
        content_label.setWordWrap(True)
        self.viewLayout.addWidget(title_label)
        self.viewLayout.addWidget(content_label)
        self.viewLayout.addStretch(1)
        self.yesButton.setText(accept_label)
        self.cancelButton.setText(reject_label)
        self.widget.setMinimumWidth(380)


class ChatInterface(QWidget):
    """Main chat interface with session list on the left and chat view on the right."""

    SESSION_PANEL_WIDTH = 300
    MESSAGE_PAGE_SIZE = 50
    HISTORY_PAGE_CACHE_LIMIT = 12
    INITIAL_HISTORY_WARM_CONCURRENCY = 2
    INITIAL_HISTORY_WARM_SESSION_LIMIT = 6
    TYPING_INDICATOR_HIDE_DELAY_MS = 1800
    CALL_RING_REPEAT_MS = 3000
    CALL_INCOMING_RING_RETRY_MS = 180

    def __init__(self, parent=None):
        super().__init__(parent)

        self._chat_controller = get_chat_controller()
        self._contact_controller = get_contact_controller()
        self._auth_controller = get_auth_controller()
        self._session_controller = get_session_controller()
        self._ui_callback_generation = 0
        self._current_session_id: Optional[str] = None
        self._session_focus_generation = 0
        self._load_task: Optional[asyncio.Task] = None
        self._event_bus = get_event_bus()
        self._event_subscriptions: list[tuple[str, object]] = []
        self._screenshot_overlays: set[ScreenshotOverlay] = set()
        self._screenshot_dialogs: set[ScreenshotPreviewDialog] = set()
        self._dialog_refs: set[QWidget] = set()
        self._incoming_call_toasts: dict[str, IncomingCallToast] = {}
        self._call_window: CallWindow | None = None
        self._call_result_messages_sent: set[tuple[str, str]] = set()
        self._active_call_ring_sound: AppSound | None = None
        self._session_visibility_active = False
        self._current_session_active = False
        self._oldest_loaded_timestamp: Optional[float] = None
        self._oldest_loaded_session_seq: Optional[int] = None
        self._has_more_history = True
        self._history_load_task: Optional[asyncio.Task] = None
        self._history_page_cache: dict[str, OrderedDict[tuple[Optional[float], Optional[int], int], list]] = {}
        self._history_page_warm_keys: set[tuple[str, Optional[float], Optional[int], int]] = set()
        self._history_page_tasks: dict[tuple[str, Optional[float], Optional[int], int], asyncio.Task] = {}
        self._startup_history_prefetch_task: Optional[asyncio.Task] = None
        self._session_view_state: dict[str, dict] = {}
        self._last_read_receipts: dict[str, str] = {}
        self._pending_read_receipts: set[tuple[str, str]] = set()
        self._composer_drafts: dict[str, list[dict]] = {}
        self._ui_tasks: set[asyncio.Task] = set()
        self._message_context_menu: RoundMenu | None = None
        self._teardown_started = False
        self._typing_indicator_timer = QTimer(self)
        self._typing_indicator_timer.setSingleShot(True)
        self._call_ring_timer = QTimer(self)
        self._call_ring_timer.setSingleShot(False)

        self._setup_ui()
        self._group_flow = ChatGroupFlowCoordinator(
            auth_controller=self._auth_controller,
            contact_controller=self._contact_controller,
            dialog_refs=self._dialog_refs,
            window_provider=self.window,
            schedule_ui_task=self._schedule_ui_task,
            close_chat_info_drawer=lambda: self.chat_panel.close_chat_info_drawer(immediate=True),
            open_group_session=self.open_group_session,
        )
        self._typing_indicator_timer.timeout.connect(self.chat_panel.hide_typing_indicator)
        self._call_ring_timer.timeout.connect(self._on_call_ring_timer)
        self._connect_signals()
        self._subscribe_to_events()
        self.destroyed.connect(self._on_destroyed)

    def _setup_ui(self) -> None:
        """Set up the two-column chat layout."""
        self.setObjectName("ChatInterface")

        self.splitter = FluentSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setObjectName("chatSplitter")

        self.session_panel = SessionPanel(self)
        self.chat_panel = ChatPanel(self)
        self.session_panel.setMinimumWidth(0)
        self.chat_panel.setMinimumWidth(0)

        self.chat_panel.set_send_segments_callback(self._on_send_segments)
        self.chat_panel.security_pending_confirm_requested.connect(self._on_security_pending_confirm_requested)
        self.chat_panel.security_pending_discard_requested.connect(self._on_security_pending_discard_requested)
        self.chat_panel.set_send_typing_callback(self._on_send_typing)
        self.chat_panel.set_attachment_open_callback(self._open_message)

        self.splitter.addWidget(self.session_panel)
        self.splitter.addWidget(self.chat_panel)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setSizes([self.SESSION_PANEL_WIDTH, 760])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setHandleWidth(1)
        self.splitter.splitterMoved.connect(self._on_splitter_moved)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.splitter)
        StyleSheet.CHAT_INTERFACE.apply(self)

    def _connect_signals(self) -> None:
        """Connect panel-level signals."""
        self.session_panel.session_selected.connect(self._on_session_selected)
        self.session_panel.search_result_requested.connect(self._on_sidebar_search_result_requested)
        self.chat_panel.composer_draft_changed.connect(self._on_composer_draft_changed)
        self.chat_panel.file_upload_requested.connect(self._on_file_upload_requested)
        self.chat_panel.screenshot_requested.connect(self._on_screenshot_requested)
        self.chat_panel.voice_call_requested.connect(self._on_voice_call_requested)
        self.chat_panel.video_call_requested.connect(self._on_video_call_requested)
        self.chat_panel.older_messages_requested.connect(self._on_older_messages_requested)
        self.chat_panel.chat_history_requested.connect(self._on_chat_history_requested)
        self.chat_panel.chat_info_add_requested.connect(self._on_chat_info_add_requested)
        self.chat_panel.chat_info_search_requested.connect(self._on_chat_info_search_requested)
        self.chat_panel.chat_info_clear_requested.connect(self._on_chat_info_clear_requested)
        self.chat_panel.chat_info_leave_requested.connect(self._on_chat_info_leave_requested)
        self.chat_panel.chat_info_mute_toggled.connect(self._on_chat_info_mute_toggled)
        self.chat_panel.chat_info_pin_toggled.connect(self._on_chat_info_pin_toggled)
        self.chat_panel.chat_info_show_nickname_toggled.connect(self._on_chat_info_show_nickname_toggled)
        self.chat_panel.chat_info_member_management_requested.connect(self._on_chat_info_member_management_requested)
        self.chat_panel.chat_info_group_profile_update_requested.connect(self._on_chat_info_group_profile_update_requested)
        self.chat_panel.chat_info_group_self_profile_update_requested.connect(self._on_chat_info_group_self_profile_update_requested)
        self.chat_panel.group_announcement_requested.connect(self._on_group_announcement_requested)
        self.chat_panel.get_message_list().customContextMenuRequested.connect(self._on_message_context_menu)

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        """Force both panes to re-layout item widths while the splitter is dragged."""
        self._schedule_ui_single_shot(0, self.session_panel._relayout_session_list)
        self._schedule_ui_single_shot(0, self.chat_panel._relayout_message_list)

    def _on_sidebar_search_result_requested(self, payload: object) -> None:
        """Open a conversation from one grouped sidebar search result."""
        generation = self._advance_session_focus_generation()
        self._schedule_ui_task(
            self._open_sidebar_search_result(payload, generation),
            "open sidebar search result",
        )

    async def _open_sidebar_search_result(self, payload: object, generation: int) -> None:
        """Route sidebar search hits into the appropriate chat open flow."""
        if not isinstance(payload, dict):
            return

        target_type = str(payload.get("type", "") or "")
        data = payload.get("data") or {}
        opened = False

        if target_type == "group":
            session_id = str(data.get("session_id", "") or data.get("id", "") or "")
            if session_id:
                opened = await self.open_group_session(session_id, generation=generation)
        elif target_type == "message":
            session_id = str(data.get("session_id", "") or "")
            if session_id:
                opened = await self.open_session(session_id, generation=generation)
        else:
            user_id = str(data.get("id", "") or "")
            if user_id:
                opened = await self.open_direct_session(
                    user_id,
                    display_name=str(data.get("display_name", "") or data.get("name", "") or ""),
                    avatar=str(data.get("avatar", "") or ""),
                    generation=generation,
                )

        if not self._is_session_focus_generation_current(generation):
            return
        if not opened:
            InfoBar.warning(
                tr("main_window.contact_jump.unavailable_title", "Chat"),
                tr("main_window.contact_jump.unavailable_message", "Unable to open this conversation right now."),
                parent=self.window(),
                duration=2200,
            )

    def _subscribe_to_events(self) -> None:
        """Subscribe to session and message events for real-time UI updates."""
        self._subscribe_sync(SessionEvent.ADDED, self._on_session_event)
        self._subscribe_sync(SessionEvent.UPDATED, self._on_session_event)
        self._subscribe_sync(SessionEvent.DELETED, self._on_session_event)

        self._subscribe_sync(MessageEvent.SENT, self._on_message_sent)
        self._subscribe_sync(MessageEvent.RECEIVED, self._on_message_received)
        self._subscribe_sync(MessageEvent.ACK, self._on_message_ack)
        self._subscribe_sync(MessageEvent.DELIVERED, self._on_delivered_event)
        self._subscribe_sync(MessageEvent.FAILED, self._on_message_failed)
        self._subscribe_sync(MessageEvent.TYPING, self._on_typing_event)
        self._subscribe_sync(MessageEvent.READ, self._on_read_event)
        self._subscribe_sync(MessageEvent.EDITED, self._on_edited_event)
        self._subscribe_sync(MessageEvent.RECALLED, self._on_recalled_event)
        self._subscribe_sync(MessageEvent.DELETED, self._on_deleted_event)
        self._subscribe_sync(MessageEvent.MEDIA_READY, self._on_media_ready)
        self._subscribe_sync(MessageEvent.SYNC_COMPLETED, self._on_sync_completed)
        self._subscribe_sync(MessageEvent.PROFILE_UPDATED, self._on_profile_updated)
        self._subscribe_sync(CallEvent.INVITE_SENT, self._on_call_invite_sent)
        self._subscribe_sync(CallEvent.INVITE_RECEIVED, self._on_call_invite_received)
        self._subscribe_sync(CallEvent.RINGING, self._on_call_ringing)
        self._subscribe_sync(CallEvent.ACCEPTED, self._on_call_accepted)
        self._subscribe_sync(CallEvent.REJECTED, self._on_call_rejected)
        self._subscribe_sync(CallEvent.ENDED, self._on_call_ended)
        self._subscribe_sync(CallEvent.BUSY, self._on_call_busy)
        self._subscribe_sync(CallEvent.FAILED, self._on_call_failed)
        self._subscribe_sync(CallEvent.SIGNAL, self._on_call_signal)

    def _subscribe_sync(self, event_type: str, handler) -> None:
        """Subscribe and retain the exact handler object for later unsubscribe."""
        self._event_subscriptions.append((event_type, handler))
        self._event_bus.subscribe_sync(event_type, handler)

    def _unsubscribe_from_events(self) -> None:
        """Remove all event-bus subscriptions owned by this widget."""
        while self._event_subscriptions:
            event_type, handler = self._event_subscriptions.pop()
            self._event_bus.unsubscribe_sync(event_type, handler)

    def _on_destroyed(self, *_args) -> None:
        """Cancel outstanding UI tasks and remove event listeners on widget teardown."""
        self.quiesce()

    def quiesce(self) -> None:
        """Stop chat-page tasks before logout clears authenticated runtime."""
        if self._teardown_started:
            return
        self._teardown_started = True
        self._invalidate_ui_callback_generation()
        self._advance_session_focus_generation()
        self._unsubscribe_from_events()
        self.session_panel.quiesce()
        self._cancel_pending_task(self._load_task)
        self._load_task = None
        self._cancel_pending_task(self._history_load_task)
        self._history_load_task = None
        self._cancel_pending_task(self._startup_history_prefetch_task)
        self._startup_history_prefetch_task = None
        for task in list(self._history_page_tasks.values()):
            self._cancel_pending_task(task)
        self._history_page_tasks.clear()
        for dialog in list(self._dialog_refs):
            dialog.close()
        self._dialog_refs.clear()
        for toast in list(self._incoming_call_toasts.values()):
            toast.close()
        self._incoming_call_toasts.clear()
        self._close_call_window()
        self._cancel_all_ui_tasks()

    def _cancel_pending_task(self, task: Optional[asyncio.Task]) -> None:
        """Cancel one tracked task if it is still running."""
        if task is not None and not task.done():
            task.cancel()

    def _cancel_all_ui_tasks(self) -> None:
        """Cancel all background tasks launched from this widget."""
        for task in list(self._ui_tasks):
            if not task.done():
                task.cancel()

    def _create_ui_task(self, coro, context: str, *, on_done=None) -> asyncio.Task:
        """Create a tracked UI task that logs failures and is canceled on teardown."""
        task = asyncio.create_task(coro)
        self._ui_tasks.add(task)
        task.add_done_callback(lambda finished, name=context, callback=on_done: self._finalize_ui_task(finished, name, callback))
        return task

    def _finalize_ui_task(self, task: asyncio.Task, context: str, on_done=None) -> None:
        """Drop tracked tasks, run completion hooks, and report failures."""
        self._ui_tasks.discard(task)
        if on_done is not None:
            on_done(task)
        self._log_ui_task_result(task, context)

    def _set_load_task(self, coro, context: str) -> None:
        """Replace the active session-load task with a newly tracked one."""
        self._cancel_pending_task(self._load_task)
        task = self._create_ui_task(coro, context, on_done=self._clear_load_task)
        self._load_task = task

    def _clear_load_task(self, task: asyncio.Task) -> None:
        """Clear the active load task reference when it finishes."""
        if self._load_task is task:
            self._load_task = None

    def _set_history_load_task(self, coro, context: str) -> None:
        """Replace the active history-pagination task with a tracked one."""
        self._cancel_pending_task(self._history_load_task)
        task = self._create_ui_task(coro, context, on_done=self._clear_history_load_task)
        self._history_load_task = task

    def _clear_history_load_task(self, task: asyncio.Task) -> None:
        """Clear the active history-pagination task reference when it finishes."""
        if self._history_load_task is task:
            self._history_load_task = None

    def _invalidate_ui_callback_generation(self) -> None:
        """Drop delayed callbacks that belong to an older widget lifetime."""
        self._ui_callback_generation += 1

    def _is_ui_callback_generation_current(self, generation: int) -> bool:
        return generation == self._ui_callback_generation

    def _make_generation_bound_ui_callback(self, callback, *, generation: int | None = None):
        """Wrap one UI callback so stale widget-lifetime callbacks do nothing."""
        callback_generation = self._ui_callback_generation if generation is None else generation

        def guarded_callback(*args, **kwargs):
            if not self._is_ui_callback_generation_current(callback_generation):
                return
            callback(*args, **kwargs)

        return guarded_callback

    def _schedule_ui_single_shot(self, delay: int, callback, *, generation: int | None = None) -> None:
        """Schedule one delayed UI callback that expires on widget teardown."""
        QTimer.singleShot(delay, self._make_generation_bound_ui_callback(callback, generation=generation))

    def _advance_session_focus_generation(self) -> int:
        """Invalidate pending async work that was targeting an older session focus."""
        self._session_focus_generation += 1
        return self._session_focus_generation

    def _is_session_focus_generation_current(self, generation: int) -> bool:
        return generation == self._session_focus_generation

    def _is_current_session_context(self, session_id: str, generation: int) -> bool:
        return self._is_session_focus_generation_current(generation) and session_id == self._current_session_id

    @staticmethod
    def _message_session_id(message) -> str:
        return str(getattr(message, "session_id", "") or "")

    def _is_current_message_context(self, message, generation: int) -> bool:
        return self._is_current_session_context(self._message_session_id(message), generation)

    def _on_session_event(self, data: dict) -> None:
        """React to session lifecycle updates."""
        is_delete_event = (
            data.get("session_id") == self._current_session_id
            and "session" not in data
            and "sessions" not in data
        )
        if is_delete_event:
            self._advance_session_focus_generation()
            self._current_session_id = None
            self._set_current_session_active(False)
            self.chat_panel.clear_messages()
            self.chat_panel.show_welcome()
            return

        if not self._current_session_id:
            return

        sessions = data.get("sessions")
        if isinstance(sessions, list):
            current_session = next(
                (
                    session
                    for session in sessions
                    if getattr(session, "session_id", "") == self._current_session_id
                ),
                None,
            )
            if current_session is None:
                self._advance_session_focus_generation()
                self._current_session_id = None
                self._set_current_session_active(False)
                self.chat_panel.clear_messages()
                self.chat_panel.show_welcome()
                return
            self.chat_panel.set_session(current_session)
            return

        session = self._get_session(self._current_session_id)
        if session:
            self.chat_panel.set_session(session)
    def _on_message_sent(self, data: dict) -> None:
        """Append sent message to the current conversation."""
        message = data.get("message")
        if message:
            self._invalidate_session_caches(message.session_id)
        if message and message.session_id == self._current_session_id:
            self.chat_panel.add_message(message, scroll_to_bottom=True)

    def _on_message_received(self, data: dict) -> None:
        """Append received message to the current conversation."""
        message = data.get("message")
        if message:
            self._invalidate_session_caches(message.session_id)
        if message and message.session_id == self._current_session_id:
            self._typing_indicator_timer.stop()
            self.chat_panel.hide_typing_indicator()
            should_scroll = self.chat_panel.is_near_bottom()
            self.chat_panel.add_message(message, scroll_to_bottom=should_scroll)
            self._schedule_read_receipt()

    def _on_message_ack(self, data: dict) -> None:
        """Update message status after server acknowledgment."""
        message = data.get("message")
        message_id = data.get("message_id")
        if message:
            self._invalidate_session_caches(message.session_id)
        if message and message.session_id == self._current_session_id:
            # Replace the optimistic local message with the canonical ACK payload so
            # later read receipts can see server-assigned metadata like session_seq.
            self.chat_panel.add_message(message, scroll_to_bottom=False)
        elif message_id:
            self.chat_panel.update_message_status(message_id, MessageStatus.SENT)

    def _on_delivered_event(self, data: dict) -> None:
        """Update delivered state for the active conversation."""
        message = data.get("message")
        message_id = data.get("message_id") or (message.message_id if message else "")
        session_id = data.get("session_id") or (message.session_id if message else "")
        if not session_id or not message_id:
            return

        self._invalidate_session_caches(session_id)
        if session_id != self._current_session_id:
            return

        self.chat_panel.update_message_status(message_id, MessageStatus.DELIVERED)

    def _on_message_failed(self, data: dict) -> None:
        """Update failed message state."""
        message = data.get("message")
        if message:
            self._invalidate_session_caches(message.session_id)
        if message and message.session_id == self._current_session_id:
            self.chat_panel.add_message(message, scroll_to_bottom=True)
            self.chat_panel.update_message_status(message.message_id, MessageStatus.FAILED)

    def _on_typing_event(self, data: dict) -> None:
        """Show typing indicator for the active conversation only."""
        session_id = data.get("session_id", "")
        user_id = data.get("user_id", "")
        typing = data.get("typing", False)
        if not isinstance(typing, bool):
            return
        if session_id != self._current_session_id:
            return
        if user_id == self._current_user_id():
            return
        if typing:
            self.chat_panel.show_typing_indicator()
            self._typing_indicator_timer.start(self.TYPING_INDICATOR_HIDE_DELAY_MS)
            return
        self._typing_indicator_timer.stop()
        self.chat_panel.hide_typing_indicator()

    def _on_read_event(self, data: dict) -> None:
        """Update read-receipt metadata in the message list."""
        session_id = data.get("session_id", "")
        reader_id = data.get("user_id", "")
        last_read_seq = int(data.get("last_read_seq", 0) or 0)
        if not session_id or not reader_id or last_read_seq <= 0:
            return

        self._invalidate_session_caches(session_id)
        if session_id != self._current_session_id:
            return

        self.chat_panel.apply_read_receipt(session_id, reader_id, last_read_seq)


    def _on_edited_event(self, data: dict) -> None:
        """Update edited message content."""
        session_id = data.get("session_id", "")
        self._invalidate_session_caches(session_id)
        if session_id != self._current_session_id:
            return
        message = data.get("message")
        if not isinstance(message, ChatMessage):
            return
        self.chat_panel.replace_message(message)
        self._schedule_ui_task(self._refresh_session_preview(session_id), f"refresh preview {session_id}")

    def _on_recalled_event(self, data: dict) -> None:
        """Replace recalled message content."""
        session_id = data.get("session_id", "")
        self._invalidate_session_caches(session_id)
        if session_id != self._current_session_id:
            self._schedule_ui_task(self._refresh_session_preview(session_id), f"refresh preview {session_id}")
            return
        message = data.get("message")
        if not isinstance(message, ChatMessage):
            return
        self.chat_panel.replace_message(message)
        self._schedule_ui_task(self._refresh_session_preview(session_id), f"refresh preview {session_id}")

    def _on_deleted_event(self, data: dict) -> None:
        """Remove a deleted message and refresh session preview."""
        session_id = data.get("session_id", "")
        self._invalidate_session_caches(session_id)
        if session_id == self._current_session_id:
            self.chat_panel.remove_message(data.get("message_id", ""))
        self._schedule_ui_task(self._refresh_session_preview(session_id), f"refresh preview {session_id}")

    def _on_media_ready(self, data: dict) -> None:
        """Refresh one visible message after its encrypted media finished downloading locally."""
        session_id = str(data.get("session_id", "") or "")
        if not session_id:
            return
        self._invalidate_session_caches(session_id)
        if session_id != self._current_session_id:
            return
        message = data.get("message")
        if not isinstance(message, ChatMessage):
            return
        self.chat_panel.replace_message(message)

    def _on_sync_completed(self, data: dict) -> None:
        """Append synced history messages for the currently open session only."""
        messages = data.get("messages") or []
        for message in messages:
            session_id = getattr(message, "session_id", None)
            if session_id:
                self._invalidate_session_caches(session_id)

        if not self._current_session_id:
            return

        current_session_messages = [
            message
            for message in messages
            if getattr(message, "session_id", None) == self._current_session_id
        ]
        if current_session_messages:
            should_scroll = self.chat_panel.is_near_bottom()
            self.chat_panel.add_messages(current_session_messages, scroll_to_bottom=should_scroll)
            self._schedule_read_receipt()

    def _on_profile_updated(self, data: dict) -> None:
        """Refresh visible sender avatars/names after one participant profile change."""
        session_id = str(data.get("session_id", "") or "")
        if not session_id:
            return
        self._invalidate_session_caches(session_id)
        if session_id != self._current_session_id:
            return
        self.chat_panel.apply_sender_profile_update(
            session_id,
            str(data.get("user_id", "") or ""),
            dict(data.get("profile") or {}) if isinstance(data.get("profile"), dict) else {},
            changed_message_ids=list(data.get("changed_message_ids") or []),
        )

    def load_sessions(self) -> None:
        """Load current sessions into the left panel."""
        sessions = list(self._chat_controller.get_sessions())
        self.session_panel.load_sessions(sessions)
        self._schedule_initial_history_prefetch(sessions)

    def _schedule_initial_history_prefetch(self, sessions: list) -> None:
        """Warm the first page for a small batch of recent sessions in the background."""
        if self._startup_history_prefetch_task is not None and not self._startup_history_prefetch_task.done():
            return

        session_ids = [
            str(getattr(session, "session_id", "") or "")
            for session in sessions[: self.INITIAL_HISTORY_WARM_SESSION_LIMIT]
            if str(getattr(session, "session_id", "") or "")
        ]
        if not session_ids:
            return

        self._startup_history_prefetch_task = self._create_ui_task(
            self._warm_history_pages(session_ids),
            "warm initial history pages",
            on_done=self._clear_startup_history_prefetch_task,
        )

    def _clear_startup_history_prefetch_task(self, task: asyncio.Task) -> None:
        """Drop the startup history warmup bookkeeping when the task finishes."""
        if self._startup_history_prefetch_task is task:
            self._startup_history_prefetch_task = None

    def _on_session_selected(self, session_id: str) -> None:
        """Handle user selecting a conversation."""
        if session_id == self._current_session_id:
            return

        generation = self._advance_session_focus_generation()
        self._remember_current_session_view_state()
        self._remember_current_composer_draft()

        self._current_session_id = session_id
        session = self._get_session(session_id)
        if session:
            self.chat_panel.set_session(session)
            self._set_session_draft_preview(session_id, [])
            self.chat_panel.clear_composer_draft()
            self.chat_panel.restore_composer_draft(self._composer_drafts.get(session_id, []))
        else:
            self._current_session_id = None
            self._set_current_session_active(False)
            self.chat_panel.show_welcome()
            return

        self.chat_panel.clear_messages()
        self.chat_panel.set_has_more_history(True)
        self.chat_panel.set_history_loading(False)
        self._oldest_loaded_timestamp = None
        self._oldest_loaded_session_seq = None
        self._has_more_history = True

        self._cancel_pending_task(self._load_task)
        self._cancel_pending_task(self._history_load_task)

        cached_state = self._session_view_state.get(session_id)
        cached_page = self._peek_cached_history_page(session_id, before_timestamp=None, before_seq=None)
        if cached_state:
            self._restore_session_view_state(session_id, cached_state)
            self._set_load_task(self._select_session_only(session_id, generation), f"select session {session_id}")
        else:
            if cached_page:
                self._apply_primary_history_page(
                    session_id,
                    cached_page,
                    schedule_read_receipt=False,
                    generation=generation,
                )
            self._set_load_task(self._load_session_messages(session_id, generation), f"load session {session_id}")

    async def _load_session_messages(self, session_id: str, generation: int) -> None:
        """Load local messages for the selected session."""
        try:
            await self._chat_controller.select_session(session_id)
            if not self._is_current_session_context(session_id, generation):
                return
            self._activate_selected_session_if_visible(session_id)
            local_messages = self._peek_cached_history_page(session_id, before_timestamp=None, before_seq=None)
            if local_messages is None:
                local_messages = await self._chat_controller.load_cached_messages(
                    session_id,
                    limit=self.MESSAGE_PAGE_SIZE,
                    before_timestamp=None,
                )
                if local_messages:
                    self._cache_history_page(
                        session_id,
                        before_timestamp=None,
                        before_seq=None,
                        messages=local_messages,
                        warm=False,
                    )
            if self._is_current_session_context(session_id, generation) and local_messages:
                self._apply_primary_history_page(
                    session_id,
                    local_messages,
                    schedule_read_receipt=False,
                    generation=generation,
                )
            messages = await self._load_history_page(
                session_id,
                before_timestamp=None,
                before_seq=None,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Failed to load messages for %s: %s", session_id, exc)
            return

        if not self._is_current_session_context(session_id, generation):
            return

        self._apply_primary_history_page(session_id, messages, generation=generation)

    def _apply_primary_history_page(
        self,
        session_id: str,
        messages: list,
        *,
        schedule_read_receipt: bool = True,
        generation: int | None = None,
    ) -> None:
        """Render the primary history page while preserving any live in-memory messages."""
        if generation is not None:
            if not self._is_current_session_context(session_id, generation):
                return
        elif session_id != self._current_session_id:
            return

        merged_messages = self._merge_loaded_messages_with_visible(messages)
        self.chat_panel.set_messages(merged_messages)
        self._oldest_loaded_timestamp = self._extract_oldest_timestamp(merged_messages)
        self._oldest_loaded_session_seq = self._extract_oldest_session_seq(merged_messages)
        self._has_more_history = len(merged_messages) >= self.MESSAGE_PAGE_SIZE and self._oldest_loaded_session_seq is not None
        self.chat_panel.set_has_more_history(self._has_more_history)
        self.chat_panel.set_history_loading(False)
        self._store_session_view_state(session_id)
        if schedule_read_receipt:
            self._schedule_read_receipt()

    def _merge_loaded_messages_with_visible(self, loaded_messages: list) -> list:
        """Preserve live-arrived/status-updated messages while an async page load completes."""
        visible_messages = list(self.chat_panel.get_visible_messages())
        if not visible_messages:
            return list(loaded_messages)

        merged_by_id: dict[str, object] = {}
        ordered_messages = list(loaded_messages) + visible_messages
        for message in ordered_messages:
            message_id = getattr(message, "message_id", "")
            if not message_id:
                continue

            current = merged_by_id.get(message_id)
            if current is None:
                merged_by_id[message_id] = message
                continue

            current_updated = getattr(current, "updated_at", None) or getattr(current, "timestamp", None)
            candidate_updated = getattr(message, "updated_at", None) or getattr(message, "timestamp", None)
            if self._message_sort_key(candidate_updated, getattr(message, "message_id", "")) >= self._message_sort_key(
                current_updated,
                getattr(current, "message_id", ""),
            ):
                merged_by_id[message_id] = message

        return sorted(
            merged_by_id.values(),
            key=lambda item: self._message_sort_key(
                getattr(item, "timestamp", None),
                getattr(item, "message_id", ""),
            ),
        )

    @staticmethod
    def _message_sort_key(timestamp, message_id: str) -> tuple[float, str]:
        """Normalize message ordering for merged visible/history pages."""
        if isinstance(timestamp, datetime):
            return (timestamp.timestamp(), message_id)
        if hasattr(timestamp, "timestamp"):
            try:
                return (float(timestamp.timestamp()), message_id)
            except (TypeError, ValueError):
                return (0.0, message_id)
        try:
            return (float(timestamp), message_id)
        except (TypeError, ValueError):
            return (0.0, message_id)

    async def _select_session_only(self, session_id: str, generation: int) -> None:
        """Update session selection side effects without reloading the visible page from storage."""
        try:
            await self._chat_controller.select_session(session_id)
            if not self._is_current_session_context(session_id, generation):
                return
            self._activate_selected_session_if_visible(session_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Failed to select session %s: %s", session_id, exc)

    def _on_older_messages_requested(self) -> None:
        """Load the next older page when the list is scrolled to the top."""
        if not self._current_session_id or not self._has_more_history:
            self.chat_panel.set_history_loading(False)
            return

        if self._history_load_task and not self._history_load_task.done():
            return

        generation = self._session_focus_generation
        self._set_history_load_task(
            self._load_older_messages(self._current_session_id, generation),
            f"load older messages {self._current_session_id}",
        )

    async def _load_older_messages(self, session_id: str, generation: int) -> None:
        """Prepend one older history page while keeping the current viewport stable."""
        if not self._is_current_session_context(session_id, generation):
            return
        before_timestamp = self._oldest_loaded_timestamp
        before_seq = self._oldest_loaded_session_seq
        if before_seq is None:
            self.chat_panel.set_history_loading(False)
            self._has_more_history = False
            self.chat_panel.set_has_more_history(False)
            return

        try:
            messages = await self._load_history_page(session_id, before_timestamp=before_timestamp, before_seq=before_seq)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Failed to load older messages for %s: %s", session_id, exc)
            if self._is_current_session_context(session_id, generation):
                self.chat_panel.set_history_loading(False)
            return

        if not self._is_current_session_context(session_id, generation):
            return

        if not messages:
            self._has_more_history = False
            self.chat_panel.set_has_more_history(False)
            self.chat_panel.set_history_loading(False)
            return

        self.chat_panel.prepend_messages(messages)
        self._oldest_loaded_timestamp = self._extract_oldest_timestamp(messages)
        self._oldest_loaded_session_seq = self._extract_oldest_session_seq(messages)
        self._has_more_history = len(messages) >= self.MESSAGE_PAGE_SIZE and self._oldest_loaded_session_seq is not None
        self.chat_panel.set_has_more_history(self._has_more_history)
        self._store_session_view_state(session_id)

    @staticmethod
    def _extract_oldest_timestamp(messages) -> Optional[float]:
        """Return the timestamp of the oldest message in a loaded batch."""
        if not messages:
            return None

        oldest = messages[0].timestamp
        if hasattr(oldest, "timestamp"):
            return float(oldest.timestamp())
        try:
            return float(oldest)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_oldest_session_seq(messages) -> Optional[int]:
        """Return the canonical session_seq cursor for the oldest loaded message."""
        if not messages:
            return None
        try:
            session_seq = int(getattr(messages[0], "extra", {}).get("session_seq", 0) or 0)
        except (TypeError, ValueError):
            return None
        return session_seq if session_seq > 0 else None

    async def _load_history_page(
        self,
        session_id: str,
        before_timestamp: Optional[float],
        before_seq: Optional[int],
    ) -> list:
        """Load one history page, reusing cached local pages when available."""
        cache = self._history_page_cache.setdefault(session_id, OrderedDict())
        cache_key = (before_timestamp, before_seq, self.MESSAGE_PAGE_SIZE)
        cached_page = cache.get(cache_key)
        task_key = self._history_page_task_key(session_id, before_timestamp, before_seq)
        if cached_page is not None and (before_timestamp is not None or task_key in self._history_page_warm_keys):
            cache.move_to_end(cache_key)
            return list(cached_page)

        task = self._history_page_tasks.get(task_key)
        if task is None or task.done():
            task = asyncio.create_task(self._fetch_and_cache_history_page(session_id, before_timestamp, before_seq))
            self._history_page_tasks[task_key] = task

        try:
            messages = await task
        finally:
            if self._history_page_tasks.get(task_key) is task and task.done():
                self._history_page_tasks.pop(task_key, None)
        return list(messages)

    async def _fetch_and_cache_history_page(
        self,
        session_id: str,
        before_timestamp: Optional[float],
        before_seq: Optional[int],
    ) -> list:
        """Fetch one history page through the normal controller path and cache it as warm data."""
        messages = await self._chat_controller.load_messages(
            session_id,
            limit=self.MESSAGE_PAGE_SIZE,
            before_timestamp=before_timestamp,
            before_seq=before_seq,
        )
        self._cache_history_page(
            session_id,
            before_timestamp=before_timestamp,
            before_seq=before_seq,
            messages=messages,
            warm=True,
        )
        return list(messages)

    def _cache_history_page(
        self,
        session_id: str,
        *,
        before_timestamp: Optional[float],
        before_seq: Optional[int],
        messages: list,
        warm: bool,
    ) -> None:
        """Store one history page and remember whether it already includes remote backfill."""
        cache = self._history_page_cache.setdefault(session_id, OrderedDict())
        cache_key = (before_timestamp, before_seq, self.MESSAGE_PAGE_SIZE)
        cache[cache_key] = list(messages)
        cache.move_to_end(cache_key)

        task_key = self._history_page_task_key(session_id, before_timestamp, before_seq)
        if warm:
            self._history_page_warm_keys.add(task_key)
        else:
            self._history_page_warm_keys.discard(task_key)

        while len(cache) > self.HISTORY_PAGE_CACHE_LIMIT:
            dropped_key, _ = cache.popitem(last=False)
            self._history_page_warm_keys.discard((session_id, dropped_key[0], dropped_key[1], dropped_key[2]))

    def _peek_cached_history_page(
        self,
        session_id: str,
        *,
        before_timestamp: Optional[float],
        before_seq: Optional[int],
    ) -> Optional[list]:
        """Return one cached history page without triggering any async work."""
        cache = self._history_page_cache.get(session_id)
        if not cache:
            return None

        cache_key = (before_timestamp, before_seq, self.MESSAGE_PAGE_SIZE)
        cached_page = cache.get(cache_key)
        if cached_page is None:
            return None
        cache.move_to_end(cache_key)
        return list(cached_page)

    def _history_page_task_key(
        self,
        session_id: str,
        before_timestamp: Optional[float],
        before_seq: Optional[int],
    ) -> tuple[str, Optional[float], Optional[int], int]:
        """Build one stable identity for a cached history page."""
        return (session_id, before_timestamp, before_seq, self.MESSAGE_PAGE_SIZE)

    async def _warm_history_pages(self, session_ids: list[str]) -> None:
        """Warm the first history page for a batch of sessions with bounded concurrency."""
        normalized_ids = [session_id for session_id in session_ids if session_id]
        if not normalized_ids:
            return

        semaphore = asyncio.Semaphore(self.INITIAL_HISTORY_WARM_CONCURRENCY)

        async def worker(session_id: str) -> None:
            async with semaphore:
                await self._prime_history_page(session_id)
                await asyncio.sleep(0)

        await asyncio.gather(*(worker(session_id) for session_id in normalized_ids))

    async def _prime_history_page(self, session_id: str) -> None:
        """Seed the in-memory first page from local storage, then backfill it remotely."""
        if self._peek_cached_history_page(session_id, before_timestamp=None, before_seq=None) is None:
            local_messages = await self._chat_controller.load_cached_messages(
                session_id,
                limit=self.MESSAGE_PAGE_SIZE,
                before_timestamp=None,
            )
            if local_messages:
                self._cache_history_page(
                    session_id,
                    before_timestamp=None,
                    before_seq=None,
                    messages=local_messages,
                    warm=False,
                )

        await self._load_history_page(session_id, before_timestamp=None, before_seq=None)

    def _invalidate_history_cache(self, session_id: Optional[str] = None) -> None:
        """Drop cached local history pages when a session receives updates."""
        if session_id:
            self._history_page_cache.pop(session_id, None)
            self._history_page_warm_keys = {
                key for key in self._history_page_warm_keys if key[0] != session_id
            }
            task_keys = [key for key in self._history_page_tasks if key[0] == session_id]
            for key in task_keys:
                task = self._history_page_tasks.pop(key, None)
                self._cancel_pending_task(task)
        else:
            self._history_page_cache.clear()
            self._history_page_warm_keys.clear()
            for task in list(self._history_page_tasks.values()):
                self._cancel_pending_task(task)
            self._history_page_tasks.clear()

    def _invalidate_session_caches(self, session_id: Optional[str] = None) -> None:
        """Drop cached history and visible-state snapshots for mutated sessions."""
        self._invalidate_history_cache(session_id)
        if session_id:
            self._session_view_state.pop(session_id, None)
        else:
            self._session_view_state.clear()

    def _remember_current_session_view_state(self) -> None:
        """Persist the current visible message slice and scroll gap for the active session."""
        if not self._current_session_id:
            return
        self._store_session_view_state(self._current_session_id)

    def _remember_current_composer_draft(self) -> None:
        """Persist the current unsent text/attachment draft for the active session."""
        if not self._current_session_id:
            return

        segments = self.chat_panel.capture_composer_draft()
        self._store_session_draft_segments(self._current_session_id, segments)
        self._set_session_draft_preview(self._current_session_id, segments)

    def _on_composer_draft_changed(self, segments: list[dict]) -> None:
        """Keep the current session draft isolated and mirrored into the session list."""
        if not self._current_session_id:
            return
        self._store_session_draft_segments(self._current_session_id, segments)
        self._set_session_draft_preview(self._current_session_id, [])

    def _store_session_draft_segments(self, session_id: str, segments: list[dict]) -> None:
        """Store in-memory draft segments for one session."""
        if not session_id:
            return

        normalized_segments = list(segments or [])
        if normalized_segments:
            self._composer_drafts[session_id] = normalized_segments
        else:
            self._composer_drafts.pop(session_id, None)

    def _set_session_draft_preview(self, session_id: str, segments: list[dict]) -> None:
        """Update the left-list draft preview for one session."""
        if not session_id:
            return

        session = self._get_session(session_id)
        if not session:
            return

        draft_preview = self._draft_preview_from_segments(segments or [])
        setattr(session, "draft_preview", draft_preview or None)
        self.session_panel.update_session(session_id, draft_preview=getattr(session, "draft_preview", None))

    def _draft_preview_from_segments(self, segments: list[dict]) -> str:
        """Build a short WeChat-style draft preview from composed editor segments."""
        parts: list[str] = []

        for segment in segments or []:
            segment_type = segment.get("type")
            if isinstance(segment_type, str):
                try:
                    segment_type = MessageType(segment_type)
                except ValueError:
                    segment_type = None

            if segment_type == MessageType.TEXT:
                text = " ".join(str(segment.get("content", "") or "").split())
                if text:
                    parts.append(text)
                continue

            if segment_type in {MessageType.IMAGE, MessageType.VIDEO, MessageType.FILE}:
                parts.append(format_message_preview("", segment_type))

        return " ".join(part for part in parts if part).strip()

    def _store_session_view_state(self, session_id: str) -> None:
        """Store the current chat panel state for a session."""
        if session_id != self._current_session_id:
            return
        self._session_view_state[session_id] = {
            "messages": self.chat_panel.get_visible_messages(),
            "scroll_gap": self.chat_panel.get_message_scroll_gap(),
            "oldest_loaded_timestamp": self._oldest_loaded_timestamp,
            "oldest_loaded_session_seq": self._oldest_loaded_session_seq,
            "has_more_history": self._has_more_history,
        }

    def _restore_session_view_state(self, session_id: str, state: dict) -> None:
        """Restore a previously cached visible state for the selected session."""
        messages = list(state.get("messages") or [])
        self.chat_panel.set_messages(messages, scroll_to_bottom=False)
        self._oldest_loaded_timestamp = state.get("oldest_loaded_timestamp")
        self._oldest_loaded_session_seq = state.get("oldest_loaded_session_seq")
        self._has_more_history = bool(state.get("has_more_history", True))
        self.chat_panel.set_has_more_history(self._has_more_history)
        self.chat_panel.set_history_loading(False)
        self.chat_panel.restore_message_scroll_gap(int(state.get("scroll_gap", 0)))
        self._schedule_read_receipt()

    def _on_send_segments(self, segments: list[dict]) -> None:
        """Dispatch mixed text/media segments in document order."""
        session_id = self._current_session_id
        if not session_id or not segments:
            return
        self._store_session_draft_segments(session_id, [])
        self._set_session_draft_preview(session_id, [])
        self._schedule_ui_task(self._send_segments_async(session_id, segments), f"send segments {session_id}")

    async def _send_segments_async(self, session_id: str, segments: list[dict]) -> None:
        """Send composed editor segments sequentially so mixed content keeps order."""
        for segment in segments:
            segment_type = segment.get("type")
            try:
                if segment_type == MessageType.TEXT and segment.get("content"):
                    await self._chat_controller.send_message_to(
                        session_id=session_id,
                        content=segment["content"],
                        message_type=MessageType.TEXT,
                        extra=segment.get("extra"),
                    )
                elif segment_type in {MessageType.IMAGE, MessageType.VIDEO, MessageType.FILE} and segment.get("file_path"):
                    await self._chat_controller.send_file(segment["file_path"], session_id=session_id)
            except Exception as exc:
                logger.error("Send composed segment error: %s", exc)

    async def _send_image_message(self, session_id: str, file_path: str, generation: int) -> None:
        """Send an image using the optimistic media upload flow."""
        try:
            message = await self._chat_controller.send_file(file_path, session_id=session_id)
            if message and self._is_current_session_context(session_id, generation):
                self.chat_panel.get_message_list().viewport().update()
        except Exception as exc:
            logger.error("Send image message error: %s", exc)

    def _on_send_typing(self) -> None:
        """Send typing indicator in background."""
        if self._current_session_id:
            self._schedule_ui_task(self._chat_controller.send_typing(), f"typing {self._current_session_id}")

    def _on_file_upload_requested(self, file_path: str) -> None:
        """Send file message in background."""
        session_id = self._current_session_id
        if not session_id:
            return
        self._schedule_ui_task(self._send_file_message(session_id, file_path), f"send file {session_id}")

    def _on_screenshot_requested(self) -> None:
        """Open the screenshot overlay and send the result as an image."""
        if not self._current_session_id:
            InfoBar.warning(
                tr("common.chat", "Chat"),
                tr("chat.screenshot.select_conversation", "Select a conversation before sending a screenshot."),
                parent=self.window(),
                duration=2000,
            )
            return

        overlay = ScreenshotOverlay(self.window())
        self._screenshot_overlays.add(overlay)
        overlay.captured.connect(lambda file_path, current=overlay: self._handle_screenshot_captured(file_path, current))
        overlay.canceled.connect(lambda current=overlay: self._discard_screenshot_overlay(current))
        overlay.destroyed.connect(lambda *_args, ref=overlay: self._discard_screenshot_overlay(ref))
        overlay.start()

    def _discard_screenshot_overlay(self, overlay: ScreenshotOverlay) -> None:
        self._screenshot_overlays.discard(overlay)

    def _handle_screenshot_captured(self, file_path: str, source_overlay: ScreenshotOverlay) -> None:
        """Preview a captured screenshot before sending it."""
        if source_overlay not in self._screenshot_overlays:
            return
        self._screenshot_overlays.discard(source_overlay)
        for overlay in list(self._screenshot_overlays):
            if not overlay.isVisible():
                self._screenshot_overlays.discard(overlay)
        if not os.path.exists(file_path):
            InfoBar.error(
                tr("chat.screenshot.preview_title", "Preview Screenshot"),
                tr("chat.screenshot.capture_failed", "Unable to open the captured screenshot."),
                parent=self.window(),
                duration=2000,
            )
            return

        dialog = ScreenshotPreviewDialog(file_path, self.window())
        self._screenshot_dialogs.add(dialog)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                if self._current_session_id:
                    generation = self._session_focus_generation
                    self._schedule_ui_task(
                        self._send_image_message(self._current_session_id, file_path, generation),
                        f"send screenshot {self._current_session_id}",
                    )
            else:
                try:
                    os.remove(file_path)
                except OSError:
                    logger.debug("Failed to remove canceled screenshot preview: %s", file_path, exc_info=True)
        finally:
            self._screenshot_dialogs.discard(dialog)

    def _on_voice_call_requested(self) -> None:
        """Start one voice call for the selected direct session."""
        self._schedule_ui_task(
            self._start_current_session_call(CallMediaType.VOICE.value),
            "start voice call",
        )

    def _on_video_call_requested(self) -> None:
        """Start one video call for the selected direct session."""
        self._schedule_ui_task(
            self._start_current_session_call(CallMediaType.VIDEO.value),
            "start video call",
        )

    async def _start_current_session_call(self, media_type: str) -> None:
        """Validate the selected session and send one outbound call invite."""
        session = self._get_session(self._current_session_id or "")
        if session is None:
            InfoBar.warning(
                tr("chat.call.invalid.title", "Call"),
                tr("chat.call.invalid.session", "Open one direct chat before starting a call."),
                parent=self.window(),
                duration=2200,
            )
            return

        active_call = self._chat_controller.get_active_call()
        if active_call is not None and active_call.session_id == session.session_id:
            await self._chat_controller.hangup_call(active_call.call_id)
            return

        try:
            await self._chat_controller.start_call(session, media_type)
        except AppError as exc:
            InfoBar.warning(
                tr("chat.call.start_failed.title", "Call"),
                str(exc),
                parent=self.window(),
                duration=2400,
            )

    def _on_call_invite_sent(self, event: object) -> None:
        """Show local feedback for one outbound invite."""
        call = self._event_call(event)
        if call is None:
            return
        logger.info("[call-ui] call_id=%s stage=invite_sent_ui status=%s direction=%s", call.call_id, call.status, call.direction)
        window = self._ensure_call_window(call)
        if window is not None:
            window.set_status_text("Waiting...")
            current_user_id = str((self._auth_controller.current_user or {}).get("id", "") or "")
            window.prepare_media(is_caller=current_user_id == call.initiator_id)
            window.activate_signaling()
        self._start_call_ring_sound(AppSound.CALL_OUTGOING_RING)
        call_label = self._call_label(call.media_type)
        InfoBar.success(
            call_label,
            tr("chat.call.invite_sent", "Calling the other participant..."),
            parent=self.window(),
            duration=1800,
        )

    def _on_call_invite_received(self, event: object) -> None:
        """Display one incoming call toast and notify the caller that it is ringing."""
        call = self._event_call(event)
        if call is None:
            return
        if call.direction != "incoming":
            return
        if call.call_id in self._incoming_call_toasts:
            return
        logger.info("[call-ui] call_id=%s stage=invite_received_ui status=%s direction=%s", call.call_id, call.status, call.direction)

        self._schedule_ui_single_shot(
            0,
            lambda cid=call.call_id: self._schedule_ui_task(
                self._chat_controller.send_call_ringing(cid),
                f"call ringing {cid}",
            ),
        )

        session = self._get_session(call.session_id)
        current_user_id = self._current_user_id()
        peer_user_id = call.peer_user_id(current_user_id)
        peer_name = self._call_session_name(call)
        peer_avatar = str(session.display_avatar() if session is not None else "")
        peer_avatar_seed = (
            str(session.display_avatar_seed() if session is not None else "")
            or profile_avatar_seed(
                user_id=peer_user_id,
                username=str(getattr(session, "extra", {}).get("counterpart_username", "") or "") if session is not None else "",
                display_name=peer_name,
                fallback=peer_name,
            )
        )
        toast = IncomingCallToast(
            peer_name=peer_name,
            subtitle=tr(
                "chat.call.incoming.content",
                "{name} is inviting you to a {kind} call.",
                name=peer_name,
                kind=self._call_kind_label(call.media_type),
            ),
            avatar=peer_avatar,
            avatar_seed=peer_avatar_seed,
            parent=self.window(),
        )
        self._incoming_call_toasts[call.call_id] = toast
        self._dialog_refs.add(toast)
        toast.destroyed.connect(lambda *_args, cid=call.call_id, ref=toast: self._on_call_toast_destroyed(cid, ref))
        toast.accepted.connect(lambda active_call=call, ref=toast: self._accept_incoming_call_from_toast(active_call, ref))
        toast.rejected.connect(lambda cid=call.call_id, ref=toast: self._reject_incoming_call_from_toast(cid, ref))
        toast.show()
        self._start_call_ring_sound(AppSound.CALL_INCOMING_RING)
        self._schedule_ui_single_shot(
            0,
            lambda active_call=call: self._schedule_ui_task(
                self._prepare_incoming_call_window(active_call),
                f"prepare incoming call window {active_call.call_id}",
            ),
        )

    async def _prepare_incoming_call_window(self, call: ActiveCallState) -> None:
        """Refresh runtime ICE config before prewarming one incoming call window."""
        await self._chat_controller.refresh_call_ice_servers(force_refresh=True)
        window = self._ensure_call_window(call, reveal=False)
        if window is not None:
            self._schedule_ui_single_shot(
                0,
                lambda current_window=window: self._prepare_current_call_window_media(current_window),
            )

    async def _accept_incoming_call(self, call: ActiveCallState) -> None:
        """Accept one incoming call and optionally switch to the related chat."""
        accepted = await self._chat_controller.accept_call(call.call_id)
        if accepted and call.session_id and call.session_id != self._current_session_id:
            await self.open_session(call.session_id)

    def _accept_incoming_call_from_toast(self, call: ActiveCallState, source_toast: IncomingCallToast) -> None:
        """Close the toast immediately and schedule accept handling."""
        if self._incoming_call_toasts.get(call.call_id) is not source_toast:
            return
        self._close_incoming_call_toast(call.call_id)
        self._schedule_ui_single_shot(
            0,
            lambda active_call=call: self._schedule_ui_task(
                self._accept_incoming_call(active_call),
                f"accept incoming call {active_call.call_id}",
            ),
        )

    def _reject_incoming_call_from_toast(self, call_id: str, source_toast: IncomingCallToast) -> None:
        """Close the toast immediately and schedule reject handling."""
        if self._incoming_call_toasts.get(call_id) is not source_toast:
            return
        self._close_incoming_call_toast(call_id)
        self._schedule_ui_single_shot(
            0,
            lambda cid=call_id: self._schedule_ui_task(
                self._chat_controller.reject_call(cid),
                f"reject incoming call {cid}",
            ),
        )

    def _on_call_ringing(self, event: object) -> None:
        """Show when the remote side is being alerted."""
        call = self._event_call(event)
        if call is None or call.direction != "outgoing":
            return
        logger.info("[call-ui] call_id=%s stage=ringing_ui status=%s direction=%s", call.call_id, call.status, call.direction)
        window = self._ensure_call_window(call)
        if window is not None:
            window.set_status_text("Ringing...")
            window.activate_signaling()
        InfoBar.info(
            self._call_label(call.media_type),
            tr("chat.call.ringing", "The other participant is being alerted."),
            parent=self.window(),
            duration=1800,
        )

    def _on_call_accepted(self, event: object) -> None:
        """Show accepted state for the current call."""
        call = self._event_call(event)
        if call is None:
            return
        logger.info("[call-ui] call_id=%s stage=accepted_ui status=%s direction=%s", call.call_id, call.status, call.direction)
        self._close_incoming_call_toast(call.call_id)
        self._ensure_call_window(call, start_media=True)
        self._stop_call_ring_sounds()
        self._play_call_sound(AppSound.CALL_CONNECTED)
        InfoBar.success(
            self._call_label(call.media_type),
            tr("chat.call.accepted", "Call accepted. Connecting media..."),
            parent=self.window(),
            duration=2200,
        )

    def _on_call_rejected(self, event: object) -> None:
        """Show rejection state and close any prompt."""
        call = self._event_call(event)
        if call is None:
            return
        self._close_incoming_call_toast(call.call_id)
        self._close_call_window(call.call_id)
        self._play_call_terminal_sound()
        self._schedule_call_result_message(call, outcome="rejected")
        InfoBar.warning(
            self._call_label(call.media_type),
            tr("chat.call.rejected", "The call was rejected."),
            parent=self.window(),
            duration=2200,
        )

    def _on_call_ended(self, event: object) -> None:
        """Show hangup state and close any prompt."""
        call = self._event_call(event)
        if call is None:
            return
        self._close_incoming_call_toast(call.call_id)
        self._close_call_window(call.call_id)
        self._play_call_terminal_sound()
        self._schedule_call_result_message(call, outcome=self._call_end_outcome(call))
        InfoBar.info(
            self._call_label(call.media_type),
            self._call_end_infobar_text(call),
            parent=self.window(),
            duration=1800,
        )

    def _on_call_busy(self, event: object) -> None:
        """Show busy state for one outbound invite."""
        call = self._event_call(event)
        if call is None:
            return
        self._close_incoming_call_toast(call.call_id)
        self._close_call_window(call.call_id)
        self._play_call_terminal_sound()
        self._schedule_call_result_message(call, outcome="busy")
        InfoBar.warning(
            self._call_label(call.media_type),
            tr("chat.call.busy", "The other participant is already in another call."),
            parent=self.window(),
            duration=2200,
        )

    def _on_call_failed(self, event: object) -> None:
        """Show signaling failures tied to the active call."""
        call = self._event_call(event)
        if call is None:
            return
        self._close_incoming_call_toast(call.call_id)
        self._close_call_window(call.call_id)
        self._play_call_terminal_sound()
        self._schedule_call_result_message(call, outcome="failed")
        message = call.reason or tr("chat.call.failed", "Call signaling failed.")
        InfoBar.error(
            self._call_label(call.media_type),
            message,
            parent=self.window(),
            duration=2600,
        )

    def _on_call_signal(self, event: object) -> None:
        """Route WebRTC SDP/ICE payloads into the active call window."""
        if not isinstance(event, dict):
            return
        message_type = str(event.get("type") or "")
        payload = event.get("data") or {}
        if not isinstance(payload, dict):
            return
        call_id = str(payload.get("call_id") or "")
        if not call_id:
            return

        window = self._call_window
        if window is None or window.call_id != call_id:
            active_call = self._chat_controller.get_active_call()
            if active_call is None or active_call.call_id != call_id:
                return
            window = self._ensure_call_window(active_call, start_media=False)
        if window is None:
            return

        if message_type == "call_offer":
            window.handle_offer(payload)
        elif message_type == "call_answer":
            window.handle_answer(payload)
        elif message_type == "call_ice":
            window.handle_ice_candidate(payload)

    def _on_call_toast_destroyed(self, call_id: str, toast: IncomingCallToast) -> None:
        """Drop one tracked incoming-call toast reference."""
        self._dialog_refs.discard(toast)
        if self._incoming_call_toasts.get(call_id) is toast:
            self._incoming_call_toasts.pop(call_id, None)

    def _close_incoming_call_toast(self, call_id: str) -> None:
        """Close one tracked incoming-call toast when the call state resolves."""
        toast = self._incoming_call_toasts.pop(call_id, None)
        if toast is None:
            return
        self._dialog_refs.discard(toast)
        toast.close()

    def _ensure_call_window(
        self,
        call: ActiveCallState,
        *,
        start_media: bool = False,
        reveal: bool = True,
    ) -> CallWindow | None:
        """Create or reuse the active media window for one accepted call."""
        if self._call_window is not None and self._call_window.call_id == call.call_id:
            self._call_window.sync_call_state(call)
            if reveal and not self._call_window.isVisible():
                self._call_window.show()
                self._call_window.raise_()
                self._call_window.activateWindow()
            if start_media:
                current_user_id = str((self._auth_controller.current_user or {}).get("id", "") or "")
                self._call_window.start_media(is_caller=current_user_id == call.initiator_id)
            return self._call_window

        self._close_call_window()
        current_user_id = str((self._auth_controller.current_user or {}).get("id", "") or "")
        current_user = dict(self._auth_controller.current_user or {})
        session_name = self._call_session_name(call)
        peer_label = session_name
        session = self._get_session(call.session_id)
        self_label = str(
            current_user.get("nickname", "")
            or current_user.get("display_name", "")
            or current_user.get("username", "")
            or "Me"
        )

        window = CallWindow(
            call,
            session_title=session_name,
            peer_label=peer_label,
            avatar=str(session.display_avatar() if session is not None else ""),
            avatar_seed=str(session.display_avatar_seed() if session is not None else ""),
            self_avatar=str(current_user.get("avatar", "") or ""),
            self_avatar_seed=profile_avatar_seed(
                user_id=current_user.get("id", ""),
                username=current_user.get("username", ""),
                display_name=self_label,
                fallback=self_label,
            ),
            self_label=self_label,
            ice_servers=self._chat_controller.get_call_ice_servers(),
            parent=None,
        )
        window.hangup_requested.connect(lambda call_id, ref=window: self._on_call_window_hangup_requested(call_id, ref))
        window.signal_generated.connect(
            lambda event_type, payload, ref=window: self._on_call_window_signal_generated(event_type, payload, ref)
        )
        window.destroyed.connect(lambda *_args, ref=window: self._on_call_window_destroyed(ref))
        if reveal:
            window.show()
            window.raise_()
            window.activateWindow()
        window.sync_call_state(call)
        if start_media:
            window.start_media(is_caller=current_user_id == call.initiator_id)
        self._call_window = window
        return window

    def _prepare_current_call_window_media(self, window: CallWindow) -> None:
        """Prepare media only for the call window that is still active."""
        if self._call_window is not window:
            return
        window.prepare_media(is_caller=False)

    def _close_call_window(self, call_id: str | None = None) -> None:
        """Close the active media window when the call finishes."""
        window = self._call_window
        if window is None:
            return
        if call_id and window.call_id != call_id:
            return
        self._call_window = None
        self._stop_call_ring_sounds()
        window.end_call()

    def _on_call_window_destroyed(self, window: CallWindow) -> None:
        """Clear the active call window reference once the widget is gone."""
        if self._call_window is window:
            self._call_window = None

    def _on_call_window_hangup_requested(self, call_id: str, source_window: CallWindow) -> None:
        """Relay user-triggered window close actions into websocket hangup."""
        if self._call_window is not source_window:
            return
        self._schedule_ui_task(
            self._chat_controller.hangup_call(call_id),
            f"hangup call window {call_id}",
        )

    def _on_call_window_signal_generated(self, event_type: str, payload: object, source_window: CallWindow) -> None:
        """Forward JS-generated SDP and ICE payloads through the chat controller."""
        if self._call_window is not source_window:
            return
        if not isinstance(payload, dict):
            return
        call_id = str(payload.get("call_id") or "")
        if not call_id:
            return
        if event_type == "call_offer":
            self._schedule_ui_task(
                self._chat_controller.send_call_offer(call_id, payload.get("sdp", {}) if isinstance(payload.get("sdp"), dict) else {}),
                f"send call offer {call_id}",
            )
        elif event_type == "call_answer":
            self._schedule_ui_task(
                self._chat_controller.send_call_answer(call_id, payload.get("sdp", {}) if isinstance(payload.get("sdp"), dict) else {}),
                f"send call answer {call_id}",
            )
        elif event_type == "call_ice":
            self._schedule_ui_task(
                self._chat_controller.send_call_ice_candidate(
                    call_id,
                    payload.get("candidate", {}) if isinstance(payload.get("candidate"), dict) else {},
                ),
                f"send call ice {call_id}",
            )

    @staticmethod
    def _event_call(event: object) -> ActiveCallState | None:
        """Extract one call state object from an event-bus payload."""
        if not isinstance(event, dict):
            return None
        call = event.get("call")
        if isinstance(call, ActiveCallState):
            return call
        return None

    def _call_session_name(self, call: ActiveCallState) -> str:
        """Resolve one readable name for the current call target."""
        session = self._get_session(call.session_id)
        if session is not None:
            return session.name or tr("session.unnamed", "Untitled Session")
        peer_user_id = call.peer_user_id(str((self._auth_controller.current_user or {}).get("id", "") or ""))
        return peer_user_id or tr("session.unnamed", "Untitled Session")

    @staticmethod
    def _call_kind_label(media_type: str) -> str:
        """Return one readable media type label."""
        return "video" if media_type == CallMediaType.VIDEO.value else "voice"

    def _call_label(self, media_type: str) -> str:
        """Return one title string for InfoBar feedback."""
        if media_type == CallMediaType.VIDEO.value:
            return tr("chat.video_call.title", "Video Call")
        return tr("chat.voice_call.title", "Voice Call")

    def _current_user_id(self) -> str:
        return str((self._auth_controller.current_user or {}).get("id", "") or "")

    def _play_call_sound(self, sound_id: AppSound) -> None:
        sound_manager = get_sound_manager()
        sound_manager.play(sound_id, force=True)

    def _stop_call_sound(self, sound_id: AppSound) -> None:
        sound_manager = get_sound_manager()
        sound_manager.stop(sound_id)

    def _stop_call_ring_sounds(self) -> None:
        self._call_ring_timer.stop()
        self._active_call_ring_sound = None
        self._stop_call_sound(AppSound.CALL_OUTGOING_RING)
        self._stop_call_sound(AppSound.CALL_INCOMING_RING)

    def _play_call_terminal_sound(self) -> None:
        self._stop_call_ring_sounds()
        self._play_call_sound(AppSound.CALL_ENDED)

    def _start_call_ring_sound(self, sound_id: AppSound) -> None:
        if self._active_call_ring_sound == sound_id and self._call_ring_timer.isActive():
            return
        self._stop_call_ring_sounds()
        self._active_call_ring_sound = sound_id
        if sound_id == AppSound.CALL_INCOMING_RING:
            sound_manager = get_sound_manager()
            sound_manager.ensure_playing(sound_id)
            self._schedule_ui_single_shot(self.CALL_INCOMING_RING_RETRY_MS, self._retry_incoming_ring_sound)
            return
        self._play_call_sound(sound_id)
        self._call_ring_timer.start(self.CALL_RING_REPEAT_MS)

    def _on_call_ring_timer(self) -> None:
        if self._active_call_ring_sound is None:
            self._call_ring_timer.stop()
            return
        self._play_call_sound(self._active_call_ring_sound)

    def _retry_incoming_ring_sound(self) -> None:
        """Retry one incoming ring shortly after the first play to mask backend warmup misses."""
        if self._active_call_ring_sound != AppSound.CALL_INCOMING_RING:
            return
        if not self._incoming_call_toasts:
            return
        sound_manager = get_sound_manager()
        sound_manager.ensure_playing(AppSound.CALL_INCOMING_RING)

    def _call_end_outcome(self, call: ActiveCallState) -> str:
        if call.reason == "timeout":
            return "timeout"
        if call.answered_at is not None:
            return "completed"
        if call.actor_id and call.actor_id == call.initiator_id:
            return "cancelled"
        return "failed"

    def _call_end_infobar_text(self, call: ActiveCallState) -> str:
        if call.reason == "timeout":
            return "The call timed out."
        if call.answered_at is not None:
            return tr("chat.call.ended", "The call ended.")
        if call.actor_id and call.actor_id == call.initiator_id:
            return "The call was canceled."
        return tr("chat.call.ended", "The call ended.")

    def _schedule_call_result_message(self, call: ActiveCallState, *, outcome: str) -> None:
        if call.direction != "outgoing":
            return
        if call.initiator_id and call.initiator_id != self._current_user_id():
            return
        dedupe_key = (call.call_id, outcome)
        if dedupe_key in self._call_result_messages_sent:
            return
        self._call_result_messages_sent.add(dedupe_key)
        self._schedule_ui_task(
            self._send_call_result_message(call, outcome=outcome),
            f"call result message {call.call_id} {outcome}",
        )

    async def _send_call_result_message(self, call: ActiveCallState, *, outcome: str) -> None:
        duration_seconds = self._call_duration_seconds(call) if outcome == "completed" else 0
        content = self._call_result_text(call.media_type, outcome=outcome, duration_seconds=duration_seconds)
        extra = {
            "system_kind": "call",
            "call_id": call.call_id,
            "call_media_type": call.media_type,
            "call_outcome": outcome,
            "call_duration_seconds": duration_seconds,
        }
        await self._chat_controller.send_message_to(
            call.session_id,
            content,
            message_type=MessageType.TEXT,
            extra=extra,
        )

    def _call_duration_seconds(self, call: ActiveCallState) -> int:
        answered_at = coerce_local_datetime(call.answered_at)
        if answered_at is None:
            return 0
        return max(0, int((datetime.now() - answered_at).total_seconds()))

    def _call_result_text(self, media_type: str, *, outcome: str, duration_seconds: int) -> str:
        call_label = "视频通话" if media_type == CallMediaType.VIDEO.value else "语音通话"
        if outcome == "completed":
            return f"{call_label} {self._format_call_duration(duration_seconds)}"
        if outcome == "rejected":
            return "对方已拒绝"
        if outcome == "cancelled":
            return "已取消"
        if outcome == "timeout":
            return "无人接听"
        if outcome == "busy":
            return "对方忙线中"
        return "通话失败"

    @staticmethod
    def _format_call_duration(duration_seconds: int) -> str:
        total_seconds = max(0, int(duration_seconds))
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _on_chat_history_requested(self) -> None:
        """Show placeholder feedback for the reserved chat-history entry point."""
        InfoBar.info(
            tr("chat.info.history.title", "Chat History"),
            tr("chat.info.history.unavailable", "The chat history entry is reserved and will be connected next."),
            parent=self.window(),
            duration=1800,
        )

    def _on_chat_info_add_requested(self) -> None:
        """Open the contact selector used to turn the current private chat into a new group."""
        session = self._get_session(self._current_session_id or "")
        if session is None or session.is_ai_session or session.session_type != "direct":
            return

        self._schedule_ui_task(
            self._group_flow.show_start_group_dialog(session),
            f"start group chat selector {session.session_id}",
        )

    def _on_chat_info_search_requested(self) -> None:
        """Keep the reserved chat-search entry visible until the real flow lands."""
        InfoBar.info(
            tr("chat.info.search.title", "Find Chat Content"),
            tr("chat.info.search.unavailable", "The in-chat search feature will be connected next."),
            parent=self.window(),
            duration=1800,
        )

    def _on_chat_info_clear_requested(self) -> None:
        """Keep the clear-history entry visible until durable sync-safe deletion is implemented."""
        InfoBar.info(
            tr("chat.info.clear.title", "Clear Chat History"),
            tr("chat.info.clear.unavailable", "The clear-history entry is reserved. Durable sync-safe clearing will be connected next."),
            parent=self.window(),
            duration=1800,
        )

    def _on_chat_info_show_nickname_toggled(self, _enabled: bool) -> None:
        """Persist the local group-member label visibility preference for the active session."""
        session_id = self._current_session_id
        if not session_id:
            return
        self._schedule_ui_task(
            self._session_controller.set_group_member_nickname_visibility(session_id, _enabled),
            f"set group member nickname visibility {session_id}",
        )

    def _show_dialog(self, dialog: QDialog) -> None:
        """Keep non-modal dialogs alive while visible."""
        self._dialog_refs.add(dialog)
        dialog.destroyed.connect(lambda *_args, dlg=dialog: self._dialog_refs.discard(dlg))
        dialog.finished.connect(dialog.deleteLater)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_chat_info_member_management_requested(self, payload: object) -> None:
        """Open the formal group-member management dialog from chat info entry points."""
        if not isinstance(payload, GroupMemberManagementRequest):
            return

        dialog = GroupMemberManagementDialog(
            self._contact_controller,
            group_id=payload.group_id,
            session_id=payload.session_id,
            preferred_mode=payload.mode,
            parent=self.window(),
        )
        dialog.groupRecordChanged.connect(
            lambda record, session_id=payload.session_id: self._schedule_ui_task(
                self._apply_group_management_record(session_id, record),
                f"apply group management record {session_id}",
            )
        )
        self._show_dialog(dialog)

    def _on_chat_info_leave_requested(self) -> None:
        """Confirm and leave the currently opened group chat."""
        session = self._session_controller.get_current_session()
        if session is None or getattr(session, "session_type", "") != "group":
            return

        group_id = session.authoritative_group_id()
        if not group_id:
            return

        dialog = LeaveGroupConfirmDialog(session.chat_title() or session.display_name(), self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._schedule_ui_task(
            self._leave_group_async(session.session_id, group_id, session.chat_title() or session.display_name()),
            f"leave group {session.session_id}",
        )

    def _on_chat_info_mute_toggled(self, muted: bool) -> None:
        """Route local do-not-disturb changes through the session controller only."""
        session_id = self._current_session_id
        if not session_id:
            return

        self._schedule_ui_task(
            self._session_controller.set_muted(session_id, muted),
            f"mute session {session_id}",
        )

    def _on_chat_info_pin_toggled(self, pinned: bool) -> None:
        """Route pin changes through the session controller only."""
        session_id = self._current_session_id
        if not session_id:
            return

        self._schedule_ui_task(
            self._session_controller.set_pinned(session_id, pinned),
            f"pin session {session_id}",
        )

    def _on_chat_info_group_profile_update_requested(self, payload: object) -> None:
        if not isinstance(payload, GroupProfileUpdateRequest):
            return
        self._schedule_ui_task(
            self._update_group_profile_async(payload),
            f"update group profile {payload.session_id}",
        )

    def _on_group_announcement_requested(self) -> None:
        session = self._get_session(self._current_session_id or "") if self._current_session_id else None
        if session is None or not session.group_announcement_text():
            return

        dialog = GroupAnnouncementDialog(
            session,
            current_user=dict(self._auth_controller.current_user or {}),
            parent=self.window(),
        )
        self._dialog_refs.add(dialog)
        dialog.finished.connect(lambda _code, ref=dialog: self._dialog_refs.discard(ref))
        viewed_message_id = session.group_announcement_message_id()
        result = dialog.exec()
        if viewed_message_id:
            self._schedule_ui_task(
                self._session_controller.mark_group_announcement_viewed(session.session_id, viewed_message_id),
                f"view group announcement {session.session_id}",
            )
        if result != QDialog.DialogCode.Accepted:
            return
        updated_announcement = dialog.pending_announcement()
        if updated_announcement is None:
            return
        self._schedule_ui_task(
            self._update_group_profile_async(
                GroupProfileUpdateRequest(
                    session_id=session.session_id,
                    group_id=session.authoritative_group_id(),
                    name=None,
                    announcement=updated_announcement,
                ),
                mark_announcement_viewed=True,
            ),
            f"update group announcement {session.session_id}",
        )

    def _on_chat_info_group_self_profile_update_requested(self, payload: object) -> None:
        if not isinstance(payload, GroupSelfProfileUpdateRequest):
            return
        self._schedule_ui_task(
            self._update_my_group_profile_async(payload),
            f"update my group profile {payload.session_id}",
        )

    async def _update_group_profile_async(self, request: GroupProfileUpdateRequest, *, mark_announcement_viewed: bool = False) -> None:
        try:
            record = await self._contact_controller.update_group_profile(
                request.group_id,
                name=request.name,
                announcement=request.announcement,
            )
        except Exception as exc:
            if self._current_session_id == request.session_id:
                self.chat_panel.refresh_chat_info_content()
            InfoBar.error(
                tr("chat.info.group.title", "Group Chat Info"),
                str(exc),
                parent=self.window(),
                duration=2400,
            )
            return
        updated_session = await self._apply_group_record(request.session_id, record, include_self_fields=True)
        if mark_announcement_viewed and updated_session is not None:
            announcement_message_id = updated_session.group_announcement_message_id()
            if announcement_message_id:
                await self._session_controller.mark_group_announcement_viewed(
                    updated_session.session_id,
                    announcement_message_id,
                )

    async def _update_my_group_profile_async(self, request: GroupSelfProfileUpdateRequest) -> None:
        try:
            record = await self._contact_controller.update_my_group_profile(
                request.group_id,
                note=request.note,
                my_group_nickname=request.my_group_nickname,
            )
        except Exception as exc:
            if self._current_session_id == request.session_id:
                self.chat_panel.refresh_chat_info_content()
            InfoBar.error(
                tr("chat.info.group.title", "Group Chat Info"),
                str(exc),
                parent=self.window(),
                duration=2400,
            )
            return
        await self._apply_group_record(request.session_id, record, include_self_fields=True)

    async def _apply_group_record(self, session_id: str, record, *, include_self_fields: bool):
        payload = self._group_record_payload(record)
        return await self._session_controller.apply_group_payload(
            session_id,
            payload,
            include_self_fields=include_self_fields,
        )

    @staticmethod
    def _group_record_payload(record) -> dict[str, object]:
        """Serialize one group record back into the session/contact update shape."""
        payload = dict(getattr(record, "extra", {}) or {})
        record_id = str(getattr(record, "id", "") or payload.get("id", "") or "")
        payload["id"] = record_id
        payload["group_id"] = str(payload.get("group_id", "") or record_id or "")

        def set_if_present(key: str, value: object) -> None:
            if key in payload or value not in (None, "", 0):
                payload[key] = value

        set_if_present("name", str(getattr(record, "name", "") or payload.get("name", "") or ""))
        set_if_present("announcement", str(getattr(record, "announcement", "") or payload.get("announcement", "") or ""))
        set_if_present("avatar", str(getattr(record, "avatar", "") or payload.get("avatar", "") or ""))
        set_if_present("owner_id", str(getattr(record, "owner_id", "") or payload.get("owner_id", "") or ""))
        set_if_present("session_id", str(getattr(record, "session_id", "") or payload.get("session_id", "") or ""))
        set_if_present("member_count", int(getattr(record, "member_count", 0) or payload.get("member_count", 0) or 0))
        set_if_present(
            "announcement_message_id",
            str(getattr(record, "announcement_message_id", "") or payload.get("announcement_message_id", "") or ""),
        )
        set_if_present(
            "announcement_author_id",
            str(getattr(record, "announcement_author_id", "") or payload.get("announcement_author_id", "") or ""),
        )
        raw_published_at = getattr(record, "announcement_published_at", None) or payload.get("announcement_published_at")
        if hasattr(raw_published_at, "isoformat"):
            set_if_present("announcement_published_at", raw_published_at.isoformat())
        else:
            set_if_present("announcement_published_at", str(raw_published_at or ""))
        return payload

    async def _apply_group_management_record(self, session_id: str, record) -> None:
        """Mirror member-management mutations into the open session and contact page."""
        if not session_id:
            return

        await self._apply_group_record(session_id, record, include_self_fields=True)

        payload = self._group_record_payload(record)
        payload.setdefault("session_id", session_id)
        await self._event_bus.emit(
            ContactEvent.SYNC_REQUIRED,
            {"reason": "group_profile_update", "payload": {"group": payload}},
        )

    async def _leave_group_async(self, session_id: str, group_id: str, group_name: str) -> None:
        try:
            await self._contact_controller.leave_group(group_id)
            await self._session_controller.remove_session(session_id)
            await self._event_bus.emit(ContactEvent.SYNC_REQUIRED, {"reason": "group_membership_changed"})
        except Exception as exc:
            InfoBar.error(
                tr("chat.info.group.leave.title", "Leave Group Chat"),
                str(exc),
                parent=self.window(),
                duration=2400,
            )
            return

        InfoBar.success(
            tr("chat.info.group.leave.title", "Leave Group Chat"),
            tr(
                "chat.info.group.leave.success",
                "You left {name}.",
                name=group_name or tr("session.unnamed", "Untitled Session"),
            ),
            parent=self.window(),
            duration=2000,
        )

    def close_transient_panels(self) -> None:
        """Close floating transient UI owned by the chat page."""
        self.chat_panel.close_chat_info_drawer(immediate=True)

    async def _send_file_message(self, session_id: str, file_path: str) -> None:
        """Upload and send a file via ChatController."""
        try:
            await self._chat_controller.send_file(file_path, session_id=session_id)
        except Exception as exc:
            logger.error("Send file message error: %s", exc)

    def _on_message_context_menu(self, position) -> None:
        """Show message actions for the clicked bubble."""
        message = self.chat_panel.get_message_at(position, bubble_only=True)
        if not message:
            return

        if self._message_context_menu is not None:
            self._message_context_menu.close()
            self._message_context_menu.deleteLater()
            self._message_context_menu = None

        menu = RoundMenu(parent=self)
        copy_action = None
        open_action = None
        translate_action = None
        quote_action = None
        multiselect_action = None
        recall_action = None
        delete_action = None
        retry_action = None

        basic_actions: list[Action] = []
        placeholder_actions: list[Action] = []
        message_actions: list[Action] = []
        retry_actions: list[Action] = []

        if message.message_type == MessageType.TEXT and message.content:
            copy_action = Action(tr("chat.context.copy", "Copy"), self)
            basic_actions.append(copy_action)

        if message.message_type == MessageType.IMAGE:
            open_action = Action(tr("chat.context.open_image", "View Image"), self)
            basic_actions.append(open_action)
        elif message.message_type in {MessageType.FILE, MessageType.VIDEO}:
            open_action = Action(tr("chat.context.open_attachment", "Open"), self)
            basic_actions.append(open_action)

        if message.message_type == MessageType.TEXT:
            translate_action = Action(tr("chat.context.translate", "Translate"), self)
            translate_action.setEnabled(False)
            placeholder_actions.append(translate_action)

        quote_action = Action(tr("chat.context.quote", "Quote"), self)
        quote_action.setEnabled(False)
        placeholder_actions.append(quote_action)

        multiselect_action = Action(tr("chat.context.multi_select", "Multi-select"), self)
        multiselect_action.setEnabled(False)
        placeholder_actions.append(multiselect_action)

        if should_offer_recall(message):
            recall_action = Action(tr("chat.context.recall", "Recall"), self)
            message_actions.append(recall_action)
        elif should_offer_delete(message):
            delete_action = Action(tr("common.delete", "Delete"), self)
            message_actions.append(delete_action)

        if message.is_self and message.status == MessageStatus.FAILED:
            retry_action = Action(tr("chat.context.retry", "Retry"), self)
            retry_actions.append(retry_action)

        for actions in (basic_actions, placeholder_actions, message_actions, retry_actions):
            if not actions:
                continue
            if menu.actions():
                menu.addSeparator()
            for action in actions:
                menu.addAction(action)

        if copy_action:
            copy_action.triggered.connect(
                lambda _checked=False, msg=message: QGuiApplication.clipboard().setText(
                    self.chat_panel.get_selected_text(msg) or (msg.content or "")
                )
            )
        if open_action:
            open_action.triggered.connect(
                lambda _checked=False, msg=message, current=self._session_focus_generation: self._schedule_ui_single_shot(
                    0,
                    lambda: self._open_message(msg, current),
                )
            )
        if recall_action:
            recall_action.triggered.connect(
                lambda _checked=False, msg=message, current=self._session_focus_generation: self._schedule_ui_task(
                    self._recall_message(msg.message_id, self._message_session_id(msg), current),
                    f"recall {msg.message_id}",
                )
            )
        if delete_action:
            delete_action.triggered.connect(
                lambda _checked=False, msg=message, current=self._session_focus_generation: self._schedule_ui_single_shot(
                    0,
                    lambda: self._confirm_delete_message(msg, current),
                )
            )
        if retry_action:
            retry_action.triggered.connect(
                lambda _checked=False, msg=message, current=self._session_focus_generation: self._schedule_ui_task(
                    self._retry_message(msg.message_id, self._message_session_id(msg), current),
                    f"retry {msg.message_id}",
                )
            )

        if delete_action:
            delete_item = delete_action.property("item")
            if delete_item is not None:
                delete_item.setForeground(QColor("#d13438"))

        if message.message_type == MessageType.TEXT:
            self.chat_panel.set_context_menu_message(message.message_id)

        def _on_menu_hidden() -> None:
            if self._message_context_menu is not menu:
                return
            self._message_context_menu = None
            self.chat_panel.clear_context_menu_message()
            menu.deleteLater()

        menu.closedSignal.connect(_on_menu_hidden)
        self._message_context_menu = menu
        menu.exec(
            self.chat_panel.get_message_list().viewport().mapToGlobal(position),
            ani=True,
            aniType=MenuAnimationType.DROP_DOWN,
        )

    def _open_message(self, message, generation: int | None = None) -> None:
        """Open an image, file, or video attachment."""
        current_generation = self._session_focus_generation if generation is None else generation
        if not self._is_current_message_context(message, current_generation):
            return

        attachment_encryption = dict((message.extra or {}).get("attachment_encryption") or {})
        if attachment_encryption.get("enabled") and message.message_type in {
            MessageType.IMAGE,
            MessageType.VIDEO,
            MessageType.FILE,
        }:
            self._schedule_ui_task(
                self._open_file_attachment(message, current_generation),
                f"open attachment {message.message_id}",
            )
            return

        if message.message_type == MessageType.IMAGE:
            from client.ui.widgets.image_viewer import ImageViewer

            viewer = ImageViewer(message.extra.get("local_path") or message.content, self)
            viewer.exec()
            return

        if message.message_type == MessageType.VIDEO:
            if not self.chat_panel.open_video_message(message):
                InfoBar.warning(
                    tr("chat.message.title", "Message"),
                    tr("chat.attachment.video_open_failed", "Unable to play this video."),
                    parent=self.window(),
                    duration=1800,
                )
            return

        if message.message_type == MessageType.FILE:
            self._schedule_ui_task(
                self._open_file_attachment(message, current_generation),
                f"open attachment {message.message_id}",
            )

    async def _open_file_attachment(self, message, generation: int) -> None:
        """Download one file attachment when needed, then open the local file."""
        try:
            local_path = await self._chat_controller.download_message_attachment(message.message_id)
        except Exception as exc:
            if not self._is_current_message_context(message, generation):
                return
            InfoBar.warning(
                tr("chat.message.title", "Message"),
                str(exc) or tr("chat.attachment.file_open_failed", "Unable to open this attachment."),
                parent=self.window(),
                duration=1800,
            )
            return

        if not self._is_current_message_context(message, generation):
            return
        if local_path:
            message.extra["local_path"] = local_path

        if not self.chat_panel.open_local_attachment(local_path, message.message_type):
            InfoBar.warning(
                tr("chat.message.title", "Message"),
                tr("chat.attachment.file_open_failed", "Unable to open this attachment."),
                parent=self.window(),
                duration=1800,
            )

    async def _retry_message(self, message_id: str, session_id: str, generation: int) -> None:
        """Retry a failed message."""
        success = await self._chat_controller.retry_message(message_id)
        if not self._is_current_session_context(session_id, generation):
            return
        if not success:
            InfoBar.error(
                tr("chat.message.title", "Message"),
                tr("chat.retry_failed", "Retry failed."),
                parent=self.window(),
                duration=1800,
            )

    def _on_security_pending_confirm_requested(self, session_id: str, action_id: str) -> None:
        """Confirm one queued security action, then send the held local messages."""
        generation = self._session_focus_generation
        if not self._is_current_session_context(session_id, generation):
            return
        self._schedule_ui_task(
            self._confirm_security_pending_messages(session_id, action_id, generation),
            f"confirm pending security messages {session_id}",
        )

    def _on_security_pending_discard_requested(self, session_id: str) -> None:
        """Discard locally held messages that are still waiting for security confirmation."""
        generation = self._session_focus_generation
        if not self._is_current_session_context(session_id, generation):
            return
        self._schedule_ui_task(
            self._discard_security_pending_messages(session_id, generation),
            f"discard pending security messages {session_id}",
        )

    async def _confirm_security_pending_messages(self, session_id: str, action_id: str, generation: int) -> None:
        """Run one security action and release the locally queued messages for the session."""
        try:
            action_result = await self._chat_controller.execute_session_security_action(session_id, action_id)
        except Exception as exc:
            if not self._is_current_session_context(session_id, generation):
                return
            InfoBar.error(
                tr("chat.message.title", "Message"),
                str(exc) or tr("chat.security_pending.confirm_failed", "Unable to confirm the required security action."),
                parent=self.window(),
                duration=2400,
            )
            return

        if not bool(action_result.get("performed")):
            if not self._is_current_session_context(session_id, generation):
                return
            message = str(action_result.get("explanation") or action_result.get("reason") or "").strip()
            InfoBar.warning(
                tr("chat.message.title", "Message"),
                message or tr("chat.security_pending.confirm_failed", "Unable to confirm the required security action."),
                parent=self.window(),
                duration=2400,
            )
            return

        release_result = await self._chat_controller.release_session_security_pending_messages(session_id)
        released_count = max(0, int(release_result.get("released", 0) or 0))
        failed_count = max(0, int(release_result.get("failed", 0) or 0))
        if not self._is_current_session_context(session_id, generation):
            return
        if failed_count:
            InfoBar.warning(
                tr("chat.message.title", "Message"),
                tr(
                    "chat.security_pending.release_partial",
                    "{released} queued messages were sent, {failed} failed.",
                    released=released_count,
                    failed=failed_count,
                ),
                parent=self.window(),
                duration=2400,
            )
            return
        InfoBar.success(
            tr("chat.message.title", "Message"),
            tr(
                "chat.security_pending.release_success",
                "{count} queued messages are now sending.",
                count=released_count,
            ),
            parent=self.window(),
            duration=2000,
        )

    async def _discard_security_pending_messages(self, session_id: str, generation: int) -> None:
        """Delete queued local messages that were never sent because security confirmation is missing."""
        result = await self._chat_controller.discard_session_security_pending_messages(session_id)
        removed_count = max(0, int(result.get("removed", 0) or 0))
        if removed_count <= 0 or not self._is_current_session_context(session_id, generation):
            return
        InfoBar.info(
            tr("chat.message.title", "Message"),
            tr(
                "chat.security_pending.discarded",
                "{count} queued messages were discarded.",
                count=removed_count,
            ),
            parent=self.window(),
            duration=1800,
        )

    async def _recall_message(self, message_id: str, session_id: str, generation: int) -> None:
        """Recall a message and surface errors in the UI."""
        success, reason = await self._chat_controller.recall_message(message_id)
        if not self._is_current_session_context(session_id, generation):
            return
        if not success:
            InfoBar.error(
                tr("chat.message.title", "Message"),
                reason or tr("chat.recall_failed", "Recall failed."),
                parent=self.window(),
                duration=2400,
            )

    def _confirm_delete_message(self, message, generation: int) -> None:
        """Ask for confirmation before scheduling one local message delete."""
        if not self._is_current_message_context(message, generation):
            return
        dialog = DeleteMessageConfirmDialog(self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if not self._is_current_message_context(message, generation):
            return

        self._schedule_ui_task(self._delete_message(message, generation), f"delete {message.message_id}")

    async def _delete_message(self, message, generation: int) -> None:
        """Delete a message locally and refresh session preview state."""
        success = await self._chat_controller.delete_message(message.message_id)
        if not self._is_current_message_context(message, generation):
            return
        if not success:
            InfoBar.error(
                tr("chat.message.title", "Message"),
                tr("chat.delete_failed", "Delete failed."),
                parent=self.window(),
                duration=1800,
            )
            return

        self._invalidate_session_caches(message.session_id)
        self.chat_panel.remove_message(message.message_id)
        await self._refresh_session_preview(message.session_id)

    def _schedule_ui_task(self, coro, context: str) -> None:
        """Schedule a UI-triggered coroutine and log any exception."""
        self._create_ui_task(coro, context)

    @staticmethod
    def _log_ui_task_result(task: asyncio.Task, context: str) -> None:
        """Log background task failures from UI actions."""
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("UI action task failed: %s", context)

    def _schedule_read_receipt(self) -> None:
        """Defer read-receipt sending until after the current UI update completes."""
        session_id = self._current_session_id
        if not session_id or not self._can_mark_session_read():
            return

        latest_incoming = self._latest_readable_message()
        if latest_incoming is None:
            return

        pending_key = (session_id, latest_incoming.message_id)
        if self._last_read_receipts.get(session_id) == latest_incoming.message_id:
            return
        if pending_key in self._pending_read_receipts:
            return

        generation = self._session_focus_generation
        ui_generation = self._ui_callback_generation
        self._pending_read_receipts.add(pending_key)
        self._schedule_ui_single_shot(
            0,
            lambda sid=session_id, mid=latest_incoming.message_id, current=generation: self._schedule_ui_task(
                self._send_read_receipt_for(sid, mid, current),
                f"read receipt {sid}:{mid}",
            ),
            generation=ui_generation,
        )

    async def _send_read_receipt_for(self, session_id: str, message_id: str, generation: int) -> None:
        """Send a cumulative read receipt for a specific session/message pair."""
        pending_key = (session_id, message_id)
        try:
            if not self._is_current_session_context(session_id, generation) or not self._can_mark_session_read():
                return
            if self._last_read_receipts.get(session_id) == message_id:
                return

            success = await self._chat_controller.send_read_receipt(message_id, session_id=session_id)
            if success and self._is_current_session_context(session_id, generation):
                self._last_read_receipts[session_id] = message_id
        finally:
            self._pending_read_receipts.discard(pending_key)

    def _latest_readable_message(self):
        """Return the latest visible non-self message that can advance read state."""
        for message in reversed(self.chat_panel.get_visible_messages()):
            if message.is_self:
                continue
            if message.message_type == MessageType.SYSTEM:
                continue
            return message
        return None

    async def _refresh_session_preview(self, session_id: str) -> None:
        """Refresh session preview content from the latest local message."""
        await self._chat_controller.refresh_session_preview(session_id)

    def _get_session(self, session_id: str):
        """Find session object by ID."""
        return self._chat_controller.get_session(session_id)

    def set_session_visibility_active(self, active: bool) -> None:
        """Toggle whether the current session is actually visible and foreground-readable."""
        normalized = bool(active)
        if self._session_visibility_active == normalized:
            return
        self._session_visibility_active = normalized
        self._set_current_session_active(normalized)

    def _activate_selected_session_if_visible(self, session_id: Optional[str]) -> None:
        """Promote the selected session into active/readable state when the page is visible."""
        if session_id != self._current_session_id:
            return
        self._set_current_session_active(self._session_visibility_active)

    def _set_current_session_active(self, active: bool) -> None:
        """Keep controller/session-manager read state aligned with window visibility."""
        is_active = bool(self._session_visibility_active and self._current_session_id)
        if not active:
            is_active = False
        if self._current_session_active == is_active:
            return

        self._current_session_active = is_active
        self._schedule_ui_task(
            self._chat_controller.set_current_session_active(is_active),
            f"set current session active {is_active}",
        )
        if is_active:
            self._schedule_read_receipt()

    def _can_mark_session_read(self) -> bool:
        """Return whether the selected session is actively visible to the user."""
        if not self._current_session_active or not self._current_session_id:
            return False

        window = self.window()
        if window is None:
            return False

        return bool(
            self.isVisible()
            and window.isVisible()
            and not window.isMinimized()
            and window.isActiveWindow()
        )

    def get_session_panel(self) -> SessionPanel:
        """Return session panel widget."""
        return self.session_panel

    def get_chat_panel(self) -> ChatPanel:
        """Return chat panel widget."""
        return self.chat_panel

    def get_current_session_id(self) -> Optional[str]:
        """Return current session ID."""
        return self._current_session_id

    def focus_session(self, session_id: str) -> bool:
        """Focus an existing session in the list and message panel."""
        if not self._get_session(session_id):
            return False
        return self.session_panel.select_session(session_id, emit_signal=True)

    def get_session(self, session_id: str):
        """Return one cached session for external UI integrations."""
        return self._get_session(session_id)

    async def open_session(self, session_id: str, *, generation: int | None = None) -> bool:
        """Open any existing session by id, fetching it when needed."""
        open_generation = self._advance_session_focus_generation() if generation is None else generation
        if not self._is_session_focus_generation_current(open_generation):
            return False
        if session_id == self._current_session_id and self._get_session(session_id):
            return True

        if self.focus_session(session_id):
            return True

        session = await self._chat_controller.ensure_session_loaded(
            session_id,
            fallback_name="Session",
        )
        if not self._is_session_focus_generation_current(open_generation):
            return False
        if not session:
            return False

        return self.focus_session(session.session_id)

    async def open_group_session(self, session_id: str, *, generation: int | None = None) -> bool:
        """Open a group session, fetching it from the backend if needed."""
        return await self.open_session(session_id, generation=generation)

    async def open_direct_session(
        self,
        user_id: str,
        display_name: str = "",
        avatar: str = "",
        *,
        generation: int | None = None,
    ) -> bool:
        """Open an existing direct session or create one for the given contact."""
        open_generation = self._advance_session_focus_generation() if generation is None else generation
        if not self._is_session_focus_generation_current(open_generation):
            return False
        session = self._chat_controller.find_direct_session(user_id)
        if session:
            return self.focus_session(session.session_id)

        session = await self._chat_controller.ensure_direct_session(
            user_id,
            display_name=display_name,
            avatar=avatar,
        )
        if not self._is_session_focus_generation_current(open_generation):
            return False
        if not session:
            return False

        return self.focus_session(session.session_id)







