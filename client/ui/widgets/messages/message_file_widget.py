"""
Message File Widget Module

Widget for displaying file messages.
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout
from PySide6.QtCore import Signal, Qt

from qfluentwidgets import AvatarWidget, BodyLabel, CaptionLabel, IconWidget, PrimaryPushButton

from client.core.i18n import format_file_size, tr


class MessageFileWidget(QWidget):
    """
    File message widget.

    UI (Self - Right):
        [Bubble with File Icon + Name + Size] [Avatar]
        
    UI (Other - Left):
        [Avatar] [Bubble with File Icon + Name + Size]
    """

    clicked = Signal()
    download_clicked = Signal(str)

    MAX_WIDTH = 300

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

        self.bubble = self._create_file_bubble()
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

        self.bubble = self._create_file_bubble()
        self.main_layout.addWidget(self.bubble, 0)

        self.main_layout.addStretch(1)

    def _create_file_bubble(self) -> QWidget:
        """Create file message bubble widget."""
        bubble = QWidget(self)
        bubble.setMaximumWidth(self.MAX_WIDTH)
        bubble.setObjectName("fileBubble")

        layout = QVBoxLayout(bubble)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        file_info_layout = QHBoxLayout()
        file_info_layout.setSpacing(8)

        self.file_icon = IconWidget(self)
        self.file_icon.setFixedSize(32, 32)
        file_info_layout.addWidget(self.file_icon)

        self.file_name = BodyLabel(self._get_file_name(), bubble)
        self.file_name.setMaximumWidth(200)
        self.file_name.setWordWrap(True)
        file_info_layout.addWidget(self.file_name, 1)

        layout.addLayout(file_info_layout)

        self.file_size = CaptionLabel(self._get_file_size(), bubble)
        layout.addWidget(self.file_size, 0, Qt.AlignmentFlag.AlignLeft)

        self.download_btn = PrimaryPushButton(tr("common.download", "Download"), bubble)
        self.download_btn.setFixedSize(80, 28)
        self.download_btn.clicked.connect(self._on_download_clicked)
        layout.addWidget(self.download_btn, 0, Qt.AlignmentFlag.AlignRight)

        return bubble

    def _get_file_name(self) -> str:
        """Extract file name from message content."""
        if self._message and self._message.extra:
            return self._message.extra.get("name", "")
        if self._message and self._message.content:
            return self._message.content.split('/')[-1]
        return tr("attachment.unknown_file", "Unknown File")

    def _get_file_url(self) -> str:
        """Extract file URL from message content."""
        if self._message and self._message.extra:
            return self._message.extra.get("url", "")
        if self._message and self._message.content:
            return self._message.content
        return ""

    def _get_file_size(self) -> str:
        """Get file size from message extra."""
        if self._message and self._message.extra:
            size = self._message.extra.get("size", 0)
            return self._format_size(size)
        return ""

    def _format_size(self, size: int) -> str:
        """Format file size to human readable format."""
        return format_file_size(size)

    def _on_download_clicked(self) -> None:
        """Handle download button click."""
        file_url = self._get_file_url()
        if file_url:
            self.download_clicked.emit(file_url)

    def set_message(self, message) -> None:
        """Set message data."""
        self._message = message
        if hasattr(self, 'file_name'):
            self.file_name.setText(self._get_file_name())
        if hasattr(self, 'file_size'):
            self.file_size.setText(self._get_file_size())

    def set_avatar(self, avatar_path: str) -> None:
        """Set avatar image."""
        self.avatar.setImage(avatar_path)

    def get_message(self):
        """Get message data."""
        return self._message

    def is_self_message(self) -> bool:
        """Check if message is from self."""
        return self._is_self
