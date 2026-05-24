"""Small pill badge with optional icon, text, and persistent checked state."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget
from qfluentwidgets import FluentIconBase, isDarkTheme

from client.core.app_icons import CollectionIcon


class _ToggleBadgeIcon(QWidget):
    """Paint a badge icon with the color resolved from the parent badge state."""

    def __init__(self, badge: "ToggleBadge") -> None:
        super().__init__(badge)
        self._badge = badge
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def sizeHint(self) -> QSize:
        return self._badge.iconSize()

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event) -> None:
        icon = self._badge.icon()
        if icon is None:
            return

        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        icon_rect = self.rect()
        if isinstance(icon, FluentIconBase):
            icon.render(painter, icon_rect, fill=self._badge._icon_color())
        elif isinstance(icon, QIcon):
            icon.paint(painter, icon_rect)


class ToggleBadge(QFrame):
    """Adaptive action badge with optional persistent selection state."""

    clicked = Signal()
    toggled = Signal(bool)

    _HORIZONTAL_PADDING = 8
    _VERTICAL_PADDING = 3
    _ICON_TEXT_SPACING = 3
    _DEFAULT_ICON_SIZE = QSize(12, 12)

    def __init__(
        self,
        text: str = "",
        icon: FluentIconBase | QIcon | str | None = None,
        parent=None,
        *,
        checked: bool = False,
        checkable: bool = True,
        hover_enabled: bool = True,
        press_enabled: bool = True,
        show_border: bool = True,
        icon_size: QSize | int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ToggleBadge")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._icon: FluentIconBase | QIcon | None = None
        self._icon_size = self._coerce_icon_size(icon_size)
        self._checked = bool(checked)
        self._checkable = bool(checkable)
        self._pressed = False
        self._mouse_down = False
        self._hover_enabled = bool(hover_enabled)
        self._press_enabled = bool(press_enabled)
        self._border_visible = bool(show_border)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            self._HORIZONTAL_PADDING,
            self._VERTICAL_PADDING,
            self._HORIZONTAL_PADDING,
            self._VERTICAL_PADDING,
        )
        layout.setSpacing(self._ICON_TEXT_SPACING)

        self.icon_widget = _ToggleBadgeIcon(self)
        self.icon_widget.setObjectName("ToggleBadgeIcon")
        self.icon_widget.setFixedSize(self._icon_size)
        layout.addWidget(self.icon_widget, 0, Qt.AlignmentFlag.AlignVCenter)

        self.text_label = QLabel(str(text or ""), self)
        self.text_label.setObjectName("ToggleBadgeText")
        self.text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.text_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.setIcon(icon)
        self._sync_visibility()
        self._sync_properties()

    def text(self) -> str:
        return self.text_label.text()

    def setText(self, text: str) -> None:
        self.text_label.setText(str(text or ""))
        self._sync_visibility()
        self.updateGeometry()

    def icon(self) -> FluentIconBase | QIcon | None:
        return self._icon

    def setIcon(self, icon: FluentIconBase | QIcon | str | None) -> None:
        if isinstance(icon, str):
            self._icon = CollectionIcon(icon)
        else:
            self._icon = icon
        self._sync_visibility()
        self.icon_widget.update()
        self.updateGeometry()

    def iconSize(self) -> QSize:
        return QSize(self._icon_size)

    def setIconSize(self, size: QSize | int) -> None:
        self._icon_size = self._coerce_icon_size(size)
        self.icon_widget.setFixedSize(self._icon_size)
        self.icon_widget.updateGeometry()
        self.updateGeometry()

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        next_checked = bool(checked)
        if self._checked == next_checked:
            return
        self._checked = next_checked
        self._sync_properties()
        self.icon_widget.update()
        self.updateGeometry()

    def isCheckable(self) -> bool:
        return self._checkable

    def setCheckable(self, checkable: bool) -> None:
        self._checkable = bool(checkable)

    def setHoverEnabled(self, enabled: bool) -> None:
        self._hover_enabled = bool(enabled)
        self._sync_properties()
        self.icon_widget.update()

    def isHoverEnabled(self) -> bool:
        return self._hover_enabled

    def setPressEnabled(self, enabled: bool) -> None:
        self._press_enabled = bool(enabled)
        if not self._press_enabled:
            self._pressed = False
        self._sync_properties()
        self.icon_widget.update()

    def isPressEnabled(self) -> bool:
        return self._press_enabled

    def setBorderVisible(self, visible: bool) -> None:
        self._border_visible = bool(visible)
        self._sync_properties()
        self.updateGeometry()

    def isBorderVisible(self) -> bool:
        return self._border_visible

    def sizeHint(self) -> QSize:
        return self._content_size()

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._has_inner_fill():
            inner_rect = QRectF(self.rect()).adjusted(0.8, 0.8, -0.8, -0.8)
            inner_radius = min(10.0, inner_rect.height() / 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._inner_fill_color())
            painter.drawRoundedRect(inner_rect, inner_radius, inner_radius)

        if not self._border_visible:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self._border_color(), 1))
        border_rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = min(10.0, border_rect.height() / 2)
        painter.drawRoundedRect(border_rect, radius, radius)

    def enterEvent(self, event) -> None:
        self.icon_widget.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._mouse_down = False
        self._set_pressed(False)
        self.icon_widget.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._mouse_down = True
            self._set_pressed(self._press_enabled)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        was_down = self._mouse_down
        self._mouse_down = False
        self._set_pressed(False)
        if was_down and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            if self._checkable:
                self._checked = not self._checked
                self._sync_properties()
                self.toggled.emit(self._checked)
            self.clicked.emit()
            self.icon_widget.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _content_size(self) -> QSize:
        has_icon = self._icon is not None
        has_text = bool(self.text_label.text())
        text_size = self.text_label.sizeHint() if has_text else QSize(0, 0)
        spacing = self._ICON_TEXT_SPACING if has_icon and has_text else 0
        border_width = 1 if self._border_visible else 0
        width = (
            self._HORIZONTAL_PADDING * 2
            + border_width * 2
            + (self._icon_size.width() if has_icon else 0)
            + spacing
            + text_size.width()
        )
        height = self._VERTICAL_PADDING * 2 + border_width * 2 + max(
            self._icon_size.height() if has_icon else 0,
            text_size.height(),
        )
        return QSize(max(1, width), max(1, height))

    def _sync_visibility(self) -> None:
        self.icon_widget.setVisible(self._icon is not None)
        self.text_label.setVisible(bool(self.text_label.text()))

    def _sync_properties(self) -> None:
        self.setProperty("checked", self._checked)
        self.setProperty("pressed", self._pressed)
        self.setProperty("hoverEnabled", self._hover_enabled)
        self.setProperty("pressEnabled", self._press_enabled)
        self.setProperty("borderVisible", self._border_visible)
        self._repolish()

    def _set_pressed(self, pressed: bool) -> None:
        next_pressed = bool(pressed)
        if self._pressed == next_pressed:
            return
        self._pressed = next_pressed
        self._sync_properties()
        self.icon_widget.update()

    def _repolish(self) -> None:
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        style.unpolish(self.text_label)
        style.polish(self.text_label)
        self.update()
        self.text_label.update()

    def _icon_color(self) -> str:
        dark = isDarkTheme()
        if self._checked:
            return "#FCA5A5" if dark else "#791F1F"
        if self._pressed and self._press_enabled:
            return "#F1F5F9" if dark else "#111827"
        if self.underMouse() and self._hover_enabled:
            return "#F8FAFC" if dark else "#111827"
        return "#D8D8D8" if dark else "#5F5F5F"

    def _has_inner_fill(self) -> bool:
        return bool(
            self._checked
            or (self._pressed and self._press_enabled)
            or (self.underMouse() and self._hover_enabled)
        )

    def _inner_fill_color(self) -> QColor:
        dark = isDarkTheme()
        if self._checked:
            return QColor(252, 165, 165, 42) if dark else QColor(224, 102, 102, 34)
        if self._pressed and self._press_enabled:
            return QColor(255, 255, 255, 36) if dark else QColor(17, 24, 39, 30)
        if self.underMouse() and self._hover_enabled:
            return QColor(255, 255, 255, 30) if dark else QColor(17, 24, 39, 24)
        return QColor(0, 0, 0, 0)

    def _border_color(self) -> QColor:
        dark = isDarkTheme()
        if self._checked:
            return QColor(252, 165, 165, 150) if dark else QColor(224, 102, 102, 210)
        if self._pressed and self._press_enabled:
            return QColor(255, 255, 255, 118) if dark else QColor(17, 24, 39, 112)
        if self.underMouse() and self._hover_enabled:
            return QColor(255, 255, 255, 104) if dark else QColor(17, 24, 39, 96)
        return QColor(255, 255, 255, 88) if dark else QColor(17, 24, 39, 82)

    @staticmethod
    def _coerce_icon_size(size: QSize | int | None) -> QSize:
        if isinstance(size, QSize):
            return QSize(max(1, size.width()), max(1, size.height()))
        if isinstance(size, int):
            value = max(1, size)
            return QSize(value, value)
        return QSize(ToggleBadge._DEFAULT_ICON_SIZE)
