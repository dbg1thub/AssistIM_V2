"""Persistent group-announcement banner shown below the active chat header."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy
from qfluentwidgets import CardWidget, IconWidget

from client.core.app_icons import CollectionIcon
from client.models.message import Session
from client.ui.widgets.contact_shared import ElidedBodyLabel


class GroupAnnouncementBanner(CardWidget):
    """Clickable banner that summarizes one unread group announcement."""

    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._session: Session | None = None
        self.setObjectName("groupAnnouncementBannerCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMaximumWidth(180)
        self.setMaximumHeight(32)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.hide()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        self.icon_widget = IconWidget(CollectionIcon("megaphone"), self)
        self.icon_widget.setObjectName("groupAnnouncementBannerIcon")
        self.icon_widget.setFixedSize(15, 15)

        self.text_label = ElidedBodyLabel("", self)
        self.text_label.setObjectName("groupAnnouncementBannerText")
        self.text_label.setMinimumWidth(0)

        self.chevron_widget = IconWidget(CollectionIcon("chevron_right"), self)
        self.chevron_widget.setObjectName("groupAnnouncementBannerChevron")
        self.chevron_widget.setFixedSize(14, 14)

        layout.addWidget(self.icon_widget, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.text_label, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.chevron_widget, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_session(self, session: Session | None) -> None:
        """Refresh banner visibility and text for the active session."""
        self._session = session
        if session is None or not session.group_announcement_needs_view():
            self.text_label.setText("")
            self.setToolTip("")
            self.hide()
            return

        announcement = session.group_announcement_text()
        self.text_label.setText(announcement)
        self.setToolTip(announcement)
        self.show()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Emit one click signal when the card is activated with the left button."""
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
