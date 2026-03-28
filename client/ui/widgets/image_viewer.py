"""
Image Viewer Module

Dialog for viewing full-size images.
"""

import os

from PySide6.QtCore import QEvent, Qt, QUrl
from PySide6.QtGui import QColor, QPalette, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QDialog, QVBoxLayout, QScrollArea, QLabel, QPushButton, QHBoxLayout, QFrame

from client.core.config_backend import get_config
from client.core.i18n import tr
from qfluentwidgets import isDarkTheme


def _apply_themed_dialog_surface(dialog: QDialog, object_name: str, *, radius: int = 14) -> None:
    """Apply one stable theme-aware palette to the image viewer dialog."""
    dialog.setObjectName(object_name)
    dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    dialog.setAutoFillBackground(True)
    background = QColor(39, 43, 48) if isDarkTheme() else QColor(255, 255, 255)
    palette = dialog.palette()
    palette.setColor(QPalette.ColorRole.Window, background)
    palette.setColor(QPalette.ColorRole.Base, background)
    dialog.setPalette(palette)


def _prepare_transparent_scroll_area(area: QScrollArea) -> None:
    """Keep the viewer scroll area transparent in both themes."""
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    area.setAutoFillBackground(False)
    area.setStyleSheet("QScrollArea{background: transparent; border: none;} QAbstractScrollArea{background: transparent; border: none;}")
    viewport = area.viewport()
    if viewport is not None:
        viewport.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        viewport.setAutoFillBackground(False)
        viewport.setStyleSheet("background: transparent; border: none;")


class ImageViewer(QDialog):
    """
    Image viewer dialog.

    Features:
        - Display full-size image
        - Scroll to zoom
        - Close on Escape key
    """

    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self._image_path = image_path
        self._network_manager = QNetworkAccessManager(self)
        self._network_manager.finished.connect(self._on_image_loaded)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Setup UI components."""
        self.setWindowTitle(tr("image_viewer.title", "Image Viewer"))
        self.setMinimumSize(600, 400)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        _apply_themed_dialog_surface(self, "ImageViewerDialog")

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area for image
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _prepare_transparent_scroll_area(self.scroll_area)

        # Image label
        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._load_image()

        self.scroll_area.setWidget(self.image_label)

        # Close button
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.close_button = QPushButton(tr("common.close", "Close"), self)
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)

        main_layout.addWidget(self.scroll_area)
        main_layout.addLayout(button_layout)

    def changeEvent(self, event) -> None:
        """Keep the dialog surface aligned with the active theme."""
        super().changeEvent(event)
        if event.type() in {
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.StyleChange,
        }:
            _apply_themed_dialog_surface(self, "ImageViewerDialog")

    def _load_image(self) -> None:
        """Load and display image."""
        source = self._resolve_image_source(self._image_path)
        pixmap = QPixmap(source)

        if pixmap.isNull():
            if source.startswith(("http://", "https://")):
                reply = self._network_manager.get(QNetworkRequest(QUrl(source)))
                reply.setProperty("image_source", source)
                self.image_label.setText(tr("image_viewer.loading", "Loading image..."))
                return

            self.image_label.setText(tr("image_viewer.load_failed", "Failed to load image"))
            return

        self.image_label.setPixmap(pixmap)

    def _resolve_image_source(self, value: str) -> str:
        """Resolve local or remote image paths."""
        if not value:
            return ""
        if os.path.exists(value):
            return value
        if value.startswith(("http://", "https://")):
            return value
        if value.startswith("/"):
            origin_base = get_config().server.origin_url.rstrip("/")
            return f"{origin_base}{value}"
        return value

    def _on_image_loaded(self, reply: QNetworkReply) -> None:
        """Handle async remote image loading."""
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.image_label.setText(tr("image_viewer.load_failed", "Failed to load image"))
                return

            pixmap = QPixmap()
            if not pixmap.loadFromData(bytes(reply.readAll())):
                self.image_label.setText(tr("image_viewer.load_failed", "Failed to load image"))
                return

            self.image_label.setPixmap(pixmap)
        finally:
            reply.deleteLater()

    def keyPressEvent(self, event) -> None:
        """Handle key press."""
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        super().keyPressEvent(event)
