"""Message composer with an integrated toolbar and input surface."""

from __future__ import annotations

from dataclasses import dataclass
import os
import time

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
    QPolygon,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextImageFormat,
)
from PySide6.QtWidgets import (
    QFrame,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyleOption,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    Flyout,
    FlyoutAnimationType,
    FlyoutViewBase,
    FluentIcon,
    InfoBar,
    PushButton,
    ScrollArea,
    SegmentedWidget,
    TextEdit,
    TransparentToolButton,
)

from client.models.message import MessageType, infer_message_type_from_path
from client.ui.common.attachment_card import attachment_card_size, draw_attachment_card
from client.ui.styles import StyleSheet

ATTACHMENT_ID_PROP = int(QTextFormat.Property.UserProperty) + 1
ATTACHMENT_PATH_PROP = int(QTextFormat.Property.UserProperty) + 2
ATTACHMENT_TYPE_PROP = int(QTextFormat.Property.UserProperty) + 3
ATTACHMENT_WIDTH_PROP = int(QTextFormat.Property.UserProperty) + 4
ATTACHMENT_HEIGHT_PROP = int(QTextFormat.Property.UserProperty) + 5
ATTACHMENT_NAME_PROP = int(QTextFormat.Property.UserProperty) + 6


@dataclass
class InlineAttachment:
    """Attachment metadata stored outside the QTextDocument but referenced by inline object id."""

    attachment_id: str
    file_path: str
    message_type: MessageType
    display_name: str
    preview: QPixmap
    rendered_preview: QPixmap | None = None


class InlineAttachmentWidget(QWidget):
    """Attachment preview rendered as a real widget over the text editor viewport."""

    activated = Signal(str, str)

    def __init__(self, attachment: InlineAttachment, parent=None):
        super().__init__(parent)
        self._attachment = attachment
        self._preview = attachment.rendered_preview or QPixmap()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_attachment(self, attachment: InlineAttachment) -> None:
        """Refresh the preview widget with new attachment state."""
        self._attachment = attachment
        self._preview = attachment.rendered_preview or QPixmap()
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self._attachment.file_path, self._attachment.message_type.value)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if not self._preview.isNull():
            painter.drawPixmap(self.rect(), self._preview)
        painter.end()


class ChatTextEdit(TextEdit):
    """Text editor that sends on Enter and inserts a newline on Shift+Enter."""

    send_requested = Signal()
    attachment_activated = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._attachments: dict[str, InlineAttachment] = {}
        self._attachment_widgets: dict[str, InlineAttachmentWidget] = {}
        self._attachment_sync_pending = False
        self.document().contentsChanged.connect(self._schedule_attachment_widget_sync)
        self.verticalScrollBar().valueChanged.connect(self._schedule_attachment_widget_sync)
        self.horizontalScrollBar().valueChanged.connect(self._schedule_attachment_widget_sync)
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Emit send on Enter without modifiers."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            event.accept()
            self.send_requested.emit()
            return

        if event.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete) and not event.modifiers():
            if self._handle_attachment_delete(event.key()):
                event.accept()
                return

        super().keyPressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept local file drags so they can be inserted as inline attachments."""
        if self._extract_local_files(event.mimeData()):
            event.acceptProposedAction()
            return

        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        """Keep accepting local file drags while hovering over the editor."""
        if self._extract_local_files(event.mimeData()):
            event.acceptProposedAction()
            return

        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        """Insert local file drops as inline attachments instead of raw paths."""
        file_paths = self._extract_local_files(event.mimeData())
        if file_paths:
            event.acceptProposedAction()
            cursor = self.cursorForPosition(event.position().toPoint()) if hasattr(event, "position") else self.textCursor()
            self.setTextCursor(cursor)
            for file_path in file_paths:
                self.insert_local_attachment(file_path)
            return

        super().dropEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        """Let embedded attachment widgets handle their own click events."""
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event) -> None:
        """Keep embedded attachment widgets aligned while the editor resizes."""
        super().resizeEvent(event)
        self._schedule_attachment_widget_sync()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        """Keep embedded attachment widgets aligned while the editor scrolls."""
        super().scrollContentsBy(dx, dy)
        self._schedule_attachment_widget_sync()

    def insert_local_attachment(self, file_path: str) -> None:
        """Insert a local file as an inline attachment token at the current cursor position."""
        normalized = os.path.normpath(file_path)
        if not normalized:
            return

        attachment = self._build_attachment(normalized)
        if attachment is None:
            return

        self._attachments[attachment.attachment_id] = attachment
        attachment.rendered_preview = self._build_inline_preview(attachment)
        resource_name = f"attachment://{attachment.attachment_id}"
        width, height = self._attachment_size(attachment.message_type)
        placeholder = QPixmap(width, height)
        placeholder.fill(Qt.GlobalColor.transparent)
        self.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl(resource_name), placeholder)

        cursor = self.textCursor()
        image_format = QTextImageFormat()
        image_format.setName(resource_name)
        image_format.setProperty(ATTACHMENT_NAME_PROP, attachment.display_name)
        image_format.setProperty(ATTACHMENT_ID_PROP, attachment.attachment_id)
        image_format.setProperty(ATTACHMENT_PATH_PROP, attachment.file_path)
        image_format.setProperty(ATTACHMENT_TYPE_PROP, attachment.message_type.value)
        image_format.setAnchor(True)
        image_format.setAnchorHref(resource_name)

        image_format.setWidth(width)
        image_format.setHeight(height)
        image_format.setProperty(ATTACHMENT_WIDTH_PROP, width)
        image_format.setProperty(ATTACHMENT_HEIGHT_PROP, height)

        cursor.insertImage(image_format)
        self.setTextCursor(cursor)
        self._schedule_attachment_widget_sync()

    def take_composed_segments(self) -> list[dict]:
        """Extract text and inline attachments in document order, then clear the editor."""
        segments: list[dict] = []
        text_buffer: list[str] = []
        document = self.document()
        block = document.begin()

        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    char_format = fragment.charFormat()
                    if self._is_attachment_format(char_format):
                        self._flush_text_buffer(text_buffer, segments)
                        attachment = self._attachment_from_char_format(char_format)
                        if attachment:
                            segments.append(
                                {
                                    "type": attachment.message_type,
                                    "file_path": attachment.file_path,
                                }
                            )
                    else:
                        text_buffer.append(fragment.text())
                iterator += 1

            if block.next().isValid():
                text_buffer.append("\n")
            block = block.next()

        self._flush_text_buffer(text_buffer, segments)
        self.clear_composer()
        return segments

    def clear_composer(self) -> None:
        """Clear both text and inline attachment state."""
        self.clear()
        self._attachments.clear()
        self._clear_attachment_widgets()

    def _handle_attachment_delete(self, key: int) -> bool:
        """Delete a neighboring inline attachment token with Backspace/Delete."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            super().keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))
            return True

        probe_pos = cursor.position() - 1 if key == Qt.Key.Key_Backspace else cursor.position()
        attachment = self._attachment_at_document_position(probe_pos)
        if attachment is None:
            return False

        removal_cursor = self.textCursor()
        if key == Qt.Key.Key_Backspace:
            removal_cursor.setPosition(max(0, probe_pos))
            removal_cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
        else:
            removal_cursor.setPosition(max(0, probe_pos))
            removal_cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
        removal_cursor.removeSelectedText()
        self._attachments.pop(attachment.attachment_id, None)
        widget = self._attachment_widgets.pop(attachment.attachment_id, None)
        if widget is not None:
            widget.deleteLater()
        self._schedule_attachment_widget_sync()
        return True

    @staticmethod
    def _extract_local_files(mime_data) -> list[str]:
        """Return local file paths from a mime payload, ignoring plain text URLs."""
        if not mime_data or not mime_data.hasUrls():
            return []

        file_paths: list[str] = []
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile().strip()
            if path:
                file_paths.append(path)
        return file_paths

    def _attachment_at_document_position(self, position: int) -> InlineAttachment | None:
        """Resolve inline attachment metadata by document character position."""
        if position < 0:
            return None
        cursor = QTextCursor(self.document())
        cursor.setPosition(position)
        char_format = cursor.charFormat()
        return self._attachment_from_char_format(char_format)

    def _schedule_attachment_widget_sync(self) -> None:
        """Defer attachment widget positioning until Qt finishes the current layout pass."""
        if self._attachment_sync_pending:
            return
        self._attachment_sync_pending = True
        QTimer.singleShot(0, self._sync_attachment_widgets)

    def _sync_attachment_widgets(self) -> None:
        """Create, place, and remove embedded attachment widgets to match the document."""
        self._attachment_sync_pending = False
        document_attachment_ids: set[str] = set()

        for document_position, attachment in self._iter_attachment_positions():
            attachment_id = attachment.attachment_id
            if attachment_id in document_attachment_ids:
                continue
            document_attachment_ids.add(attachment_id)

            rect = self._attachment_rect_in_viewport(document_position, attachment)
            widget = self._attachment_widgets.get(attachment_id)
            if rect is None:
                if widget is not None:
                    widget.hide()
                continue

            if widget is None:
                widget = InlineAttachmentWidget(attachment, self.viewport())
                widget.activated.connect(self.attachment_activated.emit)
                self._attachment_widgets[attachment_id] = widget
            else:
                widget.set_attachment(attachment)

            widget.setGeometry(
                round(rect.x()),
                round(rect.y()),
                max(1, round(rect.width())),
                max(1, round(rect.height())),
            )
            widget.show()
            widget.raise_()

        for attachment_id, widget in list(self._attachment_widgets.items()):
            if attachment_id not in document_attachment_ids:
                widget.deleteLater()
                self._attachment_widgets.pop(attachment_id, None)

    def _clear_attachment_widgets(self) -> None:
        """Destroy all embedded attachment widgets immediately."""
        for widget in self._attachment_widgets.values():
            widget.deleteLater()
        self._attachment_widgets.clear()

    def _build_attachment(self, file_path: str) -> InlineAttachment | None:
        """Build attachment metadata and preview from a local file path."""
        if not os.path.exists(file_path):
            return None

        message_type = infer_message_type_from_path(file_path)
        return InlineAttachment(
            attachment_id=f"att-{time.time_ns()}",
            file_path=file_path,
            message_type=message_type,
            display_name=os.path.basename(file_path) or "Attachment",
            preview=QPixmap(),
        )

    @staticmethod
    def _attachment_size(message_type: MessageType) -> tuple[int, int]:
        """Return inline attachment object size."""
        return attachment_card_size()

    def _attachment_rect_in_viewport(self, position: int, attachment: InlineAttachment) -> QRectF | None:
        """Return the exact inline attachment rect in viewport coordinates."""
        document = self.document()
        if position < 0 or position >= max(0, document.characterCount() - 1):
            return None

        current_cursor = QTextCursor(document)
        current_cursor.setPosition(position)
        current_rect = self.cursorRect(current_cursor)
        if current_rect.isNull():
            return None

        next_position = min(position + 1, max(0, document.characterCount() - 1))
        next_cursor = QTextCursor(document)
        next_cursor.setPosition(next_position)
        next_rect = self.cursorRect(next_cursor)

        stored_width = float(
            current_cursor.charFormat().property(ATTACHMENT_WIDTH_PROP)
            or self._attachment_size(attachment.message_type)[0]
        )
        stored_height = float(
            current_cursor.charFormat().property(ATTACHMENT_HEIGHT_PROP)
            or self._attachment_size(attachment.message_type)[1]
        )

        same_line = abs(next_rect.center().y() - current_rect.center().y()) < max(2.0, current_rect.height() / 2)
        if same_line:
            left = float(min(current_rect.x(), next_rect.x()))
        else:
            left = float(current_rect.x())
        width = stored_width

        top = current_rect.center().y() - stored_height / 2
        return QRectF(left, top, width, stored_height)

    def _build_inline_preview(self, attachment: InlineAttachment) -> QPixmap:
        """Render a visible inline preview pixmap for the attachment."""
        width, height = self._attachment_size(attachment.message_type)
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        draw_attachment_card(
            painter,
            QRectF(0, 0, width, height),
            message_type=attachment.message_type,
            display_name=attachment.display_name,
            file_path=attachment.file_path,
            dark=self._is_dark(),
        )

        painter.end()
        return pixmap

    @staticmethod
    def _cover_source_rect(source_size, target_size) -> QRectF:
        source_width = max(1, source_size.width())
        source_height = max(1, source_size.height())
        target_width = max(1, target_size.width())
        target_height = max(1, target_size.height())
        source_ratio = source_width / source_height
        target_ratio = target_width / target_height

        if source_ratio > target_ratio:
            crop_width = max(1, int(round(source_height * target_ratio)))
            crop_x = max(0, (source_width - crop_width) // 2)
            return QRectF(crop_x, 0, crop_width, source_height)

        crop_height = max(1, int(round(source_width / target_ratio)))
        crop_y = max(0, (source_height - crop_height) // 2)
        return QRectF(0, crop_y, source_width, crop_height)

    @staticmethod
    def _draw_video_play(painter: QPainter, rect: QRectF) -> None:
        circle_size = 24
        circle_rect = QRectF(
            rect.center().x() - circle_size / 2,
            rect.center().y() - circle_size / 2,
            circle_size,
            circle_size,
        )
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 110))
        painter.drawEllipse(circle_rect)
        triangle = QPolygon(
            [
                QPoint(int(circle_rect.center().x() - 3), int(circle_rect.center().y() - 5)),
                QPoint(int(circle_rect.center().x() - 3), int(circle_rect.center().y() + 5)),
                QPoint(int(circle_rect.center().x() + 5), int(circle_rect.center().y())),
            ]
        )
        painter.setBrush(QColor(255, 255, 255))
        painter.drawPolygon(triangle)
        painter.restore()

    @staticmethod
    def _rounded_rect_path(rect: QRectF, radius: float):
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path

    @staticmethod
    def _is_dark() -> bool:
        palette = QPalette()
        return palette.color(QPalette.ColorRole.Window).lightness() < 128

    @staticmethod
    def _is_attachment_format(char_format: QTextCharFormat) -> bool:
        """Return whether a char format represents one of our inline attachments."""
        return bool(char_format.property(ATTACHMENT_ID_PROP))

    def _attachment_from_char_format(self, char_format: QTextCharFormat) -> InlineAttachment | None:
        """Rebuild attachment metadata directly from the QTextDocument format properties."""
        if not self._is_attachment_format(char_format):
            return None

        attachment_id = str(char_format.property(ATTACHMENT_ID_PROP) or "")
        file_path = str(char_format.property(ATTACHMENT_PATH_PROP) or "")
        message_type_value = str(char_format.property(ATTACHMENT_TYPE_PROP) or "")
        display_name = str(char_format.property(ATTACHMENT_NAME_PROP) or "") or os.path.basename(file_path)
        if not attachment_id or not file_path or not message_type_value:
            return None

        try:
            message_type = MessageType(message_type_value)
        except ValueError:
            return None

        cached = self._attachments.get(attachment_id)
        if cached is not None:
            if cached.rendered_preview is None or cached.rendered_preview.isNull():
                cached.rendered_preview = self._build_inline_preview(cached)
            return cached

        rebuilt = self._build_attachment(file_path)
        if rebuilt is not None:
            rebuilt.attachment_id = attachment_id
            rebuilt.message_type = message_type
            rebuilt.display_name = display_name
            rebuilt.rendered_preview = self._build_inline_preview(rebuilt)
            self._attachments[attachment_id] = rebuilt
            return rebuilt

        fallback = InlineAttachment(
            attachment_id=attachment_id,
            file_path=file_path,
            message_type=message_type,
            display_name=display_name,
            preview=QPixmap(),
            rendered_preview=QPixmap(*self._attachment_size(message_type)),
        )
        fallback.rendered_preview.fill(Qt.GlobalColor.transparent)
        self._attachments[attachment_id] = fallback
        return fallback

    def _attachment_from_href(self, href: str) -> InlineAttachment | None:
        """Resolve an attachment directly from its inline anchor href."""
        if not href or not href.startswith("attachment://"):
            return None

        attachment_id = href.split("attachment://", 1)[1]
        if not attachment_id:
            return None

        cached = self._attachments.get(attachment_id)
        if cached is not None:
            return cached

        block = self.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    attachment = self._attachment_from_char_format(fragment.charFormat())
                    if attachment and attachment.attachment_id == attachment_id:
                        return attachment
                iterator += 1
            block = block.next()

        return None

    def _iter_attachment_positions(self):
        """Yield every inline attachment together with its current document position."""
        block = self.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    attachment = self._attachment_from_char_format(fragment.charFormat())
                    if attachment is not None:
                        fragment_position = fragment.position()
                        for offset, _ in enumerate(fragment.text()):
                            yield fragment_position + offset, attachment
                iterator += 1
            block = block.next()

    @staticmethod
    def _flush_text_buffer(text_buffer: list[str], segments: list[dict]) -> None:
        """Flush a buffered text chunk into the composed segment list."""
        if not text_buffer:
            return

        text = "".join(text_buffer)
        text_buffer.clear()
        if text.strip():
            segments.append({"type": MessageType.TEXT, "content": text})


class LegacyEmojiPickerFlyout(FlyoutViewBase):
    """Compact emoji picker used by the message input toolbar."""

    emoji_selected = Signal(str)

    EMOJIS = [
        "😀",
        "😁",
        "😂",
        "🤣",
        "😊",
        "😍",
        "😘",
        "😎",
        "🤔",
        "😴",
        "😭",
        "😡",
        "👍",
        "👀",
        "🎉",
        "❤️",
        "🔥",
        "✨",
        "🙏",
        "💡",
        "📷",
        "🎵",
        "🌙",
        "🌟",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.view_layout = QVBoxLayout(self)
        self.view_layout.setContentsMargins(12, 12, 12, 12)
        self.view_layout.setSpacing(10)

        grid_widget = QWidget(self)
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setHorizontalSpacing(6)
        grid_layout.setVerticalSpacing(6)

        for index, emoji in enumerate(self.EMOJIS):
            button = PushButton(emoji, grid_widget)
            button.setFixedSize(44, 36)
            button.clicked.connect(lambda _checked=False, value=emoji: self.emoji_selected.emit(value))
            grid_layout.addWidget(button, index // 8, index % 8)

        self.view_layout.addWidget(grid_widget)


class EmojiTile(QLabel):
    """Lightweight clickable emoji tile."""

    clicked = Signal(str)
    _VERTICAL_NUDGE = -1

    def __init__(self, emoji: str, parent=None):
        super().__init__("", parent)
        self._emoji = emoji
        self.setObjectName("emojiTile")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(48, 52)
        self.setToolTip(emoji)

        font = QFont(self.font())
        font.setPointSize(19)
        try:
            font.setFamilies(["Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji"])
        except AttributeError:
            font.setFamily("Segoe UI Emoji")
        self.setFont(font)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._emoji)
            event.accept()
            return

        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        option = QStyleOption()
        option.initFrom(self)

        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setFont(self.font())

        metrics = painter.fontMetrics()
        x = round((self.width() - metrics.horizontalAdvance(self._emoji)) / 2)
        y = round((self.height() + metrics.ascent() - metrics.descent()) / 2) + self._VERTICAL_NUDGE
        painter.drawText(x, y, self._emoji)
        painter.end()


class ModernEmojiPickerFlyout(FlyoutViewBase):
    """Grouped emoji picker that keeps the popup fast by building pages lazily."""

    emoji_selected = Signal(str)

    EMOJI_GROUPS = [
        (
            "smileys",
            "Smileys",
            [
                "\U0001F600", "\U0001F603", "\U0001F604", "\U0001F601", "\U0001F606", "\U0001F605", "\U0001F602", "\U0001F923",
                "\U0001F642", "\U0001F643", "\U0001FAE0", "\U0001F609", "\U0001F60A", "\U0001F607", "\U0001F970", "\U0001F60D",
                "\U0001F929", "\U0001F618", "\U0001F617", "\u263A\ufe0f", "\U0001F61A", "\U0001F619", "\U0001F60B", "\U0001F61B",
                "\U0001F61C", "\U0001F92A", "\U0001F61D", "\U0001F911", "\U0001F917", "\U0001F92D", "\U0001FAE2", "\U0001F92B",
                "\U0001F914", "\U0001FAE1", "\U0001F910", "\U0001F928", "\U0001F610", "\U0001F611", "\U0001F636", "\U0001FAE5",
            ],
        ),
        (
            "hands",
            "Hands",
            [
                "\U0001F44B", "\U0001F91A", "\U0001F590\ufe0f", "\u270B", "\U0001F596", "\U0001FAF1", "\U0001FAF2", "\U0001FAF3",
                "\U0001FAF4", "\U0001FAF7", "\U0001FAF8", "\U0001F44C", "\U0001F90F", "\u270C\ufe0f", "\U0001F91E", "\U0001F918",
                "\U0001F919", "\U0001F448", "\U0001F449", "\U0001F446", "\U0001F595", "\U0001F447", "\u261D\ufe0f", "\U0001FAF0",
                "\U0001F44D", "\U0001F44E", "\u270A", "\U0001F44A", "\U0001F91B", "\U0001F91C", "\U0001F64C", "\U0001F450",
                "\U0001FAF6", "\U0001F932", "\U0001F91D", "\U0001F64F", "\U0001FAF5", "\U0001F9BE", "\U0001F9BF", "\U0001F4AA",
            ],
        ),
        (
            "people",
            "People",
            [
                "\U0001F64B", "\U0001F64E", "\U0001F645", "\U0001F646", "\U0001F481", "\U0001F647", "\U0001F926", "\U0001F937",
                "\U0001F9D1", "\U0001F468", "\U0001F469", "\U0001F9D4", "\U0001F9D3", "\U0001F9D2", "\U0001F476", "\U0001F475",
                "\U0001F474", "\U0001F471", "\U0001F472", "\U0001F473", "\U0001F477", "\U0001F482", "\U0001F575\ufe0f", "\U0001F46E",
                "\U0001F934", "\U0001F385", "\U0001F936", "\U0001F9D9", "\U0001F9DA", "\U0001F9DB", "\U0001F9DC", "\U0001F9DD",
                "\U0001F9D1\u200d\U0001F4BB", "\U0001F9D1\u200d\U0001F3A8", "\U0001F9D1\u200d\U0001F680", "\U0001F9D1\u200d\U0001F373",
                "\U0001F9D1\u200d\U0001F3EB", "\U0001F46B", "\U0001F46A", "\U0001FAC2",
            ],
        ),
        (
            "animals",
            "Animals",
            [
                "\U0001F436", "\U0001F431", "\U0001F42D", "\U0001F439", "\U0001F430", "\U0001F98A", "\U0001F43B", "\U0001F43C",
                "\U0001F428", "\U0001F42F", "\U0001F981", "\U0001F42E", "\U0001F437", "\U0001F438", "\U0001F435", "\U0001F648",
                "\U0001F649", "\U0001F64A", "\U0001F412", "\U0001F414", "\U0001F427", "\U0001F426", "\U0001F424", "\U0001F986",
                "\U0001F985", "\U0001F989", "\U0001F99C", "\U0001F433", "\U0001F40B", "\U0001F42C", "\U0001F41F", "\U0001F420",
                "\U0001F99E", "\U0001F990", "\U0001F98B", "\U0001F40C", "\U0001F41E", "\U0001F41D", "\U0001F41B", "\U0001F98B",
            ],
        ),
        (
            "food",
            "Food",
            [
                "\U0001F34E", "\U0001F34A", "\U0001F349", "\U0001F347", "\U0001F353", "\U0001FAD0", "\U0001F965", "\U0001F951",
                "\U0001F346", "\U0001F954", "\U0001F955", "\U0001F33D", "\U0001F336\ufe0f", "\U0001FAD1", "\U0001F950", "\U0001F96F",
                "\U0001F95E", "\U0001F956", "\U0001F968", "\U0001F9C0", "\U0001F356", "\U0001F357", "\U0001F969", "\U0001F953",
                "\U0001F35F", "\U0001F355", "\U0001F354", "\U0001F32D", "\U0001F96A", "\U0001F35C", "\U0001F35D", "\U0001F363",
                "\U0001F371", "\U0001F35B", "\U0001F961", "\U0001F372", "\U0001F95F", "\U0001F9C1", "\U0001F36A", "\U0001F382",
            ],
        ),
        (
            "symbols",
            "Symbols",
            [
                "\u2764\ufe0f", "\U0001F9E1", "\U0001F49B", "\U0001F49A", "\U0001F499", "\U0001F49C", "\U0001F90E", "\U0001F5A4",
                "\U0001FA76", "\U0001F498", "\U0001F49D", "\U0001F496", "\U0001F497", "\U0001F493", "\U0001F49E", "\U0001F495",
                "\U0001F4AF", "\U0001F4A2", "\U0001F4A5", "\U0001F4AB", "\U0001F4A6", "\U0001F4A8", "\U0001F300", "\u2B50",
                "\U0001F31F", "\u2728", "\u26A1", "\u2604\ufe0f", "\U0001F525", "\U0001F4A9", "\U0001F389", "\U0001F38A",
                "\U0001F380", "\U0001F381", "\U0001F3C6", "\U0001F3C5", "\U0001F3C1", "\U0001F680", "\U0001F6A8", "\U0001F514",
            ],
        ),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._group_emoji_map = {route_key: emojis for route_key, _label, emojis in self.EMOJI_GROUPS}
        self._containers: dict[str, QWidget] = {}
        self._container_layouts: dict[str, QVBoxLayout] = {}
        self._built_pages: set[str] = set()
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setObjectName("emojiPickerFlyout")
        self.view_layout = QVBoxLayout(self)
        self.view_layout.setContentsMargins(12, 12, 12, 12)
        self.view_layout.setSpacing(8)

        self.group_tabs = SegmentedWidget(self)
        self.group_tabs.setObjectName("emojiGroupTabs")
        self.view_layout.addWidget(self.group_tabs)

        self.page_stack = QStackedWidget(self)
        self.page_stack.setObjectName("emojiPageStack")
        self.view_layout.addWidget(self.page_stack, 1)

        for route_key, label, _emojis in self.EMOJI_GROUPS:
            container = QWidget(self.page_stack)
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(0)
            self._containers[route_key] = container
            self._container_layouts[route_key] = container_layout
            self.page_stack.addWidget(container)
            self.group_tabs.addItem(route_key, label, lambda _checked=False, key=route_key: self._switch_group(key))

        first_group = self.EMOJI_GROUPS[0][0]
        self._switch_group(first_group)
        self.group_tabs.setCurrentItem(first_group)
        StyleSheet.MESSAGE_INPUT.apply(self)

    def _switch_group(self, route_key: str) -> None:
        if route_key not in self._containers:
            return
        self._ensure_page(route_key)
        self.page_stack.setCurrentWidget(self._containers[route_key])
        self.group_tabs.setCurrentItem(route_key)

    def _ensure_page(self, route_key: str) -> None:
        if route_key in self._built_pages:
            return

        emojis = self._group_emoji_map.get(route_key)
        if emojis is None:
            return

        scroll_area = ScrollArea(self._containers[route_key])
        scroll_area.setObjectName("emojiScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget(scroll_area)
        content.setObjectName("emojiScrollContent")
        grid_layout = QGridLayout(content)
        grid_layout.setContentsMargins(4, 4, 4, 4)
        grid_layout.setHorizontalSpacing(4)
        grid_layout.setVerticalSpacing(4)

        columns = 8
        for index, emoji in enumerate(emojis):
            tile = EmojiTile(emoji, content)
            tile.clicked.connect(self.emoji_selected.emit)
            grid_layout.addWidget(tile, index // columns, index % columns)

        grid_layout.setRowStretch((len(emojis) + columns - 1) // columns, 1)
        scroll_area.setWidget(content)
        self._container_layouts[route_key].addWidget(scroll_area)
        self._built_pages.add(route_key)


class MessageInput(QWidget):
    """Integrated message input surface."""

    segments_submitted = Signal(object)
    attachment_open_requested = Signal(str, str)
    screenshot_requested = Signal()
    voice_call_requested = Signal()
    video_call_requested = Signal()
    typing_signal = Signal()

    IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp)"
    FILE_FILTER = "All Files (*.*)"
    TYPING_THROTTLE = 3.0
    def __init__(self, parent=None):
        super().__init__(parent)

        self._last_typing_time = 0.0
        self._session_active = False
        self._emoji_flyout = None
        self._setup_ui()
        self._connect_signals()
        self.set_session_active(False)
        QTimer.singleShot(0, self._update_overlay_positions)

    def _setup_ui(self) -> None:
        self.setObjectName("messageInput")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(180)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.editor_card = QWidget(self)
        self.editor_card.setObjectName("messageInputCard")
        self.editor_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.card_layout = QVBoxLayout(self.editor_card)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(0)

        self.composer_widget = QWidget(self.editor_card)
        self.composer_widget.setObjectName("messageComposer")
        self.composer_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.composer_layout = QVBoxLayout(self.composer_widget)
        self.composer_layout.setContentsMargins(0, 0, 0, 0)
        self.composer_layout.setSpacing(0)

        self.toolbar_widget = QWidget(self.composer_widget)
        self.toolbar_widget.setObjectName("messageToolbar")
        self.toolbar_layout = QHBoxLayout()
        self.toolbar_layout.setContentsMargins(4, 4, 4, 4)
        self.toolbar_layout.setSpacing(4)

        self.emoji_button = TransparentToolButton(FluentIcon.EMOJI_TAB_SYMBOLS, self.composer_widget)
        self.emoji_button.setFixedSize(28, 28)
        self.emoji_button.setToolTip("Emoji")

        self.image_button = TransparentToolButton(FluentIcon.PHOTO, self.composer_widget)
        self.image_button.setFixedSize(28, 28)
        self.image_button.setToolTip("Send image")

        self.file_button = TransparentToolButton(FluentIcon.FOLDER, self.composer_widget)
        self.file_button.setFixedSize(28, 28)
        self.file_button.setToolTip("Send file")

        self.cut_button = TransparentToolButton(FluentIcon.CUT, self.composer_widget)
        self.cut_button.setFixedSize(28, 28)
        self.cut_button.setToolTip("Screenshot")

        self.voice_button = TransparentToolButton(FluentIcon.PHONE, self.composer_widget)
        self.voice_button.setFixedSize(28, 28)
        self.voice_button.setToolTip("Voice call")

        self.video_button = TransparentToolButton(FluentIcon.VIDEO, self.composer_widget)
        self.video_button.setFixedSize(28, 28)
        self.video_button.setToolTip("Video call")

        self.ai_button = TransparentToolButton(FluentIcon.ROBOT, self.composer_widget)
        self.ai_button.setFixedSize(28, 28)
        self.ai_button.setToolTip("AI assistant")

        self._apply_safe_button_font(
            self.emoji_button,
            self.image_button,
            self.file_button,
            self.cut_button,
            self.voice_button,
            self.video_button,
            self.ai_button,
        )

        self.toolbar_layout.addWidget(self.emoji_button)
        self.toolbar_layout.addWidget(self.image_button)
        self.toolbar_layout.addWidget(self.file_button)
        self.toolbar_layout.addWidget(self.cut_button)
        self.toolbar_layout.addWidget(self.voice_button)
        self.toolbar_layout.addWidget(self.video_button)
        self.toolbar_layout.addWidget(self.ai_button)
        self.toolbar_layout.addStretch(1)

        self.text_input = ChatTextEdit(self.composer_widget)
        self.text_input.setObjectName("chatMessageEdit")
        self.text_input.viewport().setObjectName("chatMessageViewport")
        self.text_input.setPlaceholderText("Select a session to start chatting")
        self.text_input.setAcceptRichText(False)
        self.text_input.setMinimumHeight(128)
        self.text_input.setViewportMargins(0, 0, 92, 8)
        self._apply_editor_transparency()

        self.send_button = PushButton("Send", self.composer_widget)
        self.send_button.setObjectName("composerSendButton")
        self.send_button.setFixedSize(84, 34)

        self.toolbar_widget.setLayout(self.toolbar_layout)

        self.composer_layout.addWidget(self.toolbar_widget, 0)
        self.composer_layout.addWidget(self.text_input, 1)
        self.card_layout.addWidget(self.composer_widget, 1)
        self.main_layout.addWidget(self.editor_card, 1)
        self.composer_widget.installEventFilter(self)
        self.text_input.installEventFilter(self)
        StyleSheet.MESSAGE_INPUT.apply(self)
        self._apply_editor_transparency()

        self._update_overlay_positions()

    def _apply_safe_button_font(self, *buttons: TransparentToolButton) -> None:
        """Ensure toolbar buttons expose a valid point-size font for tooltip rendering."""
        font = QFont(self.font())
        if font.pointSize() <= 0:
            if font.pixelSize() > 0:
                font.setPointSize(max(9, round(font.pixelSize() * 0.75)))
            else:
                font.setPointSize(10)

        for button in buttons:
            button.setFont(font)

    def _apply_editor_transparency(self) -> None:
        """Force the text editor and its viewport to render with a transparent background."""
        self.text_input.setFrameShape(QFrame.Shape.NoFrame)
        self.text_input.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.text_input.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.text_input.viewport().setAutoFillBackground(False)
        self.text_input.setStyleSheet(
            "QTextEdit { border: none !important; background-color: transparent !important; border-radius: 0; }"
            "QTextEdit:hover { background-color: transparent !important; border: none !important; }"
            "QTextEdit:focus { background-color: transparent !important; border: none !important; }"
        )
        self.text_input.viewport().setStyleSheet("border: none !important; background-color: transparent !important;")

        palette = self.text_input.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
        palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
        self.text_input.setPalette(palette)

        viewport_palette = self.text_input.viewport().palette()
        viewport_palette.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
        viewport_palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
        self.text_input.viewport().setPalette(viewport_palette)

    def _connect_signals(self) -> None:
        self.send_button.clicked.connect(self._on_send_clicked)
        self.emoji_button.clicked.connect(self._on_emoji_clicked)
        self.image_button.clicked.connect(self._on_image_clicked)
        self.file_button.clicked.connect(self._on_file_clicked)
        self.cut_button.clicked.connect(self.screenshot_requested.emit)
        self.voice_button.clicked.connect(self.voice_call_requested.emit)
        self.video_button.clicked.connect(self.video_call_requested.emit)
        self.ai_button.clicked.connect(self._on_placeholder_action)
        self.text_input.textChanged.connect(self._on_text_changed)
        self.text_input.send_requested.connect(self._on_send_clicked)
        self.text_input.attachment_activated.connect(self._on_attachment_activated)

    def resizeEvent(self, event) -> None:
        """Keep the floating footer aligned with the text input."""
        super().resizeEvent(event)
        self._update_overlay_positions()

    def showEvent(self, event) -> None:
        """Refresh overlay positions once the widget is shown."""
        super().showEvent(event)
        self._apply_editor_transparency()
        QTimer.singleShot(0, self._update_overlay_positions)

    def eventFilter(self, watched, event) -> bool:
        """Refresh floating controls after internal layout resizes."""
        if watched in {self.composer_widget, self.text_input} and event.type() in {QEvent.Type.Resize, QEvent.Type.Show}:
            QTimer.singleShot(0, self._update_overlay_positions)
        return super().eventFilter(watched, event)

    def _update_overlay_positions(self) -> None:
        """Place the send button inside the text input area."""
        text_rect = self.text_input.geometry()
        if not text_rect.isValid():
            return

        button_margin_right = 10
        button_margin_bottom = 8
        send_x = text_rect.right() - self.send_button.width() - button_margin_right
        send_y = text_rect.bottom() - self.send_button.height() - button_margin_bottom
        self.send_button.move(send_x, send_y)

        self.send_button.raise_()

    def _on_text_changed(self) -> None:
        """Emit throttled typing events."""
        current_time = time.time()
        if current_time - self._last_typing_time >= self.TYPING_THROTTLE:
            self._last_typing_time = current_time
            self.typing_signal.emit()

    def _on_send_clicked(self) -> None:
        """Extract composed segments and hand them to the chat panel."""
        segments = self.text_input.take_composed_segments()
        if not segments:
            return
        self.segments_submitted.emit(segments)

    def _on_emoji_clicked(self) -> None:
        """Show emoji picker flyout."""
        if self._emoji_flyout is not None and self._emoji_flyout.isVisible():
            self._emoji_flyout.close()

        picker = ModernEmojiPickerFlyout(self)
        picker.emoji_selected.connect(self._insert_emoji)
        self._emoji_flyout = Flyout.make(
            picker,
            self.emoji_button,
            self,
            aniType=FlyoutAnimationType.PULL_UP,
        )
        picker.emoji_selected.connect(self._emoji_flyout.close)
        self._emoji_flyout.closed.connect(lambda: setattr(self, "_emoji_flyout", None))

    def _insert_emoji(self, emoji: str) -> None:
        """Insert emoji at current cursor position."""
        cursor = self.text_input.textCursor()
        cursor.insertText(emoji)
        self.text_input.setTextCursor(cursor)
        self.text_input.setFocus()

    def _on_image_clicked(self) -> None:
        """Insert selected image into the editor as an inline attachment."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select image", "", self.IMAGE_FILTER)
        if file_path:
            self.text_input.insert_local_attachment(file_path)
            self.text_input.setFocus()

    def _on_file_clicked(self) -> None:
        """Insert selected file into the editor as an inline attachment."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select file", "", self.FILE_FILTER)
        if file_path:
            self.text_input.insert_local_attachment(file_path)
            self.text_input.setFocus()

    def _on_attachment_activated(self, file_path: str, message_type: str) -> None:
        """Forward inline attachment open requests to the chat panel."""
        self.attachment_open_requested.emit(file_path, message_type)

    def _on_placeholder_action(self) -> None:
        """Show temporary placeholder hint for unsupported toolbar actions."""
        InfoBar.info(
            "Notice",
            "This toolbar action is not connected yet.",
            parent=self.window(),
            duration=1800,
        )

    def set_session_active(self, active: bool) -> None:
        """Enable or disable the editor depending on session selection."""
        self._session_active = active

        self.emoji_button.setEnabled(active)
        self.image_button.setEnabled(active)
        self.file_button.setEnabled(active)
        self.cut_button.setEnabled(active)
        self.voice_button.setEnabled(active)
        self.video_button.setEnabled(active)
        self.ai_button.setEnabled(active)
        self.text_input.setEnabled(active)
        self.send_button.setEnabled(active)

        if active:
            self.text_input.setPlaceholderText("Enter to send, Shift+Enter for new line")
        else:
            self.text_input.setPlaceholderText("Select a session to start chatting")
            self.text_input.clear_composer()

    def focus_editor(self) -> None:
        """Focus the text editor."""
        if self._session_active:
            self.text_input.setFocus()

    def get_text_input(self) -> TextEdit:
        """Get text input widget."""
        return self.text_input

    def get_send_button(self) -> PushButton:
        """Get send button widget."""
        return self.send_button

    def get_emoji_button(self) -> TransparentToolButton:
        """Get emoji button widget."""
        return self.emoji_button

    def get_file_button(self) -> TransparentToolButton:
        """Get file button widget."""
        return self.file_button

    def get_image_button(self) -> TransparentToolButton:
        """Get image button widget."""
        return self.image_button
