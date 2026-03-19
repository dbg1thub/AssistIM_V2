"""Shared attachment card drawing helpers."""

from __future__ import annotations

import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter

from client.models.message import MessageType


ATTACHMENT_CARD_WIDTH = 236
ATTACHMENT_CARD_HEIGHT = 76


def attachment_card_size() -> tuple[int, int]:
    """Return the unified preview card size used by input and chat list."""
    return ATTACHMENT_CARD_WIDTH, ATTACHMENT_CARD_HEIGHT


def format_attachment_file_size(file_path: str, fallback_size=None) -> str:
    """Return a human-friendly file size string from path or fallback bytes."""
    size_value = None
    if fallback_size not in (None, ""):
        try:
            size_value = float(fallback_size)
        except (TypeError, ValueError):
            size_value = None

    if file_path:
        try:
            if size_value is None:
                size_value = float(os.path.getsize(file_path))
        except OSError:
            size_value = None

    if size_value is None:
        return ""

    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    while size_value >= 1024 and unit_index < len(units) - 1:
        size_value /= 1024.0
        unit_index += 1

    if unit_index == 0:
        return f"{int(size_value)} {units[unit_index]}"
    return f"{size_value:.1f} {units[unit_index]}"


def attachment_icon_text(message_type: MessageType) -> str:
    """Return the single-letter attachment type marker."""
    if message_type == MessageType.IMAGE:
        return "I"
    if message_type == MessageType.VIDEO:
        return "V"
    return "F"


def draw_attachment_card(
    painter: QPainter,
    rect,
    *,
    message_type: MessageType,
    display_name: str,
    file_path: str = "",
    fallback_size=None,
    dark: bool,
) -> None:
    """Draw the shared attachment preview card."""
    card_rect = QRectF(rect)
    bg = QColor(255, 255, 255, 18) if dark else QColor(0, 0, 0, 10)
    fg = QColor(255, 255, 255, 225) if dark else QColor(20, 20, 20, 220)
    sub = QColor(255, 255, 255, 150) if dark else QColor(30, 30, 30, 150)
    accent = QColor(255, 255, 255, 36) if dark else QColor(0, 0, 0, 18)
    content_rect = card_rect.adjusted(10, 8, -10, -8)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(bg)
    painter.drawRoundedRect(card_rect.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

    icon_rect = QRectF(content_rect.left(), content_rect.center().y() - 26, 52, 52)
    painter.setBrush(accent)
    painter.drawRoundedRect(icon_rect, 8, 8)
    painter.setPen(fg)
    icon_font = QFont(painter.font())
    icon_font.setPixelSize(20)
    icon_font.setBold(True)
    painter.setFont(icon_font)
    painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, attachment_icon_text(message_type))

    text_left = icon_rect.right() + 10
    text_width = max(0.0, content_rect.right() - text_left)
    title_rect = QRectF(text_left, content_rect.top() + 2, text_width, 20)
    size_rect = QRectF(text_left, content_rect.bottom() - 16, text_width, 14)

    title_font = QFont(painter.font())
    title_font.setPixelSize(15)
    title_font.setBold(False)
    painter.setFont(title_font)
    painter.setPen(fg)
    metrics = painter.fontMetrics()
    title = metrics.elidedText(display_name or "Attachment", Qt.TextElideMode.ElideRight, int(title_rect.width()))
    painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

    size_font = QFont(painter.font())
    size_font.setPixelSize(11)
    size_font.setBold(False)
    painter.setFont(size_font)
    painter.setPen(sub)
    painter.drawText(
        size_rect,
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        format_attachment_file_size(file_path, fallback_size) or "Unknown size",
    )
