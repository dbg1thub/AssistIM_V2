"""Session list delegate styled after the previous chat prototype."""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem
from qfluentwidgets import isDarkTheme, themeColor

from client.models.message import format_message_preview


class SessionDelegate(QStyledItemDelegate):
    """Render chat sessions with avatar, preview, time, and unread badge."""

    AVATAR_SIZE = 44
    ITEM_HEIGHT = 76
    H_MARGIN = 0
    V_MARGIN = 0

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        """Return fixed session row height."""
        return QSize(option.rect.width(), self.ITEM_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        """Paint a single session row."""
        session = index.data(Qt.ItemDataRole.UserRole)
        if not session:
            return super().paint(painter, option, index)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        card_rect = option.rect.adjusted(self.H_MARGIN, self.V_MARGIN, -self.H_MARGIN, -self.V_MARGIN)
        self._draw_background(painter, card_rect, option)

        avatar_rect = QRect(
            card_rect.x() + 12,
            card_rect.y() + (card_rect.height() - self.AVATAR_SIZE) // 2,
            self.AVATAR_SIZE,
            self.AVATAR_SIZE,
        )
        self._draw_avatar(painter, avatar_rect, session)

        content_left = avatar_rect.right() + 12
        content_right = card_rect.right() - 12
        content_width = max(120, content_right - content_left)

        name_font = QFont()
        name_font.setPixelSize(15)
        name_fm = QFontMetrics(name_font)

        preview_font = QFont()
        preview_font.setPixelSize(12)
        preview_fm = QFontMetrics(preview_font)

        time_font = QFont()
        time_font.setPixelSize(11)
        time_fm = QFontMetrics(time_font)

        time_text = self._format_time(session.last_message_time or session.updated_at)
        time_width = max(42, time_fm.horizontalAdvance(time_text) + 4)

        unread_text = self._format_unread(session.unread_count)
        unread_width = 0
        if unread_text:
            unread_width = max(16, preview_fm.horizontalAdvance(unread_text) + 12)

        name_available = max(80, content_width - time_width - unread_width - 18)
        name_text = name_fm.elidedText(session.name or "未命名会话", Qt.TextElideMode.ElideRight, name_available)
        preview_available = max(80, content_width)
        preview_text = preview_fm.elidedText(
            self._format_preview_text(session),
            Qt.TextElideMode.ElideRight,
            preview_available,
        )

        name_y = card_rect.y() + 14
        preview_y = name_y + 24

        secondary_text = QColor(216, 216, 216) if isDarkTheme() else QColor(95, 95, 95)
        primary_text = QColor(255, 255, 255) if isDarkTheme() else QColor(0, 0, 0)
        preview_color = primary_text if session.unread_count > 0 else secondary_text
        time_color = QColor(196, 196, 196) if isDarkTheme() else QColor(122, 122, 122)

        painter.setFont(name_font)
        painter.setPen(primary_text)
        painter.drawText(
            QRect(content_left, name_y, name_available, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            name_text,
        )

        badge_anchor_x = content_left + name_fm.horizontalAdvance(name_text) + 8
        if unread_text:
            badge_rect = QRect(badge_anchor_x, name_y + 2, unread_width, 16)
            self._draw_unread_badge(painter, badge_rect, unread_text)

        painter.setFont(preview_font)
        painter.setPen(preview_color)
        painter.drawText(
            QRect(content_left, preview_y, preview_available, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            preview_text,
        )

        painter.setFont(time_font)
        painter.setPen(time_color)
        painter.drawText(
            QRect(content_right - time_width, name_y, time_width, 18),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            time_text,
        )

        painter.restore()

    def _draw_background(self, painter: QPainter, rect: QRect, option: QStyleOptionViewItem) -> None:
        """Draw rounded background for hover/selected state."""
        dark = isDarkTheme()
        if option.state & QStyle.StateFlag.State_Selected:
            color = QColor(255, 255, 255, 38) if dark else QColor(0, 0, 0, 18)
            border = QColor(255, 255, 255, 0)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            color = QColor(255, 255, 255, 24) if dark else QColor(0, 0, 0, 10)
            border = QColor(255, 255, 255, 0)
        else:
            color = QColor(255, 255, 255, 0)
            border = QColor(255, 255, 255, 0)

        painter.fillRect(rect, color)
        if border.alpha() > 0:
            painter.setPen(QPen(border, 1))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))

    def _draw_avatar(self, painter: QPainter, rect: QRect, session) -> None:
        """Draw session avatar or a generated initial avatar."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        painter.setClipPath(path)

        if getattr(session, "avatar", None):
            from PySide6.QtGui import QPixmap

            pixmap = QPixmap(session.avatar)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    rect.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                painter.drawPixmap(rect, scaled)
            else:
                painter.fillPath(path, QColor("#626B76") if isDarkTheme() else QColor("#D7DEE8"))
        else:
            painter.fillPath(path, QColor("#626B76") if isDarkTheme() else QColor("#D7DEE8"))

        painter.setClipping(False)

        if not getattr(session, "avatar", None):
            initial = (session.name or "?")[:1].upper()
            font = QFont()
            font.setPixelSize(18)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, initial)

        painter.restore()

    def _draw_unread_badge(self, painter: QPainter, rect: QRect, text: str) -> None:
        """Draw unread badge using a Fluent InfoBadge-like pill."""
        path = QPainterPath()
        radius = rect.height() / 2
        path.addRoundedRect(rect, radius, radius)
        accent = QColor(themeColor())
        painter.fillPath(path, accent)

        font = QFont()
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _format_unread(self, count: int) -> str:
        """Format unread count display."""
        if count <= 0:
            return ""
        if count > 99:
            return "99+"
        return str(count)

    def _format_preview_text(self, session) -> str:
        """Format preview text for media and file messages."""
        preview = session.last_message or "开始新的对话"
        message_type = session.extra.get("last_message_type") if getattr(session, "extra", None) else None
        return format_message_preview(preview, message_type)

    def _format_time(self, timestamp) -> str:
        """Format timestamp using the previous UI's Chinese-friendly style."""
        moment = self._normalize_datetime(timestamp)
        if moment is None:
            return ""

        now = datetime.now()
        if moment.date() == now.date():
            return moment.strftime("%H:%M")
        if moment.date() == (now.date() - timedelta(days=1)):
            return f"昨天 {moment.strftime('%H:%M')}"
        if (now - moment).days < 7:
            weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
            return weekdays[moment.weekday()]
        return moment.strftime("%Y/%m/%d")

    def _normalize_datetime(self, value) -> datetime | None:
        """Normalize datetime values from model or storage."""
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
