"""Delegate-rendered message bubbles for the local AI assistant page."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QModelIndex, QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPixmap,
    QTextCharFormat,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem
from qfluentwidgets import isDarkTheme, themeColor

from client.core.i18n import tr
from client.models.ai_assistant import AIMessage, AIMessageRole, AIMessageStatus


@dataclass(frozen=True)
class AIAssistantMessageLayout:
    """Resolved viewport geometry for one assistant message row."""

    track_rect: QRect
    bubble_rect: QRect
    content_rect: QRect
    text_rect: QRect
    image_rect: QRect | None
    status_rect: QRect | None
    confirmation_rect: QRect | None
    cancel_button_rect: QRect | None
    confirm_button_rect: QRect | None
    footer_rect: QRect | None


class AIAssistantMessageDelegate(QStyledItemDelegate):
    """Paint AI assistant messages without per-row QWidget cards."""

    TRACK_HORIZONTAL_MARGIN = 28
    MAX_TRACK_WIDTH = 1100
    MIN_TRACK_WIDTH = 320
    FIRST_ROW_TOP_MARGIN = 26
    ROW_BOTTOM_SPACING = 14
    USER_MAX_TEXT_WIDTH = 520
    BUBBLE_PADDING_H = 14
    BUBBLE_PADDING_V = 10
    BUBBLE_RADIUS = 10
    ASSISTANT_SECTION_GAP = 10
    ACTION_CARD_MAX_WIDTH = 560
    ACTION_CARD_PADDING = 12
    ACTION_BUTTON_WIDTH = 76
    ACTION_BUTTON_HEIGHT = 32
    ACTION_BUTTON_GAP = 8
    ACTION_STATUS_MAX_WIDTH = 560
    ACTION_STATUS_PADDING = 10
    ACTION_STATUS_LINE_GAP = 6
    IMAGE_WIDTH = 220
    IMAGE_HEIGHT = 140
    IMAGE_BOTTOM_GAP = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selection_message_id: str | None = None
        self._selection_anchor = -1
        self._selection_position = -1
        self._selection_active = False
        self._context_menu_message_id: str | None = None
        self._hovered_action: tuple[str, str] | None = None
        self._hovered_status_message_id: str | None = None
        self._disabled_action_message_ids: set[str] = set()
        self._expanded_action_status_message_ids: set[str] = set()
        self._animation_frame = 0
        self._bottom_reserved_height = 0

    def set_bottom_reserved_height(self, height: int) -> bool:
        next_height = max(0, int(height or 0))
        if next_height == self._bottom_reserved_height:
            return False
        self._bottom_reserved_height = next_height
        return True

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        message = self._message(index)
        if message is None:
            return QSize(option.rect.width(), 0)
        row_width = max(option.rect.width(), self.MIN_TRACK_WIDTH + self.TRACK_HORIZONTAL_MARGIN * 2)
        layout = self._layout_rects(QRect(0, 0, row_width, 1), message, index.row())
        bottom_reserved = self._bottom_reserved_height if self._is_last_row(index) else 0
        return QSize(row_width, max(1, layout.bubble_rect.bottom() + 1 + self.ROW_BOTTOM_SPACING + bottom_reserved))

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        message = self._message(index)
        if message is None:
            return super().paint(painter, option, index)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setClipRect(option.rect)

        layout = self.layout_for_index(option.rect, index)
        if self._is_user(message):
            self._draw_user_bubble(painter, layout.bubble_rect, message)
        elif message.message_id == self._context_menu_message_id:
            self._draw_assistant_context_highlight(painter, layout.bubble_rect)

        if layout.image_rect is not None:
            self._draw_image(painter, layout.image_rect, self._first_image_attachment(message.extra))
        if layout.text_rect.height() > 0:
            self._draw_message_text(painter, layout.text_rect, message)
        if layout.status_rect is not None:
            self._draw_action_status_card(painter, layout.status_rect, message)
        if layout.confirmation_rect is not None:
            self._draw_confirmation_card(painter, layout, message)
        if layout.footer_rect is not None:
            self._draw_auxiliary_text(painter, layout.footer_rect, self._footer_text(message))

        painter.restore()

    def layout_for_index(self, row_rect: QRect, index: QModelIndex) -> AIAssistantMessageLayout:
        message = self._message(index)
        if message is None:
            empty = QRect(row_rect.x(), row_rect.y(), 0, 0)
            return AIAssistantMessageLayout(empty, empty, empty, empty, None, None, None, None, None, None)
        height = row_rect.height()
        if height <= 0:
            option = QStyleOptionViewItem()
            option.rect = QRect(row_rect.x(), row_rect.y(), row_rect.width(), 1)
            height = self.sizeHint(option, index).height()
            row_rect = QRect(row_rect.x(), row_rect.y(), row_rect.width(), height)
        return self._layout_rects(row_rect, message, index.row())

    def is_bubble_hit(self, view, index: QModelIndex, position: QPoint) -> bool:
        if not index.isValid():
            return False
        layout = self.layout_for_index(view.visualRect(index), index)
        return layout.bubble_rect.contains(position)

    def is_text_hit(self, view, index: QModelIndex, position: QPoint) -> bool:
        if not index.isValid():
            return False
        layout = self.layout_for_index(view.visualRect(index), index)
        return layout.text_rect.contains(position)

    def is_action_status_hit(self, view, index: QModelIndex, position: QPoint) -> bool:
        if not index.isValid():
            return False
        message = self._message(index)
        if message is None or not self._action_status_summary_text(message.extra):
            return False
        layout = self.layout_for_index(view.visualRect(index), index)
        return layout.status_rect is not None and layout.status_rect.contains(position)

    def toggle_action_status_expanded(self, view, index: QModelIndex, position: QPoint) -> bool:
        message = self._message(index)
        if message is None or not self.is_action_status_hit(view, index, position):
            return False
        if message.message_id in self._expanded_action_status_message_ids:
            self._expanded_action_status_message_ids.discard(message.message_id)
        else:
            self._expanded_action_status_message_ids.add(message.message_id)
        if view is not None:
            view.doItemsLayout()
            view.viewport().update()
        return True

    def is_action_status_expanded(self, message_id: str) -> bool:
        return str(message_id or "").strip() in self._expanded_action_status_message_ids

    def set_animation_frame(self, frame: int, view=None) -> None:
        next_frame = max(0, int(frame or 0)) % 4
        if next_frame == self._animation_frame:
            return
        self._animation_frame = next_frame
        if view is not None:
            view.viewport().update()

    def action_command_at(self, view, index: QModelIndex, position: QPoint) -> str | None:
        message = self._message(index)
        if message is None or message.message_id in self._disabled_action_message_ids:
            return None
        layout = self.layout_for_index(view.visualRect(index), index)
        if layout.confirm_button_rect is not None and layout.confirm_button_rect.contains(position):
            return "confirm"
        if layout.cancel_button_rect is not None and layout.cancel_button_rect.contains(position):
            return "cancel"
        return None

    def update_action_hover(self, view, index: QModelIndex, position: QPoint) -> bool:
        message = self._message(index)
        command = self.action_command_at(view, index, position) if message is not None else None
        next_hover = (message.message_id, command) if message is not None and command else None
        if next_hover == self._hovered_action:
            return bool(next_hover)
        self._hovered_action = next_hover
        if next_hover is not None:
            self._hovered_status_message_id = None
        if view is not None:
            view.viewport().update()
        return bool(next_hover)

    def update_action_status_hover(self, view, index: QModelIndex, position: QPoint) -> bool:
        message = self._message(index)
        next_hover = (
            message.message_id
            if message is not None and self.is_action_status_hit(view, index, position)
            else None
        )
        if next_hover == self._hovered_status_message_id:
            return bool(next_hover)
        self._hovered_status_message_id = next_hover
        if next_hover is not None:
            self._hovered_action = None
        if view is not None:
            view.viewport().update()
        return bool(next_hover)

    def clear_action_hover(self, view=None) -> None:
        if self._hovered_action is None and self._hovered_status_message_id is None:
            return
        self._hovered_action = None
        self._hovered_status_message_id = None
        if view is not None:
            view.viewport().update()

    def set_action_message_enabled(self, view, message_id: str, enabled: bool) -> None:
        normalized = str(message_id or "").strip()
        if not normalized:
            return
        if enabled:
            self._disabled_action_message_ids.discard(normalized)
        else:
            self._disabled_action_message_ids.add(normalized)
        if view is not None:
            view.viewport().update()

    def set_context_menu_message(self, view, message_id: str | None) -> None:
        normalized = str(message_id or "").strip() or None
        if normalized == self._context_menu_message_id:
            return
        self._context_menu_message_id = normalized
        if view is not None:
            view.viewport().update()

    def begin_text_selection(self, view, index: QModelIndex, position: QPoint) -> bool:
        message = self._message(index)
        if message is None or not str(message.content or ""):
            return False
        cursor_pos = self._text_position_for_point(view, index, position, clamp=False)
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
        if not self._selection_active:
            return False
        index = view.currentIndex()
        message = self._message(index)
        if message is None or message.message_id != self._selection_message_id:
            return False
        cursor_pos = self._text_position_for_point(view, index, position, clamp=True)
        if cursor_pos < 0:
            return False
        self._selection_position = cursor_pos
        view.viewport().update()
        return True

    def end_text_selection(self, view=None) -> None:
        self._selection_active = False
        if view is not None:
            view.viewport().update()

    def clear_text_selection(self, view=None) -> None:
        self._selection_message_id = None
        self._selection_anchor = -1
        self._selection_position = -1
        self._selection_active = False
        if view is not None:
            view.viewport().update()

    def is_selection_active(self) -> bool:
        return self._selection_active

    def has_selected_text(self, message_id: str | None = None) -> bool:
        if self._selection_message_id is None or self._selection_anchor == self._selection_position:
            return False
        return message_id is None or self._selection_message_id == message_id

    def selected_text(self, content: str, message_id: str | None = None) -> str:
        if not self.has_selected_text(message_id):
            return ""
        start = max(0, min(self._selection_anchor, self._selection_position))
        end = min(len(content or ""), max(self._selection_anchor, self._selection_position))
        return (content or "")[start:end]

    def _layout_rects(self, row_rect: QRect, message: AIMessage, row: int) -> AIAssistantMessageLayout:
        track_width = self._track_width(row_rect.width())
        track_x = row_rect.x() + max(0, (row_rect.width() - track_width) // 2)
        top = row_rect.y() + (self.FIRST_ROW_TOP_MARGIN if row <= 0 else 0)
        track_rect = QRect(track_x, top, track_width, max(1, row_rect.height()))
        is_user = self._is_user(message)
        image_rect = self._image_rect(track_rect, message) if self._first_image_attachment(message.extra) else None
        cursor_y = top

        if image_rect is not None:
            cursor_y = image_rect.bottom() + 1 + self.IMAGE_BOTTOM_GAP

        text = self._message_display_text(message)
        footer_text = self._footer_text(message)
        status_lines = self._action_status_display_lines(message)
        confirmation = self._confirmation_preview(message.extra)

        if is_user:
            available_text_width = max(24, min(self.USER_MAX_TEXT_WIDTH, track_width - self.BUBBLE_PADDING_H * 2))
            text_size = self._measure_text(text, available_text_width, self._text_font())
            content_width = max(18, text_size.width())
            bubble_width = min(track_width, max(42, content_width + self.BUBBLE_PADDING_H * 2))
            text_height = max(QFontMetrics(self._text_font()).height(), text_size.height()) if text else 0
            bubble_height = max(40, text_height + self.BUBBLE_PADDING_V * 2)
            if image_rect is not None:
                bubble_height += image_rect.height() + self.IMAGE_BOTTOM_GAP
                bubble_width = max(bubble_width, image_rect.width() + self.BUBBLE_PADDING_H * 2)
            bubble_x = track_rect.right() - bubble_width + 1
            bubble_rect = QRect(bubble_x, top, bubble_width, bubble_height)
            image_rect = self._offset_image_for_bubble(image_rect, bubble_rect) if image_rect is not None else None
            content_rect = bubble_rect.adjusted(self.BUBBLE_PADDING_H, self.BUBBLE_PADDING_V, -self.BUBBLE_PADDING_H, -self.BUBBLE_PADDING_V)
            text_top = content_rect.y() if image_rect is None else image_rect.bottom() + 1 + self.IMAGE_BOTTOM_GAP
            text_rect = QRect(content_rect.x(), text_top, max(1, content_rect.width()), text_height)
            return AIAssistantMessageLayout(
                track_rect=track_rect,
                bubble_rect=bubble_rect,
                content_rect=content_rect,
                text_rect=text_rect,
                image_rect=image_rect,
                status_rect=None,
                confirmation_rect=None,
                cancel_button_rect=None,
                confirm_button_rect=None,
                footer_rect=None,
            )

        text_width = track_width
        text_size = self._measure_text(text, text_width, self._text_font())
        text_height = text_size.height() if text else 0
        text_rect = QRect(track_x, cursor_y, text_width, text_height)
        cursor_y = text_rect.bottom() + 1 if text_height > 0 else cursor_y

        status_rect = None
        if status_lines:
            if cursor_y > top:
                cursor_y += self.ASSISTANT_SECTION_GAP
            status_rect = self._action_status_layout(track_x, cursor_y, track_width, status_lines)
            cursor_y = status_rect.bottom() + 1

        confirmation_rect = None
        cancel_button_rect = None
        confirm_button_rect = None
        if confirmation:
            if cursor_y > top:
                cursor_y += self.ASSISTANT_SECTION_GAP
            confirmation_rect, cancel_button_rect, confirm_button_rect = self._confirmation_layout(track_x, cursor_y, track_width, confirmation)
            cursor_y = confirmation_rect.bottom() + 1

        footer_rect = None
        if footer_text:
            if cursor_y > top:
                cursor_y += self.ASSISTANT_SECTION_GAP
            footer_size = self._measure_text(footer_text, text_width, self._caption_font())
            footer_rect = QRect(track_x, cursor_y, text_width, footer_size.height())
            cursor_y = footer_rect.bottom() + 1

        if image_rect is not None and image_rect.bottom() + 1 > cursor_y:
            cursor_y = image_rect.bottom() + 1
        if cursor_y <= top:
            cursor_y = top + QFontMetrics(self._text_font()).height()
        bubble_rect = QRect(track_x, top, track_width, max(1, cursor_y - top))
        return AIAssistantMessageLayout(
            track_rect=track_rect,
            bubble_rect=bubble_rect,
            content_rect=bubble_rect,
            text_rect=text_rect,
            image_rect=image_rect,
            status_rect=status_rect,
            confirmation_rect=confirmation_rect,
            cancel_button_rect=cancel_button_rect,
            confirm_button_rect=confirm_button_rect,
            footer_rect=footer_rect,
        )

    def _draw_user_bubble(self, painter: QPainter, rect: QRect, message: AIMessage) -> None:
        color = QColor(themeColor())
        color.setAlpha(58 if isDarkTheme() else 22)
        if message.message_id == self._context_menu_message_id:
            color.setAlpha(min(255, color.alpha() + 34))
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), self.BUBBLE_RADIUS, self.BUBBLE_RADIUS)
        painter.fillPath(path, color)

    def _draw_assistant_context_highlight(self, painter: QPainter, rect: QRect) -> None:
        color = QColor(255, 255, 255, 24) if isDarkTheme() else QColor(0, 0, 0, 10)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect.adjusted(-8, -6, 8, 6)), self.BUBBLE_RADIUS, self.BUBBLE_RADIUS)
        painter.fillPath(path, color)

    def _draw_message_text(self, painter: QPainter, rect: QRect, message: AIMessage) -> None:
        text = self._message_display_text(message)
        if not text:
            return
        color = QColor(246, 248, 250, 235) if isDarkTheme() else QColor(26, 26, 26)
        self._draw_text_layout(
            painter,
            rect,
            text,
            self._text_font(),
            color,
            selection=self._selection_range_for(message),
        )

    def _draw_auxiliary_text(self, painter: QPainter, rect: QRect, text: str) -> None:
        if not text:
            return
        color = QColor(236, 239, 243, 166) if isDarkTheme() else QColor(26, 26, 26, 150)
        self._draw_text_layout(painter, rect, text, self._caption_font(), color)

    def _draw_action_status_card(self, painter: QPainter, rect: QRect, message: AIMessage) -> None:
        lines = self._action_status_display_lines(message)
        if not lines:
            return
        dark = isDarkTheme()
        hovered = self._hovered_status_message_id == message.message_id
        bg = QColor(255, 255, 255, 14 if hovered else 9) if dark else QColor(255, 255, 255, 180 if hovered else 150)
        border = QColor(255, 255, 255, 42) if dark else QColor(15, 23, 42, 28)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 8, 8)
        painter.fillPath(path, bg)
        painter.setPen(border)
        painter.drawPath(path)

        x = rect.x() + self.ACTION_STATUS_PADDING
        y = rect.y() + self.ACTION_STATUS_PADDING
        width = rect.width() - self.ACTION_STATUS_PADDING * 2
        header_color = QColor(246, 248, 250, 235) if dark else QColor(26, 26, 26)
        detail_color = QColor(236, 239, 243, 166) if dark else QColor(26, 26, 26, 150)
        for index, text in enumerate(lines):
            font = self._text_font() if index == 0 else self._caption_font()
            color = header_color if index == 0 else detail_color
            size = self._measure_text(text, width, font)
            self._draw_text_layout(painter, QRect(x, y, width, size.height()), text, font, color)
            y += size.height() + self.ACTION_STATUS_LINE_GAP

    def _draw_confirmation_card(self, painter: QPainter, layout: AIAssistantMessageLayout, message: AIMessage) -> None:
        rect = layout.confirmation_rect
        if rect is None:
            return
        preview = self._confirmation_preview(message.extra)
        if not preview:
            return
        dark = isDarkTheme()
        bg = QColor(255, 255, 255, 10) if dark else QColor(255, 255, 255, 158)
        border = QColor(255, 255, 255, 36) if dark else QColor(15, 23, 42, 30)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 8, 8)
        painter.fillPath(path, bg)
        painter.setPen(border)
        painter.drawPath(path)

        x = rect.x() + self.ACTION_CARD_PADDING
        y = rect.y() + self.ACTION_CARD_PADDING
        width = rect.width() - self.ACTION_CARD_PADDING * 2
        title = str(preview.get("operation") or "发送消息").strip() or "发送消息"
        target = str(preview.get("target") or "目标联系人").strip() or "目标联系人"
        content = str(preview.get("content") or "").strip()
        lines = [
            (title, self._text_font(), QColor(246, 248, 250, 235) if dark else QColor(26, 26, 26)),
            (f"收件人：{target}", self._caption_font(), QColor(236, 239, 243, 166) if dark else QColor(26, 26, 26, 150)),
            (f"内容：{content}" if content else "内容：", self._text_font(), QColor(246, 248, 250, 235) if dark else QColor(26, 26, 26)),
            ("这是会产生外部影响的操作，确认后才会发送。", self._caption_font(), QColor(236, 239, 243, 166) if dark else QColor(26, 26, 26, 150)),
        ]
        for text, font, color in lines:
            size = self._measure_text(text, width, font)
            self._draw_text_layout(painter, QRect(x, y, width, size.height()), text, font, color)
            y += size.height() + 6

        disabled = message.message_id in self._disabled_action_message_ids
        if layout.cancel_button_rect is not None:
            self._draw_action_button(painter, layout.cancel_button_rect, "取消", primary=False, disabled=disabled, message_id=message.message_id, command="cancel")
        if layout.confirm_button_rect is not None:
            self._draw_action_button(painter, layout.confirm_button_rect, "发送", primary=True, disabled=disabled, message_id=message.message_id, command="confirm")

    def _draw_action_button(
        self,
        painter: QPainter,
        rect: QRect,
        text: str,
        *,
        primary: bool,
        disabled: bool,
        message_id: str,
        command: str,
    ) -> None:
        dark = isDarkTheme()
        hovered = self._hovered_action == (message_id, command)
        if primary:
            fill = QColor(themeColor())
            fill.setAlpha(118 if disabled else (232 if hovered else 210))
            pen = QColor(themeColor())
            text_color = QColor(255, 255, 255, 150 if disabled else 255)
        else:
            fill = QColor(255, 255, 255, 10 if dark else 210)
            if hovered and not disabled:
                fill = QColor(255, 255, 255, 26) if dark else QColor(0, 0, 0, 12)
            pen = QColor(255, 255, 255, 36) if dark else QColor(15, 23, 42, 34)
            text_color = QColor(236, 239, 243, 120 if disabled else 230) if dark else QColor(26, 26, 26, 100 if disabled else 220)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 7, 7)
        painter.fillPath(path, fill)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.setFont(self._button_font())
        painter.setPen(text_color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_image(self, painter: QPainter, rect: QRect, attachment: dict | None) -> None:
        path = str((attachment or {}).get("local_path") or "").strip()
        pixmap = QPixmap(path) if path and Path(path).is_file() else QPixmap()
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(rect), 8, 8)
        painter.save()
        painter.setClipPath(clip)
        if pixmap.isNull():
            painter.fillRect(rect, QColor(255, 255, 255, 18) if isDarkTheme() else QColor(0, 0, 0, 10))
            painter.setPen(QColor(236, 239, 243, 166) if isDarkTheme() else QColor(26, 26, 26, 150))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Image")
        else:
            scaled = pixmap.scaled(rect.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            draw_x = rect.x() + max(0, (rect.width() - scaled.width()) // 2)
            draw_y = rect.y() + max(0, (rect.height() - scaled.height()) // 2)
            painter.drawPixmap(draw_x, draw_y, scaled)
        painter.restore()

    def _draw_text_layout(
        self,
        painter: QPainter,
        rect: QRect,
        text: str,
        font: QFont,
        color: QColor,
        *,
        selection: tuple[int, int] | None = None,
    ) -> None:
        layout, _size = self._build_text_layout(text, max(1, rect.width()), font)
        painter.save()
        painter.setFont(font)
        painter.setPen(color)
        selections = []
        if selection is not None and selection[0] < selection[1]:
            text_format = QTextCharFormat()
            text_format.setBackground(QColor(86, 157, 229, 120) if isDarkTheme() else QColor(140, 196, 255, 140))
            text_format.setForeground(QColor(255, 255, 255) if isDarkTheme() else QColor("#101010"))
            selection_range = QTextLayout.FormatRange()
            selection_range.start = selection[0]
            selection_range.length = selection[1] - selection[0]
            selection_range.format = text_format
            selections = [selection_range]
        layout.draw(painter, QPointF(rect.x(), rect.y()), selections)
        painter.restore()

    def _text_position_for_point(self, view, index: QModelIndex, position: QPoint, *, clamp: bool) -> int:
        message = self._message(index)
        if message is None:
            return -1
        layout_rects = self.layout_for_index(view.visualRect(index), index)
        if not layout_rects.text_rect.isValid() or not str(message.content or ""):
            return -1
        if not clamp and not layout_rects.text_rect.contains(position):
            return -1
        text = str(message.content or "")
        layout, _size = self._build_text_layout(text, max(1, layout_rects.text_rect.width()), self._text_font())
        local_x = position.x() - layout_rects.text_rect.x()
        local_y = position.y() - layout_rects.text_rect.y()
        line_count = layout.lineCount()
        if line_count <= 0:
            return 0
        if local_y <= 0:
            return 0 if clamp else -1
        for line_index in range(line_count):
            line = layout.lineAt(line_index)
            if local_y <= line.y() + line.height():
                return max(0, min(len(text), line.xToCursor(local_x)))
        return len(text) if clamp else -1

    def _selection_range_for(self, message: AIMessage) -> tuple[int, int] | None:
        if not self.has_selected_text(message.message_id):
            return None
        start = max(0, min(self._selection_anchor, self._selection_position))
        end = min(len(message.content or ""), max(self._selection_anchor, self._selection_position))
        return start, end

    def _action_status_display_lines(self, message: AIMessage) -> list[str]:
        summary = self._action_status_summary_text(message.extra, animation_frame=self._animation_frame)
        if not summary:
            return []
        if not self.is_action_status_expanded(message.message_id):
            return [summary]
        details = [line for line in self._action_status_text(message.extra).splitlines() if line.strip()]
        if not details:
            return [summary]
        if len(details) == 1 and details[0] == summary:
            return [summary]
        return [summary, *details[:6]]

    def _action_status_layout(self, x: int, y: int, track_width: int, lines: list[str]) -> QRect:
        width = min(self.ACTION_STATUS_MAX_WIDTH, max(240, track_width))
        content_width = width - self.ACTION_STATUS_PADDING * 2
        height = self.ACTION_STATUS_PADDING * 2
        for index, text in enumerate(lines):
            font = self._text_font() if index == 0 else self._caption_font()
            height += self._measure_text(text, content_width, font).height()
            if index < len(lines) - 1:
                height += self.ACTION_STATUS_LINE_GAP
        return QRect(x, y, width, height)

    def _confirmation_layout(self, x: int, y: int, track_width: int, preview: dict) -> tuple[QRect, QRect, QRect]:
        width = min(self.ACTION_CARD_MAX_WIDTH, max(240, track_width))
        content_width = width - self.ACTION_CARD_PADDING * 2
        operation = str(preview.get("operation") or "发送消息").strip() or "发送消息"
        target = str(preview.get("target") or "目标联系人").strip() or "目标联系人"
        content = str(preview.get("content") or "").strip()
        line_specs = [
            (operation, self._text_font()),
            (f"收件人：{target}", self._caption_font()),
            (f"内容：{content}" if content else "内容：", self._text_font()),
            ("这是会产生外部影响的操作，确认后才会发送。", self._caption_font()),
        ]
        text_height = sum(self._measure_text(text, content_width, font).height() for text, font in line_specs)
        text_height += 6 * (len(line_specs) - 1)
        height = self.ACTION_CARD_PADDING * 2 + text_height + 8 + self.ACTION_BUTTON_HEIGHT
        rect = QRect(x, y, width, height)
        confirm_rect = QRect(
            rect.right() - self.ACTION_CARD_PADDING - self.ACTION_BUTTON_WIDTH + 1,
            rect.bottom() - self.ACTION_CARD_PADDING - self.ACTION_BUTTON_HEIGHT + 1,
            self.ACTION_BUTTON_WIDTH,
            self.ACTION_BUTTON_HEIGHT,
        )
        cancel_rect = QRect(
            confirm_rect.x() - self.ACTION_BUTTON_GAP - self.ACTION_BUTTON_WIDTH,
            confirm_rect.y(),
            self.ACTION_BUTTON_WIDTH,
            self.ACTION_BUTTON_HEIGHT,
        )
        return rect, cancel_rect, confirm_rect

    def _image_rect(self, track_rect: QRect, message: AIMessage) -> QRect:
        del message
        width = min(self.IMAGE_WIDTH, max(96, track_rect.width()))
        height = self.IMAGE_HEIGHT
        return QRect(track_rect.x(), track_rect.y(), width, height)

    def _offset_image_for_bubble(self, image_rect: QRect, bubble_rect: QRect) -> QRect:
        x = bubble_rect.x() + self.BUBBLE_PADDING_H
        y = bubble_rect.y() + self.BUBBLE_PADDING_V
        return QRect(x, y, image_rect.width(), image_rect.height())

    def _measure_text(self, text: str, max_width: int, font: QFont) -> QSize:
        if not text:
            return QSize(0, 0)
        _layout, size = self._build_text_layout(text, max_width, font)
        return size

    def _build_text_layout(self, text: str, max_width: int, font: QFont) -> tuple[QTextLayout, QSize]:
        layout = QTextLayout(text or "", font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        option.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.setTextOption(option)
        layout.beginLayout()
        y = 0.0
        width = 0.0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1, max_width))
            line.setPosition(QPointF(0, y))
            y += line.height()
            width = max(width, line.naturalTextWidth())
        layout.endLayout()
        metrics = QFontMetrics(font)
        return layout, QSize(max(1, math.ceil(width)), max(metrics.height(), math.ceil(y)))

    def _track_width(self, row_width: int) -> int:
        available = max(self.MIN_TRACK_WIDTH, int(row_width or 0) - self.TRACK_HORIZONTAL_MARGIN * 2)
        return max(self.MIN_TRACK_WIDTH, min(self.MAX_TRACK_WIDTH, available))

    def _message_display_text(self, message: AIMessage) -> str:
        text = str(message.content or "")
        if text:
            return text
        if self._is_user(message):
            return ""
        if dict((message.extra or {}).get("ai_action") or {}):
            return ""
        if message.status not in {AIMessageStatus.PENDING, AIMessageStatus.STREAMING}:
            return ""
        thinking = dict((message.extra or {}).get("ai_thinking") or {})
        state = str(thinking.get("state") or "").strip()
        labels = {
            "planning": "正在理解请求",
            "generating": "正在生成回复",
            "action": "正在执行操作",
        }
        label = labels.get(state, "正在处理")
        return f"{label}{self._animated_dots(self._animation_frame)}"

    @staticmethod
    def _message(index: QModelIndex) -> AIMessage | None:
        if not index.isValid():
            return None
        message = index.data(Qt.ItemDataRole.UserRole)
        return message if isinstance(message, AIMessage) else None

    @staticmethod
    def _is_last_row(index: QModelIndex) -> bool:
        model = index.model()
        return model is not None and index.row() == model.rowCount() - 1

    @staticmethod
    def _is_user(message: AIMessage) -> bool:
        return str(getattr(message.role, "value", message.role) or "") == AIMessageRole.USER.value

    @staticmethod
    def _text_font() -> QFont:
        font = QFont()
        font.setPixelSize(17)
        try:
            font.setFamilies(["Segoe UI", "Microsoft YaHei UI", "Segoe UI Emoji", "Noto Color Emoji"])
        except AttributeError:
            font.setFamily("Segoe UI")
        return font

    @staticmethod
    def _caption_font() -> QFont:
        font = QFont()
        font.setPixelSize(13)
        try:
            font.setFamilies(["Segoe UI", "Microsoft YaHei UI", "Segoe UI Emoji", "Noto Color Emoji"])
        except AttributeError:
            font.setFamily("Segoe UI")
        return font

    @staticmethod
    def _button_font() -> QFont:
        font = QFont()
        font.setPixelSize(13)
        font.setBold(True)
        return font

    @staticmethod
    def _first_image_attachment(extra: dict | None) -> dict | None:
        for attachment in list((extra or {}).get("attachments") or []):
            if isinstance(attachment, dict) and str(attachment.get("type") or "").strip().lower() == "image":
                return dict(attachment)
        return None

    @classmethod
    def _footer_text(cls, message: AIMessage) -> str:
        if bool((message.extra or {}).get("truncated")):
            return tr(
                "ai_assistant.message.truncated_hint",
                "内容较长，已截断。继续提问可接着往下说。",
            )
        if message.status == AIMessageStatus.FAILED:
            return tr(
                "ai_assistant.message.failed_hint",
                "本次生成未完成。你可以继续追问，或稍后再试。",
            )
        return cls._action_footer_text(message.extra)

    @staticmethod
    def _confirmation_preview(extra: dict | None) -> dict:
        action = dict((extra or {}).get("ai_action") or {})
        waiting = dict(action.get("waiting") or {})
        preview = waiting.get("preview") if isinstance(waiting.get("preview"), dict) else {}
        should_show = (
            str(action.get("state") or "").strip() == "waiting_confirmation"
            and str(waiting.get("type") or "").strip() == "confirmation"
            and bool(preview)
        )
        return dict(preview) if should_show else {}

    @staticmethod
    def _action_footer_text(extra: dict | None) -> str:
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

    @classmethod
    def _action_status_summary_text(cls, extra: dict | None, *, animation_frame: int = 0) -> str:
        action = dict((extra or {}).get("ai_action") or {})
        if not action:
            return ""
        state = str(action.get("state") or "").strip()
        if state in {"done", "cancelled"}:
            return ""
        steps = [item for item in list(action.get("steps") or []) if isinstance(item, dict)]
        events = [item for item in list(action.get("events") or []) if isinstance(item, dict)]
        if state == "failed":
            current = cls._current_action_step_summary(
                steps,
                events,
                current_step_id=str(action.get("current_step_id") or ""),
                preferred_states={"failed"},
            )
            title = current[1] if current else ""
            hint = cls._action_failure_hint(action, events)
            if title and hint:
                return f"执行失败：{title} · {hint}"
            if title:
                return f"执行失败：{title}"
            return f"执行失败：{hint or '操作未完成'}"
        current = cls._current_action_step_summary(
            steps,
            events,
            current_step_id=str(action.get("current_step_id") or ""),
            preferred_states={"running", "retrying", "waiting_confirmation", "waiting_clarification"},
        )
        if current is None and steps:
            current = cls._current_action_step_summary(
                steps,
                events,
                current_step_id="",
                preferred_states={"pending"},
            )
        if current is None:
            label = "正在处理" if state == "running" else cls._step_state_label(state)
            return f"{label}{cls._animated_dots(animation_frame)}"
        step_state, title = current
        label = cls._step_state_label(step_state)
        if state == "running" and step_state in {"running", "started"}:
            label = f"正在执行{cls._animated_dots(animation_frame)}"
        completed = cls._completed_step_count(steps, events)
        total = len(steps)
        suffix = f" · {completed}/{total}" if state == "running" and total > 0 else ""
        return f"{label}：{title}{suffix}"

    @classmethod
    def _action_status_text(cls, extra: dict | None) -> str:
        action = dict((extra or {}).get("ai_action") or {})
        if not action:
            return ""
        state = str(action.get("state") or "").strip()
        if state in {"done", "cancelled"}:
            return ""
        steps = [item for item in list(action.get("steps") or []) if isinstance(item, dict)]
        events = [item for item in list(action.get("events") or []) if isinstance(item, dict)]
        lines: list[str] = []
        for step in steps:
            step_id = str(step.get("id") or "").strip()
            event_state = cls._step_state_from_events(step_id, events)
            step_state = event_state or str(step.get("state") or "").strip()
            label = cls._step_state_label(step_state)
            display_text = str(step.get("display_text") or "").strip()
            explanation = str(step.get("explanation") or "").strip()
            action_name = str(step.get("action") or "").strip()
            title = display_text or explanation or action_name
            if not title:
                continue
            if explanation and display_text and explanation != display_text:
                title = f"{title}（{explanation}）"
            lines.append(f"{label}：{title}")
        if not lines:
            for event in events[-4:]:
                step_state = cls._state_from_event(event)
                label = cls._step_state_label(step_state)
                title = str(event.get("message") or event.get("action") or "").strip()
                if title and title != "plan":
                    lines.append(f"{label}：{title}")
        if not lines and state == "failed":
            hint = cls._action_failure_hint(action, events)
            if hint:
                lines.append(f"执行失败：{hint}")
        return "\n".join(lines[:6])

    @classmethod
    def _current_action_step_summary(
        cls,
        steps: list[dict],
        events: list[dict],
        *,
        current_step_id: str,
        preferred_states: set[str],
    ) -> tuple[str, str] | None:
        normalized_current = str(current_step_id or "").strip()
        candidates: list[tuple[str, dict]] = []
        for step in steps:
            step_id = str(step.get("id") or "").strip()
            event_state = cls._step_state_from_events(step_id, events)
            step_state = event_state or str(step.get("state") or "").strip()
            candidates.append((step_state, step))
        if normalized_current:
            for step_state, step in candidates:
                if str(step.get("id") or "").strip() == normalized_current:
                    title = cls._step_title(step)
                    if title:
                        return step_state or "pending", title
        for step_state, step in candidates:
            if step_state in preferred_states:
                title = cls._step_title(step)
                if title:
                    return step_state, title
        return None

    @classmethod
    def _completed_step_count(cls, steps: list[dict], events: list[dict]) -> int:
        count = 0
        for step in steps:
            step_id = str(step.get("id") or "").strip()
            state = cls._step_state_from_events(step_id, events) or str(step.get("state") or "").strip()
            if state in {"done", "completed"}:
                count += 1
        return count

    @staticmethod
    def _step_title(step: dict) -> str:
        display_text = str(step.get("display_text") or "").strip()
        explanation = str(step.get("explanation") or "").strip()
        action_name = str(step.get("action") or "").strip()
        return display_text or explanation or action_name

    @classmethod
    def _action_failure_hint(cls, action: dict, events: list[dict]) -> str:
        error_code = str(action.get("error_code") or "").strip()
        if not error_code:
            for event in reversed(events):
                error_code = str(event.get("error_code") or "").strip()
                if error_code:
                    break
        resource_limit = ""
        for event in reversed(events):
            resource_limit = str(event.get("resource_limit") or "").strip()
            if resource_limit:
                break
        if (
            error_code == "RESOURCE_LIMIT_EXCEEDED"
            or resource_limit
            or any(str(event.get("type") or "").strip() == "plan_resource_limit_exceeded" for event in events)
        ):
            return "结果过多，已停止执行"
        labels = {
            "ACTION_NOT_FOUND": "当前不支持这个操作",
            "PLAN_SCHEMA_INVALID": "操作计划结构有问题",
            "PLANNER_CONTRACT_INVALID": "操作计划结构不安全",
            "PERMISSION_DENIED": "权限不允许访问",
            "SESSION_NOT_FOUND": "没有找到可发送的会话",
            "ACTION_TIMEOUT": "操作超时",
            "ACTION_FAILED": "操作执行失败",
            "ARG_REFERENCE_INVALID": "操作参数不完整",
            "ARG_SCHEMA_INVALID": "操作参数不完整",
            "OUTPUT_SCHEMA_INVALID": "操作结果格式异常",
            "TEMP_RESULT_EXPIRED": "临时结果已过期",
            "expired_confirmation": "确认已过期",
        }
        return labels.get(error_code, "操作未完成" if error_code else "")

    @classmethod
    def _step_state_from_events(cls, step_id: str, events: list[dict]) -> str:
        normalized_step_id = str(step_id or "").strip()
        if not normalized_step_id:
            return ""
        for event in reversed(events):
            if str(event.get("step_id") or "").strip() == normalized_step_id:
                return cls._state_from_event(event)
        return ""

    @staticmethod
    def _state_from_event(event: dict) -> str:
        event_type = str(event.get("type") or "").strip()
        state = str(event.get("state") or "").strip()
        if event_type == "step_completed" or state == "completed":
            return "done"
        if event_type == "step_failed" or state == "failed":
            return "failed"
        if event_type == "step_waiting_confirmation" or state == "waiting_confirmation":
            return "waiting_confirmation"
        if event_type == "step_waiting_clarification" or state == "waiting_clarification":
            return "waiting_clarification"
        if event_type == "step_started" or state == "started":
            return "running"
        if event_type == "step_retrying" or state == "retrying":
            return "retrying"
        if event_type == "plan_cancelled" or state == "cancelled":
            return "cancelled"
        return state

    @staticmethod
    def _step_state_label(state: str) -> str:
        labels = {
            "running": "正在执行",
            "started": "正在执行",
            "done": "已完成",
            "completed": "已完成",
            "waiting_confirmation": "等待确认",
            "waiting_clarification": "等待补充",
            "failed": "执行失败",
            "retrying": "正在重试",
            "cancelled": "已取消",
            "pending": "待执行",
        }
        return labels.get(str(state or "").strip(), "待执行")

    @staticmethod
    def _animated_dots(frame: int) -> str:
        return "." * (max(0, int(frame or 0)) % 4)
