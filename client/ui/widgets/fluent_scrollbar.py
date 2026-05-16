"""Fluent-style overlay scrollbar drawn directly on top of a QAbstractScrollArea.

Why this exists
---------------
``qfluentwidgets`` ships ``SmoothScrollDelegate`` which wraps the native
scrollbars with a custom ``SmoothScrollBar``. The delegate adds wheel
interpolation that visibly degrades performance on long message lists, so the
chat panel and the AI assistant page have moved back to the native scrollbars
for actual scrolling. This widget keeps the *visual* style of the Fluent
scrollbar without hijacking the wheel pipeline:

- Hover-only: groove and handle are hidden when the parent is idle.
- No groove: the bar is just a slim rounded handle so the chat surface stays
  clean when the cursor is elsewhere.
- No arrow buttons: top/bottom carets are removed.
- Vertical only: callers force the native horizontal scrollbar off through the
  parent area; this widget never lays out a horizontal partner.
- Bottom inset: the chat surface keeps a floating composer overlay; we expose
  ``set_bottom_inset`` so the bar can stop above that overlay.

The widget mirrors the partner ``QScrollBar`` of the parent area so the actual
scrolling stays on Qt's optimized path. Only colours, hover animations and
geometry are owned here.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QTimer,
    Qt,
    Property,
    Signal,
)
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QWidget

from qfluentwidgets import isDarkTheme
from qfluentwidgets.common.config import qconfig


class FluentOverlayScrollBarDisplayMode(Enum):
    """Display mode for :class:`FluentOverlayScrollBar`."""

    ALWAYS = 0
    ON_HOVER = 1


# Colours sourced from ``qfluentwidgets.components.widgets.scroll_bar`` so the
# hover state visually matches the rest of the Fluent design system.
_LIGHT_HANDLE = QColor(0, 0, 0, 114)
_DARK_HANDLE = QColor(255, 255, 255, 139)

_HANDLE_THIN_WIDTH = 3
_HANDLE_THICK_WIDTH = 6
_BAR_TOTAL_WIDTH = 12
_BAR_RIGHT_INSET = 1  # 1px gutter so the bar does not touch the panel edge
_DEFAULT_TOP_INSET = 1
_DEFAULT_BOTTOM_INSET = 1
_HANDLE_MIN_HEIGHT = 30
_HANDLE_PADDING = 4  # space between handle and bar ends
_FADE_DURATION_MS = 150
_LEAVE_HIDE_DELAY_MS = 200
_SCROLL_IDLE_HIDE_DELAY_MS = 1500
_HANDLE_CHASE_DURATION_MS = 60


class _Handle(QWidget):
    """Slim rounded handle drawn inside :class:`FluentOverlayScrollBar`.

    The handle owns two independent animated states that the parent scrollbar
    drives separately:

    - ``opacity``: visibility, animated when the cursor enters / leaves the
      parent scroll area.
    - width: thickness, animated by the scrollbar itself only when the cursor
      enters / leaves the 12px overlay strip. The handle does not adjust its
      own width; the scrollbar mutates it through ``setFixedWidth`` so the two
      animations stay decoupled.
    """

    def __init__(self, parent: "FluentOverlayScrollBar") -> None:
        super().__init__(parent)
        self._opacity = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setFixedWidth(_HANDLE_THIN_WIDTH)

    def paintEvent(self, _event) -> None:
        if self._opacity <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        radius = self.width() / 2
        painter.setOpacity(self._opacity)
        painter.setBrush(_DARK_HANDLE if isDarkTheme() else _LIGHT_HANDLE)
        painter.drawRoundedRect(self.rect(), radius, radius)

    def get_opacity(self) -> float:
        return self._opacity

    def set_opacity(self, value: float) -> None:
        self._opacity = max(0.0, min(1.0, float(value)))
        self.update()

    opacity = Property(float, get_opacity, set_opacity)


class FluentOverlayScrollBar(QWidget):
    """Vertical Fluent-style scrollbar mirroring a parent's native scrollbar.

    Behaviour summary:

    - Default :class:`FluentOverlayScrollBarDisplayMode.ON_HOVER` mode: the bar
      stays hidden until the cursor enters the parent area (or the user is
      actively scrolling), then fades in for ``_FADE_DURATION_MS`` ms.
    - Wheel events are forwarded to the parent viewport untouched so Qt's
      native scroll math runs without any interpolation layer.
    - Click-on-track translates to ``pageStep`` jumps; click-and-drag on the
      handle scrolls proportionally to handle travel.
    - ``set_bottom_inset`` / ``set_top_inset`` shrink the bar height so it can
      stop above a floating composer overlay.
    """

    valueChanged = Signal(int)

    def __init__(
        self,
        parent: QAbstractScrollArea,
        *,
        mode: FluentOverlayScrollBarDisplayMode = FluentOverlayScrollBarDisplayMode.ON_HOVER,
    ) -> None:
        if not isinstance(parent, QAbstractScrollArea):
            raise TypeError("FluentOverlayScrollBar requires a QAbstractScrollArea parent")
        super().__init__(parent)

        self._partner = parent.verticalScrollBar()
        self._area = parent
        self._mode = mode
        self._force_hidden = False

        self._minimum = self._partner.minimum()
        self._maximum = self._partner.maximum()
        self._value = self._partner.value()
        self._page_step = max(1, self._partner.pageStep())

        self._is_pressed_handle = False
        self._press_offset_y = 0

        self._top_inset = _DEFAULT_TOP_INSET
        self._bottom_inset = _DEFAULT_BOTTOM_INSET

        self._handle = _Handle(self)
        self._fade_animation = QPropertyAnimation(self._handle, b"opacity", self)
        self._fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_animation.setDuration(_FADE_DURATION_MS)

        # Thickness animation is independent from visibility: the handle is
        # always 3px when the cursor sits inside the parent area but outside
        # the 12px overlay strip; it grows to 6px only when the cursor is on
        # the scrollbar itself.
        self._thickness = 0.0
        self._thickness_animation = QPropertyAnimation(self, b"thickness", self)
        self._thickness_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._thickness_animation.setDuration(_FADE_DURATION_MS)

        # Handle chase animation: when the viewport scrolls (partner value
        # changes), the handle smoothly follows instead of teleporting. This
        # gives a subtle "elastic" feel without delaying the actual content
        # scroll. Duration is kept very short (60ms) so fast consecutive wheel
        # events don't pile up visible lag.
        self._handle_target_y = _HANDLE_PADDING
        self._handle_chase_animation = QPropertyAnimation(self, b"handleY", self)
        self._handle_chase_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._handle_chase_animation.setDuration(_HANDLE_CHASE_DURATION_MS)

        self._leave_timer = QTimer(self)
        self._leave_timer.setSingleShot(True)
        self._leave_timer.timeout.connect(self._on_leave_timeout)

        self._scroll_idle_timer = QTimer(self)
        self._scroll_idle_timer.setSingleShot(True)
        self._scroll_idle_timer.timeout.connect(self._on_scroll_idle_timeout)

        self._connect_partner()

        # Native scrollbars are kept off; the overlay is the only visible
        # scrollbar. Both axes are turned off because the chat surfaces never
        # need a horizontal one.
        QAbstractScrollArea.setVerticalScrollBarPolicy(parent, Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        QAbstractScrollArea.setHorizontalScrollBarPolicy(parent, Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Watch parent enter/leave/resize and viewport hover events so the bar
        # follows the cursor's logical "in chat" state.
        parent.installEventFilter(self)
        viewport = parent.viewport()
        if viewport is not None:
            viewport.installEventFilter(self)

        try:
            qconfig.themeChanged.connect(self._on_theme_changed)
        except Exception:
            # Fallback: theme broadcast may not be wired in tests; subsequent
            # paints still pick up ``isDarkTheme()`` directly.
            pass

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)
        self._handle.setMouseTracking(True)

        self._update_geometry()
        self._refresh_handle_layout()
        self.setVisible(self._should_be_visible())
        if self._mode == FluentOverlayScrollBarDisplayMode.ALWAYS:
            self._fade_in()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_top_inset(self, inset: int) -> None:
        inset = max(0, int(inset))
        if inset == self._top_inset:
            return
        self._top_inset = inset
        self._update_geometry()
        self._refresh_handle_layout()

    def set_bottom_inset(self, inset: int) -> None:
        inset = max(0, int(inset))
        if inset == self._bottom_inset:
            return
        self._bottom_inset = inset
        self._update_geometry()
        self._refresh_handle_layout()

    def set_force_hidden(self, hidden: bool) -> None:
        self._force_hidden = bool(hidden)
        self.setVisible(self._should_be_visible())

    def set_display_mode(self, mode: FluentOverlayScrollBarDisplayMode) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        if mode == FluentOverlayScrollBarDisplayMode.ALWAYS:
            self._fade_in()
        else:
            self._fade_out()

    # ------------------------------------------------------------------
    # Partner sync
    # ------------------------------------------------------------------
    def _connect_partner(self) -> None:
        self._partner.rangeChanged.connect(self._on_partner_range_changed)
        self._partner.valueChanged.connect(self._on_partner_value_changed)

    def _on_partner_range_changed(self, minimum: int, maximum: int) -> None:
        self._minimum = minimum
        self._maximum = maximum
        self._page_step = max(1, self._partner.pageStep())
        self._refresh_handle_layout()
        self.setVisible(self._should_be_visible())

    def _on_partner_value_changed(self, value: int) -> None:
        self._value = value
        # During drag, the handle is positioned directly by mouseMoveEvent;
        # skip the chase animation to avoid fighting with the user's input.
        if self._is_pressed_handle:
            self._reposition_handle()
        else:
            self._animate_handle_to_target()
        # Active scrolling counts as "user interaction"; show the bar even when
        # the cursor is parked outside the area.
        if self._mode == FluentOverlayScrollBarDisplayMode.ON_HOVER:
            self._fade_in()
            self._scroll_idle_timer.start(_SCROLL_IDLE_HIDE_DELAY_MS)

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------
    def _update_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        width = _BAR_TOTAL_WIDTH
        x = max(0, parent.width() - width - _BAR_RIGHT_INSET)
        y = self._top_inset
        height = max(0, parent.height() - self._top_inset - self._bottom_inset)
        self.setGeometry(x, y, width, height)

    def _refresh_handle_layout(self) -> None:
        track_length = self._track_length()
        if track_length <= 0:
            self._handle.setFixedHeight(_HANDLE_MIN_HEIGHT)
            self._handle.move(self._handle_x(), _HANDLE_PADDING)
            return

        span = max(1, self._maximum - self._minimum + self._page_step)
        ratio = self._page_step / span
        handle_height = max(_HANDLE_MIN_HEIGHT, int(track_length * ratio))
        handle_height = min(handle_height, track_length)
        self._handle.setFixedHeight(handle_height)
        self._reposition_handle()

    def _reposition_handle(self) -> None:
        track_length = self._track_length()
        slide_length = max(0, track_length - self._handle.height())
        span = max(1, self._maximum - self._minimum)
        progress = (self._value - self._minimum) / span if span > 0 else 0.0
        progress = max(0.0, min(1.0, progress))
        delta = int(slide_length * progress)
        target_y = _HANDLE_PADDING + delta
        self._handle_target_y = target_y
        self._handle.move(self._handle_x(), target_y)

    def _compute_handle_target_y(self) -> int:
        """Compute the target Y for the handle based on current value."""
        track_length = self._track_length()
        slide_length = max(0, track_length - self._handle.height())
        span = max(1, self._maximum - self._minimum)
        progress = (self._value - self._minimum) / span if span > 0 else 0.0
        progress = max(0.0, min(1.0, progress))
        return _HANDLE_PADDING + int(slide_length * progress)

    def _animate_handle_to_target(self) -> None:
        """Smoothly chase the handle to the current scroll position."""
        # Recompute handle size in case range changed simultaneously.
        track_length = self._track_length()
        if track_length <= 0:
            return
        span = max(1, self._maximum - self._minimum + self._page_step)
        ratio = self._page_step / span
        handle_height = max(_HANDLE_MIN_HEIGHT, int(track_length * ratio))
        handle_height = min(handle_height, track_length)
        if handle_height != self._handle.height():
            self._handle.setFixedHeight(handle_height)

        target_y = self._compute_handle_target_y()
        self._handle_target_y = target_y
        current_y = self._handle.y()
        if current_y == target_y:
            return
        self._handle_chase_animation.stop()
        self._handle_chase_animation.setStartValue(current_y)
        self._handle_chase_animation.setEndValue(target_y)
        self._handle_chase_animation.start()

    def get_handle_y(self) -> int:
        return self._handle.y()

    def set_handle_y(self, y: int) -> None:
        self._handle.move(self._handle_x(), int(y))

    handleY = Property(int, get_handle_y, set_handle_y)

    def _handle_x(self) -> int:
        return max(0, self.width() - self._handle.width() - 3)

    def _track_length(self) -> int:
        return max(0, self.height() - 2 * _HANDLE_PADDING)

    # ------------------------------------------------------------------
    # Visibility / fade
    # ------------------------------------------------------------------
    def _should_be_visible(self) -> bool:
        return (not self._force_hidden) and (self._maximum > self._minimum)

    def _is_partner_scrolling(self) -> bool:
        return self._scroll_idle_timer.isActive()

    def _fade_in(self) -> None:
        if not self._should_be_visible():
            return
        self.setVisible(True)
        self._leave_timer.stop()
        if self._fade_animation.endValue() == 1.0 and self._fade_animation.state() == QPropertyAnimation.State.Running:
            return
        self._fade_animation.stop()
        self._fade_animation.setStartValue(self._handle.get_opacity())
        self._fade_animation.setEndValue(1.0)
        self._fade_animation.start()

    def _fade_out(self) -> None:
        if self._fade_animation.endValue() == 0.0 and self._fade_animation.state() == QPropertyAnimation.State.Running:
            return
        self._fade_animation.stop()
        self._fade_animation.setStartValue(self._handle.get_opacity())
        self._fade_animation.setEndValue(0.0)
        self._fade_animation.start()

    def _on_leave_timeout(self) -> None:
        if self._is_pressed_handle or self._is_partner_scrolling():
            return
        if self._mode == FluentOverlayScrollBarDisplayMode.ON_HOVER:
            self._fade_out()

    def _on_scroll_idle_timeout(self) -> None:
        if self._is_pressed_handle or self._is_pointer_inside_area():
            return
        if self._mode == FluentOverlayScrollBarDisplayMode.ON_HOVER:
            self._fade_out()

    def _is_pointer_inside_area(self) -> bool:
        parent = self.parentWidget()
        if parent is None:
            return False
        return parent.underMouse() or self.underMouse()

    def _on_theme_changed(self, *_args) -> None:
        self._handle.update()

    # ------------------------------------------------------------------
    # Thickness animation (hover scrollbar -> handle becomes thicker)
    # ------------------------------------------------------------------
    def get_thickness(self) -> float:
        return self._thickness

    def set_thickness(self, value: float) -> None:
        clamped = max(0.0, min(1.0, float(value)))
        if clamped == self._thickness:
            return
        self._thickness = clamped
        width = int(_HANDLE_THIN_WIDTH + (_HANDLE_THICK_WIDTH - _HANDLE_THIN_WIDTH) * clamped)
        if width != self._handle.width():
            self._handle.setFixedWidth(width)
            self._reposition_handle()
        self._handle.update()

    thickness = Property(float, get_thickness, set_thickness)

    def _animate_thickness(self, target: float) -> None:
        if (
            self._thickness_animation.endValue() == target
            and self._thickness_animation.state() == QPropertyAnimation.State.Running
        ):
            return
        self._thickness_animation.stop()
        self._thickness_animation.setStartValue(self._thickness)
        self._thickness_animation.setEndValue(target)
        self._thickness_animation.start()

    def enterEvent(self, event) -> None:
        # Cursor entered the 12px overlay strip itself: thicken the handle and
        # cancel any pending leave-driven hide so the bar stays visible.
        self._leave_timer.stop()
        self._fade_in()
        self._animate_thickness(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        # Leaving the overlay strip: shrink the handle back to its idle width.
        # Active dragging keeps it thick because the user is still interacting.
        if not self._is_pressed_handle:
            self._animate_thickness(0.0)
        super().leaveEvent(event)

    # ------------------------------------------------------------------
    # Event filters & mouse handling
    # ------------------------------------------------------------------
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        parent = self.parentWidget()
        viewport = parent.viewport() if isinstance(parent, QAbstractScrollArea) else None

        if event.type() == QEvent.Type.Resize and watched is parent:
            self._update_geometry()
            self._refresh_handle_layout()
            return False

        if watched is parent or (viewport is not None and watched is viewport):
            event_type = event.type()
            if event_type in (QEvent.Type.Enter, QEvent.Type.HoverEnter):
                if self._mode == FluentOverlayScrollBarDisplayMode.ON_HOVER:
                    self._leave_timer.stop()
                    self._fade_in()
                else:
                    self._fade_in()
            elif event_type in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
                if self._mode == FluentOverlayScrollBarDisplayMode.ON_HOVER:
                    if not self._is_pressed_handle:
                        self._leave_timer.start(_LEAVE_HIDE_DELAY_MS)

        return super().eventFilter(watched, event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        # Forward the wheel to the parent viewport so the native QScrollBar
        # handles the scroll. The overlay never animates wheel input itself.
        parent = self.parentWidget()
        viewport = parent.viewport() if parent is not None else None
        if viewport is not None:
            QApplication.sendEvent(viewport, event)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        click_y = event.position().y()
        handle_top = self._handle.y()
        handle_bottom = handle_top + self._handle.height()
        if handle_top <= click_y <= handle_bottom:
            self._is_pressed_handle = True
            self._press_offset_y = int(click_y - handle_top)
            event.accept()
            return
        # Click on the track: page jump in the corresponding direction.
        if click_y < handle_top:
            self._set_value(self._value - self._page_step)
        else:
            self._set_value(self._value + self._page_step)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._is_pressed_handle:
            super().mouseMoveEvent(event)
            return
        slide_length = max(1, self._track_length() - self._handle.height())
        new_handle_y = int(event.position().y()) - self._press_offset_y
        new_handle_y = max(_HANDLE_PADDING, min(new_handle_y, _HANDLE_PADDING + slide_length))
        progress = (new_handle_y - _HANDLE_PADDING) / slide_length
        span = max(0, self._maximum - self._minimum)
        new_value = int(self._minimum + progress * span)
        self._set_value(new_value)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._is_pressed_handle:
            self._is_pressed_handle = False
            inside = self._is_pointer_inside_area()
            if self._mode == FluentOverlayScrollBarDisplayMode.ON_HOVER and not inside:
                self._leave_timer.start(_LEAVE_HIDE_DELAY_MS)
            # If the drag ended outside the 12px strip (e.g. the user released
            # while the cursor sits over the chat content), let the handle
            # collapse back to its thin idle width.
            if not self.underMouse():
                self._animate_thickness(0.0)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _set_value(self, value: int) -> None:
        clamped = max(self._minimum, min(self._maximum, int(value)))
        if clamped == self._value:
            return
        self._value = clamped
        # Mirror to the partner; partner.valueChanged then loops back into
        # ``_on_partner_value_changed`` and updates the handle position.
        self._partner.setValue(clamped)
        self.valueChanged.emit(clamped)


def attach_fluent_scrollbar(
    area: QAbstractScrollArea,
    *,
    mode: FluentOverlayScrollBarDisplayMode = FluentOverlayScrollBarDisplayMode.ON_HOVER,
) -> FluentOverlayScrollBar:
    """Attach a :class:`FluentOverlayScrollBar` to ``area`` and return it.

    The caller must keep the returned reference alive (e.g. ``self._scrollbar``)
    so the overlay is not garbage-collected.
    """
    return FluentOverlayScrollBar(area, mode=mode)


__all__ = [
    "FluentOverlayScrollBar",
    "FluentOverlayScrollBarDisplayMode",
    "attach_fluent_scrollbar",
]
