"""Chat window container that keeps the new architecture but migrates old UI styling."""

from __future__ import annotations

import asyncio
import logging
import os
from collections import OrderedDict
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from qfluentwidgets import Action, InfoBar, PrimaryPushButton, PushButton, RoundMenu, SubtitleLabel, TextEdit

from client.core.i18n import tr
from client.events.event_bus import get_event_bus
from client.managers.message_manager import MessageEvent
from client.managers.session_manager import SessionEvent
from client.models.message import MessageStatus, MessageType, format_message_preview
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
        self.setWindowTitle(tr("chat.screenshot.preview_title", "Preview Screenshot"))
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


class EditMessageDialog(QDialog):
    """Dialog used to edit a text message."""

    def __init__(self, content: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("chat.edit.title", "Edit Message"))
        self.setModal(True)
        self.resize(420, 240)

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
        self._event_bus = get_event_bus()
        self._event_subscriptions: list[tuple[str, object]] = []
        self._screenshot_overlays: set[ScreenshotOverlay] = set()
        self._screenshot_dialogs: set[ScreenshotPreviewDialog] = set()
        self._oldest_loaded_timestamp: Optional[float] = None
        self._has_more_history = True
        self._history_load_task: Optional[asyncio.Task] = None
        self._history_page_cache: dict[str, OrderedDict[tuple[Optional[float], int], list]] = {}
        self._session_view_state: dict[str, dict] = {}
        self._last_read_receipts: dict[str, str] = {}
        self._pending_read_receipts: set[tuple[str, str]] = set()
        self._composer_drafts: dict[str, list[dict]] = {}
        self._ui_tasks: set[asyncio.Task] = set()

        self._setup_ui()
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
        self.chat_panel.composer_draft_changed.connect(self._on_composer_draft_changed)
        self.chat_panel.file_upload_requested.connect(self._on_file_upload_requested)
        self.chat_panel.screenshot_requested.connect(self._on_screenshot_requested)
        self.chat_panel.voice_call_requested.connect(self._on_voice_call_requested)
        self.chat_panel.video_call_requested.connect(self._on_video_call_requested)
        self.chat_panel.older_messages_requested.connect(self._on_older_messages_requested)
        self.chat_panel.get_message_list().customContextMenuRequested.connect(self._on_message_context_menu)

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        """Force both panes to re-layout item widths while the splitter is dragged."""
        QTimer.singleShot(0, self.session_panel._relayout_session_list)
        QTimer.singleShot(0, self.chat_panel._relayout_message_list)

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
            self.chat_panel.update_message_status(message.message_id, message.status)
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
            QTimer.singleShot(5000, self.chat_panel.hide_typing_indicator)

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
        self.session_panel.load_sessions(self._chat_controller.get_sessions())

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
        if cached_state:
            self._restore_session_view_state(session_id, cached_state)
            self._set_load_task(self._select_session_only(session_id), f"select session {session_id}")
        else:
            self._set_load_task(self._load_session_messages(session_id), f"load session {session_id}")

    async def _load_session_messages(self, session_id: str) -> None:
        """Load local messages for the selected session."""
        try:
            await self._chat_controller.select_session(session_id)
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

        messages = self._merge_loaded_messages_with_visible(messages)
        self.chat_panel.set_messages(messages)
        self._oldest_loaded_timestamp = self._extract_oldest_timestamp(messages)
        self._has_more_history = len(messages) >= self.MESSAGE_PAGE_SIZE and self._oldest_loaded_timestamp is not None
        self.chat_panel.set_has_more_history(self._has_more_history)
        self.chat_panel.set_history_loading(False)
        self._store_session_view_state(session_id)
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

    async def _send_file_message(self, session_id: str, file_path: str) -> None:
        """Upload and send a file via ChatController."""
        try:
            await self._chat_controller.send_file(file_path, session_id=session_id)
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
            copy_action = Action(tr("chat.context.copy", "Copy"), self)
            menu.addAction(copy_action)

        if message.message_type == MessageType.IMAGE:
            open_action = Action(tr("chat.context.open_image", "View Image"), self)
            menu.addAction(open_action)
        elif message.message_type in {MessageType.FILE, MessageType.VIDEO}:
            open_action = Action(tr("chat.context.open_attachment", "Open"), self)
            menu.addAction(open_action)

        if message.is_self and message.message_type == MessageType.TEXT and message.status != MessageStatus.RECALLED:
            edit_action = Action(tr("chat.context.edit", "Edit"), self)
            menu.addAction(edit_action)

        if message.is_self and message.status not in {MessageStatus.RECALLED, MessageStatus.FAILED}:
            recall_action = Action(tr("chat.context.recall", "Recall"), self)
            menu.addAction(recall_action)

        delete_action = Action(tr("common.delete", "Delete"), self)
        menu.addAction(delete_action)

        if message.is_self and message.status == MessageStatus.FAILED:
            retry_action = Action(tr("chat.context.retry", "Retry"), self)
            menu.addAction(retry_action)

        if copy_action:
            copy_action.triggered.connect(
                lambda _checked=False, msg=message: QGuiApplication.clipboard().setText(
                    self.chat_panel.get_selected_text(msg) or (msg.content or "")
                )
            )
        if open_action:
            open_action.triggered.connect(lambda _checked=False, msg=message: self._open_message(msg))
        if edit_action:
            edit_action.triggered.connect(lambda _checked=False, msg=message: self._prompt_edit_message(msg))
        if recall_action:
            recall_action.triggered.connect(
                lambda _checked=False, message_id=message.message_id: self._schedule_ui_task(
                    self._recall_message(message_id),
                    f"recall {message_id}",
                )
            )
        if delete_action:
            delete_action.triggered.connect(
                lambda _checked=False, msg=message: self._schedule_ui_task(
                    self._delete_message(msg),
                    f"delete {msg.message_id}",
                )
            )
        if retry_action:
            retry_action.triggered.connect(
                lambda _checked=False, message_id=message.message_id: self._schedule_ui_task(
                    self._retry_message(message_id),
                    f"retry {message_id}",
                )
            )

        menu.exec(self.chat_panel.get_message_list().viewport().mapToGlobal(position))

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
        if not session_id:
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

        session = await self._chat_controller.ensure_session_loaded(
            session_id,
            fallback_name="Session",
        )
        if not session:
            return False

        return self.focus_session(session.session_id)

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
