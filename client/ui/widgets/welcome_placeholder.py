"""Reusable logo-and-title placeholder for page welcome states."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel


_DEFAULT_LOGO_PATH = Path(__file__).resolve().parents[2] / "resources" / "logo.png"


class WelcomePlaceholder(QWidget):
    """Centered transparent placeholder that mirrors the chat welcome layout."""

    def __init__(
        self,
        *,
        title: str,
        object_name: str = "WelcomePlaceholder",
        logo_path: str | Path = _DEFAULT_LOGO_PATH,
        logo_size: int = 160,
        title_pixel_size: int = 32,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.logo_label = QLabel(self)
        self.logo_label.setObjectName("welcomePlaceholderLogo")
        self.logo_label.setFixedSize(logo_size, logo_size)
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_logo_pixmap(Path(logo_path), logo_size)

        self.title_label = BodyLabel(title, self)
        self.title_label.setObjectName("welcomePlaceholderTitle")
        title_font = QFont(self.title_label.font())
        title_font.setPixelSize(title_pixel_size)
        title_font.setBold(False)
        self.title_label.setFont(title_font)

        layout.addWidget(self.logo_label, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignCenter)

    def _set_logo_pixmap(self, logo_path: Path, logo_size: int) -> None:
        pixmap = QPixmap(str(logo_path))
        if pixmap.isNull():
            self.logo_label.clear()
            return

        self.logo_label.setPixmap(
            pixmap.scaled(
                logo_size,
                logo_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
