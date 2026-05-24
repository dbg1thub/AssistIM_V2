"""Fluent-styled dialog surface without qframelesswindow resize hit testing."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QFile, QEasingCurve, QEvent, QPoint, QPointF, QParallelAnimationGroup, QPropertyAnimation, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtXml import QDomDocument
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import SubtitleLabel, isDarkTheme, qconfig
from qframelesswindow.titlebar.title_bar_buttons import TitleBarButton


def _title_button_background_path(rect: QRectF, corner: str, radius: int) -> QPainterPath:
    corner = str(corner or "none").lower()
    radius_value = min(float(max(0, radius)), rect.width(), rect.height())
    path = QPainterPath()
    if corner == "left" and radius_value > 0:
        path.moveTo(rect.left() + radius_value, rect.top())
        path.lineTo(rect.right(), rect.top())
        path.lineTo(rect.right(), rect.bottom())
        path.lineTo(rect.left(), rect.bottom())
        path.lineTo(rect.left(), rect.top() + radius_value)
        path.quadTo(rect.left(), rect.top(), rect.left() + radius_value, rect.top())
        path.closeSubpath()
        return path
    if corner == "right" and radius_value > 0:
        path.moveTo(rect.left(), rect.top())
        path.lineTo(rect.right() - radius_value, rect.top())
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + radius_value)
        path.lineTo(rect.right(), rect.bottom())
        path.lineTo(rect.left(), rect.bottom())
        path.closeSubpath()
        return path
    path.addRect(rect)
    return path


class FluentDialogWindowButton(TitleBarButton):
    """Self-drawn minimize, maximize, and close buttons matching the main window title bar."""

    def __init__(self, button_type: str, parent=None, *, corner_radius: int = 12) -> None:
        super().__init__(parent)
        self._button_type = str(button_type or "").lower()
        self._corner = "none"
        self._corner_radius = max(0, int(corner_radius or 0))
        self._is_maximized = False
        self._close_svg_dom = QDomDocument()
        if self._button_type == "close":
            file = QFile(":/qframelesswindow/close.svg")
            file.open(QFile.OpenModeFlag.ReadOnly)
            self._close_svg_dom.setContent(file.readAll())
            file.close()
            self.setHoverColor(Qt.GlobalColor.white)
            self.setPressedColor(Qt.GlobalColor.white)
            self.setHoverBackgroundColor(QColor(232, 17, 35))
            self.setPressedBackgroundColor(QColor(241, 112, 122))

    def setCorner(self, corner: str) -> None:
        self._corner = str(corner or "none").lower()
        self.update()

    def _background_path(self) -> QPainterPath:
        return _title_button_background_path(QRectF(self.rect()), self._corner, self._corner_radius)

    def setMaximized(self, maximized: bool) -> None:
        self._is_maximized = bool(maximized)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color, bg_color = self._getColors()

        painter.setBrush(bg_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(self._background_path())

        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(color, 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        if self._button_type == "minimize":
            painter.drawLine(18, 16, 28, 16)
        elif self._button_type == "maximize":
            r = self.devicePixelRatioF()
            painter.scale(1 / r, 1 / r)
            if self._is_maximized:
                painter.drawRect(int(18 * r), int(13 * r), int(8 * r), int(8 * r))
                x0 = int(18 * r) + int(2 * r)
                y0 = 13 * r
                dw = int(2 * r)
                path = QPainterPath(QPointF(x0, y0))
                path.lineTo(x0, y0 - dw)
                path.lineTo(x0 + 8 * r, y0 - dw)
                path.lineTo(x0 + 8 * r, y0 - dw + 8 * r)
                path.lineTo(x0 + 8 * r - dw, y0 - dw + 8 * r)
                painter.drawPath(path)
            else:
                painter.drawRect(int(18 * r), int(11 * r), int(10 * r), int(10 * r))
        elif self._button_type == "close":
            path_nodes = self._close_svg_dom.elementsByTagName("path")
            for index in range(path_nodes.length()):
                element = path_nodes.at(index).toElement()
                element.setAttribute("stroke", color.name())
            renderer = QSvgRenderer(self._close_svg_dom.toByteArray())
            renderer.render(painter, QRectF(self.rect()))


class FluentDialogTitleButton(TitleBarButton):
    """Reusable FluentDialog title-bar button with caller-provided vector icon geometry."""

    def __init__(
        self,
        path_factory: Callable[[QRectF], QPainterPath],
        parent=None,
        *,
        corner: str = "none",
        corner_radius: int = 12,
        icon_size: QSize | None = None,
        pen_width: float = 1.0,
    ) -> None:
        super().__init__(parent)
        self._path_factory = path_factory
        self._corner = str(corner or "none").lower()
        self._corner_radius = max(0, int(corner_radius or 0))
        self._pen_width = max(0.5, float(pen_width or 1.0))
        self.setIconSize(icon_size or QSize(12, 12))

    def setCorner(self, corner: str) -> None:
        self._corner = str(corner or "none").lower()
        self.update()

    def _background_path(self) -> QPainterPath:
        return _title_button_background_path(QRectF(self.rect()), self._corner, self._corner_radius)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        color, bg_color = self._getColors()

        painter.setBrush(bg_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(self._background_path())

        icon_size = self.iconSize()
        icon_rect = QRectF(
            (self.width() - icon_size.width()) / 2,
            (self.height() - icon_size.height()) / 2,
            icon_size.width(),
            icon_size.height(),
        )
        pen = QPen(color, self._pen_width)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._path_factory(icon_rect))


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
        self._title_buttons: list[FluentDialogTitleButton] = []
        self._left_title_buttons: list[FluentDialogTitleButton] = []
        self._right_title_buttons: list[FluentDialogTitleButton] = []
        self._default_title_buttons: list[FluentDialogWindowButton] = []

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

        self.minimize_button = FluentDialogWindowButton("minimize", self.title_bar, corner_radius=self._radius)
        self.minimize_button.setObjectName("fluentDialogMinimizeButton")
        self.minimize_button.clicked.connect(self.showMinimized)
        self.minimize_button.setVisible(False)

        self.maximize_button = FluentDialogWindowButton("maximize", self.title_bar, corner_radius=self._radius)
        self.maximize_button.setObjectName("fluentDialogMaximizeButton")
        self.maximize_button.clicked.connect(self._toggle_maximized)
        self.maximize_button.setVisible(False)

        self.close_button = FluentDialogWindowButton("close", self.title_bar, corner_radius=self._radius)
        self.close_button.setObjectName("fluentDialogCloseButton")
        self.close_button.clicked.connect(self.close)
        self.close_button.setVisible(True)
        self._default_title_buttons = [self.minimize_button, self.maximize_button, self.close_button]

        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)

        self.title_left_balance = QWidget(self.title_bar)
        self.title_left_balance.setFixedWidth(self.CLOSE_BUTTON_WIDTH)
        self.title_right_balance = QWidget(self.title_bar)
        self.title_right_balance.setFixedWidth(0)

        self.title_label = SubtitleLabel(str(title or ""), self.title_bar)
        self.title_label.setObjectName("fluentDialogTitleLabel")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title_font = QFont(self.title_label.font())
        title_font.setPixelSize(15)
        title_font.setBold(False)
        self.title_label.setFont(title_font)

        title_layout.addWidget(self.title_left_balance, 0)
        title_layout.addWidget(self.title_label, 1, Qt.AlignmentFlag.AlignVCenter)
        title_layout.addWidget(self.title_right_balance, 0)
        title_layout.addWidget(self.minimize_button, 0, Qt.AlignmentFlag.AlignTop)
        title_layout.addWidget(self.maximize_button, 0, Qt.AlignmentFlag.AlignTop)
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
        self._sync_title_bar_layout()
        self._schedule_title_bar_layout_sync()

    def add_title_left_button(
        self,
        path_factory: Callable[[QRectF], QPainterPath],
        *,
        tooltip: str = "",
        corner: str = "none",
        on_clicked=None,
        object_name: str = "",
        icon_size: QSize | None = None,
        pen_width: float = 1.0,
    ) -> FluentDialogTitleButton:
        """Add one custom icon button to the left side of the title bar."""
        button = FluentDialogTitleButton(
            path_factory,
            self.title_bar,
            corner=corner,
            corner_radius=self._radius,
            icon_size=icon_size,
            pen_width=pen_width,
        )
        self._configure_title_button(button, tooltip=tooltip, object_name=object_name, on_clicked=on_clicked)
        self._left_title_buttons.append(button)
        layout = self.title_bar.layout()
        if isinstance(layout, QHBoxLayout):
            layout.insertWidget(max(0, layout.indexOf(self.title_left_balance)), button, 0, Qt.AlignmentFlag.AlignTop)
        self._sync_title_bar_layout()
        return button

    def add_title_right_button(
        self,
        path_factory: Callable[[QRectF], QPainterPath],
        *,
        tooltip: str = "",
        corner: str = "none",
        on_clicked=None,
        object_name: str = "",
        icon_size: QSize | None = None,
        pen_width: float = 1.0,
    ) -> FluentDialogTitleButton:
        """Add one custom icon button immediately before the close button."""
        button = FluentDialogTitleButton(
            path_factory,
            self.title_bar,
            corner=corner,
            corner_radius=self._radius,
            icon_size=icon_size,
            pen_width=pen_width,
        )
        self._configure_title_button(button, tooltip=tooltip, object_name=object_name, on_clicked=on_clicked)
        self._right_title_buttons.append(button)
        layout = self.title_bar.layout()
        if isinstance(layout, QHBoxLayout):
            minimize_index = layout.indexOf(self.minimize_button)
            layout.insertWidget(minimize_index if minimize_index >= 0 else layout.count(), button, 0, Qt.AlignmentFlag.AlignTop)
        self._sync_title_bar_layout()
        return button

    def _configure_title_button(
        self,
        button: FluentDialogTitleButton,
        *,
        tooltip: str,
        object_name: str,
        on_clicked,
    ) -> None:
        if object_name:
            button.setObjectName(object_name)
        if tooltip:
            button.setToolTip(tooltip)
        if on_clicked is not None:
            button.clicked.connect(on_clicked)
        self._title_buttons.append(button)
        self._sync_title_button_colors(
            QColor(255, 255, 255) if isDarkTheme() else QColor(0, 0, 0)
        )
        self._sync_title_bar_layout()

    def _sync_title_button_colors(self, text_color: QColor) -> None:
        hover_bg = QColor(255, 255, 255, 26) if isDarkTheme() else QColor(0, 0, 0, 26)
        pressed_bg = QColor(255, 255, 255, 51) if isDarkTheme() else QColor(0, 0, 0, 51)
        for button in list(self._title_buttons):
            button.setNormalColor(text_color)
            button.setHoverColor(text_color)
            button.setPressedColor(text_color)
            button.setNormalBackgroundColor(QColor(0, 0, 0, 0))
            button.setHoverBackgroundColor(hover_bg)
            button.setPressedBackgroundColor(pressed_bg)

    def _sync_default_title_button_colors(self, text_color: QColor) -> None:
        hover_bg = QColor(255, 255, 255, 26) if isDarkTheme() else QColor(0, 0, 0, 26)
        pressed_bg = QColor(255, 255, 255, 51) if isDarkTheme() else QColor(0, 0, 0, 51)
        for button in (self.minimize_button, self.maximize_button):
            button.setNormalColor(text_color)
            button.setHoverColor(text_color)
            button.setPressedColor(text_color)
            button.setNormalBackgroundColor(QColor(0, 0, 0, 0))
            button.setHoverBackgroundColor(hover_bg)
            button.setPressedBackgroundColor(pressed_bg)
        self.close_button.setNormalColor(text_color)
        self.close_button.setHoverColor(QColor(255, 255, 255))
        self.close_button.setPressedColor(QColor(255, 255, 255))
        self.close_button.setNormalBackgroundColor(QColor(0, 0, 0, 0))
        self.close_button.setHoverBackgroundColor(QColor(232, 17, 35))
        self.close_button.setPressedBackgroundColor(QColor(241, 112, 122))

    def setTitleText(self, title: str) -> None:
        self.setWindowTitle(str(title or ""))

    def setWindowTitle(self, title: str) -> None:
        normalized = str(title or "")
        super().setWindowTitle(normalized)
        if hasattr(self, "title_label"):
            self.title_label.setText(normalized)
            self._schedule_title_bar_layout_sync()

    def setMinimizeButtonVisible(self, visible: bool) -> None:
        self.minimize_button.setVisible(bool(visible))
        self._sync_title_bar_layout()

    def setMaximizeButtonVisible(self, visible: bool) -> None:
        self.maximize_button.setVisible(bool(visible))
        self._sync_maximize_button_state()
        self._sync_title_bar_layout()

    def setCloseButtonVisible(self, visible: bool) -> None:
        self.close_button.setVisible(bool(visible))
        self._sync_title_bar_layout()

    def _toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._sync_maximize_button_state()

    def _sync_maximize_button_state(self) -> None:
        self.maximize_button.setMaximized(self.isMaximized())

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

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_maximize_button_state()
            self._schedule_title_bar_layout_sync()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_title_bar_layout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_title_bar_layout()
        self._start_show_animation()

    @staticmethod
    def _visible_button_width(buttons: list[QWidget]) -> int:
        return sum(button.width() for button in buttons if button.isVisible())

    def _schedule_title_bar_layout_sync(self) -> None:
        QTimer.singleShot(0, self._sync_title_bar_layout)

    def _sync_title_bar_layout(self) -> None:
        left_width = self._visible_button_width(self._left_title_buttons)
        right_width = self._visible_button_width(self._right_title_buttons + self._default_title_buttons)
        self.title_left_balance.setFixedWidth(max(0, right_width - left_width))
        self.title_right_balance.setFixedWidth(max(0, left_width - right_width))
        self._sync_title_button_corners()
        self._sync_title_label_vertical_alignment()

    def _sync_title_button_corners(self) -> None:
        for button in self._left_title_buttons + self._right_title_buttons:
            button.setCorner("none")
        for button in self._default_title_buttons:
            button.setCorner("none")

        visible_left_buttons = [button for button in self._left_title_buttons if button.isVisible()]
        if visible_left_buttons:
            button = visible_left_buttons[0]
            button.setCorner("left")

        visible_right_buttons = [
            button
            for button in self._right_title_buttons + self._default_title_buttons
            if button.isVisible()
        ]
        if visible_right_buttons:
            button = visible_right_buttons[-1]
            button.setCorner("right")

    def _visible_title_button_center_y(self) -> int:
        for button in self._default_title_buttons + self._right_title_buttons + self._left_title_buttons:
            if button.isVisible() and button.geometry().height() > 0:
                return button.geometry().center().y()
        return self.title_bar.height() // 2

    def _sync_title_label_vertical_alignment(self) -> None:
        button_center_y = self._visible_title_button_center_y()
        label_rect = self.title_label.geometry()
        label_y = max(0, button_center_y - label_rect.height() // 2)
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
        self._sync_default_title_button_colors(text_color)
        self._sync_title_button_colors(text_color)
        self._sync_title_bar_layout()
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
