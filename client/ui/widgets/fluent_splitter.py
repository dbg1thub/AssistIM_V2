"""Custom splitter with a stable 1px indicator line."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSplitter, QSplitterHandle
from qfluentwidgets import isDarkTheme


class FluentSplitterHandle(QSplitterHandle):
    """Splitter handle that keeps a constant hairline during hover and drag."""

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter):
        super().__init__(orientation, parent)
        self._hovered = False
        self._pressed = False
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._pressed = True
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        if isDarkTheme():
            color = QColor(255, 255, 255, 56 if self._pressed else 44 if self._hovered else 34)
        else:
            color = QColor(15, 23, 42, 54 if self._pressed else 40 if self._hovered else 28)

        pen = QPen(color)
        pen.setWidth(0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self.orientation() == Qt.Orientation.Horizontal:
            x = self.width() / 2
            painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        else:
            y = self.height() / 2
            painter.drawLine(QPointF(0, y), QPointF(self.width(), y))


class FluentSplitter(QSplitter):
    """Splitter that uses the stable custom handle."""

    def createHandle(self) -> QSplitterHandle:
        return FluentSplitterHandle(self.orientation(), self)
