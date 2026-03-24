"""
Message Image Widget Module

Widget for displaying image messages.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout
from PySide6.QtGui import QPixmap

from qfluentwidgets import AvatarWidget, StateLabel, IconWidget

from client.core.avatar_utils import choose_avatar_image


class MessageImageWidget(QWidget):
    """
    Image message widget.

    UI (Self - Right):
        [Bubble with Image] [Avatar]
        
    UI (Other - Left):
        [Avatar] [Bubble with Image]
    """

    clicked = Signal(str)
    image_clicked = Signal(str)

    MAX_WIDTH = 250
    MAX_HEIGHT = 200

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

        self.bubble = self._create_image_bubble()
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

        self.bubble = self._create_image_bubble()
        self.main_layout.addWidget(self.bubble, 0)

        self.main_layout.addStretch(1)

    def _create_image_bubble(self) -> QWidget:
        """Create image message bubble widget."""
        bubble = QWidget(self)
        bubble.setMaximumWidth(self.MAX_WIDTH + 20)
        bubble.setMaximumHeight(self.MAX_HEIGHT + 20)
        bubble.setObjectName("imageBubble")

        layout = QVBoxLayout(bubble)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        self.image_label = StateLabel(bubble)
        self.image_label.setFixedSize(self.MAX_WIDTH, self.MAX_HEIGHT)
        self.image_label.setScaledContents(False)

        if self._message and self._message.content:
            pixmap = QPixmap(self._message.content)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self.MAX_WIDTH, self.MAX_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.image_label.setPixmap(scaled)

        layout.addWidget(self.image_label)

        return bubble

    def set_message(self, message) -> None:
        """Set message data."""
        self._message = message
        if hasattr(self, 'image_label') and message and message.content:
            pixmap = QPixmap(message.content)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self.MAX_WIDTH, self.MAX_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.image_label.setPixmap(scaled)

    def set_avatar(self, avatar_path: str, *, gender: str = "", seed: str = "") -> None:
        """Set avatar image."""
        self.avatar.setImage(choose_avatar_image(avatar_path, gender=gender, seed=seed))

    def get_message(self):
        """Get message data."""
        return self._message

    def is_self_message(self) -> bool:
        """Check if message is from self."""
        return self._is_self
