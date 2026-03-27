from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import HyperlinkButton, isDarkTheme
from qfluentwidgets.components.material import AcrylicFlyoutViewBase

from client.core.avatar_rendering import get_avatar_image_store
from client.core.avatar_utils import profile_avatar_seed
from client.core.i18n import tr
from client.ui.widgets.fluent_divider import FluentDivider


@dataclass
class TrayAlertEntry:
    """One tray-alert session row."""

    session_id: str
    name: str
    avatar: str = ""
    unread_count: int = 0
    counterpart_id: str = ""
    counterpart_username: str = ""


class TrayAlertAvatar(QWidget):
    """Compact avatar with an unread badge overlay."""

    def __init__(self, size: int = 36, parent=None) -> None:
        super().__init__(parent)
        self._size = size
        self._radius = max(8, size // 4)
        self._pixmap: Optional[QPixmap] = None
        self._fallback = "?"
        self._avatar_source = ""
        self._avatar_seed = ""
        self._unread_count = 0
        self._avatar_store = get_avatar_image_store()
        self._avatar_store.avatar_ready.connect(self._on_avatar_ready)
        self.setFixedSize(size, size)

    def set_entry(self, entry: TrayAlertEntry) -> None:
        self._fallback = (entry.name or "?").strip()[:2].upper() or "?"
        self._avatar_seed = profile_avatar_seed(
            user_id=entry.counterpart_id,
            username=entry.counterpart_username,
            display_name=entry.name,
            fallback=entry.session_id,
        )
        self._unread_count = max(0, int(entry.unread_count or 0))
        self._avatar_source, resolved = self._avatar_store.resolve_display_path(
            entry.avatar,
            seed=self._avatar_seed,
        )
        self._apply_avatar_path(resolved)

    def _apply_avatar_path(self, avatar_path: str) -> None:
        self._pixmap = None
        if avatar_path:
            pixmap = QPixmap(avatar_path)
            if not pixmap.isNull():
                self._pixmap = pixmap
        self.update()

    def _on_avatar_ready(self, source: str) -> None:
        if source != self._avatar_source:
            return
        resolved = self._avatar_store.display_path_for_source(source, seed=self._avatar_seed)
        self._apply_avatar_path(resolved)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        avatar_rect = rect.adjusted(0, 0, 0, 0)
        clip = QPainterPath()
        clip.addRoundedRect(avatar_rect, self._radius, self._radius)
        painter.setClipPath(clip)

        if self._pixmap is not None:
            scaled = self._pixmap.scaled(
                avatar_rect.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(avatar_rect, scaled)
        else:
            painter.fillPath(clip, QColor("#626B76") if isDarkTheme() else QColor("#D7DEE8"))
            painter.setClipping(False)
            font = QFont()
            font.setBold(True)
            font.setPixelSize(max(11, self._size // 3))
            painter.setFont(font)
            painter.setPen(QColor("#FFFFFF") if isDarkTheme() else QColor("#27486B"))
            painter.drawText(avatar_rect, Qt.AlignmentFlag.AlignCenter, self._fallback)

        painter.setClipping(False)
        if self._unread_count <= 0:
            return

        badge_text = "99+" if self._unread_count > 99 else str(self._unread_count)
        badge_font = QFont()
        badge_font.setBold(True)
        badge_font.setPixelSize(10)
        painter.setFont(badge_font)
        metrics = painter.fontMetrics()
        badge_width = max(14, metrics.horizontalAdvance(badge_text) + 8)
        badge_rect = rect.adjusted(rect.width() - badge_width, 0, 0, -(rect.height() - 14))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FF4D4F"))
        painter.drawRoundedRect(badge_rect, 7, 7)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)


class ElidedTrayNameLabel(QLabel):
    """Single-line elided label used by tray-alert rows."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__("", parent)
        self._full_text = ""
        self.setWordWrap(False)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        font = QFont(self.font())
        font.setPixelSize(14)
        self.setFont(font)
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full_text = text or ""
        self._refresh_text()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_text()

    def _refresh_text(self) -> None:
        available = max(0, self.contentsRect().width())
        display = self._full_text
        if available > 0:
            display = self.fontMetrics().elidedText(display, Qt.TextElideMode.ElideRight, available)
        super().setText(display)
        self.setToolTip(self._full_text if display != self._full_text else "")


class TrayAlertRow(QWidget):
    """Clickable session row shown inside the tray flyout."""

    activated = Signal(str)

    def __init__(self, entry: TrayAlertEntry, parent=None) -> None:
        super().__init__(parent)
        self._entry = entry
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        self.avatar = TrayAlertAvatar(36, self)
        self.name_label = ElidedTrayNameLabel(entry.name, self)

        layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.name_label, 1, Qt.AlignmentFlag.AlignVCenter)
        self.set_entry(entry)

    def set_entry(self, entry: TrayAlertEntry) -> None:
        self._entry = entry
        self.avatar.set_entry(entry)
        self.name_label.setText(entry.name or tr("session.unnamed", "Untitled Session"))
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self._entry.session_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hovered:
            painter.fillRect(
                self.rect(),
                QColor(255, 255, 255, 16) if isDarkTheme() else QColor(0, 0, 0, 12),
            )


class TrayIgnoreButton(HyperlinkButton):
    """Hyperlink button without a heavy hover state."""

    def enterEvent(self, event) -> None:
        self.isHover = False
        self.update()
        event.accept()

    def leaveEvent(self, event) -> None:
        self.isHover = False
        self.update()
        event.accept()


class TrayMessageFlyoutView(AcrylicFlyoutViewBase):
    """Acrylic flyout that lists unread tray-alert sessions."""

    sessionActivated = Signal(str)
    ignoreRequested = Signal()
    hoverEntered = Signal()
    hoverLeft = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[TrayAlertEntry] = []
        self._rows: list[TrayAlertRow] = []

        self.v_box_layout = QVBoxLayout(self)
        self.v_box_layout.setContentsMargins(0, 0, 0, 0)
        self.v_box_layout.setSpacing(0)

        self.rows_container = QWidget(self)
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(0)

        self.footer_divider = FluentDivider(self, variant=FluentDivider.FULL, left_inset=0, right_inset=0)
        self.footer = QWidget(self)
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(0, 6, 0, 8)
        footer_layout.setSpacing(0)
        footer_layout.addStretch(1)

        self.ignore_button = TrayIgnoreButton(self.footer)
        self.ignore_button.setText(tr("main_window.tray.ignore", "Ignore for now"))
        self.ignore_button.clicked.connect(self.ignoreRequested.emit)
        footer_layout.addWidget(self.ignore_button, 0, Qt.AlignmentFlag.AlignCenter)
        footer_layout.addStretch(1)

        self.v_box_layout.addWidget(self.rows_container)
        self.v_box_layout.addWidget(self.footer_divider)
        self.v_box_layout.addWidget(self.footer)
        self.setFixedWidth(280)

    def set_entries(self, entries: list[TrayAlertEntry]) -> None:
        self._entries = list(entries)
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows.clear()

        for index, entry in enumerate(self._entries):
            row = TrayAlertRow(entry, self.rows_container)
            row.activated.connect(self.sessionActivated.emit)
            self.rows_layout.addWidget(row)
            self._rows.append(row)
            if index < len(self._entries) - 1:
                self.rows_layout.addWidget(
                    FluentDivider(self.rows_container, variant=FluentDivider.FULL, left_inset=14, right_inset=14)
                )

        self.rows_container.setVisible(bool(self._entries))
        self.footer_divider.setVisible(bool(self._entries))
        self.adjustSize()

    def enterEvent(self, event) -> None:
        self.hoverEntered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.hoverLeft.emit()
        super().leaveEvent(event)
