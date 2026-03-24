"""Fluent-style divider lines for lightweight panel separation."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget
from qfluentwidgets import isDarkTheme


class FluentDivider(QWidget):
    """A subtle 1px divider with full-width and inset variants."""

    FULL = "full"
    INSET = "inset"

    def __init__(self, parent=None, *, variant: str = FULL, inset: int = 14):
        super().__init__(parent)
        self._variant = self.FULL
        self._inset = max(0, int(inset))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(1)
        self.setVariant(variant)

    def variant(self) -> str:
        return self._variant

    def setVariant(self, variant: str) -> None:
        normalized = str(variant or self.FULL).strip().lower()
        if normalized not in {self.FULL, self.INSET}:
            normalized = self.FULL
        self._variant = normalized
        self.update()

    def inset(self) -> int:
        return self._inset

    def setInset(self, inset: int) -> None:
        self._inset = max(0, int(inset))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        if isDarkTheme():
            color = QColor(255, 255, 255, 34)
        else:
            color = QColor(15, 23, 42, 28)

        left = float(self._inset if self._variant == self.INSET else 0)
        right = float(max(left, self.width() - (self._inset if self._variant == self.INSET else 0)))
        y = self.height() / 2

        pen = QPen(color)
        pen.setWidth(0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(left, y), QPointF(right, y))
