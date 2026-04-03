"""Session list delegate styled after the previous chat prototype."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem
from qfluentwidgets import isDarkTheme

from client.core.app_icons import CollectionIcon
from client.core.avatar_rendering import get_avatar_image_store
from client.core.avatar_utils import profile_avatar_seed
from client.core.datetime_utils import coerce_local_datetime
from client.core.i18n import format_session_timestamp, tr
from client.models.message import format_message_preview
from client.ui.common.emoji_utils import (
    centered_text_baseline,
    centered_emoji_top,
    PREVIEW_EMOJI_PIXEL_SIZE,
    PREVIEW_ONLY_EMOJI_PIXEL_SIZE,
    is_emoji_text,
    iter_text_and_emoji_clusters,
    load_emoji_pixmap,
)


@dataclass
class _PreviewRun:
    """Preview text run used for mixed text/emoji rendering."""

    kind: str
    text: str
    width: int


class SessionDelegate(QStyledItemDelegate):
    """Render chat sessions with avatar, preview, time, and unread badge."""

    AVATAR_SIZE = 44
    ITEM_HEIGHT = 80
    H_MARGIN = 0
    V_MARGIN = 0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._avatar_store = get_avatar_image_store()
        self._avatar_store.avatar_ready.connect(self._on_avatar_ready)
        self._mute_icon = CollectionIcon("alert_off")

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
        painter.setClipRect(option.rect)

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
        content_width = max(0, content_right - content_left)

        name_font = self._ui_font(16)
        name_fm = QFontMetrics(name_font)

        draft_preview = (getattr(session, "draft_preview", None) or "").strip()
        preview_text = self._format_preview_text(session)
        preview_font = self._preview_font(draft_preview or preview_text)
        preview_fm = QFontMetrics(preview_font)

        time_font = self._ui_font(10)
        time_fm = QFontMetrics(time_font)

        time_text = self._format_time(session.last_message_time or session.created_at)
        time_width = max(0, min(max(0, content_width // 2), time_fm.horizontalAdvance(time_text) + 4))
        time_text = time_fm.elidedText(time_text, Qt.TextElideMode.ElideRight, time_width)
        muted = bool(getattr(session, "extra", {}).get("is_muted", False))
        mute_icon_size = 10
        mute_slot_width = mute_icon_size + 8 if muted else 0

        unread_text = self._format_unread(session.unread_count)
        unread_width = 0
        if unread_text:
            unread_width = max(16, preview_fm.horizontalAdvance(unread_text) + 12)

        name_available = max(0, content_width - time_width - unread_width - 18)
        name_text = name_fm.elidedText(
            session.display_name() or tr("session.unnamed", "Untitled Session"),
            Qt.TextElideMode.ElideRight,
            name_available,
        )
        preview_available = max(0, content_width - mute_slot_width)

        name_y = card_rect.y() + 14
        preview_y = name_y + 24

        secondary_text = QColor(216, 216, 216) if isDarkTheme() else QColor(95, 95, 95)
        primary_text = QColor(255, 255, 255) if isDarkTheme() else QColor(0, 0, 0)
        preview_color = primary_text if session.unread_count > 0 else secondary_text
        time_color = QColor(196, 196, 196) if isDarkTheme() else QColor(122, 122, 122)

        painter.setFont(name_font)
        painter.setPen(primary_text)
        painter.drawText(
                QRect(content_left, name_y, name_available, 22),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                name_text,
            )

        badge_anchor_x = content_left + name_fm.horizontalAdvance(name_text) + 8
        if unread_text and unread_width > 0 and badge_anchor_x + unread_width <= content_right:
            badge_rect = QRect(badge_anchor_x, name_y + 2, unread_width, 16)
            self._draw_unread_badge(painter, badge_rect, unread_text)

        painter.setFont(preview_font)
        if draft_preview:
            prefix_text = tr("session.draft_prefix", "[Draft]")
            prefix_color = QColor("#FF6B6B") if isDarkTheme() else QColor("#D93025")
            prefix_font = self._ui_font(13)
            prefix_fm = QFontMetrics(prefix_font)
            prefix_width = prefix_fm.horizontalAdvance(prefix_text) + 6
            body_available = max(0, preview_available - prefix_width)

            painter.setFont(prefix_font)
            painter.setPen(prefix_color)
            painter.drawText(
                QRect(content_left, preview_y, prefix_fm.horizontalAdvance(prefix_text) + 10, 24),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                prefix_text,
            )

            painter.setFont(preview_font)
            painter.setPen(preview_color)
            self._draw_preview_runs(
                painter,
                QRect(content_left + prefix_width, preview_y - 1, body_available, 28),
                draft_preview,
                preview_color,
            )
        else:
            painter.setPen(preview_color)
            self._draw_preview_runs(
                painter,
                QRect(content_left, preview_y - 1, preview_available, 28),
                preview_text,
                preview_color,
            )

        painter.setFont(time_font)
        painter.setPen(time_color)
        painter.drawText(
            QRect(content_right - time_width, name_y, time_width, 18),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            time_text,
        )

        if muted:
            icon_rect = QRect(
                content_right - mute_icon_size,
                preview_y + 6,
                mute_icon_size,
                mute_icon_size,
            )
            self._mute_icon.render(painter, icon_rect, fill=time_color)

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

        avatar_seed_value = (
            session.display_avatar_seed()
            or profile_avatar_seed(
                user_id=getattr(session, "extra", {}).get("counterpart_id", ""),
                username=getattr(session, "extra", {}).get("counterpart_username", ""),
                display_name=getattr(session, "name", ""),
                fallback=getattr(session, "session_id", ""),
            )
        )
        _avatar_source, avatar_path = self._avatar_store.resolve_display_path(
            session.display_avatar(),
            gender=session.display_gender(),
            seed=avatar_seed_value,
        )

        if avatar_path:
            from PySide6.QtGui import QPixmap

            pixmap = QPixmap(avatar_path)
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

        if not avatar_path:
            initial = (session.display_name() or "?")[:1].upper()
            font = QFont()
            font.setPixelSize(18)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, initial)

        painter.restore()

    def _on_avatar_ready(self, _source: str) -> None:
        """Refresh the bound session view when a remote avatar finishes downloading."""
        parent = self.parent()
        if parent is None:
            return
        if hasattr(parent, "viewport"):
            parent.viewport().update()
            return
        if hasattr(parent, "update"):
            parent.update()

    def _draw_unread_badge(self, painter: QPainter, rect: QRect, text: str) -> None:
        """Draw unread badge using a Fluent InfoBadge-like pill."""
        path = QPainterPath()
        radius = rect.height() / 2
        path.addRoundedRect(rect, radius, radius)
        accent = QColor("#FF5A5F") if isDarkTheme() else QColor("#E53935")
        painter.fillPath(path, accent)

        font = QFont()
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    @staticmethod
    def _ui_font(pixel_size: int, *, bold: bool = False) -> QFont:
        """Return a UI font with emoji-capable fallbacks."""
        font = QFont()
        font.setPixelSize(pixel_size)
        font.setBold(bold)
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

    def _preview_font(self, text: str) -> QFont:
        """Return the preview font, enlarging emoji-only previews without changing normal text."""
        if is_emoji_text(text):
            return self._ui_font(22)
        return self._ui_font(13)

    def _preview_emoji_font(self) -> QFont:
        """Return the larger font used for emoji glyphs inside preview text."""
        font = QFont()
        font.setPixelSize(18)
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
        return font

    def _draw_preview_runs(self, painter: QPainter, rect: QRect, text: str, color: QColor) -> None:
        """Draw preview text with larger emoji glyphs while keeping ordinary text small."""
        text = text or ""
        if not text:
            return

        base_font = self._ui_font(13)
        base_metrics = QFontMetrics(base_font)
        emoji_side = PREVIEW_ONLY_EMOJI_PIXEL_SIZE if is_emoji_text(text) else PREVIEW_EMOJI_PIXEL_SIZE
        display_runs = self._preview_runs_for_width(text, max(0, rect.width()), base_metrics, emoji_side)

        baseline = centered_text_baseline(rect, base_metrics, vertical_nudge=-1)
        x = rect.x()

        painter.save()
        painter.setPen(color)
        for run in display_runs:
            if run.kind == "emoji":
                pixmap = load_emoji_pixmap(run.text, emoji_side, emoji_side)
                if not pixmap.isNull():
                    top = centered_emoji_top(rect.y(), rect.height(), emoji_side)
                    painter.drawPixmap(x, top, pixmap)
                else:
                    painter.setFont(self._preview_emoji_font())
                    painter.drawText(x, baseline, run.text)
                x += run.width
                continue

            painter.setFont(base_font)
            painter.drawText(x, baseline, run.text)
            x += run.width
        painter.restore()

    def _preview_runs_for_width(
        self,
        text: str,
        available_width: int,
        base_metrics: QFontMetrics,
        emoji_side: int,
    ) -> list[_PreviewRun]:
        """Build a single-line preview run list with emoji-aware elision."""
        ellipsis = "..."
        ellipsis_width = base_metrics.horizontalAdvance(ellipsis)
        remaining = max(0, available_width)
        runs: list[_PreviewRun] = []
        text_buffer: list[str] = []
        text_buffer_width = 0

        def flush_text_buffer() -> None:
            nonlocal text_buffer, text_buffer_width
            if not text_buffer:
                return
            runs.append(_PreviewRun("text", "".join(text_buffer), text_buffer_width))
            text_buffer = []
            text_buffer_width = 0

        for run_text, is_emoji_run in iter_text_and_emoji_clusters(text):
            run_width = emoji_side if is_emoji_run else base_metrics.horizontalAdvance(run_text)
            reserve = ellipsis_width if run_width > remaining and runs else 0
            if run_width + reserve <= remaining:
                if is_emoji_run:
                    flush_text_buffer()
                    runs.append(_PreviewRun("emoji", run_text, run_width))
                else:
                    text_buffer.append(run_text)
                    text_buffer_width += run_width
                remaining -= run_width
                continue

            if is_emoji_run:
                flush_text_buffer()
                if remaining >= ellipsis_width:
                    runs.append(_PreviewRun("text", ellipsis, ellipsis_width))
                break

            clipped = ""
            clipped_width = 0
            for char in run_text:
                char_width = base_metrics.horizontalAdvance(char)
                if clipped_width + char_width + ellipsis_width > remaining:
                    break
                clipped += char
                clipped_width += char_width

            if clipped:
                text_buffer.append(clipped)
                text_buffer_width += clipped_width
                flush_text_buffer()
            else:
                flush_text_buffer()

            if remaining >= ellipsis_width:
                runs.append(_PreviewRun("text", ellipsis, ellipsis_width))
            break
        else:
            flush_text_buffer()

        if not runs:
            elided = base_metrics.elidedText(text, Qt.TextElideMode.ElideRight, available_width)
            return [_PreviewRun("text", elided, base_metrics.horizontalAdvance(elided))] if elided else []

        return runs

    def _format_unread(self, count: int) -> str:
        """Format unread count display."""
        if count <= 0:
            return ""
        if count > 99:
            return "99+"
        return str(count)

    def _format_preview_text(self, session) -> str:
        """Format preview text for media and file messages."""
        preview = session.last_message or tr("session.start_new", "Start a new conversation")
        message_type = session.extra.get("last_message_type") if getattr(session, "extra", None) else None
        preview_text = format_message_preview(preview, message_type)
        sender_name = session.preview_sender_name() if hasattr(session, "preview_sender_name") else ""
        if sender_name and session.last_message:
            return f"{sender_name}：{preview_text}"
        return preview_text

    def _format_time(self, timestamp) -> str:
        """Format timestamp using the previous UI's Chinese-friendly style."""
        return format_session_timestamp(timestamp)

    def _normalize_datetime(self, value) -> datetime | None:
        """Normalize datetime values from model or storage."""
        return coerce_local_datetime(value)




