"""Contact interface built with qfluentwidgets."""

from __future__ import annotations

import asyncio
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QLabel, QDialog, QFrame, QHBoxLayout, QSizePolicy, QSplitter, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentIcon,
    IconWidget,
    InfoBar,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SearchLineEdit,
    SegmentedWidget,
    SubtitleLabel,
    TitleLabel,
    TransparentToolButton,
)

from client.core import logging
from client.core.exceptions import APIError, NetworkError
from client.core.logging import setup_logging
from client.ui.controllers.auth_controller import get_auth_controller
from client.ui.controllers.contact_controller import (
    ContactRecord,
    FriendRequestRecord,
    GroupRecord,
    UserSearchRecord,
    get_contact_controller,
)

from client.ui.controllers.discovery_controller import MomentRecord, get_discovery_controller
from client.ui.styles import StyleSheet

setup_logging()
logger = logging.get_logger(__name__)


class ContactAvatar(QWidget):
    def __init__(self, size: int = 48, parent=None):
        super().__init__(parent)
        self._size = size
        self._pixmap: Optional[QPixmap] = None
        self._fallback = "?"
        self.setFixedSize(size, size)

    def set_avatar(self, avatar_path: str = "", fallback: str = "?") -> None:
        self._fallback = (fallback or "?").strip()[:2].upper() or "?"
        self._pixmap = None
        if avatar_path:
            pixmap = QPixmap(avatar_path)
            if not pixmap.isNull():
                self._pixmap = pixmap
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        clip = QPainterPath()
        clip.addEllipse(rect)
        painter.setClipPath(clip)
        if self._pixmap:
            scaled = self._pixmap.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(rect, scaled)
            return
        painter.fillPath(clip, QColor("#D9E4F5"))
        painter.setClipping(False)
        font = QFont()
        font.setPixelSize(max(12, self._size // 3))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#37506B"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._fallback)


class ElidedBodyLabel(QLabel):
    """Body label that elides long text to the available width."""

    def __init__(self, text: str = "", parent=None):
        super().__init__("", parent)
        self._full_text = ""
        self.setWordWrap(False)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        font = QFont(self.font())
        font.setPixelSize(15)
        font.setBold(True)
        self.setFont(font)
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full_text = text or ""
        self._refresh_text()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_text()

    def _refresh_text(self) -> None:
        available = max(0, self.contentsRect().width())
        display = self._full_text
        if available > 0:
            display = self.fontMetrics().elidedText(display, Qt.TextElideMode.ElideRight, available)
        super().setText(display)
        self.setToolTip(self._full_text if display != self._full_text else "")


class ElidedCaptionLabel(QLabel):
    """Caption label that elides long text to the available width."""

    def __init__(self, text: str = "", parent=None):
        super().__init__("", parent)
        self._full_text = ""
        self.setWordWrap(False)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        font = QFont(self.font())
        font.setPixelSize(12)
        self.setFont(font)
        self.setObjectName("elidedCaptionLabel")
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full_text = text or ""
        self._refresh_text()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_text()

    def _refresh_text(self) -> None:
        available = max(0, self.contentsRect().width())
        display = self._full_text
        if available > 0:
            display = self.fontMetrics().elidedText(display, Qt.TextElideMode.ElideRight, available)
        super().setText(display)
        self.setToolTip(self._full_text if display != self._full_text else "")


class ContactListItem(QWidget):
    clicked = Signal(str)

    def __init__(self, item_id: str, title: str, subtitle: str = "", meta: str = "", avatar: str = "", badge: str = "", parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self._selected = False
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(72)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        self.avatar = ContactAvatar(42, self)
        self.avatar.set_avatar(avatar, title)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)
        self.title_label = ElidedBodyLabel(title, self)
        top_row.addWidget(self.title_label, 1)
        badge_label = CaptionLabel(badge, self)
        badge_label.setVisible(bool(badge))
        top_row.addWidget(badge_label, 0)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(8)
        self.subtitle_label = ElidedCaptionLabel(subtitle, self)
        self.subtitle_label.setVisible(bool(subtitle))
        self.meta_label = CaptionLabel(meta, self)
        self.meta_label.setObjectName("contactMetaLabel")
        self.meta_label.setVisible(bool(meta))
        bottom_row.addWidget(self.subtitle_label, 1)
        bottom_row.addWidget(self.meta_label, 0)

        text_layout.addLayout(top_row)
        text_layout.addLayout(bottom_row)
        layout.addWidget(self.avatar, 0)
        layout.addLayout(text_layout, 1)

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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(4, 2, -4, -2)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        if self._selected:
            painter.fillPath(path, QColor("#E7F0FF"))
        elif self._hovered:
            painter.fillPath(path, QColor("#F5F8FC"))


class RequestListItem(CardWidget):
    accept_clicked = Signal(str)
    reject_clicked = Signal(str)
    selected = Signal(str)

    STATUS_TEXT = {
        "pending": "待处理",
        "accepted": "已通过",
        "rejected": "已拒绝",
        "expired": "已过期",
    }

    def __init__(self, request: FriendRequestRecord, current_user_id: str, parent=None):
        super().__init__(parent)
        self.request = request
        self.current_user_id = current_user_id
        self._selected = False
        self._hovered = False
        self.setObjectName("RequestListItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(0)
        self.setFixedHeight(72)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        avatar = ContactAvatar(42, self)
        avatar.set_avatar(fallback=request.counterpart_name(current_user_id))

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)

        self.title_label = ElidedBodyLabel(request.counterpart_name(current_user_id), self)
        text_layout.addWidget(self.title_label)

        if request.is_outgoing(current_user_id):
            message = request.message or "你发出了一条好友申请。"
        else:
            message = request.message or "对方向你发送了一条好友申请。"
        self.message_label = ElidedCaptionLabel(message, self)
        text_layout.addWidget(self.message_label)

        action_layout = QVBoxLayout()
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)
        action_layout.addStretch(1)
        if request.can_review(current_user_id):
            accept_button = PrimaryPushButton("通过", self)
            reject_button = PushButton("拒绝", self)
            accept_button.setFixedWidth(76)
            reject_button.setFixedWidth(76)
            accept_button.clicked.connect(lambda: self.accept_clicked.emit(self.request.id))
            reject_button.clicked.connect(lambda: self.reject_clicked.emit(self.request.id))
            action_layout.addWidget(accept_button, 0, Qt.AlignmentFlag.AlignHCenter)
            action_layout.addWidget(reject_button, 0, Qt.AlignmentFlag.AlignHCenter)
        else:
            status_button = PushButton(self._status_text(), self)
            status_button.setObjectName("requestStatusButton")
            status_button.setFixedWidth(88)
            status_button.setEnabled(False)
            action_layout.addWidget(status_button, 0, Qt.AlignmentFlag.AlignHCenter)
        action_layout.addStretch(1)

        layout.addWidget(avatar, 0)
        layout.addLayout(text_layout, 1)
        layout.addLayout(action_layout, 0)

    def _status_text(self) -> str:
        return self.STATUS_TEXT.get(self.request.status, self.request.status_label() or "已处理")

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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(4, 2, -4, -2)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        if self._selected:
            painter.fillPath(path, QColor("#E7F0FF"))
        elif self._hovered:
            painter.fillPath(path, QColor("#F5F8FC"))
        super().paintEvent(event)


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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        avatar = ContactAvatar(36, self)
        avatar.set_avatar(moment.avatar, moment.display_name)
        header_text = QVBoxLayout()
        header_text.setContentsMargins(0, 0, 0, 0)
        header_text.setSpacing(2)
        header_text.addWidget(BodyLabel(moment.display_name, self))
        header_text.addWidget(CaptionLabel(moment.created_at or "刚刚", self))
        header.addWidget(avatar, 0)
        header.addLayout(header_text, 1)
        layout.addLayout(header)

        content_label = BodyLabel(moment.content or "", self)
        content_label.setWordWrap(True)
        layout.addWidget(content_label)

        meta = CaptionLabel(f"{moment.like_count} 赞 · {moment.comment_count} 评论", self)
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

        self.title_label = SubtitleLabel("朋友圈", self)
        self.subtitle_label = CaptionLabel("浏览该联系人的最近动态", self)
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
            self.container_layout.addWidget(BodyLabel("这个联系人还没有动态。", self.container))
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
        self.title_label = TitleLabel("联系人详情", self.profile_card)
        self.subtitle_label = CaptionLabel("从左侧选择一个联系人、群组或申请查看详情。", self.profile_card)
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
        self.message_button = PrimaryPushButton("发消息", self.profile_card)
        self.voice_button = PushButton("语音通话", self.profile_card)
        self.video_button = PushButton("视频通话", self.profile_card)
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
        self.title_label.setText("联系人详情")
        self.subtitle_label.setText("从左侧选择一个联系人、群组或好友申请查看详情。")
        self._set_rows([])
        self.message_button.setEnabled(False)
        self.voice_button.setEnabled(False)
        self.video_button.setEnabled(False)
        self.moments_panel.show_placeholder()

    def set_contact(self, contact: ContactRecord, moments: Optional[list[MomentRecord]] = None) -> None:
        self._entity = {"type": "friend", "data": contact}
        self.avatar.set_avatar(contact.avatar, contact.display_name)
        self.title_label.setText(contact.display_name)
        self.subtitle_label.setText(contact.username or contact.assistim_id or "好友")
        self._set_rows([
            ("AssistIM 号", contact.assistim_id or contact.username or "-"),
            ("昵称", contact.nickname or "-"),
            ("备注", contact.remark or "-"),
            ("地区", contact.region or "-"),
            ("个性签名", contact.signature or "-"),
        ])
        self.message_button.setEnabled(True)
        self.voice_button.setEnabled(True)
        self.video_button.setEnabled(True)
        self.moments_panel.set_moments(moments or [])

    def set_group(self, group: GroupRecord, moments: Optional[list[MomentRecord]] = None) -> None:
        self._entity = {"type": "group", "data": group}
        self.avatar.set_avatar(fallback=group.name)
        self.title_label.setText(group.name)
        self.subtitle_label.setText("群组")
        self._set_rows([
            ("群组 ID", group.id or "-"),
            ("会话 ID", group.session_id or "-"),
            ("成员数量", str(group.member_count)),
            ("创建时间", group.created_at or "-"),
        ])
        self.message_button.setEnabled(True)
        self.voice_button.setEnabled(False)
        self.video_button.setEnabled(False)
        self.moments_panel.set_moments(moments or [])

    def set_request(self, request: FriendRequestRecord, current_user_id: str = "", moments: Optional[list[MomentRecord]] = None) -> None:
        self._entity = None
        counterpart_name = request.counterpart_name(current_user_id)
        self.avatar.set_avatar(fallback=counterpart_name)
        self.title_label.setText("收到的好友申请" if request.is_incoming(current_user_id) else "发出的好友申请")
        self.subtitle_label.setText(counterpart_name)
        self._set_rows([
            ("发送者 ID", request.sender_id or "-"),
            ("接收者 ID", request.receiver_id or "-"),
            ("申请状态", request.status_label()),
            ("申请信息", request.message or "对方没有填写验证信息。"),
            ("时间", request.created_at or "-"),
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
        InfoBar.info("提示", "语音和视频入口先保留 UI，后续再接业务逻辑。", parent=self.window(), duration=1800)


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
        avatar.set_avatar(user.avatar, user.display_name)

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

        self.add_button = PrimaryPushButton("添加好友", self)
        self.add_button.setFixedWidth(88)
        self.add_button.setDisabled(bool(disabled_reason))
        if disabled_reason:
            self.add_button.setText(disabled_reason)
        self.add_button.clicked.connect(lambda: self.add_clicked.emit(self.user.id))

        layout.addWidget(avatar, 0)
        layout.addLayout(text_layout, 1)
        layout.addWidget(self.add_button, 0)


class GroupMemberItem(CardWidget):
    toggled = Signal(str, bool)

    def __init__(self, contact: ContactRecord, parent=None):
        super().__init__(parent)
        self.setObjectName("GroupMemberItem")
        self.contact = contact
        self._selected = False
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        self.avatar = ContactAvatar(42, self)
        self.avatar.set_avatar(contact.avatar, contact.display_name)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        text_layout.addWidget(BodyLabel(contact.display_name, self))

        subtitle = CaptionLabel(contact.signature or contact.username or "-", self)
        subtitle.setWordWrap(True)
        text_layout.addWidget(subtitle)

        self.state_label = CaptionLabel("未选择", self)

        layout.addWidget(self.avatar, 0)
        layout.addLayout(text_layout, 1)
        layout.addWidget(self.state_label, 0)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.state_label.setText("已选择" if selected else "未选择")
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
            self.set_selected(not self._selected)
            self.toggled.emit(self.contact.id, self._selected)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._selected and not self._hovered:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        painter.fillPath(path, QColor(94, 146, 255, 22 if self._selected else 10))


class AddFriendDialog(QDialog):
    friend_request_sent = Signal()

    def __init__(self, controller, existing_ids: set[str], parent=None):
        super().__init__(parent)
        self._controller = controller
        auth = get_auth_controller()
        current_user = auth.current_user or {}
        self._current_user_id = str(current_user.get("id", "") or "")
        self._existing_ids = set(existing_ids)
        self._search_task: Optional[asyncio.Task] = None
        self._action_task: Optional[asyncio.Task] = None

        self.setWindowTitle("新增好友")
        self.setModal(True)
        self.resize(560, 680)

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        layout.addWidget(TitleLabel("新增好友", self))
        subtitle = CaptionLabel("按用户名或昵称搜索用户，然后发送好友申请。", self)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(10)
        self.search_edit = SearchLineEdit(self)
        self.search_edit.setPlaceholderText("搜索用户名或昵称")
        self.search_edit.setMinimumHeight(38)
        self.search_button = PrimaryPushButton("搜索", self)
        self.search_button.setFixedWidth(88)
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.search_button, 0)
        layout.addLayout(search_row)

        self.message_edit = LineEdit(self)
        self.message_edit.setPlaceholderText("验证消息（可选）")
        self.message_edit.setMinimumHeight(38)
        layout.addWidget(self.message_edit)

        self.summary_label = CaptionLabel("输入关键词后搜索用户。", self)
        self.summary_label.setObjectName("contactSummaryLabel")
        layout.addWidget(self.summary_label)

        self.result_area = ScrollArea(self)
        self.result_area.setWidgetResizable(True)
        self.result_area.setFrameShape(QFrame.Shape.NoFrame)
        self.result_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.result_container = QWidget(self.result_area)
        self.result_layout = QVBoxLayout(self.result_container)
        self.result_layout.setContentsMargins(6, 6, 6, 6)
        self.result_layout.setSpacing(8)
        self.result_layout.addStretch(1)
        self.result_area.setWidget(self.result_container)
        layout.addWidget(self.result_area, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch(1)
        self.close_button = PushButton("关闭", self)
        footer.addWidget(self.close_button, 0)
        layout.addLayout(footer)

        self.search_button.clicked.connect(self._trigger_search)
        self.search_edit.returnPressed.connect(self._trigger_search)
        self.close_button.clicked.connect(self.close)

    def _trigger_search(self) -> None:
        keyword = self.search_edit.text().strip()
        if not keyword:
            self.summary_label.setText("请输入搜索关键词。")
            return

        if self._search_task and not self._search_task.done():
            self._search_task.cancel()
        self._search_task = asyncio.create_task(self._search_async(keyword))

    async def _search_async(self, keyword: str) -> None:
        self.summary_label.setText("正在搜索用户...")
        try:
            users = await self._controller.search_users(keyword)
        except Exception as exc:
            self.summary_label.setText("搜索失败")
            InfoBar.error("新增好友", str(exc), parent=self, duration=2200)
            return

        filtered = [user for user in users if user.id and user.id != self._current_user_id]
        self.summary_label.setText(f"共找到 {len(filtered)} 位用户")
        self._render_search_results(filtered)

    def _render_search_results(self, users: list[UserSearchRecord]) -> None:
        self._clear_layout(self.result_layout)
        if not users:
            self.result_layout.addWidget(BodyLabel("没有找到匹配用户。", self.result_container))
            self.result_layout.addStretch(1)
            return

        for user in users:
            reason = "已是好友" if user.id in self._existing_ids else ""
            item = UserSearchItem(user, reason, self.result_container)
            if not reason:
                item.add_clicked.connect(self._send_friend_request)
            self.result_layout.addWidget(item)
        self.result_layout.addStretch(1)

    def _send_friend_request(self, user_id: str) -> None:
        if self._action_task and not self._action_task.done():
            return
        self._action_task = asyncio.create_task(self._send_friend_request_async(user_id))

    async def _send_friend_request_async(self, user_id: str) -> None:
        try:
            await self._controller.send_friend_request(user_id, self.message_edit.text().strip())
        except Exception as exc:
            InfoBar.error("新增好友", str(exc), parent=self, duration=2200)
            return

        InfoBar.success("新增好友", "好友申请已发送", parent=self, duration=1800)
        self.friend_request_sent.emit()
        self.close()

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


class CreateGroupDialog(QDialog):
    group_created = Signal(object)

    def __init__(self, controller, contacts: list[ContactRecord], parent=None):
        super().__init__(parent)
        self._controller = controller
        self._contacts = list(contacts)
        self._selected_ids: set[str] = set()
        self._member_items: dict[str, GroupMemberItem] = {}
        self._create_task: Optional[asyncio.Task] = None

        self.setWindowTitle("新建群组")
        self.setModal(True)
        self.resize(580, 720)

        self._setup_ui()
        self._rebuild_member_list()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        layout.addWidget(TitleLabel("新建群组", self))
        subtitle = CaptionLabel("从当前好友中选择成员，创建一个新的群组会话。", self)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("输入群组名称")
        self.name_edit.setMinimumHeight(38)
        layout.addWidget(self.name_edit)

        self.search_edit = SearchLineEdit(self)
        self.search_edit.setPlaceholderText("筛选好友")
        self.search_edit.setMinimumHeight(38)
        layout.addWidget(self.search_edit)

        self.summary_label = CaptionLabel("请选择至少 1 位好友。", self)
        self.summary_label.setObjectName("contactSummaryLabel")
        layout.addWidget(self.summary_label)

        self.member_area = ScrollArea(self)
        self.member_area.setWidgetResizable(True)
        self.member_area.setFrameShape(QFrame.Shape.NoFrame)
        self.member_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.member_container = QWidget(self.member_area)
        self.member_layout = QVBoxLayout(self.member_container)
        self.member_layout.setContentsMargins(6, 6, 6, 6)
        self.member_layout.setSpacing(8)
        self.member_layout.addStretch(1)
        self.member_area.setWidget(self.member_container)
        layout.addWidget(self.member_area, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(10)
        footer.addStretch(1)
        self.cancel_button = PushButton("取消", self)
        self.create_button = PrimaryPushButton("创建群组", self)
        footer.addWidget(self.cancel_button, 0)
        footer.addWidget(self.create_button, 0)
        layout.addLayout(footer)

        self.search_edit.textChanged.connect(self._rebuild_member_list)
        self.cancel_button.clicked.connect(self.close)
        self.create_button.clicked.connect(self._create_group)

    def _rebuild_member_list(self) -> None:
        self._clear_layout(self.member_layout)
        self._member_items.clear()

        keyword = self.search_edit.text().strip().lower()
        filtered = [
            contact
            for contact in self._contacts
            if not keyword
            or keyword in contact.display_name.lower()
            or keyword in contact.username.lower()
            or keyword in contact.signature.lower()
        ]

        if not filtered:
            self.member_layout.addWidget(BodyLabel("没有匹配的好友。", self.member_container))
            self.member_layout.addStretch(1)
            self._update_summary()
            return

        for contact in filtered:
            item = GroupMemberItem(contact, self.member_container)
            item.set_selected(contact.id in self._selected_ids)
            item.toggled.connect(self._toggle_member)
            self.member_layout.addWidget(item)
            self._member_items[contact.id] = item

        self.member_layout.addStretch(1)
        self._update_summary()

    def _toggle_member(self, contact_id: str, selected: bool) -> None:
        if selected:
            self._selected_ids.add(contact_id)
        else:
            self._selected_ids.discard(contact_id)
        self._update_summary()

    def _update_summary(self) -> None:
        self.summary_label.setText(f"已选择 {len(self._selected_ids)} 位好友")

    def _create_group(self) -> None:
        if self._create_task and not self._create_task.done():
            return

        name = self.name_edit.text().strip()
        if not name:
            InfoBar.warning("新建群组", "请输入群组名称", parent=self, duration=1800)
            self.name_edit.setFocus()
            return

        if not self._selected_ids:
            InfoBar.warning("新建群组", "请至少选择 1 位好友", parent=self, duration=1800)
            return

        self._create_task = asyncio.create_task(self._create_group_async(name))

    async def _create_group_async(self, name: str) -> None:
        self.create_button.setEnabled(False)
        self.create_button.setText("创建中...")
        try:
            group = await self._controller.create_group(name, list(self._selected_ids))
        except Exception as exc:
            InfoBar.error("新建群组", str(exc), parent=self, duration=2200)
        else:
            InfoBar.success("新建群组", "群组创建成功", parent=self, duration=1800)
            self.group_created.emit(group)
            self.close()
        finally:
            self.create_button.setEnabled(True)
            self.create_button.setText("创建群组")

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
        self._dialog_refs: set[QDialog] = set()
        self._current_user_id = ""
        self._setup_ui()
        self._connect_signals()
        QTimer.singleShot(0, self.reload_data)

    def _setup_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setObjectName("contactSplitter")
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)

        sidebar = CardWidget(self)
        sidebar.setObjectName("ContactSidebarCard")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(20, 20, 20, 20)
        sidebar_layout.setSpacing(16)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(2)
        title_stack.addWidget(TitleLabel("联系人", sidebar))
        self.summary_label = CaptionLabel("正在加载联系人数据...", sidebar)
        self.summary_label.setObjectName("contactSummaryLabel")
        title_stack.addWidget(self.summary_label)
        self.refresh_button = TransparentToolButton(FluentIcon.SYNC, sidebar)
        self.add_button = TransparentToolButton(FluentIcon.ADD, sidebar)
        self.refresh_button.setToolTip("刷新")
        self.add_button.setToolTip("新增")
        title_row.addLayout(title_stack, 1)
        title_row.addWidget(self.refresh_button, 0)
        title_row.addWidget(self.add_button, 0)

        self.search_box = SearchLineEdit(sidebar)
        self.search_box.setPlaceholderText("搜索联系人、群组或申请")
        self.search_box.setMinimumHeight(38)

        self.segmented = SegmentedWidget(sidebar)
        self.segmented.addItem("friends", "好友", lambda: self._switch_page("friends"))
        self.segmented.addItem("groups", "群组", lambda: self._switch_page("groups"))
        self.segmented.addItem("requests", "新朋友", lambda: self._switch_page("requests"))

        self.page_stack = QStackedWidget(sidebar)
        self.friends_page, self.friends_container, self.friends_layout = self._create_scroll_page()
        self.groups_page, self.groups_container, self.groups_layout = self._create_scroll_page()
        self.requests_page, self.requests_container, self.requests_layout = self._create_scroll_page()
        self.page_stack.addWidget(self.friends_page)
        self.page_stack.addWidget(self.groups_page)
        self.page_stack.addWidget(self.requests_page)

        sidebar_layout.addLayout(title_row)
        sidebar_layout.addWidget(self.search_box)
        sidebar_layout.addWidget(self.segmented, 0, Qt.AlignmentFlag.AlignLeft)
        sidebar_layout.addWidget(self.page_stack, 1)

        left = QWidget(self)
        left.setMinimumWidth(260)
        left.setMaximumWidth(560)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(sidebar)

        self.detail_panel = ContactDetailPanel(self)

        splitter.addWidget(left)
        splitter.addWidget(self.detail_panel)
        splitter.setSizes([320, 880])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        StyleSheet.CONTACT_INTERFACE.apply(self)
        self.segmented.setCurrentItem("friends")
        self._switch_page("friends")

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(self.reload_data)
        self.add_button.clicked.connect(self._show_add_placeholder)
        self.search_box.textChanged.connect(self._rebuild_current_page)
        self.detail_panel.message_requested.connect(self.message_requested.emit)

    def _create_scroll_page(self) -> tuple[ScrollArea, QWidget, QVBoxLayout]:
        area = ScrollArea(self)
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget(area)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addStretch(1)
        area.setWidget(container)
        return area, container, layout

    def _switch_page(self, key: str) -> None:
        self._current_page = key
        self.page_stack.setCurrentIndex({"friends": 0, "groups": 1, "requests": 2}[key])
        self._rebuild_current_page()

    def reload_data(self) -> None:
        auth = get_auth_controller()
        current_user = auth.current_user or {}
        self._current_user_id = str(current_user.get("id", "") or "")
        if self._load_task and not self._load_task.done():
            self._load_task.cancel()
        self._load_task = asyncio.create_task(self._reload_data_async())

    async def _reload_data_async(self) -> None:
        self.summary_label.setText("正在同步联系人数据...")
        try:
            self._contacts, self._groups, self._requests = await asyncio.gather(
                self._controller.load_contacts(),
                self._controller.load_groups(),
                self._controller.load_requests(),
            )
            self._moments = []
        except asyncio.CancelledError:
            raise
        except (APIError, NetworkError) as exc:
            self.summary_label.setText("联系人加载失败")
            InfoBar.error("联系人", str(exc), parent=self.window(), duration=2400)
            return
        except Exception:
            logger.exception("Unexpected contact load error")
            self.summary_label.setText("联系人加载失败")
            InfoBar.error("联系人", "加载联系人时发生未知错误", parent=self.window(), duration=2400)
            return

        self.summary_label.setText(f"{len(self._contacts)} 位好友 · {len(self._groups)} 个群组 · {len(self._requests)} 条申请")
        self._build_friends_page()
        self._build_groups_page()
        self._build_requests_page()
        self._restore_selection(full_reload=True)

    def _rebuild_current_page(self) -> None:
        if self._current_page == "friends":
            self._build_friends_page()
        elif self._current_page == "groups":
            self._build_groups_page()
        else:
            self._build_requests_page()
        self._restore_selection(full_reload=False)

    def _cancel_moment_load(self) -> None:
        if self._moment_load_task and not self._moment_load_task.done():
            self._moment_load_task.cancel()

    def _load_detail_moments(self, user_id: str, kind: str, selection_id: str, payload: object) -> None:
        self._cancel_moment_load()
        if not user_id:
            return
        self._moment_load_task = asyncio.create_task(
            self._load_detail_moments_async(user_id, kind, selection_id, payload)
        )

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
        search = self.search_box.text().strip().lower()
        filtered = [
            item for item in self._contacts
            if not search or search in item.display_name.lower() or search in item.username.lower() or search in item.signature.lower()
        ]
        grouped = self._controller.group_contacts(filtered)
        if not filtered:
            self._add_empty_state(self.friends_layout, FluentIcon.PEOPLE, "没有找到匹配的好友")
            return
        for letter, contacts in grouped.items():
            self.friends_layout.addWidget(SubtitleLabel(letter, self.friends_container))
            for contact in contacts:
                item = ContactListItem(contact.id, contact.display_name, contact.signature or contact.username, contact.username, contact.avatar)
                item.clicked.connect(self._select_friend)
                self.friends_layout.addWidget(item)
                self._friend_items[contact.id] = item
        self.friends_layout.addStretch(1)

    def _build_groups_page(self) -> None:
        self._clear_layout(self.groups_layout)
        self._group_items.clear()
        search = self.search_box.text().strip().lower()
        filtered = [item for item in self._groups if not search or search in item.name.lower() or search in item.id.lower()]
        if not filtered:
            self._add_empty_state(self.groups_layout, FluentIcon.PEOPLE, "当前没有群组")
            return
        for group in filtered:
            item = ContactListItem(group.id, group.name, f"成员 {group.member_count}", "群组", badge="GROUP")
            item.clicked.connect(self._select_group)
            self.groups_layout.addWidget(item)
            self._group_items[group.id] = item
        self.groups_layout.addStretch(1)

    def _build_requests_page(self) -> None:
        self._clear_layout(self.requests_layout)
        self._request_items.clear()
        search = self.search_box.text().strip().lower()
        filtered = [
            item for item in self._requests
            if not search
            or search in item.counterpart_name(self._current_user_id).lower()
            or search in item.counterpart_id(self._current_user_id).lower()
            or search in item.sender_id.lower()
            or search in item.receiver_id.lower()
            or search in item.message.lower()
        ]
        if not filtered:
            self._add_empty_state(self.requests_layout, FluentIcon.ADD, "没有新的好友申请")
            return

        incoming = [item for item in filtered if item.is_incoming(self._current_user_id)]
        outgoing = [item for item in filtered if item.is_outgoing(self._current_user_id)]
        unknown = [item for item in filtered if not item.is_incoming(self._current_user_id) and not item.is_outgoing(self._current_user_id)]

        sections = [
            ("收到的申请", incoming),
            ("发出的申请", outgoing),
            ("其他申请", unknown),
        ]

        for title, requests in sections:
            if not requests:
                continue

            self.requests_layout.addWidget(SubtitleLabel(title, self.requests_container))
            for request in requests:
                item = RequestListItem(request, self._current_user_id, self.requests_container)
                if request.can_review(self._current_user_id):
                    item.accept_clicked.connect(self._accept_request)
                    item.reject_clicked.connect(self._reject_request)
                item.selected.connect(self._select_request)
                self.requests_layout.addWidget(item)
                self._request_items[request.id] = item
        self.requests_layout.addStretch(1)

    def _restore_selection(self, full_reload: bool) -> None:
        current_map = {
            "friends": self._friend_items,
            "groups": self._group_items,
            "requests": self._request_items,
        }
        if self._selected_key:
            category, item_id = self._selected_key
            if category == "friend" and item_id in self._friend_items:
                self._select_friend(item_id)
                return
            if category == "group" and item_id in self._group_items:
                self._select_group(item_id)
                return
            if category == "request" and item_id in self._request_items:
                self._select_request(item_id)
                return
        visible = current_map[self._current_page]
        if visible:
            first_id = next(iter(visible))
            {"friends": self._select_friend, "groups": self._select_group, "requests": self._select_request}[self._current_page](first_id)
            return
        if full_reload:
            for category, mapping in (("friend", self._friend_items), ("group", self._group_items), ("request", self._request_items)):
                if mapping:
                    first_id = next(iter(mapping))
                    {"friend": self._select_friend, "group": self._select_group, "request": self._select_request}[category](first_id)
                    return
        self._selected_key = None
        self._cancel_moment_load()
        self._clear_selection()
        self.detail_panel.show_placeholder()

    def _select_friend(self, contact_id: str) -> None:
        selected = next((item for item in self._contacts if item.id == contact_id), None)
        if not selected:
            return
        self._selected_key = ("friend", contact_id)
        self._clear_selection()
        self._friend_items[contact_id].set_selected(True)
        self.detail_panel.set_contact(selected, [])
        self._load_detail_moments(contact_id, "friend", contact_id, selected)

    def _select_group(self, group_id: str) -> None:
        selected = next((item for item in self._groups if item.id == group_id), None)
        if not selected:
            return
        self._selected_key = ("group", group_id)
        self._cancel_moment_load()
        self._clear_selection()
        self._group_items[group_id].set_selected(True)
        self.detail_panel.set_group(selected, [])

    def _select_request(self, request_id: str) -> None:
        selected = next((item for item in self._requests if item.id == request_id), None)
        if not selected:
            return
        self._selected_key = ("request", request_id)
        self._clear_selection()
        self._request_items[request_id].set_selected(True)
        counterpart_id = selected.counterpart_id(self._current_user_id)
        self.detail_panel.set_request(selected, self._current_user_id, [])
        self._load_detail_moments(counterpart_id, "request", request_id, selected)

    def _accept_request(self, request_id: str) -> None:
        request = next((item for item in self._requests if item.id == request_id), None)
        if not request or not request.can_review(self._current_user_id):
            return
        asyncio.create_task(self._accept_request_async(request_id))

    async def _accept_request_async(self, request_id: str) -> None:
        try:
            await self._controller.accept_request(request_id)
        except Exception as exc:
            InfoBar.error("新朋友", str(exc), parent=self.window(), duration=2200)
            return
        InfoBar.success("新朋友", "好友申请已通过", parent=self.window(), duration=1800)
        self.reload_data()

    def _reject_request(self, request_id: str) -> None:
        request = next((item for item in self._requests if item.id == request_id), None)
        if not request or not request.can_review(self._current_user_id):
            return
        asyncio.create_task(self._reject_request_async(request_id))

    async def _reject_request_async(self, request_id: str) -> None:
        try:
            await self._controller.reject_request(request_id)
        except Exception as exc:
            InfoBar.error("新朋友", str(exc), parent=self.window(), duration=2200)
            return
        InfoBar.success("新朋友", "好友申请已拒绝", parent=self.window(), duration=1800)
        self.reload_data()

    def _show_add_placeholder(self) -> None:
        if self._current_page == "friends":
            dialog = AddFriendDialog(self._controller, {item.id for item in self._contacts}, self.window())
            dialog.friend_request_sent.connect(self._on_friend_request_sent)
            self._show_dialog(dialog)
            return

        if self._current_page == "groups":
            if not self._contacts:
                InfoBar.info("新建群组", "当前没有可选的好友", parent=self.window(), duration=2000)
                return
            dialog = CreateGroupDialog(self._controller, self._contacts, self.window())
            dialog.group_created.connect(self._on_group_created)
            self._show_dialog(dialog)
            return

        InfoBar.info("提示", "申请列表已经可以在当前页面直接查看。", parent=self.window(), duration=1800)

    def _show_dialog(self, dialog: QDialog) -> None:
        """Keep a dialog alive while it is visible."""
        self._dialog_refs.add(dialog)
        dialog.finished.connect(lambda _result=0, dlg=dialog: self._dialog_refs.discard(dlg))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_friend_request_sent(self) -> None:
        """Refresh data after a new friend request is sent."""
        self._current_page = "requests"
        self.segmented.setCurrentItem("requests")
        self.page_stack.setCurrentIndex(2)
        self.reload_data()

    def _on_group_created(self, group: object) -> None:
        """Switch to groups and jump into the new group chat."""
        self._current_page = "groups"
        self.segmented.setCurrentItem("groups")
        self.page_stack.setCurrentIndex(1)
        self.reload_data()
        self.message_requested.emit({"type": "group", "data": group})

    def _add_empty_state(self, layout: QVBoxLayout, icon: FluentIcon, text: str) -> None:
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
