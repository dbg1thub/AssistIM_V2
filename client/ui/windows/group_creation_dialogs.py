"""Shared dialogs for group creation flows."""

from __future__ import annotations

import asyncio
from typing import Optional

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    InfoBar,
    LineEdit,
    MaskDialogBase,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SearchLineEdit,
    SingleDirectionScrollArea,
    TitleLabel,
    isDarkTheme,
)

from client.core.i18n import tr
from client.core.logging import setup_logging
from client.core import logging
from client.ui.controllers.auth_controller import get_auth_controller
from client.ui.controllers.contact_controller import ContactRecord, GroupRecord
from client.ui.widgets.contact_shared import (
    ContactSectionHeader,
    GroupMemberItem,
    SelectableContactListItem,
    SelectedContactSummaryItem,
    apply_themed_dialog_surface,
    prepare_transparent_scroll_area,
)
from client.ui.widgets.fluent_divider import FluentDivider
from client.ui.widgets.fluent_splitter import FluentSplitter

setup_logging()
logger = logging.get_logger(__name__)


def enrich_created_group(group: GroupRecord, contacts: list[ContactRecord]) -> GroupRecord:
    """Attach one lightweight member preview to a newly created group without inventing avatar state."""
    preview = _build_group_member_preview(contacts)
    extra = dict(getattr(group, "extra", {}) or {})
    extra["member_preview"] = preview
    extra["member_previews"] = [item.get("name", "") for item in preview if item.get("name")]
    group.extra = extra
    return group


def _build_group_member_preview(contacts: list[ContactRecord]) -> list[dict[str, str]]:
    preview: list[dict[str, str]] = []
    current_user = get_auth_controller().current_user or {}
    current_user_id = str(current_user.get("id", "") or "")
    if current_user_id:
        preview.append(
            {
                "id": current_user_id,
                "name": str(current_user.get("nickname", "") or current_user.get("username", "") or current_user_id),
                "username": str(current_user.get("username", "") or ""),
                "avatar": str(current_user.get("avatar", "") or ""),
                "gender": str(current_user.get("gender", "") or ""),
            }
        )

    for contact in contacts:
        preview.append(
            {
                "id": contact.id,
                "name": contact.display_name,
                "username": contact.username,
                "avatar": contact.avatar,
                "gender": contact.gender,
            }
        )
    return preview


def _default_group_name_preview(contacts: list[ContactRecord]) -> str:
    names = [contact.display_name for contact in contacts if contact.display_name]
    if not names:
        return ""
    if len(names) <= 3:
        return "、".join(names)
    return "、".join(names[:3]) + "..."


class StartGroupChatDialog(MaskDialogBase):
    """Frameless modal used by private-chat info to start one new group chat."""

    group_created = Signal(object)

    def __init__(
        self,
        controller,
        contacts: list[ContactRecord],
        *,
        excluded_contact_id: str,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self._controller = controller
        self._excluded_contact_id = str(excluded_contact_id or "")
        self._contacts = [contact for contact in contacts if contact.id and contact.id != self._excluded_contact_id]
        self._selected_ids: set[str] = set()
        self._member_items: dict[str, SelectableContactListItem] = {}
        self._create_task: Optional[asyncio.Task] = None
        self._ui_tasks: set[asyncio.Task] = set()

        self.setModal(True)
        self.setObjectName("StartGroupChatDialog")
        self.widget.setObjectName("startGroupChatDialogWidget")
        self.widget.setFixedSize(700, 540)
        self._hBoxLayout.setContentsMargins(24, 24, 24, 24)
        self._hBoxLayout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setShadowEffect(68, (0, 18), QColor(0, 0, 0, 70))
        self.setMaskColor(QColor(0, 0, 0, 88))

        self._setup_ui()
        self._apply_styles()
        self._rebuild_member_list()
        self.finished.connect(self._on_finished)
        self.destroyed.connect(self._on_destroyed)

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self.widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.left_panel = QWidget(self.widget)
        self.left_panel.setObjectName("startGroupChatLeftPanel")
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self.search_bar = QWidget(self.left_panel)
        self.search_bar.setObjectName("sessionSearchBar")
        search_row = QHBoxLayout(self.search_bar)
        search_row.setContentsMargins(12, 12, 12, 12)
        search_row.setSpacing(12)

        self.search_edit = SearchLineEdit(self.search_bar)
        self.search_edit.setPlaceholderText(tr("chat.group_picker.search_placeholder", "Search"))
        self.search_edit.setFixedHeight(36)
        search_row.addWidget(self.search_edit, 1)

        self.list_area = SingleDirectionScrollArea(self.left_panel, orient=Qt.Orientation.Vertical)
        self.list_area.setWidgetResizable(True)
        self.list_area.setFrameShape(QFrame.Shape.NoFrame)
        self.list_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_area.setViewportMargins(0, 0, 0, 0)
        self.list_area.setObjectName("startGroupChatListArea")
        self.list_area.viewport().setObjectName("startGroupChatListViewport")

        self.list_container = QWidget(self.list_area)
        self.list_container.setObjectName("startGroupChatListContainer")
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        self.list_area.setWidget(self.list_container)

        left_layout.addWidget(self.search_bar, 0)
        left_layout.addWidget(self.list_area, 1)

        self.right_panel = QWidget(self.widget)
        self.right_panel.setObjectName("startGroupChatRightPanel")
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(20, 18, 20, 18)
        right_layout.setSpacing(12)

        self.title_label = BodyLabel(tr("chat.group_picker.title", "Start Group Chat"), self.right_panel)
        title_font = QFont(self.title_label.font())
        title_font.setPixelSize(18)
        title_font.setBold(False)
        self.title_label.setFont(title_font)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.status_label = CaptionLabel(tr("chat.group_picker.status_idle", "Select Contacts"), self.right_panel)
        self.status_label.setObjectName("startGroupChatStatusLabel")

        right_top_row = QHBoxLayout()
        right_top_row.setContentsMargins(0, 0, 0, 0)
        right_top_row.setSpacing(12)
        right_top_row.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        right_top_row.addStretch(1)
        right_top_row.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.selected_area = SingleDirectionScrollArea(self.right_panel, orient=Qt.Orientation.Vertical)
        self.selected_area.setWidgetResizable(True)
        self.selected_area.setFrameShape(QFrame.Shape.NoFrame)
        self.selected_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.selected_area.setViewportMargins(0, 0, 0, 0)
        self.selected_area.setObjectName("startGroupChatSelectedArea")
        self.selected_area.viewport().setObjectName("startGroupChatSelectedViewport")
        self.selected_area.setMinimumWidth(220)

        self.selected_container = QWidget(self.selected_area)
        self.selected_container.setObjectName("startGroupChatSelectedContainer")
        self.selected_layout = QVBoxLayout(self.selected_container)
        self.selected_layout.setContentsMargins(0, 0, 0, 0)
        self.selected_layout.setSpacing(0)
        self.selected_area.setWidget(self.selected_container)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(12)
        footer.addStretch(1)
        self.complete_button = PrimaryPushButton(tr("chat.group_picker.complete", "Done"), self.right_panel)
        self.cancel_button = PushButton(tr("common.cancel", "Cancel"), self.right_panel)
        self.complete_button.setFixedWidth(124)
        self.cancel_button.setFixedWidth(124)
        footer.addWidget(self.complete_button, 0)
        footer.addWidget(self.cancel_button, 0)

        right_layout.addLayout(right_top_row)
        right_layout.addWidget(self.selected_area, 1)
        right_layout.addLayout(footer)

        self.body_splitter = FluentSplitter(Qt.Orientation.Horizontal, self.widget)
        self.body_splitter.setObjectName("startGroupChatSplitter")
        self.body_splitter.setChildrenCollapsible(False)
        self.body_splitter.setHandleWidth(1)
        self.body_splitter.addWidget(self.left_panel)
        self.body_splitter.addWidget(self.right_panel)
        self.body_splitter.setStretchFactor(0, 11)
        self.body_splitter.setStretchFactor(1, 10)
        self.body_splitter.setSizes([350, 330])

        layout.addWidget(self.body_splitter, 1)

        self.search_edit.textChanged.connect(self._rebuild_member_list)
        self.complete_button.clicked.connect(self._create_group)
        self.cancel_button.clicked.connect(self.close)

    def _apply_styles(self) -> None:
        dark = isDarkTheme()
        border = "rgba(255, 255, 255, 28)" if dark else "rgba(15, 23, 42, 18)"
        background = "#262626" if dark else "#FFFFFF"
        status_color = "rgb(196, 196, 196)" if dark else "rgb(122, 122, 122)"
        self.setStyleSheet(
            f"""
            QFrame#startGroupChatDialogWidget {{
                background: {background};
                border: 1px solid {border};
                border-radius: 14px;
            }}
            QLabel#startGroupChatStatusLabel {{
                color: {status_color};
                font-size: 13px;
            }}
            QWidget#startGroupChatLeftPanel {{
                background: transparent;
            }}
            QWidget#startGroupChatListContainer {{
                background: transparent;
            }}
            QWidget#startGroupChatListViewport {{
                background: transparent;
            }}
            QWidget#startGroupChatRightPanel {{
                background: transparent;
            }}
            QWidget#startGroupChatSelectedContainer {{
                background: transparent;
            }}
            QWidget#startGroupChatSelectedViewport {{
                background: transparent;
            }}
            QAbstractScrollArea#startGroupChatListArea {{
                background: transparent;
                border: none;
            }}
            QAbstractScrollArea#startGroupChatSelectedArea {{
                background: transparent;
                border: none;
            }}
            QToolButton#startGroupChatSelectedRemoveButton {{
                background: transparent;
                border: none;
                border-radius: 14px;
                padding: 0;
            }}
            QToolButton#startGroupChatSelectedRemoveButton:hover {{
                background: rgba(127, 127, 127, 0.12);
            }}
            """
        )

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
            or keyword in str(contact.signature or "").lower()
        ]

        if not filtered:
            empty = BodyLabel(tr("contact.create_group.empty_results", "No matching friends."), self.list_container)
            empty.setObjectName("startGroupChatEmptyLabel")
            self.list_layout.addWidget(empty)
            self.list_layout.addStretch(1)
            self._update_footer()
            return

        grouped = self._controller.group_contacts(filtered)
        for letter, contacts in grouped.items():
            self.list_layout.addWidget(ContactSectionHeader(letter, self.list_container))
            for contact in contacts:
                item = SelectableContactListItem(contact, locked=False, parent=self.list_container)
                item.set_selected(contact.id in self._selected_ids)
                item.toggled.connect(self._toggle_member)
                self.list_layout.addWidget(item)
                self._member_items[contact.id] = item

        self.list_layout.addStretch(1)
        self._update_footer()

    def _toggle_member(self, contact_id: str, selected: bool) -> None:
        if self._create_task and not self._create_task.done():
            return
        if selected:
            self._selected_ids.add(contact_id)
        else:
            self._selected_ids.discard(contact_id)
        self._update_footer()

    def _remove_selected_member(self, contact_id: str) -> None:
        if self._create_task and not self._create_task.done():
            return
        if not contact_id:
            return
        self._selected_ids.discard(contact_id)
        member_item = self._member_items.get(contact_id)
        if member_item is not None:
            member_item.set_selected(False)
        self._update_footer()

    def _update_footer(self) -> None:
        selected_count = len(self._selected_ids)
        if selected_count > 0:
            self.status_label.setText(
                tr("chat.group_picker.status_selected", "{count} contacts selected", count=selected_count)
            )
        else:
            self.status_label.setText(tr("chat.group_picker.status_idle", "Select Contacts"))
        self._rebuild_selected_list()
        self.complete_button.setEnabled(selected_count > 0)

    def _selected_contacts(self) -> list[ContactRecord]:
        selected_ids = list(self._selected_ids)
        selected_contacts = [contact for contact in self._contacts if contact.id in selected_ids]
        selected_contacts.sort(key=lambda item: item.display_name.lower())
        return selected_contacts

    def _rebuild_selected_list(self) -> None:
        self._clear_layout(self.selected_layout)
        contacts = self._selected_contacts()
        for index, contact in enumerate(contacts):
            item = SelectedContactSummaryItem(contact, removable=True, parent=self.selected_container)
            item.remove_requested.connect(self._remove_selected_member)
            self.selected_layout.addWidget(item)
            if index != len(contacts) - 1:
                self.selected_layout.addWidget(
                    FluentDivider(
                        self.selected_container,
                        variant=FluentDivider.FULL,
                        left_inset=50,
                        right_inset=0,
                    )
                )
        self.selected_layout.addStretch(1)

    def _default_group_name(self) -> str:
        return _default_group_name_preview(self._selected_contacts()) or tr("chat.group_picker.default_name", "Group Chat")

    def _create_group(self) -> None:
        if self._create_task and not self._create_task.done():
            return
        if not self._selected_ids:
            InfoBar.warning(
                tr("chat.group_picker.title", "Start Group Chat"),
                tr("chat.group_picker.validation_members", "Select at least one contact."),
                parent=self,
                duration=1800,
            )
            return
        member_ids = [contact.id for contact in self._selected_contacts()]
        name = self._default_group_name()
        self._set_create_task(self._create_group_async(name, member_ids))

    async def _create_group_async(self, name: str, member_ids: list[str]) -> None:
        self.complete_button.setEnabled(False)
        self.search_edit.setEnabled(False)
        self.complete_button.setText(tr("chat.group_picker.creating", "Creating..."))
        try:
            group = await self._controller.create_group(name, list(dict.fromkeys(member_ids)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            InfoBar.error(
                tr("chat.group_picker.title", "Start Group Chat"),
                str(exc),
                parent=self,
                duration=2200,
            )
        else:
            selected_contacts = [contact for contact in self._contacts if contact.id in set(member_ids)]
            selected_contacts.sort(key=lambda item: item.display_name.lower())
            self.group_created.emit(enrich_created_group(group, selected_contacts))
            self.close()
        finally:
            self.complete_button.setEnabled(True)
            self.search_edit.setEnabled(True)
            self.complete_button.setText(tr("chat.group_picker.complete", "Done"))

    def _on_finished(self, _result: int) -> None:
        self._cancel_pending_task(self._create_task)
        self._create_task = None
        self._cancel_all_ui_tasks()

    def _on_destroyed(self, *_args) -> None:
        self._on_finished(0)

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
            logger.exception("StartGroupChatDialog task failed: %s", context)

    def _set_create_task(self, coro) -> None:
        self._cancel_pending_task(self._create_task)
        self._create_task = self._create_ui_task(coro, "start group chat", on_done=self._clear_create_task)

    def _clear_create_task(self, task: asyncio.Task) -> None:
        if self._create_task is task:
            self._create_task = None

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
        self._ui_tasks: set[asyncio.Task] = set()

        self.setWindowTitle(tr("contact.create_group.window_title", "Create Group"))
        self.setModal(True)
        self.resize(580, 720)
        apply_themed_dialog_surface(self, "CreateGroupDialog")

        self._setup_ui()
        self._rebuild_member_list()
        self.finished.connect(self._on_finished)
        self.destroyed.connect(self._on_destroyed)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        layout.addWidget(TitleLabel(tr("contact.create_group.title", "Create Group"), self))
        subtitle = CaptionLabel(
            tr(
                "contact.create_group.subtitle",
                "Select members from your current friends to create a new group session.",
            ),
            self,
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText(tr("contact.create_group.name_placeholder", "Enter group name"))
        self.name_edit.setMinimumHeight(38)
        layout.addWidget(self.name_edit)

        self.search_edit = SearchLineEdit(self)
        self.search_edit.setPlaceholderText(tr("contact.create_group.search_placeholder", "Filter friends"))
        self.search_edit.setMinimumHeight(38)
        layout.addWidget(self.search_edit)

        self.summary_label = CaptionLabel(
            tr("contact.create_group.summary_minimum", "Select at least one friend."),
            self,
        )
        self.summary_label.setObjectName("contactSummaryLabel")
        layout.addWidget(self.summary_label)

        self.member_area = ScrollArea(self)
        self.member_area.setWidgetResizable(True)
        self.member_area.setFrameShape(QFrame.Shape.NoFrame)
        self.member_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        prepare_transparent_scroll_area(self.member_area)
        self.member_container = QWidget(self.member_area)
        self.member_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.member_container.setAutoFillBackground(False)
        self.member_container.setStyleSheet("background: transparent; border: none;")
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
        self.cancel_button = PushButton(tr("common.cancel", "Cancel"), self)
        self.create_button = PrimaryPushButton(tr("contact.create_group.create", "Create Group"), self)
        footer.addWidget(self.cancel_button, 0)
        footer.addWidget(self.create_button, 0)
        layout.addLayout(footer)

        self.search_edit.textChanged.connect(self._rebuild_member_list)
        self.cancel_button.clicked.connect(self.close)
        self.create_button.clicked.connect(self._create_group)
        self._update_name_placeholder()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in {
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.StyleChange,
        }:
            apply_themed_dialog_surface(self, "CreateGroupDialog")

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
            or keyword in str(contact.assistim_id or "").lower()
            or keyword in contact.signature.lower()
        ]

        if not filtered:
            self.member_layout.addWidget(
                BodyLabel(tr("contact.create_group.empty_results", "No matching friends."), self.member_container)
            )
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
        if self._create_task and not self._create_task.done():
            return
        if selected:
            self._selected_ids.add(contact_id)
        else:
            self._selected_ids.discard(contact_id)
        self._update_summary()

    def _update_summary(self) -> None:
        self.summary_label.setText(
            tr("contact.create_group.summary_selected", "{count} friends selected", count=len(self._selected_ids))
        )
        self._update_name_placeholder()

    def _default_group_name(self) -> str:
        return _default_group_name_preview(self._selected_contacts())

    def _update_name_placeholder(self) -> None:
        generated_name = self._default_group_name()
        self.name_edit.setPlaceholderText(
            generated_name or tr("contact.create_group.name_placeholder", "Enter group name")
        )
    def _create_group(self) -> None:
        if self._create_task and not self._create_task.done():
            return

        name = self.name_edit.text().strip() or self._default_group_name() or tr("chat.group_picker.default_name", "Group Chat")
        if not self._selected_ids:
            InfoBar.warning(
                tr("contact.create_group.title", "Create Group"),
                tr("contact.create_group.validation_members", "Please select at least one friend."),
                parent=self,
                duration=1800,
            )
            return

        member_ids = [contact.id for contact in self._selected_contacts()]
        self._set_create_task(self._create_group_async(name, member_ids))

    async def _create_group_async(self, name: str, member_ids: list[str]) -> None:
        self.create_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.search_edit.setEnabled(False)
        self.name_edit.setEnabled(False)
        self.create_button.setText(tr("contact.create_group.creating", "Creating..."))
        try:
            group = await self._controller.create_group(name, list(dict.fromkeys(member_ids)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            InfoBar.error(tr("contact.create_group.title", "Create Group"), str(exc), parent=self, duration=2200)
        else:
            InfoBar.success(
                tr("contact.create_group.title", "Create Group"),
                tr("contact.create_group.success", "Group created."),
                parent=self,
                duration=1800,
            )
            self.group_created.emit(enrich_created_group(group, self._selected_contacts()))
            self.close()
        finally:
            self.create_button.setEnabled(True)
            self.cancel_button.setEnabled(True)
            self.search_edit.setEnabled(True)
            self.name_edit.setEnabled(True)
            self.create_button.setText(tr("contact.create_group.create", "Create Group"))

    def _selected_contacts(self) -> list[ContactRecord]:
        selected_contacts = [contact for contact in self._contacts if contact.id in self._selected_ids]
        selected_contacts.sort(key=lambda item: item.display_name.lower())
        return selected_contacts

    def _on_finished(self, _result: int) -> None:
        self._cancel_pending_task(self._create_task)
        self._create_task = None
        self._cancel_all_ui_tasks()

    def _on_destroyed(self, *_args) -> None:
        self._on_finished(0)

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
            logger.exception("CreateGroupDialog task failed: %s", context)

    def _set_create_task(self, coro) -> None:
        self._cancel_pending_task(self._create_task)
        self._create_task = self._create_ui_task(coro, "create group", on_done=self._clear_create_task)

    def _clear_create_task(self, task: asyncio.Task) -> None:
        if self._create_task is task:
            self._create_task = None

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()




