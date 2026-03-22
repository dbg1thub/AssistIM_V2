"""Fullscreen screenshot overlay with window-snapping and freeform selection."""

from __future__ import annotations

import ctypes
import math
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QKeyEvent, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


@dataclass
class WindowTarget:
    """Native window hit-test result with both logical and physical bounds."""

    hwnd: int
    logical_rect: QRect
    physical_rect: QRect


class ScreenshotOverlay(QWidget):
    """Overlay used to capture a window or an arbitrary screen region."""

    captured = Signal(str)
    canceled = Signal()

    DRAG_THRESHOLD = 8
    MIN_SELECTION_SIZE = 6

    def __init__(self, parent=None):
        super().__init__(parent)

        self._virtual_geometry = self._compute_virtual_geometry()
        self._hover_target: WindowTarget | None = None
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
                self._hover_target = self._window_target_at(global_pos)
        else:
            self._hover_target = self._window_target_at(global_pos)

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
        self._hover_target = self._window_target_at(global_pos)

        if self._hover_target is None:
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
        target_window: WindowTarget | None = None
        if self._free_selecting:
            target_rect = self._selection_rect_global
        else:
            target_window = self._window_target_at(event.globalPosition().toPoint()) or self._hover_target
            target_rect = target_window.logical_rect if target_window else None

        if target_rect is not None and target_rect.width() >= self.MIN_SELECTION_SIZE and target_rect.height() >= self.MIN_SELECTION_SIZE:
            self._finish_capture(target_rect, target_window)
            return

        self._cancel()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        """Draw the dimmed desktop and the current selection highlight."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))

        highlight_global = self._selection_rect_global if self._free_selecting else (
            self._hover_target.logical_rect if self._hover_target else None
        )
        if highlight_global is None or highlight_global.isNull():
            return

        highlight = self._to_local_rect(highlight_global)
        if highlight.isNull():
            return

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(highlight, Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.fillRect(highlight, QColor(255, 255, 255, 18))
        painter.setPen(QPen(QColor("#4C8DFF"), 2))
        painter.drawRect(highlight)

    def _finish_capture(self, rect_global: QRect, target_window: WindowTarget | None = None) -> None:
        """Save the selected area to a temporary PNG file and emit it."""
        self.hide()
        app = QGuiApplication.instance()
        if app is not None:
            app.processEvents()

        if target_window is not None:
            pixmap = self._capture_window(target_window)
        else:
            pixmap = self._capture_rect(rect_global)
        output_dir = Path(__file__).resolve().parents[2] / "data" / "screenshots"
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
        pixmap.save(str(file_path), "PNG")
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

    def _capture_rect(self, rect_global: QRect) -> QPixmap:
        """Capture the selected rect using native pixel crops to keep screenshots sharp."""
        parts: list[tuple[QImage, QPoint]] = []
        target_width = 0
        target_height = 0

        for screen in QGuiApplication.screens():
            logical_geometry = screen.geometry()
            intersection = rect_global.intersected(logical_geometry)
            if intersection.isEmpty():
                continue

            grab = screen.grabWindow(0)
            if grab.isNull():
                continue

            image = grab.toImage()
            scale_x = image.width() / max(1, logical_geometry.width())
            scale_y = image.height() / max(1, logical_geometry.height())

            source_rect = QRect(
                max(0, round((intersection.left() - logical_geometry.left()) * scale_x)),
                max(0, round((intersection.top() - logical_geometry.top()) * scale_y)),
                max(1, round(intersection.width() * scale_x)),
                max(1, round(intersection.height() * scale_y)),
            ).intersected(image.rect())
            if source_rect.isEmpty():
                continue

            draw_point = QPoint(
                max(0, round((intersection.left() - rect_global.left()) * scale_x)),
                max(0, round((intersection.top() - rect_global.top()) * scale_y)),
            )
            cropped = image.copy(source_rect)
            parts.append((cropped, draw_point))
            target_width = max(target_width, draw_point.x() + cropped.width())
            target_height = max(target_height, draw_point.y() + cropped.height())

        if not parts or target_width <= 0 or target_height <= 0:
            return QPixmap()

        target = QImage(target_width, target_height, QImage.Format.Format_ARGB32_Premultiplied)
        target.fill(Qt.GlobalColor.transparent)

        painter = QPainter(target)
        for image, draw_point in parts:
            painter.drawImage(draw_point, image)
        painter.end()
        return QPixmap.fromImage(target)

    def _capture_window(self, target_window: WindowTarget) -> QPixmap:
        """Capture a native window directly so snapped-window screenshots stay precise."""
        native = self._capture_window_native(target_window)
        if native is not None and not native.isNull():
            return native

        screen = QGuiApplication.screenAt(target_window.logical_rect.center())
        if screen is None:
            return self._capture_rect(target_window.logical_rect)

        grab = screen.grabWindow(target_window.hwnd)
        if not grab.isNull():
            return grab

        return self._capture_rect(target_window.logical_rect)

    def _capture_window_native(self, target_window: WindowTarget) -> QPixmap | None:
        """Capture a window with PrintWindow so occluded windows don't include front content."""
        if not hasattr(ctypes, "windll"):
            return None

        width = target_window.physical_rect.width()
        height = target_window.physical_rect.height()
        if width <= 0 or height <= 0:
            return None

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [
                ("bmiHeader", BITMAPINFOHEADER),
                ("bmiColors", wintypes.DWORD * 3),
            ]

        BI_RGB = 0
        DIB_RGB_COLORS = 0
        PW_RENDERFULLCONTENT = 0x00000002

        screen_dc = user32.GetDC(0)
        if not screen_dc:
            return None

        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
        if not memory_dc or not bitmap:
            if bitmap:
                gdi32.DeleteObject(bitmap)
            if memory_dc:
                gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(0, screen_dc)
            return None

        old_bitmap = gdi32.SelectObject(memory_dc, bitmap)
        try:
            success = user32.PrintWindow(target_window.hwnd, memory_dc, PW_RENDERFULLCONTENT)
            if not success:
                success = user32.PrintWindow(target_window.hwnd, memory_dc, 0)
            if not success:
                return None

            bitmap_info = BITMAPINFO()
            bitmap_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bitmap_info.bmiHeader.biWidth = width
            bitmap_info.bmiHeader.biHeight = -height
            bitmap_info.bmiHeader.biPlanes = 1
            bitmap_info.bmiHeader.biBitCount = 32
            bitmap_info.bmiHeader.biCompression = BI_RGB

            buffer = ctypes.create_string_buffer(width * height * 4)
            copied = gdi32.GetDIBits(
                memory_dc,
                bitmap,
                0,
                height,
                buffer,
                ctypes.byref(bitmap_info),
                DIB_RGB_COLORS,
            )
            if copied != height:
                return None

            image = QImage(buffer.raw, width, height, width * 4, QImage.Format.Format_ARGB32)
            return QPixmap.fromImage(image.copy())
        finally:
            if old_bitmap:
                gdi32.SelectObject(memory_dc, old_bitmap)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(0, screen_dc)

    def _window_target_at(self, global_pos: QPoint) -> WindowTarget | None:
        """Return the hovered top-level window with logical and physical bounds."""
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
        logical_rect = self._physical_rect_to_logical(hwnd, rect, screen)
        if logical_rect is None:
            return None
        physical_rect = QRect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
        return WindowTarget(hwnd=hwnd, logical_rect=logical_rect, physical_rect=physical_rect)

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

        left = logical_geometry.left() + math.floor((rect.left - monitor_rect.left) / scale_x)
        top = logical_geometry.top() + math.floor((rect.top - monitor_rect.top) / scale_y)
        right = logical_geometry.left() + math.ceil((rect.right - monitor_rect.left) / scale_x)
        bottom = logical_geometry.top() + math.ceil((rect.bottom - monitor_rect.top) / scale_y)
        width = max(1, right - left)
        height = max(1, bottom - top)
        return QRect(left, top, width, height)
