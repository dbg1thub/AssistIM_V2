"""Contact interface built with qfluentwidgets."""

from __future__ import annotations

import asyncio
from typing import Optional

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPixmap
from PySide6.QtWidgets import QLabel, QDialog, QFrame, QHBoxLayout, QSizePolicy, QSplitter, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentWidget,
    FluentStyleSheet,
    FlowLayout,
    IconWidget,
    InfoBar,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SearchLineEdit,
    SegmentedWidget,
    SubtitleLabel,
    ToolButton,
    TitleLabel,
    isDarkTheme,
)
from qframelesswindow.titlebar import CloseButton
from shiboken6 import isValid as is_valid_qt_object

from client.core.app_icons import AppIcon
from client.core import logging
from client.core.avatar_utils import profile_avatar_seed
from client.core.exceptions import APIError, NetworkError
from client.core.i18n import format_relative_time, tr
from client.core.profile_fields import format_profile_birthday, localize_profile_gender, localize_profile_status
from client.core.logging import setup_logging
from client.events.contact_events import ContactEvent
from client.events.event_bus import get_event_bus
from client.managers.search_manager import search_all
from client.ui.controllers.contact_controller import (
    ContactRecord,
    FriendRequestRecord,
    GroupRecord,
    UserSearchRecord,
    get_contact_controller,
)

from client.ui.controllers.discovery_controller import MomentRecord, get_discovery_controller
from client.ui.windows.discovery_interface import MomentCard
from client.ui.styles import StyleSheet
from client.ui.widgets.chat_info_drawer import AcrylicDrawerSurface
from client.ui.widgets.global_search_panel import GlobalSearchPopupOverlay
from client.ui.widgets.fluent_divider import FluentDivider
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
    apply_themed_dialog_surface as _apply_themed_dialog_surface,
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

class ContactListItem(QWidget):
    clicked = Signal(str)

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
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.subtitle_label)
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

        self.action_layout = QVBoxLayout()
        self.action_layout.setContentsMargins(0, 0, 0, 0)
        self.action_layout.setSpacing(8)
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
        self.action_layout.addStretch(1)
        if self.request.can_review(self.current_user_id):
            accept_button = PrimaryPushButton(tr("common.accept", "Accept"), self)
            reject_button = PushButton(tr("common.reject", "Reject"), self)
            accept_button.setFixedWidth(76)
            reject_button.setFixedWidth(76)
            accept_button.clicked.connect(lambda: self.accept_clicked.emit(self.request.id))
            reject_button.clicked.connect(lambda: self.reject_clicked.emit(self.request.id))
            self.action_layout.addWidget(accept_button, 0, Qt.AlignmentFlag.AlignHCenter)
            self.action_layout.addWidget(reject_button, 0, Qt.AlignmentFlag.AlignHCenter)
        else:
            status_button = PushButton(self._status_text(), self)
            status_button.setObjectName("requestStatusButton")
            status_button.setFixedWidth(88)
            status_button.setEnabled(False)
            self.action_layout.addWidget(status_button, 0, Qt.AlignmentFlag.AlignHCenter)
        self.action_layout.addStretch(1)

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


class DetailRow(QWidget):
    def __init__(self, label: str, value: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(4)
        layout.addWidget(CaptionLabel(label, self))
        value_label = BodyLabel(value, self)
        value_label.setWordWrap(True)
        layout.addWidget(value_label)
        divider = QFrame(self)
        divider.setObjectName("DetailDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Plain)
        layout.addWidget(divider)


class ContactMomentItem(CardWidget):
    def __init__(self, moment: MomentRecord, parent=None):
        super().__init__(parent)
        self.setObjectName("ContactMomentItem")
        self.setMinimumWidth(320)
        self.setMaximumWidth(380)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        avatar = ContactAvatar(36, self)
        avatar.set_avatar(
            moment.avatar,
            moment.display_name,
            gender=getattr(moment, "gender", ""),
            seed=profile_avatar_seed(user_id=moment.user_id, username=getattr(moment, "username", ""), display_name=moment.display_name),
        )
        header_text = QVBoxLayout()
        header_text.setContentsMargins(0, 0, 0, 0)
        header_text.setSpacing(2)
        header_text.addWidget(BodyLabel(moment.display_name, self))
        header_text.addWidget(CaptionLabel(format_relative_time(moment.created_at), self))
        header.addWidget(avatar, 0)
        header.addLayout(header_text, 1)
        layout.addLayout(header)

        content_label = BodyLabel(moment.content or "", self)
        content_label.setWordWrap(True)
        layout.addWidget(content_label)

        meta = CaptionLabel(
            tr(
                "contact.moment.meta",
                "{likes} likes · {comments} comments",
                likes=moment.like_count,
                comments=moment.comment_count,
            ),
            self,
        )
        meta.setObjectName("contactMomentMetaLabel")
        layout.addWidget(meta)

        comments = list(moment.comments or [])[:2]
        if comments:
            comment_box = QWidget(self)
            comment_box.setObjectName("contactMomentCommentBox")
            comment_layout = QVBoxLayout(comment_box)
            comment_layout.setContentsMargins(12, 10, 12, 10)
            comment_layout.setSpacing(6)
            for comment in comments:
                label = CaptionLabel(f"{comment.display_name}: {comment.content}", comment_box)
                label.setObjectName("contactMomentCommentLabel")
                label.setWordWrap(True)
                comment_layout.addWidget(label)
            layout.addWidget(comment_box)


class ContactMomentsPanel(CardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ContactMomentsPanel")
        self._moments: list[MomentRecord] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        self.title_label = SubtitleLabel(tr("contact.moments.title", "Moments"), self)
        self.subtitle_label = CaptionLabel(
            tr("contact.moments.subtitle", "Browse this contact's latest updates"),
            self,
        )
        self.subtitle_label.setObjectName("contactSectionCaption")
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)

        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.container = QWidget(self.scroll_area)
        self.container.setObjectName("contactMomentsScrollWidget")
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(10)
        self.container_layout.addStretch(1)
        self.scroll_area.setWidget(self.container)
        layout.addWidget(self.scroll_area, 1)

        self.show_placeholder()

    def show_placeholder(self) -> None:
        self.set_moments([])

    def set_moments(self, moments: list[MomentRecord]) -> None:
        self._moments = list(moments)
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self._moments:
            self.container_layout.addWidget(
                BodyLabel(tr("contact.moments.contact_empty", "This contact has no moments yet."), self.container)
            )
            self.container_layout.addStretch(1)
            return
        for moment in self._moments:
            self.container_layout.addWidget(ContactMomentItem(moment, self.container))
        self.container_layout.addStretch(1)


class ContactDetailPanel(QWidget):
    message_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entity: Optional[dict[str, object]] = None
        self.setObjectName("ContactDetailPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(12)

        self.profile_card = CardWidget(self)
        self.profile_card.setObjectName("ContactProfileCard")
        self.profile_card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.profile_card.setMinimumWidth(340)
        self.profile_card.setMaximumWidth(420)
        layout = QVBoxLayout(self.profile_card)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(20)

        header = QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar = ContactAvatar(84, self.profile_card)
        self.title_label = TitleLabel(tr("contact.detail.title", "Contact Details"), self.profile_card)
        self.subtitle_label = CaptionLabel(
            tr("contact.detail.placeholder_short", "Select a contact, group, or request from the left to view details."),
            self.profile_card,
        )
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.subtitle_label, 0, Qt.AlignmentFlag.AlignCenter)

        self.info_container = QWidget(self.profile_card)
        self.info_layout = QVBoxLayout(self.info_container)
        self.info_layout.setContentsMargins(0, 0, 0, 0)
        self.info_layout.setSpacing(0)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 8, 0, 0)
        action_row.setSpacing(12)
        self.message_button = PrimaryPushButton(tr("contact.detail.action.message", "Message"), self.profile_card)
        self.voice_button = PushButton(tr("contact.detail.action.voice_call", "Voice Call"), self.profile_card)
        self.video_button = PushButton(tr("contact.detail.action.video_call", "Video Call"), self.profile_card)
        action_row.addWidget(self.message_button)
        action_row.addWidget(self.voice_button)
        action_row.addWidget(self.video_button)
        action_row.addStretch(1)

        self.message_button.clicked.connect(self._emit_message_request)
        self.voice_button.clicked.connect(self._show_unavailable)
        self.video_button.clicked.connect(self._show_unavailable)

        layout.addLayout(header)
        layout.addWidget(self.info_container, 1)
        layout.addLayout(action_row)

        self.moments_panel = ContactMomentsPanel(self)
        self.moments_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root_layout.addWidget(self.profile_card, 0)
        root_layout.addWidget(self.moments_panel, 1)
        self.show_placeholder()

    def show_placeholder(self) -> None:
        self._entity = None
        self.avatar.set_avatar(fallback="CT")
        self.title_label.setText(tr("contact.detail.title", "Contact Details"))
        self.subtitle_label.setText(
            tr(
                "contact.detail.placeholder",
                "Select a contact, group, or friend request from the left to view details.",
            )
        )
        self._set_rows([])
        self.message_button.setEnabled(False)
        self.voice_button.setEnabled(False)
        self.video_button.setEnabled(False)
        self.moments_panel.show_placeholder()

    def set_contact(self, contact: ContactRecord, moments: Optional[list[MomentRecord]] = None) -> None:
        self._entity = {"type": "friend", "data": contact}
        self.avatar.set_avatar(
            contact.avatar,
            contact.display_name,
            gender=contact.gender,
            seed=profile_avatar_seed(user_id=contact.id, username=contact.username, display_name=contact.display_name),
        )
        self.title_label.setText(contact.display_name)
        self.subtitle_label.setText(contact.username or contact.assistim_id or tr("contact.detail.friend_fallback", "Friend"))
        birthday_text = format_profile_birthday(contact.birthday)
        gender_text = localize_profile_gender(contact.gender)
        status_text = localize_profile_status(contact.status)
        self._set_rows([
            (tr("contact.detail.label.assistim_id", "AssistIM ID"), contact.assistim_id or contact.username or "-"),
            (tr("contact.detail.label.nickname", "Nickname"), contact.nickname or "-"),
            (tr("contact.detail.label.remark", "Remark"), contact.remark or "-"),
            (tr("contact.detail.label.region", "Region"), contact.region or "-"),
            (tr("contact.detail.label.signature", "Signature"), contact.signature or "-"),
            (tr("contact.detail.label.email", "Email"), contact.email or "-"),
            (tr("contact.detail.label.phone", "Phone"), contact.phone or "-"),
            (tr("contact.detail.label.birthday", "Birthday"), birthday_text or "-"),
            (tr("contact.detail.label.gender", "Gender"), gender_text or "-"),
            (tr("contact.detail.label.status", "Status"), status_text or "-"),
        ])
        self.message_button.setEnabled(True)
        self.voice_button.setEnabled(True)
        self.video_button.setEnabled(True)
        self.moments_panel.set_moments(moments or [])

    def set_group(self, group: GroupRecord, moments: Optional[list[MomentRecord]] = None) -> None:
        self._entity = {"type": "group", "data": group}
        self.avatar.set_avatar(group.avatar, fallback=group.name)
        self.title_label.setText(group.name)
        self.subtitle_label.setText(tr("contact.detail.group", "Group"))
        self._set_rows([
            (tr("contact.detail.label.group_id", "Group ID"), group.id or "-"),
            (tr("contact.detail.label.session_id", "Session ID"), group.session_id or "-"),
            (tr("contact.detail.label.member_count", "Members"), str(group.member_count)),
            (tr("contact.detail.label.created_at", "Created At"), group.created_at or "-"),
        ])
        self.message_button.setEnabled(True)
        self.voice_button.setEnabled(False)
        self.video_button.setEnabled(False)
        self.moments_panel.set_moments(moments or [])

    def set_request(self, request: FriendRequestRecord, current_user_id: str = "", moments: Optional[list[MomentRecord]] = None) -> None:
        self._entity = None
        counterpart_name = request.counterpart_name(current_user_id)
        self.avatar.set_avatar(fallback=counterpart_name)
        self.title_label.setText(_request_title_text(request, current_user_id))
        self.subtitle_label.setText(counterpart_name)
        self._set_rows([
            (tr("contact.detail.label.sender_id", "Sender ID"), request.sender_id or "-"),
            (tr("contact.detail.label.receiver_id", "Receiver ID"), request.receiver_id or "-"),
            (tr("contact.detail.label.request_status", "Request Status"), _request_status_text(request.status)),
            (
                tr("contact.detail.label.request_message", "Request Message"),
                request.message or tr("contact.request.no_message", "No verification message was provided."),
            ),
            (tr("contact.detail.label.time", "Time"), request.created_at or "-"),
        ])
        self.message_button.setEnabled(False)
        self.voice_button.setEnabled(False)
        self.video_button.setEnabled(False)
        self.moments_panel.set_moments(moments or [])

    def _set_rows(self, rows: list[tuple[str, str]]) -> None:
        while self.info_layout.count():
            item = self.info_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        for label, value in rows:
            self.info_layout.addWidget(DetailRow(label, value, self.info_container))
        self.info_layout.addStretch(1)

    def _emit_message_request(self) -> None:
        if self._entity:
            self.message_requested.emit(self._entity)

    def _show_unavailable(self) -> None:
        InfoBar.info(
            tr("contact.detail.unavailable_title", "Notice"),
            tr("contact.detail.unavailable_content", "Voice and video entries are UI placeholders for now."),
            parent=self.window(),
            duration=1800,
        )


class ContactMomentsFlowPanel(QWidget):
    like_requested = Signal(str, bool, int)
    comment_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ContactMomentsSection")
        self._cards: dict[str, MomentCard] = {}
        self._featured_widget: Optional[QWidget] = None
        self._moments: list[MomentRecord] = []
        self._empty_text = tr("contact.moments.empty", "No moments available")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.section_title = SubtitleLabel(tr("contact.moments.title", "Moments"), self)
        self.section_caption = CaptionLabel(
            tr("contact.moments.flow_subtitle", "Scroll through the latest updates"),
            self,
        )
        self.section_caption.setObjectName("contactSectionCaption")
        self.section_title.hide()
        self.section_caption.hide()

        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.scroll_widget = QWidget(self.scroll_area)
        self.scroll_widget.setObjectName("contactDetailScrollWidget")
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setContentsMargins(12, 8, 12, 16)
        self.scroll_layout.setSpacing(18)

        self.placeholder_label = BodyLabel(tr("contact.moments.empty", "No moments available"), self.scroll_widget)
        self.placeholder_label.setObjectName("contactMomentsPlaceholder")
        self.placeholder_label.setWordWrap(True)

        self.flow_host = QWidget(self.scroll_widget)
        self.flow_host.setObjectName("contactMomentFlowWidget")
        self.flow_layout = FlowLayout(self.flow_host, needAni=True)
        self.flow_layout.setContentsMargins(0, 2, 0, 2)
        self.flow_layout.setHorizontalSpacing(18)
        self.flow_layout.setVerticalSpacing(18)

        self.scroll_layout.addWidget(self.placeholder_label)
        self.scroll_layout.addWidget(self.flow_host)
        self.scroll_layout.addStretch(1)
        self.scroll_area.setWidget(self.scroll_widget)

        layout.addWidget(self.section_title)
        layout.addWidget(self.section_caption)
        layout.addWidget(self.scroll_area, 1)

        self.set_section(
            tr("contact.moments.title", "Moments"),
            tr("contact.moments.flow_subtitle", "Scroll through the latest updates"),
        )
        self.show_placeholder()

    def set_section(self, title: str, subtitle: str) -> None:
        self.section_title.setText(title)
        self.section_caption.setText(subtitle)

    def show_placeholder(self, text: str | None = None) -> None:
        self._moments = []
        self._empty_text = text or tr("contact.moments.empty", "No moments available")
        self._rebuild_flow()

    def set_moments(self, moments: list[MomentRecord], empty_text: str | None = None) -> None:
        self._moments = list(moments)
        self._empty_text = empty_text or tr("contact.moments.empty", "No moments available")
        self._rebuild_flow()

    def set_featured_widget(self, widget: QWidget | None) -> None:
        self._featured_widget = widget
        if widget is not None and widget.parent() is not self.flow_host:
            widget.setParent(self.flow_host)
        self._rebuild_flow()

    def _rebuild_flow(self) -> None:
        self._clear_flow_widgets()
        self._cards.clear()

        if self._featured_widget is not None:
            if self._featured_widget.parent() is not self.flow_host:
                self._featured_widget.setParent(self.flow_host)
            self._featured_widget.show()
            self.flow_layout.addWidget(self._featured_widget)

        if not self._moments:
            self.placeholder_label.setText(self._empty_text)
            self.placeholder_label.show()
            self.flow_host.setVisible(self._featured_widget is not None)
            return

        self.placeholder_label.hide()
        self.flow_host.show()
        for moment in self._moments:
            card = MomentCard(moment, self.flow_host)
            card.setMinimumWidth(320)
            card.setMaximumWidth(380)
            card.like_requested.connect(self.like_requested.emit)
            card.comment_requested.connect(self.comment_requested.emit)
            self.flow_layout.addWidget(card)
            self._cards[moment.id] = card

    def _clear_flow_widgets(self) -> None:
        while self.flow_layout.count():
            widget = self.flow_layout.takeAt(0)
            if widget is None:
                continue
            if widget is self._featured_widget:
                widget.hide()
                continue
            widget.deleteLater()

    def set_like_state(self, moment_id: str, liked: bool, like_count: int) -> None:
        card = self._cards.get(moment_id)
        if card is not None:
            card.set_like_state(liked, like_count)

    def append_comment(self, moment_id: str, comment) -> None:
        card = self._cards.get(moment_id)
        if card is not None:
            card.append_comment(comment)


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


class GalleryContactDetailPanel(QWidget):
    message_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entity: Optional[dict[str, object]] = None
        self.setObjectName("ContactDetailPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.header = CardWidget(self)
        self.header.setObjectName("ContactDetailHeader")
        self.header.setBorderRadius(8)
        self.header.setMinimumWidth(420)
        self.header.setMaximumWidth(460)
        self.header.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        header_layout = QVBoxLayout(self.header)
        header_layout.setContentsMargins(30, 28, 30, 24)
        header_layout.setSpacing(16)

        self.avatar = ContactAvatar(88, self.header)

        self.title_label = TitleLabel(tr("contact.detail.title", "Contact Details"), self.header)
        self.subtitle_label = CaptionLabel("", self.header)
        self.subtitle_label.setObjectName("contactMetaLabel")
        self.meta_primary_label = CaptionLabel("", self.header)
        self.meta_primary_label.setObjectName("contactMetaLabel")
        self.meta_primary_label.setWordWrap(True)
        self.meta_secondary_label = CaptionLabel("", self.header)
        self.meta_secondary_label.setObjectName("contactMetaLabel")
        self.meta_secondary_label.hide()

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(10)
        self.message_button = PrimaryPushButton(tr("contact.detail.action.message", "Message"), self.header)
        self.voice_button = PushButton(tr("contact.detail.action.voice_call", "Voice Call"), self.header)
        self.video_button = PushButton(tr("contact.detail.action.video_call", "Video Call"), self.header)
        for button in (self.message_button, self.voice_button, self.video_button):
            button.setFixedWidth(112)
            button.setMinimumHeight(36)
        action_row.addWidget(self.message_button)
        action_row.addWidget(self.voice_button)
        action_row.addWidget(self.video_button)
        action_row.addStretch(1)

        header_layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignLeft)
        header_layout.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignLeft)
        header_layout.addWidget(self.subtitle_label, 0, Qt.AlignmentFlag.AlignLeft)
        header_layout.addWidget(self.meta_primary_label, 0, Qt.AlignmentFlag.AlignLeft)
        header_layout.addLayout(action_row, 0)
        header_layout.addStretch(1)

        self.message_button.clicked.connect(self._emit_message_request)
        self.voice_button.clicked.connect(self._show_unavailable)
        self.video_button.clicked.connect(self._show_unavailable)

        self.moments_panel = ContactMomentsFlowPanel(self)

        root_layout.addWidget(self.header, 0, Qt.AlignmentFlag.AlignTop)
        root_layout.addWidget(self.moments_panel, 1)
        self.show_placeholder()

    def show_placeholder(self) -> None:
        self._entity = None
        self.avatar.set_avatar(fallback="CT")
        self.title_label.setText(tr("contact.detail.title", "Contact Details"))
        self.subtitle_label.clear()
        self.meta_primary_label.clear()
        self.message_button.setEnabled(False)
        self.voice_button.setEnabled(False)
        self.video_button.setEnabled(False)
        self.moments_panel.show_placeholder(tr("contact.moments.detail_empty", "There is nothing to display right now."))

    def set_contact(self, contact: ContactRecord, moments: Optional[list[MomentRecord]] = None) -> None:
        self._entity = {"type": "friend", "data": contact}
        self.avatar.set_avatar(
            contact.avatar,
            contact.display_name,
            gender=contact.gender,
            seed=profile_avatar_seed(user_id=contact.id, username=contact.username, display_name=contact.display_name),
        )
        self.title_label.setText(contact.display_name)
        self.subtitle_label.setText(
            f"{tr('contact.detail.label.assistim_id', 'AssistIM ID')} {contact.assistim_id or contact.username or '-'}"
        )
        self.meta_primary_label.setText(
            " │ ".join(
                filter(
                    None,
                    [
                        f"{tr('contact.detail.label.nickname', 'Nickname')}：{contact.nickname}" if contact.nickname else "",
                        f"{tr('contact.detail.label.remark', 'Remark')}：{contact.remark}" if contact.remark else "",
                        f"{tr('contact.detail.label.region', 'Region')}：{contact.region}" if contact.region else "",
                        f"{tr('contact.detail.label.signature', 'Signature')}：{contact.signature}" if contact.signature else "",
                        f"{tr('contact.detail.label.email', 'Email')}：{contact.email}" if contact.email else "",
                        f"{tr('contact.detail.label.phone', 'Phone')}：{contact.phone}" if contact.phone else "",
                        f"{tr('contact.detail.label.birthday', 'Birthday')}：{format_profile_birthday(contact.birthday)}" if format_profile_birthday(contact.birthday) else "",
                        f"{tr('contact.detail.label.gender', 'Gender')}：{localize_profile_gender(contact.gender)}" if localize_profile_gender(contact.gender) else "",
                        f"{tr('contact.detail.label.status', 'Status')}：{localize_profile_status(contact.status)}" if localize_profile_status(contact.status) else "",
                    ],
                )
            )
            or tr("contact.relationship.established", "Friend relationship established")
        )
        self.message_button.setEnabled(True)
        self.voice_button.setEnabled(True)
        self.video_button.setEnabled(True)
        self.moments_panel.set_moments(
            moments or [],
            tr("contact.moments.contact_empty", "This contact has no moments yet."),
        )

    def set_group(self, group: GroupRecord, moments: Optional[list[MomentRecord]] = None) -> None:
        self._entity = {"type": "group", "data": group}
        self.avatar.set_avatar(group.avatar, fallback=group.name)
        self.title_label.setText(group.name)
        self.subtitle_label.setText(f"{tr('contact.detail.label.group_id', 'Group ID')} {group.id or '-'}")
        self.meta_primary_label.setText(
            " │ ".join(
                filter(
                    None,
                    [
                        tr("contact.group.member_summary", "{count} members", count=group.member_count),
                        f"{tr('contact.detail.label.session_id', 'Session ID')}：{group.session_id}" if group.session_id else "",
                        f"{tr('contact.detail.label.created_at', 'Created At')}：{group.created_at}" if group.created_at else "",
                    ],
                )
            )
        )
        self.message_button.setEnabled(True)
        self.voice_button.setEnabled(False)
        self.video_button.setEnabled(False)
        self.moments_panel.set_moments(
            moments or [],
            tr("contact.moments.group_empty", "There are no group moments to display yet."),
        )

    def set_request(self, request: FriendRequestRecord, current_user_id: str = "", moments: Optional[list[MomentRecord]] = None) -> None:
        self._entity = None
        counterpart_name = request.counterpart_name(current_user_id)
        self.avatar.set_avatar(fallback=counterpart_name)
        self.title_label.setText(_request_title_text(request, current_user_id))
        self.subtitle_label.setText(f"{tr('contact.detail.label.assistim_id', 'AssistIM ID')} {counterpart_name}")
        self.meta_primary_label.setText(
            " │ ".join(
                filter(
                    None,
                    [
                        f"{tr('contact.detail.label.request_status', 'Request Status')}：{_request_status_text(request.status)}",
                        f"{tr('contact.detail.label.time', 'Time')}：{request.created_at}" if request.created_at else "",
                        request.message or "",
                    ],
                )
            )
        )
        self.message_button.setEnabled(False)
        self.voice_button.setEnabled(False)
        self.video_button.setEnabled(False)
        self.moments_panel.set_moments(
            moments or [],
            tr("contact.moments.contact_empty", "This contact has no moments yet."),
        )

    def _emit_message_request(self) -> None:
        if self._entity:
            self.message_requested.emit(self._entity)

    def _show_unavailable(self) -> None:
        InfoBar.info(
            tr("contact.detail.unavailable_title", "Notice"),
            tr("contact.detail.unavailable_content", "Voice and video entries are UI placeholders for now."),
            parent=self.window(),
            duration=1800,
        )


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


class AddFriendDialog(FluentWidget):
    friend_request_sent = Signal(object)

    def __init__(self, controller, existing_ids: set[str], current_user_id: str = "", parent=None):
        super().__init__(parent=parent)
        self._controller = controller
        self._current_user_id = str(current_user_id or "")
        self._existing_ids = set(existing_ids)
        self._search_task: Optional[asyncio.Task] = None
        self._action_task: Optional[asyncio.Task] = None
        self._ui_tasks: set[asyncio.Task] = set()
        self._close_cleanup_done = False

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("")
        self.setObjectName("AddFriendDialog")
        self.resize(560, 680)
        self.setFixedSize(560, 680)
        if hasattr(self, "titleBar") and hasattr(self.titleBar, "titleLabel"):
            self.titleBar.titleLabel.hide()

        self._setup_ui()
        self.destroyed.connect(self._on_destroyed)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 56, 24, 24)
        layout.setSpacing(16)

        layout.addWidget(TitleLabel(tr("contact.add_friend.title", "Add Friend"), self))
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
        self._run_close_cleanup()
        super().closeEvent(event)

    def _trigger_search(self) -> None:
        keyword = self.search_edit.text().strip()
        if not keyword:
            self.summary_label.setText(tr("contact.add_friend.summary_empty_keyword", "Please enter a search keyword."))
            return

        if self._search_task and not self._search_task.done():
            self._search_task.cancel()
        self._set_search_task(self._search_async(keyword))

    async def _search_async(self, keyword: str) -> None:
        self.summary_label.setText(tr("contact.add_friend.summary_searching", "Searching users..."))
        try:
            users = await self._controller.search_users(keyword)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.summary_label.setText(tr("contact.add_friend.summary_failed", "Search failed."))
            InfoBar.error(tr("contact.add_friend.title", "Add Friend"), str(exc), parent=self, duration=2200)
            return

        filtered = [user for user in users if user.id and user.id != self._current_user_id]
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
            reason = tr("contact.user_search.already_friend", "Already Friends") if user.id in self._existing_ids else ""
            item = UserSearchItem(user, reason, self.result_container)
            if not reason:
                item.add_clicked.connect(self._send_friend_request)
            self.result_layout.addWidget(item)
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
        except Exception as exc:
            InfoBar.error(tr("contact.add_friend.title", "Add Friend"), str(exc), parent=self, duration=2200)
            return

        status = str((payload or {}).get("status", "pending") or "pending")
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

    def _on_finished(self, _result: int) -> None:
        """Stop outstanding work after the dialog closes."""
        self._cancel_pending_task(self._search_task)
        self._search_task = None
        self._cancel_pending_task(self._action_task)
        self._action_task = None
        self._cancel_all_ui_tasks()

    def _on_destroyed(self, *_args) -> None:
        """Mirror close cleanup when the dialog is destroyed by its parent."""
        self._run_close_cleanup()

    def _run_close_cleanup(self) -> None:
        """Run dialog cleanup only once across close and destroy paths."""
        if self._close_cleanup_done:
            return
        self._close_cleanup_done = True
        self._on_finished(0)

    def _cancel_pending_task(self, task: Optional[asyncio.Task]) -> None:
        """Cancel a tracked task if it is still running."""
        if task is not None and not task.done():
            task.cancel()

    def _cancel_all_ui_tasks(self) -> None:
        """Cancel every task launched from this dialog."""
        for task in list(self._ui_tasks):
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ContactInterface")
        self._controller = get_contact_controller()
        self._discovery_controller = get_discovery_controller()
        self._contacts: list[ContactRecord] = []
        self._groups: list[GroupRecord] = []
        self._requests: list[FriendRequestRecord] = []
        self._moments: list[MomentRecord] = []
        self._friend_items: dict[str, ContactListItem] = {}
        self._group_items: dict[str, ContactListItem] = {}
        self._request_items: dict[str, RequestListItem] = {}
        self._current_page = "friends"
        self._selected_key: tuple[str, str] | None = None
        self._load_task: Optional[asyncio.Task] = None
        self._moment_load_task: Optional[asyncio.Task] = None
        self._search_task: Optional[asyncio.Task] = None
        self._search_flyout = None
        self._search_flyout_view: Optional[GlobalSearchPopupOverlay] = None
        self._pending_search_keyword = ''
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)
        self._search_timer.timeout.connect(self._trigger_global_search)
        self._keyed_ui_tasks: dict[tuple[str, str], asyncio.Task] = {}
        self._ui_tasks: set[asyncio.Task] = set()
        self._dialog_refs: set[QWidget] = set()
        self._current_user_id = ""
        self._initial_load_done = False
        self._destroyed = False
        self._event_bus = get_event_bus()
        self._friend_section_headers: dict[str, QWidget] = {}
        self._friend_section_widgets: dict[str, QWidget] = {}
        self._friend_section_layouts: dict[str, QVBoxLayout] = {}
        self._friend_item_sections: dict[str, str] = {}
        self._setup_ui()
        self._connect_signals()
        self.destroyed.connect(self._on_destroyed)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._initial_load_done:
            return
        self._initial_load_done = True
        logger.info("Contact interface first show; scheduling initial reload")
        QTimer.singleShot(80, self.reload_data)

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

        self.summary_label = CaptionLabel(tr("contact.sidebar.loading", "Loading contacts..."), sidebar)
        self.summary_label.setObjectName("contactSummaryLabel")
        self.summary_label.hide()

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
        self.segmented.setMinimumHeight(36)

        self.page_stack = QStackedWidget(sidebar)
        self.friends_page, self.friends_container, self.friends_layout = self._create_scroll_page()
        self.groups_page, self.groups_container, self.groups_layout = self._create_scroll_page()
        self.requests_page, self.requests_container, self.requests_layout = self._create_scroll_page()
        self.page_stack.addWidget(self.friends_page)
        self.page_stack.addWidget(self.groups_page)
        self.page_stack.addWidget(self.requests_page)

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
        self._event_bus.subscribe_sync(ContactEvent.SYNC_REQUIRED, self._on_contact_sync_required)
        self.detail_panel.moments_panel.like_requested.connect(self._request_detail_like_toggle)
        self.detail_panel.moments_panel.comment_requested.connect(self._request_detail_comment_create)

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
        self.page_stack.setCurrentIndex({"friends": 0, "groups": 1, "requests": 2}[key])

    def _switch_page(self, key: str) -> None:
        self._activate_page(key)
        self._rebuild_current_page()

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
            return
        if reason == "group_profile_update":
            self._apply_group_update_payload(dict(event_payload.get("payload") or {}))
            return
        if reason == "group_self_profile_update":
            self._apply_group_self_profile_update_payload(dict(event_payload.get("payload") or {}))
            return
        self.reload_data()

    def _can_update_contact_ui(self) -> bool:
        """Return whether sidebar/detail widgets are still safe to touch."""
        if self._destroyed or not is_valid_qt_object(self):
            return False
        summary_label = getattr(self, "summary_label", None)
        return summary_label is not None and is_valid_qt_object(summary_label)

    def refresh_groups_after_profile_change(self) -> None:
        """Refresh only the group slice after the current user changes their profile."""
        if self._destroyed or not self._can_update_contact_ui():
            return
        self._schedule_keyed_ui_task(
            ("refresh_groups_after_profile_change", self._current_user_id or "self"),
            self._refresh_groups_only(),
            "refresh groups after profile change",
        )

    async def _refresh_groups_only(self) -> None:
        self._groups = await self._controller.load_groups()
        if self._destroyed:
            return
        self._update_summary_counts()
        self._build_groups_page()
        if self._current_page == "groups":
            self._restore_selection(full_reload=False)

    def _current_detail_moments(self) -> list[MomentRecord]:
        moments_panel = getattr(self.detail_panel, "moments_panel", None)
        if moments_panel is None:
            return []
        return list(getattr(moments_panel, "_moments", []) or [])

    def _update_friend_item_view(self, contact: ContactRecord) -> None:
        item = self._friend_items.get(contact.id)
        if item is None:
            return
        item.update_content(
            title=contact.display_name,
            subtitle=self._friend_assistim_line(contact),
            avatar=contact.avatar,
            gender=contact.gender,
            seed_user_id=contact.id,
            seed_username=contact.username,
        )

    def _create_friend_item(self, contact: ContactRecord) -> ContactListItem:
        item = ContactListItem(
            contact.id,
            contact.display_name,
            self._friend_assistim_line(contact),
            "",
            contact.avatar,
            left_padding=CONTACT_SECTION_INSET,
        )
        item.clicked.connect(self._select_friend)
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
        if item is not None:
            item.deleteLater()
        if not letter:
            return
        section_layout = self._friend_section_layouts.get(letter)
        if section_layout is None or section_layout.count() > 1:
            if section_layout is None:
                return
            remaining_items = [widget_id for widget_id, widget_letter in self._friend_item_sections.items() if widget_letter == letter]
            if remaining_items:
                return
        section = self._friend_section_widgets.pop(letter, None)
        self._friend_section_headers.pop(letter, None)
        self._friend_section_layouts.pop(letter, None)
        if section is not None:
            section.deleteLater()
        if not self._friend_items:
            self._add_empty_state(
                self.friends_layout,
                AppIcon.PEOPLE,
                tr("contact.sidebar.empty_friends", "No friends yet"),
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
        incoming = [item for item in self._requests if item.is_incoming(self._current_user_id)]
        outgoing = [item for item in self._requests if item.is_outgoing(self._current_user_id)]
        unknown = [item for item in self._requests if not item.is_incoming(self._current_user_id) and not item.is_outgoing(self._current_user_id)]
        return incoming + outgoing + unknown

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
        ordered_ids = [item.id for item in self._ordered_requests()]
        insert_at = ordered_ids.index(request.id)
        item = self._create_request_item(request)
        self.requests_layout.insertWidget(insert_at, item)
        self._request_items[request.id] = item

    @staticmethod
    def _request_record_from_payload(payload: dict[str, object]) -> FriendRequestRecord:
        from_user = dict(payload.get("from_user") or {}) if isinstance(payload.get("from_user"), dict) else {}
        to_user = dict(payload.get("to_user") or {}) if isinstance(payload.get("to_user"), dict) else {}
        return FriendRequestRecord(
            id=str(payload.get("request_id", "") or payload.get("id", "") or ""),
            sender_id=str(payload.get("sender_id", "") or from_user.get("id", "") or ""),
            receiver_id=str(payload.get("receiver_id", "") or to_user.get("id", "") or ""),
            message=str(payload.get("message", "") or ""),
            status=str(payload.get("status", "pending") or "pending"),
            created_at=str(payload.get("created_at", "") or ""),
            sender_name=str(from_user.get("nickname", "") or from_user.get("username", "") or payload.get("sender_name", "") or ""),
            receiver_name=str(to_user.get("nickname", "") or to_user.get("username", "") or payload.get("receiver_name", "") or ""),
            sender_avatar=str(from_user.get("avatar", "") or payload.get("sender_avatar", "") or ""),
            receiver_avatar=str(to_user.get("avatar", "") or payload.get("receiver_avatar", "") or ""),
            sender_gender=str(from_user.get("gender", "") or payload.get("sender_gender", "") or ""),
            receiver_gender=str(to_user.get("gender", "") or payload.get("receiver_gender", "") or ""),
        )

    def _upsert_request_record(self, request: FriendRequestRecord) -> None:
        for index, existing in enumerate(list(self._requests)):
            if existing.id != request.id:
                continue
            self._requests[index] = request
            self._update_request_item_view(request)
            if self._selected_key == ("request", request.id):
                self.detail_panel.set_request(request, self._current_user_id, self._current_detail_moments())
            return
        self._requests.insert(0, request)
        if self._request_items or self._current_page == "requests":
            self._insert_request_item_view(request)
            if self._current_page == "requests" and request.id in self._request_items:
                self._select_request(request.id, force=True)

    def _contact_record_from_request(self, request: FriendRequestRecord) -> ContactRecord:
        counterpart_id = request.counterpart_id(self._current_user_id)
        counterpart_name = request.counterpart_name(self._current_user_id)
        counterpart_avatar = request.counterpart_avatar(self._current_user_id)
        counterpart_gender = request.counterpart_gender(self._current_user_id)
        current_user_is_receiver = request.receiver_id == self._current_user_id
        raw_username = request.sender_name if current_user_is_receiver else request.receiver_name
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
                remark=existing.remark,
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
                self._remove_friend_item_view(contact.id)
                self._insert_friend_item_view(contact)
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

    def _friend_sort_key(self, contact: ContactRecord) -> tuple[str, str]:
        """Return the sidebar ordering key for one friend entry."""
        display_name = contact.display_name
        return self._controller.sort_letter(display_name), display_name.lower()

    def _schedule_groups_cache_persist(self) -> None:
        """Persist the current normalized group snapshot after local incremental mutations."""
        self._schedule_keyed_ui_task(
            ("persist_groups_cache", "groups"),
            self._controller.persist_groups_cache(list(self._groups)),
            "persist groups cache",
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

        if self._selected_key == ("group", group.id):
            self.detail_panel.set_group(group, self._current_detail_moments())

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
        current_moments = self._current_detail_moments()

        contacts_changed = False

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
                self.detail_panel.set_contact(updated, current_moments)

        if contacts_changed and self._current_page == "friends":
            self._restore_selection(full_reload=False)

        for index, group in enumerate(list(self._groups)):
            if session_id and group.session_id != session_id:
                continue
            if not session_avatar or group.avatar == session_avatar:
                continue
            updated = self._controller.normalize_group_record({"avatar": session_avatar}, existing=group, fallback_id=group.id)
            if updated is None:
                continue
            self._groups[index] = updated
            self._update_group_item_view(updated)
            if self._selected_key == ("group", updated.id):
                self.detail_panel.set_group(updated, current_moments)

        for index, request in enumerate(list(self._requests)):
            updated_request = request
            changed = False
            if request.sender_id == user_id:
                sender_name = str(profile.get("nickname", "") or profile.get("username", "") or request.sender_name)
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
                        sender_avatar=sender_avatar,
                        receiver_avatar=request.receiver_avatar,
                        sender_gender=sender_gender,
                        receiver_gender=request.receiver_gender,
                    )
                    changed = True
            elif request.receiver_id == user_id:
                receiver_name = str(profile.get("nickname", "") or profile.get("username", "") or request.receiver_name)
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
            if self._selected_key == ("request", updated_request.id):
                self.detail_panel.set_request(updated_request, self._current_user_id, current_moments)

    async def _reload_data_async(self) -> None:
        if not self._can_update_contact_ui():
            return
        logger.info("Contact interface reload started")
        self.summary_label.setText(tr("contact.sidebar.syncing", "Syncing contact data..."))
        try:
            self._contacts = await self._controller.load_contacts()
            if self._destroyed:
                return
            await asyncio.sleep(0)
            self._groups = await self._controller.load_groups()
            if self._destroyed:
                return
            await asyncio.sleep(0)
            self._requests = await self._controller.load_requests()
            self._moments = []
        except asyncio.CancelledError:
            raise
        except (APIError, NetworkError) as exc:
            if not self._can_update_contact_ui():
                return
            self.summary_label.setText(tr("contact.sidebar.load_failed", "Failed to load contacts."))
            InfoBar.error(tr("common.contacts", "Contacts"), str(exc), parent=self.window(), duration=2400)
            return
        except Exception:
            logger.exception("Unexpected contact load error")
            if not self._can_update_contact_ui():
                return
            self.summary_label.setText(tr("contact.sidebar.load_failed", "Failed to load contacts."))
            InfoBar.error(
                tr("common.contacts", "Contacts"),
                tr("contact.sidebar.load_unknown_error", "Unexpected error while loading contacts."),
                parent=self.window(),
                duration=2400,
            )
            return

        if not self._can_update_contact_ui():
            return
        logger.info(
            "Contact interface reload fetched %d friends, %d groups, %d requests",
            len(self._contacts),
            len(self._groups),
            len(self._requests),
        )
        self._update_summary_counts()
        logger.info("Contact interface rebuilding sidebar pages")
        self._build_friends_page()
        self._build_groups_page()
        self._build_requests_page()
        logger.info("Contact interface restoring selection")
        self._restore_selection(full_reload=True)
        keyword = self.search_box.text().strip()
        if keyword:
            self._search_timer.start()
        logger.info("Contact interface reload finished")

    def _rebuild_current_page(self) -> None:
        if self._current_page == "friends":
            self._build_friends_page()
        elif self._current_page == "groups":
            self._build_groups_page()
        else:
            self._build_requests_page()
        self._restore_selection(full_reload=False)

    def _update_summary_counts(self) -> None:
        if not self._can_update_contact_ui():
            return
        self.summary_label.setText(
            tr(
                "contact.sidebar.summary",
                "{friends} friends · {groups} groups · {requests} requests",
                friends=len(self._contacts),
                groups=len(self._groups),
                requests=len(self._requests),
            )
        )

    def _on_search_text_changed(self, text: str) -> None:
        """Open or update the anchored search flyout for the current keyword."""
        keyword = str(text or "").strip()
        self._pending_search_keyword = keyword

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
        if not keyword:
            return
        flyout_view = self._show_search_flyout()
        if flyout_view is not None:
            flyout_view.set_loading(keyword)
        self._set_search_task(self._run_global_search(keyword))

    async def _run_global_search(self, keyword: str) -> None:
        """Populate grouped local-search results for the contact sidebar."""
        results = await search_all(keyword, message_limit=30, contact_limit=30, group_limit=30)
        if self._destroyed or self.search_box.text().strip() != keyword:
            return
        flyout_view = self._show_search_flyout()
        if flyout_view is not None:
            flyout_view.set_results(keyword, results)

    def _on_search_result_activated(self, payload: object) -> None:
        """Route one grouped-search result into the shared chat-opening flow."""
        self.clear_search()
        self.message_requested.emit(payload)

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
        self.search_box.clear()

    @staticmethod
    def _friend_assistim_line(contact: ContactRecord) -> str:
        return str(contact.assistim_id or contact.username or "").strip() or "-"

    def _cancel_moment_load(self) -> None:
        self._cancel_pending_task(self._moment_load_task)
        self._moment_load_task = None

    def _load_detail_moments(self, user_id: str, kind: str, selection_id: str, payload: object) -> None:
        self._cancel_moment_load()
        if not user_id:
            return
        self._set_moment_load_task(self._load_detail_moments_async(user_id, kind, selection_id, payload))

    async def _load_detail_moments_async(self, user_id: str, kind: str, selection_id: str, payload: object) -> None:
        try:
            moments = await self._discovery_controller.load_moments(user_id=user_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("Contact detail moments load failed for %s", user_id, exc_info=True)
            moments = []

        if self._selected_key != (kind, selection_id):
            return

        if kind == "friend":
            self.detail_panel.set_contact(payload, moments)
        elif kind == "request":
            self.detail_panel.set_request(payload, self._current_user_id, moments)

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
        if not self._requests:
            self._add_empty_state(
                self.requests_layout,
                AppIcon.ADD,
                tr("contact.sidebar.empty_requests", "No new friend requests"),
            )
            return

        incoming = [item for item in self._requests if item.is_incoming(self._current_user_id)]
        outgoing = [item for item in self._requests if item.is_outgoing(self._current_user_id)]
        unknown = [item for item in self._requests if not item.is_incoming(self._current_user_id) and not item.is_outgoing(self._current_user_id)]
        ordered_requests = incoming + outgoing + unknown
        for request in ordered_requests:
            item = self._create_request_item(request)
            self.requests_layout.addWidget(item)
            self._request_items[request.id] = item
        self.requests_layout.addStretch(1)

    def _restore_selection(self, full_reload: bool) -> None:
        current_map = {
            "friends": self._friend_items,
            "groups": self._group_items,
            "requests": self._request_items,
        }
        current_category = {"friends": "friend", "groups": "group", "requests": "request"}[self._current_page]
        if self._selected_key:
            category, item_id = self._selected_key
            if not full_reload:
                if category != current_category:
                    self._clear_selection()
                    self._show_welcome_panel()
                    return
                current_visible = current_map[self._current_page]
                if item_id in current_visible:
                    self._clear_selection()
                    current_visible[item_id].set_selected(True)
                    self._show_detail_panel()
                else:
                    self._clear_selection()
                    self._show_welcome_panel()
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
        self._cancel_moment_load()
        self._clear_selection()
        self.detail_panel.show_placeholder()
        self._show_welcome_panel()

    def _select_friend(self, contact_id: str, force: bool = False) -> None:
        selected = next((item for item in self._contacts if item.id == contact_id), None)
        if not selected:
            return
        if not force and self._selected_key == ("friend", contact_id):
            return
        self._selected_key = ("friend", contact_id)
        self._clear_selection()
        self._friend_items[contact_id].set_selected(True)
        self.detail_panel.set_contact(selected, [])
        self._show_detail_panel()
        self._load_detail_moments(contact_id, "friend", contact_id, selected)

    def _select_group(self, group_id: str, force: bool = False) -> None:
        selected = next((item for item in self._groups if item.id == group_id), None)
        if not selected:
            return
        if not force and self._selected_key == ("group", group_id):
            return
        self._selected_key = ("group", group_id)
        self._cancel_moment_load()
        self._clear_selection()
        self._group_items[group_id].set_selected(True)
        self.detail_panel.set_group(selected, [])
        self._show_detail_panel()

    def _select_request(self, request_id: str, force: bool = False) -> None:
        selected = next((item for item in self._requests if item.id == request_id), None)
        if not selected:
            return
        if not force and self._selected_key == ("request", request_id):
            return
        self._selected_key = ("request", request_id)
        self._clear_selection()
        self._request_items[request_id].set_selected(True)
        counterpart_id = selected.counterpart_id(self._current_user_id)
        self.detail_panel.set_request(selected, self._current_user_id, [])
        self._show_detail_panel()
        self._load_detail_moments(counterpart_id, "request", request_id, selected)

    def _accept_request(self, request_id: str) -> None:
        request = next((item for item in self._requests if item.id == request_id), None)
        if not request or not request.can_review(self._current_user_id):
            return
        self._schedule_keyed_ui_task(
            ("accept_request", request_id),
            self._accept_request_async(request_id),
            f"accept request {request_id}",
        )

    async def _accept_request_async(self, request_id: str) -> None:
        try:
            payload = await self._controller.accept_request(request_id)
        except Exception as exc:
            InfoBar.error(tr("contact.request.tab_title", "New Friends"), str(exc), parent=self.window(), duration=2200)
            return
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
            self._reject_request_async(request_id),
            f"reject request {request_id}",
        )

    async def _reject_request_async(self, request_id: str) -> None:
        try:
            payload = await self._controller.reject_request(request_id)
        except Exception as exc:
            InfoBar.error(tr("contact.request.tab_title", "New Friends"), str(exc), parent=self.window(), duration=2200)
            return
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
            dialog = AddFriendDialog(
                self._controller,
                {item.id for item in self._contacts},
                self._current_user_id,
                self.window(),
            )
            dialog.friend_request_sent.connect(self._on_friend_request_sent)
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
            dialog = CreateGroupDialog(self._controller, self._contacts, self.window())
            dialog.group_created.connect(self._on_group_created)
            self._show_dialog(dialog)
            return

        InfoBar.info(
            tr("contact.detail.unavailable_title", "Notice"),
            tr("contact.sidebar.requests_inline_hint", "The request list is already available on this page."),
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

    def _on_friend_request_sent(self, payload: object) -> None:
        """Refresh only the affected sidebar slices after a friend action dialog completes."""
        request_payload = dict(payload or {}) if isinstance(payload, dict) else {}
        if not request_payload:
            return
        request = self._request_record_from_payload(request_payload)
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

    def _request_detail_like_toggle(self, moment_id: str, liked: bool, like_count: int) -> None:
        self._schedule_keyed_ui_task(
            ("moment_like", moment_id),
            self._request_detail_like_toggle_async(moment_id, liked, like_count),
            f"toggle moment like {moment_id}",
        )

    async def _request_detail_like_toggle_async(self, moment_id: str, liked: bool, like_count: int) -> None:
        previous_liked = not liked
        previous_count = like_count - 1 if liked else like_count + 1
        try:
            await self._discovery_controller.set_liked(moment_id, liked, like_count)
        except Exception as exc:
            self.detail_panel.moments_panel.set_like_state(moment_id, previous_liked, previous_count)
            InfoBar.error(tr("discovery.feed.title", "Moments"), str(exc), parent=self.window(), duration=2200)
            return

    def _request_detail_comment_create(self, moment_id: str, content: str) -> None:
        self._schedule_keyed_ui_task(
            ("moment_comment", moment_id),
            self._request_detail_comment_create_async(moment_id, content),
            f"create moment comment {moment_id}",
        )

    async def _request_detail_comment_create_async(self, moment_id: str, content: str) -> None:
        try:
            comment = await self._discovery_controller.add_comment(moment_id, content)
        except Exception as exc:
            InfoBar.error(tr("discovery.comment.title", "Post Comment"), str(exc), parent=self.window(), duration=2200)
            return

        self.detail_panel.moments_panel.append_comment(moment_id, comment)
        InfoBar.success(
            tr("discovery.comment.title", "Post Comment"),
            tr("discovery.comment.success", "Comment sent."),
            parent=self.window(),
            duration=1400,
        )

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
        self._destroyed = True
        self._event_bus.unsubscribe_sync(ContactEvent.SYNC_REQUIRED, self._on_contact_sync_required)
        self._search_timer.stop()
        self._cancel_pending_task(self._search_task)
        self._search_task = None
        self._dismiss_search_flyout(clear_results=False)
        self._cancel_pending_task(self._load_task)
        self._load_task = None
        self._cancel_pending_task(self._moment_load_task)
        self._moment_load_task = None
        for task in list(self._keyed_ui_tasks.values()):
            if not task.done():
                task.cancel()
        self._keyed_ui_tasks.clear()
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

    def _set_moment_load_task(self, coro) -> None:
        """Replace the active detail-moments load task."""
        self._cancel_pending_task(self._moment_load_task)
        self._moment_load_task = self._create_ui_task(coro, "load contact moments", on_done=self._clear_moment_load_task)

    def _clear_moment_load_task(self, task: asyncio.Task) -> None:
        """Clear the tracked moments task when it finishes."""
        if self._moment_load_task is task:
            self._moment_load_task = None

    def _schedule_keyed_ui_task(self, key: tuple[str, str], coro, context: str) -> None:
        """Prevent duplicate actions for the same target while one is still running."""
        existing = self._keyed_ui_tasks.get(key)
        if existing is not None and not existing.done():
            return
        self._keyed_ui_tasks[key] = self._create_ui_task(
            coro,
            context,
            on_done=lambda task, task_key=key: self._clear_keyed_ui_task(task_key, task),
        )

    def _clear_keyed_ui_task(self, key: tuple[str, str], task: asyncio.Task) -> None:
        """Clear a keyed action slot once its task finishes."""
        if self._keyed_ui_tasks.get(key) is task:
            self._keyed_ui_tasks.pop(key, None)










