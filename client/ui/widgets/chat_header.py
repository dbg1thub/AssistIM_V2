"""Chat header widget with session info, security badges, and top-right actions."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from qfluentwidgets import BodyLabel, CaptionLabel, InfoBadge, InfoLevel, TransparentToolButton

from client.core.app_icons import AppIcon, CollectionIcon
from client.core.i18n import tr
from client.ui.styles import StyleSheet
from client.ui.widgets.group_announcement_banner import GroupAnnouncementBanner


class ChatHeader(QWidget):
    """Top bar showing current chat identity, status, and actions."""

    history_clicked = Signal()
    info_clicked = Signal()
    more_clicked = Signal()
    ai_summary_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setObjectName("chatHeader")
        self.setMinimumWidth(0)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 12, 20, 12)
        self.main_layout.setSpacing(0)

        self.info_widget = QWidget(self)
        self.info_widget.setMinimumWidth(0)
        self.info_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.info_layout = QVBoxLayout(self.info_widget)
        self.info_layout.setContentsMargins(0, 0, 0, 0)
        self.info_layout.setSpacing(0)

        self.title_row = QWidget(self.info_widget)
        self.title_row.setMinimumWidth(0)
        self.title_row_layout = QHBoxLayout(self.title_row)
        self.title_row_layout.setContentsMargins(0, 0, 0, 0)
        self.title_row_layout.setSpacing(8)

        self.title_label = BodyLabel(tr("chat_header.placeholder_title", "Select a Conversation"), self.info_widget)
        self.status_label = CaptionLabel(
            tr("chat_header.placeholder_status", "Choose a chat from the left to get started"),
            self.info_widget,
        )
        self.title_label.setMinimumWidth(0)
        self.status_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self.title_label.setObjectName("chatHeaderTitle")
        self.status_label.setObjectName("chatHeaderStatus")
        self.group_announcement_banner = GroupAnnouncementBanner(self.info_widget)
        self.group_announcement_banner.hide()
        self.info_layout.addWidget(self.title_row)
        self.info_layout.addSpacing(6)
        self.info_layout.addWidget(self.group_announcement_banner, 0)
        self.info_layout.addSpacing(2)
        self.info_layout.addWidget(self.status_label)

        self.history_button = TransparentToolButton(CollectionIcon("history"), self)
        self.history_button.setFixedSize(36, 36)
        self.history_button.setToolTip(tr("chat_header.history_tooltip", "Chat History"))
        self.history_button.hide()

        self.info_button = TransparentToolButton(AppIcon.INFO, self)
        self.info_button.setFixedSize(36, 36)
        self.info_button.setToolTip(tr("chat_header.info_tooltip", "Chat Info"))
        self._apply_safe_button_font(self.history_button, self.info_button)

        self.badge_container = QWidget(self.title_row)
        self.badge_container.setObjectName("chatHeaderBadgeContainer")
        self.badge_layout = QHBoxLayout(self.badge_container)
        self.badge_layout.setContentsMargins(0, 0, 0, 0)
        self.badge_layout.setSpacing(6)
        self.badge_container.hide()
        self._badge_widgets: list[InfoBadge] = []

        self.title_row_layout.addWidget(self.title_label, 1)
        self.title_row_layout.addWidget(self.badge_container, 0)
        self.title_row_layout.addWidget(self.history_button, 0)
        self.title_row_layout.addWidget(self.info_button, 0)

        self.main_layout.addWidget(self.info_widget, 1)

        self.history_button.clicked.connect(self.history_clicked.emit)
        self.info_button.clicked.connect(self.info_clicked.emit)
        self.info_button.clicked.connect(self.more_clicked.emit)
        self.set_actions_enabled(False)

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
        self.title_label.setText(title or tr("session.unnamed", "Untitled Session"))
        self.status_label.setText(status)
        self.set_actions_enabled(True)

    def set_group_announcement_session(self, session) -> None:
        """Bind the header-level announcement card to the active session."""
        self.group_announcement_banner.set_session(session)

    def group_announcement_visible(self) -> bool:
        """Return whether the header-level announcement card should currently be shown."""
        return bool(self.group_announcement_banner.isVisible())

    def group_announcement_widget(self) -> GroupAnnouncementBanner:
        """Expose the header-level announcement card for signal wiring."""
        return self.group_announcement_banner

    def set_title(self, title: str) -> None:
        """Set chat title only."""
        self.title_label.setText(title)

    def set_status(self, status: str) -> None:
        """Set status label."""
        self.status_label.setText(status)

    def set_actions_enabled(self, enabled: bool) -> None:
        """Enable or disable the header action buttons together."""
        self.history_button.setEnabled(False)
        self.info_button.setEnabled(enabled)

    def set_security_badges(self, badges: list[dict[str, str]]) -> None:
        """Replace the current header badge list with one compact session-status strip."""
        while self._badge_widgets:
            widget = self._badge_widgets.pop()
            self.badge_layout.removeWidget(widget)
            widget.deleteLater()

        normalized_badges = [item for item in badges if isinstance(item, dict) and str(item.get("text", "") or "").strip()]
        if not normalized_badges:
            self.badge_container.hide()
            return

        level_map = {
            "secure": InfoLevel.SUCCESS,
            "neutral": InfoLevel.INFOAMTION,
            "muted": InfoLevel.INFOAMTION,
            "warning": InfoLevel.WARNING,
            "danger": InfoLevel.ERROR,
        }
        for badge in normalized_badges:
            widget = InfoBadge(self.badge_container, level_map.get(str(badge.get("tone", "neutral") or "neutral"), InfoLevel.INFOAMTION))
            widget.setText(str(badge.get("text", "") or "").strip())
            tooltip = str(badge.get("tooltip", "") or "").strip()
            if tooltip:
                widget.setToolTip(tooltip)
            self.badge_layout.addWidget(widget, 0)
            self._badge_widgets.append(widget)

        self.badge_container.show()

    def get_title_label(self) -> BodyLabel:
        """Get title label widget."""
        return self.title_label

    def get_status_label(self) -> CaptionLabel:
        """Get status label widget."""
        return self.status_label

    def get_more_button(self) -> TransparentToolButton:
        """Get detail button widget."""
        return self.info_button

    def get_history_button(self) -> TransparentToolButton:
        """Get history button widget."""
        return self.history_button
