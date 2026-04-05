"""Formal group-announcement view and edit dialog."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, PrimaryPushButton, PushButton, SingleDirectionScrollArea, TextEdit

from client.core.avatar_utils import profile_avatar_seed
from client.core.i18n import tr
from client.models.message import Session
from client.ui.widgets.contact_shared import ContactAvatar, apply_themed_dialog_surface, prepare_transparent_scroll_area


def _member_display_name(member: dict[str, object]) -> str:
    return (
        str(member.get("group_nickname", "") or "").strip()
        or str(member.get("remark", "") or "").strip()
        or str(member.get("nickname", "") or "").strip()
        or str(member.get("display_name", "") or "").strip()
        or str(member.get("username", "") or "").strip()
        or str(member.get("id", "") or member.get("user_id", "") or "").strip()
        or tr("session.unnamed", "Untitled Session")
    )


def _member_role(member: dict[str, object], owner_id: str) -> str:
    role = str(member.get("role", "") or "").strip().lower()
    if role:
        return role
    member_id = str(member.get("id", "") or member.get("user_id", "") or "").strip()
    return "owner" if member_id and member_id == owner_id else "member"


def _resolve_current_role(session: Session, current_user_id: str) -> str:
    if not current_user_id:
        return "member"
    owner_id = str(session.extra.get("owner_id", "") or "").strip()
    if owner_id and owner_id == current_user_id:
        return "owner"
    for member in list(session.extra.get("members") or []):
        member_id = str(member.get("id", "") or member.get("user_id", "") or "").strip()
        if member_id == current_user_id:
            return _member_role(member, owner_id)
    return "member"


def _format_announcement_time(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y.%m.%d %H:%M")


class GroupAnnouncementDialog(QDialog):
    """View one group announcement and optionally switch into edit mode."""

    def __init__(self, session: Session, current_user: dict[str, object] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._session = session
        self._current_user = dict(current_user or {})
        self._current_user_id = str(self._current_user.get("id", "") or "")
        self._original_announcement = session.group_announcement_text()
        self._pending_announcement: str | None = None
        self._can_edit = _resolve_current_role(session, self._current_user_id) in {"owner", "admin"}

        self.setModal(True)
        self.resize(620, 700)
        self.setWindowTitle(
            tr(
                "chat.group_announcement.window_title",
                '"{name}"的群公告',
                name=session.chat_title() or session.display_name() or tr("session.unnamed", "Untitled Session"),
            )
        )
        apply_themed_dialog_surface(self, "GroupAnnouncementDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(12)

        author_meta = self._resolve_author_meta()
        self.author_avatar = ContactAvatar(46, self)
        self.author_avatar.set_avatar(
            author_meta["avatar"],
            author_meta["name"],
            gender=author_meta["gender"],
            seed=author_meta["seed"],
        )

        header_text_layout = QVBoxLayout()
        header_text_layout.setContentsMargins(0, 0, 0, 0)
        header_text_layout.setSpacing(6)

        self.author_name_label = BodyLabel(author_meta["name"], self)
        author_font = QFont(self.author_name_label.font())
        author_font.setPixelSize(18)
        self.author_name_label.setFont(author_font)

        published_at = _format_announcement_time(self._session.group_announcement_published_at())
        self.published_at_label = CaptionLabel(published_at, self)

        header_text_layout.addWidget(self.author_name_label, 0, Qt.AlignmentFlag.AlignLeft)
        header_text_layout.addWidget(self.published_at_label, 0, Qt.AlignmentFlag.AlignLeft)

        header_row.addWidget(self.author_avatar, 0, Qt.AlignmentFlag.AlignTop)
        header_row.addLayout(header_text_layout, 1)

        self.edit_button = PushButton(tr("chat.group_announcement.edit", "Edit Announcement"), self)
        self.edit_button.clicked.connect(self._enter_edit_mode)
        self.edit_button.setVisible(self._can_edit)
        header_row.addWidget(self.edit_button, 0, Qt.AlignmentFlag.AlignTop)

        divider = QFrame(self)
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Plain)
        divider.setObjectName("groupAnnouncementDialogDivider")

        self.scroll_area = SingleDirectionScrollArea(self, orient=Qt.Orientation.Vertical)
        prepare_transparent_scroll_area(self.scroll_area)
        self.scroll_content = QWidget(self.scroll_area)
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(8)

        self.content_label = BodyLabel(self._original_announcement, self.scroll_content)
        self.content_label.setWordWrap(True)
        self.content_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self.content_editor = TextEdit(self.scroll_content)
        self.content_editor.setPlainText(self._original_announcement)
        self.content_editor.setPlaceholderText(tr("chat.info.group.announcement.empty", "No group announcement yet"))
        self.content_editor.setMinimumHeight(280)
        self.content_editor.hide()

        self.scroll_layout.addWidget(self.content_label)
        self.scroll_layout.addWidget(self.content_editor)
        self.scroll_layout.addStretch(1)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_content)

        self.button_row = QHBoxLayout()
        self.button_row.setContentsMargins(0, 0, 0, 0)
        self.button_row.setSpacing(10)
        self.button_row.addStretch(1)

        self.cancel_button = PushButton(tr("common.cancel", "Cancel"), self)
        self.cancel_button.clicked.connect(self._cancel_edit_mode)
        self.save_button = PrimaryPushButton(tr("common.save", "Save"), self)
        self.save_button.clicked.connect(self._submit_edit)
        self.button_row.addWidget(self.cancel_button)
        self.button_row.addWidget(self.save_button)

        self.cancel_button.hide()
        self.save_button.hide()

        root.addLayout(header_row)
        root.addWidget(divider)
        root.addWidget(self.scroll_area, 1)
        root.addLayout(self.button_row)

    def _resolve_author_meta(self) -> dict[str, str]:
        announcement_author_id = self._session.group_announcement_author_id()
        members = list(self._session.extra.get("members") or [])
        for member in members:
            member_id = str(member.get("id", "") or member.get("user_id", "") or "").strip()
            if member_id != announcement_author_id:
                continue
            name = _member_display_name(member)
            return {
                "name": name,
                "avatar": str(member.get("avatar", "") or ""),
                "gender": str(member.get("gender", "") or ""),
                "seed": profile_avatar_seed(user_id=member_id, username=str(member.get("username", "") or ""), display_name=name),
            }

        fallback_name = str(self._current_user.get("nickname", "") or self._current_user.get("username", "") or "").strip()
        fallback_id = announcement_author_id or self._current_user_id
        return {
            "name": fallback_name or tr("chat.group_announcement.author_unknown", "Unknown"),
            "avatar": str(self._current_user.get("avatar", "") or ""),
            "gender": str(self._current_user.get("gender", "") or ""),
            "seed": profile_avatar_seed(user_id=fallback_id, username=str(self._current_user.get("username", "") or ""), display_name=fallback_name),
        }

    def _enter_edit_mode(self) -> None:
        if not self._can_edit:
            return
        self.content_label.hide()
        self.content_editor.show()
        self.content_editor.setFocus()
        self.edit_button.hide()
        self.cancel_button.show()
        self.save_button.show()

    def _cancel_edit_mode(self) -> None:
        self.content_editor.setPlainText(self._original_announcement)
        self.content_editor.hide()
        self.content_label.show()
        self.edit_button.setVisible(self._can_edit)
        self.cancel_button.hide()
        self.save_button.hide()

    def _submit_edit(self) -> None:
        normalized = str(self.content_editor.toPlainText() or "").strip()
        if normalized == self._original_announcement:
            self.accept()
            return
        self._pending_announcement = normalized
        self.accept()

    def pending_announcement(self) -> str | None:
        """Return the edited announcement text when the dialog confirmed a save."""
        return self._pending_announcement

