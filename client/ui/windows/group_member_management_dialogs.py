"""Formal group-member management dialogs used by chat info flows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QDialog, QFrame, QSizePolicy, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    HyperlinkButton,
    InfoBar,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    SingleDirectionScrollArea,
    isDarkTheme,
)

from client.core import logging
from client.core.i18n import tr
from client.core.logging import setup_logging
from client.ui.controllers.contact_controller import ContactController, ContactRecord, GroupRecord
from client.ui.widgets.contact_shared import (
    ContactAvatar,
    ElidedBodyLabel,
    ElidedCaptionLabel,
    SelectableContactListItem,
    apply_themed_dialog_surface,
    prepare_transparent_scroll_area,
)
from client.ui.widgets.fluent_divider import FluentDivider

setup_logging()
logger = logging.get_logger(__name__)


def _member_display_name(member: dict[str, object]) -> str:
    return (
        str(member.get("remark", "") or "").strip()
        or str(member.get("group_nickname", "") or "").strip()
        or str(member.get("nickname", "") or "").strip()
        or str(member.get("display_name", "") or "").strip()
        or str(member.get("username", "") or "").strip()
        or str(member.get("id", "") or "").strip()
        or tr("session.unnamed", "Untitled Session")
    )


def _member_role(member: dict[str, object], owner_id: str) -> str:
    role = str(member.get("role", "") or "").strip().lower()
    if role:
        return role
    member_id = str(member.get("id", "") or member.get("user_id", "") or "").strip()
    return "owner" if member_id and member_id == owner_id else "member"


def _member_sort_key(member: dict[str, object], owner_id: str) -> tuple[int, str]:
    role = _member_role(member, owner_id)
    role_rank = {"owner": 0, "admin": 1, "member": 2}.get(role, 3)
    return role_rank, _member_display_name(member).lower()


def _member_subtitle(member: dict[str, object]) -> str:
    return (
        str(member.get("username", "") or "").strip()
        or str(member.get("assistim_id", "") or "").strip()
        or str(member.get("id", "") or "").strip()
    )


def _role_label(role: str) -> str:
    return {
        "owner": tr("chat.group.manage.role.owner", "Owner"),
        "admin": tr("chat.group.manage.role.admin", "Admin"),
        "member": tr("chat.group.manage.role.member", "Member"),
    }.get(role, tr("chat.group.manage.role.member", "Member"))


def _apply_management_dialog_styles(widget: QWidget) -> None:
    border = "rgba(255, 255, 255, 28)" if isDarkTheme() else "rgba(15, 23, 42, 18)"
    role_bg = "rgba(94, 146, 255, 0.18)" if isDarkTheme() else "rgba(65, 124, 255, 0.12)"
    row_hover = "rgba(255, 255, 255, 0.06)" if isDarkTheme() else "rgba(0, 0, 0, 0.04)"
    action_color = "rgb(91, 156, 255)" if isDarkTheme() else "rgb(38, 101, 213)"
    widget.setStyleSheet(
        f"""
        QWidget#groupMemberManageContent,
        QWidget#groupMemberPickerContent {{
            border: 1px solid {border};
            border-radius: 14px;
        }}
        QWidget#groupMemberManageListViewport,
        QWidget#groupMemberPickerListViewport {{
            background: transparent;
        }}
        QWidget#groupMemberManageRow {{
            background: transparent;
            border-radius: 12px;
        }}
        QWidget#groupMemberManageRow:hover {{
            background: {row_hover};
        }}
        QLabel#groupMemberManageRoleBadge {{
            padding: 2px 8px;
            border-radius: 10px;
            background: {role_bg};
            color: {action_color};
        }}
        QPushButton#groupMemberManageAction {{
            background: transparent;
            border: none;
            color: {action_color};
            padding: 0 2px;
        }}
        QPushButton#groupMemberManageAction:hover,
        QPushButton#groupMemberManageAction:pressed {{
            background: transparent;
            border: none;
            color: {action_color};
        }}
        """
    )


@dataclass(frozen=True)
class GroupManagementPermissions:
    """Permission snapshot derived from the current user's role."""

    current_user_id: str
    current_user_role: str
    can_add_members: bool
    can_manage_member_roles: bool
    can_transfer_owner: bool

    @classmethod
    def from_group(cls, group: GroupRecord, *, current_user_id: str) -> "GroupManagementPermissions":
        owner_id = str(group.owner_id or "").strip()
        members = list((group.extra or {}).get("members") or [])
        current_role = "member"
        if current_user_id and current_user_id == owner_id:
            current_role = "owner"
        else:
            for member in members:
                if str(member.get("id", "") or member.get("user_id", "") or "").strip() != current_user_id:
                    continue
                current_role = _member_role(member, owner_id)
                break
        is_owner = current_role == "owner"
        return cls(
            current_user_id=current_user_id,
            current_user_role=current_role,
            can_add_members=is_owner,
            can_manage_member_roles=is_owner,
            can_transfer_owner=is_owner,
        )

    def can_manage_member(self, member: dict[str, object], *, owner_id: str) -> bool:
        target_id = str(member.get("id", "") or member.get("user_id", "") or "").strip()
        target_role = _member_role(member, owner_id)
        return self.can_manage_member_roles and bool(target_id) and target_id != self.current_user_id and target_role != "owner"

    def can_transfer_to(self, member: dict[str, object], *, owner_id: str) -> bool:
        if not self.can_transfer_owner:
            return False
        target_id = str(member.get("id", "") or member.get("user_id", "") or "").strip()
        target_role = _member_role(member, owner_id)
        return bool(target_id) and target_id != self.current_user_id and target_role != "owner"


class GroupMemberActionConfirmDialog(MessageBoxBase):
    """Simple confirm dialog for destructive member-management actions."""

    def __init__(self, title: str, content: str, action_text: str, parent=None) -> None:
        super().__init__(parent=parent)
        heading = BodyLabel(title, self.widget)
        heading_font = QFont(heading.font())
        heading_font.setPixelSize(16)
        heading.setFont(heading_font)
        description = CaptionLabel(content, self.widget)
        description.setWordWrap(True)
        self.viewLayout.addWidget(heading)
        self.viewLayout.addWidget(description)
        self.viewLayout.addStretch(1)
        self.yesButton.setText(action_text)
        self.cancelButton.setText(tr("common.cancel", "Cancel"))
        self.widget.setMinimumWidth(380)


class GroupMemberPickerDialog(QDialog):
    """Select contacts to add into one existing group."""

    def __init__(self, contacts: list[ContactRecord], parent=None) -> None:
        super().__init__(parent)
        self._contacts = list(contacts)
        self._selected_ids: set[str] = set()
        self._member_items: dict[str, SelectableContactListItem] = {}

        self.setWindowTitle(tr("chat.group.manage.add.title", "Add Group Members"))
        self.setModal(True)
        self.resize(520, 620)
        apply_themed_dialog_surface(self, "GroupMemberPickerDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        self.content = QWidget(self)
        self.content.setObjectName("groupMemberPickerContent")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(18, 18, 18, 18)
        content_layout.setSpacing(12)

        title = BodyLabel(tr("chat.group.manage.add.title", "Add Group Members"), self.content)
        title_font = QFont(title.font())
        title_font.setPixelSize(18)
        title.setFont(title_font)
        self.summary_label = CaptionLabel(tr("chat.group.manage.add.idle", "Select friends to add to this group."), self.content)

        self.search_edit = SearchLineEdit(self.content)
        self.search_edit.setPlaceholderText(tr("chat.group.manage.add.search_placeholder", "Search friends"))
        self.search_edit.setFixedHeight(36)

        self.list_area = SingleDirectionScrollArea(self.content, orient=Qt.Orientation.Vertical)
        self.list_area.setObjectName("groupMemberPickerListArea")
        self.list_area.viewport().setObjectName("groupMemberPickerListViewport")
        self.list_area.setWidgetResizable(True)
        self.list_area.setFrameShape(QFrame.Shape.NoFrame)
        self.list_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        prepare_transparent_scroll_area(self.list_area)

        self.list_container = QWidget(self.list_area)
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        self.list_area.setWidget(self.list_container)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(10)
        footer.addStretch(1)
        self.cancel_button = PushButton(tr("common.cancel", "Cancel"), self.content)
        self.confirm_button = PrimaryPushButton(tr("chat.group.manage.add.action", "Add"), self.content)
        self.confirm_button.setEnabled(False)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.confirm_button)

        content_layout.addWidget(title)
        content_layout.addWidget(self.summary_label)
        content_layout.addWidget(self.search_edit)
        content_layout.addWidget(self.list_area, 1)
        content_layout.addLayout(footer)
        root.addWidget(self.content, 1)

        self.search_edit.textChanged.connect(self._rebuild_member_list)
        self.cancel_button.clicked.connect(self.reject)
        self.confirm_button.clicked.connect(self.accept)
        self._rebuild_member_list()
        _apply_management_dialog_styles(self)

    def selected_member_ids(self) -> list[str]:
        """Return the currently selected contact ids."""
        return sorted(self._selected_ids)

    def _toggle_member(self, contact_id: str, selected: bool) -> None:
        if selected:
            self._selected_ids.add(contact_id)
        else:
            self._selected_ids.discard(contact_id)
        self.summary_label.setText(
            tr("chat.group.manage.add.selected", "{count} friends selected", count=len(self._selected_ids))
            if self._selected_ids
            else tr("chat.group.manage.add.idle", "Select friends to add to this group.")
        )
        self.confirm_button.setEnabled(bool(self._selected_ids))

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _rebuild_member_list(self) -> None:
        self._clear_layout(self.list_layout)
        self._member_items.clear()

        keyword = self.search_edit.text().strip().lower()
        filtered = [
            contact
            for contact in self._contacts
            if not keyword
            or keyword in str(contact.display_name or "").lower()
            or keyword in str(contact.username or "").lower()
            or keyword in str(contact.assistim_id or "").lower()
        ]

        if not filtered:
            empty = CaptionLabel(tr("chat.group.manage.add.empty", "No friends available to add."), self.list_container)
            empty.setWordWrap(True)
            self.list_layout.addWidget(empty)
            self.list_layout.addStretch(1)
            return

        for index, contact in enumerate(filtered):
            item = SelectableContactListItem(contact, locked=False, parent=self.list_container)
            item.set_selected(contact.id in self._selected_ids)
            item.toggled.connect(self._toggle_member)
            self.list_layout.addWidget(item)
            self._member_items[contact.id] = item
            if index != len(filtered) - 1:
                self.list_layout.addWidget(
                    FluentDivider(
                        self.list_container,
                        variant=FluentDivider.FULL,
                        left_inset=52,
                        right_inset=0,
                    )
                )
        self.list_layout.addStretch(1)


class GroupMemberManageRow(QWidget):
    """One member row shown inside the management dialog."""

    promoteRequested = Signal(str)
    demoteRequested = Signal(str)
    transferRequested = Signal(str)
    removeRequested = Signal(str)

    def __init__(
        self,
        member: dict[str, object],
        *,
        owner_id: str,
        permissions: GroupManagementPermissions,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._member = dict(member or {})
        self._owner_id = str(owner_id or "")
        self._permissions = permissions
        self._member_id = str(self._member.get("id", "") or self._member.get("user_id", "") or "").strip()
        self._member_role = _member_role(self._member, self._owner_id)

        self.setObjectName("groupMemberManageRow")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        self.avatar = ContactAvatar(42, self)
        self.avatar.set_avatar(
            str(self._member.get("avatar", "") or ""),
            _member_display_name(self._member),
            gender=str(self._member.get("gender", "") or ""),
            seed=str(self._member_id or ""),
        )

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)

        self.name_label = ElidedBodyLabel(_member_display_name(self._member), self)
        self.subtitle_label = ElidedCaptionLabel(_member_subtitle(self._member), self)
        self.subtitle_label.setVisible(bool(_member_subtitle(self._member)))

        text_layout.addWidget(self.name_label)
        text_layout.addWidget(self.subtitle_label)

        self.role_label = CaptionLabel(_role_label(self._member_role), self)
        self.role_label.setObjectName("groupMemberManageRoleBadge")

        self.actions_widget = QWidget(self)
        actions_layout = QHBoxLayout(self.actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)

        self.promote_button = HyperlinkButton(parent=self.actions_widget)
        self.promote_button.setObjectName("groupMemberManageAction")
        self.promote_button.setText(tr("chat.group.manage.action.promote", "Set Admin"))
        self.promote_button.clicked.connect(lambda: self.promoteRequested.emit(self._member_id))

        self.demote_button = HyperlinkButton(parent=self.actions_widget)
        self.demote_button.setObjectName("groupMemberManageAction")
        self.demote_button.setText(tr("chat.group.manage.action.demote", "Demote"))
        self.demote_button.clicked.connect(lambda: self.demoteRequested.emit(self._member_id))

        self.transfer_button = HyperlinkButton(parent=self.actions_widget)
        self.transfer_button.setObjectName("groupMemberManageAction")
        self.transfer_button.setText(tr("chat.group.manage.action.transfer", "Transfer"))
        self.transfer_button.clicked.connect(lambda: self.transferRequested.emit(self._member_id))

        self.remove_button = HyperlinkButton(parent=self.actions_widget)
        self.remove_button.setObjectName("groupMemberManageAction")
        self.remove_button.setText(tr("chat.group.manage.action.remove", "Remove"))
        self.remove_button.clicked.connect(lambda: self.removeRequested.emit(self._member_id))

        for button in (self.promote_button, self.demote_button, self.transfer_button, self.remove_button):
            actions_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(text_layout, 1)
        layout.addWidget(self.role_label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.actions_widget, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._apply_permissions()

    def _apply_permissions(self) -> None:
        can_manage = self._permissions.can_manage_member(self._member, owner_id=self._owner_id)
        can_transfer = self._permissions.can_transfer_to(self._member, owner_id=self._owner_id)

        self.promote_button.setVisible(can_manage and self._member_role == "member")
        self.demote_button.setVisible(can_manage and self._member_role == "admin")
        self.transfer_button.setVisible(can_transfer)
        self.remove_button.setVisible(can_manage)
        self.actions_widget.setVisible(
            self.promote_button.isVisible()
            or self.demote_button.isVisible()
            or self.transfer_button.isVisible()
            or self.remove_button.isVisible()
        )


class GroupMemberManagementDialog(QDialog):
    """Formal member-management dialog for one group."""

    groupRecordChanged = Signal(object)

    def __init__(
        self,
        controller: ContactController,
        *,
        group_id: str,
        session_id: str,
        preferred_mode: str = "browse",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._group_id = str(group_id or "").strip()
        self._session_id = str(session_id or "").strip()
        self._preferred_mode = str(preferred_mode or "browse").strip().lower()
        self._group_record: GroupRecord | None = None
        self._contacts_cache: list[ContactRecord] | None = None
        self._load_task: Optional[asyncio.Task] = None
        self._mutation_task: Optional[asyncio.Task] = None
        self._ui_tasks: set[asyncio.Task] = set()
        self._initial_mode_consumed = False

        self.setWindowTitle(tr("chat.group.manage.title", "Group Members"))
        self.setModal(False)
        self.resize(720, 620)
        apply_themed_dialog_surface(self, "GroupMemberManagementDialog")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(0)

        self.content = QWidget(self)
        self.content.setObjectName("groupMemberManageContent")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(18, 18, 18, 18)
        content_layout.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)

        header_text = QVBoxLayout()
        header_text.setContentsMargins(0, 0, 0, 0)
        header_text.setSpacing(4)
        self.title_label = BodyLabel(tr("chat.group.manage.title", "Group Members"), self.content)
        title_font = QFont(self.title_label.font())
        title_font.setPixelSize(18)
        self.title_label.setFont(title_font)
        self.summary_label = CaptionLabel(tr("chat.group.manage.loading", "Loading group members..."), self.content)
        header_text.addWidget(self.title_label)
        header_text.addWidget(self.summary_label)

        self.add_button = PrimaryPushButton(tr("chat.group.manage.add.action", "Add Members"), self.content)
        self.add_button.setFixedHeight(34)

        header_row.addLayout(header_text, 1)
        header_row.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        self.search_edit = SearchLineEdit(self.content)
        self.search_edit.setPlaceholderText(tr("chat.group.manage.search_placeholder", "Search members"))
        self.search_edit.setFixedHeight(36)

        self.permission_label = CaptionLabel("", self.content)
        self.permission_label.setWordWrap(True)

        self.list_area = SingleDirectionScrollArea(self.content, orient=Qt.Orientation.Vertical)
        self.list_area.setObjectName("groupMemberManageListArea")
        self.list_area.viewport().setObjectName("groupMemberManageListViewport")
        self.list_area.setWidgetResizable(True)
        self.list_area.setFrameShape(QFrame.Shape.NoFrame)
        self.list_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        prepare_transparent_scroll_area(self.list_area)

        self.list_container = QWidget(self.list_area)
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        self.list_area.setWidget(self.list_container)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(10)
        footer.addStretch(1)
        self.close_button = PushButton(tr("common.close", "Close"), self.content)
        footer.addWidget(self.close_button)

        content_layout.addLayout(header_row)
        content_layout.addWidget(self.search_edit)
        content_layout.addWidget(self.permission_label)
        content_layout.addWidget(self.list_area, 1)
        content_layout.addLayout(footer)
        root.addWidget(self.content, 1)

        self.add_button.clicked.connect(self._open_add_members_dialog)
        self.search_edit.textChanged.connect(self._rebuild_member_list)
        self.close_button.clicked.connect(self.close)
        self.finished.connect(self._on_finished)
        self.destroyed.connect(self._on_destroyed)
        _apply_management_dialog_styles(self)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._group_record is None and self._load_task is None:
            self._set_load_task(self._reload_group_async())

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in {
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.StyleChange,
        }:
            apply_themed_dialog_surface(self, "GroupMemberManagementDialog")
            _apply_management_dialog_styles(self)

    def _current_user_id(self) -> str:
        return self._controller.get_current_user_id()

    def _permissions(self) -> GroupManagementPermissions:
        if self._group_record is None:
            return GroupManagementPermissions(
                current_user_id=self._current_user_id(),
                current_user_role="member",
                can_add_members=False,
                can_manage_member_roles=False,
                can_transfer_owner=False,
            )
        return GroupManagementPermissions.from_group(self._group_record, current_user_id=self._current_user_id())

    def _members(self) -> list[dict[str, object]]:
        if self._group_record is None:
            return []
        owner_id = str(self._group_record.owner_id or "")
        members = [
            dict(item or {})
            for item in list((self._group_record.extra or {}).get("members") or [])
            if isinstance(item, dict)
        ]
        members.sort(key=lambda item: _member_sort_key(item, owner_id))
        return members

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self.add_button.setEnabled(not busy and self._permissions().can_add_members)
        self.search_edit.setEnabled(not busy)
        if message:
            self.summary_label.setText(message)

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _permission_summary_text(self, permissions: GroupManagementPermissions) -> str:
        if permissions.current_user_role == "owner":
            return tr(
                "chat.group.manage.permission.owner",
                "You can add members, remove non-owners, manage admin roles, and transfer ownership.",
            )
        if permissions.current_user_role == "admin":
            return tr(
                "chat.group.manage.permission.admin",
                "You can view the full member list. Member management remains owner-only.",
            )
        return tr(
            "chat.group.manage.permission.member",
            "You can view the full member list. Member management remains owner-only.",
        )

    def _apply_group_record(self, group: GroupRecord) -> None:
        self._group_record = group
        permissions = self._permissions()
        self.title_label.setText(
            tr(
                "chat.group.manage.title_named",
                "Group Members · {name}",
                name=group.name or tr("session.unnamed", "Untitled Session"),
            )
        )
        self.summary_label.setText(
            tr(
                "chat.group.manage.summary",
                "{count} members",
                count=len(self._members()),
            )
        )
        self.permission_label.setText(self._permission_summary_text(permissions))
        self.add_button.setVisible(permissions.can_add_members)
        self.add_button.setEnabled(permissions.can_add_members)
        self._rebuild_member_list()
        self.groupRecordChanged.emit(group)

        if not self._initial_mode_consumed:
            self._initial_mode_consumed = True
            if self._preferred_mode == "add" and permissions.can_add_members:
                QTimer.singleShot(0, self._open_add_members_dialog)

    def _rebuild_member_list(self) -> None:
        self._clear_layout(self.list_layout)
        if self._group_record is None:
            loading = CaptionLabel(tr("chat.group.manage.loading", "Loading group members..."), self.list_container)
            loading.setWordWrap(True)
            self.list_layout.addWidget(loading)
            self.list_layout.addStretch(1)
            return

        owner_id = str(self._group_record.owner_id or "")
        permissions = self._permissions()
        keyword = self.search_edit.text().strip().lower()
        members = [
            member
            for member in self._members()
            if not keyword
            or keyword in _member_display_name(member).lower()
            or keyword in _member_subtitle(member).lower()
        ]

        if not members:
            empty = CaptionLabel(tr("chat.group.manage.empty", "No matching members."), self.list_container)
            empty.setWordWrap(True)
            self.list_layout.addWidget(empty)
            self.list_layout.addStretch(1)
            return

        for index, member in enumerate(members):
            row = GroupMemberManageRow(member, owner_id=owner_id, permissions=permissions, parent=self.list_container)
            row.promoteRequested.connect(self._promote_member)
            row.demoteRequested.connect(self._demote_member)
            row.transferRequested.connect(self._transfer_owner)
            row.removeRequested.connect(self._remove_member)
            self.list_layout.addWidget(row)
            if index != len(members) - 1:
                self.list_layout.addWidget(
                    FluentDivider(
                        self.list_container,
                        variant=FluentDivider.FULL,
                        left_inset=54,
                        right_inset=0,
                    )
                )
        self.list_layout.addStretch(1)

    async def _reload_group_async(self) -> None:
        self._set_busy(True, tr("chat.group.manage.loading", "Loading group members..."))
        try:
            record = await self._controller.fetch_group(self._group_id)
        except Exception as exc:
            InfoBar.error(
                tr("chat.group.manage.title", "Group Members"),
                str(exc),
                parent=self.window(),
                duration=2400,
            )
            self._set_busy(False, tr("chat.group.manage.load_failed", "Unable to load group members right now."))
            return
        self._set_busy(False)
        self._apply_group_record(record)

    async def _ensure_contacts_cache(self) -> list[ContactRecord]:
        self._contacts_cache = await self._controller.load_contacts()
        return list(self._contacts_cache)

    def _open_add_members_dialog(self) -> None:
        if self._mutation_task and not self._mutation_task.done():
            return
        if not self._permissions().can_add_members or self._group_record is None:
            return
        self._set_mutation_task(self._open_add_members_dialog_async())

    async def _open_add_members_dialog_async(self) -> None:
        try:
            contacts = await self._ensure_contacts_cache()
        except Exception as exc:
            InfoBar.error(
                tr("chat.group.manage.add.title", "Add Group Members"),
                str(exc),
                parent=self.window(),
                duration=2400,
            )
            return
        existing_ids = {
            str(member.get("id", "") or member.get("user_id", "") or "").strip()
            for member in self._members()
        }
        candidates = [contact for contact in contacts if contact.id and contact.id not in existing_ids]
        if not candidates:
            InfoBar.info(
                tr("chat.group.manage.add.title", "Add Group Members"),
                tr("chat.group.manage.add.no_candidates", "There are no additional friends available to add."),
                parent=self.window(),
                duration=2200,
            )
            return

        dialog = GroupMemberPickerDialog(candidates, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        member_ids = dialog.selected_member_ids()
        if not member_ids:
            return
        self._set_mutation_task(self._add_members_async(member_ids))

    async def _add_members_async(self, member_ids: list[str]) -> None:
        self._set_busy(True, tr("chat.group.manage.add.progress", "Adding members..."))
        try:
            latest_record: GroupRecord | None = None
            for member_id in member_ids:
                latest_record = await self._controller.add_group_member(self._group_id, member_id)
            if latest_record is None:
                latest_record = await self._controller.fetch_group(self._group_id)
        except Exception as exc:
            InfoBar.error(
                tr("chat.group.manage.add.title", "Add Group Members"),
                str(exc),
                parent=self.window(),
                duration=2400,
            )
        else:
            self._apply_group_record(latest_record)
            InfoBar.success(
                tr("chat.group.manage.add.title", "Add Group Members"),
                tr("chat.group.manage.add.success", "Members added."),
                parent=self.window(),
                duration=1800,
            )
        finally:
            self._set_busy(False)

    def _find_member(self, user_id: str) -> dict[str, object] | None:
        for member in self._members():
            member_id = str(member.get("id", "") or member.get("user_id", "") or "").strip()
            if member_id == str(user_id or "").strip():
                return member
        return None

    def _promote_member(self, user_id: str) -> None:
        if self._mutation_task and not self._mutation_task.done():
            return
        self._set_mutation_task(self._update_member_role_async(user_id, role="admin"))

    def _demote_member(self, user_id: str) -> None:
        if self._mutation_task and not self._mutation_task.done():
            return
        self._set_mutation_task(self._update_member_role_async(user_id, role="member"))

    async def _update_member_role_async(self, user_id: str, *, role: str) -> None:
        self._set_busy(True, tr("chat.group.manage.role.progress", "Updating member role..."))
        try:
            record = await self._controller.update_group_member_role(self._group_id, user_id, role=role)
        except Exception as exc:
            InfoBar.error(
                tr("chat.group.manage.title", "Group Members"),
                str(exc),
                parent=self.window(),
                duration=2400,
            )
        else:
            self._apply_group_record(record)
            InfoBar.success(
                tr("chat.group.manage.title", "Group Members"),
                tr("chat.group.manage.role.success", "Member role updated."),
                parent=self.window(),
                duration=1800,
            )
        finally:
            self._set_busy(False)

    def _remove_member(self, user_id: str) -> None:
        if self._mutation_task and not self._mutation_task.done():
            return
        member = self._find_member(user_id)
        if member is None:
            return
        dialog = GroupMemberActionConfirmDialog(
            tr("chat.group.manage.remove.title", "Remove Member"),
            tr(
                "chat.group.manage.remove.confirm",
                "Remove {name} from this group?",
                name=_member_display_name(member),
            ),
            tr("chat.group.manage.action.remove", "Remove"),
            self.window(),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._set_mutation_task(self._remove_member_async(user_id))

    async def _remove_member_async(self, user_id: str) -> None:
        self._set_busy(True, tr("chat.group.manage.remove.progress", "Removing member..."))
        try:
            record = await self._controller.remove_group_member(self._group_id, user_id)
        except Exception as exc:
            InfoBar.error(
                tr("chat.group.manage.remove.title", "Remove Member"),
                str(exc),
                parent=self.window(),
                duration=2400,
            )
        else:
            self._apply_group_record(record)
            InfoBar.success(
                tr("chat.group.manage.remove.title", "Remove Member"),
                tr("chat.group.manage.remove.success", "Member removed."),
                parent=self.window(),
                duration=1800,
            )
        finally:
            self._set_busy(False)

    def _transfer_owner(self, user_id: str) -> None:
        if self._mutation_task and not self._mutation_task.done():
            return
        member = self._find_member(user_id)
        if member is None:
            return
        dialog = GroupMemberActionConfirmDialog(
            tr("chat.group.manage.transfer.title", "Transfer Ownership"),
            tr(
                "chat.group.manage.transfer.confirm",
                "Transfer ownership to {name}? You will become a regular member.",
                name=_member_display_name(member),
            ),
            tr("chat.group.manage.action.transfer", "Transfer"),
            self.window(),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._set_mutation_task(self._transfer_owner_async(user_id))

    async def _transfer_owner_async(self, user_id: str) -> None:
        self._set_busy(True, tr("chat.group.manage.transfer.progress", "Transferring ownership..."))
        try:
            record = await self._controller.transfer_group_ownership(self._group_id, user_id)
        except Exception as exc:
            InfoBar.error(
                tr("chat.group.manage.transfer.title", "Transfer Ownership"),
                str(exc),
                parent=self.window(),
                duration=2400,
            )
        else:
            self._apply_group_record(record)
            InfoBar.success(
                tr("chat.group.manage.transfer.title", "Transfer Ownership"),
                tr("chat.group.manage.transfer.success", "Ownership transferred."),
                parent=self.window(),
                duration=1800,
            )
        finally:
            self._set_busy(False)

    def _cancel_pending_task(self, task: Optional[asyncio.Task]) -> None:
        if task is not None and not task.done():
            task.cancel()

    def _cancel_all_ui_tasks(self) -> None:
        for task in list(self._ui_tasks):
            if not task.done():
                task.cancel()

    def _create_ui_task(self, coro, context: str, *, on_done=None) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._ui_tasks.add(task)
        task.add_done_callback(lambda finished, name=context, callback=on_done: self._finalize_ui_task(finished, name, callback))
        return task

    def _finalize_ui_task(self, task: asyncio.Task, context: str, on_done=None) -> None:
        self._ui_tasks.discard(task)
        if on_done is not None:
            on_done(task)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("GroupMemberManagementDialog task failed: %s", context)

    def _set_load_task(self, coro) -> None:
        self._cancel_pending_task(self._load_task)
        self._load_task = self._create_ui_task(coro, "load group members", on_done=self._clear_load_task)

    def _clear_load_task(self, task: asyncio.Task) -> None:
        if self._load_task is task:
            self._load_task = None

    def _set_mutation_task(self, coro) -> None:
        if self._mutation_task and not self._mutation_task.done():
            return
        self._mutation_task = self._create_ui_task(coro, "mutate group members", on_done=self._clear_mutation_task)

    def _clear_mutation_task(self, task: asyncio.Task) -> None:
        if self._mutation_task is task:
            self._mutation_task = None

    def _on_finished(self, _result: int) -> None:
        self._cancel_pending_task(self._load_task)
        self._load_task = None
        self._cancel_pending_task(self._mutation_task)
        self._mutation_task = None
        self._cancel_all_ui_tasks()

    def _on_destroyed(self, *_args) -> None:
        self._on_finished(0)
