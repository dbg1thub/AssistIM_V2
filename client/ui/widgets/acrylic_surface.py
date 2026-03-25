"""Reusable acrylic-style surfaces built on top of QFluentWidgets components."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget
from qfluentwidgets import InfoBar, isDarkTheme
from qfluentwidgets.components.widgets.acrylic_label import AcrylicBrush


class AcrylicBackdrop(QWidget):
    """Blurred translucent backdrop that can sit behind Fluent content."""

    def __init__(self, parent: QWidget | None = None, *, radius: int = 16) -> None:
        super().__init__(parent)
        self._radius = max(0, int(radius))
        self._brush = AcrylicBrush(self, 30)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.lower()

    def set_radius(self, radius: int) -> None:
        self._radius = max(0, int(radius))
        self.update()

    def _clip_path(self) -> QPainterPath:
        path = QPainterPath()
        rect = self.rect().adjusted(0, 0, -1, -1)
        path.addRoundedRect(rect, self._radius, self._radius)
        return path

    def _colors(self) -> tuple[QColor, QColor, QColor]:
        if isDarkTheme():
            return (
                QColor(36, 36, 36, 208),
                QColor(0, 0, 0, 0),
                QColor(255, 255, 255, 26),
            )
        return (
            QColor(255, 255, 255, 190),
            QColor(255, 255, 255, 0),
            QColor(0, 0, 0, 20),
        )

    def _paint_fallback(self, border_color: QColor) -> None:
        tint_color, _luminosity_color, _ = self._colors()
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        path = self._clip_path()
        painter.fillPath(path, tint_color)
        painter.setPen(QPen(border_color, 1))
        painter.drawPath(path)

    def paintEvent(self, event) -> None:
        path = self._clip_path()
        tint_color, luminosity_color, border_color = self._colors()
        painted = False

        if self._brush is not None and getattr(self._brush, "isAvailable", lambda: True)():
            try:
                global_pos = self.mapToGlobal(QPoint(0, 0))
                self._brush.grabImage(QRect(global_pos, self.size()))
                self._brush.setClipPath(path)
                self._brush.tintColor = tint_color
                self._brush.luminosityColor = luminosity_color
                self._brush.paint()
                painted = True
            except Exception:
                painted = False

        if not painted:
            self._paint_fallback(border_color)
            return

        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        painter.setPen(QPen(border_color, 1))
        painter.drawPath(path)


class _BackdropEventFilter(QObject):
    """Keep one backdrop aligned with its target widget."""

    def __init__(self, target: QWidget, backdrop: AcrylicBackdrop) -> None:
        super().__init__(target)
        self._target = target
        self._backdrop = backdrop

    def _sync(self) -> None:
        if self._backdrop.parentWidget() is not self._target:
            return
        self._backdrop.setGeometry(self._target.rect())
        self._backdrop.lower()
        if self._backdrop.isHidden():
            self._backdrop.show()
        self._backdrop.update()

    def eventFilter(self, watched: QObject, event) -> bool:
        if watched is self._target and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Move,
            QEvent.Type.Show,
            QEvent.Type.WindowStateChange,
            QEvent.Type.PaletteChange,
        }:
            self._sync()
        return False


def attach_acrylic_backdrop(target: QWidget, *, radius: int = 16) -> AcrylicBackdrop:
    """Attach or update one acrylic backdrop for a widget."""
    backdrop = getattr(target, "_assistim_acrylic_backdrop", None)
    if isinstance(backdrop, AcrylicBackdrop):
        backdrop.set_radius(radius)
        backdrop.setGeometry(target.rect())
        backdrop.lower()
        backdrop.show()
        backdrop.update()
        return backdrop

    backdrop = AcrylicBackdrop(target, radius=radius)
    backdrop.setGeometry(target.rect())
    backdrop.show()
    backdrop.lower()
    target._assistim_acrylic_backdrop = backdrop

    event_filter = _BackdropEventFilter(target, backdrop)
    target.installEventFilter(event_filter)
    target._assistim_acrylic_backdrop_filter = event_filter
    return backdrop


def configure_acrylic_infobar(info_bar: InfoBar, *, radius: int = 14) -> InfoBar:
    """Apply an acrylic-style backdrop to an InfoBar instance."""
    info_bar.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    if hasattr(info_bar, "setCustomBackgroundColor"):
        info_bar.setCustomBackgroundColor(QColor(255, 255, 255, 0), QColor(0, 0, 0, 0))
    attach_acrylic_backdrop(info_bar, radius=radius)
    return info_bar
