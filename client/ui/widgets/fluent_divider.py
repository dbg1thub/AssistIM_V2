"""Fluent-style divider lines for lightweight panel separation."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget
from qfluentwidgets import isDarkTheme


class FluentDivider(QWidget):
    """A subtle 1px divider with full-width and inset variants."""

    DEFAULT_INSET = 14
    FULL = "full"
    LEFT_FULL = "left_full"
    RIGHT_FULL = "right_full"
    INSET = "inset"

    def __init__(
        self,
        parent=None,
        *,
        variant: str = RIGHT_FULL,
        inset: int = DEFAULT_INSET,
        left_inset: int | None = None,
        right_inset: int | None = None,
    ):
        super().__init__(parent)
        self._variant = self.RIGHT_FULL
        self._inset = max(0, int(inset))
        self._left_inset_override = max(0, int(left_inset)) if left_inset is not None else None
        self._right_inset_override = max(0, int(right_inset)) if right_inset is not None else None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(1)
        self.setVariant(variant)

    def variant(self) -> str:
        return self._variant

    def setVariant(self, variant: str) -> None:
        normalized = str(variant or self.RIGHT_FULL).strip().lower()
        if normalized not in {self.FULL, self.LEFT_FULL, self.RIGHT_FULL, self.INSET}:
            normalized = self.RIGHT_FULL
        self._variant = normalized
        self.update()

    def inset(self) -> int:
        return self._inset

    def setInset(self, inset: int) -> None:
        self._inset = max(0, int(inset))
        self.update()

    def leftInset(self) -> int:
        return self._resolve_insets()[0]

    def rightInset(self) -> int:
        return self._resolve_insets()[1]

    def setLeftInset(self, inset: int | None) -> None:
        self._left_inset_override = max(0, int(inset)) if inset is not None else None
        self.update()

    def setRightInset(self, inset: int | None) -> None:
        self._right_inset_override = max(0, int(inset)) if inset is not None else None
        self.update()

    def setInsets(self, left: int | None = None, right: int | None = None) -> None:
        self.setLeftInset(left)
        self.setRightInset(right)

    def _resolve_insets(self) -> tuple[int, int]:
        left_inset = self._inset if self._variant in {self.RIGHT_FULL, self.INSET} else 0
        right_inset = self._inset if self._variant in {self.LEFT_FULL, self.INSET} else 0
        if self._left_inset_override is not None:
            left_inset = self._left_inset_override
        if self._right_inset_override is not None:
            right_inset = self._right_inset_override
        return left_inset, right_inset

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        if isDarkTheme():
            color = QColor(255, 255, 255, 34)
        else:
            color = QColor(15, 23, 42, 28)

        left_inset, right_inset = self._resolve_insets()
        left = float(left_inset)
        right = float(max(left, self.width() - right_inset))
        y = self.height() / 2

        pen = QPen(color)
        pen.setWidth(0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(left, y), QPointF(right, y))
