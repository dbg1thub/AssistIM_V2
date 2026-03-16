"""
Message Text Widget Module

Widget for displaying text messages.
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout
from PySide6.QtCore import Qt, Signal

from qfluentwidgets import AvatarWidget, BodyLabel, CaptionLabel


class MessageTextWidget(QWidget):
    """
    Text message widget.

    UI (Self - Right):
        [Bubble] [Avatar]
        
    UI (Other - Left):
        [Avatar] [Bubble]
    """

    clicked = Signal()

    def __init__(self, message=None, is_self: bool = False, parent=None):
        super().__init__(parent)
        self._message = message
        self._is_self = is_self
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Setup UI components."""
        if self._is_self:
            self._setup_self_ui()
        else:
            self._setup_other_ui()

    def _setup_self_ui(self) -> None:
        """Setup UI for self message (right aligned)."""
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(10, 5, 10, 5)
        self.main_layout.setSpacing(8)

        self.main_layout.addStretch(1)

        self.bubble = self._create_bubble()
        self.main_layout.addWidget(self.bubble, 0)

        self.avatar = AvatarWidget(self)
        self.avatar.setRadius(20)
        self.avatar.setFixedSize(40, 40)
        self.main_layout.addWidget(self.avatar, 0)

    def _setup_other_ui(self) -> None:
        """Setup UI for other message (left aligned)."""
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(10, 5, 10, 5)
        self.main_layout.setSpacing(8)

        self.avatar = AvatarWidget(self)
        self.avatar.setRadius(20)
        self.avatar.setFixedSize(40, 40)
        self.main_layout.addWidget(self.avatar, 0)

        self.bubble = self._create_bubble()
        self.main_layout.addWidget(self.bubble, 0)

        self.main_layout.addStretch(1)

    def _create_bubble(self) -> QWidget:
        """Create message bubble widget."""
        bubble = QWidget(self)
        bubble.setMaximumWidth(400)
        bubble.setObjectName("messageBubble")

        layout = QVBoxLayout(bubble)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        self.content_label = BodyLabel(self._message.content if self._message else "", bubble)
        self.content_label.setWordWrap(True)
        self.content_label.setTextFormat(Qt.TextFormat.PlainText)

        layout.addWidget(self.content_label)

        return bubble

    def set_message(self, message) -> None:
        """Set message data."""
        self._message = message
        if hasattr(self, 'content_label'):
            self.content_label.setText(message.content)

    def set_avatar(self, avatar_path: str) -> None:
        """Set avatar image."""
        self.avatar.setImage(avatar_path)

    def get_message(self):
        """Get message data."""
        return self._message

    def is_self_message(self) -> bool:
        """Check if message is from self."""
        return self._is_self
