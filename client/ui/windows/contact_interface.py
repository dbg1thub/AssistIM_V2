"""Contact interface built with qfluentwidgets."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QLabel, QDialog, QFrame, QHBoxLayout, QSizePolicy, QSplitter, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentStyleSheet,
    IconWidget,
    InfoBar,
    LineEdit,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SearchLineEdit,
    SegmentedWidget,
    SubtitleLabel,
    RoundMenu,
    TransparentToolButton,
    ToolButton,
    TitleLabel,
    isDarkTheme,
    themeColor,
)
from qframelesswindow.titlebar import CloseButton
from shiboken6 import isValid as is_valid_qt_object

from client.core.app_icons import AppIcon
from client.core import logging
from client.core.avatar_utils import profile_avatar_seed
from client.core.config_backend import get_config
from client.core.i18n import tr
from client.core.profile_fields import format_profile_birthday, localize_profile_gender, localize_profile_status
from client.core.logging import setup_logging
from client.events.contact_events import ContactEvent
from client.events.event_bus import get_event_bus
from client.managers.connection_manager import get_connection_manager
from client.managers.search_manager import search_all
from client.network.http_client import get_http_client
from client.network.websocket_client import ConnectionState
from client.ui.controllers.discovery_controller import MomentMediaRecord, get_discovery_controller
from client.ui.controllers.contact_controller import (
    ContactRecord,
    FriendRequestRecord,
    GroupRecord,
    UserSearchRecord,
    get_contact_controller,
)

from client.ui.styles import StyleSheet
from client.ui.widgets.chat_info_drawer import AcrylicDrawerSurface
from client.ui.widgets.global_search_panel import GlobalSearchPopupOverlay
from client.ui.widgets.fluent_divider import FluentDivider
from client.ui.widgets.fluent_dialog import FluentDialog
from client.ui.widgets.contact_shared import (
    CONTACT_SIDEBAR_AVATAR_SIZE,
    CONTACT_SIDEBAR_CONTENT_GAP,
    CONTACT_SIDEBAR_ITEM_HEIGHT,
    CONTACT_SECTION_INSET,
    CONTACT_SIDEBAR_ITEM_PADDING,
    CONTACT_SIDEBAR_TEXT_SPACING,
    CONTACT_SIDEBAR_TEXT_TOP_OFFSET,
    CONTACT_SIDEBAR_TITLE_FONT_SIZE,
    ContactAvatar,
    ContactSectionHeader,
    ElidedBodyLabel,
    ElidedCaptionLabel,
    prepare_transparent_scroll_area as _prepare_transparent_scroll_area,
)
from client.ui.windows.group_creation_dialogs import CreateGroupDialog

setup_logging()
logger = logging.get_logger(__name__)


def _request_status_text(status: str) -> str:
    """Return the localized status text for a friend request."""
    mapping = {
        "pending": tr("contact.request.status.pending", "Pending"),
        "accepted": tr("contact.request.status.accepted", "Accepted"),
        "rejected": tr("contact.request.status.rejected", "Rejected"),
        "expired": tr("contact.request.status.expired", "Expired"),
    }
    return mapping.get(status, status or tr("contact.request.status.processed", "Processed"))


def _request_title_text(request: FriendRequestRecord, current_user_id: str) -> str:
    """Return the localized title for a friend request block."""
    return (
        tr("contact.request.title.received", "Received Friend Request")
        if request.is_incoming(current_user_id)
        else tr("contact.request.title.sent", "Sent Friend Request")
    )


def _request_message_text(request: FriendRequestRecord, current_user_id: str) -> str:
    """Return the fallback message shown in request rows."""
    if request.is_outgoing(current_user_id):
        return request.message or tr("contact.request.default_outgoing", "You sent a friend request.")
    return request.message or tr("contact.request.default_incoming", "The other user sent you a friend request.")


def _request_accept_button_style() -> str:
    """Return a compact theme-colored style for request acceptance."""
    base = QColor(themeColor())
    hover = QColor(base).lighter(108)
    pressed = QColor(base).darker(108)
    return f"""
        QToolButton#requestAcceptButton {{
            background: {base.name()};
            border: none;
            border-radius: 6px;
        }}
        QToolButton#requestAcceptButton:hover {{
            background: {hover.name()};
        }}
        QToolButton#requestAcceptButton:pressed {{
            background: {pressed.name()};
        }}
    """


class RemoveFriendConfirmDialog(MessageBoxBase):
    """Ask for confirmation before removing one friend."""

    def __init__(self, display_name: str, parent=None):
        super().__init__(parent=parent)
        title = SubtitleLabel(tr("contact.detail.remove_friend.title", "Remove Friend"), self.widget)
        content = BodyLabel(
            tr(
                "contact.detail.remove_friend.confirm",
                "Remove {name} from your friends?",
                name=display_name or tr("session.unnamed", "Untitled Session"),
            ),
            self.widget,
        )
        content.setWordWrap(True)
        self.viewLayout.addWidget(title)
        self.viewLayout.addWidget(content)
        self.viewLayout.addStretch(1)
        self.yesButton.setText(tr("contact.detail.remove_friend.action", "Remove"))
        self.cancelButton.setText(tr("common.cancel", "Cancel"))
        self.widget.setMinimumWidth(380)


class BlockFriendConfirmDialog(MessageBoxBase):
    """Ask for confirmation before blocking one friend."""

    def __init__(self, display_name: str, parent=None):
        super().__init__(parent=parent)
        title = SubtitleLabel(tr("contact.detail.block_friend.title", "Block Contact"), self.widget)
        content = BodyLabel(
            tr(
                "contact.detail.block_friend.confirm",
                "Block {name}? This removes the friendship and blocks new messages and friend requests until you unblock them.",
                name=display_name or tr("session.unnamed", "Untitled Session"),
            ),
            self.widget,
        )
        content.setWordWrap(True)
        self.viewLayout.addWidget(title)
        self.viewLayout.addWidget(content)
        self.viewLayout.addStretch(1)
        self.yesButton.setText(tr("contact.detail.block_friend.action", "Block"))
        self.cancelButton.setText(tr("common.cancel", "Cancel"))
        self.widget.setMinimumWidth(420)


class EditFriendRemarkDialog(FluentDialog):
    submitted = Signal(str, str)

    def __init__(self, contact: ContactRecord, parent=None):
        super().__init__(parent=parent, title=tr("contact.detail.edit_remark.title", "Edit Remark"))
        self._contact_id = contact.id
        self.setFixedWidth(420)

        hint = BodyLabel(
            tr(
                "contact.detail.edit_remark.hint",
                "Set a private remark for this friend. Only you can see it.",
            ),
            self.content_widget,
        )
        hint.setWordWrap(True)
        self.remark_edit = LineEdit(self.content_widget)
        self.remark_edit.setMaxLength(64)
        self.remark_edit.setPlaceholderText(tr("contact.detail.edit_remark.placeholder", "Friend remark"))
        self.remark_edit.setText(contact.remark)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 8, 0, 0)
        button_row.setSpacing(10)
        button_row.addStretch(1)
        self.cancel_button = PushButton(tr("common.cancel", "Cancel"), self.content_widget)
        self.save_button = PrimaryPushButton(tr("common.save", "Save"), self.content_widget)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.save_button)

        self.content_layout.addWidget(hint)
        self.content_layout.addWidget(self.remark_edit)
        self.content_layout.addLayout(button_row)

        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._submit)

    def _submit(self) -> None:
        self.submitted.emit(self._contact_id, self.remark_edit.text().strip())
        self.accept()


class ContactListItem(QWidget):
    clicked = Signal(str)
    context_requested = Signal(str, QPoint)

    def __init__(
        self,
        item_id: str,
        title: str,
        subtitle: str = "",
        meta: str = "",
        avatar: str = "",
        badge: str = "",
        parent=None,
        *,
        left_padding: int | None = None,
    ):
        super().__init__(parent)
        self.item_id = item_id
        self._selected = False
        self._hovered = False
        self._left_padding = int(left_padding if left_padding is not None else CONTACT_SIDEBAR_ITEM_PADDING)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(CONTACT_SIDEBAR_ITEM_HEIGHT)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            self._left_padding,
            CONTACT_SIDEBAR_ITEM_PADDING,
            CONTACT_SIDEBAR_ITEM_PADDING,
            CONTACT_SIDEBAR_ITEM_PADDING,
        )
        layout.setSpacing(CONTACT_SIDEBAR_CONTENT_GAP)

        self.avatar = ContactAvatar(CONTACT_SIDEBAR_AVATAR_SIZE, self)
        self.avatar.set_avatar(avatar, title, seed=profile_avatar_seed(user_id=self.item_id, display_name=title))

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, CONTACT_SIDEBAR_TEXT_TOP_OFFSET, 0, 0)
        text_layout.setSpacing(CONTACT_SIDEBAR_TEXT_SPACING)

        self.title_label = ElidedBodyLabel(title, self)
        title_font = QFont(self.title_label.font())
        title_font.setPixelSize(CONTACT_SIDEBAR_TITLE_FONT_SIZE)
        title_font.setBold(False)
        self.title_label.setFont(title_font)

        self.subtitle_label = ElidedCaptionLabel(subtitle, self)
        self.subtitle_label.setVisible(bool(subtitle))
        text_layout.addStretch(1)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.subtitle_label)
        text_layout.addStretch(1)
        layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(text_layout, 1)

    def update_content(
        self,
        *,
        title: str,
        subtitle: str = "",
        avatar: str = "",
        gender: str = "",
        seed_user_id: str = "",
        seed_username: str = "",
    ) -> None:
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)
        self.subtitle_label.setVisible(bool(subtitle))
        self.avatar.set_avatar(
            avatar,
            title,
            gender=gender,
            seed=profile_avatar_seed(
                user_id=seed_user_id or self.item_id,
                username=seed_username,
                display_name=title,
            ),
        )

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item_id)
            super().mousePressEvent(event)
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.context_requested.emit(self.item_id, event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        dark = isDarkTheme()
        if self._selected:
            painter.fillRect(self.rect(), QColor(255, 255, 255, 38) if dark else QColor(0, 0, 0, 18))
        elif self._hovered:
            painter.fillRect(self.rect(), QColor(255, 255, 255, 24) if dark else QColor(0, 0, 0, 10))


class RequestListItem(QWidget):
    accept_clicked = Signal(str)
    reject_clicked = Signal(str)
    selected = Signal(str)

    def __init__(self, request: FriendRequestRecord, current_user_id: str, parent=None):
        super().__init__(parent)
        self.request = request
        self.current_user_id = current_user_id
        self._selected = False
        self._hovered = False
        self.setObjectName("RequestListItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(0)
        self.setFixedHeight(CONTACT_SIDEBAR_ITEM_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            CONTACT_SIDEBAR_ITEM_PADDING,
            CONTACT_SIDEBAR_ITEM_PADDING,
            CONTACT_SIDEBAR_ITEM_PADDING,
            CONTACT_SIDEBAR_ITEM_PADDING,
        )
        layout.setSpacing(CONTACT_SIDEBAR_CONTENT_GAP)

        self.avatar = ContactAvatar(CONTACT_SIDEBAR_AVATAR_SIZE, self)
        self.avatar.set_avatar(
            request.counterpart_avatar(current_user_id),
            fallback=request.counterpart_name(current_user_id),
            gender=request.counterpart_gender(current_user_id),
            seed=profile_avatar_seed(
                user_id=request.counterpart_id(current_user_id),
                display_name=request.counterpart_name(current_user_id),
            ),
        )

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, CONTACT_SIDEBAR_TEXT_TOP_OFFSET, 0, 0)
        text_layout.setSpacing(CONTACT_SIDEBAR_TEXT_SPACING)

        self.title_label = ElidedBodyLabel(request.counterpart_name(current_user_id), self)
        title_font = QFont(self.title_label.font())
        title_font.setPixelSize(CONTACT_SIDEBAR_TITLE_FONT_SIZE)
        title_font.setBold(False)
        self.title_label.setFont(title_font)

        self.message_label = ElidedCaptionLabel(_request_message_text(request, current_user_id), self)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.message_label)

        self.action_layout = QHBoxLayout()
        self.action_layout.setContentsMargins(0, 0, 0, 0)
        self.action_layout.setSpacing(6)
        self._render_actions()

        layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(text_layout, 1)
        layout.addLayout(self.action_layout, 0)

    def _status_text(self) -> str:
        return _request_status_text(self.request.status)

    def _render_actions(self) -> None:
        while self.action_layout.count():
            item = self.action_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if self.request.can_review(self.current_user_id):
            accept_button = ToolButton(AppIcon.CHECK, self)
            reject_button = ToolButton(AppIcon.CLOSE, self)
            accept_button.setObjectName("requestAcceptButton")
            accept_button.setFixedSize(28, 28)
            reject_button.setFixedSize(28, 28)
            accept_button.setToolTip(tr("common.accept", "Accept"))
            reject_button.setToolTip(tr("common.reject", "Reject"))
            accept_button.setStyleSheet(_request_accept_button_style())
            accept_button.clicked.connect(lambda: self.accept_clicked.emit(self.request.id))
            reject_button.clicked.connect(lambda: self.reject_clicked.emit(self.request.id))
            self.action_layout.addWidget(accept_button, 0, Qt.AlignmentFlag.AlignVCenter)
            self.action_layout.addWidget(reject_button, 0, Qt.AlignmentFlag.AlignVCenter)
        else:
            status_button = PushButton(self._status_text(), self)
            status_button.setObjectName("requestStatusButton")
            status_button.setFixedWidth(88)
            status_button.setEnabled(False)
            self.action_layout.addWidget(status_button, 0, Qt.AlignmentFlag.AlignVCenter)

    def update_request(self, request: FriendRequestRecord, current_user_id: str) -> None:
        self.request = request
        self.current_user_id = current_user_id
        counterpart_name = request.counterpart_name(current_user_id)
        self.title_label.setText(counterpart_name)
        self.message_label.setText(_request_message_text(request, current_user_id))
        self.avatar.set_avatar(
            request.counterpart_avatar(current_user_id),
            fallback=counterpart_name,
            gender=request.counterpart_gender(current_user_id),
            seed=profile_avatar_seed(
                user_id=request.counterpart_id(current_user_id),
                display_name=counterpart_name,
            ),
        )
        self._render_actions()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.request.id)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        dark = isDarkTheme()
        if self._selected:
            painter.fillRect(self.rect(), QColor(255, 255, 255, 38) if dark else QColor(0, 0, 0, 18))
        elif self._hovered:
            painter.fillRect(self.rect(), QColor(255, 255, 255, 24) if dark else QColor(0, 0, 0, 10))


class ContactWelcomeWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ContactWelcomeWidget")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(0)
        layout.addStretch(1)

        card = CardWidget(self)
        card.setObjectName("ContactWelcomeCard")
        card.setBorderRadius(8)
        card.setMinimumWidth(420)
        card.setMaximumWidth(540)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(36, 36, 36, 36)
        card_layout.setSpacing(14)

        icon = IconWidget(AppIcon.PEOPLE, card)
        icon.setFixedSize(52, 52)

        title_label = BodyLabel(tr("contact.welcome.title", "Welcome to Contacts"), card)
        title_font = QFont(title_label.font())
        title_font.setPixelSize(24)
        title_font.setBold(False)
        title_label.setFont(title_font)

        subtitle_label = CaptionLabel(
            tr(
                "contact.welcome.subtitle",
                "Select a friend, group, or request from the left to view the profile and recent activity.",
            ),
            card,
        )
        subtitle_label.setWordWrap(True)

        hint_label = CaptionLabel(
            tr(
                "contact.welcome.hint",
                "You can also search above, add friends, or create groups from the sidebar.",
            ),
            card,
        )
        hint_label.setObjectName("contactSectionCaption")
        hint_label.setWordWrap(True)

        card_layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignLeft)
        card_layout.addWidget(title_label, 0, Qt.AlignmentFlag.AlignLeft)
        card_layout.addWidget(subtitle_label, 0, Qt.AlignmentFlag.AlignLeft)
        card_layout.addWidget(hint_label, 0, Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)


class FriendMomentPreviewStrip(QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._network_manager = QNetworkAccessManager(self)
        self._pending_replies: list[QNetworkReply] = []
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(42)
        self.setMinimumWidth(0)

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(4)
        self.empty_label = BodyLabel("-", self)
        self.empty_label.setObjectName("friendMomentEmptyLabel")
        self.layout.addWidget(self.empty_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self._tiles: list[QLabel] = []
        for _index in range(5):
            tile = QLabel(self)
            tile.setObjectName("friendMomentPreviewTile")
            tile.setFixedSize(42, 42)
            tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile.hide()
            self.layout.addWidget(tile)
            self._tiles.append(tile)
        self.layout.addStretch(1)

    def set_media(self, media: list[MomentMediaRecord]) -> None:
        self._cancel_pending_replies()
        images = [item for item in media if item.is_image][: len(self._tiles)]
        self.empty_label.setVisible(not images)
        for index, tile in enumerate(self._tiles):
            if index >= len(images):
                tile.clear()
                tile.hide()
                continue
            tile.show()
            tile.setText(tr("contact.detail.moment_image_placeholder", "Image"))
            self._load_tile(tile, images[index])

    def clear(self) -> None:
        self._cancel_pending_replies()
        self.empty_label.show()
        for tile in self._tiles:
            tile.clear()
            tile.hide()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def _load_tile(self, tile: QLabel, media: MomentMediaRecord) -> None:
        source = self._resolve_media_source(media)
        if not source:
            return
        if Path(source).exists():
            self._apply_pixmap(tile, QPixmap(source))
            return
        if source.startswith(("http://", "https://")):
            reply = self._network_manager.get(self._build_media_request(source))
            self._pending_replies.append(reply)
            reply.finished.connect(lambda current=reply, target=tile: self._finish_network_tile(current, target))

    def _finish_network_tile(self, reply: QNetworkReply, tile: QLabel) -> None:
        if reply in self._pending_replies:
            self._pending_replies.remove(reply)
        data = reply.readAll()
        pixmap = QPixmap()
        pixmap.loadFromData(bytes(data))
        self._apply_pixmap(tile, pixmap)
        reply.deleteLater()

    @staticmethod
    def _apply_pixmap(tile: QLabel, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        scaled = pixmap.scaled(tile.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        tile.setPixmap(scaled)
        tile.setText("")

    def _cancel_pending_replies(self) -> None:
        for reply in list(self._pending_replies):
            reply.abort()
            reply.deleteLater()
        self._pending_replies.clear()

    @staticmethod
    def _resolve_media_source(media: MomentMediaRecord) -> str:
        for value in (media.local_path, media.url):
            source = str(value or "").strip()
            if not source:
                continue
            if Path(source).exists() or source.startswith(("http://", "https://")):
                return source
            if source.startswith("/"):
                return f"{get_config().server.origin_url.rstrip('/')}{source}"
            return source
        return ""

    def _build_media_request(self, source: str) -> QNetworkRequest:
        request = QNetworkRequest(QUrl(source))
        token = str(get_http_client().access_token or "").strip()
        if token and self._should_authenticate_media_source(source):
            request.setRawHeader(b"Authorization", f"Bearer {token}".encode("utf-8"))
        return request

    @staticmethod
    def _should_authenticate_media_source(source: str) -> bool:
        source_text = str(source or "").strip()
        if not source_text:
            return False
        split_result = urlsplit(source_text)
        if not split_result.scheme and source_text.startswith("/"):
            return source_text.startswith("/uploads/")
        origin = urlsplit(get_config().server.origin_url)
        return (
            split_result.scheme == origin.scheme
            and split_result.netloc == origin.netloc
            and split_result.path.startswith("/uploads/")
        )


class ContactDetailRow(QWidget):
    clicked = Signal()

    def __init__(self, label: str, parent=None, *, editable: bool = False, clickable: bool = False):
        super().__init__(parent)
        self._clickable = clickable or editable
        if self._clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(16)
        self.label = CaptionLabel(label, self)
        self.label.setObjectName("contactDetailFieldLabel")
        self.label.setFixedWidth(58)
        self.value = BodyLabel("", self)
        self.value.setWordWrap(True)
        self.value.setMinimumWidth(0)
        layout.addWidget(self.label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.value, 1, Qt.AlignmentFlag.AlignVCenter)
        if editable:
            self.edit_button = TransparentToolButton(AppIcon.EDIT, self)
            self.edit_button.setFixedSize(24, 24)
            self.edit_button.setToolTip(tr("contact.detail.edit_remark.title", "Edit Remark"))
            self.edit_button.clicked.connect(self.clicked.emit)
            layout.addWidget(self.edit_button, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_value(self, value: str) -> None:
        self.value.setText(str(value or ""))

    def mousePressEvent(self, event) -> None:
        if self._clickable and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ContactActionButton(QWidget):
    clicked = Signal()

    def __init__(self, icon: AppIcon, text: str, parent=None):
        super().__init__(parent)
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(76, 66)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 7)
        layout.setSpacing(6)
        self.icon = IconWidget(icon, self)
        self.icon.setFixedSize(26, 26)
        self.label = CaptionLabel(text, self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.label, 0, Qt.AlignmentFlag.AlignHCenter)

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if self.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        if self.isEnabled() and self._hovered:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            color = QColor(255, 255, 255, 26) if isDarkTheme() else QColor(0, 0, 0, 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)
        super().paintEvent(event)


class GalleryContactDetailPanel(QWidget):
    message_requested = Signal(object)
    call_requested = Signal(object, str)
    remark_edit_requested = Signal(object)
    friend_moments_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entity: Optional[dict[str, object]] = None
        self.setObjectName("ContactDetailPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(24, 24, 24, 24)
        root_layout.setSpacing(0)
        root_layout.addStretch(1)

        self.header = CardWidget(self)
        self.header.setObjectName("ContactDetailHeader")
        self.header.setBorderRadius(8)
        self.header.setMinimumWidth(420)
        self.header.setMaximumWidth(460)
        self.header.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        header_layout = QVBoxLayout(self.header)
        header_layout.setContentsMargins(28, 26, 28, 26)
        header_layout.setSpacing(0)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(14)
        self.avatar = ContactAvatar(72, self.header)
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(4)
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(6)
        self.title_label = SubtitleLabel(tr("contact.detail.title", "Contact Details"), self.header)
        self.gender_icon = IconWidget(AppIcon.GENDER_MALE, self.header)
        self.gender_icon.setFixedSize(16, 16)
        self.gender_icon.hide()
        self.gender_label = CaptionLabel("", self.header)
        self.gender_label.setObjectName("contactGenderLabel")
        self.gender_label.hide()
        name_row.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignVCenter)
        name_row.addWidget(self.gender_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        name_row.addWidget(self.gender_label, 0, Qt.AlignmentFlag.AlignVCenter)
        name_row.addStretch(1)
        self.subtitle_label = CaptionLabel("", self.header)
        self.subtitle_label.setObjectName("contactMetaLabel")
        self.region_label = CaptionLabel("", self.header)
        self.region_label.setObjectName("contactMetaLabel")
        info_layout.addLayout(name_row)
        info_layout.addWidget(self.subtitle_label)
        info_layout.addWidget(self.region_label)
        self.more_button = TransparentToolButton(AppIcon.MORE_HORIZONTAL, self.header)
        self.more_button.setFixedSize(24, 24)
        self.more_button.setToolTip(tr("contact.detail.more", "More"))

        top_row.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)
        top_row.addLayout(info_layout, 1)
        top_row.addWidget(self.more_button, 0, Qt.AlignmentFlag.AlignTop)

        self.remark_row = ContactDetailRow(tr("contact.detail.label.remark", "Remark"), self.header, editable=True)
        self.moments_row = ContactDetailRow(tr("contact.detail.label.moments", "Moments"), self.header, clickable=True)
        self.moment_strip = FriendMomentPreviewStrip(self.moments_row)
        self.moments_row.layout().replaceWidget(self.moments_row.value, self.moment_strip)
        self.moments_row.value.deleteLater()
        self.signature_row = ContactDetailRow(tr("contact.detail.label.signature", "Signature"), self.header)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(32, 26, 32, 0)
        action_row.setSpacing(42)
        self.message_button = ContactActionButton(AppIcon.CHAT, tr("contact.detail.action.message", "Message"), self.header)
        self.voice_button = ContactActionButton(AppIcon.PHONE, tr("contact.detail.action.voice_call", "Voice Call"), self.header)
        self.video_button = ContactActionButton(AppIcon.VIDEO, tr("contact.detail.action.video_call", "Video Call"), self.header)
        action_row.addWidget(self.message_button)
        action_row.addWidget(self.voice_button)
        action_row.addWidget(self.video_button)

        header_layout.addLayout(top_row)
        header_layout.addSpacing(18)
        self._add_divider(header_layout)
        header_layout.addWidget(self.remark_row)
        self._add_divider(header_layout)
        header_layout.addWidget(self.moments_row)
        self._add_divider(header_layout)
        header_layout.addWidget(self.signature_row)
        self._add_divider(header_layout)
        header_layout.addLayout(action_row)

        self.message_button.clicked.connect(self._emit_message_request)
        self.voice_button.clicked.connect(lambda _checked=False: self._emit_call_request("voice"))
        self.video_button.clicked.connect(lambda _checked=False: self._emit_call_request("video"))
        self.remark_row.clicked.connect(self._emit_remark_edit_request)
        self.moments_row.clicked.connect(self._emit_friend_moments_request)
        self.moment_strip.clicked.connect(self._emit_friend_moments_request)
        self.moments_row.layout().setAlignment(self.moment_strip, Qt.AlignmentFlag.AlignVCenter)
        self._set_call_buttons_available(False)

        root_layout.addWidget(self.header, 0, Qt.AlignmentFlag.AlignHCenter)
        root_layout.addStretch(1)
        self.show_placeholder()

    @staticmethod
    def _add_divider(layout: QVBoxLayout) -> None:
        line = QFrame()
        line.setObjectName("ContactDetailDivider")
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        layout.addWidget(line)

    def show_placeholder(self) -> None:
        self._entity = None
        self.avatar.set_avatar(fallback="CT")
        self.title_label.setText(tr("contact.detail.title", "Contact Details"))
        self.subtitle_label.clear()
        self.region_label.clear()
        self.gender_icon.hide()
        self.gender_label.hide()
        self.remark_row.set_value("")
        self.signature_row.set_value("")
        self.moment_strip.clear()
        self.message_button.setEnabled(False)
        self._set_call_buttons_available(False)

    def set_contact(self, contact: ContactRecord) -> None:
        self._entity = {"type": "friend", "data": contact}
        self.avatar.set_avatar(
            contact.avatar,
            contact.display_name,
            gender=contact.gender,
            seed=profile_avatar_seed(user_id=contact.id, username=contact.username, display_name=contact.display_name),
        )
        self.title_label.setText(contact.display_name)
        self.subtitle_label.setText(
            f"{tr('contact.detail.label.assistim_id', 'AssistIM ID')}: {contact.assistim_id or contact.username or '-'}"
        )
        self.region_label.setText(f"{tr('contact.detail.label.region', 'Region')}: {contact.region or '-'}")
        self._set_gender_icon(contact.gender)
        self.remark_row.set_value(contact.remark or "-")
        self.signature_row.set_value(contact.signature or "-")
        self.message_button.setEnabled(True)
        self._set_call_buttons_available(True)

    def _set_gender_icon(self, gender: str) -> None:
        normalized = str(gender or "").strip().lower()
        canonical = {
            "m": "male",
            "男": "male",
            "male": "male",
            "f": "female",
            "女": "female",
            "female": "female",
        }.get(normalized, normalized)
        label = localize_profile_gender(canonical)
        self.gender_icon.hide()
        self.gender_label.hide()
        if canonical == "male":
            self.gender_icon.setIcon(AppIcon.GENDER_MALE)
            self.gender_icon.setToolTip(label)
            self.gender_icon.show()
            return
        if canonical == "female":
            self.gender_icon.setIcon(AppIcon.GENDER_FEMALE)
            self.gender_icon.setToolTip(label)
            self.gender_icon.show()
            return
        if canonical:
            self.gender_label.setText(label or str(gender))
            self.gender_label.show()

    def set_friend_moment_images(self, media: list[MomentMediaRecord]) -> None:
        self.moment_strip.set_media(media)

    def set_blocked_contact(self, contact: ContactRecord) -> None:
        self._entity = {"type": "blocked", "data": contact}
        self.avatar.set_avatar(
            contact.avatar,
            contact.display_name,
            gender=contact.gender,
            seed=profile_avatar_seed(user_id=contact.id, username=contact.username, display_name=contact.display_name),
        )
        self.title_label.setText(contact.display_name)
        self.subtitle_label.setText(
            f"{tr('contact.detail.label.assistim_id', 'AssistIM ID')}: {contact.assistim_id or contact.username or '-'}"
        )
        self.region_label.setText(f"{tr('contact.detail.label.region', 'Region')}: {contact.region or '-'}")
        self._set_gender_icon(contact.gender)
        self.remark_row.set_value(tr("contact.relationship.blocked", "Blocked contact"))
        self.signature_row.set_value(contact.signature or "-")
        self.moment_strip.clear()
        self.message_button.setEnabled(False)
        self._set_call_buttons_available(False)

    def set_group(self, group: GroupRecord) -> None:
        self._entity = {"type": "group", "data": group}
        self.avatar.set_avatar(group.avatar, fallback=group.name)
        self.title_label.setText(group.name)
        self.subtitle_label.setText(f"{tr('contact.detail.label.group_id', 'Group ID')} {group.id or '-'}")
        self.region_label.setText(tr("contact.group.member_summary", "{count} members", count=group.member_count))
        self.gender_icon.hide()
        self.gender_label.hide()
        self.remark_row.set_value(group.session_id or "-")
        self.signature_row.set_value(group.created_at or "-")
        self.moment_strip.clear()
        self.message_button.setEnabled(True)
        self._set_call_buttons_available(False)

    def set_request(self, request: FriendRequestRecord, current_user_id: str = "") -> None:
        counterpart_id = request.counterpart_id(current_user_id)
        counterpart_name = request.counterpart_name(current_user_id)
        counterpart_username = (
            request.receiver_username if request.is_outgoing(current_user_id) else request.sender_username
        )
        self._entity = (
            {
                "type": "contact",
                "data": {
                    "id": counterpart_id,
                    "display_name": counterpart_name,
                    "name": counterpart_name,
                    "username": counterpart_username,
                    "assistim_id": counterpart_username,
                    "avatar": request.counterpart_avatar(current_user_id),
                },
            }
            if request.status == "accepted" and counterpart_id
            else None
        )
        self.avatar.set_avatar(
            request.counterpart_avatar(current_user_id),
            fallback=counterpart_name,
            gender=request.counterpart_gender(current_user_id),
            seed=profile_avatar_seed(user_id=counterpart_id, username=counterpart_username, display_name=counterpart_name),
        )
        self.title_label.setText(_request_title_text(request, current_user_id))
        self.subtitle_label.setText(
            f"{tr('contact.detail.label.assistim_id', 'AssistIM ID')}: {counterpart_username or counterpart_id or '-'}"
        )
        self.region_label.setText(f"{tr('contact.detail.label.request_status', 'Request Status')} {_request_status_text(request.status)}")
        self.gender_icon.hide()
        self.gender_label.hide()
        self.remark_row.set_value(request.message or "-")
        self.signature_row.set_value(request.created_at or "-")
        self.moment_strip.clear()
        self.message_button.setEnabled(self._entity is not None)
        self._set_call_buttons_available(False)

    def _emit_message_request(self) -> None:
        if self._entity:
            self.message_requested.emit(self._entity)

    def _emit_call_request(self, media_type: str) -> None:
        if self._entity and self._entity.get("type") == "friend":
            self.call_requested.emit(self._entity, media_type)

    def _emit_remark_edit_request(self) -> None:
        if self._entity and self._entity.get("type") == "friend":
            self.remark_edit_requested.emit(self._entity)

    def _emit_friend_moments_request(self) -> None:
        if self._entity and self._entity.get("type") == "friend":
            self.friend_moments_requested.emit(self._entity)

    def _set_call_buttons_available(self, available: bool) -> None:
        for button in (self.voice_button, self.video_button):
            button.setVisible(available)
            button.setEnabled(available)

class UserSearchItem(CardWidget):
    add_clicked = Signal(str)

    def __init__(self, user: UserSearchRecord, disabled_reason: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("UserSearchItem")
        self.user = user
        self.disabled_reason = disabled_reason

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        avatar = ContactAvatar(42, self)
        avatar.set_avatar(
            user.avatar,
            user.display_name,
            gender=user.gender,
            seed=profile_avatar_seed(user_id=user.id, username=user.username, display_name=user.display_name),
        )

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        text_layout.addWidget(BodyLabel(user.display_name, self))

        subtitle = user.username
        if user.status:
            subtitle = f"{subtitle} · {user.status}" if subtitle else user.status
        subtitle_label = CaptionLabel(subtitle or "-", self)
        subtitle_label.setWordWrap(True)
        text_layout.addWidget(subtitle_label)

        self.add_button = PrimaryPushButton(tr("contact.user_search.add", "Add Friend"), self)
        self.add_button.setFixedWidth(88)
        self.add_button.setDisabled(bool(disabled_reason))
        if disabled_reason:
            self.add_button.setText(disabled_reason)
        self.add_button.clicked.connect(lambda: self.add_clicked.emit(self.user.id))

        layout.addWidget(avatar, 0)
        layout.addLayout(text_layout, 1)
        layout.addWidget(self.add_button, 0)


class AcrylicToolWindow(QWidget):
    """Frameless floating window with one shared acrylic surface and close button."""

    closed = Signal()
    DRAG_REGION_HEIGHT = 52
    CLOSE_BUTTON_TOP = 0

    def __init__(self, parent=None, *, radius: int = 10) -> None:
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._drag_active = False
        self._drag_offset = QPoint()
        self._backdrop_primed = False
        self._backdrop_capture_in_progress = False
        self._backdrop_refresh_delay_ms = 56
        self._backdrop_capture_wait_ms = 24
        self._backdrop_refresh_timer = QTimer(self)
        self._backdrop_refresh_timer.setSingleShot(True)
        self._backdrop_refresh_timer.timeout.connect(self._refresh_backdrop_after_move)

        self.surface = AcrylicDrawerSurface(self, extend_right_edge=False, radius=radius)
        self.surface.setObjectName("addFriendAcrylicSurface")
        self.surface.set_border_object_name("addFriendAcrylicBorder")
        self.surface.installEventFilter(self)

        self.content_root = QWidget(self.surface)
        self.content_root.setObjectName("addFriendContentRoot")
        self.content_root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.content_root.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.content_root.setAutoFillBackground(False)

        self.close_button = CloseButton(self.surface)
        FluentStyleSheet.FLUENT_WINDOW.apply(self.close_button)
        self.close_button.setObjectName("addFriendWindowCloseButton")
        self.close_button.clicked.connect(self.close)

    def show(self) -> None:
        if not self._backdrop_primed:
            self._prime_backdrop()
            self._backdrop_primed = True
        super().show()

    def _prime_backdrop(self) -> None:
        if self.width() <= 0 or self.height() <= 0:
            return
        global_rect = QRect(self.mapToGlobal(QPoint(0, 0)), self.size())
        self.surface.capture_backdrop(global_rect)

    def _schedule_backdrop_refresh(self) -> None:
        if not self._backdrop_primed or not self.isVisible() or self._backdrop_capture_in_progress:
            return
        self._backdrop_refresh_timer.start(self._backdrop_refresh_delay_ms)

    def _refresh_backdrop_after_move(self) -> None:
        if not self.isVisible() or self.width() <= 0 or self.height() <= 0:
            return
        if self._drag_active:
            self._schedule_backdrop_refresh()
            return
        self._backdrop_capture_in_progress = True
        self.setWindowOpacity(0.0)
        QTimer.singleShot(self._backdrop_capture_wait_ms, self._finish_backdrop_refresh)

    def _finish_backdrop_refresh(self) -> None:
        if not self._backdrop_capture_in_progress:
            return
        if not self.isVisible() or self.width() <= 0 or self.height() <= 0:
            self.setWindowOpacity(1.0)
            self._backdrop_capture_in_progress = False
            return
        global_rect = QRect(self.mapToGlobal(QPoint(0, 0)), self.size())
        self.surface.capture_backdrop(global_rect)
        self.surface.raise_()
        self.close_button.raise_()
        self.setWindowOpacity(1.0)
        self._backdrop_capture_in_progress = False

    def _position_close_button(self) -> None:
        self.close_button.move(
            max(0, self.surface.width() - self.close_button.width()),
            self.CLOSE_BUTTON_TOP,
        )
        self.close_button.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.surface.setGeometry(self.rect())
        self.content_root.setGeometry(self.surface.rect())
        self._position_close_button()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._schedule_backdrop_refresh()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.surface:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._backdrop_refresh_timer.stop()
                point = event.position().toPoint()
                if point.y() <= self.DRAG_REGION_HEIGHT and not self.close_button.geometry().contains(point):
                    self._drag_active = True
                    self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                    event.accept()
                    return True
            elif event.type() == QEvent.Type.MouseMove and self._drag_active:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                event.accept()
                return True
            elif event.type() == QEvent.Type.MouseButtonRelease and self._drag_active:
                self._drag_active = False
                self._schedule_backdrop_refresh()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event) -> None:
        self._backdrop_refresh_timer.stop()
        self.setWindowOpacity(1.0)
        self._backdrop_capture_in_progress = False
        self.closed.emit()
        super().closeEvent(event)


class AddFriendDialog(FluentDialog):
    friend_request_sent = Signal(object)

    def __init__(self, controller, existing_ids: set[str], current_user_id: str = "", parent=None):
        super().__init__(parent=parent, title=tr("contact.add_friend.title", "Add Friend"))
        self._controller = controller
        self._current_user_id = str(current_user_id or "")
        self._existing_ids = set(existing_ids)
        self._search_task: Optional[asyncio.Task] = None
        self._action_task: Optional[asyncio.Task] = None
        self._search_generation = 0
        self._ui_tasks: set[asyncio.Task] = set()
        self._close_cleanup_done = False
        self._deferred_close_requested = False

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(tr("contact.add_friend.title", "Add Friend"))
        self.setObjectName("AddFriendDialog")
        self.resize(560, 680)
        self.setFixedSize(560, 680)

        self._setup_ui()
        self.destroyed.connect(self._on_destroyed)

    def _setup_ui(self) -> None:
        layout = self.content_layout

        subtitle = CaptionLabel(
            tr(
                "contact.add_friend.subtitle",
                "Search users by username or nickname, then send a friend request.",
            ),
            self,
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(10)
        self.search_edit = SearchLineEdit(self)
        self.search_edit.setPlaceholderText(tr("contact.add_friend.search_placeholder", "Search username or nickname"))
        self.search_edit.setMinimumHeight(38)
        self.search_button = PrimaryPushButton(tr("contact.add_friend.search_button", "Search"), self)
        self.search_button.setFixedWidth(88)
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.search_button, 0)
        layout.addLayout(search_row)

        self.message_edit = LineEdit(self)
        self.message_edit.setPlaceholderText(
            tr("contact.add_friend.message_placeholder", "Verification message (optional)")
        )
        self.message_edit.setMinimumHeight(38)
        layout.addWidget(self.message_edit)

        self.summary_label = CaptionLabel(
            tr("contact.add_friend.summary_idle", "Enter a keyword to search for users."),
            self,
        )
        self.summary_label.setObjectName("contactSummaryLabel")
        layout.addWidget(self.summary_label)

        self.result_area = ScrollArea(self)
        self.result_area.setWidgetResizable(True)
        self.result_area.setFrameShape(QFrame.Shape.NoFrame)
        self.result_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        _prepare_transparent_scroll_area(self.result_area)
        self.result_container = QWidget(self.result_area)
        self.result_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.result_container.setAutoFillBackground(False)
        self.result_container.setStyleSheet("background: transparent; border: none;")
        self.result_layout = QVBoxLayout(self.result_container)
        self.result_layout.setContentsMargins(6, 6, 6, 6)
        self.result_layout.setSpacing(8)
        self.result_layout.addStretch(1)
        self.result_area.setWidget(self.result_container)
        layout.addWidget(self.result_area, 1)

        self.search_button.clicked.connect(self._trigger_search)
        self.search_edit.returnPressed.connect(self._trigger_search)

    def closeEvent(self, event) -> None:
        if self._action_task is not None and not self._action_task.done():
            self._deferred_close_requested = True
            self.hide()
            event.ignore()
            return
        self._run_close_cleanup()
        super().closeEvent(event)

    def _trigger_search(self) -> None:
        keyword = self.search_edit.text().strip()
        self._search_generation += 1
        generation = self._search_generation
        if self._search_task and not self._search_task.done():
            self._search_task.cancel()
        if not keyword:
            self._clear_search_results()
            self.summary_label.setText(tr("contact.add_friend.summary_empty_keyword", "Please enter a search keyword."))
            return

        self._clear_search_results()
        self._set_search_task(self._search_async(keyword, generation))

    async def _search_async(self, keyword: str, generation: int) -> None:
        self.summary_label.setText(tr("contact.add_friend.summary_searching", "Searching users..."))
        try:
            users = await self._controller.search_users(keyword)
        except asyncio.CancelledError:
            raise
        except Exception:
            if generation != self._search_generation or self.search_edit.text().strip() != keyword:
                return
            self._clear_search_results()
            self.summary_label.setText(tr("contact.add_friend.summary_failed", "Search failed."))
            raise

        if generation != self._search_generation or self.search_edit.text().strip() != keyword:
            return
        filtered = [
            user
            for user in users
            if user.id and user.id != self._current_user_id and user.id not in self._existing_ids
        ]
        self.summary_label.setText(
            tr("contact.add_friend.summary_count", "{count} users found", count=len(filtered))
        )
        self._render_search_results(filtered)

    def _render_search_results(self, users: list[UserSearchRecord]) -> None:
        self._clear_layout(self.result_layout)
        if not users:
            self.result_layout.addWidget(
                BodyLabel(tr("contact.add_friend.empty_results", "No matching users were found."), self.result_container)
            )
            self.result_layout.addStretch(1)
            return

        for user in users:
            item = UserSearchItem(user, "", self.result_container)
            item.add_clicked.connect(self._send_friend_request)
            self.result_layout.addWidget(item)
        self.result_layout.addStretch(1)

    def _clear_search_results(self) -> None:
        """Clear stale add-friend search rows while the keyword changes."""
        self._clear_layout(self.result_layout)
        self.result_layout.addStretch(1)

    def _send_friend_request(self, user_id: str) -> None:
        if self._action_task and not self._action_task.done():
            return
        self._set_action_task(self._send_friend_request_async(user_id))

    async def _send_friend_request_async(self, user_id: str) -> None:
        try:
            payload = await self._controller.send_friend_request(user_id, self.message_edit.text().strip())
        except asyncio.CancelledError:
            raise
        except Exception:
            self._finalize_deferred_close_if_needed()
            raise

        request_payload = dict((payload or {}).get("request") or {})
        status = str(request_payload.get("status", "pending") or "pending")
        success_message = (
            tr("contact.request.accepted", "Friend request accepted.")
            if status == "accepted"
            else tr("contact.add_friend.request_sent", "Friend request sent.")
        )
        InfoBar.success(
            tr("contact.add_friend.title", "Add Friend"),
            success_message,
            parent=self,
            duration=1800,
        )
        self.friend_request_sent.emit(dict(payload or {}))
        self.close()
        self._finalize_deferred_close_if_needed()

    def _on_finished(self, _result: int, *, preserve_action_task: bool = False) -> None:
        """Stop outstanding work after the dialog closes."""
        self._cancel_pending_task(self._search_task)
        self._search_task = None
        if not preserve_action_task:
            self._cancel_pending_task(self._action_task)
            self._action_task = None
        self._cancel_all_ui_tasks(preserve_task=self._action_task if preserve_action_task else None)

    def _on_destroyed(self, *_args) -> None:
        """Mirror close cleanup when the dialog is destroyed by its parent."""
        self._run_close_cleanup()

    def _run_close_cleanup(self, *, preserve_action_task: bool = False) -> None:
        """Run dialog cleanup only once across close and destroy paths."""
        if self._close_cleanup_done:
            return
        self._close_cleanup_done = True
        self._on_finished(0, preserve_action_task=preserve_action_task)

    def _finalize_deferred_close_if_needed(self) -> None:
        """Destroy the hidden dialog after one deferred in-flight mutation settles."""
        if not self._deferred_close_requested:
            return
        self._run_close_cleanup(preserve_action_task=True)
        self.deleteLater()

    def _cancel_pending_task(self, task: Optional[asyncio.Task]) -> None:
        """Cancel a tracked task if it is still running."""
        if task is not None and not task.done():
            task.cancel()

    def _cancel_all_ui_tasks(self, preserve_task: Optional[asyncio.Task] = None) -> None:
        """Cancel every task launched from this dialog."""
        for task in list(self._ui_tasks):
            if preserve_task is not None and task is preserve_task:
                continue
            if not task.done():
                task.cancel()

    def _create_ui_task(self, coro, context: str, *, on_done=None) -> asyncio.Task:
        """Track dialog-owned coroutines so they can be canceled on close."""
        task = asyncio.create_task(coro)
        self._ui_tasks.add(task)
        task.add_done_callback(lambda finished, name=context, callback=on_done: self._finalize_ui_task(finished, name, callback))
        return task

    def _finalize_ui_task(self, task: asyncio.Task, context: str, on_done=None) -> None:
        """Drop bookkeeping and log background failures."""
        self._ui_tasks.discard(task)
        if on_done is not None:
            on_done(task)

        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("AddFriendDialog task failed: %s", context)

    def _set_search_task(self, coro) -> None:
        """Keep only the latest user search request alive."""
        self._cancel_pending_task(self._search_task)
        self._search_task = self._create_ui_task(coro, "search users", on_done=self._clear_search_task)

    def _clear_search_task(self, task: asyncio.Task) -> None:
        """Clear the tracked search task when it finishes."""
        if self._search_task is task:
            self._search_task = None

    def _set_action_task(self, coro) -> None:
        """Track the current friend-request action."""
        self._cancel_pending_task(self._action_task)
        self._action_task = self._create_ui_task(coro, "send friend request", on_done=self._clear_action_task)

    def _clear_action_task(self, task: asyncio.Task) -> None:
        """Clear the tracked action task when it finishes."""
        if self._action_task is task:
            self._action_task = None

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


class ContactInterface(QWidget):
    message_requested = Signal(object)
    call_requested = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ContactInterface")
        self._controller = get_contact_controller()
        self._discovery_controller = get_discovery_controller()
        self._contacts: list[ContactRecord] = []
        self._blocked_contacts: list[ContactRecord] = []
        self._groups: list[GroupRecord] = []
        self._requests: list[FriendRequestRecord] = []
        self._friend_items: dict[str, ContactListItem] = {}
        self._blocked_items: dict[str, ContactListItem] = {}
        self._group_items: dict[str, ContactListItem] = {}
        self._request_items: dict[str, RequestListItem] = {}
        self._current_page = "friends"
        self._selected_key: tuple[str, str] | None = None
        self._load_task: Optional[asyncio.Task] = None
        self._friend_moment_task: Optional[asyncio.Task] = None
        self._search_task: Optional[asyncio.Task] = None
        self._search_flyout = None
        self._search_flyout_view: Optional[GlobalSearchPopupOverlay] = None
        self._pending_search_keyword = ''
        self._search_generation = 0
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)
        self._search_timer.timeout.connect(self._trigger_global_search)
        self._keyed_ui_tasks: dict[tuple[str, str], asyncio.Task] = {}
        self._ui_tasks: set[asyncio.Task] = set()
        self._dialog_refs: set[QWidget] = set()
        self._add_friend_dialog: AddFriendDialog | None = None
        self._create_group_dialog: CreateGroupDialog | None = None
        self._current_user_id = ""
        self._initial_load_done = False
        self._destroyed = False
        self._teardown_started = False
        self._event_bus = get_event_bus()
        self._connection_manager = get_connection_manager()
        self._friend_section_headers: dict[str, QWidget] = {}
        self._friend_section_widgets: dict[str, QWidget] = {}
        self._friend_section_layouts: dict[str, QVBoxLayout] = {}
        self._friend_item_sections: dict[str, str] = {}
        self._setup_ui()
        self._connect_signals()
        self.destroyed.connect(self._on_destroyed)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.ensure_initial_load()

    def ensure_initial_load(self) -> None:
        """Kick off the first contact snapshot load once per runtime."""
        if self._initial_load_done:
            return
        self._initial_load_done = True
        logger.info("Contact interface first load requested")
        QTimer.singleShot(0, self.reload_data)

    def _setup_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setObjectName("contactSplitter")
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)

        sidebar = QWidget(self)
        sidebar.setObjectName("ContactSidebarCard")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        self.search_bar = QWidget(sidebar)
        self.search_bar.setObjectName("sessionSearchBar")
        search_row = QHBoxLayout(self.search_bar)
        search_row.setContentsMargins(12, 12, 12, 12)
        search_row.setSpacing(12)
        self.search_box = SearchLineEdit(self.search_bar)
        self.search_box.setPlaceholderText(tr("session.search.placeholder", "搜索"))
        self.search_box.setFixedHeight(36)
        self.add_button = ToolButton(AppIcon.ADD, self.search_bar)
        self.add_button.setObjectName("sessionAddButton")
        self.add_button.setToolTip(tr("contact.sidebar.add_tooltip", "Add"))
        self.add_button.setFixedSize(36, 36)
        search_row.addWidget(self.search_box, 1)
        search_row.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.segmented = SegmentedWidget(sidebar)
        self.segmented.addItem("friends", tr("contact.sidebar.tab.friends", "Friends"), lambda: self._switch_page("friends"))
        self.segmented.addItem("groups", tr("contact.sidebar.tab.groups", "Groups"), lambda: self._switch_page("groups"))
        self.segmented.addItem("requests", tr("contact.sidebar.tab.requests", "New Friends"), lambda: self._switch_page("requests"))
        self.segmented.addItem("blocked", tr("contact.sidebar.tab.blocked", "Blocked"), lambda: self._switch_page("blocked"))
        self.segmented.setMinimumHeight(36)

        self.page_stack = QStackedWidget(sidebar)
        self.friends_page, self.friends_container, self.friends_layout = self._create_scroll_page()
        self.groups_page, self.groups_container, self.groups_layout = self._create_scroll_page()
        self.requests_page, self.requests_container, self.requests_layout = self._create_scroll_page()
        self.blocked_page, self.blocked_container, self.blocked_layout = self._create_scroll_page()
        self.page_stack.addWidget(self.friends_page)
        self.page_stack.addWidget(self.groups_page)
        self.page_stack.addWidget(self.requests_page)
        self.page_stack.addWidget(self.blocked_page)

        segmented_row = QWidget(sidebar)
        segmented_layout = QHBoxLayout(segmented_row)
        segmented_layout.setContentsMargins(12, 0, 12, 8)
        segmented_layout.setSpacing(0)
        segmented_layout.addWidget(self.segmented, 1)

        sidebar_layout.addWidget(self.search_bar)
        sidebar_layout.addWidget(segmented_row)
        sidebar_layout.addWidget(self.page_stack, 1)

        left = QWidget(self)
        left.setMinimumWidth(260)
        left.setMaximumWidth(560)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(sidebar)

        self.detail_stack = QStackedWidget(self)
        self.detail_stack.setObjectName("contactDetailStack")
        self.welcome_panel = ContactWelcomeWidget(self.detail_stack)
        self.detail_panel = GalleryContactDetailPanel(self.detail_stack)
        self.detail_stack.addWidget(self.welcome_panel)
        self.detail_stack.addWidget(self.detail_panel)

        splitter.addWidget(left)
        splitter.addWidget(self.detail_stack)
        splitter.setSizes([320, 880])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        StyleSheet.CONTACT_INTERFACE.apply(self)
        self.segmented.setCurrentItem("friends")
        self._show_welcome_panel()
        self._switch_page("friends")

    def _connect_signals(self) -> None:
        self.add_button.clicked.connect(self._show_add_placeholder)
        self.search_box.textChanged.connect(self._on_search_text_changed)
        self.detail_panel.message_requested.connect(self.message_requested.emit)
        self.detail_panel.call_requested.connect(self.call_requested.emit)
        self.detail_panel.remark_edit_requested.connect(self._on_friend_remark_edit_requested)
        self.detail_panel.friend_moments_requested.connect(self._on_friend_moments_requested)
        self._event_bus.subscribe_sync(ContactEvent.SYNC_REQUIRED, self._on_contact_sync_required)
        self._connection_manager.add_state_listener(self._on_connection_state_changed)

    def _create_scroll_page(self) -> tuple[ScrollArea, QWidget, QVBoxLayout]:
        area = ScrollArea(self)
        area.setObjectName("contactListScrollArea")
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget(area)
        container.setObjectName("contactListScrollWidget")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch(1)
        area.setWidget(container)
        return area, container, layout

    def _show_welcome_panel(self) -> None:
        self.detail_stack.setCurrentWidget(self.welcome_panel)

    def _show_detail_panel(self) -> None:
        self.detail_stack.setCurrentWidget(self.detail_panel)

    def _activate_page(self, key: str) -> None:
        self._current_page = key
        self.segmented.setCurrentItem(key)
        self.page_stack.setCurrentIndex({"friends": 0, "groups": 1, "requests": 2, "blocked": 3}[key])

    def _switch_page(self, key: str) -> None:
        if key != self._current_page:
            self._clear_active_selection()
        self._activate_page(key)
        self._rebuild_current_page()
        self._refresh_search_surface()

    def reload_data(self) -> None:
        if self._destroyed or not is_valid_qt_object(self):
            return
        self._current_user_id = self._controller.get_current_user_id()
        logger.info("Contact interface reload requested")
        self._set_load_task(self._reload_data_async())

    def _on_contact_sync_required(self, payload: object) -> None:
        """Refresh only the affected contact-domain slices when realtime mutations arrive."""
        if self._destroyed:
            return
        event_payload = dict(payload or {}) if isinstance(payload, dict) else {}
        reason = str(event_payload.get("reason", "") or "")
        if reason == "user_profile_update":
            self._apply_profile_update_payload(dict(event_payload.get("payload") or {}))
            self._refresh_search_surface()
            return
        if reason == "group_profile_update":
            self._apply_group_update_payload(dict(event_payload.get("payload") or {}))
            self._refresh_search_surface()
            return
        if reason == "group_self_profile_update":
            self._apply_group_self_profile_update_payload(dict(event_payload.get("payload") or {}))
            self._refresh_search_surface()
            return
        if reason in {"friend_request_created", "friend_request_updated"}:
            self._schedule_keyed_ui_task(
                ("refresh_requests_slice", self._current_user_id or "self"),
                self._refresh_requests_slice_async,
                f"refresh requests after {reason}",
            )
            return
        if reason in {"friendship_created", "friendship_removed"}:
            self._schedule_keyed_ui_task(
                ("refresh_contacts_requests_slices", self._current_user_id or "self"),
                self._refresh_contacts_and_requests_slices_async,
                f"refresh contacts and requests after {reason}",
            )
            return
        if reason == "friend_remark_updated":
            record = self._contact_record_from_relationship_payload(dict(event_payload.get("payload") or {}))
            if record is not None:
                self._upsert_contact_record(record)
                self._refresh_search_surface()
                return
        self.reload_data()

    def _on_connection_state_changed(self, old_state: ConnectionState, new_state: ConnectionState) -> None:
        """Refresh contact-domain truth after reconnect because contact_refresh is not replayed."""
        if self._destroyed or not self._initial_load_done:
            return
        if old_state == ConnectionState.CONNECTED or new_state != ConnectionState.CONNECTED:
            return
        self.reload_data()

    def _can_update_contact_ui(self) -> bool:
        """Return whether sidebar/detail widgets are still safe to touch."""
        if self._destroyed or not is_valid_qt_object(self):
            return False
        page_stack = getattr(self, "page_stack", None)
        return page_stack is not None and is_valid_qt_object(page_stack)

    async def _refresh_requests_slice_async(self) -> None:
        self._requests = await self._controller.load_requests()
        if self._destroyed:
            return
        self._update_summary_counts()
        self._build_requests_page()
        if self._current_page == "requests":
            self._restore_selection(full_reload=False)
        self._refresh_search_surface()

    async def _refresh_contacts_and_requests_slices_async(self) -> None:
        contacts, requests, blocked = await asyncio.gather(
            self._controller.load_contacts(),
            self._controller.load_requests(),
            self._controller.load_blocked_contacts(),
        )
        self._contacts = contacts
        self._requests = requests
        self._blocked_contacts = blocked
        if self._destroyed:
            return
        self._update_summary_counts()
        self._build_friends_page()
        self._build_requests_page()
        self._build_blocked_page()
        self._restore_selection(full_reload=False)
        self._refresh_search_surface()

    def refresh_profile_related_slices(self) -> None:
        """Refresh self-facing contact slices after the current user changes their profile."""
        if self._destroyed or not self._can_update_contact_ui():
            return
        self._schedule_keyed_ui_task(
            ("refresh_profile_related_slices", self._current_user_id or "self"),
            self._refresh_profile_related_slices_async,
            "refresh profile-related contact slices",
        )

    async def _refresh_profile_related_slices_async(self) -> None:
        contacts, groups, requests, blocked = await asyncio.gather(
            self._controller.load_contacts(),
            self._controller.load_groups(),
            self._controller.load_requests(),
            self._controller.load_blocked_contacts(),
        )
        self._contacts = contacts
        self._groups = groups
        self._requests = requests
        self._blocked_contacts = blocked
        if self._destroyed:
            return
        self._update_summary_counts()
        self._build_friends_page()
        self._build_groups_page()
        self._build_requests_page()
        self._build_blocked_page()
        self._restore_selection(full_reload=False)
        self._refresh_search_surface()

    def _update_friend_item_view(self, contact: ContactRecord) -> None:
        item = self._friend_items.get(contact.id)
        if item is None:
            return
        item.update_content(
            title=self._friend_sidebar_title(contact),
            subtitle="",
            avatar=contact.avatar,
            gender=contact.gender,
            seed_user_id=contact.id,
            seed_username=contact.username,
        )

    def _create_friend_item(self, contact: ContactRecord) -> ContactListItem:
        item = ContactListItem(
            contact.id,
            self._friend_sidebar_title(contact),
            "",
            "",
            contact.avatar,
            left_padding=CONTACT_SECTION_INSET,
        )
        item.clicked.connect(self._select_friend)
        item.context_requested.connect(self._show_friend_context_menu)
        return item

    def _ensure_friend_section_view(self, letter: str) -> QVBoxLayout:
        layout = self._friend_section_layouts.get(letter)
        if layout is not None:
            return layout
        section = QWidget(self.friends_container)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(0)
        header = ContactSectionHeader(letter, section)
        section_layout.addWidget(header)
        insert_at = sum(1 for existing_letter in self._friend_section_widgets if existing_letter < letter)
        self.friends_layout.insertWidget(insert_at, section)
        self._friend_section_headers[letter] = header
        self._friend_section_widgets[letter] = section
        self._friend_section_layouts[letter] = section_layout
        return section_layout

    def _insert_friend_item_view(self, contact: ContactRecord) -> None:
        if contact.id in self._friend_items:
            self._update_friend_item_view(contact)
            return
        if not self._friend_items and not self._friend_section_widgets:
            self._clear_layout(self.friends_layout)
        letter = self._controller.sort_letter(contact.display_name)
        section_layout = self._ensure_friend_section_view(letter)
        section_contacts = [item for item in self._contacts if self._controller.sort_letter(item.display_name) == letter]
        insert_at = 1 + next(
            (
                index
                for index, item in enumerate(section_contacts)
                if item.id == contact.id
            ),
            len(section_contacts) - 1,
        )
        widget = self._create_friend_item(contact)
        section_layout.insertWidget(insert_at, widget)
        self._friend_items[contact.id] = widget
        self._friend_item_sections[contact.id] = letter

    def _remove_friend_item_view(self, contact_id: str) -> None:
        item = self._friend_items.pop(contact_id, None)
        letter = self._friend_item_sections.pop(contact_id, "")
        section_layout = self._friend_section_layouts.get(letter)
        if item is not None:
            if section_layout is not None:
                section_layout.removeWidget(item)
            item.deleteLater()
        if not letter:
            return
        if section_layout is None:
            return
        remaining_items = [widget_id for widget_id, widget_letter in self._friend_item_sections.items() if widget_letter == letter]
        if remaining_items:
            return
        section = self._friend_section_widgets.pop(letter, None)
        self._friend_section_headers.pop(letter, None)
        self._friend_section_layouts.pop(letter, None)
        if section is not None:
            self.friends_layout.removeWidget(section)
            section.deleteLater()
        if not self._friend_items:
            self._add_empty_state(
                self.friends_layout,
                AppIcon.PEOPLE,
                tr("contact.sidebar.empty_friends", "No friends yet"),
            )

    def _update_blocked_item_view(self, contact: ContactRecord) -> None:
        item = self._blocked_items.get(contact.id)
        if item is None:
            return
        item.update_content(
            title=self._friend_sidebar_title(contact),
            subtitle="",
            avatar=contact.avatar,
            gender=contact.gender,
            seed_user_id=contact.id,
            seed_username=contact.username,
        )

    def _create_blocked_item(self, contact: ContactRecord) -> ContactListItem:
        item = ContactListItem(
            contact.id,
            self._friend_sidebar_title(contact),
            "",
            "",
            contact.avatar,
        )
        item.clicked.connect(self._select_blocked)
        item.context_requested.connect(self._show_blocked_context_menu)
        return item

    def _insert_blocked_item_view(self, contact: ContactRecord) -> None:
        if contact.id in self._blocked_items:
            self._update_blocked_item_view(contact)
            return
        if not self._blocked_items:
            self._clear_layout(self.blocked_layout)
            item = self._create_blocked_item(contact)
            self.blocked_layout.addWidget(item)
            self.blocked_layout.addStretch(1)
            self._blocked_items[contact.id] = item
            return
        ordered_ids = [item.id for item in self._blocked_contacts]
        insert_at = ordered_ids.index(contact.id)
        item = self._create_blocked_item(contact)
        self.blocked_layout.insertWidget(insert_at, item)
        self._blocked_items[contact.id] = item

    def _remove_blocked_item_view(self, contact_id: str) -> None:
        item = self._blocked_items.pop(contact_id, None)
        if item is not None:
            self.blocked_layout.removeWidget(item)
            item.deleteLater()
        if self._blocked_items:
            return
        self._clear_layout(self.blocked_layout)
        self._add_empty_state(
            self.blocked_layout,
            AppIcon.PEOPLE,
            tr("contact.sidebar.empty_blocked", "No blocked contacts"),
        )

    def _update_group_item_view(self, group: GroupRecord) -> None:
        item = self._group_items.get(group.id)
        if item is None:
            return
        item.update_content(
            title=group.name,
            subtitle=tr("contact.group.member_summary", "{count} members", count=group.member_count),
            avatar=group.avatar,
            seed_user_id=group.id,
        )

    def _update_request_item_view(self, request: FriendRequestRecord) -> None:
        item = self._request_items.get(request.id)
        if item is None:
            return
        item.update_request(request, self._current_user_id)

    def _ordered_requests(self) -> list[FriendRequestRecord]:
        return sorted(self._requests, key=self._request_sort_key)

    def _visible_requests(self) -> list[FriendRequestRecord]:
        return [request for request in self._ordered_requests() if self._is_visible_request(request)]

    def _is_visible_request(self, request: FriendRequestRecord) -> bool:
        return request.status == "pending" and request.is_incoming(self._current_user_id)

    def _request_sort_key(self, request: FriendRequestRecord) -> tuple[int, float, str]:
        """Keep request ordering stable across reload and realtime upsert paths."""
        if request.is_incoming(self._current_user_id):
            bucket = 0
        elif request.is_outgoing(self._current_user_id):
            bucket = 1
        else:
            bucket = 2
        return (bucket, -self._request_sort_timestamp(request), request.id)

    @staticmethod
    def _request_sort_timestamp(request: FriendRequestRecord) -> float:
        created_at = str(request.created_at or "").strip()
        if not created_at:
            return 0.0
        try:
            return datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0

    def _create_group_item(self, group: GroupRecord) -> ContactListItem:
        item = ContactListItem(
            group.id,
            group.name,
            tr("contact.group.member_summary", "{count} members", count=group.member_count),
            tr("contact.group.badge", "Group"),
            group.avatar,
        )
        item.clicked.connect(self._select_group)
        return item

    def _create_request_item(self, request: FriendRequestRecord) -> RequestListItem:
        item = RequestListItem(request, self._current_user_id, self.requests_container)
        if request.can_review(self._current_user_id):
            item.accept_clicked.connect(self._accept_request)
            item.reject_clicked.connect(self._reject_request)
        item.selected.connect(self._select_request)
        return item

    def _insert_group_item_view(self, group: GroupRecord) -> None:
        if group.id in self._group_items:
            self._update_group_item_view(group)
            return
        if not self._group_items:
            self._clear_layout(self.groups_layout)
            item = self._create_group_item(group)
            self.groups_layout.addWidget(item)
            self.groups_layout.addStretch(1)
            self._group_items[group.id] = item
            return
        ordered_ids = [item.id for item in self._groups]
        insert_at = ordered_ids.index(group.id)
        item = self._create_group_item(group)
        self.groups_layout.insertWidget(insert_at, item)
        self._group_items[group.id] = item

    def _remove_group_item_view(self, group_id: str) -> None:
        item = self._group_items.pop(group_id, None)
        if item is not None:
            self.groups_layout.removeWidget(item)
            item.deleteLater()
        if self._group_items:
            return
        self._clear_layout(self.groups_layout)
        self._add_empty_state(
            self.groups_layout,
            AppIcon.PEOPLE,
            tr("contact.sidebar.empty_groups", "No groups yet"),
        )

    def _insert_request_item_view(self, request: FriendRequestRecord) -> None:
        if not self._is_visible_request(request):
            return
        if request.id in self._request_items:
            self._update_request_item_view(request)
            return
        if not self._request_items:
            self._clear_layout(self.requests_layout)
            item = self._create_request_item(request)
            self.requests_layout.addWidget(item)
            self.requests_layout.addStretch(1)
            self._request_items[request.id] = item
            return
        ordered_ids = [item.id for item in self._visible_requests()]
        insert_at = ordered_ids.index(request.id)
        item = self._create_request_item(request)
        self.requests_layout.insertWidget(insert_at, item)
        self._request_items[request.id] = item

    @staticmethod
    def _contact_record_from_relationship_payload(payload: dict[str, object]) -> ContactRecord | None:
        relationship = dict(payload.get("relationship") or {}) if isinstance(payload.get("relationship"), dict) else dict(payload or {})
        user = dict(relationship.get("user") or {}) if isinstance(relationship.get("user"), dict) else {}
        friendship = dict(relationship.get("friendship") or {}) if isinstance(relationship.get("friendship"), dict) else {}
        contact_id = str(user.get("id", "") or friendship.get("friend_id", "") or "").strip()
        if not contact_id:
            return None
        username = str(user.get("username", "") or "")
        nickname = str(user.get("nickname", "") or "")
        remark = (
            str(friendship.get("remark", "") or "")
            if "remark" in friendship
            else str(user.get("remark", "") or "")
        )
        return ContactRecord(
            id=contact_id,
            name=username or nickname,
            username=username,
            nickname=nickname,
            avatar=str(user.get("avatar", "") or ""),
            remark=remark,
            assistim_id=username,
            region=str(user.get("region", "") or ""),
            signature=str(user.get("signature", "") or ""),
            email=str(user.get("email", "") or ""),
            phone=str(user.get("phone", "") or ""),
            birthday=str(user.get("birthday", "") or ""),
            gender=str(user.get("gender", "") or ""),
            status=str(user.get("status", "") or ""),
            category="friend",
            extra=relationship,
        )

    @staticmethod
    def _request_record_from_payload(payload: dict[str, object]) -> FriendRequestRecord:
        request_payload = dict(payload.get("request") or {}) if isinstance(payload.get("request"), dict) else dict(payload or {})
        from_user = dict(request_payload.get("sender") or {}) if isinstance(request_payload.get("sender"), dict) else {}
        to_user = dict(request_payload.get("receiver") or {}) if isinstance(request_payload.get("receiver"), dict) else {}
        return FriendRequestRecord(
            id=str(request_payload.get("request_id", "") or ""),
            sender_id=str(from_user.get("id", "") or ""),
            receiver_id=str(to_user.get("id", "") or ""),
            message=str(request_payload.get("message", "") or ""),
            status=str(request_payload.get("status", "pending") or "pending"),
            created_at=str(request_payload.get("created_at", "") or ""),
            sender_name=str(from_user.get("nickname", "") or from_user.get("username", "") or ""),
            receiver_name=str(to_user.get("nickname", "") or to_user.get("username", "") or ""),
            sender_username=str(from_user.get("username", "") or ""),
            receiver_username=str(to_user.get("username", "") or ""),
            sender_avatar=str(from_user.get("avatar", "") or ""),
            receiver_avatar=str(to_user.get("avatar", "") or ""),
            sender_gender=str(from_user.get("gender", "") or ""),
            receiver_gender=str(to_user.get("gender", "") or ""),
        )

    def _upsert_request_record(self, request: FriendRequestRecord) -> None:
        previous_order = [item.id for item in self._visible_requests()]
        for index, existing in enumerate(list(self._requests)):
            if existing.id != request.id:
                continue
            self._requests[index] = request
            break
        else:
            self._requests.append(request)
        self._requests = self._ordered_requests()
        self._update_summary_counts()
        current_order = [item.id for item in self._visible_requests()]
        if previous_order != current_order and (self._request_items or self._current_page == "requests"):
            self._build_requests_page()
            if self._current_page == "requests" and request.id in self._request_items:
                self._select_request(request.id, force=True)
            return
        if not self._is_visible_request(request):
            if request.id in self._request_items:
                self._build_requests_page()
            return
        self._update_request_item_view(request)
        if self._selected_key == ("request", request.id):
            self.detail_panel.set_request(request, self._current_user_id)

    def _contact_record_from_request(self, request: FriendRequestRecord) -> ContactRecord:
        counterpart_id = request.counterpart_id(self._current_user_id)
        counterpart_name = request.counterpart_name(self._current_user_id)
        counterpart_avatar = request.counterpart_avatar(self._current_user_id)
        counterpart_gender = request.counterpart_gender(self._current_user_id)
        current_user_is_receiver = request.receiver_id == self._current_user_id
        raw_username = request.sender_username if current_user_is_receiver else request.receiver_username
        username = str(raw_username or "").strip()
        nickname = counterpart_name if counterpart_name and counterpart_name != username else ""
        return ContactRecord(
            id=counterpart_id,
            name=username or counterpart_name,
            username=username,
            nickname=nickname,
            avatar=counterpart_avatar,
            remark="",
            assistim_id=username,
            region="",
            signature="",
            email="",
            phone="",
            birthday="",
            gender=counterpart_gender,
            status="",
            category="friend",
            extra={},
        )

    def _upsert_contact_record(self, contact: ContactRecord, *, select_after_upsert: bool = False) -> None:
        replaced = False
        previous_sort_key: tuple[str, str] | None = None
        for index, existing in enumerate(list(self._contacts)):
            if existing.id != contact.id:
                continue
            previous_sort_key = self._friend_sort_key(existing)
            merged = ContactRecord(
                id=existing.id,
                name=contact.name or existing.name,
                username=contact.username or existing.username,
                nickname=contact.nickname or existing.nickname,
                avatar=contact.avatar or existing.avatar,
                remark=contact.remark,
                assistim_id=contact.assistim_id or existing.assistim_id,
                region=contact.region or existing.region,
                signature=contact.signature or existing.signature,
                email=contact.email or existing.email,
                phone=contact.phone or existing.phone,
                birthday=contact.birthday or existing.birthday,
                gender=contact.gender or existing.gender,
                status=contact.status or existing.status,
                category=existing.category,
                extra={**dict(existing.extra or {}), **dict(contact.extra or {})},
            )
            self._contacts[index] = merged
            replaced = True
            contact = merged
            break
        if not replaced:
            self._contacts.append(contact)

        self._contacts.sort(key=self._friend_sort_key)
        self._update_summary_counts()
        if self._friend_items or self._current_page == "friends":
            current_sort_key = self._friend_sort_key(contact)
            if previous_sort_key is not None and previous_sort_key != current_sort_key:
                self._build_friends_page()
                if self._current_page == "friends":
                    self._restore_selection(full_reload=False)
            elif previous_sort_key is None:
                self._insert_friend_item_view(contact)
            else:
                self._update_friend_item_view(contact)

        if select_after_upsert:
            self._activate_page("friends")
            if contact.id in self._friend_items:
                self._select_friend(contact.id, force=True)
                return

        if self._current_page == "friends":
            self._restore_selection(full_reload=False)
        self._schedule_contacts_cache_persist()

    def _upsert_blocked_contact_record(self, contact: ContactRecord) -> None:
        """Insert or replace one blocked contact in the current in-memory snapshot."""
        blocked_contact = ContactRecord(
            id=contact.id,
            name=contact.name,
            username=contact.username,
            nickname=contact.nickname,
            avatar=contact.avatar,
            remark=contact.remark,
            assistim_id=contact.assistim_id,
            region=contact.region,
            signature=contact.signature,
            email=contact.email,
            phone=contact.phone,
            birthday=contact.birthday,
            gender=contact.gender,
            status=contact.status,
            category="blocked",
            extra=dict(contact.extra or {}),
        )
        for index, existing in enumerate(list(self._blocked_contacts)):
            if existing.id == blocked_contact.id:
                self._blocked_contacts[index] = blocked_contact
                break
        else:
            self._blocked_contacts.append(blocked_contact)
        self._blocked_contacts.sort(key=self._friend_sort_key)
        self._update_summary_counts()
        if self._blocked_items or self._current_page == "blocked":
            self._insert_blocked_item_view(blocked_contact)
        if self._selected_key == ("blocked", blocked_contact.id):
            self.detail_panel.set_blocked_contact(blocked_contact)

    def _friend_sort_key(self, contact: ContactRecord) -> tuple[str, str]:
        """Return the sidebar ordering key for one friend entry."""
        display_name = contact.display_name
        return self._controller.sort_letter(display_name), display_name.lower()

    @staticmethod
    def _group_member_display_name(member: dict[str, object]) -> str:
        """Resolve one stable group-member display name for contact-side caches and detail views."""
        return (
            str(member.get("remark", "") or "").strip()
            or str(member.get("group_nickname", "") or "").strip()
            or str(member.get("nickname", "") or "").strip()
            or str(member.get("display_name", "") or "").strip()
            or str(member.get("username", "") or "").strip()
            or str(member.get("user_id", "") or "").strip()
            or str(member.get("id", "") or "").strip()
        )

    def _schedule_groups_cache_persist(self) -> None:
        """Persist the current normalized group snapshot after local incremental mutations."""
        self._schedule_keyed_ui_task(
            ("persist_groups_cache", "groups"),
            lambda: self._controller.persist_groups_cache(list(self._groups)),
            "persist groups cache",
        )

    def _schedule_contacts_cache_persist(self) -> None:
        """Persist the current normalized contact snapshot after local incremental mutations."""
        self._schedule_keyed_ui_task(
            ("persist_contacts_cache", "contacts"),
            lambda: self._controller.persist_contacts_cache(list(self._contacts)),
            "persist contacts cache",
        )

    def _sync_group_record_view(self, group: GroupRecord, *, rebuild: bool) -> None:
        """Update the group sidebar/detail widgets after the controller produced a new record."""
        self._update_summary_counts()
        needs_selection_restore = False
        if rebuild:
            if group.id in self._group_items:
                self._remove_group_item_view(group.id)
            self._insert_group_item_view(group)
            needs_selection_restore = self._current_page == "groups"
        elif group.id in self._group_items:
            self._update_group_item_view(group)
        elif self._group_items or self._current_page == "groups":
            self._insert_group_item_view(group)
            needs_selection_restore = self._current_page == "groups"

        if needs_selection_restore:
            self._restore_selection(full_reload=False)

    def _apply_group_update_payload(self, payload: dict[str, object]) -> None:
        """Apply one realtime shared group-profile update without reloading the contact page."""
        group_payload = dict(payload.get("group") or payload) if isinstance(payload, dict) else {}
        groups, record, rebuild = self._controller.merge_group_record(self._groups, group_payload)
        if record is None:
            return
        self._groups = groups
        self._sync_group_record_view(record, rebuild=rebuild)
        self._schedule_groups_cache_persist()

    def _apply_group_self_profile_update_payload(self, payload: dict[str, object]) -> None:
        """Apply one realtime self-scoped group-profile update without reloading the contact page."""
        groups, record = self._controller.apply_group_self_profile_update(self._groups, payload)
        if record is None:
            return
        self._groups = groups
        self._sync_group_record_view(record, rebuild=False)
        self._schedule_groups_cache_persist()

    def _apply_profile_update_payload(self, payload: dict[str, object]) -> None:
        """Apply one realtime user-profile update without reloading the whole contact page."""
        user_id = str(payload.get("user_id", "") or "").strip()
        if not user_id:
            return

        profile = dict(payload.get("profile") or {}) if isinstance(payload.get("profile"), dict) else {}
        session_id = str(payload.get("session_id", "") or "").strip()
        session_avatar = str(payload.get("session_avatar", "") or "").strip()
        profile_display_name = (
            str(profile.get("display_name", "") or "").strip()
            or str(profile.get("nickname", "") or "").strip()
            or str(profile.get("username", "") or "").strip()
        )

        contacts_changed = False
        groups_changed = False

        for index, contact in enumerate(list(self._contacts)):
            if contact.id != user_id:
                continue
            previous_sort_key = self._friend_sort_key(contact)
            updated = ContactRecord(
                id=contact.id,
                name=str(profile.get("username", "") or contact.name or contact.username),
                username=str(profile.get("username", "") or contact.username),
                nickname=str(profile.get("nickname", "") or contact.nickname),
                avatar=str(profile.get("avatar", "") or contact.avatar),
                remark=contact.remark,
                assistim_id=contact.assistim_id,
                region=str(profile.get("region", "") or contact.region),
                signature=str(profile.get("signature", "") or contact.signature),
                email=contact.email,
                phone=contact.phone,
                birthday=contact.birthday,
                gender=str(profile.get("gender", "") or contact.gender),
                status=str(profile.get("status", "") or contact.status),
                category=contact.category,
                extra={**dict(contact.extra or {}), **profile},
            )
            self._contacts[index] = updated
            contacts_changed = True
            self._contacts.sort(key=self._friend_sort_key)
            if previous_sort_key != self._friend_sort_key(updated):
                self._remove_friend_item_view(updated.id)
                self._insert_friend_item_view(updated)
            else:
                self._update_friend_item_view(updated)
            if self._selected_key == ("friend", updated.id):
                self.detail_panel.set_contact(updated)

        if contacts_changed and self._current_page == "friends":
            self._restore_selection(full_reload=False)

        for index, contact in enumerate(list(self._blocked_contacts)):
            if contact.id != user_id:
                continue
            updated = ContactRecord(
                id=contact.id,
                name=str(profile.get("username", "") or contact.name or contact.username),
                username=str(profile.get("username", "") or contact.username),
                nickname=str(profile.get("nickname", "") or contact.nickname),
                avatar=str(profile.get("avatar", "") or contact.avatar),
                remark=contact.remark,
                assistim_id=contact.assistim_id,
                region=str(profile.get("region", "") or contact.region),
                signature=str(profile.get("signature", "") or contact.signature),
                email=contact.email,
                phone=contact.phone,
                birthday=contact.birthday,
                gender=str(profile.get("gender", "") or contact.gender),
                status=str(profile.get("status", "") or contact.status),
                category="blocked",
                extra={**dict(contact.extra or {}), **profile},
            )
            self._blocked_contacts[index] = updated
            self._blocked_contacts.sort(key=self._friend_sort_key)
            self._update_blocked_item_view(updated)

        for index, group in enumerate(list(self._groups)):
            group_changed = False
            avatar_changed = bool(session_id and group.session_id == session_id and session_avatar and group.avatar != session_avatar)
            merged_payload = dict(group.extra or {})
            raw_members = [dict(item or {}) for item in list(merged_payload.get("members") or []) if isinstance(item, dict)]
            if raw_members:
                updated_members = []
                for raw_member in raw_members:
                    member = dict(raw_member or {})
                    member_id = str(member.get("id", "") or member.get("user_id", "") or "").strip()
                    if member_id == user_id:
                        updated_values = {
                            "username": str(profile.get("username", "") or "").strip(),
                            "nickname": str(profile.get("nickname", "") or "").strip(),
                            "avatar": str(profile.get("avatar", "") or "").strip(),
                            "gender": str(profile.get("gender", "") or "").strip(),
                        }
                        for key, value in updated_values.items():
                            if str(member.get(key, "") or "").strip() != value:
                                member[key] = value
                                group_changed = True
                    next_display_name = self._group_member_display_name(member)
                    if str(member.get("display_name", "") or "").strip() != next_display_name:
                        member["display_name"] = next_display_name
                        group_changed = True
                    updated_members.append(member)
                if group_changed:
                    merged_payload["members"] = updated_members
            if avatar_changed:
                merged_payload["avatar"] = session_avatar
                group_changed = True
            if not group_changed:
                continue
            updated = self._controller.normalize_group_record(merged_payload, existing=group, fallback_id=group.id)
            if updated is None:
                continue
            self._groups[index] = updated
            groups_changed = True
            if avatar_changed:
                self._update_group_item_view(updated)

        for index, request in enumerate(list(self._requests)):
            updated_request = request
            changed = False
            if request.sender_id == user_id:
                sender_name = str(profile_display_name or request.sender_name)
                sender_avatar = str(profile.get("avatar", "") or request.sender_avatar)
                sender_gender = str(profile.get("gender", "") or request.sender_gender)
                if (sender_name, sender_avatar, sender_gender) != (request.sender_name, request.sender_avatar, request.sender_gender):
                    updated_request = FriendRequestRecord(
                        id=request.id,
                        sender_id=request.sender_id,
                        receiver_id=request.receiver_id,
                        message=request.message,
                        status=request.status,
                        created_at=request.created_at,
                        sender_name=sender_name,
                        receiver_name=request.receiver_name,
                        sender_username=request.sender_username,
                        receiver_username=request.receiver_username,
                        sender_avatar=sender_avatar,
                        receiver_avatar=request.receiver_avatar,
                        sender_gender=sender_gender,
                        receiver_gender=request.receiver_gender,
                    )
                    changed = True
            elif request.receiver_id == user_id:
                receiver_name = str(profile_display_name or request.receiver_name)
                receiver_avatar = str(profile.get("avatar", "") or request.receiver_avatar)
                receiver_gender = str(profile.get("gender", "") or request.receiver_gender)
                if (receiver_name, receiver_avatar, receiver_gender) != (request.receiver_name, request.receiver_avatar, request.receiver_gender):
                    updated_request = FriendRequestRecord(
                        id=request.id,
                        sender_id=request.sender_id,
                        receiver_id=request.receiver_id,
                        message=request.message,
                        status=request.status,
                        created_at=request.created_at,
                        sender_name=request.sender_name,
                        receiver_name=receiver_name,
                        sender_username=request.sender_username,
                        receiver_username=request.receiver_username,
                        sender_avatar=request.sender_avatar,
                        receiver_avatar=receiver_avatar,
                        sender_gender=request.sender_gender,
                        receiver_gender=receiver_gender,
                    )
                    changed = True
            if not changed:
                continue
            self._requests[index] = updated_request
            self._update_request_item_view(updated_request)
        if contacts_changed:
            self._schedule_contacts_cache_persist()
        if groups_changed:
            self._schedule_groups_cache_persist()

    async def _reload_data_async(self) -> None:
        if not self._can_update_contact_ui():
            return
        logger.info("Contact interface reload started")
        try:
            contacts = await self._controller.load_contacts()
            if self._destroyed:
                return
            await asyncio.sleep(0)
            groups = await self._controller.load_groups()
            if self._destroyed:
                return
            await asyncio.sleep(0)
            requests = await self._controller.load_requests()
            if self._destroyed:
                return
            await asyncio.sleep(0)
            blocked = await self._controller.load_blocked_contacts()
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self._can_update_contact_ui():
                return
            raise

        if not self._can_update_contact_ui():
            return
        self._contacts = contacts
        self._groups = groups
        self._requests = requests
        self._blocked_contacts = blocked
        logger.info(
            "Contact interface reload fetched %d friends, %d groups, %d requests, %d blocked contacts",
            len(self._contacts),
            len(self._groups),
            len(self._requests),
            len(self._blocked_contacts),
        )
        self._update_summary_counts()
        logger.info("Contact interface rebuilding sidebar pages")
        self._build_friends_page()
        self._build_groups_page()
        self._build_requests_page()
        self._build_blocked_page()
        logger.info("Contact interface restoring selection")
        self._restore_selection(full_reload=True)
        keyword = self.search_box.text().strip()
        if keyword:
            flyout_view = self._show_search_flyout()
            if flyout_view is not None:
                flyout_view.set_loading(keyword)
            self._search_generation += 1
            self._set_search_task(self._run_global_search(keyword, self._search_generation))
        logger.info("Contact interface reload finished")

    def _rebuild_current_page(self) -> None:
        if self._current_page == "friends":
            self._build_friends_page()
        elif self._current_page == "groups":
            self._build_groups_page()
        elif self._current_page == "requests":
            self._build_requests_page()
        else:
            self._build_blocked_page()
        self._restore_selection(full_reload=False)

    def _update_summary_counts(self) -> None:
        return

    def _on_search_text_changed(self, text: str) -> None:
        """Open or update the anchored search flyout for the current keyword."""
        keyword = str(text or "").strip()
        self._pending_search_keyword = keyword

        if self._current_page in {"requests", "blocked"}:
            self._search_timer.stop()
            self._cancel_pending_task(self._search_task)
            self._search_task = None
            self._dismiss_search_flyout(clear_results=True)
            if self._current_page == "requests":
                self._build_requests_page()
            else:
                self._build_blocked_page()
            self._restore_selection(full_reload=False)
            return

        if not keyword:
            self._search_timer.stop()
            self._cancel_pending_task(self._search_task)
            self._search_task = None
            self._dismiss_search_flyout(clear_results=True)
            return

        self._search_timer.start()

    def _trigger_global_search(self) -> None:
        """Run the latest pending grouped sidebar search request."""
        keyword = self._pending_search_keyword
        if not keyword or self._current_page in {"requests", "blocked"}:
            return
        self._search_generation += 1
        generation = self._search_generation
        flyout_view = self._show_search_flyout()
        if flyout_view is not None:
            flyout_view.set_loading(keyword)
        self._set_search_task(self._run_global_search(keyword, generation))

    async def _run_global_search(self, keyword: str, generation: int) -> None:
        """Populate grouped local-search results for the contact sidebar."""
        results = await search_all(keyword, message_limit=30, contact_limit=30, group_limit=30)
        if (
            self._destroyed
            or self.search_box.text().strip() != keyword
            or generation != self._search_generation
            or self._current_page in {"requests", "blocked"}
        ):
            return
        flyout_view = self._show_search_flyout()
        if flyout_view is not None:
            flyout_view.set_results(keyword, results)

    def _on_search_result_activated(self, payload: object) -> None:
        """Route one grouped-search result into local detail selection or chat open flow."""
        if not isinstance(payload, dict):
            return
        target_type = str(payload.get("type", "") or "")
        data = dict(payload.get("data") or {}) if isinstance(payload.get("data"), dict) else {}
        if target_type == "contact":
            contact_id = str(data.get("id", "") or data.get("user_id", "") or "").strip()
            if contact_id and contact_id in self._friend_items:
                self._activate_page("friends")
                self._select_friend(contact_id, force=True)
                self.clear_search()
            return
        if target_type == "group":
            group_id = str(data.get("id", "") or data.get("group_id", "") or "").strip()
            if group_id and group_id in self._group_items:
                self._activate_page("groups")
                self._select_group(group_id, force=True)
                self.clear_search()
            return

        routed_payload = dict(payload)
        routed_payload["_clear_contact_search"] = True
        self.message_requested.emit(routed_payload)

    def _on_remove_friend_requested(self, payload: object) -> None:
        """Confirm and remove one selected friend from the contact page."""
        if not isinstance(payload, dict):
            return
        contact = payload.get("data")
        if not isinstance(contact, ContactRecord):
            return
        contact_id = str(contact.id or "").strip()
        if not contact_id:
            return
        dialog = RemoveFriendConfirmDialog(contact.display_name, self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._schedule_keyed_ui_task(
            ("remove_friend", contact_id),
            lambda: self._remove_friend_async(contact_id, contact.display_name),
            f"remove friend {contact_id}",
        )

    def _on_friend_remark_edit_requested(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        contact = payload.get("data")
        if not isinstance(contact, ContactRecord):
            return
        dialog = EditFriendRemarkDialog(contact, self.window())
        dialog.submitted.connect(self._request_friend_remark_update)
        self._show_dialog(dialog)

    def _request_friend_remark_update(self, contact_id: str, remark: str) -> None:
        normalized_contact_id = str(contact_id or "").strip()
        if not normalized_contact_id:
            return
        self._schedule_keyed_ui_task(
            ("friend_remark", normalized_contact_id),
            lambda: self._update_friend_remark_async(normalized_contact_id, str(remark or "").strip()),
            f"update friend remark {normalized_contact_id}",
        )

    async def _update_friend_remark_async(self, contact_id: str, remark: str) -> None:
        try:
            contact = await self._controller.update_friend_remark(contact_id, remark)
        except Exception:
            InfoBar.error(
                tr("contact.detail.edit_remark.title", "Edit Remark"),
                tr("contact.detail.edit_remark.failed", "Unable to update the remark right now."),
                parent=self.window(),
                duration=2200,
            )
            raise
        self._upsert_contact_record(contact)
        if self._selected_key == ("friend", contact.id):
            self.detail_panel.set_contact(contact)
        self._refresh_search_surface()

    def _on_friend_moments_requested(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        contact = payload.get("data")
        if not isinstance(contact, ContactRecord):
            return
        InfoBar.info(
            tr("contact.detail.moments", "Moments"),
            tr("contact.detail.moments_coming_soon", "Friend timeline view will open here later."),
            parent=self.window(),
            duration=1600,
        )

    def _show_friend_context_menu(self, contact_id: str, global_pos: QPoint) -> None:
        """Show friend management actions for one sidebar contact item."""
        contact = next((item for item in self._contacts if item.id == contact_id), None)
        if contact is None:
            return

        menu = RoundMenu(parent=self)
        menu.setMinimumWidth(148)
        message_action = Action(tr("contact.detail.action.message", "Message"), self)
        block_action = Action(tr("contact.context.block", "Block"), self)
        remove_action = Action(tr("contact.detail.action.remove_friend", "Remove Friend"), self)

        menu.addAction(message_action)
        menu.addSeparator()
        menu.addAction(block_action)
        menu.addAction(remove_action)

        for action in (block_action, remove_action):
            action_item = action.property("item")
            if action_item is not None:
                action_item.setForeground(QColor("#d13438"))

        message_action.triggered.connect(
            lambda _checked=False, item=contact: self.message_requested.emit({"type": "friend", "data": item})
        )
        block_action.triggered.connect(lambda _checked=False, cid=contact_id: self._on_block_friend_requested(cid))
        remove_action.triggered.connect(
            lambda _checked=False, item=contact: self._on_remove_friend_requested({"type": "friend", "data": item})
        )

        menu.exec(global_pos)

    def _show_blocked_context_menu(self, contact_id: str, global_pos: QPoint) -> None:
        """Show block-list actions for one sidebar contact item."""
        contact = next((item for item in self._blocked_contacts if item.id == contact_id), None)
        if contact is None:
            return

        menu = RoundMenu(parent=self)
        menu.setMinimumWidth(148)
        unblock_action = Action(tr("contact.context.unblock", "Unblock"), self)
        menu.addAction(unblock_action)
        unblock_action.triggered.connect(lambda _checked=False, cid=contact_id: self._on_unblock_contact_requested(cid))
        menu.exec(global_pos)

    def _on_block_friend_requested(self, contact_id: str) -> None:
        """Confirm and block one selected friend from the contact list."""
        contact = next((item for item in self._contacts if item.id == contact_id), None)
        if contact is None:
            return
        dialog = BlockFriendConfirmDialog(contact.display_name, self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._schedule_keyed_ui_task(
            ("block_friend", contact_id),
            lambda: self._block_friend_async(contact_id, contact.display_name),
            f"block friend {contact_id}",
        )

    def _on_unblock_contact_requested(self, contact_id: str) -> None:
        """Unblock one contact from the block-list page."""
        contact = next((item for item in self._blocked_contacts if item.id == contact_id), None)
        if contact is None:
            return
        self._schedule_keyed_ui_task(
            ("unblock_contact", contact_id),
            lambda: self._unblock_contact_async(contact_id, contact.display_name),
            f"unblock contact {contact_id}",
        )

    async def _remove_friend_async(self, contact_id: str, display_name: str) -> None:
        try:
            await self._controller.remove_friend(contact_id)
        except Exception:
            InfoBar.error(
                tr("contact.detail.remove_friend.title", "Remove Friend"),
                tr("contact.detail.remove_friend.failed", "Unable to remove this friend right now."),
                parent=self.window(),
                duration=2400,
            )
            raise

        self._contacts = [item for item in self._contacts if item.id != contact_id]
        self._remove_friend_item_view(contact_id)
        self._update_summary_counts()
        self._schedule_contacts_cache_persist()
        self._refresh_search_surface()
        if self._selected_key == ("friend", contact_id):
            self._clear_active_selection()

        InfoBar.success(
            tr("contact.detail.remove_friend.title", "Remove Friend"),
            tr(
                "contact.detail.remove_friend.success",
                "{name} has been removed.",
                name=display_name or contact_id,
            ),
            parent=self.window(),
            duration=1800,
        )

    async def _block_friend_async(self, contact_id: str, display_name: str) -> None:
        blocked_contact = next((item for item in self._contacts if item.id == contact_id), None)
        try:
            await self._controller.block_user(contact_id)
        except Exception:
            InfoBar.error(
                tr("contact.detail.block_friend.title", "Block Contact"),
                tr("contact.detail.block_friend.failed", "Unable to block this contact right now."),
                parent=self.window(),
                duration=2400,
            )
            raise

        self._contacts = [item for item in self._contacts if item.id != contact_id]
        self._remove_friend_item_view(contact_id)
        if blocked_contact is not None:
            self._upsert_blocked_contact_record(blocked_contact)
        self._update_summary_counts()
        self._schedule_contacts_cache_persist()
        self._refresh_search_surface()
        if self._selected_key == ("friend", contact_id):
            self._clear_active_selection()

        InfoBar.success(
            tr("contact.detail.block_friend.title", "Block Contact"),
            tr(
                "contact.detail.block_friend.success",
                "{name} has been blocked.",
                name=display_name or contact_id,
            ),
            parent=self.window(),
            duration=1800,
        )

    async def _unblock_contact_async(self, contact_id: str, display_name: str) -> None:
        try:
            await self._controller.unblock_user(contact_id)
        except Exception:
            InfoBar.error(
                tr("contact.detail.unblock_contact.title", "Unblock Contact"),
                tr("contact.detail.unblock_contact.failed", "Unable to unblock this contact right now."),
                parent=self.window(),
                duration=2400,
            )
            raise

        self._blocked_contacts = [item for item in self._blocked_contacts if item.id != contact_id]
        self._remove_blocked_item_view(contact_id)
        self._update_summary_counts()
        self._refresh_search_surface()
        if self._selected_key == ("blocked", contact_id):
            self._clear_active_selection()

        InfoBar.success(
            tr("contact.detail.unblock_contact.title", "Unblock Contact"),
            tr(
                "contact.detail.unblock_contact.success",
                "{name} has been unblocked.",
                name=display_name or contact_id,
            ),
            parent=self.window(),
            duration=1800,
        )

    def clear_search(self) -> None:
        """Clear the shared sidebar search box and anchored results flyout."""
        self.search_box.clear()
        self._dismiss_search_flyout(clear_results=True)

    def _show_search_flyout(self) -> Optional[GlobalSearchPopupOverlay]:
        """Create or reuse the anchored search overlay below the search box."""
        if self._search_flyout_view is not None and self._search_flyout is not None:
            self._search_flyout_view.set_content_width(self.search_box.width() + 72)
            self._search_flyout_view.show_for(self.search_box)
            return self._search_flyout_view

        host = self.window() or self
        view = GlobalSearchPopupOverlay(host)
        view.set_content_width(self.search_box.width() + 72)
        view.resultActivated.connect(self._on_search_result_activated)
        view.closed.connect(self._on_search_flyout_closed)
        view.show_for(self.search_box)
        self._search_flyout = view
        self._search_flyout_view = view
        return view

    def _dismiss_search_flyout(self, *, clear_results: bool) -> None:
        """Close the anchored search overlay when the search is cleared or completed."""
        if self._search_flyout_view is not None and clear_results:
            self._search_flyout_view.clear_results()
        if self._search_flyout is not None:
            self._search_flyout.close_overlay()
        else:
            self._clear_search_flyout()

    def _clear_search_flyout(self) -> None:
        """Drop stale search-overlay references after the popup closes."""
        self._search_flyout = None
        self._search_flyout_view = None

    def _on_search_flyout_closed(self) -> None:
        """Reset search state when the overlay closes outside normal clear flow."""
        self._clear_search_flyout()

    def _refresh_search_surface(self) -> None:
        keyword = self.search_box.text().strip()
        if self._current_page in {"requests", "blocked"}:
            if keyword:
                if self._current_page == "requests":
                    self._build_requests_page()
                else:
                    self._build_blocked_page()
                self._restore_selection(full_reload=False)
            return
        if not keyword or self._search_flyout_view is None:
            return
        self._search_generation += 1
        generation = self._search_generation
        flyout_view = self._show_search_flyout()
        if flyout_view is not None:
            flyout_view.set_loading(keyword)
        self._set_search_task(self._run_global_search(keyword, generation))

    @staticmethod
    def _friend_assistim_line(contact: ContactRecord) -> str:
        return str(contact.assistim_id or contact.username or "").strip() or "-"

    @staticmethod
    def _friend_sidebar_title(contact: ContactRecord) -> str:
        return (
            str(contact.remark or "").strip()
            or str(contact.nickname or "").strip()
            or str(contact.username or "").strip()
            or contact.display_name
        )

    def _clear_active_selection(self) -> None:
        self._selected_key = None
        self._cancel_friend_moment_task()
        self._clear_selection()
        self.detail_panel.show_placeholder()
        self._show_welcome_panel()

    def _resolve_detail_selection_payload(self, kind: str, selection_id: str) -> ContactRecord | FriendRequestRecord | None:
        """Resolve the latest selected record before re-painting the detail panel."""
        if kind == "friend":
            return next((item for item in self._contacts if item.id == selection_id), None)
        if kind == "blocked":
            return next((item for item in self._blocked_contacts if item.id == selection_id), None)
        if kind == "request":
            return next((item for item in self._requests if item.id == selection_id), None)
        return None

    def _build_friends_page(self) -> None:
        self._clear_layout(self.friends_layout)
        self._friend_items.clear()
        self._friend_section_headers.clear()
        self._friend_section_widgets.clear()
        self._friend_section_layouts.clear()
        self._friend_item_sections.clear()
        grouped = self._controller.group_contacts(self._contacts)
        if not self._contacts:
            self._add_empty_state(
                self.friends_layout,
                AppIcon.PEOPLE,
                tr("contact.sidebar.empty_friends", "No friends yet"),
            )
            return
        for letter, contacts in grouped.items():
            self._ensure_friend_section_view(letter)
            for contact in contacts:
                self._insert_friend_item_view(contact)
        self.friends_layout.addStretch(1)

    def _build_groups_page(self) -> None:
        self._clear_layout(self.groups_layout)
        self._group_items.clear()
        if not self._groups:
            self._add_empty_state(
                self.groups_layout,
                AppIcon.PEOPLE,
                tr("contact.sidebar.empty_groups", "No groups yet"),
            )
            return
        for group in self._groups:
            item = self._create_group_item(group)
            self.groups_layout.addWidget(item)
            self._group_items[group.id] = item
        self.groups_layout.addStretch(1)

    def _build_requests_page(self) -> None:
        self._clear_layout(self.requests_layout)
        self._request_items.clear()
        requests = self._visible_requests()
        keyword = self.search_box.text().strip().lower() if self._current_page == "requests" else ""
        if keyword:
            requests = [
                item
                for item in requests
                if keyword in str(item.counterpart_name(self._current_user_id) or "").lower()
                or keyword in str(item.counterpart_id(self._current_user_id) or "").lower()
                or keyword in str(item.message or "").lower()
            ]
        if not requests:
            self._add_empty_state(
                self.requests_layout,
                AppIcon.ADD,
                tr("contact.sidebar.empty_requests", "No new friend requests")
                if not keyword
                else tr("contact.request.empty_results", "No matching friend requests."),
            )
            return

        incoming = [item for item in requests if item.is_incoming(self._current_user_id)]
        outgoing = [item for item in requests if item.is_outgoing(self._current_user_id)]
        unknown = [item for item in requests if not item.is_incoming(self._current_user_id) and not item.is_outgoing(self._current_user_id)]
        ordered_requests = incoming + outgoing + unknown
        for request in ordered_requests:
            item = self._create_request_item(request)
            self.requests_layout.addWidget(item)
            self._request_items[request.id] = item
        self.requests_layout.addStretch(1)

    def _build_blocked_page(self) -> None:
        self._clear_layout(self.blocked_layout)
        self._blocked_items.clear()
        contacts = list(self._blocked_contacts)
        keyword = self.search_box.text().strip().lower() if self._current_page == "blocked" else ""
        if keyword:
            contacts = [
                item
                for item in contacts
                if keyword in str(item.display_name or "").lower()
                or keyword in str(item.username or "").lower()
                or keyword in str(item.assistim_id or "").lower()
            ]
        if not contacts:
            self._add_empty_state(
                self.blocked_layout,
                AppIcon.PEOPLE,
                tr("contact.sidebar.empty_blocked", "No blocked contacts")
                if not keyword
                else tr("contact.blocked.empty_results", "No matching blocked contacts."),
            )
            return
        for contact in contacts:
            item = self._create_blocked_item(contact)
            self.blocked_layout.addWidget(item)
            self._blocked_items[contact.id] = item
        self.blocked_layout.addStretch(1)

    def _restore_selection(self, full_reload: bool) -> None:
        current_map = {
            "friends": self._friend_items,
            "groups": self._group_items,
            "requests": self._request_items,
            "blocked": self._blocked_items,
        }
        current_category = {"friends": "friend", "groups": "group", "requests": "request", "blocked": "blocked"}[self._current_page]
        if self._selected_key:
            category, item_id = self._selected_key
            if category != current_category:
                self._clear_active_selection()
                return
            if category == "friend" and item_id in self._friend_items:
                self._select_friend(item_id, force=True)
                return
            if category == "group" and item_id in self._group_items:
                self._select_group(item_id, force=True)
                return
            if category == "request" and item_id in self._request_items:
                self._select_request(item_id, force=True)
                return
            if category == "blocked" and item_id in self._blocked_items:
                self._select_blocked(item_id, force=True)
                return
            if not full_reload and item_id in current_map[self._current_page]:
                return
        self._clear_active_selection()

    def _select_friend(self, contact_id: str, force: bool = False) -> None:
        selected = next((item for item in self._contacts if item.id == contact_id), None)
        if not selected:
            return
        if not force and self._selected_key == ("friend", contact_id):
            return
        self._selected_key = ("friend", contact_id)
        self._clear_selection()
        self._friend_items[contact_id].set_selected(True)
        self.detail_panel.set_contact(selected)
        self._show_detail_panel()
        self._load_friend_moment_images(selected.id)

    def _select_group(self, group_id: str, force: bool = False) -> None:
        selected = next((item for item in self._groups if item.id == group_id), None)
        if not selected:
            return
        if not force and self._selected_key == ("group", group_id):
            return
        self._selected_key = ("group", group_id)
        self._cancel_friend_moment_task()
        self._clear_selection()
        self._group_items[group_id].set_selected(True)
        self.detail_panel.show_placeholder()
        self._show_welcome_panel()

    def _select_request(self, request_id: str, force: bool = False) -> None:
        selected = next((item for item in self._requests if item.id == request_id), None)
        if not selected:
            return
        if not force and self._selected_key == ("request", request_id):
            return
        self._selected_key = ("request", request_id)
        self._cancel_friend_moment_task()
        self._clear_selection()
        self._request_items[request_id].set_selected(True)
        self.detail_panel.show_placeholder()
        self._show_welcome_panel()

    def _select_blocked(self, contact_id: str, force: bool = False) -> None:
        selected = next((item for item in self._blocked_contacts if item.id == contact_id), None)
        if not selected:
            return
        if not force and self._selected_key == ("blocked", contact_id):
            return
        self._selected_key = ("blocked", contact_id)
        self._cancel_friend_moment_task()
        self._clear_selection()
        self._blocked_items[contact_id].set_selected(True)
        self.detail_panel.show_placeholder()
        self._show_welcome_panel()

    def _load_friend_moment_images(self, contact_id: str) -> None:
        self._cancel_friend_moment_task()
        normalized_contact_id = str(contact_id or "").strip()
        if not normalized_contact_id:
            self.detail_panel.set_friend_moment_images([])
            return
        self.detail_panel.set_friend_moment_images([])
        self._friend_moment_task = self._create_ui_task(
            self._load_friend_moment_images_async(normalized_contact_id),
            f"load friend moment images {normalized_contact_id}",
            on_done=self._clear_friend_moment_task,
        )

    async def _load_friend_moment_images_async(self, contact_id: str) -> None:
        moments = await self._discovery_controller.load_moments(user_id=contact_id)
        if self._destroyed or self._selected_key != ("friend", contact_id):
            return
        media: list[MomentMediaRecord] = []
        for moment in moments:
            for item in moment.media:
                if item.is_image:
                    media.append(item)
                if len(media) >= 5:
                    break
            if len(media) >= 5:
                break
        self.detail_panel.set_friend_moment_images(media)

    def _cancel_friend_moment_task(self) -> None:
        self._cancel_pending_task(self._friend_moment_task)
        self._friend_moment_task = None
        if hasattr(self, "detail_panel"):
            self.detail_panel.set_friend_moment_images([])

    def _clear_friend_moment_task(self, task: asyncio.Task) -> None:
        if self._friend_moment_task is task:
            self._friend_moment_task = None

    def _accept_request(self, request_id: str) -> None:
        request = next((item for item in self._requests if item.id == request_id), None)
        if not request or not request.can_review(self._current_user_id):
            return
        self._schedule_keyed_ui_task(
            ("accept_request", request_id),
            lambda: self._accept_request_async(request_id),
            f"accept request {request_id}",
        )

    async def _accept_request_async(self, request_id: str) -> None:
        payload = await self._controller.accept_request(request_id)
        updated_request = self._request_record_from_payload(dict(payload or {}))
        self._upsert_request_record(updated_request)
        self._upsert_contact_record(self._contact_record_from_request(updated_request), select_after_upsert=True)
        InfoBar.success(
            tr("contact.request.tab_title", "New Friends"),
            tr("contact.request.accepted", "Friend request accepted."),
            parent=self.window(),
            duration=1800,
        )

    def _reject_request(self, request_id: str) -> None:
        request = next((item for item in self._requests if item.id == request_id), None)
        if not request or not request.can_review(self._current_user_id):
            return
        self._schedule_keyed_ui_task(
            ("reject_request", request_id),
            lambda: self._reject_request_async(request_id),
            f"reject request {request_id}",
        )

    async def _reject_request_async(self, request_id: str) -> None:
        payload = await self._controller.reject_request(request_id)
        self._upsert_request_record(self._request_record_from_payload(dict(payload or {})))
        self._update_summary_counts()
        InfoBar.success(
            tr("contact.request.tab_title", "New Friends"),
            tr("contact.request.rejected", "Friend request rejected."),
            parent=self.window(),
            duration=1800,
        )

    def _show_add_placeholder(self) -> None:
        if self._current_page == "friends":
            if self._raise_existing_dialog(self._add_friend_dialog):
                return
            dialog = AddFriendDialog(
                self._controller,
                {item.id for item in self._contacts},
                self._current_user_id,
                self.window(),
            )
            dialog.friend_request_sent.connect(self._on_friend_request_sent)
            self._add_friend_dialog = dialog
            dialog.destroyed.connect(lambda *_args: setattr(self, "_add_friend_dialog", None))
            self._show_dialog(dialog)
            return

        if self._current_page == "groups":
            if not self._contacts:
                InfoBar.info(
                    tr("contact.create_group.title", "Create Group"),
                    tr("contact.sidebar.no_contacts_for_group", "There are no friends available to add."),
                    parent=self.window(),
                    duration=2000,
                )
                return
            if self._raise_existing_dialog(self._create_group_dialog):
                return
            dialog = CreateGroupDialog(self._controller, self._contacts, self.window())
            dialog.group_created.connect(self._on_group_created)
            self._create_group_dialog = dialog
            dialog.destroyed.connect(lambda *_args: setattr(self, "_create_group_dialog", None))
            self._show_dialog(dialog)
            return

        if self._current_page == "requests":
            InfoBar.info(
                tr("contact.detail.unavailable_title", "Notice"),
                tr("contact.sidebar.requests_inline_hint", "The request list is already available on this page."),
                parent=self.window(),
                duration=1800,
            )
            return

        InfoBar.info(
            tr("contact.detail.unavailable_title", "Notice"),
            tr("contact.sidebar.blocked_inline_hint", "Use the block list context menu to unblock contacts."),
            parent=self.window(),
            duration=1800,
        )

    def _show_dialog(self, dialog: QWidget) -> None:
        """Keep a dialog alive while it is visible."""
        self._dialog_refs.add(dialog)
        dialog.destroyed.connect(lambda *_args, dlg=dialog: self._dialog_refs.discard(dlg))
        if hasattr(dialog, "finished"):
            dialog.finished.connect(dialog.deleteLater)
        elif hasattr(dialog, "closed"):
            dialog.closed.connect(dialog.deleteLater)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _raise_existing_dialog(self, dialog: QWidget | None) -> bool:
        if dialog is None or not is_valid_qt_object(dialog):
            return False
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return True

    def _on_friend_request_sent(self, payload: object) -> None:
        """Refresh only the affected sidebar slices after a friend action dialog completes."""
        request_payload = dict(payload or {}) if isinstance(payload, dict) else {}
        if not request_payload:
            return
        request = self._request_record_from_payload(request_payload)
        if request.is_outgoing(self._current_user_id):
            return
        self._upsert_request_record(request)
        self._update_summary_counts()
        if request.status == "accepted":
            self._upsert_contact_record(self._contact_record_from_request(request), select_after_upsert=True)
            return
        self._activate_page("requests")
        if request.id in self._request_items:
            self._select_request(request.id, force=True)
        else:
            self._restore_selection(full_reload=False)

    def _on_group_created(self, group: object) -> None:
        """Switch to groups, merge the new group locally, and jump into the new group chat."""
        self._groups, created_group, rebuild = self._controller.merge_group_record(self._groups, group)
        if created_group is None:
            return
        self._activate_page("groups")
        self._sync_group_record_view(created_group, rebuild=rebuild)
        self._schedule_groups_cache_persist()
        if created_group.id in self._group_items:
            self._select_group(created_group.id, force=True)
        else:
            self._restore_selection(full_reload=False)
        self.message_requested.emit({"type": "group", "data": created_group})

    def _add_empty_state(self, layout: QVBoxLayout, icon: AppIcon, text: str) -> None:
        holder = QWidget(self)
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 52, 0, 0)
        holder_layout.setSpacing(10)
        icon_widget = IconWidget(icon, holder)
        icon_widget.setFixedSize(40, 40)
        label = BodyLabel(text, holder)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        holder_layout.addWidget(icon_widget, 0, Qt.AlignmentFlag.AlignCenter)
        holder_layout.addWidget(label, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(holder)
        layout.addStretch(1)

    def _clear_selection(self) -> None:
        for item in self._friend_items.values():
            item.set_selected(False)
        for item in self._blocked_items.values():
            item.set_selected(False)
        for item in self._group_items.values():
            item.set_selected(False)
        for item in self._request_items.values():
            item.set_selected(False)

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _on_destroyed(self, *_args) -> None:
        """Cancel outstanding async work when the contact page is torn down."""
        self.quiesce()

    def quiesce(self) -> None:
        """Stop contact-page tasks before logout clears account state."""
        if self._teardown_started:
            return
        self._teardown_started = True
        self._destroyed = True
        self._event_bus.unsubscribe_sync(ContactEvent.SYNC_REQUIRED, self._on_contact_sync_required)
        self._connection_manager.remove_state_listener(self._on_connection_state_changed)
        self._search_timer.stop()
        self._cancel_pending_task(self._search_task)
        self._search_task = None
        self._dismiss_search_flyout(clear_results=False)
        self._cancel_pending_task(self._load_task)
        self._load_task = None
        self._cancel_pending_task(self._friend_moment_task)
        self._friend_moment_task = None
        for task in list(self._keyed_ui_tasks.values()):
            if not task.done():
                task.cancel()
        self._keyed_ui_tasks.clear()
        for dialog in list(self._dialog_refs):
            dialog.close()
        self._dialog_refs.clear()
        self._cancel_all_ui_tasks()

    def _cancel_pending_task(self, task: Optional[asyncio.Task]) -> None:
        """Cancel one tracked task if it is still running."""
        if task is not None and not task.done():
            task.cancel()

    def _cancel_all_ui_tasks(self) -> None:
        """Cancel all background tasks launched from this page."""
        for task in list(self._ui_tasks):
            if not task.done():
                task.cancel()

    def _create_ui_task(self, coro, context: str, *, on_done=None) -> asyncio.Task:
        """Track page-owned coroutines so they can be canceled reliably."""
        task = asyncio.create_task(coro)
        self._ui_tasks.add(task)
        task.add_done_callback(lambda finished, name=context, callback=on_done: self._finalize_ui_task(finished, name, callback))
        return task

    def _finalize_ui_task(self, task: asyncio.Task, context: str, on_done=None) -> None:
        """Drop finished tasks from bookkeeping and report failures."""
        self._ui_tasks.discard(task)
        if on_done is not None:
            on_done(task)

        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            if self._destroyed and isinstance(exc, RuntimeError) and "deleted" in str(exc).lower():
                return
            logger.exception("ContactInterface task failed: %s", context)

    def _set_load_task(self, coro) -> None:
        """Replace the active contact-reload task with the newest request."""
        self._cancel_pending_task(self._load_task)
        self._load_task = self._create_ui_task(coro, "reload contact data", on_done=self._clear_load_task)

    def _set_search_task(self, coro) -> None:
        """Keep only the latest grouped-search refresh alive."""
        self._cancel_pending_task(self._search_task)
        self._search_task = self._create_ui_task(coro, "search contacts sidebar", on_done=self._clear_search_task)

    def _clear_search_task(self, task: asyncio.Task) -> None:
        """Clear the tracked grouped-search task when it finishes."""
        if self._search_task is task:
            self._search_task = None

    def _clear_load_task(self, task: asyncio.Task) -> None:
        """Clear the active reload task reference when it finishes."""
        if self._load_task is task:
            self._load_task = None

    def _schedule_keyed_ui_task(self, key: tuple[str, str], coro_factory, context: str) -> None:
        """Prevent duplicate actions for the same target while one is still running."""
        existing = self._keyed_ui_tasks.get(key)
        if existing is not None and not existing.done():
            return
        self._keyed_ui_tasks[key] = self._create_ui_task(
            coro_factory(),
            context,
            on_done=lambda task, task_key=key: self._clear_keyed_ui_task(task_key, task),
        )

    def _clear_keyed_ui_task(self, key: tuple[str, str], task: asyncio.Task) -> None:
        """Clear a keyed action slot once its task finishes."""
        if self._keyed_ui_tasks.get(key) is task:
            self._keyed_ui_tasks.pop(key, None)










