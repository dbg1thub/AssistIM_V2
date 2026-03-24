"""Custom navigation user card variants used by the main window."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QPainter

from qfluentwidgets import NavigationUserCard


class RegularWeightNavigationUserCard(NavigationUserCard):
    """Navigation user card that keeps both title and subtitle at regular weight."""

    def _drawText(self, painter: QPainter) -> None:
        text_x = 16 + int(self.avatar.radius * 2) + 12
        text_width = self.width() - text_x - 16

        title_font = QFont(self.font())
        title_font.setPixelSize(self._titleSize)
        title_font.setBold(False)
        title_font.setWeight(QFont.Weight.Normal)
        painter.setFont(title_font)

        title_color = self.textColor()
        title_color.setAlpha(int(255 * self._textOpacity))
        painter.setPen(title_color)

        title_y = self.height() // 2 - 2
        painter.drawText(
            QRectF(text_x, 0, text_width, title_y),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
            self._title,
        )

        if not self._subtitle:
            return

        subtitle_font = QFont(self.font())
        subtitle_font.setPixelSize(self._subtitleSize)
        subtitle_font.setBold(False)
        subtitle_font.setWeight(QFont.Weight.Normal)
        painter.setFont(subtitle_font)

        subtitle_color = self.subtitleColor or self.textColor()
        subtitle_color.setAlpha(int(150 * self._textOpacity))
        painter.setPen(subtitle_color)

        subtitle_y = self.height() // 2 + 2
        painter.drawText(
            QRectF(text_x, subtitle_y, text_width, self.height() - subtitle_y),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            self._subtitle,
        )
