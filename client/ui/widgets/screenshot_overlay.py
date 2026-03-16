"""Fullscreen screenshot overlay with window-snapping and freeform selection."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeyEvent, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


class ScreenshotOverlay(QWidget):
    """Overlay used to capture a window or an arbitrary screen region."""

    captured = Signal(str)
    canceled = Signal()

    DRAG_THRESHOLD = 8
    MIN_SELECTION_SIZE = 6

    def __init__(self, parent=None):
        super().__init__(parent)

        self._virtual_geometry = self._compute_virtual_geometry()
        self._background = self._grab_virtual_desktop()
        self._hover_rect_global: QRect | None = None
        self._selection_rect_global: QRect | None = None
        self._selection_start_global: QPoint | None = None
        self._free_selecting = False

        self.setObjectName("ScreenshotOverlay")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(self._virtual_geometry)

    def start(self) -> None:
        """Show the overlay and begin selection."""
        self.show()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Cancel capture on Escape."""
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            return
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Track hovered window or update freeform selection."""
        global_pos = event.globalPosition().toPoint()

        if self._selection_start_global is not None:
            if self._free_selecting:
                self._selection_rect_global = QRect(self._selection_start_global, global_pos).normalized()
            elif (global_pos - self._selection_start_global).manhattanLength() >= self.DRAG_THRESHOLD:
                self._free_selecting = True
                self._selection_rect_global = QRect(self._selection_start_global, global_pos).normalized()
            else:
                self._hover_rect_global = self._window_rect_at(global_pos)
        else:
            self._hover_rect_global = self._window_rect_at(global_pos)

        self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Begin window or freeform capture."""
        if event.button() == Qt.MouseButton.RightButton:
            self._cancel()
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)

        global_pos = event.globalPosition().toPoint()
        self._selection_start_global = global_pos
        self._hover_rect_global = self._window_rect_at(global_pos)

        if self._hover_rect_global is None:
            self._free_selecting = True
            self._selection_rect_global = QRect(global_pos, global_pos)
        else:
            self._free_selecting = False
            self._selection_rect_global = None

        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish the capture on left release."""
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)

        target_rect: QRect | None = None
        if self._free_selecting:
            target_rect = self._selection_rect_global
        else:
            target_rect = self._window_rect_at(event.globalPosition().toPoint()) or self._hover_rect_global

        if target_rect is not None and target_rect.width() >= self.MIN_SELECTION_SIZE and target_rect.height() >= self.MIN_SELECTION_SIZE:
            self._finish_capture(target_rect)
            return

        self._cancel()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        """Draw the dimmed desktop and the current selection highlight."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(self.rect(), self._background)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))

        highlight_global = self._selection_rect_global if self._free_selecting else self._hover_rect_global
        if highlight_global is None or highlight_global.isNull():
            return

        highlight = self._to_local_rect(highlight_global)
        if highlight.isNull():
            return

        painter.drawPixmap(highlight, self._background.copy(highlight))
        painter.fillRect(highlight, QColor(255, 255, 255, 18))
        painter.setPen(QPen(QColor("#4C8DFF"), 2))
        painter.drawRect(highlight)

    def _finish_capture(self, rect_global: QRect) -> None:
        """Save the selected area to a temporary PNG file and emit it."""
        pixmap = self._capture_rect(rect_global)
        output_dir = Path(__file__).resolve().parents[2] / "data" / "screenshots"
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
        pixmap.save(str(file_path), "PNG")
        self.hide()
        self.captured.emit(str(file_path))
        self.deleteLater()

    def _cancel(self) -> None:
        """Cancel the current capture session."""
        self.hide()
        self.canceled.emit()
        self.deleteLater()

    def _to_local_rect(self, rect_global: QRect) -> QRect:
        """Translate a global rect into overlay-local coordinates."""
        top_left = rect_global.topLeft() - self._virtual_geometry.topLeft()
        return QRect(top_left, rect_global.size())

    @staticmethod
    def _compute_virtual_geometry() -> QRect:
        """Return the union of all screen geometries."""
        geometry = QRect()
        for screen in QGuiApplication.screens():
            geometry = geometry.united(screen.geometry())
        return geometry

    def _grab_virtual_desktop(self) -> QPixmap:
        """Capture all screens into a single pixmap."""
        pixmap = QPixmap(self._virtual_geometry.size())
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        for screen in QGuiApplication.screens():
            logical_geometry = screen.geometry()
            target_rect = QRect(logical_geometry.topLeft() - self._virtual_geometry.topLeft(), logical_geometry.size())
            grab = screen.grabWindow(0, 0, 0, logical_geometry.width(), logical_geometry.height())
            painter.drawPixmap(QRectF(target_rect), grab, QRectF(grab.rect()))
        painter.end()
        return pixmap

    def _capture_rect(self, rect_global: QRect) -> QPixmap:
        """Capture the selected rect using per-screen grabs to avoid blur."""
        target = QPixmap(rect_global.size())
        target.fill(Qt.GlobalColor.transparent)

        painter = QPainter(target)
        for screen in QGuiApplication.screens():
            logical_geometry = screen.geometry()
            intersection = rect_global.intersected(logical_geometry)
            if intersection.isEmpty():
                continue

            screen_local = intersection.translated(-logical_geometry.topLeft())
            grab = screen.grabWindow(0, screen_local.x(), screen_local.y(), screen_local.width(), screen_local.height())
            draw_rect = QRect(intersection.topLeft() - rect_global.topLeft(), intersection.size())
            painter.drawPixmap(QRectF(draw_rect), grab, QRectF(grab.rect()))
        painter.end()
        return target

    def _window_rect_at(self, global_pos: QPoint) -> QRect | None:
        """Return the hovered top-level window rect on Windows."""
        if not hasattr(ctypes, "WINFUNCTYPE"):
            return None

        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi
        overlay_hwnd = int(self.winId())

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        physical_point = POINT()
        if not user32.GetCursorPos(ctypes.byref(physical_point)):
            return None

        enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        matched: list[tuple[int, RECT]] = []

        def enum_proc(hwnd, _lparam):
            if hwnd == overlay_hwnd:
                return True
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True

            rect = RECT()
            if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return True

            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width < 40 or height < 40:
                return True

            if rect.left <= physical_point.x < rect.right and rect.top <= physical_point.y < rect.bottom:
                matched.append((hwnd, rect))
                return False
            return True

        user32.EnumWindows(enum_proc_type(enum_proc), 0)
        if not matched:
            return None

        hwnd, rect = matched[0]
        screen = QGuiApplication.screenAt(global_pos)
        if screen is None:
            return None
        return self._physical_rect_to_logical(hwnd, rect, screen)

    def _physical_rect_to_logical(self, hwnd, rect, screen) -> QRect | None:
        """Convert a native window rect to Qt logical coordinates."""
        user32 = ctypes.windll.user32

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        monitor_info = MONITORINFO()
        monitor_info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
            return None

        monitor_rect = monitor_info.rcMonitor
        physical_width = max(1, monitor_rect.right - monitor_rect.left)
        physical_height = max(1, monitor_rect.bottom - monitor_rect.top)
        logical_geometry = screen.geometry()
        scale_x = physical_width / max(1, logical_geometry.width())
        scale_y = physical_height / max(1, logical_geometry.height())

        left = logical_geometry.left() + round((rect.left - monitor_rect.left) / scale_x)
        top = logical_geometry.top() + round((rect.top - monitor_rect.top) / scale_y)
        width = max(1, round((rect.right - rect.left) / scale_x))
        height = max(1, round((rect.bottom - rect.top) / scale_y))
        return QRect(left, top, width, height)
