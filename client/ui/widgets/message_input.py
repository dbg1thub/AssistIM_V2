"""Message composer with an integrated toolbar and input surface."""

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Any, Optional

from PySide6.QtCore import QByteArray, QEvent, QMimeData, QPoint, QPointF, QRect, QRectF, QSize, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
    QPen,
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    Flyout,
    FlyoutAnimationType,
    FlyoutViewBase,
    InfoBar,
    IconWidget,
    PushButton,
    RoundMenu,
    ScrollArea,
    SegmentedWidget,
    TransparentToolButton,
    isDarkTheme,
    qconfig, ToolTipPosition,
)
from qfluentwidgets.components.material import AcrylicToolTipFilter, AcrylicFlyoutViewBase, AcrylicFlyout

from client.core.app_icons import AppIcon
from client.core.avatar_rendering import get_avatar_image_store
from client.core.avatar_utils import profile_avatar_seed
from client.core.i18n import tr
from client.models.message import MessageType, Session, infer_message_type_from_path, normalize_message_mentions
from client.ui.common.attachment_card import attachment_card_size, draw_attachment_card
from client.ui.common.emoji_names import emoji_display_name
from client.ui.common.emoji_utils import (
    COMPOSER_EMOJI_PIXEL_SIZE,
    centered_emoji_top,
    is_emoji_char,
    iter_text_and_emoji_clusters,
    load_emoji_pixmap,
)
from client.core.video_thumbnail_cache import get_thumbnail as get_video_thumbnail, get_video_thumbnail_cache
from client.ui.styles import StyleSheet
from client.ui.widgets.chat_info_drawer import AcrylicDrawerSurface
from client.ui.widgets.composer_clipboard import (
    COMPOSER_SEGMENTS_MIME,
    clipboard_file_paths,
    clipboard_plain_text,
    deserialize_clipboard_segments,
    serialize_clipboard_segments,
)
from client.ui.widgets.composer_layout import centered_inline_object_top, inline_object_line_metrics

ATTACHMENT_ID_PROP = int(QTextFormat.Property.UserProperty) + 1
ATTACHMENT_PATH_PROP = int(QTextFormat.Property.UserProperty) + 2
ATTACHMENT_TYPE_PROP = int(QTextFormat.Property.UserProperty) + 3
ATTACHMENT_WIDTH_PROP = int(QTextFormat.Property.UserProperty) + 4
ATTACHMENT_HEIGHT_PROP = int(QTextFormat.Property.UserProperty) + 5
ATTACHMENT_NAME_PROP = int(QTextFormat.Property.UserProperty) + 6
EMOJI_ID_PROP = int(QTextFormat.Property.UserProperty) + 7
EMOJI_VALUE_PROP = int(QTextFormat.Property.UserProperty) + 8
ATTACHMENT_RENDER_HEIGHT_PROP = int(QTextFormat.Property.UserProperty) + 9


@dataclass
class InlineAttachment:
    """Attachment metadata stored outside the QTextDocument but referenced by inline object id."""

    attachment_id: str
    file_path: str
    message_type: MessageType
    display_name: str


@dataclass
class InlineEmoji:
    """Emoji metadata represented as an inline object inside the composer."""

    emoji_id: str
    value: str


@dataclass(frozen=True)
class MentionCandidate:
    """One selectable @ mention candidate shown above the composer."""

    member_id: str
    display_name: str
    username: str = ""
    avatar: str = ""
    gender: str = ""
    is_everyone: bool = False


@dataclass(frozen=True)
class MentionToken:
    """Structured @ mention token tracked outside QTextDocument formatting."""

    start: int
    end: int
    display_name: str
    mention_type: str = "member"
    member_id: str = ""


class MentionAvatarWidget(QWidget):
    """Rounded-rect avatar used by mention candidates."""

    def __init__(
        self,
        avatar: str,
        *,
        gender: str = "",
        seed: str = "",
        size: int = 28,
        radius: int = 8,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._source = str(avatar or "")
        self._gender = str(gender or "")
        self._seed = str(seed or "")
        self._radius = max(0, int(radius))
        self._store = get_avatar_image_store()
        self._store.avatar_ready.connect(self._handle_avatar_ready)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(path)

        _source, display_path = self._store.resolve_display_path(self._source, gender=self._gender, seed=self._seed)
        pixmap = QPixmap(display_path) if display_path else QPixmap()
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(self.rect(), scaled)
        else:
            painter.fillPath(path, QColor("#626B76") if isDarkTheme() else QColor("#D7DEE8"))

        painter.setClipping(False)
        if pixmap.isNull():
            initial = (self._seed or "?")[:1].upper()
            font = QFont()
            font.setPixelSize(14)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, initial)
        painter.end()

    def _handle_avatar_ready(self, source: str) -> None:
        if str(source or "") == self._source:
            self.update()


def _preferred_member_name(member: dict[str, Any]) -> str:
    """Resolve one stable group-member display name for @ mention choices."""
    return (
        str(member.get("remark", "") or "").strip()
        or str(member.get("group_nickname", "") or "").strip()
        or str(member.get("nickname", "") or "").strip()
        or str(member.get("display_name", "") or "").strip()
        or str(member.get("username", "") or "").strip()
        or str(member.get("id", "") or "").strip()
    )


def _mention_search_tokens(candidate: MentionCandidate) -> tuple[str, ...]:
    """Return lowercase search tokens used by the @ suggestion filter."""
    tokens = [candidate.display_name, candidate.username]
    if candidate.is_everyone:
        tokens.extend(["all", "all members", "所有人"])
    return tuple(token.lower() for token in tokens if str(token or "").strip())


def _mention_payload_from_candidate(candidate: MentionCandidate, start: int, end: int) -> dict[str, object]:
    """Build one normalized structured mention payload from a selected candidate."""
    payload: dict[str, object] = {
        "start": start,
        "end": end,
        "display_name": candidate.display_name,
        "mention_type": "all" if candidate.is_everyone else "member",
    }
    if not candidate.is_everyone:
        payload["member_id"] = candidate.member_id
    return payload


class InlineAttachmentWidget(QWidget):
    """Attachment preview rendered as a real widget over the text editor viewport."""

    activated = Signal(str, str)
    IMAGE_SIZE = QSize(132, 132)
    VIDEO_SIZE = QSize(176, 100)
    FILE_SIZE = QSize(*attachment_card_size())
    CARD_RADIUS = 12

    def __init__(self, attachment: InlineAttachment, parent=None):
        super().__init__(parent)
        self._attachment = attachment
        self._video_thumbnail_cache = get_video_thumbnail_cache()
        self._video_thumbnail_cache.signals.thumbnail_ready.connect(self._on_video_thumbnail_ready)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_attachment(self, attachment: InlineAttachment) -> None:
        """Refresh the preview widget with new attachment state."""
        self._attachment = attachment
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self._attachment.file_path, self._attachment.message_type.value)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._attachment.message_type == MessageType.FILE:
            draw_attachment_card(
                painter,
                QRectF(self.rect()),
                message_type=self._attachment.message_type,
                display_name=self._attachment.display_name,
                file_path=self._attachment.file_path,
                dark=isDarkTheme(),
            )
        elif self._attachment.message_type == MessageType.IMAGE:
            self._draw_image_card(painter)
        else:
            self._draw_video_card(painter)
        painter.end()

    def _draw_image_card(self, painter: QPainter) -> None:
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self.CARD_RADIUS, self.CARD_RADIUS)
        pixmap = QPixmap(self._attachment.file_path)
        if pixmap.isNull():
            painter.fillPath(path, QColor(255, 255, 255, 20) if isDarkTheme() else QColor(0, 0, 0, 10))
            painter.setPen(QColor(220, 220, 220) if isDarkTheme() else QColor("#666666"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Image")
            return
        source_rect = self._cover_source_rect(pixmap.size(), self.size())
        painter.save()
        painter.setClipPath(path)
        painter.drawPixmap(self.rect(), pixmap, source_rect)
        painter.restore()

    def _draw_video_card(self, painter: QPainter) -> None:
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self.CARD_RADIUS, self.CARD_RADIUS)
        thumbnail = get_video_thumbnail(self._attachment.file_path)
        if thumbnail is None:
            self._video_thumbnail_cache.request_thumbnail(self._attachment.file_path)
            painter.fillPath(path, QColor(255, 255, 255, 18) if isDarkTheme() else QColor(0, 0, 0, 10))
            painter.setPen(QColor(220, 220, 220) if isDarkTheme() else QColor("#666666"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Video")
        else:
            source_rect = self._cover_source_rect(thumbnail.size(), self.size())
            painter.save()
            painter.setClipPath(path)
            painter.drawPixmap(self.rect(), thumbnail, source_rect)
            painter.restore()
        painter.fillRect(self.rect(), QColor(0, 0, 0, 24))
        self._draw_play_button(painter)

    def _on_video_thumbnail_ready(self, source: str) -> None:
        if os.path.normcase(source) == os.path.normcase(self._attachment.file_path):
            self.update()

    @staticmethod
    def _cover_source_rect(source_size: QSize, target_size: QSize) -> QRect:
        source_width = max(1, source_size.width())
        source_height = max(1, source_size.height())
        target_width = max(1, target_size.width())
        target_height = max(1, target_size.height())
        source_ratio = source_width / source_height
        target_ratio = target_width / target_height
        if source_ratio > target_ratio:
            crop_height = source_height
            crop_width = round(crop_height * target_ratio)
            crop_x = max(0, (source_width - crop_width) // 2)
            return QRect(crop_x, 0, crop_width, crop_height)
        crop_width = source_width
        crop_height = round(crop_width / target_ratio)
        crop_y = max(0, (source_height - crop_height) // 2)
        return QRect(0, crop_y, crop_width, crop_height)

    def _draw_play_button(self, painter: QPainter) -> None:
        circle_size = 32
        circle_rect = QRect(
            self.rect().center().x() - circle_size // 2,
            self.rect().center().y() - circle_size // 2,
            circle_size,
            circle_size,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 110))
        painter.drawEllipse(circle_rect)

        triangle = QPainterPath()
        triangle.moveTo(circle_rect.center().x() - 4, circle_rect.center().y() - 7)
        triangle.lineTo(circle_rect.center().x() - 4, circle_rect.center().y() + 7)
        triangle.lineTo(circle_rect.center().x() + 7, circle_rect.center().y())
        triangle.closeSubpath()
        painter.fillPath(triangle, QColor(255, 255, 255))


class InlineEmojiWidget(QWidget):
    """Emoji preview rendered as a real widget over the text editor viewport."""

    def __init__(self, emoji: InlineEmoji, parent=None):
        super().__init__(parent)
        self._emoji = emoji
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_emoji(self, emoji: InlineEmoji) -> None:
        """Refresh the widget with the latest emoji metadata."""
        self._emoji = emoji
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        target_size = min(COMPOSER_EMOJI_PIXEL_SIZE, max(12, self.width() - 1), max(12, self.height() - 2))
        pixmap = load_emoji_pixmap(self._emoji.value, target_size, target_size)
        if not pixmap.isNull():
            x = round((self.width() - pixmap.width()) / 2)
            y = round((self.height() - pixmap.height()) / 2)
            painter.drawPixmap(x, y, pixmap)
        else:
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            font = ChatTextEdit._build_emoji_font()
            painter.setFont(font)
            painter.setPen(self.palette().color(QPalette.ColorRole.Text))
            painter.drawText(self.rect().adjusted(0, -1, -2, 1), Qt.AlignmentFlag.AlignCenter, self._emoji.value)
        painter.end()


class ChatTextEdit(QTextEdit):
    """Text editor that sends on Enter and inserts a newline on Shift+Enter."""

    send_requested = Signal()
    attachment_activated = Signal(str, str)
    files_dropped = Signal(object)
    _ATTACHMENT_VERTICAL_PADDING = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._editor_font = self._build_editor_font()
        self.setFont(self._editor_font)
        self.document().setDefaultFont(self._editor_font)
        self.document().setDocumentMargin(5)
        self._attachments: dict[str, InlineAttachment] = {}
        self._attachment_widgets: dict[str, InlineAttachmentWidget] = {}
        self._emoji_objects: dict[str, InlineEmoji] = {}
        self._emoji_widgets: dict[str, InlineEmojiWidget] = {}
        self._mention_tokens: list[MentionToken] = []
        self._attachment_sync_pending = False
        self._inline_emoji_sync_pending = False
        self._applying_inline_emoji_sync = False
        self.document().contentsChanged.connect(self._schedule_attachment_widget_sync)
        self.document().contentsChange.connect(self._on_document_contents_change)
        self.verticalScrollBar().valueChanged.connect(self._schedule_attachment_widget_sync)
        self.horizontalScrollBar().valueChanged.connect(self._schedule_attachment_widget_sync)
        self.textChanged.connect(self._schedule_inline_emoji_sync)

    def _reset_cursor_to_plain_text(self, cursor: QTextCursor | None = None) -> QTextCursor:
        """Reset a cursor format so following text won't inherit inline object properties."""
        cursor = QTextCursor(cursor or self.textCursor())
        plain_format = QTextCharFormat()
        plain_format.setFont(self._editor_font)
        plain_format.setForeground(self.palette().color(QPalette.ColorRole.Text))
        cursor.setCharFormat(plain_format)
        self.setTextCursor(cursor)
        return cursor

    def _on_document_contents_change(self, position: int, chars_removed: int, chars_added: int) -> None:
        """Shift or drop tracked mention tokens after one document edit."""
        if not self._mention_tokens:
            return

        edit_start = max(0, int(position or 0))
        removed = max(0, int(chars_removed or 0))
        delta = max(0, int(chars_added or 0)) - removed
        edit_end = edit_start + removed
        updated_tokens: list[MentionToken] = []

        for token in self._mention_tokens:
            if token.end <= edit_start:
                updated_tokens.append(token)
                continue

            if token.start >= edit_end:
                updated_tokens.append(
                    MentionToken(
                        start=token.start + delta,
                        end=token.end + delta,
                        display_name=token.display_name,
                        mention_type=token.mention_type,
                        member_id=token.member_id,
                    )
                )
                continue

        if updated_tokens != self._mention_tokens:
            self._mention_tokens = updated_tokens
            self._refresh_mention_selections()

    def _refresh_mention_selections(self) -> None:
        """Paint mention runs using transient editor selections instead of document formatting."""
        selection_color = QColor("#3B82F6") if not self._is_dark() else QColor("#8AB4F8")
        selections: list[QTextEdit.ExtraSelection] = []
        document_limit = max(0, self.document().characterCount() - 1)

        for token in self._mention_tokens:
            if token.start < 0 or token.end <= token.start or token.start >= document_limit:
                continue

            cursor = QTextCursor(self.document())
            cursor.setPosition(token.start)
            cursor.setPosition(min(token.end, document_limit), QTextCursor.MoveMode.KeepAnchor)
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format.setForeground(selection_color)
            selections.append(selection)

        self.setExtraSelections(selections)

    def _sorted_mention_tokens(self) -> list[MentionToken]:
        """Return mention tokens in document order."""
        return sorted(self._mention_tokens, key=lambda token: (token.start, token.end))

    def _add_mention_token(self, token: MentionToken) -> None:
        """Track one new mention token and refresh editor decorations."""
        self._mention_tokens = sorted(
            [
                existing
                for existing in self._mention_tokens
                if existing.end <= token.start or existing.start >= token.end
            ]
            + [token],
            key=lambda item: (item.start, item.end),
        )
        self._refresh_mention_selections()

    def _mention_token_at(self, position: int) -> MentionToken | None:
        """Return the mention token that covers the given document cursor position, if any."""
        for token in self._mention_tokens:
            if token.start <= position < token.end:
                return token
        return None

    @staticmethod
    def _build_editor_font() -> QFont:
        """Return the editor font with emoji-capable fallbacks."""
        font = QFont()
        font.setPixelSize(16)
        try:
            font.setFamilies(
                [
                    "Segoe UI",
                    "Microsoft YaHei UI",
                    "Segoe UI Emoji",
                    "Apple Color Emoji",
                    "Noto Color Emoji",
                ]
            )
        except AttributeError:
            font.setFamily("Segoe UI")
        return font

    @staticmethod
    def _build_emoji_font() -> QFont:
        """Return a larger emoji font while keeping ordinary text at the normal size."""
        font = QFont()
        font.setPixelSize(COMPOSER_EMOJI_PIXEL_SIZE)
        try:
            font.setFamilies(
                [
                    "Segoe UI Emoji",
                    "Apple Color Emoji",
                    "Noto Color Emoji",
                    "Segoe UI",
                    "Microsoft YaHei UI",
                ]
            )
        except AttributeError:
            font.setFamily("Segoe UI Emoji")
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.5)
        return font

    @staticmethod
    def _emoji_size() -> tuple[int, int]:
        """Return the fixed inline object size used for composer emoji."""
        # Keep the composer emoji box tight so adjacent emoji don't look spaced
        # out, while still leaving a little vertical room for stable alignment.
        return COMPOSER_EMOJI_PIXEL_SIZE + 1, COMPOSER_EMOJI_PIXEL_SIZE + 3

    @staticmethod
    def _attachment_vertical_alignment():
        """Return the safest bottom-style inline alignment supported by the runtime."""
        return getattr(
            QTextCharFormat.VerticalAlignment,
            "AlignBaseline",
            QTextCharFormat.VerticalAlignment.AlignMiddle,
        )
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
        """Forward local file drops to the outer composer so attachments stay in the editor flow."""
        file_paths = self._extract_local_files(event.mimeData())
        if file_paths:
            event.acceptProposedAction()
            self.files_dropped.emit(file_paths)
            return

        super().dropEvent(event)

    def canInsertFromMimeData(self, source: QMimeData) -> bool:
        """Accept composer clipboard payloads in addition to normal Qt text and file data."""
        if source is not None and source.hasFormat(COMPOSER_SEGMENTS_MIME):
            return True
        if self._extract_local_files(source):
            return True
        return super().canInsertFromMimeData(source)

    def createMimeDataFromSelection(self) -> QMimeData:
        """Serialize mixed composer selections so attachments and emoji survive copy/paste."""
        mime_data = super().createMimeDataFromSelection()
        selection_cursor = self.textCursor()
        if not selection_cursor.hasSelection():
            return mime_data

        segments = self._collect_selected_segments(selection_cursor)
        if not segments:
            return mime_data

        mime_data.setData(COMPOSER_SEGMENTS_MIME, QByteArray(serialize_clipboard_segments(segments)))
        plain_text = clipboard_plain_text(segments)
        if plain_text:
            mime_data.setText(plain_text)

        file_urls = [QUrl.fromLocalFile(file_path) for file_path in clipboard_file_paths(segments)]
        if file_urls:
            mime_data.setUrls(file_urls)
        return mime_data

    def insertFromMimeData(self, source: QMimeData) -> None:
        """Restore mixed composer selections before falling back to Qt's default paste behavior."""
        segments = self._segments_from_mime(source)
        if segments:
            self._replace_selection_with_segments(segments)
            return

        file_paths = self._extract_local_files(source)
        if file_paths:
            for file_path in file_paths:
                self.insert_local_attachment(file_path, blockify=False)
            return

        super().insertFromMimeData(source)

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

    def insert_local_attachment(self, file_path: str, *, blockify: bool = False) -> None:
        """Insert a local file as an attachment object that participates in editor flow."""
        normalized = os.path.normpath(file_path)
        if not normalized:
            return

        attachment = self._build_attachment(normalized)
        if attachment is None:
            return

        self._attachments[attachment.attachment_id] = attachment
        resource_name = f"attachment://{attachment.attachment_id}"
        card_width, render_height = self._attachment_size(attachment.message_type)
        placeholder_height = self._attachment_placeholder_height(render_height)
        placeholder = QPixmap(card_width, placeholder_height)
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
        image_format.setVerticalAlignment(self._attachment_vertical_alignment())

        image_format.setWidth(card_width)
        image_format.setHeight(placeholder_height)
        image_format.setProperty(ATTACHMENT_WIDTH_PROP, card_width)
        image_format.setProperty(ATTACHMENT_HEIGHT_PROP, placeholder_height)
        image_format.setProperty(ATTACHMENT_RENDER_HEIGHT_PROP, render_height)

        cursor.insertImage(image_format)
        self._reset_cursor_to_plain_text(cursor)
        self._schedule_attachment_widget_sync()

    def insert_inline_emoji(self, emoji: str) -> None:
        """Insert an emoji as a true inline object instead of a plain text glyph."""
        if not emoji:
            return

        inline_emoji = InlineEmoji(
            emoji_id=f"emoji-{time.time_ns()}",
            value=emoji,
        )
        self._emoji_objects[inline_emoji.emoji_id] = inline_emoji
        resource_name = f"emoji://{inline_emoji.emoji_id}"
        width, height = self._emoji_size()
        placeholder = QPixmap(width, height)
        placeholder.fill(Qt.GlobalColor.transparent)
        self.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl(resource_name), placeholder)

        cursor = self.textCursor()
        image_format = QTextImageFormat()
        image_format.setName(resource_name)
        image_format.setProperty(EMOJI_ID_PROP, inline_emoji.emoji_id)
        image_format.setProperty(EMOJI_VALUE_PROP, inline_emoji.value)
        image_format.setAnchor(True)
        image_format.setAnchorHref(resource_name)
        image_format.setVerticalAlignment(self._attachment_vertical_alignment())
        image_format.setWidth(width)
        image_format.setHeight(height)
        cursor.insertImage(image_format)
        self._reset_cursor_to_plain_text(cursor)
        self._schedule_attachment_widget_sync()

    def take_composed_segments(self) -> list[dict]:
        """Extract text and inline attachments in document order, then clear the editor."""
        return self._extract_composed_segments(clear_after=True)

    def collect_composed_segments(self) -> list[dict]:
        """Collect text and inline attachments in document order without clearing the editor."""
        return self._extract_composed_segments(clear_after=False)

    def restore_composed_segments(self, segments: list[dict]) -> None:
        """Restore a previously captured mixed text and attachment draft."""
        self._insert_composed_segments(segments or [], clear_first=True)

    def _extract_composed_segments(self, *, clear_after: bool) -> list[dict]:
        """Extract text and inline attachments in document order."""
        segments: list[dict] = []
        text_buffer: list[str] = []
        segment_fragments: list[dict[str, object]] = []
        document = self.document()
        block = document.begin()

        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    char_format = fragment.charFormat()
                    if self._is_attachment_format(char_format):
                        self._flush_text_buffer(text_buffer, segment_fragments, segments)
                        attachment = self._attachment_from_char_format(char_format)
                        if attachment:
                            segments.append(
                                {
                                    "type": attachment.message_type,
                                    "file_path": attachment.file_path,
                                }
                            )
                    elif self._is_inline_emoji_format(char_format):
                        inline_emoji = self._emoji_from_char_format(char_format)
                        if inline_emoji:
                            fragment_position = fragment.position()
                            fragment_text = inline_emoji.value
                            text_buffer.append(fragment_text)
                            segment_fragments.append(
                                {
                                    "kind": "emoji",
                                    "doc_start": fragment_position,
                                    "doc_end": fragment_position + fragment.length(),
                                    "text": fragment_text,
                                    "py_start": len("".join(text_buffer[:-1])),
                                }
                            )
                    else:
                        fragment_text = fragment.text()
                        text_buffer.append(fragment_text)
                        segment_fragments.append(
                            {
                                "kind": "text",
                                "doc_start": fragment.position(),
                                "doc_end": fragment.position() + fragment.length(),
                                "text": fragment_text,
                                "py_start": len("".join(text_buffer[:-1])),
                            }
                        )
                iterator += 1

            if block.next().isValid():
                text_buffer.append("\n")
                block_end = block.position() + max(0, block.length() - 1)
                segment_fragments.append(
                    {
                        "kind": "text",
                        "doc_start": block_end,
                        "doc_end": block_end + 1,
                        "text": "\n",
                        "py_start": len("".join(text_buffer[:-1])),
                    }
                )
            block = block.next()

        self._flush_text_buffer(text_buffer, segment_fragments, segments)
        segments = self._normalize_attachment_boundary_newlines(segments)
        if clear_after:
            self.clear_composer()
        return segments

    def _collect_selected_segments(self, selection_cursor: QTextCursor) -> list[dict]:
        """Extract mixed segments from the current selection without normalizing whitespace."""
        if selection_cursor is None or not selection_cursor.hasSelection():
            return []
        return self._extract_selected_segments(selection_cursor.selectionStart(), selection_cursor.selectionEnd())

    def _extract_selected_segments(self, selection_start: int, selection_end: int) -> list[dict]:
        """Extract a lossless segment list for clipboard copy from a document range."""
        if selection_end <= selection_start:
            return []

        segments: list[dict] = []
        text_buffer: list[str] = []
        segment_fragments: list[dict[str, object]] = []
        document = self.document()
        block = document.findBlock(selection_start)
        if not block.isValid():
            block = document.begin()

        while block.isValid():
            if block.position() >= selection_end:
                break

            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    fragment_start = fragment.position()
                    fragment_end = fragment_start + fragment.length()
                    overlap_start = max(selection_start, fragment_start)
                    overlap_end = min(selection_end, fragment_end)
                    if overlap_start < overlap_end:
                        char_format = fragment.charFormat()
                        if self._is_attachment_format(char_format):
                            self._flush_selection_text_buffer(text_buffer, segment_fragments, segments)
                            attachment = self._attachment_from_char_format(char_format)
                            if attachment:
                                segments.append(
                                    {
                                        "type": attachment.message_type,
                                        "file_path": attachment.file_path,
                                        "display_name": attachment.display_name,
                                    }
                                )
                        elif self._is_inline_emoji_format(char_format):
                            inline_emoji = self._emoji_from_char_format(char_format)
                            if inline_emoji:
                                fragment_text = inline_emoji.value
                                text_buffer.append(fragment_text)
                                segment_fragments.append(
                                    {
                                        "kind": "emoji",
                                        "doc_start": overlap_start,
                                        "doc_end": overlap_end,
                                        "text": fragment_text,
                                        "py_start": len("".join(text_buffer[:-1])),
                                    }
                                )
                        else:
                            fragment_text = fragment.text()
                            selected_text = self._slice_text_by_qt_positions(
                                fragment_text,
                                overlap_start - fragment_start,
                                overlap_end - fragment_start,
                            )
                            if selected_text:
                                text_buffer.append(selected_text)
                                segment_fragments.append(
                                    {
                                        "kind": "text",
                                        "doc_start": overlap_start,
                                        "doc_end": overlap_end,
                                        "text": selected_text,
                                        "py_start": len("".join(text_buffer[:-1])),
                                    }
                                )
                iterator += 1

            next_block = block.next()
            block_separator_position = block.position() + max(0, block.length() - 1)
            if next_block.isValid() and selection_start <= block_separator_position < selection_end:
                text_buffer.append("\n")
                segment_fragments.append(
                    {
                        "kind": "text",
                        "doc_start": block_separator_position,
                        "doc_end": block_separator_position + 1,
                        "text": "\n",
                        "py_start": len("".join(text_buffer[:-1])),
                    }
                )

            if not next_block.isValid() or next_block.position() >= selection_end:
                break
            block = next_block

        self._flush_selection_text_buffer(text_buffer, segment_fragments, segments)
        return segments

    def _segments_from_mime(self, mime_data: QMimeData | None) -> list[dict]:
        """Decode the app-private composer clipboard payload, if present."""
        if mime_data is None or not mime_data.hasFormat(COMPOSER_SEGMENTS_MIME):
            return []
        return deserialize_clipboard_segments(bytes(mime_data.data(COMPOSER_SEGMENTS_MIME)))

    def _replace_selection_with_segments(self, segments: list[dict]) -> None:
        """Replace the current selection with a previously copied mixed segment payload."""
        if not segments:
            return

        cursor = QTextCursor(self.textCursor())
        cursor.beginEditBlock()
        if cursor.hasSelection():
            cursor.removeSelectedText()
        self.setTextCursor(cursor)
        self._insert_composed_segments(segments, clear_first=False)
        cursor = QTextCursor(self.textCursor())
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        self._schedule_attachment_widget_sync()

    def _insert_composed_segments(self, segments: list[dict], *, clear_first: bool) -> None:
        """Insert a mixed text/attachment segment list into the composer."""
        if clear_first:
            self.clear_composer()
        if not segments:
            return

        cursor = self.textCursor()
        self.setTextCursor(cursor)

        for segment in segments:
            segment_type = segment.get("type")
            if isinstance(segment_type, str):
                try:
                    segment_type = MessageType(segment_type)
                except ValueError:
                    continue

            if segment_type == MessageType.TEXT:
                content = str(segment.get("content", "") or "")
                if content:
                    mentions = dict(segment.get("extra") or {}).get("mentions")
                    self._insert_mixed_text_segment(content, cursor=cursor, mentions=mentions)
                    cursor = QTextCursor(self.textCursor())
                continue

            file_path = str(segment.get("file_path", "") or "")
            if file_path:
                self.insert_local_attachment(file_path, blockify=False)
                cursor = QTextCursor(self.textCursor())

    @staticmethod
    def _slice_text_by_qt_positions(text: str, start: int, end: int) -> str:
        """Slice a Python string using Qt UTF-16 cursor offsets."""
        if not text or end <= start:
            return ""

        cursor_units = 0
        sliced_chars: list[str] = []
        for char in text:
            char_units = 2 if ord(char) > 0xFFFF else 1
            next_cursor_units = cursor_units + char_units
            if next_cursor_units <= start:
                cursor_units = next_cursor_units
                continue
            if cursor_units >= end:
                break
            if start < next_cursor_units and end > cursor_units:
                sliced_chars.append(char)
            cursor_units = next_cursor_units
        return "".join(sliced_chars)

    def has_meaningful_content(self) -> bool:
        """Return whether the composer currently contains sendable content."""
        plain_text = self.toPlainText().replace("\uFFFC", "").strip()
        return bool(plain_text) or bool(self._attachments) or bool(self._emoji_objects)

    @staticmethod
    def _qt_text_length(text: str) -> int:
        """Return the UTF-16 code-unit length Qt uses for cursor positions."""
        length = 0
        for char in text or "":
            length += 2 if ord(char) > 0xFFFF else 1
        return length

    def _schedule_inline_emoji_sync(self) -> None:
        """Normalize raw emoji text into inline emoji objects after the current edit completes."""
        if self._applying_inline_emoji_sync or self._inline_emoji_sync_pending:
            return
        self._inline_emoji_sync_pending = True
        QTimer.singleShot(0, self._sync_inline_emoji_objects)

    def _sync_inline_emoji_objects(self) -> None:
        """Replace raw emoji glyphs in the document with inline emoji objects."""
        self._inline_emoji_sync_pending = False
        if self._applying_inline_emoji_sync:
            return

        self._applying_inline_emoji_sync = True
        saved_cursor = QTextCursor(self.textCursor())

        try:
            while True:
                replacement = self._find_plain_text_fragment_with_emoji()
                if replacement is None:
                    break

                start, text = replacement
                cursor = QTextCursor(self.document())
                cursor.setPosition(start)
                cursor.setPosition(start + self._qt_text_length(text), QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
                self._insert_mixed_text_segment(text, cursor=cursor)
        finally:
            self.setTextCursor(saved_cursor)
            self._reset_cursor_to_plain_text()
            self._applying_inline_emoji_sync = False

    def clear_composer(self) -> None:
        """Clear both text and inline attachment state."""
        self.clear()
        self._attachments.clear()
        self._emoji_objects.clear()
        self._mention_tokens.clear()
        self._refresh_mention_selections()
        self._clear_attachment_widgets()
        self._reset_cursor_to_plain_text()

    def _handle_attachment_delete(self, key: int) -> bool:
        """Delete a neighboring inline attachment token with Backspace/Delete."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            super().keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))
            self._schedule_attachment_widget_sync()
            return True

        probe_pos = cursor.position() - 1 if key == Qt.Key.Key_Backspace else cursor.position()
        inline_kind = self._inline_object_kind_at_document_position(probe_pos)
        if inline_kind is None:
            return False

        removal_cursor = self.textCursor()
        if key == Qt.Key.Key_Backspace:
            removal_cursor.setPosition(max(0, probe_pos))
            removal_cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
        else:
            removal_cursor.setPosition(max(0, probe_pos))
            removal_cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
        removal_cursor.removeSelectedText()
        if inline_kind[0] == "attachment":
            attachment = inline_kind[1]
            self._attachments.pop(attachment.attachment_id, None)
            widget = self._attachment_widgets.pop(attachment.attachment_id, None)
            if widget is not None:
                widget.deleteLater()
        else:
            inline_emoji = inline_kind[1]
            self._emoji_objects.pop(inline_emoji.emoji_id, None)
            widget = self._emoji_widgets.pop(inline_emoji.emoji_id, None)
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

    def _inline_object_kind_at_document_position(self, position: int):
        """Return the inline object at a document position, attachment or emoji."""
        if position < 0:
            return None
        cursor = QTextCursor(self.document())
        cursor.setPosition(position)
        char_format = cursor.charFormat()
        attachment = self._attachment_from_char_format(char_format)
        if attachment is not None:
            return "attachment", attachment
        inline_emoji = self._emoji_from_char_format(char_format)
        if inline_emoji is not None:
            return "emoji", inline_emoji
        return None

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
        document_emoji_ids: set[str] = set()

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

        for document_position, inline_emoji in self._iter_inline_emoji_positions():
            emoji_id = inline_emoji.emoji_id
            if emoji_id in document_emoji_ids:
                continue
            document_emoji_ids.add(emoji_id)

            rect = self._emoji_rect_in_viewport(document_position, inline_emoji)
            widget = self._emoji_widgets.get(emoji_id)
            if rect is None:
                if widget is not None:
                    widget.hide()
                continue

            if widget is None:
                widget = InlineEmojiWidget(inline_emoji, self.viewport())
                self._emoji_widgets[emoji_id] = widget
            else:
                widget.set_emoji(inline_emoji)

            widget.setGeometry(
                round(rect.x()),
                round(rect.y()),
                max(1, round(rect.width())),
                max(1, round(rect.height())),
            )
            widget.show()
            widget.raise_()

        for emoji_id, widget in list(self._emoji_widgets.items()):
            if emoji_id not in document_emoji_ids:
                widget.deleteLater()
                self._emoji_widgets.pop(emoji_id, None)

        self._prune_orphan_inline_objects(document_attachment_ids, document_emoji_ids)

    def _clear_attachment_widgets(self) -> None:
        """Destroy all embedded attachment widgets immediately."""
        for widget in self._attachment_widgets.values():
            widget.deleteLater()
        self._attachment_widgets.clear()
        for widget in self._emoji_widgets.values():
            widget.deleteLater()
        self._emoji_widgets.clear()

    def _prune_orphan_inline_objects(
        self,
        document_attachment_ids: set[str],
        document_emoji_ids: set[str],
    ) -> None:
        """Drop metadata for inline objects that no longer exist in the document."""
        for attachment_id in list(self._attachments.keys()):
            if attachment_id not in document_attachment_ids:
                self._attachments.pop(attachment_id, None)

        for emoji_id in list(self._emoji_objects.keys()):
            if emoji_id not in document_emoji_ids:
                self._emoji_objects.pop(emoji_id, None)

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
        )

    @staticmethod
    def _attachment_size(message_type: MessageType) -> tuple[int, int]:
        """Return the rendered attachment card size."""
        if message_type == MessageType.IMAGE:
            return InlineAttachmentWidget.IMAGE_SIZE.width(), InlineAttachmentWidget.IMAGE_SIZE.height()
        if message_type == MessageType.VIDEO:
            return InlineAttachmentWidget.VIDEO_SIZE.width(), InlineAttachmentWidget.VIDEO_SIZE.height()
        return attachment_card_size()

    @classmethod
    def _attachment_placeholder_height(cls, render_height: int | float) -> int:
        """Return the line-box height used for attachment rows."""
        return int(max(1, round(float(render_height) + cls._ATTACHMENT_VERTICAL_PADDING * 2)))

    def _document_char_at(self, position: int) -> str:
        """Return the character at the given document position, or an empty string."""
        document = self.document()
        if position < 0 or position >= max(0, document.characterCount() - 1):
            return ""
        return document.characterAt(position)

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

        render_width, fallback_render_height = self._attachment_size(attachment.message_type)
        stored_width = float(current_cursor.charFormat().property(ATTACHMENT_WIDTH_PROP) or render_width)
        stored_placeholder_height = float(
            current_cursor.charFormat().property(ATTACHMENT_HEIGHT_PROP)
            or self._attachment_placeholder_height(fallback_render_height)
        )
        stored_render_height = float(
            current_cursor.charFormat().property(ATTACHMENT_RENDER_HEIGHT_PROP) or fallback_render_height
        )

        left = float(current_rect.x())
        width = stored_width

        line_top, line_bottom = inline_object_line_metrics(
            float(current_rect.top()),
            float(current_rect.bottom()),
            float(next_rect.top()),
            float(next_rect.bottom()),
            float(current_rect.height()),
        )
        top = round(
            centered_inline_object_top(
                line_top,
                line_bottom,
                stored_render_height,
                minimum_line_height=stored_placeholder_height,
            )
        )
        return QRectF(left, top, width, stored_render_height)

    @staticmethod
    def _is_dark() -> bool:
        return isDarkTheme()

    @staticmethod
    def _is_attachment_format(char_format: QTextCharFormat) -> bool:
        """Return whether a char format represents one of our inline attachments."""
        attachment_id = char_format.property(ATTACHMENT_ID_PROP)
        name = str(char_format.property(QTextFormat.Property.ImageName) or "")
        return bool(attachment_id and name.startswith("attachment://"))

    @staticmethod
    def _is_inline_emoji_format(char_format: QTextCharFormat) -> bool:
        """Return whether a char format represents one of our inline emoji objects."""
        emoji_id = char_format.property(EMOJI_ID_PROP)
        name = str(char_format.property(QTextFormat.Property.ImageName) or "")
        return bool(emoji_id and name.startswith("emoji://"))

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
            return cached

        rebuilt = self._build_attachment(file_path)
        if rebuilt is not None:
            rebuilt.attachment_id = attachment_id
            rebuilt.message_type = message_type
            rebuilt.display_name = display_name
            self._attachments[attachment_id] = rebuilt
            return rebuilt

        fallback = InlineAttachment(
            attachment_id=attachment_id,
            file_path=file_path,
            message_type=message_type,
            display_name=display_name,
        )
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

    def _emoji_from_char_format(self, char_format: QTextCharFormat) -> InlineEmoji | None:
        """Rebuild inline emoji metadata directly from the QTextDocument format properties."""
        if not self._is_inline_emoji_format(char_format):
            return None

        emoji_id = str(char_format.property(EMOJI_ID_PROP) or "")
        value = str(char_format.property(EMOJI_VALUE_PROP) or "")
        if not emoji_id or not value:
            return None

        cached = self._emoji_objects.get(emoji_id)
        if cached is not None:
            return cached

        inline_emoji = InlineEmoji(emoji_id=emoji_id, value=value)
        self._emoji_objects[emoji_id] = inline_emoji
        return inline_emoji

    def _iter_inline_emoji_positions(self):
        """Yield every inline emoji together with its current document position."""
        block = self.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    inline_emoji = self._emoji_from_char_format(fragment.charFormat())
                    if inline_emoji is not None:
                        fragment_position = fragment.position()
                        for offset, _ in enumerate(fragment.text()):
                            yield fragment_position + offset, inline_emoji
                iterator += 1
            block = block.next()

    def _emoji_rect_in_viewport(self, position: int, inline_emoji: InlineEmoji) -> QRectF | None:
        """Return the exact inline emoji rect in viewport coordinates."""
        del inline_emoji
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

        width, height = self._emoji_size()
        line_top, line_bottom = inline_object_line_metrics(
            float(current_rect.top()),
            float(current_rect.bottom()),
            float(next_rect.top()),
            float(next_rect.bottom()),
            float(current_rect.height()),
        )
        same_line = line_bottom != float(current_rect.bottom()) or line_top != float(current_rect.top())
        left = float(min(current_rect.x(), next_rect.x()) if same_line else current_rect.x())
        metrics = QFontMetrics(self._editor_font)
        text_top = line_bottom - metrics.height() + 1.0
        top = centered_emoji_top(text_top, metrics.height(), height, vertical_nudge=-2)
        return QRectF(left, float(top), width, height)

    def _insert_mixed_text_segment(
        self,
        text: str,
        cursor: QTextCursor | None = None,
        *,
        mentions: list[dict] | None = None,
    ) -> None:
        """Insert text while converting emoji clusters into inline emoji objects."""
        if not text:
            return

        active_cursor = QTextCursor(cursor or self.textCursor())
        normalized_mentions = normalize_message_mentions(mentions, content=text)
        text_position = 0

        for mention in normalized_mentions:
            mention_start = int(mention["start"])
            mention_end = int(mention["end"])
            if mention_start > text_position:
                active_cursor = self._insert_plain_text_chunk(text[text_position:mention_start], active_cursor)

            mention_text = text[mention_start:mention_end]
            active_cursor = self._insert_structured_mention(mention_text, mention, active_cursor)
            text_position = mention_end

        if text_position < len(text):
            active_cursor = self._insert_plain_text_chunk(text[text_position:], active_cursor)
        self.setTextCursor(active_cursor)

    def _insert_plain_text_chunk(self, text: str, cursor: QTextCursor | None = None) -> QTextCursor:
        """Insert one plain-text chunk while still converting inline emoji objects."""
        active_cursor = QTextCursor(cursor or self.textCursor())
        for chunk, is_emoji_chunk in iter_text_and_emoji_clusters(text):
            if is_emoji_chunk:
                self.setTextCursor(active_cursor)
                self.insert_inline_emoji(chunk)
                active_cursor = self.textCursor()
            else:
                active_cursor.insertText(chunk)
                self.setTextCursor(active_cursor)
        return active_cursor

    def _insert_structured_mention(
        self,
        mention_text: str,
        payload: dict[str, object],
        cursor: QTextCursor | None = None,
    ) -> QTextCursor:
        """Insert one plain-text mention token and track its range outside the document."""
        active_cursor = QTextCursor(cursor or self.textCursor())
        start = active_cursor.position()
        active_cursor.insertText(mention_text)
        end = active_cursor.position()
        self._add_mention_token(
            MentionToken(
                start=start,
                end=end,
                display_name=str(payload.get("display_name", "") or "").strip(),
                mention_type=str(payload.get("mention_type", "") or "member").strip().lower() or "member",
                member_id=str(payload.get("member_id", "") or "").strip(),
            )
        )
        self.setTextCursor(active_cursor)
        return self._reset_cursor_to_plain_text(active_cursor)

    def _find_plain_text_fragment_with_emoji(self) -> tuple[int, str] | None:
        """Return the first normal text fragment that still contains raw emoji glyphs."""
        block = self.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    char_format = fragment.charFormat()
                    if self._is_attachment_format(char_format) or self._is_inline_emoji_format(char_format):
                        iterator += 1
                        continue

                    text = fragment.text()
                    if any(is_emoji_char(char) for char in text):
                        return fragment.position(), text
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

    def _mentions_for_segment(self, text: str, segment_fragments: list[dict[str, object]]) -> list[dict[str, object]]:
        """Project tracked document mention tokens into one extracted text segment."""
        if not text or not segment_fragments or not self._mention_tokens:
            return []

        segment_start = min(int(fragment["doc_start"]) for fragment in segment_fragments)
        segment_end = max(int(fragment["doc_end"]) for fragment in segment_fragments)
        mentions: list[dict[str, object]] = []

        for token in self._sorted_mention_tokens():
            if token.start < segment_start or token.end > segment_end:
                continue

            mention = {
                "start": self._segment_py_index_for_doc_position(segment_fragments, token.start),
                "end": self._segment_py_index_for_doc_position(segment_fragments, token.end),
                "display_name": token.display_name,
                "mention_type": token.mention_type,
            }
            if token.mention_type == "member":
                mention["member_id"] = token.member_id
            mentions.append(mention)

        return normalize_message_mentions(mentions, content=text)

    def _segment_py_index_for_doc_position(
        self,
        segment_fragments: list[dict[str, object]],
        document_position: int,
    ) -> int:
        """Map one document UTF-16 cursor position into a segment-local Python string index."""
        for fragment in segment_fragments:
            fragment_start = int(fragment["doc_start"])
            fragment_end = int(fragment["doc_end"])
            fragment_text = str(fragment["text"])
            fragment_kind = str(fragment.get("kind", "text"))
            py_start = int(fragment["py_start"])
            if document_position < fragment_start:
                return py_start
            if fragment_start <= document_position <= fragment_end:
                if fragment_kind != "text":
                    return py_start if document_position <= fragment_start else py_start + len(fragment_text)
                qt_offset = max(0, min(document_position - fragment_start, fragment_end - fragment_start))
                return py_start + len(self._slice_text_by_qt_positions(fragment_text, 0, qt_offset))

        if not segment_fragments:
            return 0
        last_fragment = segment_fragments[-1]
        return int(last_fragment["py_start"]) + len(str(last_fragment["text"]))

    def _flush_text_buffer(
        self,
        text_buffer: list[str],
        segment_fragments: list[dict[str, object]],
        segments: list[dict],
    ) -> None:
        """Flush a buffered text chunk into the composed segment list."""
        if not text_buffer:
            return

        text = "".join(text_buffer)
        text_buffer.clear()
        mentions = self._mentions_for_segment(text, segment_fragments)
        segment_fragments.clear()
        if text.strip():
            segment = {"type": MessageType.TEXT, "content": text}
            if mentions:
                segment["extra"] = {"mentions": mentions}
            segments.append(segment)

    def _flush_selection_text_buffer(
        self,
        text_buffer: list[str],
        segment_fragments: list[dict[str, object]],
        segments: list[dict],
    ) -> None:
        """Flush clipboard-selected text without trimming whitespace-only segments."""
        if not text_buffer:
            return

        text = "".join(text_buffer)
        text_buffer.clear()
        mentions = self._mentions_for_segment(text, segment_fragments)
        segment_fragments.clear()
        if text:
            segment = {"type": MessageType.TEXT, "content": text}
            if mentions:
                segment["extra"] = {"mentions": mentions}
            segments.append(segment)

    @staticmethod
    def _normalize_attachment_boundary_newlines(segments: list[dict]) -> list[dict]:
        """Trim structural newlines around attachment segments so send/restore stay stable."""
        normalized = [dict(segment) for segment in segments]
        attachment_types = {MessageType.IMAGE, MessageType.VIDEO, MessageType.FILE}

        for index, segment in enumerate(normalized):
            if segment.get("type") not in attachment_types:
                continue

            if index > 0 and normalized[index - 1].get("type") == MessageType.TEXT:
                previous_content = str(normalized[index - 1].get("content", "") or "")
                normalized[index - 1]["content"] = previous_content.rstrip("\n")

            if index + 1 < len(normalized) and normalized[index + 1].get("type") == MessageType.TEXT:
                next_content = str(normalized[index + 1].get("content", "") or "")
                normalized[index + 1]["content"] = next_content.lstrip("\n")

        return [
            segment
            for segment in normalized
            if segment.get("type") != MessageType.TEXT or str(segment.get("content", "") or "").strip()
        ]

class EmojiTile(QLabel):
    """Lightweight clickable emoji tile."""

    clicked = Signal(str)
    _VERTICAL_NUDGE = 0

    def __init__(self, emoji: str, parent=None):
        super().__init__("", parent)
        self._emoji = emoji
        self.setObjectName("emojiTile")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(56, 56)
        self.setToolTip(emoji_display_name(emoji))
        self.installEventFilter(AcrylicToolTipFilter(self, 250, ToolTipPosition.TOP))

        font = QFont(self.font())
        font.setPixelSize(22)
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
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        pixmap = load_emoji_pixmap(self._emoji, self.width() - 10, self.height() - 12)
        if not pixmap.isNull():
            x = round((self.width() - pixmap.width()) / 2)
            y = round((self.height() - pixmap.height()) / 2)
            painter.drawPixmap(x, y, pixmap)
        else:
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            painter.setFont(self.font())
            metrics = painter.fontMetrics()
            x = round((self.width() - metrics.horizontalAdvance(self._emoji)) / 2)
            y = round((self.height() + metrics.ascent() - metrics.descent()) / 2) + self._VERTICAL_NUDGE
            painter.drawText(x, y, self._emoji)
        painter.end()


class ModernEmojiPickerFlyout(AcrylicFlyoutViewBase):
    """Grouped emoji picker that keeps the popup fast by building pages lazily."""

    emoji_selected = Signal(str)

    EMOJI_GROUPS = [
        (
            "smileys",
            "composer.emoji.group.smileys",
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
            "composer.emoji.group.hands",
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
            "composer.emoji.group.people",
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
            "composer.emoji.group.animals",
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
            "composer.emoji.group.food",
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
            "composer.emoji.group.symbols",
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
        self._group_emoji_map = {route_key: emojis for route_key, _label_key, _label, emojis in self.EMOJI_GROUPS}
        self._containers: dict[str, QWidget] = {}
        self._container_layouts: dict[str, QVBoxLayout] = {}
        self._built_pages: set[str] = set()
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setObjectName("emojiPickerFlyout")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.view_layout = QVBoxLayout(self)
        self.view_layout.setContentsMargins(12, 12, 12, 12)
        self.view_layout.setSpacing(8)

        self.group_tabs = SegmentedWidget(self)
        self.group_tabs.setObjectName("emojiGroupTabs")
        self.group_tabs.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.group_tabs.setAutoFillBackground(False)
        self.view_layout.addWidget(self.group_tabs)

        self.page_stack = QStackedWidget(self)
        self.page_stack.setObjectName("emojiPageStack")
        self.page_stack.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.page_stack.setAutoFillBackground(False)
        self.view_layout.addWidget(self.page_stack, 1)

        for route_key, label_key, default_label, _emojis in self.EMOJI_GROUPS:
            container = QWidget(self.page_stack)
            container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            container.setAutoFillBackground(False)
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(0)
            self._containers[route_key] = container
            self._container_layouts[route_key] = container_layout
            self.page_stack.addWidget(container)
            self.group_tabs.addItem(
                route_key,
                tr(label_key, default_label),
                lambda _checked=False, key=route_key: self._switch_group(key),
            )

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
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        scroll_area.setAutoFillBackground(False)
        if scroll_area.viewport() is not None:
            scroll_area.viewport().setObjectName("emojiScrollViewport")
            scroll_area.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            scroll_area.viewport().setAutoFillBackground(False)

        content = QWidget(scroll_area)
        content.setObjectName("emojiScrollContent")
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        content.setAutoFillBackground(False)
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


class MentionCandidateRow(QWidget):
    """Selectable row used by the group @ member flyout."""

    activated = Signal(object)
    AVATAR_SIZE = 28
    AVATAR_RADIUS = 8
    TEXT_WIDTH = 70

    def __init__(self, candidate: MentionCandidate, parent=None) -> None:
        super().__init__(parent)
        self._candidate = candidate
        self._full_name = str(candidate.display_name or "")
        self._hovered = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(8)

        self.leading = MentionAvatarWidget(
            candidate.avatar,
            gender=candidate.gender,
            seed=profile_avatar_seed(
                user_id=candidate.member_id,
                username=candidate.username,
                display_name=candidate.display_name,
            ),
            size=self.AVATAR_SIZE,
            radius=self.AVATAR_RADIUS,
            parent=self,
        )

        self.name_label = BodyLabel("", self)
        self.name_label.setObjectName("mentionCandidateNameLabel")
        name_font = QFont(self.name_label.font())
        name_font.setPixelSize(14)
        self.name_label.setFont(name_font)
        self.name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout.addWidget(self.leading, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.name_label, 1, Qt.AlignmentFlag.AlignVCenter)
        self._refresh_name_label()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self._candidate)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        highlight_rect = QRectF(self.rect())
        if self._hovered:
            fill = QColor(255, 255, 255, 16) if isDarkTheme() else QColor(0, 0, 0, 10)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(highlight_rect, 8, 8)
        super().paintEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_name_label()

    def _refresh_name_label(self) -> None:
        metrics = QFontMetrics(self.name_label.font())
        available = max(24, self.name_label.width() or self.TEXT_WIDTH)
        self.name_label.setText(metrics.elidedText(self._full_name, Qt.TextElideMode.ElideRight, available))


class GroupMentionFlyoutView(QWidget):
    """Content widget for the group @ member picker."""

    candidateSelected = Signal(object)
    PANEL_MARGIN = 6
    ROW_HEIGHT = 34
    MAX_ROWS_HEIGHT = 220
    PANEL_WIDTH = 116

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._candidates: list[MentionCandidate] = []
        self._rows: list[MentionCandidateRow] = []
        self._current_index = 0
        self._show_everyone_row = False
        self._show_member_label = False
        self._visible_row_count = 0
        self.setObjectName("groupMentionFlyout")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(False)

        self.v_box_layout = QVBoxLayout(self)
        self.v_box_layout.setContentsMargins(self.PANEL_MARGIN, self.PANEL_MARGIN, self.PANEL_MARGIN, self.PANEL_MARGIN)
        self.v_box_layout.setSpacing(0)

        self.everyone_row: MentionCandidateRow | None = None
        self.everyone_host = QWidget(self)
        self.everyone_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.everyone_host.setAutoFillBackground(False)
        self.everyone_layout = QVBoxLayout(self.everyone_host)
        self.everyone_layout.setContentsMargins(0, 0, 0, 0)
        self.everyone_layout.setSpacing(0)
        self.everyone_host.hide()

        self.section_host = QWidget(self)
        self.section_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.section_host.setAutoFillBackground(False)
        self.section_layout = QVBoxLayout(self.section_host)
        self.section_layout.setContentsMargins(0, 4, 0, 3)
        self.section_layout.setSpacing(0)

        self.section_label = CaptionLabel(tr("composer.mention.members", "群成员"), self.section_host)
        self.section_label.setObjectName("mentionSectionLabel")
        self.section_label.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.section_label.setAutoFillBackground(False)
        self.section_layout.addWidget(self.section_label)
        self.section_host.hide()

        self.scroll_area = ScrollArea(self)
        self.scroll_area.setObjectName("groupMentionScrollArea")
        self.scroll_area.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.scroll_area.setAutoFillBackground(False)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.rows_container = QWidget(self.scroll_area)
        self.rows_container.setObjectName("groupMentionRowsContainer")
        self.rows_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.rows_container.setAutoFillBackground(False)
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(0)
        self.scroll_area.setWidget(self.rows_container)
        if self.scroll_area.viewport() is not None:
            self.scroll_area.viewport().setObjectName("groupMentionScrollViewport")
            self.scroll_area.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self.scroll_area.viewport().setAutoFillBackground(False)
        self.scroll_area.setStyleSheet(
            "QScrollArea#groupMentionScrollArea { background: transparent; border: none; }"
            "QWidget#qt_scrollarea_viewport, QWidget#groupMentionScrollViewport { background: transparent; }"
            "QWidget#groupMentionRowsContainer { background: transparent; }"
            "QScrollBar:vertical {"
            " background: transparent;"
            " width: 6px;"
            " margin: 2px 0 2px 0;"
            "}"
            "QScrollBar::handle:vertical {"
            " background: rgba(0, 0, 0, 58);"
            " min-height: 24px;"
            " border-radius: 3px;"
            "}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {"
            " background: transparent;"
            " height: 0px;"
            "}"
        )
        self.scroll_area.installEventFilter(self)

        self.v_box_layout.addWidget(self.everyone_host)
        self.v_box_layout.addWidget(self.section_host)
        self.v_box_layout.addWidget(self.scroll_area)
        self.setFixedWidth(self.PANEL_WIDTH)
        self.setMaximumHeight(260)
        if self.scroll_area.viewport() is not None:
            self.scroll_area.viewport().installEventFilter(self)
        self.scroll_area.verticalScrollBar().installEventFilter(self)
        self._set_scrollbar_visible(False)

    def set_candidates(self, candidates: list[MentionCandidate], *, show_member_label: bool = False) -> None:
        self._candidates = list(candidates or [])
        self._current_index = 0

        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows.clear()

        if self.everyone_row is not None:
            self.everyone_row.deleteLater()
            self.everyone_row = None

        everyone = next((candidate for candidate in self._candidates if candidate.is_everyone), None)
        members = [candidate for candidate in self._candidates if not candidate.is_everyone]
        self._show_everyone_row = everyone is not None

        if everyone is not None:
            self.everyone_row = MentionCandidateRow(everyone, self.everyone_host)
            self.everyone_row.activated.connect(self.candidateSelected.emit)
            self.everyone_layout.addWidget(self.everyone_row)
            self.everyone_host.show()
            self.everyone_host.setFixedHeight(self.ROW_HEIGHT)
        else:
            self.everyone_host.hide()
            self.everyone_host.setFixedHeight(0)

        section_visible = bool(show_member_label and everyone is not None and members)
        self._show_member_label = section_visible
        self.section_host.setVisible(section_visible)
        self.section_host.setFixedHeight(self.section_host.sizeHint().height() if section_visible else 0)
        for candidate in members if everyone is not None else self._candidates:
            row = MentionCandidateRow(candidate, self.rows_container)
            row.activated.connect(self.candidateSelected.emit)
            self.rows_layout.addWidget(row)
            self._rows.append(row)

        self._visible_row_count = len(self._rows)
        visible_height = min(self.MAX_ROWS_HEIGHT, len(self._rows) * self.ROW_HEIGHT)
        self.scroll_area.setFixedHeight(max(0, visible_height))
        self.scroll_area.setVisible(bool(self._rows))
        self._set_scrollbar_visible(False)
        self.updateGeometry()
        self.adjustSize()

    def sizeHint(self) -> QSize:
        everyone_height = self.ROW_HEIGHT if self._show_everyone_row else 0
        label_height = self.section_host.sizeHint().height() if self._show_member_label else 0
        rows_height = min(self.MAX_ROWS_HEIGHT, self._visible_row_count * self.ROW_HEIGHT) if self._visible_row_count else 0
        content_height = self.PANEL_MARGIN * 2 + everyone_height + label_height + rows_height
        return QSize(self.PANEL_WIDTH, content_height)

    def move_selection(self, step: int) -> None:
        if not self._candidates:
            return
        self._current_index = (self._current_index + step) % len(self._candidates)

    def activate_current(self) -> MentionCandidate | None:
        if not self._candidates:
            return None
        return self._candidates[self._current_index]

    def eventFilter(self, watched, event) -> bool:
        if watched in {self.scroll_area, self.scroll_area.viewport(), self.scroll_area.verticalScrollBar()}:
            if event.type() == QEvent.Type.Enter:
                self._set_scrollbar_visible(True)
            elif event.type() == QEvent.Type.Leave:
                QTimer.singleShot(0, self._refresh_scrollbar_visibility)
        return super().eventFilter(watched, event)

    def _refresh_scrollbar_visibility(self) -> None:
        hovered = any(
            widget is not None and widget.underMouse()
            for widget in (self.scroll_area, self.scroll_area.viewport(), self.scroll_area.verticalScrollBar())
        )
        self._set_scrollbar_visible(hovered)

    def _set_scrollbar_visible(self, visible: bool) -> None:
        scrollbar = self.scroll_area.verticalScrollBar()
        should_show = bool(visible and self.scroll_area.isVisible() and scrollbar.maximum() > 0)
        scrollbar.setVisible(should_show)


class GroupMentionPopupOverlay(QWidget):
    """Modeless in-window overlay used for the group @ panel."""

    closed = Signal()
    EDGE_MARGIN = 12
    CURSOR_GAP = 10

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("groupMentionOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.hide()

        self._editor: ChatTextEdit | None = None
        self._content: GroupMentionFlyoutView | None = None
        self._last_surface_rect: QRect | None = None

        self.surface = AcrylicDrawerSurface(self, radius=7)
        self.surface.setObjectName("groupMentionSurface")
        self.surface.set_border_object_name("groupMentionSurfaceBorder")
        surface_layout = QVBoxLayout(self.surface)
        surface_layout.setContentsMargins(0, 0, 0, 0)
        surface_layout.setSpacing(0)

        if parent is not None:
            parent.installEventFilter(self)

    def bind_editor(self, editor: ChatTextEdit) -> None:
        if self._editor is editor:
            return
        if self._editor is not None:
            self._editor.removeEventFilter(self)
            viewport = self._editor.viewport()
            if viewport is not None:
                viewport.removeEventFilter(self)
        self._editor = editor
        self._editor.installEventFilter(self)
        viewport = self._editor.viewport()
        if viewport is not None:
            viewport.installEventFilter(self)

    def set_content(self, content: GroupMentionFlyoutView) -> None:
        if self._content is content:
            return
        layout = self.surface.layout()
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self._content = content
        content.setParent(self.surface)
        layout.addWidget(content, 1)

    def show_for_editor(self, editor: ChatTextEdit, content: GroupMentionFlyoutView) -> None:
        host = self.parentWidget()
        if host is None:
            return
        self.bind_editor(editor)
        self.set_content(content)
        self.setGeometry(host.rect())
        self._apply_geometry(capture=not self.isVisible())
        self.surface.show()
        self.surface.raise_()
        self.show()
        self.raise_()

    def reposition(self) -> None:
        if not self.isVisible():
            return
        host = self.parentWidget()
        if host is None:
            return
        self.setGeometry(host.rect())
        self._apply_geometry(capture=False)

    def close_overlay(self) -> None:
        if not self.isVisible():
            self.closed.emit()
            return
        self.hide()
        self._last_surface_rect = None
        self.closed.emit()

    def eventFilter(self, watched, event) -> bool:
        host = self.parentWidget()
        if watched is host and event.type() in {QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Hide}:
            if self.isVisible():
                self.close_overlay()
        elif watched in {self._editor, self._editor.viewport() if self._editor is not None else None} and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Move,
            QEvent.Type.Show,
        }:
            if self.isVisible():
                self.reposition()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:
        if not self.surface.geometry().contains(event.position().toPoint()):
            self.close_overlay()
            event.accept()
            return
        super().mousePressEvent(event)

    def _calculate_surface_rect(self) -> QRect | None:
        host = self.parentWidget()
        if host is None or self._editor is None or self._content is None:
            return None
        cursor_rect = self._editor.cursorRect()
        anchor_top_left = self._editor.viewport().mapTo(host, cursor_rect.topLeft())
        size_hint = self._content.sizeHint()
        panel_width = max(GroupMentionFlyoutView.PANEL_WIDTH, size_hint.width())
        panel_height = min(260, max(20, size_hint.height()))
        center_x = anchor_top_left.x() + cursor_rect.width() // 2
        panel_x = center_x - panel_width // 2
        panel_y = anchor_top_left.y() - panel_height - self.CURSOR_GAP
        panel_x = max(self.EDGE_MARGIN, min(panel_x, host.width() - panel_width - self.EDGE_MARGIN))
        panel_y = max(self.EDGE_MARGIN, panel_y)
        return QRect(panel_x, panel_y, panel_width, panel_height)

    def _apply_geometry(self, *, capture: bool) -> None:
        host = self.parentWidget()
        panel_rect = self._calculate_surface_rect()
        if host is None or panel_rect is None:
            return
        self.surface.setGeometry(panel_rect)
        layout = self.surface.layout()
        if layout is not None:
            layout.activate()
        if capture or self._last_surface_rect != panel_rect:
            self.surface.capture_backdrop(QRect(host.mapToGlobal(panel_rect.topLeft()), panel_rect.size()))
            self._last_surface_rect = QRect(panel_rect)


class MessageInput(QWidget):
    """Integrated message input surface."""

    segments_submitted = Signal(object)
    draft_changed = Signal(object)
    attachment_open_requested = Signal(str, str)
    screenshot_requested = Signal()
    voice_call_requested = Signal()
    video_call_requested = Signal()
    ai_action_requested = Signal(str)
    ai_reply_suggestion_selected = Signal(str)
    typing_signal = Signal()

    IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp)"
    FILE_FILTER = "All Files (*.*)"
    TYPING_THROTTLE = 1.0

    def __init__(self, parent=None):
        super().__init__(parent)

        self._last_typing_time = 0.0
        self._session_active = False
        self._current_session: Optional[Session] = None
        self._emoji_flyout = None
        self._mention_flyout = None
        self._mention_view: Optional[GroupMentionFlyoutView] = None
        self._mention_candidates: list[MentionCandidate] = []
        self._mention_refresh_pending = False
        self._mention_range: tuple[int, int] | None = None
        self._draft_emit_pending = False
        self._programmatic_edit_depth = 0
        self._ai_busy = False
        self._reply_suggestion_buttons: list[PushButton] = []
        self._setup_ui()
        self._connect_signals()
        qconfig.themeChanged.connect(lambda *_args: (self._apply_editor_transparency(), self.text_input._refresh_mention_selections()))
        self.set_session_active(False)
        QTimer.singleShot(0, self._update_overlay_positions)

    def _setup_ui(self) -> None:
        self.setObjectName("messageInput")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(0)

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

        self.emoji_button = TransparentToolButton(AppIcon.EMOJI_TAB_SYMBOLS, self.composer_widget)
        self.emoji_button.setFixedSize(28, 28)
        self.emoji_button.setToolTip(tr("composer.toolbar.emoji", "Emoji"))

        self.image_button = TransparentToolButton(AppIcon.PHOTO, self.composer_widget)
        self.image_button.setFixedSize(28, 28)
        self.image_button.setToolTip(tr("composer.toolbar.image", "Send Image"))

        self.file_button = TransparentToolButton(AppIcon.FOLDER, self.composer_widget)
        self.file_button.setFixedSize(28, 28)
        self.file_button.setToolTip(tr("composer.toolbar.file", "Send File"))

        self.cut_button = TransparentToolButton(AppIcon.CUT, self.composer_widget)
        self.cut_button.setFixedSize(28, 28)
        self.cut_button.setToolTip(tr("composer.toolbar.screenshot", "Screenshot"))

        self.voice_button = TransparentToolButton(AppIcon.PHONE, self.composer_widget)
        self.voice_button.setFixedSize(28, 28)
        self.voice_button.setToolTip(tr("composer.toolbar.voice_call", "Voice Call"))

        self.video_button = TransparentToolButton(AppIcon.VIDEO, self.composer_widget)
        self.video_button.setFixedSize(28, 28)
        self.video_button.setToolTip(tr("composer.toolbar.video_call", "Video Call"))

        self.ai_button = TransparentToolButton(AppIcon.ROBOT, self.composer_widget)
        self.ai_button.setFixedSize(28, 28)
        self.ai_button.setToolTip(tr("composer.toolbar.ai", "AI 助手"))

        self._apply_safe_button_font(
            self.emoji_button,
            self.image_button,
            self.file_button,
            self.cut_button,
            self.voice_button,
            self.video_button,
            self.ai_button,
        )
        self._install_acrylic_tooltips(
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

        self.reply_suggestion_widget = QWidget(self.composer_widget)
        self.reply_suggestion_widget.setObjectName("aiReplySuggestionBar")
        self.reply_suggestion_layout = QHBoxLayout(self.reply_suggestion_widget)
        self.reply_suggestion_layout.setContentsMargins(10, 0, 10, 4)
        self.reply_suggestion_layout.setSpacing(6)
        self.reply_suggestion_label = CaptionLabel(tr("composer.ai.reply_suggestions", "AI 回复"), self.reply_suggestion_widget)
        self.reply_suggestion_layout.addWidget(self.reply_suggestion_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.reply_suggestion_layout.addStretch(1)
        self.reply_suggestion_widget.hide()

        self.text_input = ChatTextEdit(self.composer_widget)
        self.text_input.setObjectName("chatMessageEdit")
        self.text_input.viewport().setObjectName("chatMessageViewport")
        self.text_input.setPlaceholderText(tr("composer.placeholder.inactive", "Select a session to start chatting"))
        self.text_input.setAcceptRichText(False)
        self.text_input.setMinimumHeight(128)
        self.text_input.setViewportMargins(0, 0, 24, 52)
        self._apply_editor_transparency()

        self.send_button = PushButton(tr("composer.button.send", "Send"), self.composer_widget)
        self.send_button.setObjectName("composerSendButton")
        self.send_button.setFixedSize(84, 34)

        self.toolbar_widget.setLayout(self.toolbar_layout)

        self.composer_layout.addWidget(self.toolbar_widget, 0)
        self.composer_layout.addWidget(self.reply_suggestion_widget, 0)
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

    def _install_acrylic_tooltips(self, *widgets: QWidget) -> None:
        """Install Fluent acrylic tooltips for toolbar controls."""
        if AcrylicToolTipFilter is None or ToolTipPosition is None:
            return
        for widget in widgets:
            widget.installEventFilter(AcrylicToolTipFilter(widget, 250, ToolTipPosition.TOP))

    def _is_dark(self) -> bool:
        """Return whether the current widget palette is using a dark window color."""
        return isDarkTheme()

    def _apply_editor_transparency(self) -> None:
        """Force the text editor and its viewport to render with a transparent background."""
        text_color = QColor("#FFFFFF") if self._is_dark() else QColor("#000000")
        placeholder_color = QColor(255, 255, 255, 138) if self._is_dark() else QColor(20, 20, 20, 118)
        selection_color = QColor(255, 255, 255) if self._is_dark() else QColor("#000000")
        selection_background = QColor(255, 255, 255, 48) if self._is_dark() else QColor(0, 0, 0, 32)
        transparent_base = QColor(0, 0, 0, 10) if self._is_dark() else QColor(255, 255, 255, 18)

        self.text_input.setFrameShape(QFrame.Shape.NoFrame)
        self.text_input.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.text_input.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.text_input.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.text_input.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.text_input.viewport().setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.text_input.setAutoFillBackground(False)
        self.text_input.viewport().setAutoFillBackground(False)
        self.text_input.setCursorWidth(3)
        self.text_input.setFont(self.text_input._editor_font)
        self.text_input.document().setDefaultFont(self.text_input._editor_font)
        self.text_input.setStyleSheet(
            f"QTextEdit#chatMessageEdit {{"
            " border: none !important;"
            " background-color: transparent !important;"
            " border-radius: 0;"
            f" color: {text_color.name()};"
            f" selection-background-color: {selection_background.name(QColor.NameFormat.HexArgb)};"
            f" selection-color: {selection_color.name()};"
            "}"
            "QTextEdit#chatMessageEdit:hover { background-color: transparent !important; border: none !important; }"
            "QTextEdit#chatMessageEdit:focus { background-color: transparent !important; border: none !important; }"
            "QWidget#chatMessageViewport { background-color: transparent !important; border: none !important; }"
        )
        self.text_input.viewport().setStyleSheet("border: none !important; background-color: transparent !important;")

        palette = self.text_input.palette()
        palette.setColor(QPalette.ColorRole.Base, transparent_base)
        palette.setColor(QPalette.ColorRole.Window, transparent_base)
        palette.setColor(QPalette.ColorRole.Text, text_color)
        palette.setColor(QPalette.ColorRole.WindowText, text_color)
        palette.setColor(QPalette.ColorRole.PlaceholderText, placeholder_color)
        palette.setColor(QPalette.ColorRole.HighlightedText, selection_color)
        palette.setColor(QPalette.ColorRole.Highlight, selection_background)
        self.text_input.setPalette(palette)
        self.text_input.setTextColor(text_color)

        viewport_palette = self.text_input.viewport().palette()
        viewport_palette.setColor(QPalette.ColorRole.Base, transparent_base)
        viewport_palette.setColor(QPalette.ColorRole.Window, transparent_base)
        viewport_palette.setColor(QPalette.ColorRole.Text, text_color)
        viewport_palette.setColor(QPalette.ColorRole.WindowText, text_color)
        viewport_palette.setColor(QPalette.ColorRole.PlaceholderText, placeholder_color)
        viewport_palette.setColor(QPalette.ColorRole.HighlightedText, selection_color)
        viewport_palette.setColor(QPalette.ColorRole.Highlight, selection_background)
        self.text_input.viewport().setPalette(viewport_palette)

        current_format = self.text_input.currentCharFormat()
        current_format.setFont(self.text_input._editor_font)
        current_format.setForeground(text_color)
        self.text_input.setCurrentCharFormat(current_format)
        self.text_input.document().setDocumentMargin(5)
        self.text_input.viewport().update()
        self.text_input.update()

    def _connect_signals(self) -> None:
        self.send_button.clicked.connect(self._on_send_clicked)
        self.emoji_button.clicked.connect(self._on_emoji_clicked)
        self.image_button.clicked.connect(self._on_image_clicked)
        self.file_button.clicked.connect(self._on_file_clicked)
        self.cut_button.clicked.connect(self.screenshot_requested.emit)
        self.voice_button.clicked.connect(self.voice_call_requested.emit)
        self.video_button.clicked.connect(self.video_call_requested.emit)
        self.ai_button.clicked.connect(self._on_ai_clicked)
        self.text_input.textChanged.connect(self._on_text_changed)
        self.text_input.textChanged.connect(self._update_send_button_state)
        self.text_input.textChanged.connect(self._schedule_draft_changed_emit)
        self.text_input.textChanged.connect(self._schedule_mention_refresh)
        self.text_input.cursorPositionChanged.connect(self._schedule_mention_refresh)
        self.text_input.send_requested.connect(self._on_send_clicked)
        self.text_input.attachment_activated.connect(self._on_attachment_activated)
        self.text_input.files_dropped.connect(self._on_files_dropped)

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
        if watched in {self.composer_widget, self.text_input} and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.LayoutRequest,
        }:
            QTimer.singleShot(0, self._update_overlay_positions)
            if self._mention_flyout is not None and self._mention_flyout.isVisible():
                QTimer.singleShot(0, self._reposition_mention_flyout)
        if watched is self.text_input:
            if event.type() == QEvent.Type.KeyPress and self._handle_mention_key_event(event):
                return True
        return super().eventFilter(watched, event)

    def _update_overlay_positions(self) -> None:
        """Place the send button inside the text input area."""
        if self.composer_layout is not None:
            self.composer_layout.activate()
        self.card_layout.activate()
        self.main_layout.activate()
        text_rect = self.text_input.geometry()
        if not text_rect.isValid():
            return

        button_margin_right = 14
        button_margin_bottom = 14
        send_x = text_rect.x() + text_rect.width() - self.send_button.width() - button_margin_right
        send_y = text_rect.y() + text_rect.height() - self.send_button.height() - button_margin_bottom
        composer_rect = self.composer_widget.rect()
        send_x = max(composer_rect.left(), min(send_x, composer_rect.right() - self.send_button.width()))
        send_y = max(composer_rect.top(), min(send_y, composer_rect.bottom() - self.send_button.height()))
        self.send_button.move(send_x, send_y)

        self.send_button.raise_()

    def _update_send_button_state(self) -> None:
        """Enable the send button only when the active session has draft content."""
        has_draft = self.text_input.has_meaningful_content()
        self.send_button.setEnabled(self._session_active and has_draft)

    def _run_programmatic_edit(self, callback) -> None:
        """Suppress typing side effects while mutating the composer programmatically."""
        self._programmatic_edit_depth += 1
        try:
            callback()
        finally:
            self._programmatic_edit_depth = max(0, self._programmatic_edit_depth - 1)

    def _on_text_changed(self) -> None:
        """Emit throttled typing events."""
        if self._programmatic_edit_depth:
            return
        current_time = time.monotonic()
        if current_time - self._last_typing_time >= self.TYPING_THROTTLE:
            self._last_typing_time = current_time
            self.typing_signal.emit()

    def _schedule_draft_changed_emit(self) -> None:
        """Coalesce draft updates so session preview refreshes once per event loop turn."""
        if self._programmatic_edit_depth:
            return
        if self._draft_emit_pending:
            return
        self._draft_emit_pending = True
        QTimer.singleShot(0, self._emit_draft_changed)

    def _emit_draft_changed(self) -> None:
        """Publish the current draft segments for the active session."""
        self._draft_emit_pending = False
        self._update_send_button_state()
        self.draft_changed.emit(self.capture_draft_segments())

    def _on_send_clicked(self) -> None:
        """Extract composed segments and hand them to the chat panel."""
        self._close_mention_flyout()
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
        self._emoji_flyout = AcrylicFlyout.make(
            picker,
            self.emoji_button,
            self,
            aniType=FlyoutAnimationType.PULL_UP,
        )
        picker.emoji_selected.connect(self._emoji_flyout.close)
        self._emoji_flyout.closed.connect(lambda: setattr(self, "_emoji_flyout", None))

    def _insert_emoji(self, emoji: str) -> None:
        """Insert emoji at current cursor position."""
        self.text_input.insert_inline_emoji(emoji)
        self.text_input.setFocus()

    def _on_image_clicked(self) -> None:
        """Insert a selected image into the composer flow."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("composer.dialog.select_image", "Select Image"),
            "",
            self.IMAGE_FILTER,
        )
        if file_path:
            self.text_input.insert_local_attachment(file_path, blockify=False)
            self.text_input.setFocus()

    def _on_file_clicked(self) -> None:
        """Insert a selected file into the composer flow."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("composer.dialog.select_file", "Select File"),
            "",
            self.FILE_FILTER,
        )
        if file_path:
            self.text_input.insert_local_attachment(file_path, blockify=False)
            self.text_input.setFocus()

    def _on_attachment_activated(self, file_path: str, message_type: str) -> None:
        """Forward attachment open requests to the chat panel."""
        self.attachment_open_requested.emit(file_path, message_type)

    def _on_files_dropped(self, file_paths: list[str]) -> None:
        """Insert dragged local files into the composer flow."""
        for file_path in file_paths or []:
            self.text_input.insert_local_attachment(file_path, blockify=False)
        self.text_input.setFocus()

    def _on_ai_clicked(self) -> None:
        """Show draft-assist actions for the current composer text."""
        if not self._session_active or self._ai_busy:
            return

        draft_text = self.current_plain_text().strip()
        if not draft_text:
            InfoBar.info(
                tr("composer.ai.title", "AI 助手"),
                tr("composer.ai.empty_draft", "请先输入草稿，再选择 AI 操作。"),
                parent=self.window(),
                duration=1800,
            )
            return

        menu = RoundMenu(parent=self)
        actions = [
            ("polish", tr("composer.ai.polish", "润色")),
            ("shorten", tr("composer.ai.shorten", "缩短")),
            ("translate", tr("composer.ai.translate", "翻译成中文")),
            ("rewrite", tr("composer.ai.rewrite", "重写")),
        ]
        for action_id, label in actions:
            action = Action(label, self)
            action.triggered.connect(lambda _checked=False, value=action_id: self.ai_action_requested.emit(value))
            menu.addAction(action)
        menu.exec(self.ai_button.mapToGlobal(QPoint(0, self.ai_button.height())))

    def set_session_active(self, active: bool) -> None:
        """Enable or disable the editor depending on session selection."""
        self._session_active = active

        self.emoji_button.setEnabled(active)
        self.image_button.setEnabled(active)
        self.file_button.setEnabled(active)
        self.cut_button.setEnabled(active)
        self.voice_button.setEnabled(active)
        self.video_button.setEnabled(active)
        self.ai_button.setEnabled(active and not self._ai_busy)
        self.text_input.setEnabled(active)

        if active:
            self.text_input.setPlaceholderText(tr("composer.placeholder.active", "Enter to send, Shift+Enter for new line"))
        else:
            self.text_input.setPlaceholderText(tr("composer.placeholder.inactive", "Select a session to start chatting"))
            self._current_session = None
            self._mention_candidates = []
            self._close_mention_flyout()
            self.clear_reply_suggestions()
            self.clear_draft()

        self._apply_editor_transparency()
        self._update_call_buttons()
        self._update_send_button_state()

    def focus_editor(self) -> None:
        """Focus the text editor."""
        if self._session_active:
            self.text_input.setFocus()

    def set_session(self, session: Session | None) -> None:
        """Update the active session context used by composer-only features like @ mention."""
        self._current_session = session
        self._mention_candidates = self._build_mention_candidates(session)
        self._close_mention_flyout()
        self.clear_reply_suggestions()
        self._update_call_buttons()

    def _update_call_buttons(self) -> None:
        session = self._current_session
        supports_call = bool(
            self._session_active
            and session is not None
            and session.session_type == "direct"
            and not session.is_ai_session
        )
        self.voice_button.setVisible(supports_call)
        self.video_button.setVisible(supports_call)
        self.voice_button.setEnabled(supports_call)
        self.video_button.setEnabled(supports_call)

    @staticmethod
    def _build_mention_candidates(session: Session | None) -> list[MentionCandidate]:
        """Build @ mention candidates for the current group session."""
        if session is None or session.session_type != "group" or session.is_ai_session:
            return []

        members = list(getattr(session, "extra", {}).get("members") or [])
        current_user_id = str(getattr(session, "extra", {}).get("current_user_id", "") or "").strip()
        owner_id = str(getattr(session, "extra", {}).get("owner_id", "") or "").strip()
        current_role = ""
        for member in members:
            member_id = str(member.get("id", "") or "").strip()
            if not member_id or member_id != current_user_id:
                continue
            current_role = str(member.get("role", "") or "").strip().lower()
            break

        can_mention_everyone = current_role in {"owner", "admin"} or bool(owner_id and owner_id == current_user_id)
        candidates: list[MentionCandidate] = []
        if can_mention_everyone:
            candidates.append(
                MentionCandidate(
                    member_id="all",
                    display_name=tr("composer.mention.all_members", "所有人"),
                    username="all",
                    avatar=str(session.display_avatar() or session.avatar or ""),
                    gender=str(session.display_gender() or ""),
                    is_everyone=True,
                )
            )
        seen: set[str] = set()
        for member in members:
            member_id = str(member.get("id", "") or "").strip()
            if not member_id or member_id == current_user_id or member_id in seen:
                continue
            seen.add(member_id)
            candidates.append(
                MentionCandidate(
                    member_id=member_id,
                    display_name=_preferred_member_name(member),
                    username=str(member.get("username", "") or "").strip(),
                    avatar=str(member.get("avatar", "") or "").strip(),
                    gender=str(member.get("gender", "") or "").strip(),
                )
            )
        return candidates

    def _schedule_mention_refresh(self) -> None:
        """Coalesce @ mention popup updates after editor changes and cursor moves."""
        if self._programmatic_edit_depth or self._mention_refresh_pending:
            return
        self._mention_refresh_pending = True
        QTimer.singleShot(0, self._refresh_mention_popup)

    def _refresh_mention_popup(self) -> None:
        """Show, update, or close the @ mention popup based on the current cursor context."""
        self._mention_refresh_pending = False
        context = self._active_mention_context()
        if context is None:
            self._mention_range = None
            self._close_mention_flyout()
            return

        start_pos, end_pos, query = context
        self._mention_range = (start_pos, end_pos)
        normalized_query = query.strip().lower()
        everyone = next((candidate for candidate in self._mention_candidates if candidate.is_everyone), None)
        members = [candidate for candidate in self._mention_candidates if not candidate.is_everyone]
        matched_members = [
            candidate
            for candidate in members
            if not normalized_query or any(normalized_query in token for token in _mention_search_tokens(candidate))
        ]
        show_member_label = False
        if normalized_query and matched_members:
            filtered = matched_members
        elif normalized_query:
            filtered = ([everyone] if everyone is not None and any(normalized_query in token for token in _mention_search_tokens(everyone)) else [])
        else:
            filtered = ([everyone] if everyone is not None else []) + members
            show_member_label = everyone is not None and bool(members)
        if not filtered:
            self._close_mention_flyout()
            return

        if self._mention_view is None:
            self._mention_view = GroupMentionFlyoutView(self)
            self._mention_view.candidateSelected.connect(self._insert_mention_candidate)
        self._mention_view.set_candidates(filtered, show_member_label=show_member_label)
        self._show_mention_flyout()

    def _active_mention_context(self) -> tuple[int, int, str] | None:
        """Return the active @ mention replacement range around the cursor, if any."""
        if not self._session_active or not self._mention_candidates:
            return None

        cursor = self.text_input.textCursor()
        if cursor.hasSelection():
            return None
        if self.text_input._mention_token_at(cursor.position()) is not None:
            return None

        block = cursor.block()
        if not block.isValid():
            return None
        block_text = block.text()
        cursor_in_block = cursor.positionInBlock()
        if cursor_in_block < 0:
            return None

        prefix = block_text[:cursor_in_block]
        mention_start = prefix.rfind("@")
        if mention_start < 0:
            return None
        query = prefix[mention_start + 1 :]
        if any(char.isspace() for char in query):
            return None
        document_start = block.position() + mention_start
        document_end = block.position() + cursor_in_block
        return document_start, document_end, query

    def _handle_mention_key_event(self, event) -> bool:
        """Route navigation keys to the active @ mention popup before the editor handles them."""
        if self._mention_flyout is None or not self._mention_flyout.isVisible() or self._mention_view is None:
            return False
        if not isinstance(event, QKeyEvent):
            return False

        key = event.key()
        if key == Qt.Key.Key_Down:
            self._mention_view.move_selection(1)
            event.accept()
            return True
        if key == Qt.Key.Key_Up:
            self._mention_view.move_selection(-1)
            event.accept()
            return True
        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab}:
            candidate = self._mention_view.activate_current()
            if candidate is not None:
                self._insert_mention_candidate(candidate)
            event.accept()
            return True
        if key == Qt.Key.Key_Escape:
            self._close_mention_flyout()
            event.accept()
            return True
        return False

    def _show_mention_flyout(self) -> None:
        """Create or reposition the in-window @ mention panel above the current cursor."""
        if self._mention_view is None:
            return
        if self._mention_flyout is None:
            host = self.window()
            if not isinstance(host, QWidget):
                return
            self._mention_flyout = GroupMentionPopupOverlay(host)
            self._mention_flyout.closed.connect(self._clear_mention_flyout)
        if self._mention_flyout.isVisible():
            self._reposition_mention_flyout()
            self.text_input.setFocus()
            return
        self._mention_flyout.show_for_editor(self.text_input, self._mention_view)
        self.text_input.setFocus()

    def _reposition_mention_flyout(self) -> None:
        """Move the active @ mention panel with the editor cursor and layout."""
        if self._mention_flyout is None or not self._mention_flyout.isVisible():
            return
        self._mention_flyout.reposition()

    def _insert_mention_candidate(self, candidate: MentionCandidate) -> None:
        """Replace the active @ query with one completed mention token."""
        mention_range = self._mention_range
        if mention_range is None:
            self._close_mention_flyout()
            return

        mention_text = f"@{candidate.display_name}"

        def apply() -> None:
            cursor = self.text_input.textCursor()
            cursor.beginEditBlock()
            cursor.setPosition(mention_range[0])
            cursor.setPosition(mention_range[1], QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            payload = _mention_payload_from_candidate(
                candidate,
                start=0,
                end=len(mention_text),
            )
            cursor = self.text_input._insert_structured_mention(mention_text, payload, cursor)
            cursor.insertText(" ")
            cursor.endEditBlock()
            self.text_input._reset_cursor_to_plain_text(cursor)

        self._run_programmatic_edit(apply)
        self._close_mention_flyout()
        self._update_send_button_state()
        self._schedule_draft_changed_emit()
        self.text_input.setFocus()

    def _close_mention_flyout(self) -> None:
        """Close the active @ mention panel if it is visible."""
        if self._mention_flyout is not None:
            self._mention_flyout.close_overlay()

    def _clear_mention_flyout(self) -> None:
        if self._mention_flyout is not None:
            self._mention_flyout.deleteLater()
        self._mention_flyout = None
        self._mention_view = None

    def capture_draft_segments(self) -> list[dict]:
        """Return the current mixed text/attachment draft without clearing it."""
        return self.text_input.collect_composed_segments()

    def restore_draft_segments(self, segments: list[dict]) -> None:
        """Restore a previously captured draft into the composer."""
        self._run_programmatic_edit(lambda: self.text_input.restore_composed_segments(segments or []))
        self._update_send_button_state()
        self._schedule_draft_changed_emit()

    def current_plain_text(self) -> str:
        """Return the current text-only draft content."""
        text_parts: list[str] = []
        for segment in self.capture_draft_segments():
            segment_type = segment.get("type")
            if isinstance(segment_type, str):
                try:
                    segment_type = MessageType(segment_type)
                except ValueError:
                    segment_type = None
            if segment_type == MessageType.TEXT:
                content = str(segment.get("content", "") or "")
                if content:
                    text_parts.append(content)
        return "\n".join(text_parts).strip()

    def replace_plain_text_draft(self, text: str) -> None:
        """Replace the composer content with one plain text draft."""
        normalized = str(text or "").strip()
        if not normalized:
            return
        self.restore_draft_segments([{"type": MessageType.TEXT, "content": normalized}])
        self.focus_editor()

    def set_ai_busy(self, busy: bool) -> None:
        """Reflect whether an explicit draft AI action is running."""
        self._ai_busy = bool(busy)
        self.ai_button.setEnabled(self._session_active and not self._ai_busy)
        if self._ai_busy:
            self.ai_button.setToolTip(tr("composer.ai.running", "AI 正在处理..."))
        else:
            self.ai_button.setToolTip(tr("composer.toolbar.ai", "AI 助手"))

    def set_reply_suggestions(self, suggestions: list[str]) -> None:
        """Render ephemeral AI reply candidates above the composer."""
        self.clear_reply_suggestions()
        normalized = [str(item or "").strip() for item in suggestions or [] if str(item or "").strip()]
        if not normalized:
            return

        insert_index = max(1, self.reply_suggestion_layout.count() - 1)
        for text in normalized[:3]:
            button = PushButton(self._elide_suggestion_text(text), self.reply_suggestion_widget)
            button.setFixedHeight(30)
            button.setMaximumWidth(220)
            button.setToolTip(text)
            button.clicked.connect(lambda _checked=False, value=text: self._apply_reply_suggestion(value))
            self.reply_suggestion_layout.insertWidget(insert_index, button, 0, Qt.AlignmentFlag.AlignVCenter)
            self._reply_suggestion_buttons.append(button)
            insert_index += 1
        self.reply_suggestion_widget.show()
        self._update_overlay_positions()

    def clear_reply_suggestions(self) -> None:
        """Remove visible AI reply candidates."""
        for button in self._reply_suggestion_buttons:
            self.reply_suggestion_layout.removeWidget(button)
            button.deleteLater()
        self._reply_suggestion_buttons.clear()
        self.reply_suggestion_widget.hide()
        self._update_overlay_positions()

    def _apply_reply_suggestion(self, text: str) -> None:
        """Fill the composer with a candidate reply without sending it."""
        self.replace_plain_text_draft(text)
        self.clear_reply_suggestions()
        self.ai_reply_suggestion_selected.emit(text)

    def _elide_suggestion_text(self, text: str) -> str:
        metrics = self.fontMetrics()
        return metrics.elidedText(str(text or ""), Qt.TextElideMode.ElideRight, 180)

    def clear_draft(self) -> None:
        """Clear the current composer draft explicitly."""
        self._run_programmatic_edit(self.text_input.clear_composer)
        self._update_send_button_state()

    def get_text_input(self) -> QTextEdit:
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
