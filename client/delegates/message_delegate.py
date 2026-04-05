"""Message delegate that migrates the old bubble-style chat UI."""

from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass
import time

from PySide6.QtCore import QModelIndex, QPoint, QRect, QRectF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPixmap,
    QImageReader,
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem
from qfluentwidgets import Theme, isDarkTheme, themeColor

from client.core.app_icons import AppIcon
from client.core.avatar_rendering import get_avatar_image_store
from client.core.avatar_utils import profile_avatar_seed
from client.core.config_backend import get_config
from client.core.i18n import format_chat_timestamp, format_chat_timestamp_expanded, tr
from client.ui.controllers.auth_controller import peek_auth_controller
from client.core.video_thumbnail_cache import (
    get_thumbnail as get_video_thumbnail,
    get_video_thumbnail_cache,
)
from client.models.message import ChatMessage, MessageStatus, MessageType, normalize_message_mentions
from client.models.message_model import MessageModel
from client.ui.common.attachment_card import attachment_card_size, draw_attachment_card
from client.ui.common.emoji_utils import (
    BUBBLE_EMOJI_PIXEL_SIZE,
    MIXED_EMOJI_TEXT_GAP,
    centered_emoji_top,
    is_emoji_char,
    is_emoji_text,
    iter_text_and_emoji_clusters,
    load_emoji_pixmap,
)


@dataclass
class _TextRunLayout:
    """A laid-out text or emoji run inside a message bubble."""

    kind: str
    text: str
    start: int
    end: int
    width: int
    height: int
    ascent: int
    descent: int
    char_advances: tuple[int, ...] = ()
    char_offsets: tuple[int, ...] = ()
    x: int = 0
    y: int = 0


@dataclass
class _TextLineLayout:
    """A single wrapped line inside a custom text layout."""

    runs: list[_TextRunLayout]
    width: int
    height: int
    baseline: int
    x: int = 0
    y: int = 0


@dataclass
class _RunTextLayout:
    """Layout result for a text bubble rendered without QTextDocument."""

    lines: list[_TextLineLayout]
    width: int
    height: int
    pure_emoji: bool


@dataclass
class _MessageRowLayout:
    """Resolved geometry for one rendered chat row."""

    avatar_rect: QRect
    bubble_rect: QRect
    content_rect: QRect
    sender_label_rect: QRect | None
    sender_label_alignment: Qt.AlignmentFlag


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
    RECALL_NOTICE_HEIGHT = TIME_BLOCK_HEIGHT
    RECALL_ACTION_GAP = 8
    TEXT_MEASURE_CACHE_LIMIT = 512
    TEXT_LAYOUT_CACHE_LIMIT = 256
    MEDIA_SIZE_CACHE_LIMIT = 512
    IMAGE_RECT_CACHE_LIMIT = 512
    EMOJI_TEXT_GAP = MIXED_EMOJI_TEXT_GAP
    GROUP_SENDER_LABEL_FONT_PIXEL_SIZE = 11
    GROUP_SENDER_LABEL_GAP = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._avatar_store = get_avatar_image_store()
        self._avatar_store.avatar_ready.connect(self._on_avatar_ready)
        self._image_cache: dict[str, QPixmap] = {}
        self._loading_sources: set[str] = set()
        self._failed_image_sources: dict[str, float] = {}
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
        self._context_menu_message_id: str | None = None
        self._hovered_time_separator_id: str | None = None
        self._hovered_recall_notice_action_id: str | None = None
        self._text_measure_cache: OrderedDict[str, QSize] = OrderedDict()
        self._text_layout_cache: OrderedDict[tuple[int, str], _RunTextLayout] = OrderedDict()
        self._media_size_cache: OrderedDict[tuple, QSize] = OrderedDict()
        self._image_rect_cache: OrderedDict[tuple, QRect] = OrderedDict()
        self._active_session_id = ""
        self._active_session_type = ""
        self._show_group_member_nickname = True
        self._group_members_by_id: dict[str, dict[str, object]] = {}

    def set_session(self, session) -> bool:
        """Update the active session context used for group sender-label rendering."""
        if session is None:
            next_session_id = ""
            next_session_type = ""
            next_show_group_member_nickname = True
            next_members_by_id: dict[str, dict[str, object]] = {}
        else:
            extra = dict(getattr(session, "extra", {}) or {})
            next_session_id = str(getattr(session, "session_id", "") or "")
            next_session_type = str(getattr(session, "session_type", "") or "")
            next_show_group_member_nickname = bool(extra.get("show_member_nickname", True))
            next_members_by_id = {
                str(member.get("id", "") or member.get("user_id", "") or "").strip(): dict(member or {})
                for member in list(extra.get("members") or [])
                if isinstance(member, dict) and str(member.get("id", "") or member.get("user_id", "") or "").strip()
            }

        changed = (
            self._active_session_id != next_session_id
            or self._active_session_type != next_session_type
            or self._show_group_member_nickname != next_show_group_member_nickname
            or self._group_members_by_id != next_members_by_id
        )
        self._active_session_id = next_session_id
        self._active_session_type = next_session_type
        self._show_group_member_nickname = next_show_group_member_nickname
        self._group_members_by_id = next_members_by_id
        return changed

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        """Return message item size based on type and timestamp visibility."""
        message = index.data(Qt.ItemDataRole.UserRole)
        if not message:
            return QSize(option.rect.width(), 0)

        display_kind = self._display_kind(index, message)
        if display_kind == MessageModel.DISPLAY_TIME_SEPARATOR:
            return QSize(option.rect.width(), self.TIME_BLOCK_HEIGHT + self.TIME_SPACING * 2)
        if display_kind == MessageModel.DISPLAY_RECALL_NOTICE:
            return QSize(option.rect.width(), self.TIME_BLOCK_HEIGHT + self.TIME_SPACING * 2)

        content_size = self._bubble_size(message, option.rect.width())
        sender_label_block_height = self._group_sender_label_block_height(message)
        total_height = max(content_size.height(), self.AVATAR_SIZE) + sender_label_block_height + 18
        return QSize(option.rect.width(), total_height)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        """Paint a single message bubble row."""
        message: ChatMessage = index.data(Qt.ItemDataRole.UserRole)
        if not message:
            return super().paint(painter, option, index)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(option.rect)

        display_kind = self._display_kind(index, message)

        if display_kind == MessageModel.DISPLAY_TIME_SEPARATOR:
            time_rect = QRect(
                option.rect.x(),
                option.rect.y() + self.TIME_SPACING,
                option.rect.width(),
                self.TIME_BLOCK_HEIGHT,
            )
            source_message_id = str(index.data(MessageModel.SourceMessageIdRole) or "")
            is_expanded = bool(index.data(MessageModel.TimeExpandedRole))
            is_hovered = bool(source_message_id) and source_message_id == self._hovered_time_separator_id
            self._draw_time_block(
                painter,
                time_rect,
                self._format_time(message.timestamp, expanded=is_expanded),
                hovered=is_hovered,
                expanded=is_expanded,
            )
            self._draw_row_divider(painter, option.rect)
            painter.restore()
            return

        if display_kind == MessageModel.DISPLAY_RECALL_NOTICE:
            notice_rect = QRect(
                option.rect.x(),
                option.rect.y() + self.TIME_SPACING,
                option.rect.width(),
                self.RECALL_NOTICE_HEIGHT,
            )
            self._draw_recall_notice(painter, notice_rect, message)
            self._draw_row_divider(painter, option.rect)
            painter.restore()
            return

        row_layout = self._layout_rects(option.rect, message)

        self._draw_group_sender_label(painter, row_layout, message)
        self._draw_avatar(painter, row_layout.avatar_rect, message)
        self._draw_bubble(painter, row_layout.bubble_rect, message, row_layout.avatar_rect)

        if message.is_self:
            badge_rect = self._status_badge_rect(row_layout.bubble_rect, option.rect, message)
            self._draw_status_badge(painter, badge_rect, message)

        self._draw_row_divider(painter, option.rect)
        painter.restore()

    def is_attachment_hit(self, view, index: QModelIndex, position) -> bool:
        """Return whether a click position is inside the rendered attachment content."""
        message: ChatMessage = index.data(Qt.ItemDataRole.UserRole)
        if (
            not message
            or self._display_kind(index, message) != MessageModel.DISPLAY_MESSAGE
            or message.message_type not in {MessageType.IMAGE, MessageType.FILE, MessageType.VIDEO}
        ):
            return False

        row_rect = view.visualRect(index)
        if not row_rect.isValid():
            return False

        row_layout = self._layout_rects(row_rect, message)
        hit_rect = self._attachment_hit_rect(row_layout.content_rect, message)
        return hit_rect.contains(position)

    def is_bubble_hit(self, view, index: QModelIndex, position: QPoint) -> bool:
        """Return whether a viewport position lands on the rendered message bubble/card."""
        message: ChatMessage = index.data(Qt.ItemDataRole.UserRole)
        if (
            not message
            or self._display_kind(index, message) != MessageModel.DISPLAY_MESSAGE
        ):
            return False

        row_rect = view.visualRect(index)
        if not row_rect.isValid():
            return False

        row_layout = self._layout_rects(row_rect, message)
        return row_layout.bubble_rect.contains(position)

    def is_text_hit(self, view, index: QModelIndex, position: QPoint) -> bool:
        """Return whether a viewport position lands on text content."""
        message: ChatMessage = index.data(Qt.ItemDataRole.UserRole)
        if (
            not message
            or self._display_kind(index, message) != MessageModel.DISPLAY_MESSAGE
            or message.message_type != MessageType.TEXT
        ):
            return False

        row_rect = view.visualRect(index)
        if not row_rect.isValid():
            return False

        row_layout = self._layout_rects(row_rect, message)
        text_rect, layout = self._text_layout(row_layout.content_rect, message.content or "")
        return self._text_position_for_point(layout, text_rect, position, clamp=False) >= 0

    def begin_text_selection(self, view, index: QModelIndex, position: QPoint) -> bool:
        """Begin selecting text from a message bubble."""
        message: ChatMessage = index.data(Qt.ItemDataRole.UserRole)
        if (
            not message
            or self._display_kind(index, message) != MessageModel.DISPLAY_MESSAGE
            or message.message_type != MessageType.TEXT
        ):
            return False

        row_rect = view.visualRect(index)
        if not row_rect.isValid():
            return False

        row_layout = self._layout_rects(row_rect, message)
        text_rect, layout = self._text_layout(row_layout.content_rect, message.content or "")
        cursor_pos = self._text_position_for_point(layout, text_rect, position, clamp=False)
        if cursor_pos < 0:
            return False
        cursor_pos = self._normalize_selection_index(message.content or "", cursor_pos, prefer_end=None)

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
        if (
            not message
            or self._display_kind(index, message) != MessageModel.DISPLAY_MESSAGE
            or message.message_id != self._selection_message_id
            or message.message_type != MessageType.TEXT
        ):
            return False

        row_rect = view.visualRect(index)
        if not row_rect.isValid():
            return False

        row_layout = self._layout_rects(row_rect, message)
        text_rect, layout = self._text_layout(row_layout.content_rect, message.content or "")
        cursor_pos = self._text_position_for_point(layout, text_rect, position, clamp=True)
        if cursor_pos < 0:
            return False
        cursor_pos = self._normalize_selection_index(message.content or "", cursor_pos, prefer_end=None)

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

        start, end = self._selection_index_bounds(content or "", self._selection_anchor, self._selection_position)
        return (content or "")[start:end]

    @staticmethod
    def _emoji_cluster_python_ranges(content: str) -> list[tuple[int, int]]:
        """Return Python string index ranges occupied by emoji clusters."""
        ranges: list[tuple[int, int]] = []
        position = 0
        for chunk, is_emoji_chunk in iter_text_and_emoji_clusters(content or ""):
            length = len(chunk)
            if is_emoji_chunk and length > 0:
                ranges.append((position, position + length))
            position += length
        return ranges

    @classmethod
    def _normalize_selection_index(cls, content: str, position: int, *, prefer_end: bool | None) -> int:
        """Snap a Python string index away from the middle of an emoji cluster."""
        if not content:
            return 0

        value = max(0, min(position, len(content)))
        for start, end in cls._emoji_cluster_python_ranges(content):
            if start < value < end:
                if prefer_end is None:
                    midpoint = start + (end - start) / 2
                    return end if value >= midpoint else start
                return end if prefer_end else start
        return value

    @classmethod
    def _selection_index_bounds(cls, content: str, anchor: int, position: int) -> tuple[int, int]:
        """Return Python selection bounds that never split an emoji cluster."""
        start = min(anchor, position)
        end = max(anchor, position)
        return (
            cls._normalize_selection_index(content, start, prefer_end=False),
            cls._normalize_selection_index(content, end, prefer_end=True),
        )

    def _bubble_size(self, message: ChatMessage, row_width: int | None = None) -> QSize:
        """Compute bubble or media size for the current message type."""
        max_bubble_width = self._max_bubble_width_for_row(row_width or 0)
        if message.message_type == MessageType.IMAGE:
            pixmap = self._load_pixmap(message)
            cache_key = (
                message.message_type.value,
                message.message_id,
                message.content or "",
                message.extra.get("local_path", ""),
                pixmap.width(),
                pixmap.height(),
                max_bubble_width,
            )
            cached_size = self._cache_get(self._media_size_cache, cache_key)
            if cached_size is not None:
                return cached_size

            if not pixmap.isNull():
                scaled = self._contained_size(
                    pixmap.size(),
                    QSize(min(self.MAX_IMAGE_WIDTH, max_bubble_width), self.MAX_IMAGE_HEIGHT),
                )
                size = QSize(max(72, scaled.width()), max(72, scaled.height()))
            else:
                size = QSize(max(72, min(max_bubble_width, 160)), 116)

            self._cache_put(self._media_size_cache, cache_key, size, self.MEDIA_SIZE_CACHE_LIMIT)
            return size

        if message.message_type == MessageType.FILE:
            cache_key = (
                message.message_type.value,
                message.message_id,
                message.extra.get("name", ""),
                message.extra.get("size"),
                max_bubble_width,
            )
            cached_size = self._cache_get(self._media_size_cache, cache_key)
            if cached_size is not None:
                return cached_size
            size = QSize(max(88, min(self.FILE_WIDTH, max_bubble_width)), self.FILE_HEIGHT)
            self._cache_put(self._media_size_cache, cache_key, size, self.MEDIA_SIZE_CACHE_LIMIT)
            return size

        if message.message_type == MessageType.VIDEO:
            cache_key = (
                message.message_type.value,
                message.message_id,
                message.extra.get("local_path", ""),
                message.extra.get("thumbnail_path", ""),
                max_bubble_width,
            )
            cached_size = self._cache_get(self._media_size_cache, cache_key)
            if cached_size is not None:
                return cached_size
            video_width = max(88, min(self.VIDEO_WIDTH, max_bubble_width))
            video_height = max(60, round(video_width * self.VIDEO_HEIGHT / self.VIDEO_WIDTH))
            size = QSize(video_width, video_height)
            self._cache_put(self._media_size_cache, cache_key, size, self.MEDIA_SIZE_CACHE_LIMIT)
            return size

        text_content_width = max(
            24,
            min(
                self.MAX_TEXT_WIDTH,
                max_bubble_width - self.BUBBLE_PADDING_H * 2 - self.TAIL_SPACE,
            ),
        )
        text_size = self._measure_text_content(message.content or "", text_content_width)
        bubble_width = min(
            text_content_width + self.BUBBLE_PADDING_H * 2 + self.TAIL_SPACE,
            max(36, text_size.width() + self.BUBBLE_PADDING_H * 2 + self.TAIL_SPACE),
        )
        bubble_height = max(40, text_size.height() + self.BUBBLE_PADDING_V * 2)
        return QSize(bubble_width, bubble_height)

    def _time_block_font(self) -> QFont:
        """Return the font used by standalone time separators."""
        font = QFont()
        font.setPixelSize(11)
        return font

    def _time_block_pill_rect(self, rect: QRect, time_text: str) -> tuple[QRect, str]:
        """Return the clickable pill rect and the final elided text for a time separator."""
        font = self._time_block_font()
        metrics = QFontMetrics(font)
        available_width = max(44, rect.width() - 16)
        display_text = metrics.elidedText(time_text, Qt.TextElideMode.ElideRight, max(20, available_width - 18))
        text_width = metrics.horizontalAdvance(display_text)
        pill_width = min(available_width, max(56, text_width + 18))
        pill_height = 22
        pill_x = rect.x() + max(0, (rect.width() - pill_width) // 2)
        pill_y = rect.y() + max(0, (rect.height() - pill_height) // 2)
        return QRect(pill_x, pill_y, pill_width, pill_height), display_text

    def _draw_time_block(
        self,
        painter: QPainter,
        rect: QRect,
        time_text: str,
        *,
        hovered: bool = False,
        expanded: bool = False,
    ) -> None:
        """Draw a centered standalone timestamp with hover and expanded states."""
        if not time_text:
            return

        font = self._time_block_font()
        pill_rect, display_text = self._time_block_pill_rect(rect, time_text)
        painter.setFont(font)

        if hovered:
            background = (
                QColor(255, 255, 255, 32)
                if isDarkTheme()
                else QColor(0, 0, 0, 12)
            )
            border = (
                QColor(255, 255, 255, 18)
                if isDarkTheme()
                else QColor(0, 0, 0, 8)
            )
            path = QPainterPath()
            path.addRoundedRect(QRectF(pill_rect), pill_rect.height() / 2, pill_rect.height() / 2)
            painter.fillPath(path, background)
            painter.setPen(border)
            painter.drawPath(path)

        text_color = (
            QColor(224, 224, 224, 236) if hovered else QColor(210, 210, 210, 230)
        ) if isDarkTheme() else (QColor("#5F5F5F") if hovered else QColor("#8A8A8A"))
        painter.setPen(text_color)
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, display_text)

    def is_time_separator_hit(self, view, index: QModelIndex, position: QPoint) -> bool:
        """Return whether a viewport position lands on a standalone time separator."""
        return bool(self._time_separator_source_at(view, index, position))

    def update_time_separator_hover(self, view, index: QModelIndex, position: QPoint) -> bool:
        """Refresh the hovered time separator row and request a repaint if needed."""
        hovered_id = self._time_separator_source_at(view, index, position)
        if hovered_id == self._hovered_time_separator_id:
            return bool(hovered_id)
        self._hovered_time_separator_id = hovered_id
        view.viewport().update()
        return bool(hovered_id)

    def clear_time_separator_hover(self, view=None) -> None:
        """Clear any hovered time separator row."""
        if self._hovered_time_separator_id is None:
            return
        self._hovered_time_separator_id = None
        if view is not None:
            view.viewport().update()

    def update_recall_notice_action_hover(self, view, index: QModelIndex, position: QPoint) -> bool:
        """Refresh the hovered direct-edit action on recall notices."""
        hovered_id = self.recall_notice_action_source_at(view, index, position)
        if hovered_id == self._hovered_recall_notice_action_id:
            return bool(hovered_id)
        self._hovered_recall_notice_action_id = hovered_id
        if view is not None:
            view.viewport().update()
        return bool(hovered_id)

    def clear_recall_notice_action_hover(self, view=None) -> None:
        """Clear any hovered direct-edit action on recall notices."""
        if self._hovered_recall_notice_action_id is None:
            return
        self._hovered_recall_notice_action_id = None
        if view is not None:
            view.viewport().update()

    def set_context_menu_message(self, view, message_id: str | None) -> None:
        """Persist one temporary bubble highlight while a context menu is open."""
        normalized = str(message_id or "").strip() or None
        if normalized == self._context_menu_message_id:
            return
        self._context_menu_message_id = normalized
        if view is not None:
            view.viewport().repaint()

    def toggle_time_separator_expanded_at(self, view, index: QModelIndex, position: QPoint) -> bool:
        """Toggle the display format of a clicked time separator row."""
        source_message_id = self._time_separator_source_at(view, index, position)
        if not source_message_id:
            return False
        model = index.model()
        if model is None or not hasattr(model, "toggle_time_separator_expanded"):
            return False
        return bool(model.toggle_time_separator_expanded(source_message_id))

    def _time_separator_source_at(self, view, index: QModelIndex, position: QPoint) -> str | None:
        """Return the source message id for the clicked/hovered time separator."""
        if not index.isValid():
            return None

        message: ChatMessage = index.data(Qt.ItemDataRole.UserRole)
        if not message or self._display_kind(index, message) != MessageModel.DISPLAY_TIME_SEPARATOR:
            return None

        row_rect = view.visualRect(index)
        if not row_rect.isValid():
            return None

        source_message_id = str(index.data(MessageModel.SourceMessageIdRole) or "")
        is_expanded = bool(index.data(MessageModel.TimeExpandedRole))
        time_rect = QRect(row_rect.x(), row_rect.y() + self.TIME_SPACING, row_rect.width(), self.TIME_BLOCK_HEIGHT)
        pill_rect, _display_text = self._time_block_pill_rect(time_rect, self._format_time(message.timestamp, expanded=is_expanded))
        if not pill_rect.contains(position):
            return None
        return source_message_id or None

    def recall_notice_action_source_at(self, view, index: QModelIndex, position: QPoint) -> str | None:
        """Return the recalled source message id when the inline direct-edit action is clicked."""
        if not index.isValid():
            return None

        message: ChatMessage = index.data(Qt.ItemDataRole.UserRole)
        if not message or self._display_kind(index, message) != MessageModel.DISPLAY_RECALL_NOTICE:
            return None

        row_rect = view.visualRect(index)
        if not row_rect.isValid():
            return None

        notice_rect = QRect(
            row_rect.x(),
            row_rect.y() + self.TIME_SPACING,
            row_rect.width(),
            self.RECALL_NOTICE_HEIGHT,
        )
        _notice_text, action_text, _notice_draw_rect, action_rect = self._recall_notice_layout(notice_rect, message)
        if not action_text or action_rect is None or not action_rect.contains(position):
            return None
        source_message_id = str(index.data(MessageModel.SourceMessageIdRole) or "")
        return source_message_id or None

    def is_recall_notice_action_hit(self, view, index: QModelIndex, position: QPoint) -> bool:
        """Return whether the viewport position is over the inline direct-edit action."""
        return bool(self.recall_notice_action_source_at(view, index, position))

    def _recall_notice_layout(self, rect: QRect, message: ChatMessage) -> tuple[str, str, QRect, QRect | None]:
        """Return notice/action text plus their draw rects for one recall notice row."""
        notice_text = self._recall_notice_text(message)
        action_text = ""
        if message.is_self and str((message.extra or {}).get("recalled_content", "") or "").strip():
            action_text = tr("message.recalled.edit_direct", "Direct Edit")

        notice_font = QFont()
        notice_font.setPixelSize(12)
        notice_metrics = QFontMetrics(notice_font)
        notice_width = notice_metrics.horizontalAdvance(notice_text)

        action_rect: QRect | None = None
        total_width = notice_width
        action_width = 0
        if action_text:
            action_font = QFont(notice_font)
            action_font.setBold(True)
            action_width = QFontMetrics(action_font).horizontalAdvance(action_text)
            total_width += self.RECALL_ACTION_GAP + action_width

        start_x = rect.x() + max(0, (rect.width() - total_width) // 2)
        notice_rect = QRect(start_x, rect.y(), notice_width, rect.height())
        if action_text:
            action_rect = QRect(notice_rect.right() + 1 + self.RECALL_ACTION_GAP, rect.y(), action_width, rect.height())
        return notice_text, action_text, notice_rect, action_rect

    def _draw_recall_notice(self, painter: QPainter, rect: QRect, message: ChatMessage) -> None:
        """Draw a centered system-style recall notice."""
        notice_text, action_text, notice_rect, action_rect = self._recall_notice_layout(rect, message)
        notice_font = QFont()
        notice_font.setPixelSize(12)
        painter.setFont(notice_font)
        painter.setPen(QColor(196, 196, 196, 220) if isDarkTheme() else QColor("#8A8A8A"))
        painter.drawText(notice_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, notice_text)
        if action_text and action_rect is not None:
            action_font = QFont(notice_font)
            painter.setFont(action_font)
            hovered = self._hovered_recall_notice_action_id == str((message.extra or {}).get(MessageModel.SOURCE_MESSAGE_ID_KEY, "") or "")
            if hovered:
                hover_rect = action_rect.adjusted(-6, 1, 6, -1)
                background = QColor(255, 255, 255, 32) if isDarkTheme() else QColor(0, 0, 0, 12)
                border = QColor(255, 255, 255, 18) if isDarkTheme() else QColor(0, 0, 0, 8)
                path = QPainterPath()
                path.addRoundedRect(QRectF(hover_rect), hover_rect.height() / 2, hover_rect.height() / 2)
                painter.fillPath(path, background)
                painter.setPen(border)
                painter.drawPath(path)
            action_color = (
                QColor("#AECBFA") if hovered and isDarkTheme() else
                QColor("#8AB4F8") if isDarkTheme() else
                QColor("#B3261E") if hovered else QColor("#D93025")
            )
            painter.setPen(action_color)
            painter.drawText(action_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, action_text)

    def _display_kind(self, index: QModelIndex, message: ChatMessage) -> str:
        """Return the visible row kind for the current index."""
        explicit_kind = index.data(MessageModel.DisplayKindRole)
        if explicit_kind:
            return str(explicit_kind)
        return str((message.extra or {}).get(MessageModel.DISPLAY_KIND_KEY, MessageModel.DISPLAY_MESSAGE))

    def _draw_row_divider(self, painter: QPainter, rect: QRect) -> None:
        """Draw a subtle divider line to help inspect row positioning."""
        return

    def _draw_avatar(self, painter: QPainter, rect: QRect, message: ChatMessage) -> None:
        """Draw avatar with initial text when no image is available."""
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 8, 8)

        extra = message.extra or {}
        sender_avatar = str(extra.get("sender_avatar", "") or "")
        sender_gender = str(extra.get("sender_gender", "") or "")
        sender_name = (
            str(extra.get("sender_nickname", "") or "")
            or str(extra.get("sender_name", "") or "")
            or str(extra.get("sender_username", "") or "")
        )

        if message.is_self:
            auth_controller = peek_auth_controller()
            current_user = dict(auth_controller.current_user or {}) if auth_controller is not None else {}
            sender_avatar = str(current_user.get("avatar", "") or "")
            sender_gender = str(current_user.get("gender", "") or "")
            sender_name = str(current_user.get("nickname", "") or "") or str(current_user.get("username", "") or "")
            sender_username = str(current_user.get("username", "") or "")
        else:
            sender_username = str(extra.get("sender_username", "") or "")
        avatar_seed_value = profile_avatar_seed(
            user_id=message.sender_id,
            username=sender_username,
            display_name=sender_name,
        )
        _avatar_source, avatar_path = self._avatar_store.resolve_display_path(
            sender_avatar,
            gender=sender_gender,
            seed=avatar_seed_value,
        )

        if avatar_path:
            painter.save()
            painter.setClipPath(path)
            pixmap = QPixmap(avatar_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    rect.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                painter.drawPixmap(rect, scaled)
                painter.restore()
                return
            painter.restore()

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
        bubble_color = self._bubble_fill_color(
            message,
            context_menu_active=(
                message.message_type == MessageType.TEXT and message.message_id == self._context_menu_message_id
            ),
        )

        painter.fillPath(path, bubble_color)
        painter.setPen(Qt.PenStyle.NoPen)

        content_rect = self._content_rect(rect, message)

        if message.message_type == MessageType.TEXT:
            self._draw_text_content(painter, content_rect, message, bubble_color)
        elif message.message_type == MessageType.IMAGE:
            self._draw_image_content(painter, content_rect, message)
        elif message.message_type == MessageType.FILE:
            self._draw_file_content(painter, content_rect, message)
        elif message.message_type == MessageType.VIDEO:
            self._draw_video_content(painter, content_rect, message)
        else:
            self._draw_text_content(painter, content_rect, message, bubble_color)

    def _draw_text_content(self, painter: QPainter, rect: QRect, message: ChatMessage, background_fill: QColor) -> None:
        """Draw wrapped text content."""
        del background_fill
        content = message.content or ""
        text_rect, layout = self._text_layout(rect, content)
        mention_ranges = self._message_mention_ranges(message)
        selection_range = (
            self._selection_index_bounds(content, self._selection_anchor, self._selection_position)
            if self.has_selected_text(message.message_id)
            else None
        )

        text_font = self._text_font()
        text_metrics = QFontMetrics(text_font)
        text_color = self._text_color(message)
        mention_text_color = QColor("#0F6CBD") if not isDarkTheme() else QColor("#8AB4F8")
        selected_text_color = QColor(255, 255, 255) if isDarkTheme() else QColor("#101010")
        highlight_color = QColor(86, 157, 229, 120) if isDarkTheme() else QColor(140, 196, 255, 140)
        emoji_target = BUBBLE_EMOJI_PIXEL_SIZE

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(text_font)

        for line in layout.lines:
            line_top = text_rect.y() + line.y
            baseline_y = line_top + line.baseline

            for run in line.runs:
                run_left = text_rect.x() + line.x + run.x
                run_rect = QRect(run_left, line_top + run.y, run.width, run.height)
                is_selected = bool(
                    selection_range and self._ranges_overlap(selection_range[0], selection_range[1], run.start, run.end)
                )

                if run.kind == "emoji":
                    if is_selected:
                        highlight_path = QPainterPath()
                        highlight_path.addRoundedRect(QRectF(run_rect.adjusted(0, 0, 0, -1)), 4, 4)
                        painter.fillPath(highlight_path, highlight_color)

                    pixmap = load_emoji_pixmap(run.text, emoji_target, emoji_target)
                    if pixmap.isNull():
                        painter.setFont(text_font)
                        painter.setPen(selected_text_color if is_selected else text_color)
                        painter.drawText(QPoint(run_left, baseline_y), run.text)
                        continue
                    draw_x = run_rect.x() + max(0, (run_rect.width() - pixmap.width()) // 2)
                    draw_y = centered_emoji_top(run_rect.y(), run_rect.height(), pixmap.height(), vertical_nudge=1)
                    painter.drawPixmap(draw_x, draw_y, pixmap)
                    continue

                self._draw_text_run(
                    painter,
                    run,
                    run_rect,
                    baseline_y,
                    selection_range,
                    mention_ranges,
                    text_color,
                    mention_text_color,
                    selected_text_color,
                    highlight_color,
                )

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

    def _status_badge_rect(self, bubble_rect: QRect, row_rect: QRect, message: ChatMessage) -> QRect:
        """Return the rect for the self-message status badge."""
        size = self.STATUS_BADGE_SIZE
        width = size
        count_text = self._group_read_count_text(message)
        if count_text:
            width = max(size, QFontMetrics(self._status_count_font()).horizontalAdvance(count_text) + 12)
        x = max(row_rect.x() + self.LEFT_MARGIN, bubble_rect.x() - self.BUBBLE_GAP - width)
        y = bubble_rect.y() + max(0, bubble_rect.height() - size - 6)
        return QRect(x, y, width, size)

    def _draw_status_badge(self, painter: QPainter, rect: QRect, message: ChatMessage) -> None:
        """Draw a status icon or group read-count pill on the left of self bubbles."""
        badge = self._status_badge_style(message)
        if badge is None:
            return

        color, icon = badge
        count_text = self._group_read_count_text(message)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)

        if count_text:
            badge_path = QPainterPath()
            badge_path.addRoundedRect(QRectF(rect), rect.height() / 2, rect.height() / 2)
            painter.fillPath(badge_path, color)
            painter.setPen(Qt.GlobalColor.white)
            painter.setFont(self._status_count_font())
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, count_text)
            painter.restore()
            return

        painter.drawEllipse(rect)
        icon_rect = QRectF(
            rect.x() + (rect.width() - 8) / 2,
            rect.y() + (rect.height() - 8) / 2,
            8,
            8,
        )
        icon.render(painter, icon_rect, Theme.DARK if not isDarkTheme() else Theme.LIGHT)
        painter.restore()

    def _status_count_font(self) -> QFont:
        """Return the compact font used for group read-count pills."""
        font = QFont()
        font.setPixelSize(10)
        font.setBold(True)
        return font

    def _group_read_count_text(self, message: ChatMessage) -> str:
        """Return the group read-progress label for one self message."""
        if not message.is_self:
            return ""

        extra = message.extra or {}
        try:
            read_count = max(0, int(extra.get("read_count", 0) or 0))
            read_target_count = max(0, int(extra.get("read_target_count", 0) or 0))
        except (TypeError, ValueError):
            return ""

        if read_target_count <= 1 or read_count <= 0:
            return ""
        return f"{read_count}/{read_target_count}"

    def _status_badge_style(self, message: ChatMessage) -> tuple[QColor, AppIcon] | None:
        """Return badge background and icon for message status."""
        dark = isDarkTheme()
        info_color = QColor(157, 157, 157) if dark else QColor(138, 138, 138)
        success_color = QColor(108, 203, 95) if dark else QColor(15, 123, 15)
        error_color = QColor(255, 153, 164) if dark else QColor(196, 43, 28)

        if self._is_uploading(message):
            return info_color, AppIcon.SYNC
        if message.status == MessageStatus.AWAITING_SECURITY_CONFIRMATION:
            return QColor(230, 178, 62) if dark else QColor(161, 107, 0), AppIcon.INFO
        if message.status in (MessageStatus.PENDING, MessageStatus.SENDING):
            return info_color, AppIcon.SEND_FILL
        if message.status == MessageStatus.SENT:
            return success_color, AppIcon.SEND_FILL
        if message.status == MessageStatus.DELIVERED:
            return info_color, AppIcon.COMPLETED
        if message.status == MessageStatus.READ:
            return success_color, AppIcon.COMPLETED
        if message.status == MessageStatus.FAILED:
            return error_color, AppIcon.CANCEL_MEDIUM
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

    def _media_state_text(self, message: ChatMessage) -> str:
        """Return image/video overlay text."""
        if self._is_uploading(message):
            return "Uploading..."
        if message.status == MessageStatus.FAILED:
            return "Upload failed"
        return ""

    def _group_sender_label_text(self, message: ChatMessage) -> str:
        """Return the group member label shown above group bubbles when enabled."""
        if (
            not self._show_group_member_nickname
            or self._active_session_type != "group"
            or self._active_session_id != str(message.session_id or "")
        ):
            return ""

        return self._group_member_display_name(message)

    def _group_member_display_name(self, message: ChatMessage) -> str:
        """Resolve one active-session group member display name for chat-area labels and notices."""
        if (
            self._active_session_type != "group"
            or self._active_session_id != str(message.session_id or "")
        ):
            return (
                str((message.extra or {}).get("sender_nickname", "") or "").strip()
                or str((message.extra or {}).get("sender_name", "") or "").strip()
                or str((message.extra or {}).get("sender_username", "") or "").strip()
                or str(message.sender_id or "").strip()
            )

        member = self._group_members_by_id.get(str(message.sender_id or "").strip(), {})
        return (
            str(member.get("group_nickname", "") or "").strip()
            or str(member.get("remark", "") or "").strip()
            or str(member.get("nickname", "") or "").strip()
            or str(member.get("display_name", "") or "").strip()
            or str(member.get("username", "") or "").strip()
            or str((message.extra or {}).get("sender_nickname", "") or "").strip()
            or str((message.extra or {}).get("sender_name", "") or "").strip()
            or str((message.extra or {}).get("sender_username", "") or "").strip()
            or str(message.sender_id or "").strip()
        )

    def _recall_notice_text(self, message: ChatMessage) -> str:
        """Resolve the displayed recall notice text for one chat row."""
        if (
            message.status == MessageStatus.RECALLED
            and not message.is_self
            and self._active_session_type == "group"
            and self._active_session_id == str(message.session_id or "")
        ):
            actor_name = self._group_member_display_name(message)
            if actor_name:
                return tr("message.recalled.by", "{name} recalled a message", name=f"“{actor_name}”")
        return message.content or tr("message.recalled_notice", "A message was recalled")

    def _group_sender_label_font(self) -> QFont:
        """Return the shared font used by group sender labels."""
        font = QFont()
        font.setPixelSize(self.GROUP_SENDER_LABEL_FONT_PIXEL_SIZE)
        return font

    def _group_sender_label_height(self) -> int:
        """Return the painted height for one sender label row."""
        return QFontMetrics(self._group_sender_label_font()).height()

    def _group_sender_label_block_height(self, message: ChatMessage) -> int:
        """Return the extra top spacing reserved for one group sender label."""
        return self._group_sender_label_height() + self.GROUP_SENDER_LABEL_GAP if self._group_sender_label_text(message) else 0

    def _draw_group_sender_label(self, painter: QPainter, row_layout: _MessageRowLayout, message: ChatMessage) -> None:
        """Draw one compact sender label above the group bubble and align it with the avatar top edge."""
        if row_layout.sender_label_rect is None:
            return

        label = self._group_sender_label_text(message)
        if not label:
            return

        text_rect = row_layout.sender_label_rect
        font = self._group_sender_label_font()
        metrics = QFontMetrics(font)
        painter.setFont(font)
        painter.setPen(QColor(196, 196, 196, 220) if isDarkTheme() else QColor("#8A8A8A"))
        elided = metrics.elidedText(label, Qt.TextElideMode.ElideRight, text_rect.width())
        text_width = metrics.horizontalAdvance(elided)
        if bool(row_layout.sender_label_alignment & Qt.AlignmentFlag.AlignRight):
            text_x = text_rect.right() - text_width + 1
        else:
            text_x = text_rect.x()
        text_y = text_rect.y() + metrics.ascent()
        painter.drawText(QPoint(text_x, text_y), elided)

    def _layout_rects(self, row_rect: QRect, message: ChatMessage) -> _MessageRowLayout:
        """Compute row geometry for avatar, sender label, bubble, and content."""
        bubble_size = self._bubble_size(message, row_rect.width())
        row_top = row_rect.y() + 8
        label = self._group_sender_label_text(message)
        sender_label_height = self._group_sender_label_height() if label else 0
        sender_label_block_height = sender_label_height + self.GROUP_SENDER_LABEL_GAP if label else 0
        standalone_attachment = message.message_type in {MessageType.IMAGE, MessageType.VIDEO, MessageType.FILE}
        avatar_y = row_top
        bubble_y = row_top + sender_label_block_height
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
            sender_label_rect = (
                QRect(
                    bubble_rect.x() + 2,
                    avatar_rect.y(),
                    max(1, bubble_rect.width() - self.TAIL_SPACE - 8),
                    sender_label_height,
                )
                if label
                else None
            )
            sender_label_alignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
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
            sender_label_rect = (
                QRect(
                    bubble_rect.x() + self.TAIL_SPACE + 2,
                    avatar_rect.y(),
                    max(1, bubble_rect.width() - self.TAIL_SPACE - 8),
                    sender_label_height,
                )
                if label
                else None
            )
            sender_label_alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop

        return _MessageRowLayout(
            avatar_rect=avatar_rect,
            bubble_rect=bubble_rect,
            content_rect=self._content_rect(bubble_rect, message),
            sender_label_rect=sender_label_rect,
            sender_label_alignment=sender_label_alignment,
        )

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

        attachment_encryption = dict((message.extra or {}).get("attachment_encryption") or {})
        if attachment_encryption.get("enabled"):
            return ""

        content = ((message.extra.get("url") if message.extra else None) or (message.content or "").strip())
        if not content:
            return ""

        if os.path.exists(content):
            return content

        if content.startswith(("http://", "https://")):
            return content

        if content.startswith("/"):
            origin_base = get_config().server.origin_url.rstrip("/")
            return f"{origin_base}{content}"

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

    def _measure_text_content(self, content: str, max_width: int) -> QSize:
        """Measure wrapped text using wrap-anywhere to avoid clipping digits/URLs."""
        text = content or ""
        cache_key = (text, max_width)
        cached_size = self._cache_get(self._text_measure_cache, cache_key)
        if cached_size is not None:
            return cached_size

        font = self._text_font()
        fm = QFontMetrics(font)
        if not text:
            size = QSize(18, fm.height())
            self._cache_put(self._text_measure_cache, cache_key, size, self.TEXT_MEASURE_CACHE_LIMIT)
            return size

        layout = self._run_text_layout(text, max_width)
        size = QSize(
            max(18, layout.width + 2),
            max(fm.height(), layout.height),
        )
        self._cache_put(self._text_measure_cache, cache_key, size, self.TEXT_MEASURE_CACHE_LIMIT)
        return size

    @staticmethod
    def _text_font() -> QFont:
        """Return the base font used for text messages."""
        font = QFont()
        font.setPixelSize(17)
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
    def _ranges_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
        """Return whether two half-open ranges overlap."""
        return start_a < end_b and start_b < end_a

    def _draw_text_run(
        self,
        painter: QPainter,
        run: _TextRunLayout,
        run_rect: QRect,
        baseline_y: int,
        selection_range: tuple[int, int] | None,
        mention_ranges: list[tuple[int, int]],
        text_color: QColor,
        mention_text_color: QColor,
        selected_text_color: QColor,
        highlight_color: QColor,
    ) -> None:
        """Draw a text run, splitting around any active selection."""
        painter.setFont(self._text_font())

        for segment_start, segment_end, is_selected, is_mentioned in self._text_run_segments(
            run,
            selection_range,
            mention_ranges,
        ):
            if segment_start >= segment_end:
                continue
            segment_x = run_rect.x() + self._text_run_offset(run, segment_start)
            segment_width = self._text_run_offset(run, segment_end) - self._text_run_offset(run, segment_start)
            segment_rect = QRect(segment_x, run_rect.y(), max(1, segment_width), run_rect.height())
            if is_selected:
                painter.fillRect(segment_rect.adjusted(0, 0, 0, -1), highlight_color)

            text_slice = run.text[segment_start - run.start : segment_end - run.start]
            if is_selected:
                painter.setPen(selected_text_color)
            elif is_mentioned:
                painter.setPen(mention_text_color)
            else:
                painter.setPen(text_color)
            painter.drawText(QPoint(segment_x, baseline_y), text_slice)

    @staticmethod
    def _text_run_segments(
        run: _TextRunLayout,
        selection_range: tuple[int, int] | None,
        mention_ranges: list[tuple[int, int]],
    ) -> list[tuple[int, int, bool, bool]]:
        """Split a text run into selected and unselected drawing segments."""
        boundaries = {run.start, run.end}
        if selection_range:
            selection_start = max(selection_range[0], run.start)
            selection_end = min(selection_range[1], run.end)
            if selection_start < selection_end:
                boundaries.add(selection_start)
                boundaries.add(selection_end)
        for mention_start, mention_end in mention_ranges:
            clamped_start = max(mention_start, run.start)
            clamped_end = min(mention_end, run.end)
            if clamped_start < clamped_end:
                boundaries.add(clamped_start)
                boundaries.add(clamped_end)

        ordered = sorted(boundaries)
        segments: list[tuple[int, int, bool, bool]] = []
        for segment_start, segment_end in zip(ordered, ordered[1:]):
            is_selected = bool(selection_range and selection_range[0] <= segment_start and selection_range[1] >= segment_end)
            is_mentioned = any(start <= segment_start and end >= segment_end for start, end in mention_ranges)
            segments.append((segment_start, segment_end, is_selected, is_mentioned))
        return segments

    @staticmethod
    def _message_mention_ranges(message: ChatMessage) -> list[tuple[int, int]]:
        """Return normalized mention index ranges for one text message."""
        mentions = normalize_message_mentions(
            dict(message.extra or {}).get("mentions"),
            content=message.content or "",
        )
        return [(int(mention["start"]), int(mention["end"])) for mention in mentions]

    @staticmethod
    def _text_run_offset(run: _TextRunLayout, position: int) -> int:
        """Return the pixel offset from the run start to a character index."""
        offset = max(0, min(position - run.start, len(run.char_offsets) - 1))
        if not run.char_offsets:
            return 0
        return run.char_offsets[offset]

    @staticmethod
    def _build_text_run(
        text: str,
        advances: list[int],
        start: int,
        x: int,
        text_metrics: QFontMetrics,
    ) -> _TextRunLayout:
        """Create one continuous text run with cached prefix offsets."""
        width = sum(advances)
        offsets = [0]
        current = 0
        for advance in advances:
            current += advance
            offsets.append(current)
        return _TextRunLayout(
            "text",
            text,
            start,
            start + len(text),
            width,
            text_metrics.height(),
            text_metrics.ascent(),
            text_metrics.descent(),
            tuple(advances),
            tuple(offsets),
            x=x,
        )

    def _run_text_layout(self, content: str, width: int) -> _RunTextLayout:
        """Build a custom run-based layout for bubble text."""
        cache_key = (max(1, width), content or "")
        cached_layout = self._cache_get(self._text_layout_cache, cache_key)
        if cached_layout is not None:
            return cached_layout

        text_font = self._text_font()
        text_metrics = QFontMetrics(text_font)
        emoji_target = BUBBLE_EMOJI_PIXEL_SIZE
        max_width = max(1, width)

        def new_line() -> _TextLineLayout:
            return _TextLineLayout([], 0, text_metrics.height(), text_metrics.ascent())

        def append_line(target: list[_TextLineLayout], line: _TextLineLayout) -> None:
            target.append(line)

        text_buffer: list[str] = []
        text_advances: list[int] = []
        text_buffer_start: int | None = None
        text_buffer_width = 0

        def flush_text_buffer() -> None:
            nonlocal text_buffer, text_advances, text_buffer_start, text_buffer_width, current_line
            if not text_buffer or text_buffer_start is None:
                text_buffer = []
                text_advances = []
                text_buffer_start = None
                text_buffer_width = 0
                return

            token = self._build_text_run(
                "".join(text_buffer),
                text_advances,
                text_buffer_start,
                current_line.width,
                text_metrics,
            )
            current_line.runs.append(token)
            current_line.width += token.width
            text_buffer = []
            text_advances = []
            text_buffer_start = None
            text_buffer_width = 0

        runs: list[_TextLineLayout] = []
        current_line = new_line()
        pure_emoji = bool(content) and is_emoji_text(content)
        position = 0

        for chunk, is_emoji_chunk in iter_text_and_emoji_clusters(content or ""):
            if is_emoji_chunk:
                flush_text_buffer()
                pixmap = load_emoji_pixmap(chunk, emoji_target, emoji_target)
                emoji_width = pixmap.width() if not pixmap.isNull() else max(emoji_target, text_metrics.height())
                emoji_height = pixmap.height() if not pixmap.isNull() else max(emoji_target, text_metrics.height())
                run_height = max(text_metrics.height(), emoji_height)
                run_ascent = text_metrics.ascent() + max(0, (run_height - text_metrics.height()) // 2)
                gap_before = self.EMOJI_TEXT_GAP if current_line.runs and current_line.runs[-1].kind == "text" else 0
                token = _TextRunLayout(
                    "emoji",
                    chunk,
                    position,
                    position + len(chunk),
                    emoji_width,
                    run_height,
                    run_ascent,
                    max(0, run_height - run_ascent),
                    (),
                    (),
                )
                if current_line.runs and current_line.width + gap_before + token.width > max_width:
                    append_line(runs, current_line)
                    current_line = new_line()
                    gap_before = 0
                current_line.width += gap_before
                token.x = current_line.width
                current_line.runs.append(token)
                current_line.width += token.width
                current_line.baseline = max(current_line.baseline, token.ascent)
                current_line.height = max(current_line.height, token.ascent + token.descent)
                position += len(chunk)
                continue

            for char in chunk:
                start = position
                end = position + 1
                position = end

                if char == "\n":
                    flush_text_buffer()
                    append_line(runs, current_line)
                    current_line = new_line()
                    continue

                token_width = max(1, text_metrics.horizontalAdvance(char))
                gap_before = self.EMOJI_TEXT_GAP if not text_buffer and current_line.runs and current_line.runs[-1].kind == "emoji" else 0
                if (current_line.runs or text_buffer) and current_line.width + gap_before + text_buffer_width + token_width > max_width:
                    flush_text_buffer()
                    append_line(runs, current_line)
                    current_line = new_line()
                    gap_before = 0

                if text_buffer_start is None:
                    current_line.width += gap_before
                    text_buffer_start = start
                text_buffer.append(char)
                text_advances.append(token_width)
                text_buffer_width += token_width

        flush_text_buffer()
        append_line(runs, current_line)

        if not runs:
            runs = [new_line()]

        total_height = 0
        max_line_width = 0
        for line in runs:
            line.y = total_height
            max_line_width = max(max_line_width, line.width)
            line.x = max(0, (max_width - line.width) // 2) if pure_emoji else 0
            for run in line.runs:
                run.y = max(0, line.baseline - run.ascent)
            total_height += line.height

        layout = _RunTextLayout(runs, max_line_width, max(total_height, text_metrics.height()), pure_emoji)
        self._cache_put(self._text_layout_cache, cache_key, layout, self.TEXT_LAYOUT_CACHE_LIMIT)
        return layout

    def _text_layout(self, rect: QRect, content: str) -> tuple[QRect, _RunTextLayout]:
        """Return the draw rect and custom layout for a text bubble."""
        layout = self._run_text_layout(content or "", rect.width())
        text_y = rect.y() + max(0, (rect.height() - layout.height) // 2)
        return QRect(rect.x(), text_y, max(1, rect.width()), layout.height), layout

    def _max_bubble_width_for_row(self, row_width: int) -> int:
        """Return the maximum width a bubble/media card can occupy in the current row."""
        if row_width <= 0:
            return self.MAX_TEXT_WIDTH + self.BUBBLE_PADDING_H * 2 + self.TAIL_SPACE

        reserved = self.LEFT_MARGIN + self.RIGHT_MARGIN + self.AVATAR_SIZE + self.BUBBLE_GAP + 28
        return max(56, row_width - reserved)

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
        layout: _RunTextLayout,
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

        local_x = max(0, local_x)
        local_y = max(0, local_y)

        if not layout.lines:
            return 0

        for line_index, line in enumerate(layout.lines):
            line_top = line.y
            line_bottom = line.y + line.height
            line_left = line.x
            line_right = line.x + line.width

            if not clamp:
                if local_y < line_top or local_y > line_bottom:
                    continue
                if local_x < line_left or local_x > line_right:
                    return -1

            if local_y < line_bottom or line_index == len(layout.lines) - 1:
                if not line.runs:
                    if line_index == 0:
                        return 0
                    previous_line = layout.lines[line_index - 1]
                    return previous_line.runs[-1].end if previous_line.runs else 0
                if local_x <= line.x:
                    return line.runs[0].start
                for run in line.runs:
                    run_left = line.x + run.x
                    if local_x <= run_left:
                        return run.start
                    right = run_left + run.width
                    if local_x <= right:
                        if run.kind == "text" and run.char_advances:
                            local_run_x = max(0, local_x - run_left)
                            for offset, advance in enumerate(run.char_advances):
                                current_x = run.char_offsets[offset]
                                midpoint = current_x + advance / 2
                                if local_run_x <= midpoint:
                                    return run.start + offset
                            return run.end
                        midpoint = run_left + run.width / 2
                        return run.end if local_x >= midpoint else run.start
                return line.runs[-1].end

        if not clamp:
            return -1

        last_line = layout.lines[-1]
        if not last_line.runs:
            return 0
        return last_line.runs[-1].end

    @staticmethod
    def _text_color(message: ChatMessage) -> QColor:
        """Return the foreground text color for a message bubble."""
        if isDarkTheme():
            return QColor(246, 248, 250, 235) if message.is_self else QColor(236, 239, 243, 230)
        return QColor("#1A1A1A")

    @staticmethod
    def _is_uploading(message: ChatMessage) -> bool:
        """Return whether the message is still in HTTP upload stage."""
        return bool(getattr(message, "extra", {}) and message.extra.get("uploading"))

    @staticmethod
    def _bubble_fill_color(message: ChatMessage, *, context_menu_active: bool = False) -> QColor:
        """Return one stable bubble fill, including the right-click pressed state."""
        dark = isDarkTheme()
        if message.is_self:
            bubble_color = QColor(themeColor())
            if context_menu_active:
                bubble_color.setAlpha(100 if dark else 64)
            else:
                bubble_color.setAlpha(58 if dark else 22)
            return bubble_color
        if dark:
            return QColor(255, 255, 255, 54 if context_menu_active else 22)
        return QColor("#EBEBEB") if context_menu_active else QColor(255, 255, 255, 214)

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

    def _format_time(self, value, *, expanded: bool = False) -> str:
        """Format message time for the standalone center time block."""
        if expanded:
            return format_chat_timestamp_expanded(value)
        return format_chat_timestamp(value)

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

        attachment_encryption = dict((message.extra or {}).get("attachment_encryption") or {})
        if attachment_encryption.get("enabled"):
            return ""

        content = (message.content or "").strip()
        if not content:
            return ""

        if os.path.exists(content):
            return content

        if content.startswith(("http://", "https://")):
            return content

        if content.startswith("/"):
            origin_base = get_config().server.origin_url.rstrip("/")
            return f"{origin_base}{content}"

        return content

    def _request_image(self, source: str) -> None:
        """Start downloading a remote image if needed."""
        if not source or source in self._loading_sources:
            return
        failed_at = self._failed_image_sources.get(source)
        if failed_at is not None and (time.monotonic() - failed_at) < 30.0:
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
                if source:
                    self._failed_image_sources[source] = time.monotonic()
                return

            pixmap = QPixmap()
            if not pixmap.loadFromData(bytes(reply.readAll())):
                if source:
                    self._failed_image_sources[source] = time.monotonic()
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
            self._failed_image_sources.pop(source, None)
            self._schedule_refresh_message_view()
        finally:
            reply.deleteLater()

    def _on_video_thumbnail_ready(self, source: str) -> None:
        """Refresh the view after a background video thumbnail finishes generating."""
        if source:
            self._schedule_refresh_message_view()

    def _on_avatar_ready(self, _source: str) -> None:
        """Refresh the view after a remote avatar finishes downloading."""
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


