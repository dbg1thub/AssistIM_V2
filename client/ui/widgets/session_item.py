"""
Session Item Widget Module

Widget for displaying a single session in the session list.
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout
from PySide6.QtCore import Qt

from qfluentwidgets import AvatarWidget, BodyLabel, CaptionLabel, Badge

from client.core.avatar_rendering import apply_avatar_widget_image
from client.core.i18n import tr


class SessionItem(QWidget):
    """
    Session list item widget.

    UI:
        [头像] 用户名 未读数
              最后一条消息         时间
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Setup UI components."""
        # Main layout
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(12, 8, 12, 8)
        self.main_layout.setSpacing(12)

        # Avatar
        self.avatar = AvatarWidget(self)
        self.avatar.setRadius(24)

        # Content area
        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(2)
        self.content_layout.setContentsMargins(0, 0, 0, 0)

        # Top row: name + time + unread
        self.top_layout = QHBoxLayout()
        self.top_layout.setSpacing(8)

        self.name_label = BodyLabel(self)
        self.name_label.setText(tr("session.unnamed", "Untitled Session"))

        self.time_label = CaptionLabel(self)
        self.time_label.setText("")

        self.top_layout.addWidget(self.name_label, 1)
        self.top_layout.addWidget(self.time_label, 0)

        # Unread badge
        self.unread_badge = Badge()
        self.unread_badge.setText("")
        self.top_layout.addWidget(self.unread_badge, 0)

        # Bottom row: last message
        self.last_message_label = CaptionLabel(self)
        self.last_message_label.setText("")
        self.last_message_label.setElideMode(Qt.TextElideMode.ElideRight)

        # Add to content layout
        self.content_layout.addLayout(self.top_layout)
        self.content_layout.addWidget(self.last_message_label, 1)

        # Add to main layout
        self.main_layout.addWidget(self.avatar, 0)
        self.main_layout.addLayout(self.content_layout, 1)

    def set_name(self, name: str) -> None:
        """Set session name."""
        self.name_label.setText(name)

    def set_last_message(self, message: str) -> None:
        """Set last message preview."""
        self.last_message_label.setText(message)

    def set_time(self, time_text: str) -> None:
        """Set time text."""
        self.time_label.setText(time_text)

    def set_unread_count(self, count: int) -> None:
        """Set unread count."""
        if count > 0:
            self.unread_badge.setText(str(count) if count <= 99 else "99+")
            self.unread_badge.setVisible(True)
        else:
            self.unread_badge.setVisible(False)

    def set_avatar(self, avatar_path: str, *, gender: str = "", seed: str = "") -> None:
        """Set avatar image path."""
        apply_avatar_widget_image(self.avatar, avatar_path, gender=gender, seed=seed)

