"""Compact bottom-right incoming-call reminder."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, FluentIcon as FIF, ToolButton

from client.ui.widgets.contact_shared import ContactAvatar


class IncomingCallToast(QWidget):
    """Small always-on-top toast shown above the taskbar for incoming calls."""

    accepted = Signal()
    rejected = Signal()

    def __init__(self, *, peer_name: str, subtitle: str, avatar: str = "", avatar_seed: str = "", parent=None) -> None:
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("incomingCallToast")
        self.resize(332, 104)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = QWidget(self)
        card.setObjectName("incomingCallToastCard")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(12)

        self.avatar = ContactAvatar(42, card)
        self.avatar.set_avatar(avatar, fallback=(peer_name or "?")[:1], seed=avatar_seed)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)

        self.name_label = BodyLabel(peer_name, card)
        self.name_label.setObjectName("incomingCallToastName")
        self.subtitle_label = CaptionLabel(subtitle, card)
        self.subtitle_label.setObjectName("incomingCallToastSubtitle")
        self.subtitle_label.setWordWrap(True)

        text_layout.addWidget(self.name_label)
        text_layout.addWidget(self.subtitle_label)
        text_layout.addStretch(1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)

        self.reject_button = ToolButton(FIF.PHONE, card)
        self.reject_button.setObjectName("incomingCallToastReject")
        self.reject_button.setFixedSize(40, 40)
        self.reject_button.clicked.connect(self.rejected.emit)

        self.accept_button = ToolButton(FIF.ACCEPT_MEDIUM, card)
        self.accept_button.setObjectName("incomingCallToastAccept")
        self.accept_button.setFixedSize(40, 40)
        self.accept_button.clicked.connect(self.accepted.emit)

        actions.addWidget(self.reject_button)
        actions.addWidget(self.accept_button)

        card_layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)
        card_layout.addLayout(text_layout, 1)
        card_layout.addLayout(actions, 0)
        root.addWidget(card)

        self.setStyleSheet(
            """
            QWidget#incomingCallToastCard {
                background: rgba(56, 53, 53, 244);
                border-radius: 12px;
            }
            QLabel#incomingCallToastName {
                color: white;
                font-size: 15px;
                font-weight: 600;
            }
            QLabel#incomingCallToastSubtitle {
                color: rgba(255, 255, 255, 0.78);
                font-size: 13px;
            }
            QToolButton#incomingCallToastReject {
                background: #ff5a5f;
                border: none;
                border-radius: 20px;
                color: white;
            }
            QToolButton#incomingCallToastReject:hover {
                background: #ff6b70;
            }
            QToolButton#incomingCallToastAccept {
                background: #1fc96b;
                border: none;
                border-radius: 20px;
                color: white;
            }
            QToolButton#incomingCallToastAccept:hover {
                background: #32d87c;
            }
            """
        )

    def showEvent(self, event) -> None:
        """Place the toast above the taskbar on the most relevant screen."""
        super().showEvent(event)
        self._move_to_corner()

    def _move_to_corner(self) -> None:
        """Anchor the toast to the bottom-right of the active screen work area."""
        parent_window = self.parentWidget().window() if self.parentWidget() is not None else None
        anchor_point = parent_window.frameGeometry().center() if parent_window is not None else QGuiApplication.primaryScreen().geometry().center()
        screen = QGuiApplication.screenAt(anchor_point) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        margin = 16
        x = geometry.right() - self.width() - margin
        y = geometry.bottom() - self.height() - margin
        self.move(QPoint(x, y))
