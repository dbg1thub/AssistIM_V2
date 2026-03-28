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
    TextEdit,
    isDarkTheme,
)
from qfluentwidgets.components.widgets.menu import MenuAnimationType

from client.core.i18n import tr
from client.core.message_actions import should_offer_delete, should_offer_recall
from client.events.event_bus import get_event_bus
from client.managers.message_manager import MessageEvent
from client.managers.session_manager import SessionEvent, get_session_manager
from client.models.message import MessageStatus, MessageType, format_message_preview
from client.ui.controllers.auth_controller import get_auth_controller
from client.ui.controllers.chat_controller import get_chat_controller
from client.ui.controllers.contact_controller import ContactRecord, get_contact_controller
from client.ui.controllers.session_controller import get_session_controller
from client.ui.styles import StyleSheet
from client.ui.windows.contact_interface import StartGroupChatDialog
from client.ui.widgets.chat_panel import ChatPanel
from client.ui.widgets.fluent_splitter import FluentSplitter
from client.ui.widgets.screenshot_overlay import ScreenshotOverlay
from client.ui.widgets.session_panel import SessionPanel


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


class EditMessageDialog(QDialog):
    """Dialog used to edit a text message."""

    def __init__(self, content: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("chat.edit.title", "Edit Message"))
        self.setModal(True)
        self.resize(420, 240)
        _apply_themed_dialog_surface(self, "EditMessageDialog")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = SubtitleLabel(tr("chat.edit.title", "Edit Message"), self)
        self.editor = TextEdit(self)
        self.editor.setPlainText(content)
        self.editor.setAcceptRichText(False)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        self.cancel_button = PushButton(tr("common.cancel", "Cancel"), self)
        self.confirm_button = PrimaryPushButton(tr("common.save", "Save"), self)

        self.cancel_button.clicked.connect(self.reject)
        self.confirm_button.clicked.connect(self._on_confirm)

        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.confirm_button)

        layout.addWidget(title)
        layout.addWidget(self.editor, 1)
        layout.addLayout(button_row)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in {
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.StyleChange,
        }:
            _apply_themed_dialog_surface(self, "EditMessageDialog")

    def _on_confirm(self) -> None:
        """Validate content before closing."""
        if self.get_content():
            self.accept()

    def get_content(self) -> str:
        """Return the trimmed editor content."""
        return self.editor.toPlainText().strip()


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


class ChatInterface(QWidget):
    """Main chat interface with session list on the left and chat view on the right."""

    SESSION_PANEL_WIDTH = 300
    MESSAGE_PAGE_SIZE = 50
    HISTORY_PAGE_CACHE_LIMIT = 12
    INITIAL_HISTORY_WARM_CONCURRENCY = 2
    INITIAL_HISTORY_WARM_SESSION_LIMIT = 6
    TYPING_INDICATOR_HIDE_DELAY_MS = 1800

    def __init__(self, parent=None):
        super().__init__(parent)

        self._chat_controller = get_chat_controller()
        self._contact_controller = get_contact_controller()
        self._auth_controller = get_auth_controller()
        self._session_controller = get_session_controller()
        self._current_session_id: Optional[str] = None
        self._load_task: Optional[asyncio.Task] = None
        self._event_bus = get_event_bus()
        self._event_subscriptions: list[tuple[str, object]] = []
        self._screenshot_overlays: set[ScreenshotOverlay] = set()
        self._screenshot_dialogs: set[ScreenshotPreviewDialog] = set()
        self._dialog_refs: set[QDialog] = set()
        self._session_visibility_active = False
        self._current_session_active = False
        self._oldest_loaded_timestamp: Optional[float] = None
        self._has_more_history = True
        self._history_load_task: Optional[asyncio.Task] = None
        self._history_page_cache: dict[str, OrderedDict[tuple[Optional[float], int], list]] = {}
        self._history_page_warm_keys: set[tuple[str, Optional[float], int]] = set()
        self._history_page_tasks: dict[tuple[str, Optional[float], int], asyncio.Task] = {}
        self._startup_history_prefetch_task: Optional[asyncio.Task] = None
        self._session_view_state: dict[str, dict] = {}
        self._last_read_receipts: dict[str, str] = {}
        self._pending_read_receipts: set[tuple[str, str]] = set()
        self._composer_drafts: dict[str, list[dict]] = {}
        self._ui_tasks: set[asyncio.Task] = set()
        self._message_context_menu: RoundMenu | None = None
        self._typing_indicator_timer = QTimer(self)
        self._typing_indicator_timer.setSingleShot(True)

        self._setup_ui()
        self._typing_indicator_timer.timeout.connect(self.chat_panel.hide_typing_indicator)
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
        self.chat_panel.set_send_typing_callback(self._on_send_typing)

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
        self.chat_panel.chat_info_search_requested.connect(self._on_chat_info_search_requested)
        self.chat_panel.chat_info_add_requested.connect(self._on_chat_info_add_requested)
        self.chat_panel.chat_info_clear_requested.connect(self._on_chat_info_clear_requested)
        self.chat_panel.chat_info_mute_toggled.connect(self._on_chat_info_mute_toggled)
        self.chat_panel.chat_info_pin_toggled.connect(self._on_chat_info_pin_toggled)
        self.chat_panel.get_message_list().customContextMenuRequested.connect(self._on_message_context_menu)

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        """Force both panes to re-layout item widths while the splitter is dragged."""
        QTimer.singleShot(0, self.session_panel._relayout_session_list)
        QTimer.singleShot(0, self.chat_panel._relayout_message_list)

    def _on_sidebar_search_result_requested(self, payload: object) -> None:
        """Open a conversation from one grouped sidebar search result."""
        self._schedule_ui_task(self._open_sidebar_search_result(payload), "open sidebar search result")

    async def _open_sidebar_search_result(self, payload: object) -> None:
        """Route sidebar search hits into the appropriate chat open flow."""
        if not isinstance(payload, dict):
            return

        target_type = str(payload.get("type", "") or "")
        data = payload.get("data") or {}
        opened = False

        if target_type == "group":
            session_id = str(data.get("session_id", "") or data.get("id", "") or "")
            if session_id:
                opened = await self.open_group_session(session_id)
        elif target_type == "message":
            session_id = str(data.get("session_id", "") or "")
            if session_id:
                opened = await self.open_session(session_id)
        else:
            user_id = str(data.get("id", "") or "")
            if user_id:
                opened = await self.open_direct_session(
                    user_id,
                    display_name=str(data.get("display_name", "") or data.get("name", "") or ""),
                    avatar=str(data.get("avatar", "") or ""),
                )

        if not opened:
            InfoBar.warning(
                tr("main_window.contact_jump.unavailable_title", "Chat"),
                tr("main_window.contact_jump.unavailable_message", "Unable to open this conversation right now."),
                parent=self.window(),
                duration=2200,
            )

    def _subscribe_to_events(self) -> None:
        """Subscribe to session and message events for real-time UI updates."""
        self._subscribe_sync(SessionEvent.CREATED, self._on_session_event)
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
        self._subscribe_sync(MessageEvent.SYNC_COMPLETED, self._on_sync_completed)

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
        self._unsubscribe_from_events()
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

    def _on_session_event(self, data: dict) -> None:
        """React to session lifecycle updates."""
        is_delete_event = (
            data.get("session_id") == self._current_session_id
            and "session" not in data
            and "sessions" not in data
        )
        if is_delete_event:
            self._current_session_id = None
            self._set_current_session_active(False)
            self.chat_panel.clear_messages()
            self.chat_panel.show_welcome()
            return

        if not self._current_session_id:
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
        if session_id == self._current_session_id:
            self.chat_panel.show_typing_indicator()
            self._typing_indicator_timer.start(self.TYPING_INDICATOR_HIDE_DELAY_MS)

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
        self.chat_panel.update_message_content(data.get("message_id", ""), data.get("content", ""))
        self.chat_panel.update_message_status(data.get("message_id", ""), MessageStatus.EDITED)
        self._schedule_ui_task(self._refresh_session_preview(session_id), f"refresh preview {session_id}")

    def _on_recalled_event(self, data: dict) -> None:
        """Replace recalled message content."""
        session_id = data.get("session_id", "")
        self._invalidate_session_caches(session_id)
        notice = data.get("content") or getattr(
            data.get("message"),
            "content",
            tr("message.recalled_notice", "A message was recalled"),
        )
        if session_id != self._current_session_id:
            self._schedule_ui_task(self._refresh_session_preview(session_id), f"refresh preview {session_id}")
            return
        message_id = data.get("message_id", "")
        self.chat_panel.update_message_content(message_id, notice)
        self.chat_panel.update_message_status(message_id, MessageStatus.RECALLED)
        self._schedule_ui_task(self._refresh_session_preview(session_id), f"refresh preview {session_id}")

    def _on_deleted_event(self, data: dict) -> None:
        """Remove a deleted message and refresh session preview."""
        session_id = data.get("session_id", "")
        self._invalidate_session_caches(session_id)
        if session_id == self._current_session_id:
            self.chat_panel.remove_message(data.get("message_id", ""))
        self._schedule_ui_task(self._refresh_session_preview(session_id), f"refresh preview {session_id}")

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
        self._has_more_history = True

        self._cancel_pending_task(self._load_task)
        self._cancel_pending_task(self._history_load_task)

        cached_state = self._session_view_state.get(session_id)
        cached_page = self._peek_cached_history_page(session_id, before_timestamp=None)
        if cached_state:
            self._restore_session_view_state(session_id, cached_state)
            self._set_load_task(self._select_session_only(session_id), f"select session {session_id}")
        else:
            if cached_page:
                self._apply_primary_history_page(session_id, cached_page, schedule_read_receipt=False)
            self._set_load_task(self._load_session_messages(session_id), f"load session {session_id}")

    async def _load_session_messages(self, session_id: str) -> None:
        """Load local messages for the selected session."""
        try:
            await self._chat_controller.select_session(session_id)
            self._activate_selected_session_if_visible(session_id)
            local_messages = self._peek_cached_history_page(session_id, before_timestamp=None)
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
                        messages=local_messages,
                        warm=False,
                    )
            if session_id == self._current_session_id and local_messages:
                self._apply_primary_history_page(session_id, local_messages, schedule_read_receipt=False)
            messages = await self._load_history_page(
                session_id,
                before_timestamp=None,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Failed to load messages for %s: %s", session_id, exc)
            return

        if session_id != self._current_session_id:
            return

        self._apply_primary_history_page(session_id, messages)

    def _apply_primary_history_page(
        self,
        session_id: str,
        messages: list,
        *,
        schedule_read_receipt: bool = True,
    ) -> None:
        """Render the primary history page while preserving any live in-memory messages."""
        if session_id != self._current_session_id:
            return

        merged_messages = self._merge_loaded_messages_with_visible(messages)
        self.chat_panel.set_messages(merged_messages)
        self._oldest_loaded_timestamp = self._extract_oldest_timestamp(merged_messages)
        self._has_more_history = len(merged_messages) >= self.MESSAGE_PAGE_SIZE and self._oldest_loaded_timestamp is not None
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

    async def _select_session_only(self, session_id: str) -> None:
        """Update session selection side effects without reloading the visible page from storage."""
        try:
            await self._chat_controller.select_session(session_id)
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

        self._set_history_load_task(
            self._load_older_messages(self._current_session_id),
            f"load older messages {self._current_session_id}",
        )

    async def _load_older_messages(self, session_id: str) -> None:
        """Prepend one older history page while keeping the current viewport stable."""
        before_timestamp = self._oldest_loaded_timestamp
        if before_timestamp is None:
            self.chat_panel.set_history_loading(False)
            self._has_more_history = False
            self.chat_panel.set_has_more_history(False)
            return

        try:
            messages = await self._load_history_page(session_id, before_timestamp=before_timestamp)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Failed to load older messages for %s: %s", session_id, exc)
            self.chat_panel.set_history_loading(False)
            return

        if session_id != self._current_session_id:
            self.chat_panel.set_history_loading(False)
            return

        if not messages:
            self._has_more_history = False
            self.chat_panel.set_has_more_history(False)
            self.chat_panel.set_history_loading(False)
            return

        self.chat_panel.prepend_messages(messages)
        self._oldest_loaded_timestamp = self._extract_oldest_timestamp(messages)
        self._has_more_history = len(messages) >= self.MESSAGE_PAGE_SIZE and self._oldest_loaded_timestamp is not None
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

    async def _load_history_page(
        self,
        session_id: str,
        before_timestamp: Optional[float],
    ) -> list:
        """Load one history page, reusing cached local pages when available."""
        cache = self._history_page_cache.setdefault(session_id, OrderedDict())
        cache_key = (before_timestamp, self.MESSAGE_PAGE_SIZE)
        cached_page = cache.get(cache_key)
        task_key = self._history_page_task_key(session_id, before_timestamp)
        if cached_page is not None and (before_timestamp is not None or task_key in self._history_page_warm_keys):
            cache.move_to_end(cache_key)
            return list(cached_page)

        task = self._history_page_tasks.get(task_key)
        if task is None or task.done():
            task = asyncio.create_task(self._fetch_and_cache_history_page(session_id, before_timestamp))
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
    ) -> list:
        """Fetch one history page through the normal controller path and cache it as warm data."""
        messages = await self._chat_controller.load_messages(
            session_id,
            limit=self.MESSAGE_PAGE_SIZE,
            before_timestamp=before_timestamp,
        )
        self._cache_history_page(
            session_id,
            before_timestamp=before_timestamp,
            messages=messages,
            warm=True,
        )
        return list(messages)

    def _cache_history_page(
        self,
        session_id: str,
        *,
        before_timestamp: Optional[float],
        messages: list,
        warm: bool,
    ) -> None:
        """Store one history page and remember whether it already includes remote backfill."""
        cache = self._history_page_cache.setdefault(session_id, OrderedDict())
        cache_key = (before_timestamp, self.MESSAGE_PAGE_SIZE)
        cache[cache_key] = list(messages)
        cache.move_to_end(cache_key)

        task_key = self._history_page_task_key(session_id, before_timestamp)
        if warm:
            self._history_page_warm_keys.add(task_key)
        else:
            self._history_page_warm_keys.discard(task_key)

        while len(cache) > self.HISTORY_PAGE_CACHE_LIMIT:
            dropped_key, _ = cache.popitem(last=False)
            self._history_page_warm_keys.discard((session_id, dropped_key[0], dropped_key[1]))

    def _peek_cached_history_page(
        self,
        session_id: str,
        *,
        before_timestamp: Optional[float],
    ) -> Optional[list]:
        """Return one cached history page without triggering any async work."""
        cache = self._history_page_cache.get(session_id)
        if not cache:
            return None

        cache_key = (before_timestamp, self.MESSAGE_PAGE_SIZE)
        cached_page = cache.get(cache_key)
        if cached_page is None:
            return None
        cache.move_to_end(cache_key)
        return list(cached_page)

    def _history_page_task_key(
        self,
        session_id: str,
        before_timestamp: Optional[float],
    ) -> tuple[str, Optional[float], int]:
        """Build one stable identity for a cached history page."""
        return (session_id, before_timestamp, self.MESSAGE_PAGE_SIZE)

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
        if self._peek_cached_history_page(session_id, before_timestamp=None) is None:
            local_messages = await self._chat_controller.load_cached_messages(
                session_id,
                limit=self.MESSAGE_PAGE_SIZE,
                before_timestamp=None,
            )
            if local_messages:
                self._cache_history_page(
                    session_id,
                    before_timestamp=None,
                    messages=local_messages,
                    warm=False,
                )

        await self._load_history_page(session_id, before_timestamp=None)

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
            "has_more_history": self._has_more_history,
        }

    def _restore_session_view_state(self, session_id: str, state: dict) -> None:
        """Restore a previously cached visible state for the selected session."""
        messages = list(state.get("messages") or [])
        self.chat_panel.set_messages(messages, scroll_to_bottom=False)
        self._oldest_loaded_timestamp = state.get("oldest_loaded_timestamp")
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
                    )
                elif segment_type in {MessageType.IMAGE, MessageType.VIDEO, MessageType.FILE} and segment.get("file_path"):
                    await self._chat_controller.send_file(segment["file_path"], session_id=session_id)
            except Exception as exc:
                logger.error("Send composed segment error: %s", exc)

    async def _send_image_message(self, session_id: str, file_path: str) -> None:
        """Send an image using the optimistic media upload flow."""
        try:
            message = await self._chat_controller.send_file(file_path, session_id=session_id)
            if message:
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
        overlay.captured.connect(self._handle_screenshot_captured)
        overlay.canceled.connect(lambda: self._screenshot_overlays.discard(overlay))
        overlay.destroyed.connect(lambda *_args, ref=overlay: self._screenshot_overlays.discard(ref))
        overlay.start()

    def _handle_screenshot_captured(self, file_path: str) -> None:
        """Preview a captured screenshot before sending it."""
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
                    self._schedule_ui_task(
                        self._send_image_message(self._current_session_id, file_path),
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
        """Show placeholder feedback for voice calls."""
        InfoBar.info(
            tr("chat.voice_call.title", "Voice Call"),
            tr("chat.voice_call.unavailable", "Voice calling is not connected yet."),
            parent=self.window(),
            duration=1800,
        )

    def _on_video_call_requested(self) -> None:
        """Show placeholder feedback for video calls."""
        InfoBar.info(
            tr("chat.video_call.title", "Video Call"),
            tr("chat.video_call.unavailable", "Video calling is not connected yet."),
            parent=self.window(),
            duration=1800,
        )

    def _on_chat_history_requested(self) -> None:
        """Show placeholder feedback for the reserved chat-history entry point."""
        InfoBar.info(
            tr("chat.info.history.title", "Chat History"),
            tr("chat.info.history.unavailable", "The chat history entry is reserved and will be connected next."),
            parent=self.window(),
            duration=1800,
        )

    def _on_chat_info_search_requested(self) -> None:
        """Show placeholder feedback for chat-content search."""
        InfoBar.info(
            tr("chat.info.search.title", "Find Chat Content"),
            tr("chat.info.search.unavailable", "The in-chat search feature will be connected next."),
            parent=self.window(),
            duration=1800,
        )

    def _on_chat_info_add_requested(self) -> None:
        """Open the contact selector used to turn the current private chat into a new group."""
        session = self._get_session(self._current_session_id or "")
        if session is None or session.is_ai_session or session.session_type != "direct":
            InfoBar.info(
                tr("chat.info.add.title", "Add"),
                tr("chat.info.add.unavailable", "This entry is reserved for future group-chat expansion."),
                parent=self.window(),
                duration=1800,
            )
            return

        self._schedule_ui_task(
            self._show_start_group_dialog(session),
            f"start group chat selector {session.session_id}",
        )

    def _on_chat_info_clear_requested(self) -> None:
        """Show placeholder feedback for clear-history until durable sync semantics are defined."""
        InfoBar.info(
            tr("chat.info.clear.title", "Clear Chat History"),
            tr(
                "chat.info.clear.unavailable",
                "The clear-history entry is reserved. Durable sync-safe clearing will be connected next.",
            ),
            parent=self.window(),
            duration=2200,
        )

    def _on_chat_info_mute_toggled(self, muted: bool) -> None:
        """Persist local do-not-disturb state for the current session."""
        session_id = self._current_session_id
        if not session_id:
            return

        session = self._get_session(session_id)
        if session is not None:
            session.extra["is_muted"] = bool(muted)
            self._event_bus.emit_sync(SessionEvent.UPDATED, {"session": session})

        self._schedule_ui_task(
            self._session_controller.set_muted(session_id, muted),
            f"mute session {session_id}",
        )

    def _on_chat_info_pin_toggled(self, pinned: bool) -> None:
        """Persist pin state for the current session."""
        session_id = self._current_session_id
        if not session_id:
            return

        session = self._get_session(session_id)
        if session is not None:
            setattr(session, "is_pinned", bool(pinned))
            session.extra["is_pinned"] = bool(pinned)
            self._event_bus.emit_sync(SessionEvent.UPDATED, {"session": session})

        self._schedule_ui_task(
            self._session_controller.set_pinned(session_id, pinned),
            f"pin session {session_id}",
        )

    def close_transient_panels(self) -> None:
        """Close floating transient UI owned by the chat page."""
        self.chat_panel.close_chat_info_drawer(immediate=True)

    async def _show_start_group_dialog(self, session) -> None:
        """Load contacts and open the frameless modal used to start one new group chat."""
        counterpart_id = self._resolve_counterpart_id(session)
        if not counterpart_id:
            InfoBar.warning(
                tr("chat.group_picker.title", "Start Group Chat"),
                tr("chat.group_picker.no_counterpart", "Unable to resolve the current private chat participant."),
                parent=self.window(),
                duration=2200,
            )
            return

        try:
            contacts = await self._contact_controller.load_contacts()
        except Exception as exc:
            InfoBar.error(
                tr("chat.group_picker.title", "Start Group Chat"),
                str(exc) or tr("chat.group_picker.load_failed", "Unable to load contacts right now."),
                parent=self.window(),
                duration=2200,
            )
            return

        contacts = self._merge_group_picker_contacts(contacts, session, counterpart_id)
        if not contacts:
            InfoBar.info(
                tr("chat.group_picker.title", "Start Group Chat"),
                tr("chat.group_picker.no_contacts", "There are no additional contacts available to add."),
                parent=self.window(),
                duration=2200,
            )
            return

        dialog = StartGroupChatDialog(
            self._contact_controller,
            contacts,
            excluded_contact_id=counterpart_id,
            parent=self.window(),
        )
        dialog.group_created.connect(self._on_group_chat_created)
        self._show_dialog(dialog)

    def _resolve_counterpart_id(self, session) -> str:
        """Resolve the other participant id for the current direct chat."""
        extra = dict(getattr(session, "extra", {}) or {})
        counterpart_id = str(extra.get("counterpart_id", "") or "").strip()
        if counterpart_id:
            return counterpart_id

        current_user = self._auth_controller.current_user or {}
        current_user_id = str(current_user.get("id", "") or "")
        for participant_id in getattr(session, "participant_ids", []) or []:
            normalized_id = str(participant_id or "").strip()
            if not normalized_id or normalized_id == current_user_id:
                continue
            return normalized_id
        return ""

    def _merge_group_picker_contacts(
        self,
        contacts: list[ContactRecord],
        session,
        counterpart_id: str,
    ) -> list[ContactRecord]:
        """Return deduplicated friends excluding the active private-chat participant."""
        deduped: dict[str, ContactRecord] = {}
        for contact in contacts:
            if contact.id and contact.id != counterpart_id:
                deduped[contact.id] = contact

        return sorted(
            deduped.values(),
            key=lambda item: item.display_name.lower(),
        )

    def _show_dialog(self, dialog: QDialog) -> None:
        """Keep one non-blocking modal dialog alive while it is visible."""
        self._dialog_refs.add(dialog)
        dialog.finished.connect(lambda _result=0, dlg=dialog: self._dialog_refs.discard(dlg))
        dialog.finished.connect(dialog.deleteLater)
        dialog.open()
        dialog.raise_()
        dialog.activateWindow()

    def _on_group_chat_created(self, group: object) -> None:
        """Jump from the current private chat into the newly created group."""
        self.chat_panel.close_chat_info_drawer(immediate=True)
        session_id = str(getattr(group, "session_id", "") or "")
        if not session_id:
            InfoBar.warning(
                tr("chat.group_picker.title", "Start Group Chat"),
                tr("main_window.contact_jump.unavailable_message", "Unable to open this conversation right now."),
                parent=self.window(),
                duration=2200,
            )
            return

        self._schedule_ui_task(
            self._open_created_group_session(group),
            f"open created group {session_id}",
        )

    async def _open_created_group_session(self, group: object) -> None:
        """Open the freshly created group session and report failures."""
        session_id = str(getattr(group, "session_id", "") or "")
        opened = await self.open_group_session(session_id)
        if opened:
            session = self.get_session(session_id)
            avatar = str(getattr(group, "avatar", "") or getattr(group, "extra", {}).get("avatar", "") or "")
            member_preview = list(getattr(group, "extra", {}).get("member_preview") or [])
            if session and avatar:
                session.avatar = avatar
                session.extra["member_preview"] = member_preview
                await get_session_manager().update_session(session_id, avatar=avatar, extra=session.extra)
                self.session_panel.update_session(session_id, avatar=avatar)
                if self._current_session_id == session_id:
                    self.chat_panel.set_session(session)
            return

        InfoBar.warning(
            tr("chat.group_picker.title", "Start Group Chat"),
            tr("main_window.contact_jump.unavailable_message", "Unable to open this conversation right now."),
            parent=self.window(),
            duration=2200,
        )

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
        edit_action = None
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

        if message.is_self and message.message_type == MessageType.TEXT and message.status != MessageStatus.RECALLED:
            edit_action = Action(tr("chat.context.edit", "Edit"), self)
            message_actions.append(edit_action)

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
                lambda _checked=False, msg=message: QTimer.singleShot(0, lambda: self._open_message(msg))
            )
        if edit_action:
            edit_action.triggered.connect(
                lambda _checked=False, msg=message: QTimer.singleShot(0, lambda: self._prompt_edit_message(msg))
            )
        if recall_action:
            recall_action.triggered.connect(
                lambda _checked=False, message_id=message.message_id: self._schedule_ui_task(
                    self._recall_message(message_id),
                    f"recall {message_id}",
                )
            )
        if delete_action:
            delete_action.triggered.connect(
                lambda _checked=False, msg=message: QTimer.singleShot(0, lambda: self._confirm_delete_message(msg))
            )
        if retry_action:
            retry_action.triggered.connect(
                lambda _checked=False, message_id=message.message_id: self._schedule_ui_task(
                    self._retry_message(message_id),
                    f"retry {message_id}",
                )
            )

        if delete_action:
            delete_item = delete_action.property("item")
            if delete_item is not None:
                delete_item.setForeground(QColor("#d13438"))

        if message.message_type == MessageType.TEXT:
            self.chat_panel.set_context_menu_message(message.message_id)

        def _on_menu_hidden() -> None:
            if self._message_context_menu is menu:
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

    def _open_message(self, message) -> None:
        """Open an image, file, or video attachment."""
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
            if not self.chat_panel.open_message_attachment(message):
                InfoBar.warning(
                    tr("chat.message.title", "Message"),
                    tr("chat.attachment.file_open_failed", "Unable to open this attachment."),
                    parent=self.window(),
                    duration=1800,
                )

    def _prompt_edit_message(self, message) -> None:
        """Open the edit dialog for a text message."""
        dialog = EditMessageDialog(message.content, self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        new_content = dialog.get_content()
        if not new_content:
            InfoBar.warning(
                tr("chat.edit.title", "Edit Message"),
                tr("chat.edit.empty", "Content cannot be empty."),
                parent=self.window(),
                duration=1800,
            )
            return
        if new_content == message.content:
            return

        self._schedule_ui_task(self._edit_message(message.message_id, new_content), f"edit {message.message_id}")

    async def _retry_message(self, message_id: str) -> None:
        """Retry a failed message."""
        success = await self._chat_controller.retry_message(message_id)
        if not success:
            InfoBar.error(
                tr("chat.message.title", "Message"),
                tr("chat.retry_failed", "Retry failed."),
                parent=self.window(),
                duration=1800,
            )

    async def _recall_message(self, message_id: str) -> None:
        """Recall a message and surface errors in the UI."""
        success, reason = await self._chat_controller.recall_message(message_id)
        if not success:
            InfoBar.error(
                tr("chat.message.title", "Message"),
                reason or tr("chat.recall_failed", "Recall failed."),
                parent=self.window(),
                duration=2400,
            )

    async def _edit_message(self, message_id: str, new_content: str) -> None:
        """Edit a message and surface errors in the UI."""
        success = await self._chat_controller.edit_message(message_id, new_content)
        if not success:
            InfoBar.error(
                tr("chat.edit.title", "Edit Message"),
                tr("chat.edit_failed", "Edit failed."),
                parent=self.window(),
                duration=1800,
            )

    def _confirm_delete_message(self, message) -> None:
        """Ask for confirmation before scheduling one local message delete."""
        dialog = DeleteMessageConfirmDialog(self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._schedule_ui_task(self._delete_message(message), f"delete {message.message_id}")

    async def _delete_message(self, message) -> None:
        """Delete a message locally and refresh session preview state."""
        success = await self._chat_controller.delete_message(message.message_id)
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

        self._pending_read_receipts.add(pending_key)
        QTimer.singleShot(
            0,
            lambda sid=session_id, mid=latest_incoming.message_id: self._schedule_ui_task(
                self._send_read_receipt_for(sid, mid),
                f"read receipt {sid}:{mid}",
            ),
        )

    async def _send_read_receipt_for(self, session_id: str, message_id: str) -> None:
        """Send a cumulative read receipt for a specific session/message pair."""
        pending_key = (session_id, message_id)
        try:
            if session_id != self._current_session_id or not self._can_mark_session_read():
                return
            if self._last_read_receipts.get(session_id) == message_id:
                return

            success = await self._chat_controller.send_read_receipt(message_id, session_id=session_id)
            if success:
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

    async def open_session(self, session_id: str) -> bool:
        """Open any existing session by id, fetching it when needed."""
        if self.focus_session(session_id):
            return True

        session = await self._chat_controller.ensure_session_loaded(
            session_id,
            fallback_name="Session",
        )
        if not session:
            return False

        return self.focus_session(session.session_id)

    async def open_group_session(self, session_id: str) -> bool:
        """Open a group session, fetching it from the backend if needed."""
        return await self.open_session(session_id)

    async def open_direct_session(self, user_id: str, display_name: str = "", avatar: str = "") -> bool:
        """Open an existing direct session or create one for the given contact."""
        session = self._chat_controller.find_direct_session(user_id)
        if session:
            return self.focus_session(session.session_id)

        session = await self._chat_controller.ensure_direct_session(
            user_id,
            display_name=display_name,
            avatar=avatar,
        )
        if not session:
            return False

        return self.focus_session(session.session_id)



