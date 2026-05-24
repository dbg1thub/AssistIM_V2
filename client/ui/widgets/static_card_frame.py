"""Non-interactive static card container."""

from __future__ import annotations

from PySide6.QtCore import Property, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame
from qfluentwidgets import isDarkTheme, qconfig


class StaticCardFrame(QFrame):
    """A static card-style frame for outer containers.

    This keeps the standard card background and border appearance without
    hover, press, click, or background animation behavior.
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._borderRadius = 6
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

        radius = self.borderRadius

        painter.setPen(QColor(0, 0, 0, 50) if isDarkTheme() else QColor(0, 0, 0, 19))
        painter.setBrush(self._normalBackgroundColor())
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(rect, radius, radius)

    borderRadius = Property(int, getBorderRadius, setBorderRadius)
