"""
Message Video Widget Module

Widget for displaying video messages.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout
from PySide6.QtGui import QPixmap, QIcon

from qfluentwidgets import AvatarWidget, StateLabel, IconWidget, BodyLabel

from client.core.avatar_rendering import apply_avatar_widget_image
from client.ui.styles import StyleSheet


class MessageVideoWidget(QWidget):
    """
    Video message widget.

    UI (Self - Right):
        [Bubble with Video Thumbnail + Play Button] [Avatar]
        
    UI (Other - Left):
        [Avatar] [Bubble with Video Thumbnail + Play Button]
    """

    clicked = Signal()
    play_clicked = Signal(str)

    MAX_WIDTH = 280
    MAX_HEIGHT = 180

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

        self.bubble = self._create_video_bubble()
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

        self.bubble = self._create_video_bubble()
        self.main_layout.addWidget(self.bubble, 0)

        self.main_layout.addStretch(1)

    def _create_video_bubble(self) -> QWidget:
        """Create video message bubble widget."""
        bubble = QWidget(self)
        bubble.setMaximumWidth(self.MAX_WIDTH + 20)
        bubble.setObjectName("videoBubble")

        layout = QVBoxLayout(bubble)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.thumbnail_container = QWidget(bubble)
        self.thumbnail_container.setFixedSize(self.MAX_WIDTH, self.MAX_HEIGHT)

        thumbnail_layout = QVBoxLayout(self.thumbnail_container)
        thumbnail_layout.setContentsMargins(0, 0, 0, 0)

        self.thumbnail = StateLabel(self.thumbnail_container)
        self.thumbnail.setFixedSize(self.MAX_WIDTH, self.MAX_HEIGHT)
        self.thumbnail.setScaledContents(False)

        if self._message and self._message.content:
            pixmap = QPixmap(self._message.content)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self.MAX_WIDTH, self.MAX_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.thumbnail.setPixmap(scaled)

        thumbnail_layout.addWidget(self.thumbnail)

        self.play_button = IconWidget(self.thumbnail_container)
        self.play_button.setFixedSize(48, 48)
        self.play_button.clicked.connect(self._on_play_clicked)

        self.duration_label = BodyLabel(self._get_duration(), self.thumbnail_container)
        self.duration_label.setObjectName("videoDurationLabel")
        self.duration_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.duration_label.move(self.MAX_WIDTH - 70, self.MAX_HEIGHT - 30)

        layout.addWidget(self.thumbnail_container)
        StyleSheet.MESSAGE_VIDEO_WIDGET.apply(self)

        return bubble

    def _get_duration(self) -> str:
        """Get video duration from message extra."""
        if self._message and self._message.extra:
            duration = self._message.extra.get("duration", 0)
            minutes = duration // 60
            seconds = duration % 60
            return f"{minutes:02d}:{seconds:02d}"
        return "00:00"

    def _on_play_clicked(self) -> None:
        """Handle play button click."""
        if self._message and self._message.content:
            self.play_clicked.emit(self._message.content)

    def set_message(self, message) -> None:
        """Set message data."""
        self._message = message
        if hasattr(self, 'thumbnail') and message and message.content:
            pixmap = QPixmap(message.content)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self.MAX_WIDTH, self.MAX_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.thumbnail.setPixmap(scaled)
        if hasattr(self, 'duration_label'):
            self.duration_label.setText(self._get_duration())

    def set_avatar(self, avatar_path: str, *, gender: str = "", seed: str = "") -> None:
        """Set avatar image."""
        apply_avatar_widget_image(self.avatar, avatar_path, gender=gender, seed=seed)

    def get_message(self):
        """Get message data."""
        return self._message

    def is_self_message(self) -> bool:
        """Check if message is from self."""
        return self._is_self

