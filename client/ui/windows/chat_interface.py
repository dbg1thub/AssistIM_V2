"""Chat window container that keeps the new architecture but migrates old UI styling."""

from __future__ import annotations

import asyncio
import logging
import os
from collections import OrderedDict
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from qfluentwidgets import Action, InfoBar, PrimaryPushButton, PushButton, RoundMenu, SubtitleLabel, TextEdit

from client.events.event_bus import get_event_bus
from client.managers.message_manager import MessageEvent
from client.managers.session_manager import SessionEvent, get_session_manager
from client.models.message import MessageStatus, MessageType, Session, format_message_preview
from client.network.http_client import get_http_client
from client.ui.controllers.auth_controller import get_auth_controller
from client.ui.controllers.chat_controller import get_chat_controller
from client.ui.styles import StyleSheet
from client.ui.widgets.chat_panel import ChatPanel
from client.ui.widgets.fluent_splitter import FluentSplitter
from client.ui.widgets.screenshot_overlay import ScreenshotOverlay
from client.ui.widgets.session_panel import SessionPanel


logger = logging.getLogger(__name__)


class ScreenshotPreviewDialog(QDialog):
    """Preview a captured screenshot before sending it."""

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.setWindowTitle("Preview Screenshot")
        self.resize(760, 560)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setText("Unable to load screenshot")
        self.scroll_area.setWidget(self.image_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.cancel_button = PushButton("Cancel", self)
        self.confirm_button = PrimaryPushButton("Send", self)
        self.cancel_button.clicked.connect(self.reject)
        self.confirm_button.clicked.connect(self.accept)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.confirm_button)

        layout.addWidget(self.scroll_area, 1)
        layout.addLayout(button_row)

        pixmap = QPixmap(file_path)
        if not pixmap.isNull():
            self.image_label.setPixmap(pixmap)


class EditMessageDialog(QDialog):
    """Dialog used to edit a text message."""

    def __init__(self, content: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑消息")
        self.setModal(True)
        self.resize(420, 240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = SubtitleLabel("编辑消息", self)
        self.editor = TextEdit(self)
        self.editor.setPlainText(content)
        self.editor.setAcceptRichText(False)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        self.cancel_button = PushButton("取消", self)
        self.confirm_button = PrimaryPushButton("保存", self)

        self.cancel_button.clicked.connect(self.reject)
        self.confirm_button.clicked.connect(self._on_confirm)

        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.confirm_button)

        layout.addWidget(title)
        layout.addWidget(self.editor, 1)
        layout.addLayout(button_row)

    def _on_confirm(self) -> None:
        """Validate content before closing."""
        if self.get_content():
            self.accept()

    def get_content(self) -> str:
        """Return the trimmed editor content."""
        return self.editor.toPlainText().strip()


class ChatInterface(QWidget):
    """Main chat interface with session list on the left and chat view on the right."""

    SESSION_PANEL_WIDTH = 300
    MESSAGE_PAGE_SIZE = 50
    HISTORY_PAGE_CACHE_LIMIT = 12

    def __init__(self, parent=None):
        super().__init__(parent)

        self._chat_controller = get_chat_controller()
        self._current_session_id: Optional[str] = None
        self._load_task: Optional[asyncio.Task] = None
        self._session_manager = get_session_manager()
        self._event_bus = get_event_bus()
        self._screenshot_overlays: set[ScreenshotOverlay] = set()
        self._screenshot_dialogs: set[ScreenshotPreviewDialog] = set()
        self._oldest_loaded_timestamp: Optional[float] = None
        self._has_more_history = True
        self._history_load_task: Optional[asyncio.Task] = None
        self._history_page_cache: dict[str, OrderedDict[tuple[Optional[float], int], list]] = {}
        self._session_view_state: dict[str, dict] = {}

        self._setup_ui()
        self._connect_signals()
        self._subscribe_to_events()

    def _setup_ui(self) -> None:
        """Set up the two-column chat layout."""
        self.setObjectName("ChatInterface")

        self.splitter = FluentSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setObjectName("chatSplitter")

        self.session_panel = SessionPanel(self)
        self.chat_panel = ChatPanel(self)

        self.chat_panel.set_send_message_callback(self._on_send_message)
        self.chat_panel.set_send_segments_callback(self._on_send_segments)
        self.chat_panel.set_send_typing_callback(self._on_send_typing)

        self.splitter.addWidget(self.session_panel)
        self.splitter.addWidget(self.chat_panel)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setSizes([self.SESSION_PANEL_WIDTH, 760])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setHandleWidth(1)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.splitter)
        StyleSheet.CHAT_INTERFACE.apply(self)

    def _connect_signals(self) -> None:
        """Connect panel-level signals."""
        self.session_panel.session_selected.connect(self._on_session_selected)
        self.chat_panel.file_upload_requested.connect(self._on_file_upload_requested)
        self.chat_panel.screenshot_requested.connect(self._on_screenshot_requested)
        self.chat_panel.voice_call_requested.connect(self._on_voice_call_requested)
        self.chat_panel.video_call_requested.connect(self._on_video_call_requested)
        self.chat_panel.older_messages_requested.connect(self._on_older_messages_requested)
        self.chat_panel.get_message_list().customContextMenuRequested.connect(self._on_message_context_menu)

    def _subscribe_to_events(self) -> None:
        """Subscribe to session and message events for real-time UI updates."""
        self._event_bus.subscribe_sync(SessionEvent.CREATED, self._on_session_event)
        self._event_bus.subscribe_sync(SessionEvent.UPDATED, self._on_session_event)
        self._event_bus.subscribe_sync(SessionEvent.DELETED, self._on_session_event)

        self._event_bus.subscribe_sync(MessageEvent.SENT, self._on_message_sent)
        self._event_bus.subscribe_sync(MessageEvent.RECEIVED, self._on_message_received)
        self._event_bus.subscribe_sync(MessageEvent.ACK, self._on_message_ack)
        self._event_bus.subscribe_sync(MessageEvent.FAILED, self._on_message_failed)
        self._event_bus.subscribe_sync(MessageEvent.TYPING, self._on_typing_event)
        self._event_bus.subscribe_sync(MessageEvent.READ, self._on_read_event)
        self._event_bus.subscribe_sync(MessageEvent.EDITED, self._on_edited_event)
        self._event_bus.subscribe_sync(MessageEvent.RECALLED, self._on_recalled_event)
        self._event_bus.subscribe_sync(MessageEvent.DELETED, self._on_deleted_event)
        self._event_bus.subscribe_sync(MessageEvent.SYNC_COMPLETED, self._on_sync_completed)

    def _on_session_event(self, data: dict) -> None:
        """React to session lifecycle updates."""
        is_delete_event = (
            data.get("session_id") == self._current_session_id
            and "session" not in data
            and "sessions" not in data
        )
        if is_delete_event:
            self._current_session_id = None
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
            self._invalidate_history_cache(message.session_id)
        if message and message.session_id == self._current_session_id:
            self.chat_panel.add_message(message)

    def _on_message_received(self, data: dict) -> None:
        """Append received message to the current conversation."""
        message = data.get("message")
        if message:
            self._invalidate_history_cache(message.session_id)
        if message and message.session_id == self._current_session_id:
            self.chat_panel.add_message(message)

    def _on_message_ack(self, data: dict) -> None:
        """Update message status after server acknowledgment."""
        message = data.get("message")
        message_id = data.get("message_id")
        if message and message.session_id == self._current_session_id:
            self.chat_panel.update_message_status(message.message_id, message.status)
        elif message_id:
            self.chat_panel.update_message_status(message_id, MessageStatus.SENT)

    def _on_message_failed(self, data: dict) -> None:
        """Update failed message state."""
        message = data.get("message")
        if message:
            self._invalidate_history_cache(message.session_id)
        if message and message.session_id == self._current_session_id:
            self.chat_panel.add_message(message)
            self.chat_panel.update_message_status(message.message_id, MessageStatus.FAILED)

    def _on_typing_event(self, data: dict) -> None:
        """Show typing indicator for the active conversation only."""
        session_id = data.get("session_id", "")
        if session_id == self._current_session_id:
            self.chat_panel.show_typing_indicator()
            QTimer.singleShot(5000, self.chat_panel.hide_typing_indicator)

    def _on_read_event(self, data: dict) -> None:
        """Update read state in the message list."""
        message_id = data.get("message_id", "")
        if message_id:
            self.chat_panel.update_message_status(message_id, MessageStatus.READ)

    def _on_edited_event(self, data: dict) -> None:
        """Update edited message content."""
        session_id = data.get("session_id", "")
        self._invalidate_history_cache(session_id)
        if session_id != self._current_session_id:
            return
        self.chat_panel.update_message_content(data.get("message_id", ""), data.get("content", ""))
        self.chat_panel.update_message_status(data.get("message_id", ""), MessageStatus.EDITED)
        asyncio.create_task(self._refresh_session_preview(session_id))

    def _on_recalled_event(self, data: dict) -> None:
        """Replace recalled message content."""
        session_id = data.get("session_id", "")
        self._invalidate_history_cache(session_id)
        if session_id != self._current_session_id:
            asyncio.create_task(self._refresh_session_preview(session_id))
            return
        message_id = data.get("message_id", "")
        self.chat_panel.update_message_content(message_id, "[消息已撤回]")
        self.chat_panel.update_message_status(message_id, MessageStatus.RECALLED)
        asyncio.create_task(self._refresh_session_preview(session_id))

    def _on_deleted_event(self, data: dict) -> None:
        """Remove a deleted message and refresh session preview."""
        session_id = data.get("session_id", "")
        self._invalidate_history_cache(session_id)
        if session_id == self._current_session_id:
            self.chat_panel.remove_message(data.get("message_id", ""))
        asyncio.create_task(self._refresh_session_preview(session_id))

    def _on_sync_completed(self, data: dict) -> None:
        """Append synced history messages for the currently open session only."""
        messages = data.get("messages") or []
        for message in messages:
            session_id = getattr(message, "session_id", None)
            if session_id:
                self._invalidate_history_cache(session_id)

        if not self._current_session_id:
            return

        current_session_messages = [
            message
            for message in messages
            if getattr(message, "session_id", None) == self._current_session_id
        ]
        if current_session_messages:
            self.chat_panel.add_messages(current_session_messages)

    def load_sessions(self) -> None:
        """Load current sessions into the left panel."""
        self.session_panel.load_sessions_from_manager()

    def _on_session_selected(self, session_id: str) -> None:
        """Handle user selecting a conversation."""
        if session_id == self._current_session_id:
            return

        self._remember_current_session_view_state()

        self._current_session_id = session_id
        session = self._get_session(session_id)
        if session:
            self.chat_panel.set_session(session)
        else:
            self.chat_panel.show_welcome()
            return

        self.chat_panel.clear_messages()
        self.chat_panel.set_has_more_history(True)
        self.chat_panel.set_history_loading(False)
        self._oldest_loaded_timestamp = None
        self._has_more_history = True

        if self._load_task and not self._load_task.done():
            self._load_task.cancel()
        if self._history_load_task and not self._history_load_task.done():
            self._history_load_task.cancel()

        cached_state = self._session_view_state.get(session_id)
        if cached_state:
            self._restore_session_view_state(session_id, cached_state)
            self._load_task = asyncio.create_task(self._select_session_only(session_id))
        else:
            self._load_task = asyncio.create_task(self._load_session_messages(session_id))

    async def _load_session_messages(self, session_id: str) -> None:
        """Load local messages for the selected session."""
        try:
            await self._chat_controller.select_session(session_id)
            messages = await self._load_history_page(session_id, before_timestamp=None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Failed to load messages for %s: %s", session_id, exc)
            return

        if session_id != self._current_session_id:
            return

        self.chat_panel.set_messages(messages)
        self._oldest_loaded_timestamp = self._extract_oldest_timestamp(messages)
        self._has_more_history = len(messages) >= self.MESSAGE_PAGE_SIZE and self._oldest_loaded_timestamp is not None
        self.chat_panel.set_has_more_history(self._has_more_history)
        self.chat_panel.set_history_loading(False)
        self._store_session_view_state(session_id)

    async def _select_session_only(self, session_id: str) -> None:
        """Update session selection side effects without reloading the visible page from storage."""
        try:
            await self._chat_controller.select_session(session_id)
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

        self._history_load_task = asyncio.create_task(self._load_older_messages(self._current_session_id))

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

    async def _load_history_page(self, session_id: str, before_timestamp: Optional[float]) -> list:
        """Load one history page, reusing cached local pages when available."""
        cache = self._history_page_cache.setdefault(session_id, OrderedDict())
        cache_key = (before_timestamp, self.MESSAGE_PAGE_SIZE)
        cached_page = cache.get(cache_key)
        if cached_page is not None:
            cache.move_to_end(cache_key)
            return list(cached_page)

        messages = await self._chat_controller.load_messages(
            session_id,
            limit=self.MESSAGE_PAGE_SIZE,
            before_timestamp=before_timestamp,
        )
        cache[cache_key] = list(messages)
        while len(cache) > self.HISTORY_PAGE_CACHE_LIMIT:
            cache.popitem(last=False)
        return messages

    def _invalidate_history_cache(self, session_id: Optional[str] = None) -> None:
        """Drop cached local history pages when a session receives updates."""
        if session_id:
            self._history_page_cache.pop(session_id, None)
        else:
            self._history_page_cache.clear()

    def _remember_current_session_view_state(self) -> None:
        """Persist the current visible message slice and scroll gap for the active session."""
        if not self._current_session_id:
            return
        self._store_session_view_state(self._current_session_id)

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

    def _on_send_message(self, content: str, message_type: MessageType) -> None:
        """Dispatch outgoing messages through ChatController."""
        if not self._current_session_id:
            return

        if message_type == MessageType.IMAGE:
            asyncio.create_task(self._send_image_message(content))
        else:
            asyncio.create_task(self._send_text_message(content, message_type))

    def _on_send_segments(self, segments: list[dict]) -> None:
        """Dispatch mixed text/media segments in document order."""
        if not self._current_session_id or not segments:
            return
        asyncio.create_task(self._send_segments_async(segments))

    async def _send_segments_async(self, segments: list[dict]) -> None:
        """Send composed editor segments sequentially so mixed content keeps order."""
        for segment in segments:
            segment_type = segment.get("type")
            try:
                if segment_type == MessageType.TEXT and segment.get("content"):
                    await self._chat_controller.send_message_to(
                        session_id=self._current_session_id,
                        content=segment["content"],
                        message_type=MessageType.TEXT,
                    )
                elif segment_type in {MessageType.IMAGE, MessageType.VIDEO, MessageType.FILE} and segment.get("file_path"):
                    await self._chat_controller.send_file(segment["file_path"])
            except Exception as exc:
                logger.error("Send composed segment error: %s", exc)

    async def _send_text_message(self, content: str, message_type: MessageType) -> None:
        """Send a text message through the controller."""
        try:
            await self._chat_controller.send_message_to(
                session_id=self._current_session_id,
                content=content,
                message_type=message_type,
            )
        except Exception as exc:
            logger.error("Send text message error: %s", exc)

    async def _send_image_message(self, file_path: str) -> None:
        """Send an image using the optimistic media upload flow."""
        try:
            message = await self._chat_controller.send_file(file_path)
            if message:
                self.chat_panel.get_message_list().viewport().update()
        except Exception as exc:
            logger.error("Send image message error: %s", exc)

    def _on_send_typing(self) -> None:
        """Send typing indicator in background."""
        if self._current_session_id:
            asyncio.create_task(self._chat_controller.send_typing())

    def _on_file_upload_requested(self, file_path: str) -> None:
        """Send file message in background."""
        if not self._current_session_id:
            return
        asyncio.create_task(self._send_file_message(file_path))

    def _on_screenshot_requested(self) -> None:
        """Open the screenshot overlay and send the result as an image."""
        if not self._current_session_id:
            InfoBar.warning("Chat", "Select a conversation before sending a screenshot.", parent=self.window(), duration=2000)
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
            InfoBar.error("Screenshot", "Unable to open the captured screenshot.", parent=self.window(), duration=2000)
            return

        dialog = ScreenshotPreviewDialog(file_path, self.window())
        self._screenshot_dialogs.add(dialog)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                asyncio.create_task(self._send_image_message(file_path))
            else:
                try:
                    os.remove(file_path)
                except OSError:
                    logger.debug("Failed to remove canceled screenshot preview: %s", file_path, exc_info=True)
        finally:
            self._screenshot_dialogs.discard(dialog)

    def _on_voice_call_requested(self) -> None:
        """Show placeholder feedback for voice calls."""
        InfoBar.info("Voice Call", "Voice calling is not connected yet.", parent=self.window(), duration=1800)

    def _on_video_call_requested(self) -> None:
        """Show placeholder feedback for video calls."""
        InfoBar.info("Video Call", "Video calling is not connected yet.", parent=self.window(), duration=1800)

    async def _send_file_message(self, file_path: str) -> None:
        """Upload and send a file via ChatController."""
        try:
            await self._chat_controller.send_file(file_path)
        except Exception as exc:
            logger.error("Send file message error: %s", exc)

    def _on_message_context_menu(self, position) -> None:
        """Show message actions for the clicked bubble."""
        message = self.chat_panel.get_message_at(position)
        if not message:
            return

        menu = RoundMenu(parent=self)
        copy_action = None
        open_action = None
        edit_action = None
        recall_action = None
        delete_action = None
        retry_action = None

        if message.message_type == MessageType.TEXT and message.content:
            copy_action = Action("复制", self)
            menu.addAction(copy_action)

        if message.message_type == MessageType.IMAGE:
            open_action = Action("查看图片", self)
            menu.addAction(open_action)
        elif message.message_type in {MessageType.FILE, MessageType.VIDEO}:
            open_action = Action("打开", self)
            menu.addAction(open_action)

        if message.is_self and message.message_type == MessageType.TEXT and message.status != MessageStatus.RECALLED:
            edit_action = Action("编辑", self)
            menu.addAction(edit_action)

        if message.is_self and message.status not in {MessageStatus.RECALLED, MessageStatus.FAILED}:
            recall_action = Action("撤回", self)
            menu.addAction(recall_action)

        if message.is_self:
            delete_action = Action("删除", self)
            menu.addAction(delete_action)

        if message.is_self and message.status == MessageStatus.FAILED:
            retry_action = Action("重发", self)
            menu.addAction(retry_action)

        action = menu.exec(self.chat_panel.get_message_list().viewport().mapToGlobal(position))
        if action is None:
            return

        if action == open_action:
            self._open_message(message)
            return

        if action == copy_action:
            selected_text = self.chat_panel.get_selected_text(message)
            QGuiApplication.clipboard().setText(selected_text or (message.content or ""))
            return

        if action == edit_action:
            self._prompt_edit_message(message)
            return

        if action == recall_action:
            asyncio.create_task(self._recall_message(message.message_id))
            return

        if action == delete_action:
            asyncio.create_task(self._delete_message(message))
            return

        if action == retry_action:
            asyncio.create_task(self._retry_message(message.message_id))

    def _open_message(self, message) -> None:
        """Open an image, file, or video attachment."""
        if message.message_type == MessageType.IMAGE:
            from client.ui.widgets.image_viewer import ImageViewer

            viewer = ImageViewer(message.extra.get("local_path") or message.content, self)
            viewer.exec()
            return

        if message.message_type == MessageType.VIDEO:
            if not self.chat_panel.open_video_message(message):
                InfoBar.warning("消息", "无法播放这个视频", parent=self.window(), duration=1800)
            return

        if message.message_type == MessageType.FILE:
            if not self.chat_panel.open_message_attachment(message):
                InfoBar.warning("消息", "无法打开这个附件", parent=self.window(), duration=1800)

    def _prompt_edit_message(self, message) -> None:
        """Open the edit dialog for a text message."""
        dialog = EditMessageDialog(message.content, self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        new_content = dialog.get_content()
        if not new_content:
            InfoBar.warning("编辑消息", "内容不能为空", parent=self.window(), duration=1800)
            return
        if new_content == message.content:
            return

        asyncio.create_task(self._edit_message(message.message_id, new_content))

    async def _retry_message(self, message_id: str) -> None:
        """Retry a failed message."""
        success = await self._chat_controller.retry_message(message_id)
        if not success:
            InfoBar.error("消息", "重发失败", parent=self.window(), duration=1800)

    async def _recall_message(self, message_id: str) -> None:
        """Recall a message and surface errors in the UI."""
        success, reason = await self._chat_controller.recall_message(message_id)
        if not success:
            InfoBar.error("Message", reason or "Recall failed", parent=self.window(), duration=2400)

    async def _edit_message(self, message_id: str, new_content: str) -> None:
        """Edit a message and surface errors in the UI."""
        success = await self._chat_controller.edit_message(message_id, new_content)
        if not success:
            InfoBar.error("编辑消息", "编辑失败", parent=self.window(), duration=1800)

    async def _delete_message(self, message) -> None:
        """Delete a message and refresh session preview state."""
        success = await self._chat_controller.delete_message(message.message_id)
        if not success:
            InfoBar.error("消息", "删除失败", parent=self.window(), duration=1800)
            return

        self.chat_panel.remove_message(message.message_id)
        await self._refresh_session_preview(message.session_id)

    async def _refresh_session_preview(self, session_id: str) -> None:
        """Refresh session preview content from the latest local message."""
        from client.storage.database import get_database

        session = self._get_session(session_id)
        if not session:
            return

        db = get_database()
        if not db.is_connected:
            return

        last_message = await db.get_last_message(session_id)
        preview = format_message_preview(last_message.content, last_message.message_type) if last_message else ""
        preview_time = last_message.timestamp if last_message else session.updated_at
        extra = dict(session.extra)
        if last_message:
            extra["last_message_type"] = last_message.message_type.value
        else:
            extra.pop("last_message_type", None)

        await self._session_manager.update_session(
            session_id,
            last_message=preview,
            last_message_time=preview_time,
            extra=extra,
        )

    def _get_session(self, session_id: str):
        """Find session object by ID."""
        for session in self._session_manager.sessions:
            if session.session_id == session_id:
                return session
        return None

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

    async def open_group_session(self, session_id: str) -> bool:
        """Open a group session, fetching it from the backend if needed."""
        if self.focus_session(session_id):
            return True

        session = await self._fetch_remote_session(session_id)
        if not session:
            return False

        await self._remember_session(session)
        return self.focus_session(session.session_id)

    async def open_direct_session(self, user_id: str, display_name: str = "", avatar: str = "") -> bool:
        """Open an existing direct session or create one for the given contact."""
        session = self._find_direct_session(user_id)
        if session:
            return self.focus_session(session.session_id)

        try:
            payload = await get_http_client().post(
                "/sessions",
                json={
                    "type": "private",
                    "user_id": user_id,
                    "name": display_name or "Private Chat",
                },
            )
        except Exception as exc:
            logger.error("Create direct session error: %s", exc)
            return False

        session = self._build_session_from_payload(payload, fallback_name=display_name or "Private Chat", avatar=avatar)
        if not session:
            return False

        await self._remember_session(session)
        return self.focus_session(session.session_id)

    def _find_direct_session(self, user_id: str) -> Optional[Session]:
        """Find a cached direct session by participant ID."""
        for session in self._session_manager.sessions:
            if session.is_ai_session or session.session_type == "group":
                continue
            if user_id in session.participant_ids:
                return session
        return None

    async def _fetch_remote_session(self, session_id: str) -> Optional[Session]:
        """Fetch a session payload from the backend and normalize it."""
        try:
            payload = await get_http_client().get(f"/sessions/{session_id}")
        except Exception as exc:
            logger.error("Fetch session %s error: %s", session_id, exc)
            return None
        return self._build_session_from_payload(payload, fallback_name="Session")

    def _build_session_from_payload(
        self,
        payload: Optional[dict],
        fallback_name: str,
        avatar: str = "",
    ) -> Optional[Session]:
        """Normalize backend payload into a Session model."""
        if not payload:
            return None

        data = dict(payload)
        data.setdefault("session_id", data.get("id", ""))
        data.setdefault("name", fallback_name)
        session_type = str(data.get("session_type") or data.get("type") or "direct")
        if session_type == "private":
            session_type = "direct"
        data["session_type"] = session_type

        if session_type != "group" and not data.get("is_ai_session"):
            current_user = (get_auth_controller().current_user or {})
            current_user_id = str(current_user.get("id", "") or "")
            counterpart_name = self._resolve_counterpart_name(
                data.get("members") or [],
                current_user_id,
            )
            if counterpart_name:
                data["name"] = counterpart_name

        if avatar and not data.get("avatar"):
            data["avatar"] = avatar

        try:
            session = Session.from_dict(data)
        except Exception as exc:
            logger.error("Normalize session payload error: %s", exc)
            return None

        session.extra["members"] = data.get("members") or []
        return session

    @staticmethod
    def _resolve_counterpart_name(members: list[dict], current_user_id: str) -> str:
        """Resolve the other member's display name for direct sessions."""
        for member in members:
            member_id = str(member.get("id", "") or "")
            if current_user_id and member_id == current_user_id:
                continue
            return (
                str(member.get("nickname", "") or "")
                or str(member.get("username", "") or "")
                or member_id
            )
        return ""

    async def _remember_session(self, session: Session) -> None:
        """Insert a fetched session into the manager and local database."""
        existing = self._get_session(session.session_id)
        if not existing:
            await self._session_manager.add_session(session)

        try:
            from client.storage.database import get_database

            db = get_database()
            if db.is_connected:
                await db.save_session(session)
        except Exception as exc:
            logger.warning("Persist session %s failed: %s", session.session_id, exc)
