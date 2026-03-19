"""Message delegate that migrates the old bubble-style chat UI."""

from __future__ import annotations

import os
from collections import OrderedDict
from datetime import datetime, timedelta

from PySide6.QtCore import QModelIndex, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPixmap,
    QImageReader,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem
from qfluentwidgets import FluentIcon, Theme, isDarkTheme, themeColor

from client.core.config_backend import get_config
from client.core.video_thumbnail_cache import (
    get_thumbnail as get_video_thumbnail,
    get_video_thumbnail_cache,
)
from client.models.message import ChatMessage, MessageStatus, MessageType
from client.ui.common.attachment_card import attachment_card_size, draw_attachment_card


class MessageDelegate(QStyledItemDelegate):
    """Render text, image, and file messages in a Fluent bubble layout."""

    AVATAR_SIZE = 40
    MAX_TEXT_WIDTH = 320
    MAX_IMAGE_WIDTH = 240
    MAX_IMAGE_HEIGHT = 180
    FILE_WIDTH, FILE_HEIGHT = attachment_card_size()
    VIDEO_WIDTH = 240
    VIDEO_HEIGHT = 136
    LEFT_MARGIN = 18
    RIGHT_MARGIN = 18
    BUBBLE_GAP = 10
    BUBBLE_PADDING_H = 14
    BUBBLE_PADDING_V = 10
    TIME_BLOCK_HEIGHT = 26
    TAIL_SPACE = 8
    TIME_SPACING = 9
    STATUS_BADGE_SIZE = 16
    TEXT_MEASURE_CACHE_LIMIT = 512
    TEXT_LAYOUT_CACHE_LIMIT = 256
    MEDIA_SIZE_CACHE_LIMIT = 512
    IMAGE_RECT_CACHE_LIMIT = 512

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image_cache: dict[str, QPixmap] = {}
        self._loading_sources: set[str] = set()
        self._network_manager = QNetworkAccessManager(self)
        self._network_manager.finished.connect(self._on_image_reply_finished)
        self._selection_message_id: str | None = None
        self._selection_anchor = -1
        self._selection_position = -1
        self._selection_active = False
        self._video_duration_cache: dict[str, str] = {}
        self._video_thumbnail_cache = get_video_thumbnail_cache()
        self._video_thumbnail_cache.signals.thumbnail_ready.connect(self._on_video_thumbnail_ready)
        self._refresh_scheduled = False
        self._text_measure_cache: OrderedDict[str, QSize] = OrderedDict()
        self._text_layout_cache: OrderedDict[tuple[int, str], tuple[int, QTextDocument]] = OrderedDict()
        self._media_size_cache: OrderedDict[tuple, QSize] = OrderedDict()
        self._image_rect_cache: OrderedDict[tuple, QRect] = OrderedDict()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        """Return message item size based on type and timestamp visibility."""
        message = index.data(Qt.ItemDataRole.UserRole)
        if not message:
            return QSize(option.rect.width(), 0)

        content_size = self._bubble_size(message)
        total_height = max(content_size.height(), self.AVATAR_SIZE) + 18

        if self._should_show_time(index, message):
            total_height += self.TIME_BLOCK_HEIGHT + self.TIME_SPACING * 2

        return QSize(option.rect.width(), total_height)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        """Paint a single message bubble row."""
        message: ChatMessage = index.data(Qt.ItemDataRole.UserRole)
        if not message:
            return super().paint(painter, option, index)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        avatar_rect, bubble_rect, _ = self._layout_rects(option.rect, message)

        self._draw_avatar(painter, avatar_rect, message)
        self._draw_bubble(painter, bubble_rect, message, avatar_rect)

        if message.is_self:
            badge_rect = self._status_badge_rect(bubble_rect, option.rect)
            self._draw_status_badge(painter, badge_rect, message)

        footer_top = max(bubble_rect.bottom(), avatar_rect.bottom()) + self.TIME_SPACING

        if self._should_show_time(index, message):
            time_rect = QRect(
                option.rect.x(),
                footer_top,
                option.rect.width(),
                self.TIME_BLOCK_HEIGHT,
            )
            self._draw_time_block(painter, time_rect, self._format_time(message.timestamp))

        painter.restore()

    def is_attachment_hit(self, view, index: QModelIndex, position) -> bool:
        """Return whether a click position is inside the rendered attachment content."""
        message: ChatMessage = index.data(Qt.ItemDataRole.UserRole)
        if not message or message.message_type not in {MessageType.IMAGE, MessageType.FILE, MessageType.VIDEO}:
            return False

        row_rect = view.visualRect(index)
        if not row_rect.isValid():
            return False

        _, _, content_rect = self._layout_rects(row_rect, message)
        hit_rect = self._attachment_hit_rect(content_rect, message)
        return hit_rect.contains(position)

    def is_text_hit(self, view, index: QModelIndex, position: QPoint) -> bool:
        """Return whether a viewport position lands on text content."""
        message: ChatMessage = index.data(Qt.ItemDataRole.UserRole)
        if not message or message.message_type != MessageType.TEXT:
            return False

        row_rect = view.visualRect(index)
        if not row_rect.isValid():
            return False

        _, _, content_rect = self._layout_rects(row_rect, message)
        text_rect, document = self._text_layout(content_rect, message.content or "")
        return self._text_position_for_point(document, text_rect, position, clamp=False) >= 0

    def begin_text_selection(self, view, index: QModelIndex, position: QPoint) -> bool:
        """Begin selecting text from a message bubble."""
        message: ChatMessage = index.data(Qt.ItemDataRole.UserRole)
        if not message or message.message_type != MessageType.TEXT:
            return False

        row_rect = view.visualRect(index)
        if not row_rect.isValid():
            return False

        _, _, content_rect = self._layout_rects(row_rect, message)
        text_rect, document = self._text_layout(content_rect, message.content or "")
        cursor_pos = self._text_position_for_point(document, text_rect, position, clamp=False)
        if cursor_pos < 0:
            return False

        self._selection_message_id = message.message_id
        self._selection_anchor = cursor_pos
        self._selection_position = cursor_pos
        self._selection_active = True
        view.setCurrentIndex(index)
        view.viewport().update()
        return True

    def update_text_selection(self, view, position: QPoint) -> bool:
        """Update the text selection while dragging."""
        if not self._selection_active:
            return False

        index = view.currentIndex()
        if not index.isValid():
            return False

        message: ChatMessage = index.data(Qt.ItemDataRole.UserRole)
        if not message or message.message_id != self._selection_message_id or message.message_type != MessageType.TEXT:
            return False

        row_rect = view.visualRect(index)
        if not row_rect.isValid():
            return False

        _, _, content_rect = self._layout_rects(row_rect, message)
        text_rect, document = self._text_layout(content_rect, message.content or "")
        cursor_pos = self._text_position_for_point(document, text_rect, position, clamp=True)
        if cursor_pos < 0:
            return False

        self._selection_position = cursor_pos
        view.viewport().update()
        return True

    def end_text_selection(self, view=None) -> None:
        """Finish an active drag selection while keeping the highlighted range."""
        self._selection_active = False
        if view is not None:
            view.viewport().update()

    def clear_text_selection(self, view=None) -> None:
        """Clear any existing text selection."""
        self._selection_message_id = None
        self._selection_anchor = -1
        self._selection_position = -1
        self._selection_active = False
        if view is not None:
            view.viewport().update()

    def is_selection_active(self) -> bool:
        """Return whether text is currently being selected."""
        return self._selection_active

    def has_selected_text(self, message_id: str | None = None) -> bool:
        """Return whether a non-empty selected range exists."""
        if self._selection_message_id is None or self._selection_anchor == self._selection_position:
            return False
        return message_id is None or self._selection_message_id == message_id

    def selected_text(self, content: str, message_id: str | None = None) -> str:
        """Return the selected substring for the given message."""
        if not self.has_selected_text(message_id):
            return ""

        start = min(self._selection_anchor, self._selection_position)
        end = max(self._selection_anchor, self._selection_position)
        return (content or "")[start:end]

    def _bubble_size(self, message: ChatMessage) -> QSize:
        """Compute bubble or media size for the current message type."""
        if message.message_type == MessageType.IMAGE:
            pixmap = self._load_pixmap(message)
            cache_key = (
                message.message_type.value,
                message.message_id,
                message.content or "",
                message.extra.get("local_path", ""),
                pixmap.width(),
                pixmap.height(),
            )
            cached_size = self._cache_get(self._media_size_cache, cache_key)
            if cached_size is not None:
                return cached_size

            if not pixmap.isNull():
                scaled = self._contained_size(pixmap.size(), QSize(self.MAX_IMAGE_WIDTH, self.MAX_IMAGE_HEIGHT))
                size = QSize(max(120, scaled.width()), max(96, scaled.height()))
            else:
                size = QSize(160, 116)

            self._cache_put(self._media_size_cache, cache_key, size, self.MEDIA_SIZE_CACHE_LIMIT)
            return size

        if message.message_type == MessageType.FILE:
            cache_key = (
                message.message_type.value,
                message.message_id,
                message.extra.get("name", ""),
                message.extra.get("size"),
            )
            cached_size = self._cache_get(self._media_size_cache, cache_key)
            if cached_size is not None:
                return cached_size
            size = QSize(self.FILE_WIDTH, self.FILE_HEIGHT)
            self._cache_put(self._media_size_cache, cache_key, size, self.MEDIA_SIZE_CACHE_LIMIT)
            return size

        if message.message_type == MessageType.VIDEO:
            cache_key = (
                message.message_type.value,
                message.message_id,
                message.extra.get("local_path", ""),
                message.extra.get("thumbnail_path", ""),
            )
            cached_size = self._cache_get(self._media_size_cache, cache_key)
            if cached_size is not None:
                return cached_size
            size = QSize(self.VIDEO_WIDTH, self.VIDEO_HEIGHT)
            self._cache_put(self._media_size_cache, cache_key, size, self.MEDIA_SIZE_CACHE_LIMIT)
            return size

        text_size = self._measure_text_content(message.content or "")
        bubble_width = min(
            self.MAX_TEXT_WIDTH + self.BUBBLE_PADDING_H * 2 + self.TAIL_SPACE,
            max(52, text_size.width() + self.BUBBLE_PADDING_H * 2 + self.TAIL_SPACE),
        )
        bubble_height = max(40, text_size.height() + self.BUBBLE_PADDING_V * 2)
        return QSize(bubble_width, bubble_height)

    def _draw_time_block(self, painter: QPainter, rect: QRect, time_text: str) -> None:
        """Draw centered timestamp text without a visible background."""
        if not time_text:
            return

        font = QFont()
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QColor(210, 210, 210, 230) if isDarkTheme() else QColor("#8A8A8A"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, time_text)

    def _draw_avatar(self, painter: QPainter, rect: QRect, message: ChatMessage) -> None:
        """Draw avatar with initial text when no image is available."""
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 8, 8)

        painter.save()
        painter.setClipPath(path)
        dark = isDarkTheme()
        if message.is_self:
            fill = QColor(themeColor())
            fill.setAlpha(42 if dark else 28)
        else:
            fill = QColor(98, 107, 118) if dark else QColor("#D7DEE8")
            fill.setAlpha(124 if dark else 86)
        painter.fillPath(path, fill)
        painter.restore()

        label = "ME" if message.is_self else ((message.sender_id or "?")[:1].upper())
        font = QFont()
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#DDE7F1") if dark else QColor("#425466"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_bubble(self, painter: QPainter, rect: QRect, message: ChatMessage, avatar_rect: QRect) -> None:
        """Draw a regular bubble or bare media content."""
        if message.message_type in {MessageType.IMAGE, MessageType.VIDEO, MessageType.FILE}:
            if message.message_type == MessageType.IMAGE:
                self._draw_image_content(painter, rect, message)
            elif message.message_type == MessageType.FILE:
                self._draw_file_content(painter, rect, message)
            else:
                self._draw_video_content(painter, rect, message)
            return

        path = self._bubble_path(rect, message.is_self, avatar_rect.center().y())
        dark = isDarkTheme()
        accent = QColor(themeColor())
        if message.is_self:
            bubble_color = QColor(accent)
            bubble_color.setAlpha(58 if dark else 22)
        else:
            bubble_color = QColor(255, 255, 255, 22) if dark else QColor(255, 255, 255, 214)

        painter.fillPath(path, bubble_color)
        painter.setPen(Qt.PenStyle.NoPen)

        content_rect = self._content_rect(rect, message)

        if message.message_type == MessageType.TEXT:
            self._draw_text_content(painter, content_rect, message)
        elif message.message_type == MessageType.IMAGE:
            self._draw_image_content(painter, content_rect, message)
        elif message.message_type == MessageType.FILE:
            self._draw_file_content(painter, content_rect, message)
        elif message.message_type == MessageType.VIDEO:
            self._draw_video_content(painter, content_rect, message)
        else:
            self._draw_text_content(painter, content_rect, message)

    def _draw_text_content(self, painter: QPainter, rect: QRect, message: ChatMessage) -> None:
        """Draw wrapped text content."""
        text_rect, document = self._text_layout(rect, message.content or "")
        context = QAbstractTextDocumentLayout.PaintContext()

        if self.has_selected_text(message.message_id):
            selection = QAbstractTextDocumentLayout.Selection()
            cursor = QTextCursor(document)
            cursor.setPosition(min(self._selection_anchor, self._selection_position))
            cursor.setPosition(max(self._selection_anchor, self._selection_position), QTextCursor.MoveMode.KeepAnchor)
            selection.cursor = cursor

            char_format = QTextCharFormat()
            char_format.setBackground(QColor(86, 157, 229, 120) if isDarkTheme() else QColor(140, 196, 255, 140))
            char_format.setForeground(QColor(255, 255, 255) if isDarkTheme() else QColor("#101010"))
            selection.format = char_format
            context.selections = [selection]

        painter.save()
        painter.translate(text_rect.topLeft())
        document.documentLayout().draw(painter, context)
        painter.restore()

    def _draw_image_content(self, painter: QPainter, rect: QRect, message: ChatMessage) -> None:
        """Draw image preview without an outer bubble."""
        pixmap = self._load_pixmap(message)
        draw_rect = self._image_draw_rect(rect, message)
        clip_path = QPainterPath()
        clip_path.addRoundedRect(QRectF(draw_rect), 12, 12)

        if pixmap.isNull():
            painter.fillPath(clip_path, QColor(52, 59, 66, 220) if isDarkTheme() else QColor("#EEF2F7"))
            painter.setPen(QColor(216, 216, 216) if isDarkTheme() else QColor("#7A7A7A"))
            painter.drawText(draw_rect, Qt.AlignmentFlag.AlignCenter, "Image")
            self._draw_media_state_overlay(painter, draw_rect, message)
            return

        painter.save()
        painter.setClipPath(clip_path)
        painter.drawPixmap(QRectF(draw_rect), pixmap, QRectF(pixmap.rect()))
        painter.restore()
        self._draw_media_state_overlay(painter, draw_rect, message)

    def _draw_file_content(self, painter: QPainter, rect: QRect, message: ChatMessage) -> None:
        """Draw a standalone file preview card."""
        file_name = message.extra.get("name") or os.path.basename(message.content or "") or "File"
        file_path = message.extra.get("local_path") or (message.content or "")
        fallback_size = message.extra.get("size")
        draw_attachment_card(
            painter,
            rect,
            message_type=MessageType.FILE,
            display_name=file_name,
            file_path=file_path,
            fallback_size=fallback_size,
            dark=isDarkTheme(),
        )

    def _draw_video_content(self, painter: QPainter, rect: QRect, message: ChatMessage) -> None:
        """Draw a video cover with play button and duration overlay."""
        cover_rect = rect
        cover_path = QPainterPath()
        cover_path.addRoundedRect(QRectF(cover_rect), 12, 12)

        thumbnail = self._load_video_thumbnail(message)
        if thumbnail.isNull():
            painter.fillPath(cover_path, QColor(58, 63, 70, 220) if isDarkTheme() else QColor("#EEF2F7"))
            painter.setPen(QColor(216, 216, 216) if isDarkTheme() else QColor("#7A7A7A"))
            painter.drawText(cover_rect, Qt.AlignmentFlag.AlignCenter, "Video")
        else:
            source_rect = self._video_cover_source_rect(thumbnail.size(), cover_rect.size())
            painter.save()
            painter.setClipPath(cover_path)
            painter.drawPixmap(cover_rect, thumbnail, source_rect)
            painter.restore()

        painter.save()
        painter.setClipPath(cover_path)
        painter.fillRect(cover_rect, QColor(0, 0, 0, 26))
        painter.restore()

        self._draw_video_play_overlay(painter, cover_rect)
        self._draw_video_duration(painter, cover_rect, message)
        self._draw_media_state_overlay(painter, cover_rect, message)

    def _status_badge_rect(self, bubble_rect: QRect, row_rect: QRect) -> QRect:
        """Return the rect for the self-message status badge."""
        size = self.STATUS_BADGE_SIZE
        x = max(row_rect.x() + self.LEFT_MARGIN, bubble_rect.x() - self.BUBBLE_GAP - size)
        y = bubble_rect.y() + max(0, bubble_rect.height() - size - 6)
        return QRect(x, y, size, size)

    def _draw_status_badge(self, painter: QPainter, rect: QRect, message: ChatMessage) -> None:
        """Draw a Fluent IconInfoBadge-like status badge on the left of self bubbles."""
        badge = self._status_badge_style(message)
        if badge is None:
            return

        color, icon = badge
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(rect)

        icon_rect = QRectF(
            rect.x() + (rect.width() - 8) / 2,
            rect.y() + (rect.height() - 8) / 2,
            8,
            8,
        )
        icon.render(painter, icon_rect, Theme.DARK if not isDarkTheme() else Theme.LIGHT)
        painter.restore()

    def _status_badge_style(self, message: ChatMessage) -> tuple[QColor, FluentIcon] | None:
        """Return badge background and icon for message status."""
        dark = isDarkTheme()
        info_color = QColor(157, 157, 157) if dark else QColor(138, 138, 138)
        success_color = QColor(108, 203, 95) if dark else QColor(15, 123, 15)
        error_color = QColor(255, 153, 164) if dark else QColor(196, 43, 28)
        accent_color = QColor(themeColor())

        if self._is_uploading(message):
            return info_color, FluentIcon.SYNC
        if message.status in (MessageStatus.PENDING, MessageStatus.SENDING):
            return info_color, FluentIcon.SEND
        if message.status == MessageStatus.SENT:
            return info_color, FluentIcon.ACCEPT_MEDIUM
        if message.status == MessageStatus.DELIVERED:
            return success_color, FluentIcon.COMPLETED
        if message.status == MessageStatus.READ:
            return accent_color, FluentIcon.COMPLETED
        if message.status == MessageStatus.FAILED:
            return error_color, FluentIcon.CANCEL_MEDIUM
        return None

    def _draw_media_state_overlay(self, painter: QPainter, rect: QRect, message: ChatMessage) -> None:
        """Overlay media preview with upload state text."""
        state_text = self._media_state_text(message)
        if not state_text:
            return

        overlay_path = QPainterPath()
        overlay_path.addRoundedRect(QRectF(rect), 10, 10)
        overlay_color = QColor(0, 0, 0, 88) if self._is_uploading(message) else QColor(166, 35, 35, 112)
        painter.fillPath(overlay_path, overlay_color)

        font = QFont()
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, state_text)

    def _attachment_description(self, message: ChatMessage, default: str) -> str:
        """Return card secondary text based on upload state."""
        if self._is_uploading(message):
            return "Uploading..."
        if message.status == MessageStatus.FAILED:
            return "Upload failed, right click to retry"
        return default

    def _attachment_desc_color(self, message: ChatMessage) -> QColor:
        """Return attachment description color."""
        if message.status == MessageStatus.FAILED:
            return QColor("#D84A4A")
        if self._is_uploading(message):
            return QColor(themeColor())
        return QColor(196, 196, 196) if isDarkTheme() else QColor("#7A7A7A")

    def _media_state_text(self, message: ChatMessage) -> str:
        """Return image/video overlay text."""
        if self._is_uploading(message):
            return "Uploading..."
        if message.status == MessageStatus.FAILED:
            return "Upload failed"
        return ""

    def _layout_rects(self, row_rect: QRect, message: ChatMessage) -> tuple[QRect, QRect, QRect]:
        """Compute avatar, bubble, and content rectangles for a row."""
        bubble_size = self._bubble_size(message)
        row_top = row_rect.y() + 8
        body_height = max(bubble_size.height(), self.AVATAR_SIZE)
        standalone_attachment = message.message_type in {MessageType.IMAGE, MessageType.VIDEO, MessageType.FILE}
        avatar_y = row_top if standalone_attachment else row_top + (body_height - self.AVATAR_SIZE) // 2
        bubble_y = row_top if standalone_attachment else row_top + (body_height - bubble_size.height()) // 2
        bubble_gap = self.BUBBLE_GAP + (self.TAIL_SPACE if standalone_attachment else 0)

        if message.is_self:
            avatar_rect = QRect(
                row_rect.right() - self.RIGHT_MARGIN - self.AVATAR_SIZE,
                avatar_y,
                self.AVATAR_SIZE,
                self.AVATAR_SIZE,
            )
            bubble_rect = QRect(
                avatar_rect.x() - bubble_gap - bubble_size.width(),
                bubble_y,
                bubble_size.width(),
                bubble_size.height(),
            )
        else:
            avatar_rect = QRect(
                row_rect.x() + self.LEFT_MARGIN,
                avatar_y,
                self.AVATAR_SIZE,
                self.AVATAR_SIZE,
            )
            bubble_rect = QRect(
                avatar_rect.right() + bubble_gap,
                bubble_y,
                bubble_size.width(),
                bubble_size.height(),
            )

        return avatar_rect, bubble_rect, self._content_rect(bubble_rect, message)

    def _content_rect(self, bubble_rect: QRect, message: ChatMessage) -> QRect:
        """Return the inner bubble content rectangle."""
        if message.message_type in {MessageType.IMAGE, MessageType.VIDEO, MessageType.FILE}:
            return bubble_rect
        return bubble_rect.adjusted(
            self.BUBBLE_PADDING_H + self.TAIL_SPACE if not message.is_self else 12,
            self.BUBBLE_PADDING_V,
            -12 if not message.is_self else -(self.BUBBLE_PADDING_H + self.TAIL_SPACE),
            -self.BUBBLE_PADDING_V,
        )

    def _attachment_hit_rect(self, content_rect: QRect, message: ChatMessage) -> QRect:
        """Return the clickable rect for image/file/video messages."""
        if message.message_type == MessageType.IMAGE:
            return self._image_draw_rect(content_rect, message)
        if message.message_type == MessageType.VIDEO:
            return content_rect
        return content_rect

    def _image_draw_rect(self, rect: QRect, message: ChatMessage) -> QRect:
        """Return the actual image draw rect for a bubble-less image message."""
        pixmap = self._load_pixmap(message)
        cache_key = (
            message.message_id,
            rect.width(),
            rect.height(),
            pixmap.width(),
            pixmap.height(),
        )
        cached_rect = self._cache_get(self._image_rect_cache, cache_key)
        if cached_rect is not None:
            return QRect(
                rect.x() + cached_rect.x(),
                rect.y() + cached_rect.y(),
                cached_rect.width(),
                cached_rect.height(),
            )

        if pixmap.isNull():
            fallback = QRect(0, 0, max(120, rect.width()), max(96, rect.height()))
            self._cache_put(self._image_rect_cache, cache_key, fallback, self.IMAGE_RECT_CACHE_LIMIT)
            return QRect(rect.x(), rect.y(), fallback.width(), fallback.height())

        scaled = self._contained_size(pixmap.size(), rect.size())
        image_rect = QRect(
            max(0, (rect.width() - scaled.width()) // 2),
            max(0, (rect.height() - scaled.height()) // 2),
            scaled.width(),
            scaled.height(),
        )
        self._cache_put(self._image_rect_cache, cache_key, image_rect, self.IMAGE_RECT_CACHE_LIMIT)
        return QRect(rect.x() + image_rect.x(), rect.y() + image_rect.y(), image_rect.width(), image_rect.height())

    def _load_video_thumbnail(self, message: ChatMessage) -> QPixmap:
        """Load a cached thumbnail for a video message and request async generation on miss."""
        source = self._resolve_video_source(message)
        if not source:
            return QPixmap()
        thumbnail = get_video_thumbnail(source)
        if thumbnail is None:
            self._video_thumbnail_cache.request_thumbnail(source)
            return QPixmap()
        return thumbnail

    def _resolve_video_source(self, message: ChatMessage) -> str:
        """Resolve the best local path or URL for a video message."""
        local_path = message.extra.get("local_path") if message.extra else None
        if local_path and os.path.exists(local_path):
            return local_path

        content = ((message.extra.get("url") if message.extra else None) or (message.content or "").strip())
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

    def _draw_video_play_overlay(self, painter: QPainter, rect: QRect) -> None:
        """Draw the center play button for a video cover."""
        circle_size = 46
        circle_rect = QRect(
            rect.center().x() - circle_size // 2,
            rect.center().y() - circle_size // 2,
            circle_size,
            circle_size,
        )
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 110))
        painter.drawEllipse(circle_rect)

        triangle = QPainterPath()
        triangle.moveTo(circle_rect.center().x() - 5, circle_rect.center().y() - 9)
        triangle.lineTo(circle_rect.center().x() - 5, circle_rect.center().y() + 9)
        triangle.lineTo(circle_rect.center().x() + 10, circle_rect.center().y())
        triangle.closeSubpath()
        painter.fillPath(triangle, QColor(255, 255, 255))
        painter.restore()

    def _draw_video_duration(self, painter: QPainter, rect: QRect, message: ChatMessage) -> None:
        """Draw the video duration pill in the bottom-right corner."""
        duration_text = self._format_video_duration(message)
        if not duration_text:
            return

        font = QFont()
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        text_width = metrics.horizontalAdvance(duration_text)
        text_rect = QRect(rect.right() - text_width - 10, rect.bottom() - 24, text_width, 16)

        painter.save()
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, duration_text)
        painter.restore()

    @staticmethod
    def _video_cover_source_rect(source_size: QSize, target_size: QSize) -> QRect:
        """Crop the source thumbnail so it fills the target cover rect."""
        source_width = max(1, source_size.width())
        source_height = max(1, source_size.height())
        target_width = max(1, target_size.width())
        target_height = max(1, target_size.height())

        source_ratio = source_width / source_height
        target_ratio = target_width / target_height

        if source_ratio > target_ratio:
            crop_width = max(1, int(round(source_height * target_ratio)))
            crop_x = max(0, (source_width - crop_width) // 2)
            return QRect(crop_x, 0, crop_width, source_height)

        crop_height = max(1, int(round(source_width / target_ratio)))
        crop_y = max(0, (source_height - crop_height) // 2)
        return QRect(0, crop_y, source_width, crop_height)

    def _format_video_duration(self, message: ChatMessage) -> str:
        """Format duration stored in message metadata without probing synchronously."""
        duration = (message.extra or {}).get("duration")
        if duration not in (None, ""):
            try:
                total_seconds = int(float(duration))
            except (TypeError, ValueError):
                total_seconds = -1
            if total_seconds >= 0:
                duration_text = self._seconds_to_duration_text(total_seconds)
                source = self._resolve_video_source(message)
                if source:
                    self._video_duration_cache[source] = duration_text
                return duration_text

        source = self._resolve_video_source(message)
        return self._video_duration_cache.get(source, "") if source else ""

    @staticmethod
    def _seconds_to_duration_text(total_seconds: int) -> str:
        """Convert seconds to a video duration label."""
        total_seconds = max(0, total_seconds)
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _measure_text_content(self, content: str) -> QSize:
        """Measure wrapped text using wrap-anywhere to avoid clipping digits/URLs."""
        text = content or ""
        cached_size = self._cache_get(self._text_measure_cache, text)
        if cached_size is not None:
            return cached_size

        font = self._text_font()
        fm = QFontMetrics(font)
        if not text:
            size = QSize(18, fm.height())
            self._cache_put(self._text_measure_cache, text, size, self.TEXT_MEASURE_CACHE_LIMIT)
            return size

        text_rect = fm.boundingRect(
            QRect(0, 0, self.MAX_TEXT_WIDTH, 4000),
            self._text_measure_flags(),
            text,
        )
        size = QSize(max(18, text_rect.width()), max(fm.height(), text_rect.height()))
        self._cache_put(self._text_measure_cache, text, size, self.TEXT_MEASURE_CACHE_LIMIT)
        return size

    @staticmethod
    def _text_measure_flags() -> Qt.TextFlag | Qt.AlignmentFlag:
        """Flags used when measuring text bubbles."""
        return Qt.TextFlag.TextWrapAnywhere | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop

    @staticmethod
    def _text_draw_flags() -> Qt.TextFlag | Qt.AlignmentFlag:
        """Flags used when drawing text bubbles."""
        return Qt.TextFlag.TextWrapAnywhere | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop

    @staticmethod
    def _text_font() -> QFont:
        """Return the font used for text messages."""
        font = QFont()
        font.setPixelSize(14)
        return font

    def _text_layout(self, rect: QRect, content: str) -> tuple[QRect, QTextDocument]:
        """Create the document and draw rect for a text bubble."""
        width = max(1, rect.width())
        cache_key = (width, content or "")
        cached_layout = self._cache_get(self._text_layout_cache, cache_key)
        if cached_layout is not None:
            text_height, document = cached_layout
            return QRect(rect.x(), rect.y(), width, text_height), document

        document = QTextDocument()
        document.setDocumentMargin(0)
        document.setDefaultFont(self._text_font())

        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAnywhere)
        document.setDefaultTextOption(option)
        document.setPlainText(content or "")
        document.setTextWidth(width)

        text_height = max(1, int(round(document.size().height())))
        self._cache_put(
            self._text_layout_cache,
            cache_key,
            (text_height, document),
            self.TEXT_LAYOUT_CACHE_LIMIT,
        )
        return QRect(rect.x(), rect.y(), width, text_height), document

    @staticmethod
    def _cache_get(cache, key):
        """Return a cached value while updating LRU order."""
        value = cache.get(key)
        if value is None:
            return None
        cache.move_to_end(key)
        return value

    @staticmethod
    def _cache_put(cache, key, value, limit: int) -> None:
        """Store a cached value and trim the oldest entries."""
        if key in cache:
            cache.pop(key)
        cache[key] = value
        while len(cache) > limit:
            cache.popitem(last=False)

    def _text_position_for_point(
        self,
        document: QTextDocument,
        text_rect: QRect,
        position: QPoint,
        *,
        clamp: bool,
    ) -> int:
        """Map a viewport point into a text cursor position."""
        local_x = position.x() - text_rect.x()
        local_y = position.y() - text_rect.y()

        if not clamp and (local_x < 0 or local_y < 0 or local_x > text_rect.width() or local_y > text_rect.height()):
            return -1

        local_x = max(0, min(local_x, text_rect.width()))
        local_y = max(0, min(local_y, text_rect.height()))
        return document.documentLayout().hitTest(QPointF(local_x, local_y), Qt.HitTestAccuracy.FuzzyHit)

    @staticmethod
    def _is_uploading(message: ChatMessage) -> bool:
        """Return whether the message is still in HTTP upload stage."""
        return bool(getattr(message, "extra", {}) and message.extra.get("uploading"))

    def _bubble_path(self, rect: QRect, is_self: bool, avatar_center_y: int) -> QPainterPath:
        """Create a rounded bubble with a small tail aligned to the avatar center."""
        radius = 10
        tail_width = 8
        tail_height = 12
        tail_mid = max(rect.top() + radius + 8, min(avatar_center_y, rect.bottom() - radius - 8))

        path = QPainterPath()

        if is_self:
            path.moveTo(rect.left() + radius, rect.top())
            path.lineTo(rect.right() - tail_width - radius, rect.top())
            path.quadTo(rect.right() - tail_width, rect.top(), rect.right() - tail_width, rect.top() + radius)
            path.lineTo(rect.right() - tail_width, tail_mid - tail_height / 2)
            path.lineTo(rect.right(), tail_mid)
            path.lineTo(rect.right() - tail_width, tail_mid + tail_height / 2)
            path.lineTo(rect.right() - tail_width, rect.bottom() - radius)
            path.quadTo(rect.right() - tail_width, rect.bottom(), rect.right() - tail_width - radius, rect.bottom())
            path.lineTo(rect.left() + radius, rect.bottom())
            path.quadTo(rect.left(), rect.bottom(), rect.left(), rect.bottom() - radius)
            path.lineTo(rect.left(), rect.top() + radius)
            path.quadTo(rect.left(), rect.top(), rect.left() + radius, rect.top())
        else:
            path.moveTo(rect.left() + tail_width + radius, rect.top())
            path.lineTo(rect.right() - radius, rect.top())
            path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + radius)
            path.lineTo(rect.right(), rect.bottom() - radius)
            path.quadTo(rect.right(), rect.bottom(), rect.right() - radius, rect.bottom())
            path.lineTo(rect.left() + tail_width + radius, rect.bottom())
            path.quadTo(rect.left() + tail_width, rect.bottom(), rect.left() + tail_width, rect.bottom() - radius)
            path.lineTo(rect.left() + tail_width, tail_mid + tail_height / 2)
            path.lineTo(rect.left(), tail_mid)
            path.lineTo(rect.left() + tail_width, tail_mid - tail_height / 2)
            path.lineTo(rect.left() + tail_width, rect.top() + radius)
            path.quadTo(rect.left() + tail_width, rect.top(), rect.left() + tail_width + radius, rect.top())

        return path

    def _should_show_time(self, index: QModelIndex, message: ChatMessage) -> bool:
        """Show time if this is the first message or minute changed."""
        if index.row() == 0:
            return True

        previous_index = index.model().index(index.row() - 1, 0)
        previous_message = previous_index.data(Qt.ItemDataRole.UserRole)
        if not previous_message:
            return True

        current_time = self._normalize_datetime(message.timestamp)
        previous_time = self._normalize_datetime(previous_message.timestamp)

        if current_time is None or previous_time is None:
            return True

        return current_time.strftime("%Y-%m-%d %H:%M") != previous_time.strftime("%Y-%m-%d %H:%M")

    def _format_time(self, value) -> str:
        """Format message time for the center time block."""
        moment = self._normalize_datetime(value)
        if moment is None:
            return ""
        now = datetime.now()
        today = now.date()
        moment_date = moment.date()

        if moment_date == today:
            return moment.strftime("%H:%M")
        if moment_date == today - timedelta(days=1):
            return moment.strftime("昨天 %H:%M")

        day_delta = (today - moment_date).days
        if 1 < day_delta <= 7:
            weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
            return f"{weekdays[moment.weekday()]} {moment.strftime('%H:%M')}"

        if moment.year == now.year:
            return f"{moment.month}月{moment.day}日 {moment.strftime('%H:%M')}"

        return f"{moment.year}年{moment.month}月{moment.day}日 {moment.strftime('%H:%M')}"

    def _normalize_datetime(self, value) -> datetime | None:
        """Normalize timestamp values from the message model."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    def _load_pixmap(self, message: ChatMessage) -> QPixmap:
        """Load image from local path, cache, or remote URL."""
        source = self._resolve_image_source(message)
        if not source:
            return QPixmap()

        cached = self._image_cache.get(source)
        if cached is not None:
            return cached

        if os.path.exists(source):
            pixmap = self._load_local_pixmap(source)
            if not pixmap.isNull():
                self._image_cache[source] = pixmap
                return pixmap
            return QPixmap()

        self._request_image(source)
        return QPixmap()

    def _load_local_pixmap(self, source: str) -> QPixmap:
        """Load a scaled local image once and cache it for later paints."""
        reader = QImageReader(source)
        reader.setAutoTransform(True)

        source_size = reader.size()
        if source_size.isValid() and source_size.width() > 0 and source_size.height() > 0:
            max_width = self.MAX_IMAGE_WIDTH * 2
            max_height = self.MAX_IMAGE_HEIGHT * 2
            source_width = source_size.width()
            source_height = source_size.height()
            scale = min(max_width / source_width, max_height / source_height, 1.0)
            if scale < 1.0:
                reader.setScaledSize(
                    QSize(
                        max(1, int(source_width * scale)),
                        max(1, int(source_height * scale)),
                    )
                )

        image = reader.read()
        if image.isNull():
            return QPixmap()

        return QPixmap.fromImage(image)

    @staticmethod
    def _contained_size(source_size: QSize, target_size: QSize) -> QSize:
        """Return a keep-aspect-ratio size without allocating a scaled pixmap."""
        source_width = max(1, source_size.width())
        source_height = max(1, source_size.height())
        target_width = max(1, target_size.width())
        target_height = max(1, target_size.height())
        scale = min(target_width / source_width, target_height / source_height)
        return QSize(
            max(1, int(round(source_width * scale))),
            max(1, int(round(source_height * scale))),
        )

    def _resolve_image_source(self, message: ChatMessage) -> str:
        """Resolve the best image source for a message."""
        local_path = message.extra.get("local_path") if message.extra else None
        if local_path and os.path.exists(local_path):
            return local_path

        content = (message.content or "").strip()
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

    def _request_image(self, source: str) -> None:
        """Start downloading a remote image if needed."""
        if not source or source in self._loading_sources:
            return

        self._loading_sources.add(source)
        reply = self._network_manager.get(QNetworkRequest(QUrl(source)))
        reply.setProperty("image_source", source)

    def _on_image_reply_finished(self, reply: QNetworkReply) -> None:
        """Cache downloaded images and refresh the list view."""
        source = reply.property("image_source") or ""
        self._loading_sources.discard(source)

        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                return

            pixmap = QPixmap()
            if not pixmap.loadFromData(bytes(reply.readAll())):
                return

            if pixmap.width() > self.MAX_IMAGE_WIDTH * 2 or pixmap.height() > self.MAX_IMAGE_HEIGHT * 2:
                target = self._contained_size(
                    pixmap.size(),
                    QSize(self.MAX_IMAGE_WIDTH * 2, self.MAX_IMAGE_HEIGHT * 2),
                )
                pixmap = pixmap.scaled(
                    target,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

            self._image_cache[source] = pixmap
            self._schedule_refresh_message_view()
        finally:
            reply.deleteLater()

    def _on_video_thumbnail_ready(self, source: str) -> None:
        """Refresh the view after a background video thumbnail finishes generating."""
        if source:
            self._schedule_refresh_message_view()

    def _schedule_refresh_message_view(self) -> None:
        """Coalesce async media refreshes into a single view update."""
        if self._refresh_scheduled:
            return
        self._refresh_scheduled = True
        QTimer.singleShot(0, self._refresh_message_view)

    def _refresh_message_view(self) -> None:
        """Re-layout the chat list after an async image load."""
        self._refresh_scheduled = False
        parent = self.parent()
        if parent is None or not hasattr(parent, "get_message_list"):
            return

        message_list = parent.get_message_list()
        message_list.doItemsLayout()
        message_list.viewport().update()
