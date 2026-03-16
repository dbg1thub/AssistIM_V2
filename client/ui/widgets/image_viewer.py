"""
Image Viewer Module

Dialog for viewing full-size images.
"""

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QDialog, QVBoxLayout, QScrollArea, QLabel, QPushButton, QHBoxLayout

from client.core.config_backend import get_config


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
        self.setWindowTitle("Image Viewer")
        self.setMinimumSize(600, 400)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area for image
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Image label
        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._load_image()

        self.scroll_area.setWidget(self.image_label)

        # Close button
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)

        main_layout.addWidget(self.scroll_area)
        main_layout.addLayout(button_layout)

    def _load_image(self) -> None:
        """Load and display image."""
        source = self._resolve_image_source(self._image_path)
        pixmap = QPixmap(source)

        if pixmap.isNull():
            if source.startswith(("http://", "https://")):
                reply = self._network_manager.get(QNetworkRequest(QUrl(source)))
                reply.setProperty("image_source", source)
                self.image_label.setText("Loading image...")
                return

            self.image_label.setText("Failed to load image")
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
            api_base = get_config().server.api_base_url.rstrip("/")
            host_base = api_base[:-4] if api_base.endswith("/api") else api_base
            return f"{host_base}{value}"
        return value

    def _on_image_loaded(self, reply: QNetworkReply) -> None:
        """Handle async remote image loading."""
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.image_label.setText("Failed to load image")
                return

            pixmap = QPixmap()
            if not pixmap.loadFromData(bytes(reply.readAll())):
                self.image_label.setText("Failed to load image")
                return

            self.image_label.setPixmap(pixmap)
        finally:
            reply.deleteLater()

    def keyPressEvent(self, event) -> None:
        """Handle key press."""
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        super().keyPressEvent(event)
