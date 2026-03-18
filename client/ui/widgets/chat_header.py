"""Chat header widget with session info and top-right actions."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import BodyLabel, CaptionLabel, FluentIcon, IconWidget, TransparentToolButton

from client.ui.styles import StyleSheet


class ChatHeader(QWidget):
    """Top bar showing current chat identity, status, and actions."""

    more_clicked = Signal()
    ai_summary_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setObjectName("chatHeader")

        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(20, 12, 20, 12)
        self.main_layout.setSpacing(12)

        self.avatar_widget = IconWidget(FluentIcon.PEOPLE, self)
        self.avatar_widget.setFixedSize(40, 40)

        self.info_widget = QWidget(self)
        self.info_layout = QVBoxLayout(self.info_widget)
        self.info_layout.setContentsMargins(0, 0, 0, 0)
        self.info_layout.setSpacing(2)

        self.title_label = BodyLabel("选择一个会话", self.info_widget)
        self.status_label = CaptionLabel("从左侧选择一个聊天开始对话", self.info_widget)

        self.title_label.setObjectName("chatHeaderTitle")
        self.status_label.setObjectName("chatHeaderStatus")
        self.info_layout.addWidget(self.title_label)
        self.info_layout.addWidget(self.status_label)

        self.detail_button = TransparentToolButton(FluentIcon.INFO, self)
        self.detail_button.setFixedSize(36, 36)
        self.detail_button.setToolTip("聊天详情")

        self.ai_button = TransparentToolButton(FluentIcon.ROBOT, self)
        self.ai_button.setFixedSize(36, 36)
        self.ai_button.setToolTip("AI 总结")
        self._apply_safe_button_font(self.detail_button, self.ai_button)

        self.main_layout.addWidget(self.avatar_widget, 0)
        self.main_layout.addWidget(self.info_widget, 1)
        self.main_layout.addWidget(self.detail_button, 0)
        self.main_layout.addWidget(self.ai_button, 0)

        self.detail_button.clicked.connect(self.more_clicked.emit)
        self.ai_button.clicked.connect(self.ai_summary_clicked.emit)

        StyleSheet.CHAT_HEADER.apply(self)

    def _apply_safe_button_font(self, *buttons: TransparentToolButton) -> None:
        """Ensure tooltip rendering gets a valid point-size font."""
        font = QFont(self.font())
        if font.pointSize() <= 0:
            if font.pixelSize() > 0:
                font.setPointSize(max(9, round(font.pixelSize() * 0.75)))
            else:
                font.setPointSize(10)

        for button in buttons:
            button.setFont(font)

    def set_session_info(
        self,
        title: str,
        status: str = "",
        avatar: str | None = None,
        is_ai: bool = False,
    ) -> None:
        """Set header content for the current session."""
        self.title_label.setText(title or "未命名会话")
        self.status_label.setText(status)
        self._set_avatar(avatar, is_ai=is_ai)

    def _set_avatar(self, avatar: str | None, is_ai: bool = False) -> None:
        """Update avatar icon or image."""
        if avatar and os.path.exists(avatar):
            pixmap = QPixmap(avatar)
            if not pixmap.isNull():
                self.avatar_widget.setIcon(
                    pixmap.scaled(
                        self.avatar_widget.size(),
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                return

        self.avatar_widget.setIcon(FluentIcon.ROBOT if is_ai else FluentIcon.PEOPLE)

    def set_title(self, title: str) -> None:
        """Set chat title only."""
        self.title_label.setText(title)

    def set_status(self, status: str) -> None:
        """Set status label."""
        self.status_label.setText(status)

    def get_title_label(self) -> BodyLabel:
        """Get title label widget."""
        return self.title_label

    def get_status_label(self) -> CaptionLabel:
        """Get status label widget."""
        return self.status_label

    def get_more_button(self) -> TransparentToolButton:
        """Get detail button widget."""
        return self.detail_button
