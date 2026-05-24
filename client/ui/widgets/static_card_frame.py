"""Non-interactive static card container."""

from __future__ import annotations

from PySide6.QtCore import Property, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QFrame
from qfluentwidgets import isDarkTheme, qconfig


class StaticCardFrame(QFrame):
    """A static card-style frame for outer containers.

    This keeps the standard card background and border appearance without
    hover, press, click, or background animation behavior.
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._borderRadius = 5
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        qconfig.themeChanged.connect(self.update)

    def _normalBackgroundColor(self) -> QColor:
        return QColor(255, 255, 255, 13 if isDarkTheme() else 170)

    def getBorderRadius(self) -> int:
        return self._borderRadius

    def setBorderRadius(self, radius: int) -> None:
        self._borderRadius = int(radius)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing)

        width, height = self.width(), self.height()
        radius = self.borderRadius
        diameter = 2 * radius

        top_path = QPainterPath()
        top_path.arcMoveTo(1, height - diameter - 1, diameter, diameter, 240)
        top_path.arcTo(1, height - diameter - 1, diameter, diameter, 225, -60)
        top_path.lineTo(1, radius)
        top_path.arcTo(1, 1, diameter, diameter, -180, -90)
        top_path.lineTo(width - radius, 1)
        top_path.arcTo(width - diameter - 1, 1, diameter, diameter, 90, -90)
        top_path.lineTo(width - 1, height - radius)
        top_path.arcTo(width - diameter - 1, height - diameter - 1, diameter, diameter, 0, -60)

        top_border_color = QColor(255, 255, 255, 18) if isDarkTheme() else QColor(0, 0, 0, 15)
        painter.strokePath(top_path, top_border_color)

        bottom_path = QPainterPath()
        bottom_path.arcMoveTo(1, height - diameter - 1, diameter, diameter, 240)
        bottom_path.arcTo(1, height - diameter - 1, diameter, diameter, 240, 30)
        bottom_path.lineTo(width - radius - 1, height - 1)
        bottom_path.arcTo(width - diameter - 1, height - diameter - 1, diameter, diameter, 270, 30)
        painter.strokePath(bottom_path, top_border_color)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._normalBackgroundColor())
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(rect, radius, radius)

    borderRadius = Property(int, getBorderRadius, setBorderRadius)
