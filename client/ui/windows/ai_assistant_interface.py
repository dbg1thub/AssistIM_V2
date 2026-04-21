"""Standalone local AI assistant page with thread list and streaming chat."""

from __future__ import annotations

import asyncio
import mimetypes
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPixmap, QRegion
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
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
    PrimaryPushButton,
    ScrollBarHandleDisplayMode,
    SubtitleLabel,
    TransparentToolButton,
    isDarkTheme,
    themeColor,
)
from qfluentwidgets.components.widgets.scroll_bar import SmoothScrollDelegate

from client.core import logging
from client.core.app_icons import AppIcon, CollectionIcon
from client.core.i18n import tr
from client.events.event_bus import get_event_bus
from client.managers.ai_action_workflow import AIActionPlanner, AIActionWorkflow
from client.managers.conversation_memory_manager import ConversationMemoryManager
from client.managers.ai_prompt_builder import AIPromptBuilder
from client.managers.ai_task_manager import AITaskEvent, AITaskSnapshot, AITaskState, get_ai_task_manager
from client.models.ai_assistant import AIMessage, AIMessageRole, AIMessageStatus, AIThread
from client.services.ai_service import AIErrorCode
from client.storage.ai_assistant_store import get_ai_assistant_store

logger = logging.get_logger(__name__)

SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _qss_rgba(color: QColor, alpha: int | None = None) -> str:
    resolved_alpha = color.alpha() if alpha is None else max(0, min(255, int(alpha)))
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {resolved_alpha})"


def _first_image_attachment(extra: dict | None) -> dict | None:
    for attachment in list((extra or {}).get("attachments") or []):
        if isinstance(attachment, dict) and str(attachment.get("type") or "").strip().lower() == "image":
            return dict(attachment)
    return None


def _attachment_display_name(attachment: dict | None) -> str:
    if not attachment:
        return ""
    name = str(attachment.get("name") or "").strip()
    if name:
        return name
    path = str(attachment.get("local_path") or "").strip()
    return Path(path).name if path else ""


def _ai_action_footer_text(extra: dict | None) -> str:
    action = dict((extra or {}).get("ai_action") or {})
    if not action:
        return ""
    state = str(action.get("state") or "").strip()
    if state == "waiting_confirmation":
        return "等待你确认后继续。"
    if state == "waiting_clarification":
        return "等待你补充信息后继续。"
    steps = [item for item in list(action.get("steps") or []) if isinstance(item, dict)]
    current_step_id = str(action.get("current_step_id") or "").strip()
    current = next((item for item in steps if str(item.get("id") or "") == current_step_id), None)
    if state == "running" and current is not None:
        return str(current.get("display_text") or "正在执行操作...")
    if state == "cancelled":
        return "操作已取消。"
    return ""


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


class AIAssistantMessageCard(QFrame):
    """One message card in the standalone assistant stream."""

    def __init__(self, message: AIMessage, parent=None):
        super().__init__(parent)
        self.message = message
        self._applying_theme = False
        self.setObjectName("aiAssistantMessageCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 10, 14, 10)
        self.layout.setSpacing(8)

        self.image_label = QLabel(self)
        self.image_label.setObjectName("aiAssistantMessageImage")
        self.image_label.setFixedSize(220, 140)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.hide()

        self.content_label = BodyLabel(self)
        self.content_label.setWordWrap(True)
        self.content_label.setMinimumWidth(0)
        self.content_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.content_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.content_label.setTextFormat(Qt.TextFormat.PlainText)
        self.footer_label = CaptionLabel(self)
        self.footer_label.setWordWrap(True)
        self.footer_label.setMinimumWidth(0)
        self.footer_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.footer_label.hide()

        self.layout.addWidget(self.image_label)
        self.layout.addWidget(self.content_label)
        self.layout.addWidget(self.footer_label)
        self.set_message(message)

    def set_fill_width(self, fill: bool) -> None:
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        if not fill:
            policy.setHorizontalPolicy(QSizePolicy.Policy.Maximum)
        self.setSizePolicy(policy)

    def set_message(self, message: AIMessage) -> None:
        self.message = message
        self._set_image_attachment(_first_image_attachment(message.extra))
        self.content_label.setText(message.content or tr("ai_assistant.message.empty", ""))
        footer_text = ""
        if bool((message.extra or {}).get("truncated")):
            footer_text = tr(
                "ai_assistant.message.truncated_hint",
                "内容较长，已截断。继续提问可接着往下说。",
            )
        elif message.status == AIMessageStatus.FAILED:
            footer_text = tr(
                "ai_assistant.message.failed_hint",
                "本次生成未完成。你可以继续追问，或稍后再试。",
            )
        else:
            footer_text = _ai_action_footer_text(message.extra)
        self.footer_label.setText(footer_text)
        self.footer_label.setVisible(bool(footer_text))
        self._sync_text_metrics()
        self._apply_theme()

    def _set_image_attachment(self, attachment: dict | None) -> None:
        path = str((attachment or {}).get("local_path") or "").strip()
        if not path or not Path(path).is_file():
            self.image_label.clear()
            self.image_label.hide()
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.image_label.clear()
            self.image_label.hide()
            return
        scaled = pixmap.scaled(
            QSize(220, 140),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)
        self.image_label.setToolTip(_attachment_display_name(attachment))
        self.image_label.show()

    def set_content(self, content: str, *, status: AIMessageStatus | None = None) -> None:
        if status is not None:
            self.message.status = status
        self.message.content = str(content or "")
        self.set_message(self.message)

    def _sync_text_metrics(self) -> None:
        self._sync_wrapped_label_height(self.content_label)
        self._sync_wrapped_label_height(self.footer_label, visible=self.footer_label.isVisible())
        self.layout.activate()
        self.updateGeometry()

    def _sync_wrapped_label_height(self, label: QLabel, *, visible: bool = True) -> None:
        if not visible:
            label.setFixedHeight(0)
            return
        available_width = label.width()
        if available_width <= 0:
            margins = self.layout.contentsMargins()
            available_width = max(0, self.width() - margins.left() - margins.right())
        if available_width <= 0:
            return
        metrics = label.fontMetrics()
        text = label.text() or ""
        bounding = metrics.boundingRect(
            0,
            0,
            available_width,
            0,
            int(Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextExpandTabs),
            text,
        )
        target_height = max(metrics.height(), bounding.height())
        if label.height() != target_height:
            label.setFixedHeight(target_height)

    def _apply_theme(self) -> None:
        if self._applying_theme:
            return
        self._applying_theme = True
        role = self.message.role.value if isinstance(self.message.role, AIMessageRole) else str(self.message.role or "")
        try:
            if isDarkTheme():
                user_bg = _qss_rgba(QColor(themeColor()), 58)
                assistant_bg = "transparent"
                text = "rgba(246, 248, 250, 235)" if role == AIMessageRole.USER.value else "rgba(236, 239, 243, 230)"
                muted_text = "rgba(236, 239, 243, 166)"
                image_border = "rgba(255,255,255,0.14)"
                image_bg = "rgba(255,255,255,0.04)"
            else:
                user_bg = _qss_rgba(QColor(themeColor()), 22)
                assistant_bg = "transparent"
                text = "rgb(26, 26, 26)"
                muted_text = "rgba(26, 26, 26, 150)"
                image_border = "rgba(15,23,42,0.12)"
                image_bg = "rgba(255,255,255,0.62)"
            bg = user_bg if role == AIMessageRole.USER.value else assistant_bg
            self.setStyleSheet(
                f"""
                QFrame#aiAssistantMessageCard {{
                    background: {bg};
                    border: none;
                    border-radius: {"10px" if role == AIMessageRole.USER.value else "0"};
                }}
                QLabel {{
                    color: {text};
                    background: transparent;
                }}
                QLabel[isFooter="true"] {{
                    color: {muted_text};
                    background: transparent;
                }}
                QLabel#aiAssistantMessageImage {{
                    background: {image_bg};
                    border: 1px solid {image_border};
                    border-radius: 8px;
                }}
                """
            )
            self.footer_label.setProperty("isFooter", True)
            self.footer_label.style().unpolish(self.footer_label)
            self.footer_label.style().polish(self.footer_label)
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

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_text_metrics()


class AIAssistantMessageRow(QWidget):
    """Message row that aligns assistant/user content to the composer track."""

    DEFAULT_CONTENT_WIDTH = 1100
    MIN_CONTENT_WIDTH = 320

    def __init__(self, message: AIMessage, parent=None):
        super().__init__(parent)
        self.message = message
        self._role = message.role.value if isinstance(message.role, AIMessageRole) else str(message.role or "")
        self._content_width = self.DEFAULT_CONTENT_WIDTH
        self.card = AIAssistantMessageCard(message, self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.row_layout = QHBoxLayout(self)
        self.row_layout.setContentsMargins(0, 0, 0, 0)
        self.row_layout.setSpacing(0)

        self._content_lane = QWidget(self)
        self._content_lane.setObjectName("aiAssistantMessageLane")
        self._content_lane.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._content_lane_layout = QHBoxLayout(self._content_lane)
        self._content_lane_layout.setContentsMargins(0, 0, 0, 0)
        self._content_lane_layout.setSpacing(0)

        self.row_layout.addStretch(1)
        self.row_layout.addWidget(self._content_lane, 0)
        self.row_layout.addStretch(1)

        if self._role == AIMessageRole.USER.value:
            self.card.set_fill_width(False)
            self._content_lane_layout.addStretch(1)
            self._content_lane_layout.addWidget(self.card, 0)
        else:
            self.card.set_fill_width(True)
            self._content_lane_layout.addWidget(self.card, 1)

        self.set_content_width(self.DEFAULT_CONTENT_WIDTH)

    def set_content_width(self, width: int) -> None:
        capped_width = max(self.MIN_CONTENT_WIDTH, int(width or 0))
        if (
            capped_width == self._content_width
            and self._content_lane.width() == capped_width
            and self.width() == capped_width
        ):
            self.card._sync_text_metrics()
            return
        self._content_width = capped_width
        self.setFixedWidth(capped_width)
        self._content_lane.setFixedWidth(capped_width)
        self.card.setMaximumWidth(capped_width)
        self.row_layout.invalidate()
        self._content_lane_layout.invalidate()
        self.card._sync_text_metrics()
        self._content_lane.updateGeometry()
        self.updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.set_content_width(self._content_width)


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

    THREAD_WIDTH = 286
    MAX_CONTEXT_MESSAGES = 80
    COMPOSER_HEIGHT = 140
    INPUT_SAFE_AREA_HEIGHT = 196
    MESSAGE_BOTTOM_MARGIN = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AIAssistantInterface")
        self._store = get_ai_assistant_store()
        self._task_manager = get_ai_task_manager()
        self._prompt_builder = AIPromptBuilder()
        self._memory_manager = ConversationMemoryManager()
        self._action_workflow = AIActionWorkflow(
            memory_manager=self._memory_manager,
            planner=AIActionPlanner(self._task_manager),
        )
        self._event_bus = get_event_bus()
        self._ui_tasks: set[asyncio.Task] = set()
        self._event_subscriptions: list[tuple[str, object]] = []
        self._initialized = False
        self._teardown_started = False
        self._threads: list[AIThread] = []
        self._current_thread_id = ""
        self._messages: list[AIMessage] = []
        self._message_cards: dict[str, AIAssistantMessageCard] = {}
        self._active_task_id = ""
        self._active_assistant_message: AIMessage | None = None
        self._active_stream_task: asyncio.Task | None = None
        self._last_persist_at = 0.0
        self._applying_theme = False
        self._scroll_delegate: SmoothScrollDelegate | None = None
        self._is_generating = False
        self._pending_image_attachment: dict | None = None

        self._setup_ui()
        self._subscribe_to_events()
        self.destroyed.connect(self._on_destroyed)

    def _setup_ui(self) -> None:
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.thread_panel = QFrame(self)
        self.thread_panel.setObjectName("aiAssistantThreadPanel")
        self.thread_panel.setFixedWidth(self.THREAD_WIDTH)
        self.thread_layout = QVBoxLayout(self.thread_panel)
        self.thread_layout.setContentsMargins(14, 14, 14, 14)
        self.thread_layout.setSpacing(12)

        self.new_thread_button = PrimaryPushButton(
            tr("ai_assistant.new_chat", "New Chat"),
            self.thread_panel,
        )
        self.new_thread_button.setIcon(AppIcon.ADD.icon())
        self.new_thread_button.clicked.connect(self._on_new_thread_clicked)
        self.thread_list = QListWidget(self.thread_panel)
        self.thread_list.setObjectName("aiAssistantThreadList")
        self.thread_list.setFrameShape(QFrame.Shape.NoFrame)
        self.thread_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.thread_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.thread_list.itemClicked.connect(self._on_thread_item_clicked)

        self.thread_layout.addWidget(self.new_thread_button)
        self.thread_layout.addWidget(self.thread_list, 1)

        self.content_panel = QFrame(self)
        self.content_panel.setObjectName("aiAssistantContentPanel")
        self.content_layout = QVBoxLayout(self.content_panel)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        self.header = QFrame(self.content_panel)
        self.header.setObjectName("aiAssistantHeader")
        self.header_layout = QHBoxLayout(self.header)
        self.header_layout.setContentsMargins(22, 12, 22, 12)
        self.header_layout.setSpacing(12)

        self.product_label = BodyLabel("AssistIM AI", self.header)
        self.product_label.setObjectName("aiAssistantProductTitle")
        self.product_label.setMinimumWidth(0)
        self.product_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self.title_label = BodyLabel(tr("ai_assistant.thread.new", "New Chat"), self.header)
        self.title_label.setObjectName("aiAssistantThreadTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self.header_actions = QWidget(self.header)
        self.header_actions.setObjectName("aiAssistantHeaderActions")
        self.header_actions_layout = QHBoxLayout(self.header_actions)
        self.header_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.header_actions_layout.setSpacing(0)
        self.delete_button = TransparentToolButton(CollectionIcon("delete"), self.header_actions)
        self.delete_button.setObjectName("aiAssistantHeaderDeleteButton")
        self.delete_button.setFixedSize(36, 36)
        self.delete_button.setToolTip(tr("common.delete", "Delete"))
        self.delete_button.clicked.connect(self._on_delete_clicked)
        self.header_actions_layout.addStretch(1)
        self.header_actions_layout.addWidget(self.delete_button)

        self.header_layout.addWidget(self.product_label, 1, Qt.AlignmentFlag.AlignVCenter)
        self.header_layout.addWidget(self.title_label, 2, Qt.AlignmentFlag.AlignVCenter)
        self.header_layout.addWidget(self.header_actions, 1, Qt.AlignmentFlag.AlignVCenter)

        self.scroll_area = QScrollArea(self.content_panel)
        self.scroll_area.setObjectName("aiAssistantScrollArea")
        self.scroll_area.viewport().setObjectName("aiAssistantScrollViewport")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll_delegate = SmoothScrollDelegate(self.scroll_area)
        self._scroll_delegate.vScrollBar.setHandleDisplayMode(ScrollBarHandleDisplayMode.ALWAYS)
        self._scroll_delegate.hScrollBar.setForceHidden(True)
        self._scroll_delegate.vScrollBar.setForceHidden(True)
        self.message_container = QWidget(self.scroll_area)
        self.message_container.setObjectName("aiAssistantMessageContainer")
        self.message_layout = QVBoxLayout(self.message_container)
        self.message_layout.setContentsMargins(28, 26, 28, self.MESSAGE_BOTTOM_MARGIN)
        self.message_layout.setSpacing(14)
        self.message_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.message_container)
        self.scroll_area.installEventFilter(self)
        self.scroll_area.viewport().installEventFilter(self)
        self.scroll_area.verticalScrollBar().installEventFilter(self)
        self._scroll_delegate.vScrollBar.installEventFilter(self)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._sync_scroll_to_bottom_button)
        self.scroll_area.verticalScrollBar().rangeChanged.connect(self._sync_scroll_to_bottom_button)

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
        self.content_layout.addWidget(self.scroll_area, 1)
        self.content_layout.addWidget(self.input_safe_area)
        self.scroll_area.hide()

        self.scroll_to_bottom_button = PrimaryPushButton(
            tr("ai_assistant.scroll_to_bottom", "Scroll to bottom"),
            self.content_panel,
        )
        self.scroll_to_bottom_button.setObjectName("aiAssistantScrollToBottomButton")
        self.scroll_to_bottom_button.setIcon(CollectionIcon("arrow_down").icon())
        self.scroll_to_bottom_button.setFixedHeight(34)
        self.scroll_to_bottom_button.hide()
        self.scroll_to_bottom_button.clicked.connect(self._on_scroll_to_bottom_clicked)

        self.main_layout.addWidget(self.thread_panel)
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
        if self._active_task_id:
            cancel_task = self._create_ui_task(
                self._task_manager.cancel(self._active_task_id),
                "cancel AI assistant task on teardown",
            )
        for task in list(self._ui_tasks):
            if task is not cancel_task and not task.done():
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
        self._render_thread_list()
        return updated

    def regenerate_current_thread(self) -> asyncio.Task | None:
        """Schedule one regenerate for the current assistant thread without exposing a UI entry here."""
        if not self._current_thread_id:
            return None
        return self._create_ui_task(
            self._regenerate_last(),
            f"regenerate AI assistant thread {self._current_thread_id}",
        )

    def _on_thread_item_clicked(self, item: QListWidgetItem) -> None:
        thread_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if thread_id and thread_id != self._current_thread_id:
            self._create_ui_task(self._select_thread(thread_id), f"select AI assistant thread {thread_id}")

    async def _reload_threads(self, *, select_first: bool = False, select_thread_id: str = "") -> None:
        self._threads = await self._store.list_threads()
        if not self._threads:
            self._threads = [await self._store.create_thread()]
        self._render_thread_list()
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
        self._render_thread_list()
        self._render_messages()
        self._set_generating(bool(self._active_task_id))
        self.prompt_edit.setFocus()

    def _render_thread_list(self) -> None:
        self.thread_list.blockSignals(True)
        self.thread_list.clear()
        for thread in self._threads:
            preview = str(thread.last_message or "").strip()
            title = str(thread.title or tr("ai_assistant.thread.new", "New Chat")).strip()
            item_text = title if not preview else f"{title}\n{preview}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, thread.thread_id)
            item.setToolTip(item_text)
            self.thread_list.addItem(item)
            if thread.thread_id == self._current_thread_id:
                item.setSelected(True)
                self.thread_list.setCurrentItem(item)
        self.thread_list.blockSignals(False)

    def _render_messages(self) -> None:
        while self.message_layout.count() > 0:
            item = self.message_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._message_cards.clear()
        if not self._messages:
            self.scroll_area.hide()
            self.empty_widget.show()
            QTimer.singleShot(0, self._update_input_overlay_positions)
            return
        self.empty_widget.hide()
        self.scroll_area.show()
        for message in self._messages:
            self._add_message_card(message)
        QTimer.singleShot(0, self._update_input_overlay_positions)
        self._scroll_to_bottom()

    def _add_message_card(self, message: AIMessage) -> None:
        wrapper = AIAssistantMessageRow(message, self.message_container)
        wrapper.set_content_width(self._message_track_width())
        self.message_layout.insertWidget(self._message_insert_index(), wrapper, 0, Qt.AlignmentFlag.AlignHCenter)
        self._message_cards[message.message_id] = wrapper.card

    def _message_insert_index(self) -> int:
        """Return the message insertion point for a top-aligned list layout."""
        return self.message_layout.count()

    def _append_message(self, message: AIMessage) -> None:
        self._messages.append(message)
        if self.empty_widget.isVisible():
            self.empty_widget.hide()
            self.scroll_area.show()
            while self.message_layout.count() > 0:
                item = self.message_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
        self._add_message_card(message)
        self._scroll_to_bottom()

    def _update_message_card(self, message: AIMessage) -> None:
        should_follow = self._is_generating and self._is_scroll_at_bottom()
        card = self._message_cards.get(message.message_id)
        if card is not None:
            card.set_message(message)
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
        if self._active_task_id:
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

        assistant_message = await self._store.create_message(
            thread_id=thread_id,
            role=AIMessageRole.ASSISTANT,
            content="",
            status=AIMessageStatus.PENDING,
        )
        self._append_message(assistant_message)
        self._set_generating(True)

        memory_context_lines: tuple[str, ...] = ()
        action_message_extra: dict | None = None
        if not attachments:
            action_result = await self._action_workflow.handle_user_turn(
                thread_id=thread_id,
                text=text,
                has_attachments=False,
            )
            if action_result.handled and action_result.response_text:
                await self._store.update_message(
                    assistant_message,
                    content=action_result.response_text,
                    status=AIMessageStatus.DONE,
                    extra=action_result.message_extra,
                )
                assistant_message.content = action_result.response_text
                assistant_message.status = AIMessageStatus.DONE
                assistant_message.extra = action_result.message_extra
                self._update_message_card(assistant_message)
                self._set_generating(False)
                await self._reload_threads(select_thread_id=thread_id)
                return
            if action_result.handled:
                memory_context_lines = action_result.memory_context_lines
                action_message_extra = action_result.message_extra

        task_id = f"ai-chat-{uuid.uuid4()}"
        await self._store.update_message(
            assistant_message,
            status=AIMessageStatus.STREAMING,
            task_id=task_id,
            extra=action_message_extra,
        )
        assistant_message.status = AIMessageStatus.STREAMING
        assistant_message.task_id = task_id
        assistant_message.extra = dict(action_message_extra or {})
        self._update_message_card(assistant_message)

        context_messages = [message for message in self._messages if message.message_id != assistant_message.message_id]
        request = self._prompt_builder.build_ai_chat_request(
            thread_id,
            context_messages,
            task_id=task_id,
            memory_context_lines=memory_context_lines,
        )
        self._active_task_id = request.task_id
        self._active_assistant_message = assistant_message
        self._last_persist_at = 0.0
        self._active_stream_task = self._create_ui_task(self._run_stream(request), f"AI assistant stream {request.task_id}")

    async def _run_stream(self, request) -> None:
        snapshot = await self._task_manager.stream(request)
        await self._finalize_snapshot(snapshot)

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
        self._render_thread_list()

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
        self._active_assistant_message.content = content
        self._active_assistant_message.status = status
        self._active_assistant_message.model = str(snapshot.model or "")
        self._active_assistant_message.extra = message_extra
        await self._action_workflow.finish_streamed_action(
            message_extra,
            content=content,
            status=status.value if isinstance(status, AIMessageStatus) else str(status),
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
        task_id = self._active_task_id
        if not task_id:
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
        task_id = f"ai-chat-{uuid.uuid4()}"
        assistant_message = await self._store.create_message(
            thread_id=self._current_thread_id,
            role=AIMessageRole.ASSISTANT,
            status=AIMessageStatus.STREAMING,
            task_id=task_id,
        )
        self._append_message(assistant_message)
        context_messages = [message for message in self._messages if message.message_id != assistant_message.message_id]
        memory_context_lines: tuple[str, ...] = ()
        if last_user is not None and not _first_image_attachment(last_user.extra):
            action_result = await self._action_workflow.handle_user_turn(
                thread_id=self._current_thread_id,
                text=last_user.content,
                has_attachments=False,
            )
            if action_result.handled and action_result.response_text:
                await self._store.update_message(
                    assistant_message,
                    content=action_result.response_text,
                    status=AIMessageStatus.DONE,
                    extra=action_result.message_extra,
                )
                assistant_message.content = action_result.response_text
                assistant_message.status = AIMessageStatus.DONE
                assistant_message.extra = action_result.message_extra
                self._render_messages()
                await self._reload_threads(select_thread_id=self._current_thread_id)
                return
            if action_result.handled:
                memory_context_lines = action_result.memory_context_lines
                assistant_message.extra = action_result.message_extra
                await self._store.update_message(assistant_message, extra=action_result.message_extra)
        request = self._prompt_builder.build_ai_chat_request(
            self._current_thread_id,
            context_messages,
            task_id=task_id,
            memory_context_lines=memory_context_lines,
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

    def _on_delete_clicked(self) -> None:
        if not self._current_thread_id:
            return
        current_thread = next((thread for thread in self._threads if thread.thread_id == self._current_thread_id), None)
        dialog = DeleteAIThreadConfirmDialog(
            current_thread.title if current_thread is not None else self.title_label.text(),
            self.window(),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._create_ui_task(self._delete_current_thread(), "delete AI assistant thread")

    async def _delete_current_thread(self) -> None:
        if not self._current_thread_id:
            return
        if self._active_task_id:
            await self._stop_active_generation()
        await self._store.delete_thread(self._current_thread_id)
        self._current_thread_id = ""
        await self._reload_threads(select_first=True)

    def _set_generating(self, generating: bool) -> None:
        self._is_generating = bool(generating)
        self.send_button.setEnabled(True)
        self.attachment_button.setEnabled(not generating)
        if generating:
            self.send_button.setText(tr("ai_assistant.stop", "Stop"))
            self.send_button.setIcon(CollectionIcon("stop").icon())
            self.send_button.setToolTip(tr("ai_assistant.stop", "Stop"))
        else:
            self.send_button.setText(tr("common.send", "Send"))
            self.send_button.setIcon(AppIcon.SEND_FILL.icon())
            self.send_button.setToolTip(tr("common.send", "Send"))
        self.delete_button.setEnabled(bool(self._current_thread_id))
        self._update_input_overlay_positions()
        self._sync_scroll_to_bottom_button()

    def _scroll_to_bottom(self, *, passes: int = 3) -> None:
        def _scroll(remaining: int) -> None:
            bar = self.scroll_area.verticalScrollBar()
            bar.setValue(bar.maximum())
            self._sync_scroll_to_bottom_button()
            if remaining > 0:
                QTimer.singleShot(0, lambda: _scroll(remaining - 1))

        self._schedule_single_shot(lambda: _scroll(max(0, int(passes))))

    def _on_scroll_to_bottom_clicked(self) -> None:
        self._scroll_to_bottom()

    def _is_scroll_at_bottom(self, *, tolerance: int = 8) -> bool:
        bar = self.scroll_area.verticalScrollBar()
        return bar.maximum() - bar.value() <= tolerance

    def _sync_scroll_to_bottom_button(self, *_args) -> None:
        if not hasattr(self, "scroll_to_bottom_button"):
            return
        should_show = self._is_generating and self.scroll_area.isVisible() and not self._is_scroll_at_bottom()
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
        scroll_rect = self.scroll_area.geometry()
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
        if hasattr(self, "scroll_area"):
            viewport_width = self.scroll_area.viewport().width()
            if viewport_width > 0:
                horizontal_margin = getattr(self.composer_overlay, "HORIZONTAL_MARGIN", 28)
                return max(self.composer_shell.minimumWidth(), min(self.composer_shell.maximumWidth(), viewport_width - horizontal_margin * 2))
        return self.composer_shell.maximumWidth()

    def _sync_message_row_widths(self) -> None:
        track_width = self._message_track_width()
        for index in range(self.message_layout.count()):
            item = self.message_layout.itemAt(index)
            row = item.widget() if item is not None else None
            if isinstance(row, AIAssistantMessageRow):
                row.set_content_width(track_width)
        self.message_layout.invalidate()
        self.message_container.adjustSize()
        self.message_container.updateGeometry()

    def _sync_message_scrollbar_hover(self) -> None:
        delegate_bar = self._scroll_delegate.vScrollBar if self._scroll_delegate is not None else None
        hovered = (
            self.scroll_area.underMouse()
            or self.scroll_area.viewport().underMouse()
            or self.scroll_area.verticalScrollBar().underMouse()
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

    def eventFilter(self, watched, event) -> bool:
        watched_scrollbar = set()
        if hasattr(self, "scroll_area"):
            watched_scrollbar.update(
                {
                    self.scroll_area,
                    self.scroll_area.viewport(),
                    self.scroll_area.verticalScrollBar(),
                }
            )
        if self._scroll_delegate is not None:
            watched_scrollbar.add(self._scroll_delegate.vScrollBar)
        if watched in watched_scrollbar:
            if event.type() in {QEvent.Type.Enter, QEvent.Type.MouseMove}:
                self._set_message_scrollbar_visible(True)
            elif event.type() == QEvent.Type.Leave:
                QTimer.singleShot(80, self._sync_message_scrollbar_hover)

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
                QFrame#aiAssistantThreadPanel {{
                    background: {panel};
                    border-right: 1px solid {border};
                }}
                QListWidget#aiAssistantThreadList {{
                    background: transparent;
                    border: none;
                    outline: none;
                }}
                QListWidget#aiAssistantThreadList::item {{
                    padding: 10px 8px;
                    border-radius: 8px;
                    margin: 2px 0;
                }}
                QListWidget#aiAssistantThreadList::item:selected {{
                    background: rgba(59, 130, 246, 0.18);
                }}
                QFrame#aiAssistantContentPanel {{
                    background: transparent;
                }}
                QFrame#aiAssistantHeader {{
                    background: transparent;
                    border: none;
                }}
                QLabel#aiAssistantProductTitle {{
                    color: {text};
                    font: 16px "Segoe UI Semibold", "Microsoft YaHei", "PingFang SC";
                }}
                QLabel#aiAssistantThreadTitle {{
                    color: {text};
                    font: 16px "Segoe UI Semibold", "Microsoft YaHei", "PingFang SC";
                }}
                QWidget#aiAssistantHeaderActions {{
                    background: transparent;
                }}
                QScrollArea#aiAssistantScrollArea {{
                    background: transparent;
                    border: none;
                }}
                QWidget#aiAssistantScrollViewport {{
                    background: transparent;
                }}
                QWidget#aiAssistantMessageContainer {{
                    background: transparent;
                }}
                QScrollArea#aiAssistantScrollArea QScrollBar:vertical {{
                    width: 8px;
                    margin: 8px 0 8px 0;
                    border: none;
                    border-radius: 4px;
                    background: {scrollbar_track};
                }}
                QScrollArea#aiAssistantScrollArea QScrollBar::handle:vertical {{
                    min-height: 28px;
                    border: none;
                    border-radius: 4px;
                    background: {scrollbar_handle};
                }}
                QScrollArea#aiAssistantScrollArea QScrollBar::add-line:vertical,
                QScrollArea#aiAssistantScrollArea QScrollBar::sub-line:vertical,
                QScrollArea#aiAssistantScrollArea QScrollBar::add-page:vertical,
                QScrollArea#aiAssistantScrollArea QScrollBar::sub-page:vertical {{
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
