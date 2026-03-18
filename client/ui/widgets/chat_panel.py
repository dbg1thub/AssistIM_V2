"""Right-side chat panel with welcome page, header, message list, and composer."""

from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import QEvent, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import QAbstractItemView, QFrame, QListView, QStackedWidget, QVBoxLayout, QWidget

from qfluentwidgets import BodyLabel, CaptionLabel, FluentIcon, IconWidget

from client.core.config_backend import get_config
from client.delegates.message_delegate import MessageDelegate
from client.models.message import ChatMessage, MessageType, Session
from client.models.message_model import MessageModel
from client.ui.styles import StyleSheet
from client.ui.widgets.chat_header import ChatHeader
from client.ui.widgets.fluent_splitter import FluentSplitter
from client.ui.widgets.message_input import MessageInput


class WelcomeWidget(QWidget):
    """Welcome screen shown before any session is selected."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chatWelcomeWidget")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.icon = IconWidget(FluentIcon.CHAT, self)
        self.icon.setFixedSize(88, 88)

        self.title_label = BodyLabel("欢迎使用 AssistIM", self)
        self.subtitle_label = CaptionLabel("从左侧选择一个会话，继续消息同步、文件传输和 AI 辅助聊天。", self)
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

    message_sent = Signal(str)
    file_upload_requested = Signal(str)
    screenshot_requested = Signal()
    voice_call_requested = Signal()
    video_call_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._message_model: Optional[MessageModel] = None
        self._message_delegate: Optional[MessageDelegate] = None
        self._send_message_callback: Optional[Callable] = None
        self._send_typing_callback: Optional[Callable] = None
        self._current_session: Optional[Session] = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Create stacked welcome page and active chat page."""
        self.setObjectName("ChatPanel")

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
        self.message_list.setFrameShape(QFrame.Shape.NoFrame)
        self.message_list.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.message_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.message_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.message_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.message_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.message_list.setSpacing(0)
        self.message_list.setMouseTracking(True)
        self.message_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.message_list.installEventFilter(self)
        self.message_list.viewport().installEventFilter(self)

        self._setup_message_model()

        self.message_input = MessageInput(self.chat_page)
        self.message_input.send_clicked.connect(self._on_send_message)
        self.message_input.image_selected.connect(self._on_image_selected)
        self.message_input.file_selected.connect(self._on_file_selected)
        self.message_input.screenshot_requested.connect(self.screenshot_requested.emit)
        self.message_input.voice_call_requested.connect(self.voice_call_requested.emit)
        self.message_input.video_call_requested.connect(self.video_call_requested.emit)
        self.message_input.typing_signal.connect(self._on_typing)

        self.content_splitter = FluentSplitter(Qt.Orientation.Vertical, self.chat_page)
        self.content_splitter.setObjectName("chatContentSplitter")
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(1)
        self.message_list.setMinimumHeight(180)
        self.content_splitter.addWidget(self.message_list)
        self.content_splitter.addWidget(self.message_input)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 0)
        self.content_splitter.setSizes([560, 220])

        self.chat_layout.addWidget(self.chat_header, 0)
        self.chat_layout.addWidget(self.content_splitter, 1)

        self.stack.addWidget(self.welcome_widget)
        self.stack.addWidget(self.chat_page)
        self.main_layout.addWidget(self.stack)

        self.show_welcome()
        StyleSheet.CHAT_PANEL.apply(self)

    def _setup_message_model(self) -> None:
        """Set up the model/delegate pair used by the message list."""
        self._message_model = MessageModel(self)
        self._message_delegate = MessageDelegate(self)
        self.message_list.setModel(self._message_model)
        self.message_list.setItemDelegate(self._message_delegate)

    def show_welcome(self) -> None:
        """Show welcome page and disable input."""
        self._current_session = None
        self.stack.setCurrentWidget(self.welcome_widget)
        self.message_input.set_session_active(False)

    def show_chat(self) -> None:
        """Show active chat page and enable input."""
        self.stack.setCurrentWidget(self.chat_page)
        self.message_input.set_session_active(True)
        self.message_input.focus_editor()

    def set_session(self, session: Session) -> None:
        """Update header and switch to active chat page."""
        self._current_session = session
        status = "AI 会话" if session.is_ai_session else f"{'群聊' if session.session_type == 'group' else '私聊'}"
        self.chat_header.set_session_info(
            title=session.name,
            status=status,
            avatar=session.avatar,
            is_ai=session.is_ai_session,
        )
        self.show_chat()

    def clear_messages(self) -> None:
        """Clear visible messages from the model."""
        if self._message_model:
            self._message_model.clear()

    def _on_send_message(self, text: str) -> None:
        """Forward text send request."""
        if self._send_message_callback:
            self._send_message_callback(text, MessageType.TEXT)
        self.message_sent.emit(text)

    def _on_image_selected(self, file_path: str) -> None:
        """Forward image selection to the outside callback."""
        if self._send_message_callback:
            self._send_message_callback(file_path, MessageType.IMAGE)

    def _on_file_selected(self, file_path: str) -> None:
        """Forward file selection to upload handler."""
        self.file_upload_requested.emit(file_path)

    def _on_typing(self) -> None:
        """Emit typing signal through external callback."""
        if self._send_typing_callback:
            self._send_typing_callback()

    def set_send_message_callback(self, callback: Callable[[str, MessageType], None]) -> None:
        """Set message send callback."""
        self._send_message_callback = callback

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

    def get_message_delegate(self) -> MessageDelegate:
        """Return message delegate."""
        return self._message_delegate

    def add_message(self, message: ChatMessage) -> None:
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
            self._message_model.refresh_message(message.message_id)
            self.message_list.viewport().update()
            return

        self._message_model.add_message(message)
        self.message_list.scrollToBottom()

    def update_message_status(self, message_id: str, status) -> None:
        """Update message status in model."""
        if self._message_model:
            self._message_model.update_message_status(message_id, status)

    def update_message_content(self, message_id: str, content: str) -> None:
        """Update message content in model."""
        if self._message_model:
            self._message_model.update_message_content(message_id, content)

    def remove_message(self, message_id: str) -> None:
        """Remove a message from the model."""
        if self._message_model:
            self._message_model.remove_message(message_id)

    def get_message_at(self, position) -> Optional[ChatMessage]:
        """Return the message under a viewport position."""
        index = self.message_list.indexAt(position)
        if not index.isValid():
            return None
        return index.data(Qt.ItemDataRole.UserRole)

    def eventFilter(self, watched, event) -> bool:
        """Only open attachments when the click lands inside the rendered content area."""
        if watched is self.message_list.viewport():
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                position = event.position().toPoint() if hasattr(event, "position") else event.pos()
                index = self.message_list.indexAt(position)
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
                if index.isValid() and self._is_attachment_click(index, position):
                    self.handle_message_click(index)
                    return True

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

    def current_message(self) -> Optional[ChatMessage]:
        """Return the currently selected message, if any."""
        index = self.message_list.currentIndex()
        if not index.isValid():
            return None
        return index.data(Qt.ItemDataRole.UserRole)

    def get_selected_text(self, message: Optional[ChatMessage] = None) -> str:
        """Return the currently selected substring from a text bubble, if any."""
        message = message or self.current_message()
        if not message or message.message_type != MessageType.TEXT or not self._message_delegate:
            return ""
        return self._message_delegate.selected_text(message.content, message.message_id)

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

        if message.message_type in {MessageType.FILE, MessageType.VIDEO}:
            self.open_message_attachment(message)

    def open_message_attachment(self, message: ChatMessage) -> bool:
        """Open a file or video attachment with the system handler."""
        source = self._resolve_attachment_source(message)
        if not source:
            return False

        if os.path.exists(source):
            return QDesktopServices.openUrl(QUrl.fromLocalFile(source))

        return QDesktopServices.openUrl(QUrl(source))

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
            api_base = get_config().server.api_base_url.rstrip("/")
            host_base = api_base[:-4] if api_base.endswith("/api") else api_base
            return f"{host_base}{content}"

        return content

    def show_typing_indicator(self) -> None:
        """Display typing status in header."""
        self.chat_header.set_status("对方正在输入...")

    def hide_typing_indicator(self) -> None:
        """Clear typing status and restore session type label."""
        if self._current_session:
            status = "AI 会话" if self._current_session.is_ai_session else (
                "群聊" if self._current_session.session_type == "group" else "私聊"
            )
            self.chat_header.set_status(status)
        else:
            self.chat_header.set_status("")
