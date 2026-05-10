"""Fluent-styled dialog surface without qframelesswindow resize hit testing."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QParallelAnimationGroup, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import SubtitleLabel, isDarkTheme, qconfig
from qframelesswindow.titlebar.title_bar_buttons import CloseButton


class FluentDialogCloseButton(CloseButton):
    """Close button that keeps the dialog's top-right rounded corner."""

    def __init__(self, parent=None, *, corner_radius: int = 12) -> None:
        super().__init__(parent)
        self._corner_radius = max(0, int(corner_radius or 0))

    def setCornerRadius(self, radius: int) -> None:
        self._corner_radius = max(0, int(radius or 0))
        self.update()

    def _background_path(self) -> QPainterPath:
        rect = QRectF(self.rect())
        radius = min(float(self._corner_radius), rect.width(), rect.height())
        path = QPainterPath()
        path.moveTo(rect.left(), rect.top())
        path.lineTo(rect.right() - radius, rect.top())
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + radius)
        path.lineTo(rect.right(), rect.bottom())
        path.lineTo(rect.left(), rect.bottom())
        path.closeSubpath()
        return path

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        color, bg_color = self._getColors()

        painter.setBrush(bg_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(self._background_path())

        path_nodes = self._svgDom.elementsByTagName("path")
        for index in range(path_nodes.length()):
            element = path_nodes.at(index).toElement()
            element.setAttribute("stroke", color.name())

        renderer = QSvgRenderer(self._svgDom.toByteArray())
        renderer.render(painter, QRectF(self.rect()))


class FluentDialog(QDialog):
    """A frameless Fluent visual shell that keeps Qt's standard dialog ownership."""

    TITLE_BAR_HEIGHT = 48
    CLOSE_BUTTON_WIDTH = 48

    def __init__(
        self,
        parent=None,
        *,
        title: str = "",
        radius: int = 12,
    ) -> None:
        super().__init__(parent)
        self._radius = max(6, int(radius or 12))
        self._drag_active = False
        self._drag_offset = QPoint()
        self._show_animation_group: QParallelAnimationGroup | None = None

        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self.shell_layout = QVBoxLayout(self)
        self.shell_layout.setContentsMargins(0, 0, 0, 0)
        self.shell_layout.setSpacing(0)

        self.surface = QFrame(self)
        self.surface.setObjectName("fluentDialogSurface")
        self.surface.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.shell_layout.addWidget(self.surface)

        self.surface_layout = QVBoxLayout(self.surface)
        self.surface_layout.setContentsMargins(0, 0, 0, 0)
        self.surface_layout.setSpacing(0)

        self.title_bar = QWidget(self.surface)
        self.title_bar.setObjectName("fluentDialogTitleBar")
        self.title_bar.setFixedHeight(self.TITLE_BAR_HEIGHT)
        self.title_bar.installEventFilter(self)

        self.close_button = FluentDialogCloseButton(self.title_bar, corner_radius=self._radius)
        self.close_button.setObjectName("fluentDialogCloseButton")
        self.close_button.clicked.connect(self.close)

        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)

        self.title_left_spacer = QWidget(self.title_bar)
        self.title_left_spacer.setFixedWidth(self.CLOSE_BUTTON_WIDTH)

        self.title_label = SubtitleLabel(str(title or ""), self.title_bar)
        self.title_label.setObjectName("fluentDialogTitleLabel")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title_font = QFont(self.title_label.font())
        title_font.setPixelSize(15)
        title_font.setBold(False)
        self.title_label.setFont(title_font)

        title_layout.addWidget(self.title_left_spacer, 0)
        title_layout.addWidget(self.title_label, 1, Qt.AlignmentFlag.AlignVCenter)
        title_layout.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)

        self.content_widget = QWidget(self.surface)
        self.content_widget.setObjectName("fluentDialogContent")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(24, 8, 24, 24)
        self.content_layout.setSpacing(16)

        self.surface_layout.addWidget(self.title_bar)
        self.surface_layout.addWidget(self.content_widget, 1)

        qconfig.themeChangedFinished.connect(self._apply_fluent_surface)
        self._apply_fluent_surface()
        self._sync_title_left_spacer_width()
        self._schedule_title_alignment_sync()

    def setTitleText(self, title: str) -> None:
        self.setWindowTitle(str(title or ""))

    def setWindowTitle(self, title: str) -> None:
        normalized = str(title or "")
        super().setWindowTitle(normalized)
        if hasattr(self, "title_label"):
            self.title_label.setText(normalized)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.title_bar:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_active = True
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag_active:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                event.accept()
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and self._drag_active:
                self._drag_active = False
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event) -> None:
        self._drag_active = False
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        self._sync_title_left_spacer_width()
        super().resizeEvent(event)
        self._schedule_title_alignment_sync()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_title_left_spacer_width()
        self._schedule_title_alignment_sync()
        self._start_show_animation()

    def _sync_title_left_spacer_width(self) -> None:
        width = self.close_button.width() if self.close_button.width() > 0 else self.CLOSE_BUTTON_WIDTH
        self.title_left_spacer.setFixedWidth(width)

    def _schedule_title_alignment_sync(self) -> None:
        QTimer.singleShot(0, self._sync_title_label_to_close_button)

    def _sync_title_label_to_close_button(self) -> None:
        close_center_y = self.close_button.geometry().center().y()
        if close_center_y <= 0:
            return
        label_rect = self.title_label.geometry()
        label_y = max(0, close_center_y - label_rect.height() // 2)
        self.title_label.move(self.title_label.x(), label_y)

    def _start_show_animation(self) -> None:
        if self._show_animation_group is not None:
            self._show_animation_group.stop()
            self._show_animation_group.deleteLater()

        final_pos = self.pos()
        start_pos = final_pos + QPoint(0, 8)
        self.setWindowOpacity(0.0)
        self.move(start_pos)

        opacity_animation = QPropertyAnimation(self, b"windowOpacity", self)
        opacity_animation.setDuration(150)
        opacity_animation.setStartValue(0.0)
        opacity_animation.setEndValue(1.0)
        opacity_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        position_animation = QPropertyAnimation(self, b"pos", self)
        position_animation.setDuration(150)
        position_animation.setStartValue(start_pos)
        position_animation.setEndValue(final_pos)
        position_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(opacity_animation)
        group.addAnimation(position_animation)

        def finish_animation() -> None:
            self.setWindowOpacity(1.0)
            self.move(final_pos)
            if self._show_animation_group is group:
                self._show_animation_group = None
            group.deleteLater()

        group.finished.connect(finish_animation)
        self._show_animation_group = group
        group.start()

    def _apply_fluent_surface(self) -> None:
        dark = isDarkTheme()
        border = "#3A3A3A" if dark else "#D1D5DB"
        background = "#202020" if dark else "#FFFFFF"
        text_color = QColor(255, 255, 255) if dark else QColor(0, 0, 0)
        self.close_button.setNormalColor(text_color)
        self.close_button.setHoverColor(QColor(255, 255, 255))
        self.close_button.setPressedColor(QColor(255, 255, 255))
        self.surface.setStyleSheet(
            f"""
            QFrame#fluentDialogSurface {{
                background: {background};
                border: 1px solid {border};
                border-radius: {self._radius}px;
            }}
            QWidget#fluentDialogTitleBar {{
                background: transparent;
                border: none;
            }}
            QWidget#fluentDialogContent {{
                background: transparent;
                border: none;
            }}
            """
        )
