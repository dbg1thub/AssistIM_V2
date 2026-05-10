"""Reusable empty-state card used by page placeholders."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, CardWidget


_DEFAULT_LOGO_PATH = Path(__file__).resolve().parents[2] / "resources" / "logo.png"


class EmptyStateCard(CardWidget):
    """Small centered card for page-level empty and welcome states."""

    def __init__(
        self,
        *,
        title: str,
        subtitle: str = "",
        hint: str = "",
        logo_path: str | Path = _DEFAULT_LOGO_PATH,
        logo_size: int = 56,
        title_pixel_size: int = 22,
        min_width: int = 360,
        max_width: int = 540,
        alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("EmptyStateCard")
        self.setBorderRadius(8)
        self.setMinimumWidth(min_width)
        self.setMaximumWidth(max_width)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 36, 36, 36)
        layout.setSpacing(14)
        layout.setAlignment(alignment)

        self.logo_label = QLabel(self)
        self.logo_label.setObjectName("EmptyStateLogo")
        self.logo_label.setFixedSize(logo_size, logo_size)
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_logo_pixmap(Path(logo_path), logo_size)

        self.title_label = BodyLabel(title, self)
        self.title_label.setObjectName("EmptyStateTitle")
        title_font = QFont(self.title_label.font())
        title_font.setPixelSize(title_pixel_size)
        title_font.setBold(False)
        self.title_label.setFont(title_font)
        self.title_label.setAlignment(alignment)

        layout.addWidget(self.logo_label, 0, alignment)
        layout.addWidget(self.title_label, 0, alignment)

        self.subtitle_label: CaptionLabel | None = None
        if subtitle:
            self.subtitle_label = CaptionLabel(subtitle, self)
            self.subtitle_label.setObjectName("EmptyStateSubtitle")
            self.subtitle_label.setWordWrap(True)
            self.subtitle_label.setAlignment(alignment)
            self.subtitle_label.setMaximumWidth(max_width - 72)
            layout.addWidget(self.subtitle_label, 0, alignment)

        self.hint_label: CaptionLabel | None = None
        if hint:
            self.hint_label = CaptionLabel(hint, self)
            self.hint_label.setObjectName("EmptyStateHint")
            self.hint_label.setWordWrap(True)
            self.hint_label.setAlignment(alignment)
            self.hint_label.setMaximumWidth(max_width - 72)
            layout.addWidget(self.hint_label, 0, alignment)

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
