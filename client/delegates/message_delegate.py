"""Message delegate that migrates the old bubble-style chat UI."""

from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import QModelIndex, QRect, QRectF, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

from client.core.config_backend import get_config
from client.models.message import ChatMessage, MessageStatus, MessageType


class MessageDelegate(QStyledItemDelegate):
    """Render text, image, and file messages in a Fluent bubble layout."""

    AVATAR_SIZE = 40
    MAX_TEXT_WIDTH = 320
    MAX_IMAGE_WIDTH = 240
    MAX_IMAGE_HEIGHT = 180
    FILE_WIDTH = 260
    FILE_HEIGHT = 74
    VIDEO_WIDTH = 260
    VIDEO_HEIGHT = 74
    LEFT_MARGIN = 18
    RIGHT_MARGIN = 18
    BUBBLE_GAP = 10
    BUBBLE_PADDING_H = 14
    BUBBLE_PADDING_V = 10
    TIME_BLOCK_HEIGHT = 26
    STATUS_HEIGHT = 16

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image_cache: dict[str, QPixmap] = {}
        self._loading_sources: set[str] = set()
        self._network_manager = QNetworkAccessManager(self)
        self._network_manager.finished.connect(self._on_image_reply_finished)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        """Return message item size based on type and timestamp visibility."""
        message = index.data(Qt.ItemDataRole.UserRole)
        if not message:
            return QSize(option.rect.width(), 0)

        content_size = self._bubble_size(message)
        total_height = max(content_size.height(), self.AVATAR_SIZE) + 18

        if self._should_show_time(index, message):
            total_height += self.TIME_BLOCK_HEIGHT

        if message.is_self:
            total_height += self.STATUS_HEIGHT

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
        self._draw_bubble(painter, bubble_rect, message)

        footer_top = max(bubble_rect.bottom(), avatar_rect.bottom()) + 2

        if message.is_self:
            status_rect = QRect(
                bubble_rect.x(),
                footer_top,
                bubble_rect.width(),
                self.STATUS_HEIGHT,
            )
            self._draw_status(painter, status_rect, message)
            footer_top = status_rect.bottom() + 2

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

    def _bubble_size(self, message: ChatMessage) -> QSize:
        """Compute bubble size for the current message type."""
        if message.message_type == MessageType.IMAGE:
            pixmap = self._load_pixmap(message)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    QSize(self.MAX_IMAGE_WIDTH, self.MAX_IMAGE_HEIGHT),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                return QSize(max(120, scaled.width()), max(96, scaled.height()))
            return QSize(160, 116)

        if message.message_type == MessageType.FILE:
            return QSize(self.FILE_WIDTH, self.FILE_HEIGHT)

        if message.message_type == MessageType.VIDEO:
            return QSize(self.VIDEO_WIDTH, self.VIDEO_HEIGHT)

        text = message.content or ""
        font = QFont()
        font.setPixelSize(14)
        fm = QFontMetrics(font)
        text_rect = fm.boundingRect(
            QRect(0, 0, self.MAX_TEXT_WIDTH, 4000),
            Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft,
            text,
        )
        bubble_width = min(self.MAX_TEXT_WIDTH, max(84, text_rect.width() + self.BUBBLE_PADDING_H * 2))
        bubble_height = max(42, text_rect.height() + self.BUBBLE_PADDING_V * 2)
        return QSize(bubble_width, bubble_height)

    def _draw_time_block(self, painter: QPainter, rect: QRect, time_text: str) -> None:
        """Draw centered timestamp capsule."""
        if not time_text:
            return

        font = QFont()
        font.setPixelSize(11)
        painter.setFont(font)
        fm = QFontMetrics(font)
        pill_width = max(68, fm.horizontalAdvance(time_text) + 18)
        pill_rect = QRect(
            rect.center().x() - pill_width // 2,
            rect.y() + 2,
            pill_width,
            20,
        )

        path = QPainterPath()
        path.addRoundedRect(QRectF(pill_rect), 10, 10)
        painter.fillPath(path, QColor(245, 247, 250))
        painter.setPen(QColor("#8A8A8A"))
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, time_text)

    def _draw_avatar(self, painter: QPainter, rect: QRect, message: ChatMessage) -> None:
        """Draw avatar with initial text when no image is available."""
        path = QPainterPath()
        path.addEllipse(rect)

        painter.save()
        painter.setClipPath(path)
        painter.fillPath(path, QColor("#D7DEE8") if not message.is_self else QColor("#CFE8C7"))
        painter.restore()

        label = "ME" if message.is_self else ((message.sender_id or "?")[:1].upper())
        font = QFont()
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#425466"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_bubble(self, painter: QPainter, rect: QRect, message: ChatMessage) -> None:
        """Draw bubble frame and inner content."""
        path = self._bubble_path(rect, message.is_self)
        bubble_color = QColor("#95EC69") if message.is_self else QColor("#FFFFFF")
        border_color = QColor(0, 0, 0, 12) if not message.is_self else QColor(91, 168, 65, 40)

        painter.fillPath(path, bubble_color)
        painter.setPen(QPen(border_color, 1))
        painter.drawPath(path)

        content_rect = self._content_rect(rect, message)

        if message.message_type == MessageType.TEXT:
            self._draw_text_content(painter, content_rect, message.content)
        elif message.message_type == MessageType.IMAGE:
            self._draw_image_content(painter, content_rect, message)
        elif message.message_type == MessageType.FILE:
            self._draw_file_content(painter, content_rect, message)
        elif message.message_type == MessageType.VIDEO:
            self._draw_video_content(painter, content_rect, message)
        else:
            self._draw_text_content(painter, content_rect, message.content)

    def _draw_text_content(self, painter: QPainter, rect: QRect, content: str) -> None:
        """Draw wrapped text content."""
        font = QFont()
        font.setPixelSize(14)
        painter.setFont(font)
        painter.setPen(QColor("#101010"))
        painter.drawText(
            rect,
            Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            content or "",
        )

    def _draw_image_content(self, painter: QPainter, rect: QRect, message: ChatMessage) -> None:
        """Draw image preview or a fallback placeholder."""
        pixmap = self._load_pixmap(message)
        if pixmap.isNull():
            placeholder = self._image_draw_rect(rect, message)
            path = QPainterPath()
            path.addRoundedRect(QRectF(placeholder), 10, 10)
            painter.fillPath(path, QColor("#EEF2F7"))
            painter.setPen(QColor("#7A7A7A"))
            painter.drawText(placeholder, Qt.AlignmentFlag.AlignCenter, "Image")
            self._draw_media_state_overlay(painter, placeholder, message)
            return

        draw_rect = self._image_draw_rect(rect, message)
        scaled = pixmap.scaled(
            draw_rect.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap(draw_rect, scaled)
        self._draw_media_state_overlay(painter, draw_rect, message)

    def _draw_file_content(self, painter: QPainter, rect: QRect, message: ChatMessage) -> None:
        """Draw file card inside the bubble."""
        icon_rect = QRect(rect.x(), rect.y() + 6, 40, 40)
        icon_path = QPainterPath()
        icon_path.addRoundedRect(QRectF(icon_rect), 10, 10)
        painter.fillPath(icon_path, QColor("#EAF2FF"))
        painter.setPen(QColor("#3574F0"))
        painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, "F")

        file_name = message.extra.get("name") or os.path.basename(message.content or "") or "File"
        file_desc = self._attachment_description(message, "File")

        title_rect = QRect(icon_rect.right() + 10, rect.y() + 4, rect.width() - 56, 22)
        desc_rect = QRect(icon_rect.right() + 10, rect.y() + 28, rect.width() - 56, 18)

        title_font = QFont()
        title_font.setPixelSize(13)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#202020"))
        title_fm = QFontMetrics(title_font)
        title_text = title_fm.elidedText(file_name, Qt.TextElideMode.ElideRight, title_rect.width())
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title_text)

        desc_font = QFont()
        desc_font.setPixelSize(11)
        painter.setFont(desc_font)
        painter.setPen(self._attachment_desc_color(message))
        painter.drawText(desc_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, file_desc)

    def _draw_video_content(self, painter: QPainter, rect: QRect, message: ChatMessage) -> None:
        """Draw a compact video card inside the bubble."""
        icon_rect = QRect(rect.x(), rect.y() + 6, 40, 40)
        icon_path = QPainterPath()
        icon_path.addRoundedRect(QRectF(icon_rect), 10, 10)
        painter.fillPath(icon_path, QColor("#FFF1E8"))
        painter.setPen(QColor("#E86A33"))
        painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, "V")

        video_name = message.extra.get("name") or os.path.basename(message.content or "") or "Video"
        video_desc = self._attachment_description(message, "Video")

        title_rect = QRect(icon_rect.right() + 10, rect.y() + 4, rect.width() - 56, 22)
        desc_rect = QRect(icon_rect.right() + 10, rect.y() + 28, rect.width() - 56, 18)

        title_font = QFont()
        title_font.setPixelSize(13)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#202020"))
        title_fm = QFontMetrics(title_font)
        title_text = title_fm.elidedText(video_name, Qt.TextElideMode.ElideRight, title_rect.width())
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title_text)

        desc_font = QFont()
        desc_font.setPixelSize(11)
        painter.setFont(desc_font)
        painter.setPen(self._attachment_desc_color(message))
        painter.drawText(desc_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, video_desc)

    def _draw_status(self, painter: QPainter, rect: QRect, message: ChatMessage) -> None:
        """Draw small delivery state text under self messages."""
        if self._is_uploading(message):
            text = "uploading"
            color = QColor("#4C6EF5")
        elif message.status in (MessageStatus.PENDING, MessageStatus.SENDING):
            text = "sending"
            color = QColor("#8A8A8A")
        elif message.status == MessageStatus.SENT:
            text = "sent"
            color = QColor("#8A8A8A")
        elif message.status == MessageStatus.DELIVERED:
            text = "delivered"
            color = QColor("#6C7785")
        elif message.status == MessageStatus.READ:
            text = "read"
            color = QColor("#2F8F4E")
        elif message.status == MessageStatus.FAILED:
            text = "failed"
            color = QColor("#D84A4A")
        else:
            return

        font = QFont()
        font.setPixelSize(10)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)

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
            return QColor("#4C6EF5")
        return QColor("#7A7A7A")

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

        if message.is_self:
            avatar_rect = QRect(
                row_rect.right() - self.RIGHT_MARGIN - self.AVATAR_SIZE,
                row_top,
                self.AVATAR_SIZE,
                self.AVATAR_SIZE,
            )
            bubble_rect = QRect(
                avatar_rect.x() - self.BUBBLE_GAP - bubble_size.width(),
                row_top,
                bubble_size.width(),
                bubble_size.height(),
            )
        else:
            avatar_rect = QRect(
                row_rect.x() + self.LEFT_MARGIN,
                row_top,
                self.AVATAR_SIZE,
                self.AVATAR_SIZE,
            )
            bubble_rect = QRect(
                avatar_rect.right() + self.BUBBLE_GAP,
                row_top,
                bubble_size.width(),
                bubble_size.height(),
            )

        return avatar_rect, bubble_rect, self._content_rect(bubble_rect, message)

    def _content_rect(self, bubble_rect: QRect, message: ChatMessage) -> QRect:
        """Return the inner bubble content rectangle."""
        return bubble_rect.adjusted(
            self.BUBBLE_PADDING_H if not message.is_self else 12,
            self.BUBBLE_PADDING_V,
            -12 if not message.is_self else -self.BUBBLE_PADDING_H,
            -self.BUBBLE_PADDING_V,
        )

    def _attachment_hit_rect(self, content_rect: QRect, message: ChatMessage) -> QRect:
        """Return the clickable rect for image/file/video messages."""
        if message.message_type == MessageType.IMAGE:
            return self._image_draw_rect(content_rect, message)
        return content_rect

    def _image_draw_rect(self, rect: QRect, message: ChatMessage) -> QRect:
        """Return the actual image draw rect inside the bubble."""
        pixmap = self._load_pixmap(message)
        if pixmap.isNull():
            return QRect(rect.x(), rect.y(), max(120, rect.width()), max(96, rect.height()))

        scaled = pixmap.scaled(
            rect.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        return QRect(rect.x(), rect.y(), scaled.width(), scaled.height())

    @staticmethod
    def _is_uploading(message: ChatMessage) -> bool:
        """Return whether the message is still in HTTP upload stage."""
        return bool(getattr(message, "extra", {}) and message.extra.get("uploading"))

    def _bubble_path(self, rect: QRect, is_self: bool) -> QPainterPath:
        """Create a bubble path with a subtle tail."""
        radius = 10
        tail_width = 8
        tail_height = 10
        tail_mid = rect.height() / 2

        path = QPainterPath()

        if is_self:
            path.moveTo(rect.left() + radius, rect.top())
            path.lineTo(rect.right() - tail_width - radius, rect.top())
            path.quadTo(rect.right() - tail_width, rect.top(), rect.right() - tail_width, rect.top() + radius)
            path.lineTo(rect.right() - tail_width, rect.top() + tail_mid - tail_height / 2)
            path.lineTo(rect.right(), rect.top() + tail_mid)
            path.lineTo(rect.right() - tail_width, rect.top() + tail_mid + tail_height / 2)
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
            path.lineTo(rect.left() + tail_width, rect.top() + tail_mid + tail_height / 2)
            path.lineTo(rect.left(), rect.top() + tail_mid)
            path.lineTo(rect.left() + tail_width, rect.top() + tail_mid - tail_height / 2)
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
        return moment.strftime("%m-%d %H:%M")

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

        if os.path.exists(source):
            return QPixmap(source)

        cached = self._image_cache.get(source)
        if cached is not None:
            return cached

        self._request_image(source)
        return QPixmap()

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

            self._image_cache[source] = pixmap
            self._refresh_message_view()
        finally:
            reply.deleteLater()

    def _refresh_message_view(self) -> None:
        """Re-layout the chat list after an async image load."""
        parent = self.parent()
        if parent is None or not hasattr(parent, "get_message_list"):
            return

        message_list = parent.get_message_list()
        message_list.doItemsLayout()
        message_list.viewport().update()
