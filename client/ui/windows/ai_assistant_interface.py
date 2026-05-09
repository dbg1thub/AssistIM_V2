"""Standalone local AI assistant page with thread list and streaming chat."""

from __future__ import annotations

import asyncio
import mimetypes
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeyEvent, QPixmap, QRegion
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    IconWidget,
    MessageBoxBase,
    Action,
    MenuAnimationType,
    PrimaryPushButton,
    RoundMenu,
    ScrollBarHandleDisplayMode,
    SubtitleLabel,
    TabBar,
    TabCloseButtonDisplayMode,
    TransparentToolButton,
    isDarkTheme,
    themeColor,
)
from qfluentwidgets.components.widgets.scroll_bar import SmoothScrollDelegate

from client.core import logging
from client.core.app_icons import AppIcon, CollectionIcon
from client.core.i18n import tr
from client.delegates.ai_assistant_message_delegate import AIAssistantMessageDelegate
from client.events.event_bus import get_event_bus
from client.managers.ai_action_permission_policy import AIPermissionScope
from client.managers.ai_action_workflow import AIActionWorkflow
from client.managers.ai_prompt_builder import AIPromptBuilder
from client.managers.ai_task_manager import AITaskEvent, AITaskSnapshot, AITaskState, get_ai_task_manager
from client.managers.conversation_memory_manager import ConversationMemoryContext, ConversationMemoryManager
from client.models.ai_assistant import AIMessage, AIMessageRole, AIMessageStatus, AIThread
from client.models.ai_assistant_message_model import AIAssistantMessageModel
from client.services.ai_service import AIErrorCode
from client.services.local_embedding_gguf_runtime import LocalEmbeddingGGUFRuntimeError
from client.storage.ai_assistant_store import get_ai_assistant_store

logger = logging.get_logger(__name__)

SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _attachment_display_name(attachment: dict | None) -> str:
    if not attachment:
        return ""
    name = str(attachment.get("name") or "").strip()
    if name:
        return name
    path = str(attachment.get("local_path") or "").strip()
    return Path(path).name if path else ""


class AIAssistantPromptEdit(QTextEdit):
    """Prompt editor that sends on Enter and inserts a newline on Shift+Enter."""

    submitted = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            event.accept()
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class DeleteAIThreadConfirmDialog(MessageBoxBase):
    """Ask for confirmation before deleting one local AI assistant thread."""

    def __init__(self, thread_title: str, parent=None):
        super().__init__(parent=parent)
        display_name = str(thread_title or "").strip() or tr("ai_assistant.thread.new", "New Chat")
        title = SubtitleLabel(tr("ai_assistant.delete.confirm_title", "Delete Chat"), self.widget)
        content = BodyLabel(
            tr(
                "ai_assistant.delete.confirm_content",
                "Delete {name} and remove its local AI messages from this device?",
                name=display_name,
            ),
            self.widget,
        )
        content.setWordWrap(True)
        self.viewLayout.addWidget(title)
        self.viewLayout.addWidget(content)
        self.viewLayout.addStretch(1)
        self.yesButton.setText(tr("ai_assistant.delete.confirm_action", "Delete"))
        self.cancelButton.setText(tr("common.cancel", "Cancel"))
        self.widget.setMinimumWidth(380)


class AIAssistantComposerControlsOverlay(QWidget):
    """Transparent in-composer overlay that only accepts events on its buttons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiAssistantComposerControlsOverlay")
        self.setMouseTracking(True)

        self.attachment_button = TransparentToolButton(AppIcon.ADD, self)
        self.attachment_button.setObjectName("aiAssistantAttachmentButton")
        self.attachment_button.setFixedSize(32, 32)
        self.attachment_button.setEnabled(True)
        self.attachment_button.setToolTip(tr("ai_assistant.attachment.add", "Add image"))

        self.send_button = PrimaryPushButton(tr("common.send", "Send"), self)
        self.send_button.setObjectName("aiAssistantSendButton")
        self.send_button.setIcon(AppIcon.SEND_FILL.icon())
        self.send_button.setFixedSize(84, 34)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update_overlay_layout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.update_overlay_layout()

    def update_overlay_layout(self) -> None:
        bounds = self.rect()
        if not bounds.isValid():
            return

        left_margin = 12
        right_margin = 14
        bottom_margin = 12
        attach_x = bounds.left() + left_margin
        attach_y = bounds.bottom() - self.attachment_button.height() - bottom_margin + 1
        send_x = bounds.right() - self.send_button.width() - right_margin + 1
        send_y = bounds.bottom() - self.send_button.height() - bottom_margin + 1

        self.attachment_button.move(attach_x, max(bounds.top(), attach_y))
        self.send_button.move(max(bounds.left(), send_x), max(bounds.top(), send_y))
        self.attachment_button.raise_()
        self.send_button.raise_()

        region = QRegion(self.attachment_button.geometry()).united(QRegion(self.send_button.geometry()))
        self.setMask(region)


class AIAssistantPendingAttachmentPreview(QFrame):
    """Compact image preview shown above the assistant composer."""

    removed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiAssistantPendingAttachmentPreview")
        self.setFixedHeight(58)

        self.preview_layout = QHBoxLayout(self)
        self.preview_layout.setContentsMargins(12, 7, 12, 7)
        self.preview_layout.setSpacing(10)

        self.thumbnail_label = QLabel(self)
        self.thumbnail_label.setObjectName("aiAssistantPendingAttachmentThumbnail")
        self.thumbnail_label.setFixedSize(44, 44)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.name_label = CaptionLabel(self)
        self.name_label.setObjectName("aiAssistantPendingAttachmentName")
        self.name_label.setMinimumWidth(0)
        self.name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self.remove_button = TransparentToolButton(AppIcon.CLOSE, self)
        self.remove_button.setObjectName("aiAssistantPendingAttachmentRemove")
        self.remove_button.setFixedSize(28, 28)
        self.remove_button.setToolTip(tr("ai_assistant.attachment.remove", "Remove image"))
        self.remove_button.clicked.connect(self.removed.emit)

        self.preview_layout.addWidget(self.thumbnail_label)
        self.preview_layout.addWidget(self.name_label, 1)
        self.preview_layout.addWidget(self.remove_button)
        self.hide()

    def set_attachment(self, attachment: dict | None) -> None:
        if not attachment:
            self.thumbnail_label.clear()
            self.name_label.clear()
            self.hide()
            return

        path = str(attachment.get("local_path") or "").strip()
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            self.thumbnail_label.setPixmap(
                pixmap.scaled(
                    QSize(44, 44),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self.thumbnail_label.clear()
        self.name_label.setText(_attachment_display_name(attachment) or tr("ai_assistant.attachment.image", "Image"))
        self.show()


class AIAssistantFloatingComposerOverlay(QWidget):
    """Transparent layer that floats the composer above the message area."""

    HORIZONTAL_MARGIN = 28
    BOTTOM_MARGIN = 28
    MIN_COMPOSER_WIDTH = 280

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiAssistantFloatingComposerOverlay")
        self.setMouseTracking(True)
        self.composer: QWidget | None = None

    def set_composer(self, composer: QWidget) -> None:
        self.composer = composer
        composer.setParent(self)
        self.update_overlay_layout()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update_overlay_layout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.update_overlay_layout()

    def update_overlay_layout(self) -> None:
        if self.composer is None:
            return
        bounds = self.rect()
        if not bounds.isValid():
            return

        available_width = max(self.MIN_COMPOSER_WIDTH, bounds.width() - self.HORIZONTAL_MARGIN * 2)
        composer_width = min(self.composer.maximumWidth(), available_width)
        composer_width = max(self.MIN_COMPOSER_WIDTH, composer_width)
        composer_height = self.composer.height() or self.composer.sizeHint().height()
        composer_x = bounds.left() + (bounds.width() - composer_width) // 2
        composer_y = bounds.bottom() - composer_height - self.BOTTOM_MARGIN + 1
        composer_y = max(bounds.top(), composer_y)

        self.composer.setGeometry(composer_x, composer_y, composer_width, composer_height)
        self.composer.raise_()
        self.setMask(QRegion(self.composer.geometry()))


class AIAssistantInterface(QWidget):
    """Top-level navigation page for local AI assistant threads."""

    MAX_CONTEXT_MESSAGES = 80
    COMPOSER_HEIGHT = 140
    INPUT_SAFE_AREA_HEIGHT = 196
    MESSAGE_BOTTOM_MARGIN = 26

    def __init__(self, parent=None, *, owner_user_id: str):
        super().__init__(parent)
        self.setObjectName("AIAssistantInterface")
        self._owner_user_id = str(owner_user_id or "").strip()
        if not self._owner_user_id:
            raise ValueError("AIAssistantInterface requires owner_user_id")
        self._store = get_ai_assistant_store(self._owner_user_id)
        self._task_manager = get_ai_task_manager()
        self._prompt_builder = AIPromptBuilder()
        self._memory_manager = ConversationMemoryManager()
        self._action_workflow = AIActionWorkflow(
            memory_manager=self._memory_manager,
            permission_scope_provider=self._current_action_permission_scope,
        )
        self._event_bus = get_event_bus()
        self._ui_tasks: set[asyncio.Task] = set()
        self._event_subscriptions: list[tuple[str, object]] = []
        self._initialized = False
        self._teardown_started = False
        self._threads: list[AIThread] = []
        self._current_thread_id = ""
        self._messages: list[AIMessage] = []
        self._message_model: AIAssistantMessageModel | None = None
        self._message_delegate: AIAssistantMessageDelegate | None = None
        self._message_context_menu: RoundMenu | None = None
        self._active_task_id = ""
        self._active_assistant_message: AIMessage | None = None
        self._active_stream_task: asyncio.Task | None = None
        self._active_action_plan_id = ""
        self._active_action_message: AIMessage | None = None
        self._active_action_task: asyncio.Task | None = None
        self._last_persist_at = 0.0
        self._applying_theme = False
        self._scroll_delegate: SmoothScrollDelegate | None = None
        self._is_generating = False
        self._pending_image_attachment: dict | None = None
        self._thinking_animation_frame = 0
        self._thinking_animation_timer = QTimer(self)
        self._thinking_animation_timer.setInterval(420)
        self._thinking_animation_timer.timeout.connect(self._advance_thinking_animation)

        self._setup_ui()
        self._subscribe_to_events()
        self.destroyed.connect(self._on_destroyed)

    def _current_action_permission_scope(self) -> AIPermissionScope:
        return AIPermissionScope(allow_e2ee_plaintext=True)

    def _setup_ui(self) -> None:
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.content_panel = QFrame(self)
        self.content_panel.setObjectName("aiAssistantContentPanel")
        self.content_layout = QVBoxLayout(self.content_panel)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        self.header = QFrame(self.content_panel)
        self.header.setObjectName("aiAssistantHeader")
        self.header_layout = QHBoxLayout(self.header)
        self.header_layout.setContentsMargins(16, 6, 16, 6)
        self.header_layout.setSpacing(12)

        self.title_label = BodyLabel(tr("ai_assistant.thread.new", "New Chat"), self.header)
        self.title_label.setObjectName("aiAssistantThreadTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title_label.hide()

        self.thread_tab_bar = TabBar(self.header)
        self.thread_tab_bar.setObjectName("aiAssistantThreadTabBar")
        self.thread_tab_bar.setTabMaximumWidth(220)
        self.thread_tab_bar.setMovable(True)
        self.thread_tab_bar.setScrollable(True)
        self.thread_tab_bar.setTabShadowEnabled(True)
        self.thread_tab_bar.setCloseButtonDisplayMode(TabCloseButtonDisplayMode.ON_HOVER)
        self.thread_tab_bar.tabAddRequested.connect(self._on_new_thread_clicked)
        self.thread_tab_bar.tabCloseRequested.connect(self._on_thread_tab_close_requested)

        self.header_layout.addWidget(self.thread_tab_bar, 1, Qt.AlignmentFlag.AlignVCenter)

        self.message_list = QListView(self.content_panel)
        self.message_list.setObjectName("aiAssistantMessageList")
        self.message_list.viewport().setObjectName("aiAssistantMessageViewport")
        self.message_list.setFrameShape(QFrame.Shape.NoFrame)
        self.message_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.message_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.message_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.message_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.message_list.setLayoutMode(QListView.LayoutMode.SinglePass)
        self.message_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.message_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.message_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.message_list.setSpacing(0)
        self.message_list.setMouseTracking(True)
        self._message_model = AIAssistantMessageModel(self.message_list)
        self._message_delegate = AIAssistantMessageDelegate(self.message_list)
        self.message_list.setModel(self._message_model)
        self.message_list.setItemDelegate(self._message_delegate)
        self._scroll_delegate = SmoothScrollDelegate(self.message_list)
        self._scroll_delegate.vScrollBar.setHandleDisplayMode(ScrollBarHandleDisplayMode.ALWAYS)
        self._scroll_delegate.hScrollBar.setForceHidden(True)
        self._scroll_delegate.vScrollBar.setForceHidden(True)
        self.message_list.installEventFilter(self)
        self.message_list.viewport().installEventFilter(self)
        self.message_list.verticalScrollBar().installEventFilter(self)
        self._scroll_delegate.vScrollBar.installEventFilter(self)
        self.message_list.verticalScrollBar().valueChanged.connect(self._sync_scroll_to_bottom_button)
        self.message_list.verticalScrollBar().rangeChanged.connect(self._sync_scroll_to_bottom_button)
        self.message_list.customContextMenuRequested.connect(self._on_message_context_menu)

        self.empty_widget = QFrame(self.content_panel)
        self.empty_widget.setObjectName("aiAssistantEmpty")
        self.empty_layout = QVBoxLayout(self.empty_widget)
        self.empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_layout.setSpacing(12)
        self.empty_icon = IconWidget(AppIcon.ROBOT, self.empty_widget)
        self.empty_icon.setFixedSize(64, 64)
        self.empty_title = BodyLabel(tr("ai_assistant.empty.title", "Ask the local AI assistant"), self.empty_widget)
        self.empty_subtitle = CaptionLabel(
            tr("ai_assistant.empty.subtitle", "Start a thread on the left or type a question below."),
            self.empty_widget,
        )
        self.empty_subtitle.setWordWrap(True)
        self.empty_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_subtitle.setMaximumWidth(420)
        self.empty_layout.addWidget(self.empty_icon, 0, Qt.AlignmentFlag.AlignCenter)
        self.empty_layout.addWidget(self.empty_title, 0, Qt.AlignmentFlag.AlignCenter)
        self.empty_layout.addWidget(self.empty_subtitle, 0, Qt.AlignmentFlag.AlignCenter)

        self.input_safe_area = QFrame(self.content_panel)
        self.input_safe_area.setObjectName("aiAssistantInputSafeArea")
        self.input_safe_area.setFixedHeight(self.INPUT_SAFE_AREA_HEIGHT)

        self.composer_overlay = AIAssistantFloatingComposerOverlay(self.content_panel)
        self.composer_overlay.setObjectName("aiAssistantFloatingComposerOverlay")

        self.composer_shell = QFrame(self.composer_overlay)
        self.composer_shell.setObjectName("aiAssistantComposerShell")
        self.composer_shell.setMaximumWidth(1100)
        self.composer_shell.setMinimumWidth(320)
        self.composer_shell.setFixedHeight(self.COMPOSER_HEIGHT)
        self.composer_shell_layout = QVBoxLayout(self.composer_shell)
        self.composer_shell_layout.setContentsMargins(0, 0, 0, 0)
        self.composer_shell_layout.setSpacing(0)

        self.pending_attachment_preview = AIAssistantPendingAttachmentPreview(self.composer_shell)
        self.pending_attachment_preview.removed.connect(self._clear_pending_attachment)

        self.prompt_edit = AIAssistantPromptEdit(self.composer_shell)
        self.prompt_edit.setObjectName("aiAssistantPromptEdit")
        self.prompt_edit.viewport().setObjectName("aiAssistantPromptViewport")
        self.prompt_edit.setPlaceholderText(tr("ai_assistant.input.placeholder", "Message AssistIM AI..."))
        self.prompt_edit.setFixedHeight(self.COMPOSER_HEIGHT)
        self.prompt_edit.setViewportMargins(0, 0, 96, 48)
        self.prompt_edit.submitted.connect(self._on_send_clicked)
        self.composer_controls_overlay = AIAssistantComposerControlsOverlay(self.composer_shell)
        self.attachment_button = self.composer_controls_overlay.attachment_button
        self.send_button = self.composer_controls_overlay.send_button
        self.attachment_button.clicked.connect(self._on_attachment_clicked)
        self.send_button.clicked.connect(self._on_send_clicked)
        self.composer_shell_layout.addWidget(self.pending_attachment_preview)
        self.composer_shell_layout.addWidget(self.prompt_edit, 1)
        self.composer_overlay.set_composer(self.composer_shell)
        self.composer_shell.installEventFilter(self)
        self.prompt_edit.installEventFilter(self)
        self.composer_controls_overlay.installEventFilter(self)

        self.content_layout.addWidget(self.header)
        self.content_layout.addWidget(self.empty_widget, 1)
        self.content_layout.addWidget(self.message_list, 1)
        self.content_layout.addWidget(self.input_safe_area)
        self.message_list.hide()

        self.scroll_to_bottom_button = PrimaryPushButton(
            tr("ai_assistant.scroll_to_bottom", "Scroll to bottom"),
            self.content_panel,
        )
        self.scroll_to_bottom_button.setObjectName("aiAssistantScrollToBottomButton")
        self.scroll_to_bottom_button.setIcon(CollectionIcon("arrow_down").icon())
        self.scroll_to_bottom_button.setFixedHeight(34)
        self.scroll_to_bottom_button.hide()
        self.scroll_to_bottom_button.clicked.connect(self._on_scroll_to_bottom_clicked)

        self.main_layout.addWidget(self.content_panel, 1)
        self._apply_theme()
        self._set_generating(False)

    def ensure_initial_load(self) -> None:
        """Schedule initial local AI assistant thread loading."""
        if self._initialized or self._teardown_started:
            return
        self._initialized = True
        self._create_ui_task(self._ensure_initial_load_async(), "load AI assistant threads")

    async def _ensure_initial_load_async(self) -> None:
        """Load local AI assistant threads once the authenticated shell is ready."""
        try:
            await self._store.initialize()
            await self._action_workflow.recover_interrupted_plans()
            await self._reload_threads(select_first=True)
        except Exception:
            self._initialized = False
            raise

    def _subscribe_to_events(self) -> None:
        for event_name in (AITaskEvent.UPDATED, AITaskEvent.FINISHED, AITaskEvent.FAILED, AITaskEvent.CANCELLED):
            self._event_bus.subscribe_sync(event_name, self._on_ai_task_event)
            self._event_subscriptions.append((event_name, self._on_ai_task_event))

    def _unsubscribe_from_events(self) -> None:
        while self._event_subscriptions:
            event_name, handler = self._event_subscriptions.pop()
            self._event_bus.unsubscribe_sync(event_name, handler)

    def _on_destroyed(self, *_args) -> None:
        self.quiesce()

    def quiesce(self) -> None:
        """Stop UI-owned async work during shell teardown."""
        if self._teardown_started:
            return
        self._teardown_started = True
        self._unsubscribe_from_events()
        cancel_task = None
        cancel_action_task = None
        if self._active_task_id:
            cancel_task = self._create_ui_task(
                self._task_manager.cancel(self._active_task_id),
                "cancel AI assistant task on teardown",
            )
        if self._active_action_plan_id:
            cancel_action_task = self._create_ui_task(
                self._action_workflow.cancel_plan(self._active_action_plan_id),
                "cancel AI assistant action on teardown",
            )
        for task in list(self._ui_tasks):
            if task not in {cancel_task, cancel_action_task} and not task.done():
                task.cancel()

    def _create_ui_task(self, coro, context: str, *, on_done=None) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._ui_tasks.add(task)

        def _done(finished: asyncio.Task) -> None:
            self._ui_tasks.discard(finished)
            try:
                finished.result()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("AI assistant UI task failed: %s", context)
            if on_done is not None:
                on_done(finished)

        task.add_done_callback(_done)
        return task

    def _on_new_thread_clicked(self) -> None:
        self._create_ui_task(self._create_and_select_thread(), "create AI assistant thread")

    async def _create_and_select_thread(self) -> None:
        await self._stop_active_generation()
        thread = await self._store.create_thread(model="")
        await self._reload_threads(select_thread_id=thread.thread_id)

    def rename_current_thread(self, title: str) -> asyncio.Task | None:
        """Schedule one rename for the current assistant thread without exposing a UI entry here."""
        if not self._current_thread_id:
            return None
        return self._create_ui_task(
            self.rename_thread(self._current_thread_id, title),
            f"rename AI assistant thread {self._current_thread_id}",
        )

    async def rename_thread(self, thread_id: str, title: str) -> AIThread | None:
        """Rename one assistant thread and refresh local thread/header state."""
        normalized_thread_id = str(thread_id or "").strip()
        if not normalized_thread_id:
            return None
        updated = await self._store.update_thread_title(normalized_thread_id, title)
        if updated is None:
            return None
        self._threads = await self._store.list_threads()
        if normalized_thread_id == self._current_thread_id:
            self.title_label.setText(updated.title or tr("ai_assistant.thread.new", "New Chat"))
        self._render_thread_tabs()
        return updated

    def regenerate_current_thread(self) -> asyncio.Task | None:
        """Schedule one regenerate for the current assistant thread without exposing a UI entry here."""
        if not self._current_thread_id:
            return None
        return self._create_ui_task(
            self._regenerate_last(),
            f"regenerate AI assistant thread {self._current_thread_id}",
        )

    def _on_thread_tab_clicked(self, thread_id: str) -> None:
        thread_id = str(thread_id or "").strip()
        if thread_id and thread_id != self._current_thread_id:
            self._create_ui_task(self._select_thread(thread_id), f"select AI assistant thread {thread_id}")

    async def _reload_threads(self, *, select_first: bool = False, select_thread_id: str = "") -> None:
        self._threads = await self._store.list_threads()
        if not self._threads:
            self._threads = [await self._store.create_thread()]
        self._render_thread_tabs()
        target_id = select_thread_id or (self._threads[0].thread_id if select_first and self._threads else "")
        if target_id:
            await self._select_thread(target_id, stop_generation=False)

    async def _select_thread(self, thread_id: str, *, stop_generation: bool = True) -> None:
        if stop_generation:
            await self._stop_active_generation()
        thread = await self._store.get_thread(thread_id)
        if thread is None:
            await self._reload_threads(select_first=True)
            return
        self._current_thread_id = thread.thread_id
        self.title_label.setText(thread.title or tr("ai_assistant.thread.new", "New Chat"))
        self._messages = await self._store.list_messages(thread.thread_id, limit=self.MAX_CONTEXT_MESSAGES)
        self._render_thread_tabs()
        self._render_messages()
        self._set_generating(bool(self._active_task_id or self._active_action_plan_id))
        self.prompt_edit.setFocus()

    def _render_thread_tabs(self) -> None:
        self.thread_tab_bar.blockSignals(True)
        self.thread_tab_bar.clear()
        for thread in self._threads:
            preview = str(thread.last_message or "").strip()
            title = str(thread.title or tr("ai_assistant.thread.new", "New Chat")).strip()
            tooltip = title if not preview else f"{title}\n{preview}"
            tab = self.thread_tab_bar.addTab(
                routeKey=thread.thread_id,
                text=title,
                onClick=lambda thread_id=thread.thread_id: self._on_thread_tab_clicked(thread_id),
            )
            tab.setToolTip(tooltip)
        if self._current_thread_id:
            self.thread_tab_bar.setCurrentTab(self._current_thread_id)
        self.thread_tab_bar.blockSignals(False)

    def _render_messages(self) -> None:
        if self._message_model is not None:
            self._message_model.set_messages(self._messages)
        if not self._messages:
            self.message_list.hide()
            self.empty_widget.show()
            QTimer.singleShot(0, self._update_input_overlay_positions)
            return
        self.empty_widget.hide()
        self.message_list.show()
        if self._message_delegate is not None:
            self._message_delegate.clear_text_selection(self.message_list)
        QTimer.singleShot(0, self._update_input_overlay_positions)
        self._scroll_to_bottom()

    def _append_message(self, message: AIMessage) -> None:
        self._messages.append(message)
        if self.empty_widget.isVisible():
            self.empty_widget.hide()
            self.message_list.show()
        if self._message_model is not None:
            self._message_model.add_message(message)
        self._scroll_to_bottom()

    def _update_message_card(self, message: AIMessage) -> None:
        should_follow = self._is_generating and self._is_scroll_at_bottom()
        if self._message_model is not None:
            self._message_model.update_message(message)
        if self._message_delegate is not None:
            self.message_list.doItemsLayout()
            self.message_list.viewport().update()
        if should_follow:
            self._scroll_to_bottom()
        else:
            self._schedule_single_shot(self._sync_scroll_to_bottom_button)

    def _on_attachment_clicked(self) -> None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self.window(),
            tr("ai_assistant.attachment.open_title", "Select image"),
            "",
            tr("ai_assistant.attachment.open_filter", "Images (*.png *.jpg *.jpeg *.webp *.bmp)"),
        )
        if not file_path:
            return
        attachment = self._build_image_attachment(file_path)
        if attachment is None:
            return
        self._pending_image_attachment = attachment
        self._sync_pending_attachment_preview()

    def _on_action_message_requested(self, message_id: str, command: str) -> None:
        self._create_ui_task(
            self._continue_action_from_message(message_id, command),
            f"continue AI action {message_id}",
        )

    async def _continue_action_from_message(self, message_id: str, command: str) -> None:
        normalized_message_id = str(message_id or "").strip()
        normalized_command = str(command or "").strip()
        message = next((item for item in self._messages if item.message_id == normalized_message_id), None)
        if message is None:
            return
        if self._message_delegate is not None:
            self._message_delegate.set_action_message_enabled(self.message_list, normalized_message_id, False)

        async def on_action_progress(progress_result) -> None:
            await self._upsert_action_progress_message(
                message.thread_id,
                progress_result,
                message,
            )

        action_result = await self._action_workflow.handle_pending_control(
            thread_id=message.thread_id,
            control_type=normalized_command,
            progress_callback=on_action_progress,
        )
        if not action_result.handled:
            if self._message_delegate is not None:
                self._message_delegate.set_action_message_enabled(self.message_list, normalized_message_id, True)
            return
        if action_result.memory_context_lines:
            await self._handle_action_turn_result(
                message.thread_id,
                action_result,
                context_messages=list(self._messages),
                assistant_message=message,
            )
            return
        await self._complete_pending_assistant_message(
            message,
            action_result.response_text,
            extra=action_result.message_extra,
        )

    def _build_image_attachment(self, file_path: str) -> dict | None:
        path = Path(file_path).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
            return None
        mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        return {
            "type": "image",
            "local_path": str(path),
            "mime_type": mime_type,
            "name": path.name,
            "size_bytes": path.stat().st_size,
        }

    def _clear_pending_attachment(self) -> None:
        self._pending_image_attachment = None
        self._sync_pending_attachment_preview()

    def _sync_pending_attachment_preview(self) -> None:
        attachment = self._pending_image_attachment
        self.pending_attachment_preview.set_attachment(attachment)
        extra_height = self.pending_attachment_preview.height() + 6 if attachment else 0
        self.composer_shell.setFixedHeight(self.COMPOSER_HEIGHT + extra_height)
        self.input_safe_area.setFixedHeight(self.INPUT_SAFE_AREA_HEIGHT + extra_height)
        self._update_input_overlay_positions()

    def _on_send_clicked(self) -> None:
        if self._active_task_id or self._active_action_plan_id or self._is_generating:
            self._create_ui_task(self._stop_active_generation(), "stop AI assistant generation from send button")
            return
        text = self.prompt_edit.toPlainText().strip()
        attachment = dict(self._pending_image_attachment or {})
        if not text and attachment:
            text = tr(
                "ai_assistant.attachment.default_prompt",
                "请描述这张图片，并说明你能观察到的关键信息。",
            )
        if not text:
            return
        self.prompt_edit.clear()
        self._pending_image_attachment = None
        self._sync_pending_attachment_preview()
        attachments = [attachment] if attachment else []
        self._create_ui_task(self._send_prompt(text, attachments=attachments), "send AI assistant prompt")

    async def _send_prompt(self, text: str, *, attachments: list[dict] | None = None) -> None:
        if not self._current_thread_id:
            thread = await self._store.create_thread()
            await self._reload_threads(select_thread_id=thread.thread_id)
        if self._active_task_id:
            await self._stop_active_generation()

        thread_id = self._current_thread_id
        user_message = await self._store.create_message(
            thread_id=thread_id,
            role=AIMessageRole.USER,
            content=text,
            status=AIMessageStatus.DONE,
            extra={"attachments": list(attachments or [])} if attachments else None,
        )
        self._append_message(user_message)
        await self._store.maybe_title_from_first_user_message(thread_id, text)
        await self._reload_threads(select_thread_id=thread_id)

        context_messages = list(self._messages)
        assistant_message = await self._store.create_message(
            thread_id=thread_id,
            role=AIMessageRole.ASSISTANT,
            content="",
            status=AIMessageStatus.PENDING,
            extra={"ai_thinking": {"state": "planning"}},
        )
        self._append_message(assistant_message)
        self._set_generating(True)
        action_message: AIMessage | None = assistant_message

        async def on_action_progress(progress_result) -> None:
            nonlocal action_message
            action_message = await self._upsert_action_progress_message(
                thread_id,
                progress_result,
                action_message,
            )

        action_result = await self._action_workflow.handle_user_turn(
            thread_id=thread_id,
            text=text,
            has_attachments=bool(attachments),
            progress_callback=on_action_progress,
        )
        if action_result.handled:
            await self._handle_action_turn_result(
                thread_id,
                action_result,
                context_messages=context_messages,
                assistant_message=action_message,
            )
            return

        assistant_message.content = ""
        assistant_message.status = AIMessageStatus.PENDING
        assistant_message.task_id = ""
        assistant_message.extra = {"ai_thinking": {"state": "generating"}}

        task_id = f"ai-chat-{uuid.uuid4()}"
        await self._store.update_message(
            assistant_message,
            status=AIMessageStatus.STREAMING,
            task_id=task_id,
            extra=assistant_message.extra,
        )
        assistant_message.status = AIMessageStatus.STREAMING
        assistant_message.task_id = task_id
        self._update_message_card(assistant_message)

        context_messages = [message for message in self._messages if message.message_id != assistant_message.message_id]
        rag_history_messages = [
            message
            for message in context_messages
            if message.message_id != user_message.message_id
        ]
        memory_context = ConversationMemoryContext(lines=(), query_kind="")
        try:
            if not attachments:
                memory_context = await self._memory_manager.build_rag_context_for_ai_chat(
                    text,
                    previous_messages=rag_history_messages,
                )
        except Exception as exc:
            logger.exception("AI assistant failed to build local RAG context")
            await self._fail_pending_assistant_message(assistant_message, self._rag_error_text(exc))
            return
        if memory_context.requires_confirmation:
            await self._complete_pending_assistant_message(
                assistant_message,
                memory_context.confirmation_prompt,
                extra={"memory_confirmation": {"query": memory_context.pending_query_text or text}},
            )
            return
        request = self._prompt_builder.build_ai_chat_request(
            thread_id,
            context_messages,
            task_id=task_id,
            memory_context_lines=memory_context.lines,
        )
        self._active_task_id = request.task_id
        self._active_assistant_message = assistant_message
        self._last_persist_at = 0.0
        self._active_stream_task = self._create_ui_task(self._run_stream(request), f"AI assistant stream {request.task_id}")

    async def _upsert_action_progress_message(
        self,
        thread_id: str,
        action_result,
        assistant_message: AIMessage | None,
    ) -> AIMessage:
        extra = dict(action_result.message_extra or {})
        content = str(action_result.response_text or "").strip()
        action = dict(extra.get("ai_action") or {})
        state = str(action.get("state") or "").strip()
        plan_id = str(action.get("plan_id") or action.get("id") or "").strip()
        if assistant_message is None:
            message = await self._store.create_message(
                thread_id=thread_id,
                role=AIMessageRole.ASSISTANT,
                content=content,
                status=AIMessageStatus.PENDING,
                extra=extra,
            )
            self._append_message(message)
            self._sync_active_action_progress(message, plan_id=plan_id, state=state)
            return message

        if content:
            assistant_message.content = content
        assistant_message.status = AIMessageStatus.PENDING
        assistant_message.task_id = ""
        assistant_message.extra = extra
        await self._persist_assistant_message(assistant_message)
        self._update_message_card(assistant_message)
        self._sync_active_action_progress(assistant_message, plan_id=plan_id, state=state)
        return assistant_message

    def _sync_active_action_progress(self, message: AIMessage, *, plan_id: str, state: str) -> None:
        if state == "running" and plan_id:
            self._active_action_plan_id = plan_id
            self._active_action_message = message
            self._active_action_task = asyncio.current_task()
            self._set_generating(True)
            return
        if plan_id and plan_id == self._active_action_plan_id:
            self._clear_active_action()
            self._set_generating(bool(self._active_task_id or self._active_action_plan_id))

    def _clear_active_action(self) -> None:
        self._active_action_plan_id = ""
        self._active_action_message = None
        self._active_action_task = None

    async def _run_stream(self, request) -> None:
        snapshot = await self._task_manager.stream(request)
        await self._finalize_snapshot(snapshot)

    async def _handle_action_turn_result(
        self,
        thread_id: str,
        action_result,
        *,
        context_messages: list[AIMessage],
        assistant_message: AIMessage | None = None,
    ) -> None:
        if not action_result.memory_context_lines:
            if assistant_message is not None:
                await self._complete_pending_assistant_message(
                    assistant_message,
                    action_result.response_text,
                    extra=action_result.message_extra,
                )
                return
            assistant_message = await self._store.create_message(
                thread_id=thread_id,
                role=AIMessageRole.ASSISTANT,
                content=action_result.response_text,
                status=AIMessageStatus.DONE,
                extra=action_result.message_extra,
            )
            self._append_message(assistant_message)
            self._threads = await self._store.list_threads()
            self._render_thread_tabs()
            return

        if assistant_message is None:
            assistant_message = await self._store.create_message(
                thread_id=thread_id,
                role=AIMessageRole.ASSISTANT,
                content=action_result.response_text,
                status=AIMessageStatus.PENDING,
                extra=action_result.message_extra,
            )
            self._append_message(assistant_message)
        else:
            assistant_message.content = str(action_result.response_text or "").strip()
            assistant_message.status = AIMessageStatus.PENDING
            assistant_message.task_id = ""
            assistant_message.extra = dict(action_result.message_extra or {})
            await self._persist_assistant_message(assistant_message)
            self._update_message_card(assistant_message)
        self._set_generating(True)

        task_id = f"ai-chat-{uuid.uuid4()}"
        await self._store.update_message(
            assistant_message,
            status=AIMessageStatus.STREAMING,
            task_id=task_id,
            extra=action_result.message_extra,
        )
        assistant_message.status = AIMessageStatus.STREAMING
        assistant_message.task_id = task_id
        assistant_message.extra = dict(action_result.message_extra or {})
        self._update_message_card(assistant_message)

        request = self._prompt_builder.build_ai_chat_request(
            thread_id,
            context_messages,
            task_id=task_id,
            memory_context_lines=action_result.memory_context_lines,
        )
        self._active_task_id = request.task_id
        self._active_assistant_message = assistant_message
        self._last_persist_at = 0.0
        self._active_stream_task = self._create_ui_task(self._run_stream(request), f"AI assistant action stream {request.task_id}")

    def _on_ai_task_event(self, data: object) -> None:
        if not isinstance(data, dict):
            return
        task = data.get("task")
        if not isinstance(task, AITaskSnapshot):
            return
        if task.task_id != self._active_task_id:
            return
        if self._active_assistant_message is None:
            return
        self._active_assistant_message.content = str(task.content or "")
        self._active_assistant_message.model = str(task.model or "")
        if task.state == AITaskState.RUNNING:
            self._active_assistant_message.status = AIMessageStatus.STREAMING
        elif task.state == AITaskState.CANCELLED:
            self._active_assistant_message.status = AIMessageStatus.CANCELLED
        elif task.state == AITaskState.FAILED:
            self._active_assistant_message.status = AIMessageStatus.FAILED
        elif task.state == AITaskState.DONE:
            self._active_assistant_message.status = AIMessageStatus.DONE
        self._update_message_card(self._active_assistant_message)
        now = time.monotonic()
        if now - self._last_persist_at >= 0.25 or task.state in {
            AITaskState.DONE,
            AITaskState.FAILED,
            AITaskState.CANCELLED,
        }:
            self._last_persist_at = now
            self._create_ui_task(
                self._persist_assistant_message(self._active_assistant_message),
                f"persist AI assistant message {self._active_assistant_message.message_id}",
            )

    async def _persist_assistant_message(self, message: AIMessage) -> None:
        await self._store.update_message(
            message,
            content=message.content,
            status=message.status,
            model=message.model,
            task_id=message.task_id,
            extra=message.extra,
        )
        self._threads = await self._store.list_threads()
        self._render_thread_tabs()

    async def _finalize_snapshot(self, snapshot: AITaskSnapshot) -> None:
        if snapshot.task_id != self._active_task_id or self._active_assistant_message is None:
            return
        status = AIMessageStatus.DONE
        content = str(snapshot.content or "")
        message_extra = dict(self._active_assistant_message.extra or {})
        if snapshot.state == AITaskState.CANCELLED:
            status = AIMessageStatus.CANCELLED
            if not content.strip():
                content = tr("ai_assistant.message.cancelled", "已停止生成。")
        elif snapshot.state == AITaskState.FAILED:
            status = AIMessageStatus.FAILED
            if not content:
                content = self._error_text(snapshot.error_code)
        if bool(snapshot.truncated):
            message_extra["truncated"] = True
        else:
            message_extra.pop("truncated", None)
        message_extra.pop("ai_thinking", None)
        self._active_assistant_message.content = content
        self._active_assistant_message.status = status
        self._active_assistant_message.model = str(snapshot.model or "")
        self._active_assistant_message.extra = message_extra
        await self._action_workflow.finish_streamed_action(
            message_extra,
            content=content,
            status=status.value,
        )
        await self._persist_assistant_message(self._active_assistant_message)
        self._update_message_card(self._active_assistant_message)
        self._active_task_id = ""
        self._active_assistant_message = None
        self._active_stream_task = None
        self._set_generating(False)

    def _error_text(self, error_code: AIErrorCode | None) -> str:
        if error_code == AIErrorCode.AI_CONTEXT_TOO_LONG:
            return tr("ai_assistant.error.context_too_long", "The conversation is too long. Start a new chat or clear context.")
        if error_code == AIErrorCode.AI_MODEL_NOT_FOUND:
            return tr("ai_assistant.error.model_missing", "Local AI model was not found.")
        if error_code == AIErrorCode.AI_VISION_PROJECTOR_NOT_FOUND:
            return tr("ai_assistant.error.vision_projector_missing", "Vision projector file was not found.")
        if error_code in {AIErrorCode.AI_MODEL_VISION_UNSUPPORTED, AIErrorCode.AI_VISION_RUNTIME_UNAVAILABLE}:
            return tr("ai_assistant.error.vision_unavailable", "The current local AI model cannot read images.")
        return tr("ai_assistant.error.failed", "AI could not complete this request.")

    def _on_stop_clicked(self) -> None:
        self._create_ui_task(self._stop_active_generation(), "stop AI assistant generation")

    async def _stop_active_generation(self) -> None:
        action_plan_id = self._active_action_plan_id
        action_message = self._active_action_message
        action_task = self._active_action_task
        if action_plan_id:
            action_result = await self._action_workflow.cancel_plan(action_plan_id)
            if action_result.handled and action_message is not None:
                await self._complete_pending_assistant_message(
                    action_message,
                    action_result.response_text,
                    extra=action_result.message_extra,
                )
            self._clear_active_action()
            if action_task is not None and action_task is not asyncio.current_task() and not action_task.done():
                action_task.cancel()
        task_id = self._active_task_id
        if not task_id:
            self._set_generating(bool(self._active_task_id or self._active_action_plan_id))
            return
        await self._task_manager.cancel(task_id)

    def _on_regenerate_clicked(self) -> None:
        self.regenerate_current_thread()

    async def _regenerate_last(self) -> None:
        if not self._current_thread_id:
            return
        if self._active_task_id:
            await self._stop_active_generation()
            return
        messages = await self._store.list_messages(self._current_thread_id, limit=self.MAX_CONTEXT_MESSAGES)
        last_user: AIMessage | None = None
        for message in reversed(messages):
            if message.role == AIMessageRole.ASSISTANT:
                await self._store.delete_message(message.message_id)
                continue
            if message.role == AIMessageRole.USER:
                last_user = message
                break
        if last_user is None:
            return
        self._messages = await self._store.list_messages(self._current_thread_id, limit=self.MAX_CONTEXT_MESSAGES)
        self._render_messages()
        attachments = list((last_user.extra or {}).get("attachments") or []) if isinstance(last_user.extra, dict) else []
        context_messages = list(self._messages)
        action_message: AIMessage | None = None

        async def on_action_progress(progress_result) -> None:
            nonlocal action_message
            action_message = await self._upsert_action_progress_message(
                self._current_thread_id,
                progress_result,
                action_message,
            )

        action_result = await self._action_workflow.handle_user_turn(
            thread_id=self._current_thread_id,
            text=str(last_user.content or ""),
            has_attachments=bool(attachments),
            progress_callback=on_action_progress,
        )
        if action_result.handled:
            await self._handle_action_turn_result(
                self._current_thread_id,
                action_result,
                context_messages=context_messages,
                assistant_message=action_message,
            )
            return

        task_id = f"ai-chat-{uuid.uuid4()}"
        assistant_message = await self._store.create_message(
            thread_id=self._current_thread_id,
            role=AIMessageRole.ASSISTANT,
            status=AIMessageStatus.STREAMING,
            task_id=task_id,
        )
        self._append_message(assistant_message)
        context_messages = [message for message in self._messages if message.message_id != assistant_message.message_id]
        rag_history_messages = [
            message
            for message in context_messages
            if message.message_id != last_user.message_id
        ]
        memory_context = ConversationMemoryContext(lines=(), query_kind="")
        try:
            if not attachments:
                memory_context = await self._memory_manager.build_rag_context_for_ai_chat(
                    str(last_user.content or ""),
                    previous_messages=rag_history_messages,
                )
        except Exception as exc:
            logger.exception("AI assistant failed to rebuild local RAG context")
            await self._fail_pending_assistant_message(assistant_message, self._rag_error_text(exc))
            return
        if memory_context.requires_confirmation:
            await self._complete_pending_assistant_message(
                assistant_message,
                memory_context.confirmation_prompt,
                extra={"memory_confirmation": {"query": memory_context.pending_query_text or str(last_user.content or "")}},
            )
            return
        request = self._prompt_builder.build_ai_chat_request(
            self._current_thread_id,
            context_messages,
            task_id=task_id,
            memory_context_lines=memory_context.lines,
        )
        self._active_task_id = request.task_id
        self._active_assistant_message = assistant_message
        self._set_generating(True)
        self._active_stream_task = self._create_ui_task(self._run_stream(request), f"AI assistant regenerate {request.task_id}")

    def _on_clear_clicked(self) -> None:
        self._create_ui_task(self._clear_current_thread(), "clear AI assistant thread")

    async def _clear_current_thread(self) -> None:
        if not self._current_thread_id:
            return
        if self._active_task_id:
            await self._stop_active_generation()
        await self._store.clear_thread_messages(self._current_thread_id)
        self._messages = []
        self._render_messages()
        await self._reload_threads(select_thread_id=self._current_thread_id)

    def _on_thread_tab_close_requested(self, index: int) -> None:
        tab = self.thread_tab_bar.tabItem(index)
        if tab is None:
            return
        thread_id = str(tab.routeKey() or "").strip()
        self._request_thread_delete(thread_id)

    def _request_thread_delete(self, thread_id: str) -> None:
        normalized_thread_id = str(thread_id or "").strip()
        if not normalized_thread_id:
            return
        current_thread = next((thread for thread in self._threads if thread.thread_id == normalized_thread_id), None)
        if not self._can_delete_thread(current_thread):
            return
        dialog = DeleteAIThreadConfirmDialog(
            current_thread.title if current_thread is not None else tr("ai_assistant.thread.new", "New Chat"),
            self.window(),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._create_ui_task(self._delete_thread(normalized_thread_id), "delete AI assistant thread")

    def _on_delete_clicked(self) -> None:
        self._request_thread_delete(self._current_thread_id)

    async def _delete_current_thread(self) -> None:
        if not self._current_thread_id:
            return
        await self._delete_thread(self._current_thread_id)

    async def _delete_thread(self, thread_id: str) -> None:
        normalized_thread_id = str(thread_id or "").strip()
        if not normalized_thread_id:
            return
        deleting_current = normalized_thread_id == self._current_thread_id
        if deleting_current and self._active_task_id:
            await self._stop_active_generation()
        await self._store.delete_thread(normalized_thread_id)
        if deleting_current:
            self._current_thread_id = ""
            await self._reload_threads(select_first=True)
            return
        await self._reload_threads(select_thread_id=self._current_thread_id)

    def _can_delete_thread(self, thread: AIThread | None) -> bool:
        if thread is None or len(self._threads) <= 1:
            return False
        default_title = tr("ai_assistant.thread.new", "New Chat")
        title = str(thread.title or "").strip()
        has_messages = bool(str(thread.last_message or "").strip())
        return has_messages or title != default_title

    def _set_generating(self, generating: bool) -> None:
        self._is_generating = bool(generating)
        self.send_button.setEnabled(True)
        self.attachment_button.setEnabled(not generating)
        if generating:
            self.send_button.setText(tr("ai_assistant.stop", "Stop"))
            self.send_button.setIcon(CollectionIcon("stop").icon())
            self.send_button.setToolTip(tr("ai_assistant.stop", "Stop"))
            if not self._thinking_animation_timer.isActive():
                self._thinking_animation_timer.start()
        else:
            self.send_button.setText(tr("common.send", "Send"))
            self.send_button.setIcon(AppIcon.SEND_FILL.icon())
            self.send_button.setToolTip(tr("common.send", "Send"))
            self._thinking_animation_timer.stop()
            self._thinking_animation_frame = 0
            if self._message_delegate is not None:
                self._message_delegate.set_animation_frame(0, self.message_list)
        self._update_input_overlay_positions()
        self._sync_scroll_to_bottom_button()

    def _advance_thinking_animation(self) -> None:
        self._thinking_animation_frame = (self._thinking_animation_frame + 1) % 4
        if self._message_delegate is not None:
            self._message_delegate.set_animation_frame(self._thinking_animation_frame, self.message_list)

    def _scroll_to_bottom(self, *, passes: int = 3) -> None:
        def _scroll(remaining: int) -> None:
            self.message_list.doItemsLayout()
            bar = self.message_list.verticalScrollBar()
            bar.setValue(bar.maximum())
            self._sync_scroll_to_bottom_button()
            if remaining > 0:
                QTimer.singleShot(0, lambda: _scroll(remaining - 1))

        self._schedule_single_shot(lambda: _scroll(max(0, int(passes))))

    def _on_scroll_to_bottom_clicked(self) -> None:
        self._scroll_to_bottom()

    def _is_scroll_at_bottom(self, *, tolerance: int = 8) -> bool:
        bar = self.message_list.verticalScrollBar()
        return bar.maximum() - bar.value() <= tolerance

    def _sync_scroll_to_bottom_button(self, *_args) -> None:
        if not hasattr(self, "scroll_to_bottom_button"):
            return
        should_show = self._is_generating and self.message_list.isVisible() and not self._is_scroll_at_bottom()
        self.scroll_to_bottom_button.setVisible(should_show)
        if should_show:
            self._position_scroll_to_bottom_button()

    def _position_scroll_to_bottom_button(self) -> None:
        if not hasattr(self, "scroll_to_bottom_button"):
            return
        button = self.scroll_to_bottom_button
        button.adjustSize()
        button.setFixedHeight(34)
        button_width = max(112, button.sizeHint().width() + 8)
        scroll_rect = self.message_list.geometry()
        x = scroll_rect.left() + (scroll_rect.width() - button_width) // 2
        y = scroll_rect.bottom() - button.height() - 16
        button.setGeometry(max(scroll_rect.left(), x), max(scroll_rect.top(), y), button_width, button.height())
        button.raise_()

    @staticmethod
    def _schedule_single_shot(callback) -> None:
        QTimer.singleShot(0, callback)

    def _set_message_scrollbar_visible(self, visible: bool) -> None:
        if self._scroll_delegate is None:
            return
        self._scroll_delegate.vScrollBar.setForceHidden(not visible)

    def _message_track_width(self) -> int:
        if hasattr(self, "composer_shell") and self.composer_shell.width() > 0:
            return self.composer_shell.width()
        if hasattr(self, "message_list"):
            viewport_width = self.message_list.viewport().width()
            if viewport_width > 0:
                horizontal_margin = getattr(self.composer_overlay, "HORIZONTAL_MARGIN", 28)
                return max(self.composer_shell.minimumWidth(), min(self.composer_shell.maximumWidth(), viewport_width - horizontal_margin * 2))
        return self.composer_shell.maximumWidth()

    def _sync_message_row_widths(self) -> None:
        if not hasattr(self, "message_list"):
            return
        self.message_list.doItemsLayout()
        self.message_list.viewport().update()

    def _sync_message_scrollbar_hover(self) -> None:
        delegate_bar = self._scroll_delegate.vScrollBar if self._scroll_delegate is not None else None
        hovered = (
            self.message_list.underMouse()
            or self.message_list.viewport().underMouse()
            or self.message_list.verticalScrollBar().underMouse()
            or bool(delegate_bar is not None and delegate_bar.underMouse())
        )
        self._set_message_scrollbar_visible(hovered)

    def _update_input_overlay_positions(self) -> None:
        if not hasattr(self, "composer_overlay"):
            return
        panel_rect = self.content_panel.rect()
        if not panel_rect.isValid():
            return

        safe_rect = self.input_safe_area.geometry()
        if safe_rect.isValid() and safe_rect.height() > 0:
            self.composer_overlay.setGeometry(safe_rect)
        else:
            overlay_y = max(0, self.header.geometry().bottom() + 1)
            overlay_height = max(0, panel_rect.height() - overlay_y)
            self.composer_overlay.setGeometry(0, overlay_y, panel_rect.width(), overlay_height)
        self.composer_overlay.raise_()
        self.composer_overlay.update_overlay_layout()
        self.composer_shell_layout.activate()
        self.composer_controls_overlay.setGeometry(self.composer_shell.rect())
        self.composer_controls_overlay.raise_()
        self.composer_controls_overlay.update_overlay_layout()
        self._sync_message_row_widths()
        self._position_scroll_to_bottom_button()
        if self.scroll_to_bottom_button.isVisible():
            self.scroll_to_bottom_button.raise_()

    async def _fail_pending_assistant_message(self, message: AIMessage, text: str) -> None:
        message.content = str(text or "").strip() or tr("ai_assistant.error.failed", "AI could not complete this request.")
        message.status = AIMessageStatus.FAILED
        message.extra = {
            key: value
            for key, value in dict(message.extra or {}).items()
            if key != "ai_thinking"
        }
        await self._persist_assistant_message(message)
        self._update_message_card(message)
        if message is self._active_action_message:
            self._clear_active_action()
        self._active_task_id = ""
        self._active_assistant_message = None
        self._active_stream_task = None
        self._set_generating(False)

    async def _complete_pending_assistant_message(
        self,
        message: AIMessage,
        text: str,
        *,
        extra: dict | None = None,
    ) -> None:
        message.content = str(text or "").strip()
        message.status = AIMessageStatus.DONE
        message.task_id = ""
        if extra is not None:
            message.extra = dict(extra)
        await self._persist_assistant_message(message)
        self._update_message_card(message)
        if message is self._active_action_message:
            self._clear_active_action()
        self._active_task_id = ""
        self._active_assistant_message = None
        self._active_stream_task = None
        self._set_generating(False)

    @staticmethod
    def _rag_error_text(exc: Exception) -> str:
        if isinstance(exc, LocalEmbeddingGGUFRuntimeError):
            code = str(getattr(exc, "code", "") or "")
            if code == "AI_EMBEDDING_MODEL_NOT_FOUND":
                return "本地 embedding 模型文件不存在，请检查 ASSISTIM_AI_EMBEDDING_MODEL_PATH。"
            if code in {
                "AI_EMBEDDING_MODEL_LOAD_FAILED",
                "AI_EMBEDDING_MODEL_UNAVAILABLE",
                "AI_EMBEDDING_PROVIDER_UNAVAILABLE",
            }:
                return "本地 embedding 模型不可用，无法执行聊天记录检索。"
            if code == "AI_EMBEDDING_GENERATION_FAILED":
                return "本地 embedding 生成失败，无法执行聊天记录检索。"
        return "本地聊天记录检索失败。"

    def _message_at(self, position: QPoint, *, bubble_only: bool = False) -> AIMessage | None:
        index = self.message_list.indexAt(position)
        if not index.isValid():
            return None
        message = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(message, AIMessage):
            return None
        if bubble_only and self._message_delegate is not None:
            if not self._message_delegate.is_bubble_hit(self.message_list, index, position):
                return None
        return message

    def _handle_message_list_release(self, position: QPoint, button: Qt.MouseButton) -> bool:
        if button != Qt.MouseButton.LeftButton or self._message_delegate is None:
            return False
        index = self.message_list.indexAt(position)
        if not index.isValid():
            return False
        command = self._message_delegate.action_command_at(self.message_list, index, position)
        if not command:
            return self._message_delegate.toggle_action_status_expanded(self.message_list, index, position)
        message = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(message, AIMessage):
            return False
        self._on_action_message_requested(message.message_id, command)
        return True

    def _on_message_context_menu(self, position: QPoint) -> None:
        message = self._message_at(position, bubble_only=True)
        if message is None:
            return
        if not str(message.content or "").strip():
            return

        if self._message_context_menu is not None:
            self._message_context_menu.close()
            self._message_context_menu.deleteLater()
            self._message_context_menu = None

        menu = RoundMenu(parent=self)
        copy_action = Action(tr("chat.context.copy", "Copy"), self)
        menu.addAction(copy_action)

        copy_action.triggered.connect(lambda _checked=False, msg=message: self._copy_message_to_clipboard(msg))
        if self._message_delegate is not None:
            self._message_delegate.set_context_menu_message(self.message_list, message.message_id)

        def _on_menu_hidden() -> None:
            if self._message_context_menu is not menu:
                return
            self._message_context_menu = None
            if self._message_delegate is not None:
                self._message_delegate.set_context_menu_message(self.message_list, None)
            menu.deleteLater()

        menu.closedSignal.connect(_on_menu_hidden)
        self._message_context_menu = menu
        menu.exec(
            self.message_list.viewport().mapToGlobal(position),
            ani=True,
            aniType=MenuAnimationType.DROP_DOWN,
        )

    def _copy_message_to_clipboard(self, message: AIMessage | None) -> bool:
        if message is None:
            return False
        text = ""
        if self._message_delegate is not None:
            text = self._message_delegate.selected_text(str(message.content or ""), message.message_id)
        if not text:
            text = str(message.content or "")
        if not text:
            return False
        QGuiApplication.clipboard().setText(text)
        return True

    def eventFilter(self, watched, event) -> bool:
        watched_scrollbar = set()
        if hasattr(self, "message_list"):
            watched_scrollbar.update(
                {
                    self.message_list,
                    self.message_list.viewport(),
                    self.message_list.verticalScrollBar(),
                }
            )
        if self._scroll_delegate is not None:
            watched_scrollbar.add(self._scroll_delegate.vScrollBar)
        if watched in watched_scrollbar:
            if event.type() in {QEvent.Type.Enter, QEvent.Type.MouseMove}:
                self._set_message_scrollbar_visible(True)
            elif event.type() == QEvent.Type.Leave:
                QTimer.singleShot(80, self._sync_message_scrollbar_hover)

        if hasattr(self, "message_list") and watched is self.message_list.viewport():
            if event.type() == QEvent.Type.Resize:
                self.message_list.doItemsLayout()
                QTimer.singleShot(0, self._update_input_overlay_positions)
            if event.type() == QEvent.Type.Leave:
                if self._message_delegate is not None:
                    self._message_delegate.clear_action_hover(self.message_list)
                self.message_list.viewport().unsetCursor()
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                position = event.position().toPoint() if hasattr(event, "position") else event.pos()
                index = self.message_list.indexAt(position)
                if index.isValid() and self._message_delegate and self._message_delegate.begin_text_selection(
                    self.message_list,
                    index,
                    position,
                ):
                    self.message_list.viewport().setCursor(Qt.CursorShape.IBeamCursor)
                    return True
                if self._message_delegate is not None:
                    self._message_delegate.clear_text_selection(self.message_list)
            if event.type() == QEvent.Type.MouseMove:
                position = event.position().toPoint() if hasattr(event, "position") else event.pos()
                if self._message_delegate and self._message_delegate.is_selection_active():
                    if self._message_delegate.update_text_selection(self.message_list, position):
                        self.message_list.viewport().setCursor(Qt.CursorShape.IBeamCursor)
                        return True
                index = self.message_list.indexAt(position)
                if index.isValid() and self._message_delegate and self._message_delegate.update_action_hover(
                    self.message_list,
                    index,
                    position,
                ):
                    self.message_list.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                    return True
                if index.isValid() and self._message_delegate and self._message_delegate.update_action_status_hover(
                    self.message_list,
                    index,
                    position,
                ):
                    self.message_list.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                    return True
                if self._message_delegate is not None:
                    self._message_delegate.clear_action_hover(self.message_list)
                if index.isValid() and self._message_delegate and self._message_delegate.is_text_hit(
                    self.message_list,
                    index,
                    position,
                ):
                    self.message_list.viewport().setCursor(Qt.CursorShape.IBeamCursor)
                else:
                    self.message_list.viewport().unsetCursor()
            if event.type() == QEvent.Type.MouseButtonRelease:
                position = event.position().toPoint() if hasattr(event, "position") else event.pos()
                if self._message_delegate and self._message_delegate.is_selection_active():
                    self._message_delegate.end_text_selection(self.message_list)
                    return True
                if self._handle_message_list_release(position, event.button()):
                    return True

        if hasattr(self, "composer_shell") and watched in {
            self.composer_overlay,
            self.composer_shell,
            self.composer_controls_overlay,
            self.pending_attachment_preview,
            self.prompt_edit,
        }:
            if event.type() in {
                QEvent.Type.Resize,
                QEvent.Type.Show,
                QEvent.Type.LayoutRequest,
            }:
                QTimer.singleShot(0, self._update_input_overlay_positions)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._update_input_overlay_positions)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._update_input_overlay_positions)

    def _apply_theme(self) -> None:
        if self._applying_theme:
            return
        self._applying_theme = True
        try:
            if isDarkTheme():
                panel = "rgba(32, 35, 39, 0.72)"
                border = "rgba(255,255,255,0.08)"
                input_bg = "rgba(255, 255, 255, 0.06)"
                text = "rgb(241,245,249)"
                muted_text = "rgba(241,245,249,0.72)"
                hover_bg = "rgba(255,255,255,0.08)"
                pressed_bg = "rgba(255,255,255,0.12)"
                disabled_text = "rgba(255,255,255,0.34)"
                scrollbar_track = "rgba(120,120,120,0.18)"
                scrollbar_handle = "rgba(120,120,120,0.55)"
            else:
                panel = "rgba(255, 255, 255, 0.72)"
                border = "rgba(15,23,42,0.08)"
                input_bg = "rgba(255, 255, 255, 0.92)"
                text = "rgb(17,24,39)"
                muted_text = "rgba(17,24,39,0.64)"
                hover_bg = "rgba(0,0,0,0.05)"
                pressed_bg = "rgba(0,0,0,0.08)"
                disabled_text = "rgba(0,0,0,0.32)"
                scrollbar_track = "rgba(120,120,120,0.18)"
                scrollbar_handle = "rgba(120,120,120,0.55)"
            self.setStyleSheet(
                f"""
                QWidget#AIAssistantInterface {{
                    background: transparent;
                    color: {text};
                }}
                QFrame#aiAssistantContentPanel {{
                    background: transparent;
                }}
                QFrame#aiAssistantHeader {{
                    background: transparent;
                    border: none;
                }}
                QLabel#aiAssistantThreadTitle {{
                    color: {text};
                    font: 16px "Segoe UI Semibold", "Microsoft YaHei", "PingFang SC";
                }}
                QWidget#aiAssistantHeaderActions {{
                    background: transparent;
                }}
                QListView#aiAssistantMessageList {{
                    background: transparent;
                    border: none;
                    outline: none;
                }}
                QWidget#aiAssistantMessageViewport {{
                    background: transparent;
                }}
                QListView#aiAssistantMessageList QScrollBar:vertical {{
                    width: 8px;
                    margin: 8px 0 8px 0;
                    border: none;
                    border-radius: 4px;
                    background: {scrollbar_track};
                }}
                QListView#aiAssistantMessageList QScrollBar::handle:vertical {{
                    min-height: 28px;
                    border: none;
                    border-radius: 4px;
                    background: {scrollbar_handle};
                }}
                QListView#aiAssistantMessageList QScrollBar::add-line:vertical,
                QListView#aiAssistantMessageList QScrollBar::sub-line:vertical,
                QListView#aiAssistantMessageList QScrollBar::add-page:vertical,
                QListView#aiAssistantMessageList QScrollBar::sub-page:vertical {{
                    border: none;
                    background: transparent;
                    height: 0;
                }}
                QFrame#aiAssistantEmpty {{
                    background: transparent;
                }}
                QFrame#aiAssistantInputSafeArea {{
                    background: transparent;
                    border: none;
                }}
                QFrame#aiAssistantComposerShell {{
                    background: transparent;
                    border: none;
                }}
                QWidget#aiAssistantFloatingComposerOverlay,
                QWidget#aiAssistantComposerControlsOverlay {{
                    background: transparent;
                    border: none;
                }}
                QFrame#aiAssistantPendingAttachmentPreview {{
                    background: {input_bg};
                    border: 1px solid {border};
                    border-bottom: none;
                    border-top-left-radius: 8px;
                    border-top-right-radius: 8px;
                }}
                QLabel#aiAssistantPendingAttachmentThumbnail {{
                    background: transparent;
                    border: 1px solid {border};
                    border-radius: 6px;
                }}
                QLabel#aiAssistantPendingAttachmentName {{
                    color: {muted_text};
                    background: transparent;
                }}
                QTextEdit#aiAssistantPromptEdit {{
                    background: {input_bg};
                    color: {text};
                    border: 1px solid {border};
                    border-radius: 8px;
                    padding: 10px;
                }}
                QFrame#aiAssistantPendingAttachmentPreview + QTextEdit#aiAssistantPromptEdit {{
                    border-top-left-radius: 0;
                    border-top-right-radius: 0;
                }}
                QWidget#aiAssistantPromptViewport {{
                    background: transparent;
                    border: none;
                }}
                TransparentToolButton#aiAssistantAttachmentButton {{
                    background: transparent;
                    border: none;
                    color: {muted_text};
                    border-radius: 8px;
                }}
                TransparentToolButton#aiAssistantAttachmentButton:disabled {{
                    background: transparent;
                    color: {disabled_text};
                }}
                TransparentToolButton#aiAssistantPendingAttachmentRemove {{
                    background: transparent;
                    border: none;
                    color: {muted_text};
                    border-radius: 8px;
                }}
                TransparentToolButton#aiAssistantPendingAttachmentRemove:hover {{
                    background: {hover_bg};
                }}
                TransparentToolButton#aiAssistantHeaderDeleteButton {{
                    background: transparent;
                    border: none;
                    color: {text};
                    border-radius: 8px;
                }}
                TransparentToolButton#aiAssistantHeaderDeleteButton:hover {{
                    background: {hover_bg};
                }}
                TransparentToolButton#aiAssistantHeaderDeleteButton:pressed {{
                    background: {pressed_bg};
                }}
                """
            )
        finally:
            self._applying_theme = False

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in {
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.StyleChange,
        }:
            self._apply_theme()


__all__ = ["AIAssistantInterface"]
