"""Fluent-styled dialog surface without qframelesswindow resize hit testing."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import SubtitleLabel, isDarkTheme, qconfig
from qframelesswindow.titlebar.title_bar_buttons import CloseButton


class FluentDialog(QDialog):
    """A frameless Fluent visual shell that keeps Qt's standard dialog ownership."""

    TITLE_BAR_HEIGHT = 48

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

        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(20, 0, 0, 0)
        title_layout.setSpacing(8)

        self.title_label = SubtitleLabel(str(title or ""), self.title_bar)
        self.title_label.setObjectName("fluentDialogTitleLabel")
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self.close_button = CloseButton(self.title_bar)
        self.close_button.setObjectName("fluentDialogCloseButton")
        self.close_button.clicked.connect(self.close)

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

    def setTitleText(self, title: str) -> None:
        self.title_label.setText(str(title or ""))
        self.setWindowTitle(str(title or ""))

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
