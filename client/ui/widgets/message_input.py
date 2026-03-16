"""Message composer with an integrated toolbar and input surface."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import QFileDialog, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    Flyout,
    FlyoutAnimationType,
    FlyoutViewBase,
    FluentIcon,
    InfoBar,
    PrimaryPushButton,
    PushButton,
    TextEdit,
    TransparentToolButton,
)


class ChatTextEdit(TextEdit):
    """Text editor that sends on Enter and inserts a newline on Shift+Enter."""

    send_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Emit send on Enter without modifiers."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            event.accept()
            self.send_requested.emit()
            return

        super().keyPressEvent(event)


class EmojiPickerFlyout(FlyoutViewBase):
    """Compact emoji picker used by the message input toolbar."""

    emoji_selected = Signal(str)

    EMOJIS = [
        "😀",
        "😁",
        "😂",
        "🤣",
        "😊",
        "😍",
        "😘",
        "😎",
        "🤔",
        "😴",
        "😭",
        "😡",
        "👍",
        "👀",
        "🎉",
        "❤️",
        "🔥",
        "✨",
        "🙏",
        "💡",
        "📷",
        "🎵",
        "🌙",
        "🌟",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.view_layout = QVBoxLayout(self)
        self.view_layout.setContentsMargins(12, 12, 12, 12)
        self.view_layout.setSpacing(10)

        title = BodyLabel("Emoji", self)
        self.view_layout.addWidget(title)

        grid_widget = QWidget(self)
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setHorizontalSpacing(6)
        grid_layout.setVerticalSpacing(6)

        for index, emoji in enumerate(self.EMOJIS):
            button = PushButton(emoji, grid_widget)
            button.setFixedSize(44, 36)
            button.clicked.connect(lambda _checked=False, value=emoji: self.emoji_selected.emit(value))
            grid_layout.addWidget(button, index // 8, index % 8)

        self.view_layout.addWidget(grid_widget)


class MessageInput(QWidget):
    """Integrated message input surface."""

    send_clicked = Signal(str)
    image_selected = Signal(str)
    file_selected = Signal(str)
    screenshot_requested = Signal()
    voice_call_requested = Signal()
    video_call_requested = Signal()
    typing_signal = Signal()

    IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp)"
    FILE_FILTER = "All Files (*.*)"
    TYPING_THROTTLE = 3.0

    def __init__(self, parent=None):
        super().__init__(parent)

        self._last_typing_time = 0.0
        self._session_active = False
        self._setup_ui()
        self._connect_signals()
        self.set_session_active(False)

    def _setup_ui(self) -> None:
        self.setObjectName("messageInput")

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(16, 10, 16, 14)
        self.main_layout.setSpacing(0)

        self.editor_card = CardWidget(self)
        self.editor_card.setObjectName("messageInputCard")

        self.card_layout = QVBoxLayout(self.editor_card)
        self.card_layout.setContentsMargins(12, 10, 12, 10)
        self.card_layout.setSpacing(0)

        self.composer_widget = QWidget(self.editor_card)
        self.composer_widget.setObjectName("messageComposer")
        self.composer_layout = QVBoxLayout(self.composer_widget)
        self.composer_layout.setContentsMargins(0, 0, 0, 0)
        self.composer_layout.setSpacing(6)

        self.toolbar_layout = QHBoxLayout()
        self.toolbar_layout.setContentsMargins(0, 0, 0, 0)
        self.toolbar_layout.setSpacing(4)

        self.emoji_button = TransparentToolButton(FluentIcon.EMOJI_TAB_SYMBOLS, self.composer_widget)
        self.emoji_button.setFixedSize(28, 28)
        self.emoji_button.setToolTip("Emoji")

        self.image_button = TransparentToolButton(FluentIcon.PHOTO, self.composer_widget)
        self.image_button.setFixedSize(28, 28)
        self.image_button.setToolTip("Send image")

        self.file_button = TransparentToolButton(FluentIcon.FOLDER, self.composer_widget)
        self.file_button.setFixedSize(28, 28)
        self.file_button.setToolTip("Send file")

        self.cut_button = TransparentToolButton(FluentIcon.CUT, self.composer_widget)
        self.cut_button.setFixedSize(28, 28)
        self.cut_button.setToolTip("Screenshot")

        self.voice_button = TransparentToolButton(FluentIcon.PHONE, self.composer_widget)
        self.voice_button.setFixedSize(28, 28)
        self.voice_button.setToolTip("Voice call")

        self.video_button = TransparentToolButton(FluentIcon.VIDEO, self.composer_widget)
        self.video_button.setFixedSize(28, 28)
        self.video_button.setToolTip("Video call")

        self.ai_button = TransparentToolButton(FluentIcon.ROBOT, self.composer_widget)
        self.ai_button.setFixedSize(28, 28)
        self.ai_button.setToolTip("AI assistant")

        self._apply_safe_button_font(
            self.emoji_button,
            self.image_button,
            self.file_button,
            self.cut_button,
            self.voice_button,
            self.video_button,
            self.ai_button,
        )

        self.toolbar_layout.addWidget(self.emoji_button)
        self.toolbar_layout.addWidget(self.image_button)
        self.toolbar_layout.addWidget(self.file_button)
        self.toolbar_layout.addWidget(self.cut_button)
        self.toolbar_layout.addWidget(self.voice_button)
        self.toolbar_layout.addWidget(self.video_button)
        self.toolbar_layout.addWidget(self.ai_button)
        self.toolbar_layout.addStretch(1)

        self.text_input = ChatTextEdit(self.composer_widget)
        self.text_input.setObjectName("chatMessageEdit")
        self.text_input.setPlaceholderText("Select a session to start chatting")
        self.text_input.setAcceptRichText(False)
        self.text_input.setMinimumHeight(128)
        self.text_input.setMaximumHeight(210)
        self.text_input.setViewportMargins(0, 0, 0, 42)

        self.hint_label = CaptionLabel("Enter to send, Shift+Enter for new line", self.composer_widget)
        self.hint_label.setObjectName("messageInputHint")

        self.send_button = PrimaryPushButton("Send", self.composer_widget)
        self.send_button.setFixedSize(84, 34)

        self.composer_layout.addLayout(self.toolbar_layout)
        self.composer_layout.addWidget(self.text_input, 1)
        self.card_layout.addWidget(self.composer_widget)
        self.main_layout.addWidget(self.editor_card)

        self.setStyleSheet(
            """
            QWidget#messageInput {
                background: transparent;
            }
            CardWidget#messageInputCard {
                background: rgba(255, 255, 255, 0.96);
                border: 1px solid rgba(15, 23, 42, 0.08);
                border-radius: 18px;
            }
            QWidget#messageComposer {
                background: transparent;
            }
            TextEdit#chatMessageEdit {
                background: transparent;
                border: none;
                padding: 4px 2px;
            }
            QLabel#messageInputHint {
                color: rgba(71, 85, 105, 0.82);
                background: transparent;
            }
            """
        )

        self._update_overlay_positions()

    def _apply_safe_button_font(self, *buttons: TransparentToolButton) -> None:
        """Ensure toolbar buttons expose a valid point-size font for tooltip rendering."""
        font = QFont(self.font())
        if font.pointSize() <= 0:
            if font.pixelSize() > 0:
                font.setPointSize(max(9, round(font.pixelSize() * 0.75)))
            else:
                font.setPointSize(10)

        for button in buttons:
            button.setFont(font)

    def _connect_signals(self) -> None:
        self.send_button.clicked.connect(self._on_send_clicked)
        self.emoji_button.clicked.connect(self._on_emoji_clicked)
        self.image_button.clicked.connect(self._on_image_clicked)
        self.file_button.clicked.connect(self._on_file_clicked)
        self.cut_button.clicked.connect(self.screenshot_requested.emit)
        self.voice_button.clicked.connect(self.voice_call_requested.emit)
        self.video_button.clicked.connect(self.video_call_requested.emit)
        self.ai_button.clicked.connect(self._on_placeholder_action)
        self.text_input.textChanged.connect(self._on_text_changed)
        self.text_input.send_requested.connect(self._on_send_clicked)

    def resizeEvent(self, event) -> None:
        """Keep the floating footer aligned with the text input."""
        super().resizeEvent(event)
        self._update_overlay_positions()

    def _update_overlay_positions(self) -> None:
        """Place hint and send button inside the text input area."""
        text_rect = self.text_input.geometry()
        if not text_rect.isValid():
            return

        button_margin_right = 10
        button_margin_bottom = 8
        send_x = text_rect.right() - self.send_button.width() - button_margin_right
        send_y = text_rect.bottom() - self.send_button.height() - button_margin_bottom
        self.send_button.move(send_x, send_y)

        self.hint_label.adjustSize()
        hint_x = text_rect.x() + 10
        hint_y = text_rect.bottom() - self.hint_label.height() - 16
        self.hint_label.move(hint_x, hint_y)

        self.hint_label.raise_()
        self.send_button.raise_()

    def _on_text_changed(self) -> None:
        """Emit throttled typing events."""
        current_time = time.time()
        if current_time - self._last_typing_time >= self.TYPING_THROTTLE:
            self._last_typing_time = current_time
            self.typing_signal.emit()

    def _on_send_clicked(self) -> None:
        """Send text content if the editor is not empty."""
        text = self.text_input.toPlainText().strip()
        if not text:
            return

        self.send_clicked.emit(text)
        self.text_input.clear()

    def _on_emoji_clicked(self) -> None:
        """Show emoji picker flyout."""
        picker = EmojiPickerFlyout(self)
        picker.emoji_selected.connect(self._insert_emoji)
        Flyout.make(
            picker,
            self.emoji_button,
            self,
            aniType=FlyoutAnimationType.PULL_UP,
        )

    def _insert_emoji(self, emoji: str) -> None:
        """Insert emoji at current cursor position."""
        cursor = self.text_input.textCursor()
        cursor.insertText(emoji)
        self.text_input.setTextCursor(cursor)
        self.text_input.setFocus()

    def _on_image_clicked(self) -> None:
        """Open image picker dialog."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select image", "", self.IMAGE_FILTER)
        if file_path:
            self.image_selected.emit(file_path)

    def _on_file_clicked(self) -> None:
        """Open file picker dialog."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select file", "", self.FILE_FILTER)
        if file_path:
            self.file_selected.emit(file_path)

    def _on_placeholder_action(self) -> None:
        """Show temporary placeholder hint for unsupported toolbar actions."""
        InfoBar.info(
            "Notice",
            "This toolbar action is not connected yet.",
            parent=self.window(),
            duration=1800,
        )

    def set_session_active(self, active: bool) -> None:
        """Enable or disable the editor depending on session selection."""
        self._session_active = active

        self.emoji_button.setEnabled(active)
        self.image_button.setEnabled(active)
        self.file_button.setEnabled(active)
        self.cut_button.setEnabled(active)
        self.voice_button.setEnabled(active)
        self.video_button.setEnabled(active)
        self.ai_button.setEnabled(active)
        self.text_input.setEnabled(active)
        self.send_button.setEnabled(active)

        if active:
            self.text_input.setPlaceholderText("Type a message...")
        else:
            self.text_input.setPlaceholderText("Select a session to start chatting")
            self.text_input.clear()

    def focus_editor(self) -> None:
        """Focus the text editor."""
        if self._session_active:
            self.text_input.setFocus()

    def get_text_input(self) -> TextEdit:
        """Get text input widget."""
        return self.text_input

    def get_send_button(self) -> PrimaryPushButton:
        """Get send button widget."""
        return self.send_button

    def get_emoji_button(self) -> TransparentToolButton:
        """Get emoji button widget."""
        return self.emoji_button

    def get_file_button(self) -> TransparentToolButton:
        """Get file button widget."""
        return self.file_button

    def get_image_button(self) -> TransparentToolButton:
        """Get image button widget."""
        return self.image_button
