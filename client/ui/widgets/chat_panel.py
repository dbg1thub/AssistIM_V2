"""Right-side chat panel with welcome page, header, message list, and composer."""

from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import QEvent, Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import QAbstractItemView, QFrame, QListView, QStackedWidget, QVBoxLayout, QWidget

from qfluentwidgets import BodyLabel, CaptionLabel, IconWidget, ScrollBarHandleDisplayMode
from qfluentwidgets.components.widgets.scroll_bar import SmoothScrollDelegate

from client.core.app_icons import AppIcon
from client.core.config_backend import get_config
from client.core.i18n import tr
from client.delegates.message_delegate import MessageDelegate
from client.models.message import ChatMessage, MessageType, Session
from client.models.message_model import MessageModel
from client.ui.styles import StyleSheet
from client.ui.widgets.chat_header import ChatHeader
from client.ui.widgets.chat_info_drawer import ChatInfoDrawerOverlay
from client.ui.widgets.fluent_splitter import FluentSplitter
from client.ui.widgets.message_input import MessageInput
from qfluentwidgets.multimedia import VideoWidget


def _session_status_text(session: Session | None) -> str:
    """Return the localized status label for the active session."""
    if session is None:
        return ""
    if session.is_ai_session:
        return tr("chat.status.ai", "AI Session")
    return (
        tr("chat.status.group", "Group Chat")
        if session.session_type == "group"
        else tr("chat.status.direct", "Direct Chat")
    )


class WelcomeWidget(QWidget):
    """Welcome screen shown before any session is selected."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chatWelcomeWidget")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.icon = IconWidget(AppIcon.CHAT, self)
        self.icon.setFixedSize(88, 88)

        self.title_label = BodyLabel(tr("chat.welcome.title", "Welcome to AssistIM"), self)
        self.subtitle_label = CaptionLabel(
            tr(
                "chat.welcome.subtitle",
                "Choose a conversation on the left to continue message sync, file transfer, and AI-assisted chat.",
            ),
            self,
        )
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setMaximumWidth(380)
        self.title_label.setObjectName("chatWelcomeTitle")
        self.subtitle_label.setObjectName("chatWelcomeSubtitle")

        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.subtitle_label, 0, Qt.AlignmentFlag.AlignCenter)


class ChatPanel(QWidget):
    """Chat panel composed of welcome page and active conversation page."""

    MESSAGE_LIST_BOTTOM_MARGIN = 8

    file_upload_requested = Signal(str)
    screenshot_requested = Signal()
    voice_call_requested = Signal()
    video_call_requested = Signal()
    older_messages_requested = Signal()
    composer_draft_changed = Signal(object)
    chat_history_requested = Signal()
    chat_info_search_requested = Signal()
    chat_info_add_requested = Signal()
    chat_info_clear_requested = Signal()
    chat_info_mute_toggled = Signal(bool)
    chat_info_pin_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._message_model: Optional[MessageModel] = None
        self._message_delegate: Optional[MessageDelegate] = None
        self._scroll_delegate: Optional[SmoothScrollDelegate] = None
        self._send_segments_callback: Optional[Callable] = None
        self._send_typing_callback: Optional[Callable] = None
        self._current_session: Optional[Session] = None
        self._message_scroll_gap = 0
        self._restoring_message_view = False
        self._video_windows: list[VideoWidget] = []
        self._history_request_pending = False
        self._has_more_history = True
        self.message_input: Optional[MessageInput] = None
        self.content_splitter: Optional[FluentSplitter] = None
        self._chat_info_overlay: Optional[ChatInfoDrawerOverlay] = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Create stacked welcome page and active chat page."""
        self.setObjectName("ChatPanel")
        self.setMinimumWidth(0)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.stack = QStackedWidget(self)

        self.welcome_widget = WelcomeWidget(self)
        self.chat_page = QWidget(self)
        self.chat_page.setObjectName("chatPage")
        self.chat_layout = QVBoxLayout(self.chat_page)
        self.chat_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_layout.setSpacing(0)

        self.chat_header = ChatHeader(self.chat_page)

        self.message_list = QListView(self.chat_page)
        self.message_list.setObjectName("messageListView")
        self.message_list.setMinimumWidth(0)
        self.message_list.setFrameShape(QFrame.Shape.NoFrame)
        self.message_list.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.message_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.message_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.message_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.message_list.setLayoutMode(QListView.LayoutMode.SinglePass)
        self.message_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.message_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.message_list.setSpacing(0)
        self.message_list.setViewportMargins(0, 0, 0, self.MESSAGE_LIST_BOTTOM_MARGIN)
        self.message_list.setMouseTracking(True)
        self.message_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.message_list.installEventFilter(self)
        self.message_list.viewport().installEventFilter(self)
        self._history_indicator = CaptionLabel(
            tr("chat.history.loading", "Loading more messages..."),
            self.message_list.viewport(),
        )
        self._history_indicator.setObjectName("historyLoadingLabel")
        self._history_indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._history_indicator.hide()

        self._setup_message_model()

        self.message_input = MessageInput(self.chat_page)
        self.message_input.setMinimumWidth(0)
        self.message_input.setMinimumHeight(0)
        self.message_input.setMaximumHeight(340)
        self.message_input.segments_submitted.connect(self._on_segments_submitted)
        self.message_input.attachment_open_requested.connect(self._on_attachment_open_requested)
        self.message_input.screenshot_requested.connect(self.screenshot_requested.emit)
        self.message_input.voice_call_requested.connect(self.voice_call_requested.emit)
        self.message_input.video_call_requested.connect(self.video_call_requested.emit)
        self.message_input.typing_signal.connect(self._on_typing)
        self.message_input.draft_changed.connect(self.composer_draft_changed.emit)

        self.content_splitter = FluentSplitter(Qt.Orientation.Vertical, self.chat_page)
        self.content_splitter.setObjectName("chatContentSplitter")
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(1)
        self.message_list.setMinimumHeight(0)
        self.content_splitter.addWidget(self.message_list)
        self.content_splitter.addWidget(self.message_input)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 0)
        self.content_splitter.setSizes([560, 220])
        self.content_splitter.splitterMoved.connect(self._schedule_restore_message_viewport)
        self.content_splitter.installEventFilter(self)
        self.message_input.installEventFilter(self)

        self.chat_layout.addWidget(self.chat_header, 0)
        self.chat_layout.addWidget(self.content_splitter, 1)

        self._chat_info_overlay = ChatInfoDrawerOverlay(self.chat_page)
        self._chat_info_overlay.searchRequested.connect(self.chat_info_search_requested.emit)
        self._chat_info_overlay.addRequested.connect(self.chat_info_add_requested.emit)
        self._chat_info_overlay.clearRequested.connect(self.chat_info_clear_requested.emit)
        self._chat_info_overlay.muteToggled.connect(self.chat_info_mute_toggled.emit)
        self._chat_info_overlay.pinToggled.connect(self.chat_info_pin_toggled.emit)
        self.chat_header.history_clicked.connect(self.chat_history_requested.emit)
        self.chat_header.info_clicked.connect(self.toggle_chat_info_drawer)

        self.stack.addWidget(self.welcome_widget)
        self.stack.addWidget(self.chat_page)
        self.main_layout.addWidget(self.stack)

        self.show_welcome()
        StyleSheet.CHAT_PANEL.apply(self)
        self._position_history_indicator()
        self._layout_chat_info_overlay()

    def resizeEvent(self, event) -> None:
        """Keep message/input layout responsive while the chat panel is being resized."""
        self._remember_message_scroll_gap()
        super().resizeEvent(event)
        self.chat_layout.activate()
        self._position_history_indicator()
        self._layout_chat_info_overlay()
        self._relayout_message_list()
        self._restore_message_viewport()
        self._schedule_restore_message_viewport()
        QTimer.singleShot(0, self._relayout_message_list)

    def _setup_message_model(self) -> None:
        """Set up the model/delegate pair used by the message list."""
        self._message_model = MessageModel(self)
        self._message_delegate = MessageDelegate(self)
        self._scroll_delegate = SmoothScrollDelegate(self.message_list)
        self._scroll_delegate.vScrollBar.setHandleDisplayMode(ScrollBarHandleDisplayMode.ALWAYS)
        self._scroll_delegate.hScrollBar.setForceHidden(True)
        self._scroll_delegate.vScrollBar.setForceHidden(True)
        self.message_list.setModel(self._message_model)
        self.message_list.setItemDelegate(self._message_delegate)
        self._scroll_delegate.vScrollBar.installEventFilter(self)
        self.message_list.verticalScrollBar().valueChanged.connect(self._remember_message_scroll_gap)
        self.message_list.verticalScrollBar().valueChanged.connect(self._on_message_scroll_value_changed)
        self.message_list.verticalScrollBar().rangeChanged.connect(self._on_message_range_changed)

    def show_welcome(self) -> None:
        """Show welcome page and disable input."""
        self._current_session = None
        self.stack.setCurrentWidget(self.welcome_widget)
        self.message_input.set_session_active(False)
        self.chat_header.set_actions_enabled(False)
        self._history_indicator.hide()
        if self._chat_info_overlay:
            self._chat_info_overlay.set_session(None)
            self._chat_info_overlay.close_drawer(immediate=True)

    def show_chat(self) -> None:
        """Show active chat page and enable input."""
        self.stack.setCurrentWidget(self.chat_page)
        self.message_input.set_session_active(True)
        self.message_input.focus_editor()
        if self._history_request_pending:
            self._history_indicator.show()
        self._position_history_indicator()

    def set_session(self, session: Session) -> None:
        """Update header and switch to active chat page."""
        previous_session_id = getattr(self._current_session, "session_id", None)
        if self._chat_info_overlay and previous_session_id and previous_session_id != session.session_id:
            self._chat_info_overlay.close_drawer(immediate=True)
        self._current_session = session
        self.chat_header.set_session_info(
            title=session.name,
            status=_session_status_text(session),
            avatar=session.avatar,
            is_ai=session.is_ai_session,
        )
        if self._chat_info_overlay:
            self._chat_info_overlay.set_session(session)
        self.show_chat()

    def clear_messages(self) -> None:
        """Clear visible messages from the model."""
        if self._message_model:
            self._message_model.clear()
        self._history_request_pending = False
        self._has_more_history = True

    def set_messages(self, messages: list[ChatMessage], *, scroll_to_bottom: bool = True) -> None:
        """Replace the visible message list in one model reset."""
        if not self._message_model:
            return

        self._message_model.set_messages(messages)
        self._history_request_pending = False
        self._history_indicator.hide()
        if scroll_to_bottom:
            self.message_list.scrollToBottom()
            self._remember_message_scroll_gap()

    def _on_segments_submitted(self, segments: list[dict]) -> None:
        """Forward composed text/media segments in document order."""
        if self._send_segments_callback:
            self._send_segments_callback(segments)

    def _on_attachment_open_requested(self, file_path: str, message_type_value: str) -> None:
        """Open a local inline attachment from the editor."""
        try:
            message_type = MessageType(message_type_value)
        except ValueError:
            return
        self.open_local_attachment(file_path, message_type)

    def _on_typing(self) -> None:
        """Emit typing signal through external callback."""
        if self._send_typing_callback:
            self._send_typing_callback()

    def set_send_segments_callback(self, callback: Callable[[list[dict]], None]) -> None:
        """Set composed segments send callback."""
        self._send_segments_callback = callback

    def set_send_typing_callback(self, callback: Callable[[], None]) -> None:
        """Set typing callback."""
        self._send_typing_callback = callback

    def get_chat_header(self) -> ChatHeader:
        """Return header widget."""
        return self.chat_header

    def get_message_list(self) -> QListView:
        """Return message list widget."""
        return self.message_list

    def get_message_input(self) -> MessageInput:
        """Return input widget."""
        return self.message_input

    def get_message_model(self) -> MessageModel:
        """Return message model."""
        return self._message_model

    def get_visible_messages(self) -> list[ChatMessage]:
        """Return the messages currently materialized in the list view."""
        if not self._message_model:
            return []
        return list(self._message_model.get_messages())

    def get_message_delegate(self) -> MessageDelegate:
        """Return message delegate."""
        return self._message_delegate

    def capture_composer_draft(self) -> list[dict]:
        """Return the current message composer draft without clearing it."""
        return self.message_input.capture_draft_segments()

    def restore_composer_draft(self, segments: list[dict]) -> None:
        """Restore a previously captured composer draft."""
        self.message_input.restore_draft_segments(segments)

    def clear_composer_draft(self) -> None:
        """Clear the current composer draft."""
        self.message_input.clear_draft()

    def add_message(self, message: ChatMessage, *, scroll_to_bottom: bool = True) -> None:
        """Append a message or refresh an existing one in-place."""
        if not self._message_model:
            return

        existing = self._message_model.get_message_by_id(message.message_id)
        if existing is not None:
            existing.session_id = message.session_id
            existing.sender_id = message.sender_id
            existing.content = message.content
            existing.message_type = message.message_type
            existing.status = message.status
            existing.timestamp = message.timestamp
            existing.updated_at = message.updated_at
            existing.is_self = message.is_self
            existing.is_ai = message.is_ai
            existing.extra = dict(message.extra)
            self._message_model.refresh_message(message.message_id, allow_reorder=True)
            self.message_list.viewport().update()
            return

        self._message_model.add_message(message)
        if scroll_to_bottom:
            self.message_list.scrollToBottom()
            self._remember_message_scroll_gap()

    def add_messages(self, messages: list[ChatMessage], *, scroll_to_bottom: bool = True) -> None:
        """Append multiple messages in one batch update."""
        if not self._message_model or not messages:
            return

        new_messages: list[ChatMessage] = []
        for message in messages:
            existing = self._message_model.get_message_by_id(message.message_id)
            if existing is not None:
                existing.session_id = message.session_id
                existing.sender_id = message.sender_id
                existing.content = message.content
                existing.message_type = message.message_type
                existing.status = message.status
                existing.timestamp = message.timestamp
                existing.updated_at = message.updated_at
                existing.is_self = message.is_self
                existing.is_ai = message.is_ai
                existing.extra = dict(message.extra)
                self._message_model.refresh_message(message.message_id, allow_reorder=True)
                continue
            new_messages.append(message)

        if new_messages:
            self._message_model.add_messages(new_messages)

        if scroll_to_bottom:
            self.message_list.scrollToBottom()
            self._remember_message_scroll_gap()

    def prepend_messages(self, messages: list[ChatMessage]) -> None:
        """Insert older history above the current viewport without changing visible content."""
        if not self._message_model or not messages:
            self._history_request_pending = False
            self._history_indicator.hide()
            return

        older_messages: list[ChatMessage] = [
            message
            for message in messages
            if self._message_model.get_message_by_id(message.message_id) is None
        ]
        if not older_messages:
            self._history_request_pending = False
            self._history_indicator.hide()
            return

        bar = self.message_list.verticalScrollBar()
        old_value = bar.value()
        old_maximum = bar.maximum()
        self._message_model.prepend_messages(older_messages)

        def restore_position() -> None:
            new_maximum = bar.maximum()
            delta = max(0, new_maximum - old_maximum)
            self._restoring_message_view = True
            try:
                bar.setValue(old_value + delta)
            finally:
                self._restoring_message_view = False
                self._history_request_pending = False
                self._history_indicator.hide()

        QTimer.singleShot(0, restore_position)

    def update_message_status(self, message_id: str, status) -> None:
        """Update message status in model."""
        if self._message_model:
            self._message_model.update_message_status(message_id, status)

    def apply_read_receipt(self, session_id: str, reader_id: str, last_read_seq: int) -> None:
        """Apply one cumulative read receipt in the visible model."""
        if self._message_model:
            self._message_model.apply_read_receipt(session_id, reader_id, last_read_seq)


    def update_message_content(self, message_id: str, content: str) -> None:
        """Update message content in model."""
        if self._message_model:
            self._message_model.update_message_content(message_id, content)

    def remove_message(self, message_id: str) -> None:
        """Remove a message from the model."""
        if self._message_model:
            self._message_model.remove_message(message_id)

    def get_message_at(self, position, *, bubble_only: bool = False) -> Optional[ChatMessage]:
        """Return the message under a viewport position."""
        index = self.message_list.indexAt(position)
        if not index.isValid():
            return None
        message = index.data(Qt.ItemDataRole.UserRole)
        if not message or message.message_type == MessageType.SYSTEM:
            return None
        if bubble_only and self._message_delegate:
            if not self._message_delegate.is_bubble_hit(self.message_list, index, position):
                return None
        return message

    def set_context_menu_message(self, message_id: str | None) -> None:
        """Highlight one text bubble while its context menu is visible."""
        if self._message_delegate:
            self._message_delegate.set_context_menu_message(self.message_list, message_id)

    def clear_context_menu_message(self) -> None:
        """Clear any transient context-menu bubble highlight."""
        self.set_context_menu_message(None)

    def eventFilter(self, watched, event) -> bool:
        """Only open attachments when the click lands inside the rendered content area."""
        content_splitter = getattr(self, "content_splitter", None)
        message_input = getattr(self, "message_input", None)

        if self._scroll_delegate and watched in {
            self.message_list,
            self.message_list.viewport(),
            self._scroll_delegate.vScrollBar,
        }:
            if event.type() == QEvent.Type.Enter:
                self._scroll_delegate.vScrollBar.setForceHidden(False)
            elif event.type() == QEvent.Type.Leave:
                QTimer.singleShot(0, self._sync_message_scrollbar_visibility)

        if watched is self.message_list.viewport():
            if event.type() == QEvent.Type.Resize:
                self._relayout_message_list()
                self._position_history_indicator()
                self._schedule_restore_message_viewport()
            if event.type() == QEvent.Type.Leave:
                if self._message_delegate:
                    self._message_delegate.clear_time_separator_hover(self.message_list)
                self.message_list.viewport().unsetCursor()
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                position = event.position().toPoint() if hasattr(event, "position") else event.pos()
                index = self.message_list.indexAt(position)
                if index.isValid() and self._message_delegate and self._message_delegate.is_time_separator_hit(
                    self.message_list, index, position
                ):
                    return True
                if index.isValid() and self._message_delegate and self._message_delegate.begin_text_selection(
                    self.message_list, index, position
                ):
                    self.message_list.viewport().setCursor(Qt.CursorShape.IBeamCursor)
                    return True

                if self._message_delegate:
                    self._message_delegate.clear_text_selection(self.message_list)
                    self.message_list.viewport().unsetCursor()

            if event.type() == QEvent.Type.MouseMove:
                position = event.position().toPoint() if hasattr(event, "position") else event.pos()
                if self._message_delegate and self._message_delegate.is_selection_active():
                    if self._message_delegate.update_text_selection(self.message_list, position):
                        self.message_list.viewport().setCursor(Qt.CursorShape.IBeamCursor)
                        return True

                index = self.message_list.indexAt(position)
                if index.isValid() and self._message_delegate and self._message_delegate.update_time_separator_hover(
                    self.message_list, index, position
                ):
                    self.message_list.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                    return True
                if self._message_delegate:
                    self._message_delegate.clear_time_separator_hover(self.message_list)

                if index.isValid() and self._message_delegate and self._message_delegate.is_text_hit(
                    self.message_list, index, position
                ):
                    self.message_list.viewport().setCursor(Qt.CursorShape.IBeamCursor)
                else:
                    self.message_list.viewport().unsetCursor()

            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                if self._message_delegate and self._message_delegate.is_selection_active():
                    self._message_delegate.end_text_selection(self.message_list)
                    return True

                position = event.position().toPoint() if hasattr(event, "position") else event.pos()
                index = self.message_list.indexAt(position)
                if index.isValid() and self._message_delegate and self._message_delegate.toggle_time_separator_expanded_at(
                    self.message_list, index, position
                ):
                    return True
                if index.isValid() and self._is_attachment_click(index, position):
                    self.handle_message_click(index)
                    return True

        tracked_resize_widgets = {widget for widget in (content_splitter, message_input) if widget is not None}
        if watched in tracked_resize_widgets and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.LayoutRequest,
            QEvent.Type.Show,
        }:
            self._remember_message_scroll_gap()
            self._layout_chat_info_overlay()
            self._relayout_message_list()
            self._restore_message_viewport()
            self._schedule_restore_message_viewport()
            QTimer.singleShot(0, self._relayout_message_list)

        if watched is self.message_list and event.type() == QEvent.Type.KeyPress:
            if event.matches(QKeySequence.StandardKey.Copy):
                message = self.current_message()
                if message and message.message_type == MessageType.TEXT and message.content:
                    selected_text = (
                        self._message_delegate.selected_text(message.content, message.message_id)
                        if self._message_delegate
                        else ""
                    )
                    QGuiApplication.clipboard().setText(selected_text or message.content)
                    return True

        return super().eventFilter(watched, event)

    def _sync_message_scrollbar_visibility(self) -> None:
        if not self._scroll_delegate:
            return
        hovered = (
            self.message_list.underMouse()
            or self.message_list.viewport().underMouse()
            or self._scroll_delegate.vScrollBar.underMouse()
        )
        self._scroll_delegate.vScrollBar.setForceHidden(not hovered)

    def _relayout_message_list(self) -> None:
        """Force message rows to recompute widths after viewport changes."""
        self.message_list.doItemsLayout()
        self.message_list.updateGeometries()
        self.message_list.viewport().update()

    def _remember_message_scroll_gap(self) -> None:
        """Remember the current distance between viewport and bottom of the chat list."""
        if self._restoring_message_view:
            return
        bar = self.message_list.verticalScrollBar()
        self._message_scroll_gap = max(0, bar.maximum() - bar.value())

    def _on_message_range_changed(self, _minimum: int, _maximum: int) -> None:
        """Track range changes so resizing keeps the same content in view."""
        if not self._restoring_message_view:
            self._schedule_restore_message_viewport()
        self._maybe_request_older_messages()

    def _on_message_scroll_value_changed(self, _value: int) -> None:
        """Check top-of-list pagination whenever the user scrolls."""
        self._maybe_request_older_messages()

    def _schedule_restore_message_viewport(self, *_args) -> None:
        """Restore chat viewport position after splitter moves or list resizes."""
        self._restore_message_viewport()
        QTimer.singleShot(0, self._restore_message_viewport)
        QTimer.singleShot(16, self._restore_message_viewport)

    def _run_restore_message_viewport(self) -> None:
        """Kept for compatibility with older queued restore hooks."""
        self._restore_message_viewport()

    def _restore_message_viewport(self) -> None:
        """Keep the same bottom gap visible after viewport size changes."""
        bar = self.message_list.verticalScrollBar()
        target = max(bar.minimum(), bar.maximum() - self._message_scroll_gap)
        self._restoring_message_view = True
        try:
            bar.setValue(target)
        finally:
            self._restoring_message_view = False

    def set_history_loading(self, loading: bool) -> None:
        """Track whether an older-history request is in flight."""
        self._history_request_pending = loading
        self._history_indicator.setVisible(loading and self.stack.currentWidget() is self.chat_page)
        if loading:
            self._position_history_indicator()

    def set_has_more_history(self, has_more: bool) -> None:
        """Record whether older history pages are still available."""
        self._has_more_history = has_more

    def _maybe_request_older_messages(self) -> None:
        """Request an older page when the user reaches the top of the list."""
        if (
            not self._message_model
            or self._history_request_pending
            or not self._has_more_history
            or self._restoring_message_view
            or self._message_model.rowCount() == 0
        ):
            return

        bar = self.message_list.verticalScrollBar()
        if bar.maximum() <= 0 or bar.value() > bar.minimum():
            return

        self._history_request_pending = True
        self.older_messages_requested.emit()

    def _position_history_indicator(self) -> None:
        """Keep the older-history loading hint centered at the top of the viewport."""
        if not hasattr(self, "_history_indicator"):
            return
        self._history_indicator.adjustSize()
        viewport = self.message_list.viewport()
        x = max(12, (viewport.width() - self._history_indicator.width()) // 2)
        self._history_indicator.move(x, 10)

    def current_message(self) -> Optional[ChatMessage]:
        """Return the currently selected message, if any."""
        index = self.message_list.currentIndex()
        if not index.isValid():
            return None
        message = index.data(Qt.ItemDataRole.UserRole)
        if not message or message.message_type == MessageType.SYSTEM:
            return None
        return message

    def get_selected_text(self, message: Optional[ChatMessage] = None) -> str:
        """Return the currently selected substring from a text bubble, if any."""
        message = message or self.current_message()
        if not message or message.message_type != MessageType.TEXT or not self._message_delegate:
            return ""
        return self._message_delegate.selected_text(message.content, message.message_id)

    def get_message_scroll_gap(self) -> int:
        """Return the current distance between viewport and bottom of the message list."""
        return max(0, self._message_scroll_gap)

    def is_near_bottom(self, threshold: int = 48) -> bool:
        """Return whether the message list is already close enough to the bottom."""
        bar = self.message_list.verticalScrollBar()
        if bar.maximum() <= 0:
            return True
        return max(0, bar.maximum() - bar.value()) <= max(0, threshold)

    def restore_message_scroll_gap(self, scroll_gap: int) -> None:
        """Restore a previously remembered bottom gap for this conversation."""
        self._message_scroll_gap = max(0, scroll_gap)
        self._schedule_restore_message_viewport()

    def _is_attachment_click(self, index, position) -> bool:
        """Return whether the click should trigger attachment preview/opening."""
        if not self._message_delegate:
            return False
        return self._message_delegate.is_attachment_hit(self.message_list, index, position)

    def handle_message_click(self, index) -> None:
        """Open image, file, or video attachments on click."""
        if not index.isValid():
            return

        message = index.data(Qt.ItemDataRole.UserRole)
        if not message:
            return

        if message.message_type == MessageType.IMAGE:
            from client.ui.widgets.image_viewer import ImageViewer

            image_source = message.extra.get("local_path") or message.content
            viewer = ImageViewer(image_source, self)
            viewer.exec()
            return

        if message.message_type == MessageType.VIDEO:
            self.open_video_message(message)
            return

        if message.message_type == MessageType.FILE:
            self.open_message_attachment(message)

    def open_message_attachment(self, message: ChatMessage) -> bool:
        """Open a file attachment with the system handler."""
        source = self._resolve_attachment_source(message)
        if not source:
            return False

        if os.path.exists(source):
            return QDesktopServices.openUrl(QUrl.fromLocalFile(source))

        return QDesktopServices.openUrl(QUrl(source))

    def open_video_message(self, message: ChatMessage) -> bool:
        """Open a video attachment in a top-level Fluent video widget."""
        source = self._resolve_attachment_source(message)
        if not source:
            return False

        url = QUrl(source) if source.startswith(("http://", "https://")) else QUrl.fromLocalFile(os.path.abspath(source))

        viewer = VideoWidget()
        viewer.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        viewer.setWindowFlag(Qt.WindowType.Window, True)
        viewer.setWindowTitle(
            (message.extra or {}).get("name")
            or os.path.basename((source or "").split("?", 1)[0])
            or tr("chat.video.player_title", "Video Playback")
        )
        viewer.resize(960, 540)
        viewer.setVideo(url)
        viewer.destroyed.connect(lambda *_args, widget=viewer: self._discard_video_window(widget))
        self._video_windows.append(viewer)
        viewer.show()
        viewer.play()
        return True

    def open_local_attachment(self, file_path: str, message_type: MessageType) -> bool:
        """Open a local attachment from the composer preview/editor."""
        if not file_path:
            return False

        if message_type == MessageType.IMAGE:
            from client.ui.widgets.image_viewer import ImageViewer

            viewer = ImageViewer(file_path, self)
            viewer.exec()
            return True

        if message_type == MessageType.VIDEO:
            message = ChatMessage(
                message_id="preview-video",
                session_id="",
                sender_id="",
                content=file_path,
                message_type=MessageType.VIDEO,
                extra={"local_path": file_path, "name": os.path.basename(file_path)},
            )
            return self.open_video_message(message)

        return QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))

    def _discard_video_window(self, widget: VideoWidget) -> None:
        """Drop closed top-level video widgets from the local cache."""
        self._video_windows = [item for item in self._video_windows if item is not widget]

    def _resolve_attachment_source(self, message: ChatMessage) -> str:
        """Resolve a local path or full URL for an attachment."""
        local_path = message.extra.get("local_path") if message.extra else None
        if local_path and os.path.exists(local_path):
            return local_path

        content = (message.extra.get("url") if message.extra else None) or (message.content or "").strip()
        if not content:
            return ""

        if os.path.exists(content):
            return content

        if content.startswith(("http://", "https://")):
            return content

        if content.startswith("/"):
            origin_base = get_config().server.origin_url.rstrip("/")
            return f"{origin_base}{content}"

        return content

    def show_typing_indicator(self) -> None:
        """Display typing status in header."""
        self.chat_header.set_status(tr("chat.status.typing", "The other side is typing..."))

    def hide_typing_indicator(self) -> None:
        """Clear typing status and restore session type label."""
        if self._current_session:
            self.chat_header.set_status(_session_status_text(self._current_session))
        else:
            self.chat_header.set_status("")

    def toggle_chat_info_drawer(self) -> None:
        """Toggle the floating chat info drawer for the current session."""
        if not self._current_session or not self._chat_info_overlay:
            return
        self._layout_chat_info_overlay()
        self._chat_info_overlay.set_session(self._current_session)
        self._chat_info_overlay.toggle()

    def close_chat_info_drawer(self, *, immediate: bool = False) -> None:
        """Hide the floating chat info drawer if it is visible."""
        if self._chat_info_overlay:
            self._chat_info_overlay.close_drawer(immediate=immediate)

    def _layout_chat_info_overlay(self) -> None:
        """Keep the floating chat info drawer aligned to the full right-side chat pane."""
        if not self._chat_info_overlay or not self.chat_page:
            return
        self._chat_info_overlay.set_content_geometry(self.chat_page.rect())
