"""Quick user-profile flyout and profile actions for the main window."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Optional

from PySide6.QtCore import QDate, QEvent, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    AvatarWidget,
    BodyLabel,
    CaptionLabel,
    FlyoutAnimationType,
    HyperlinkLabel,
    InfoBar,
    LineEdit,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    isDarkTheme,
)
from qfluentwidgets.components.material import AcrylicFlyout, AcrylicFlyoutViewBase

from client.core import logging
from client.core.avatar_rendering import apply_avatar_widget_image
from client.core.avatar_utils import profile_avatar_seed
from client.core.i18n import tr
from client.core.logging import setup_logging
from client.core.profile_fields import (
    normalize_profile_choice,
    normalize_profile_gender,
    profile_gender_options,
    profile_status_options,
    qdate_from_profile_birthday,
)
from client.ui.controllers.auth_controller import get_auth_controller
from client.ui.widgets.fluent_divider import FluentDivider


setup_logging()
logger = logging.get_logger(__name__)

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9()\-\.\s]{5,31}$")
_EMPTY_BIRTHDAY = QDate(1900, 1, 1)


def _apply_themed_dialog_surface(dialog: QDialog, object_name: str, *, radius: int = 14) -> None:
    """Apply one stable theme-aware palette to profile dialogs."""
    dialog.setObjectName(object_name)
    dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    dialog.setAutoFillBackground(True)
    background = QColor(39, 43, 48) if isDarkTheme() else QColor(255, 255, 255)
    palette = dialog.palette()
    palette.setColor(QPalette.ColorRole.Window, background)
    palette.setColor(QPalette.ColorRole.Base, background)
    dialog.setPalette(palette)


def _avatar_initials(name: str) -> str:
    text = (name or "").strip()
    if not text:
        return "?"
    return text[:1].upper()


def _display_name(user: dict) -> str:
    return (
        str(user.get("nickname", "") or "")
        or str(user.get("username", "") or "")
        or tr("common.app_name", "AssistIM")
    )


def _assistim_id(user: dict, *, default: str = "") -> str:
    return str(user.get("username", "") or user.get("id", "") or default)


def _set_avatar_widget(
    widget: AvatarWidget,
    avatar_path: str = "",
    *,
    fallback: str = "",
    gender: str = "",
    seed: str = "",
) -> None:
    """Apply one avatar image or initials fallback to a Fluent AvatarWidget."""
    if apply_avatar_widget_image(widget, avatar_path, gender=gender, seed=seed):
        return

    widget.setImage(None)
    widget.setText(_avatar_initials(fallback))


class LogoutConfirmDialog(MessageBoxBase):
    """Ask for confirmation before logging out."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        title = SubtitleLabel(tr("profile.logout.confirm_title", "Sign Out"), self.widget)
        content = BodyLabel(
            tr("profile.logout.confirm_content", "Sign out of the current account and return to the login window?"),
            self.widget,
        )
        content.setWordWrap(True)
        self.viewLayout.addWidget(title)
        self.viewLayout.addWidget(content)
        self.viewLayout.addStretch(1)
        self.yesButton.setText(tr("profile.logout.confirm_action", "Sign Out"))
        self.cancelButton.setText(tr("common.cancel", "Cancel"))
        self.widget.setMinimumWidth(360)


class ProfileEditDialog(QDialog):
    """Profile editor for public identity fields."""

    def __init__(self, user: dict, parent=None):
        super().__init__(parent)
        self._user = dict(user or {})
        self._avatar_file_path = ""
        self._reset_avatar_requested = False

        self.setWindowTitle(tr("profile.edit.window_title", "Edit Profile"))
        self.setMinimumWidth(520)
        self.setModal(True)
        _apply_themed_dialog_surface(self, "ProfileEditDialog")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = SubtitleLabel(tr("profile.edit.title", "Edit Profile"), self)
        subtitle = CaptionLabel(
            tr("profile.edit.subtitle", "Update your public nickname, avatar, and profile details."),
            self,
        )
        subtitle.setWordWrap(True)

        seed = profile_avatar_seed(
            user_id=self._user.get("id"),
            username=self._user.get("username"),
            display_name=self._user.get("nickname"),
        )
        self.avatar_preview = AvatarWidget(self)
        self.avatar_preview.setRadius(40)
        _set_avatar_widget(
            self.avatar_preview,
            str(self._user.get("avatar", "") or ""),
            fallback=_display_name(self._user),
            gender=str(self._user.get("gender", "") or ""),
            seed=seed,
        )

        self.avatar_path_label = CaptionLabel(tr("profile.edit.avatar.current", "Using current avatar"), self)
        self.avatar_path_label.setWordWrap(True)

        avatar_actions = QHBoxLayout()
        avatar_actions.setSpacing(10)
        choose_button = PushButton(tr("profile.edit.avatar.choose", "Choose Avatar"), self)
        choose_button.clicked.connect(self._choose_avatar)
        reset_button = PushButton(tr("profile.edit.avatar.reset", "Use Default Avatar"), self)
        reset_button.clicked.connect(self._reset_avatar)
        avatar_actions.addWidget(choose_button, 0)
        avatar_actions.addWidget(reset_button, 0)
        avatar_actions.addStretch(1)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)

        self.nickname_edit = LineEdit(self)
        self.nickname_edit.setText(str(self._user.get("nickname", "") or ""))
        self.nickname_edit.setPlaceholderText(tr("profile.edit.nickname.placeholder", "Nickname"))
        self.nickname_edit.setClearButtonEnabled(True)
        self.nickname_edit.setMaxLength(64)

        self.signature_edit = LineEdit(self)
        self.signature_edit.setText(str(self._user.get("signature", "") or ""))
        self.signature_edit.setPlaceholderText(tr("profile.edit.signature.placeholder", "Signature"))
        self.signature_edit.setClearButtonEnabled(True)
        self.signature_edit.setMaxLength(255)

        self.region_edit = LineEdit(self)
        self.region_edit.setText(str(self._user.get("region", "") or ""))
        self.region_edit.setPlaceholderText(tr("profile.edit.region.placeholder", "Region"))
        self.region_edit.setClearButtonEnabled(True)
        self.region_edit.setMaxLength(128)

        self.email_edit = LineEdit(self)
        self.email_edit.setText(str(self._user.get("email", "") or ""))
        self.email_edit.setPlaceholderText(tr("profile.edit.email.placeholder", "Email"))
        self.email_edit.setClearButtonEnabled(True)
        self.email_edit.setMaxLength(255)

        self.phone_edit = LineEdit(self)
        self.phone_edit.setText(str(self._user.get("phone", "") or ""))
        self.phone_edit.setPlaceholderText(tr("profile.edit.phone.placeholder", "Phone"))
        self.phone_edit.setClearButtonEnabled(True)
        self.phone_edit.setMaxLength(32)

        self.birthday_edit = QDateEdit(self)
        self.birthday_edit.setCalendarPopup(True)
        self.birthday_edit.setDisplayFormat("yyyy-MM-dd")
        self.birthday_edit.setMinimumDate(_EMPTY_BIRTHDAY)
        self.birthday_edit.setMaximumDate(QDate.currentDate())
        self.birthday_edit.setSpecialValueText(tr("profile.edit.birthday.empty", "Not set"))
        self.birthday_edit.setDate(qdate_from_profile_birthday(self._user.get("birthday"), _EMPTY_BIRTHDAY))

        birthday_row = QWidget(self)
        birthday_layout = QHBoxLayout(birthday_row)
        birthday_layout.setContentsMargins(0, 0, 0, 0)
        birthday_layout.setSpacing(8)
        birthday_layout.addWidget(self.birthday_edit, 1)
        birthday_clear_button = PushButton(tr("profile.edit.birthday.clear", "Clear"), self)
        birthday_clear_button.clicked.connect(lambda: self.birthday_edit.setDate(_EMPTY_BIRTHDAY))
        birthday_layout.addWidget(birthday_clear_button, 0)

        self.gender_combo = QComboBox(self)
        for value, label in profile_gender_options(include_blank=True):
            self.gender_combo.addItem(label, value)
        self._set_combo_value(self.gender_combo, self._user.get("gender", ""))

        self.status_combo = QComboBox(self)
        for value, label in profile_status_options():
            self.status_combo.addItem(label, value)
        self._set_combo_value(self.status_combo, self._user.get("status", "online") or "online")

        form.addRow(tr("contact.detail.label.nickname", "Nickname"), self.nickname_edit)
        form.addRow(tr("contact.detail.label.signature", "Signature"), self.signature_edit)
        form.addRow(tr("contact.detail.label.region", "Region"), self.region_edit)
        form.addRow(tr("contact.detail.label.email", "Email"), self.email_edit)
        form.addRow(tr("contact.detail.label.phone", "Phone"), self.phone_edit)
        form.addRow(tr("contact.detail.label.birthday", "Birthday"), birthday_row)
        form.addRow(tr("contact.detail.label.gender", "Gender"), self.gender_combo)
        form.addRow(tr("contact.detail.label.status", "Status"), self.status_combo)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.cancel_button = PushButton(tr("common.cancel", "Cancel"), self)
        self.save_button = PrimaryPushButton(tr("common.save", "Save"), self)
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._submit)
        button_row.addWidget(self.cancel_button, 0)
        button_row.addWidget(self.save_button, 0)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.avatar_preview, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(avatar_actions)
        layout.addWidget(self.avatar_path_label)
        layout.addLayout(form)
        layout.addStretch(1)
        layout.addLayout(button_row)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in {
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.StyleChange,
        }:
            _apply_themed_dialog_surface(self, "ProfileEditDialog")

    def profile_payload(self) -> dict[str, str | bool | None]:
        """Return dialog values after acceptance."""
        birthday_value = ""
        if self.birthday_edit.date() != _EMPTY_BIRTHDAY:
            birthday_value = self.birthday_edit.date().toString("yyyy-MM-dd")

        return {
            "nickname": self.nickname_edit.text().strip(),
            "signature": self.signature_edit.text().strip(),
            "region": self.region_edit.text().strip(),
            "email": self.email_edit.text().strip(),
            "phone": self.phone_edit.text().strip(),
            "birthday": birthday_value,
            "gender": str(self.gender_combo.currentData() or ""),
            "status": str(self.status_combo.currentData() or "online"),
            "avatar_file_path": self._avatar_file_path,
            "reset_avatar": self._reset_avatar_requested,
        }

    def _set_combo_value(self, combo: QComboBox, value: object) -> None:
        normalized = normalize_profile_choice(value)
        for index in range(combo.count()):
            if normalize_profile_choice(combo.itemData(index)) == normalized:
                combo.setCurrentIndex(index)
                return
        if combo.count() > 0:
            combo.setCurrentIndex(0)

    def _choose_avatar(self) -> None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            tr("profile.edit.avatar.dialog_title", "Choose Avatar"),
            "",
            tr("profile.edit.avatar.dialog_filter", "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.svg)"),
        )
        if not file_path:
            return

        self._avatar_file_path = file_path
        self._reset_avatar_requested = False
        seed = profile_avatar_seed(
            user_id=self._user.get("id"),
            username=self._user.get("username"),
            display_name=self.nickname_edit.text().strip(),
        )
        _set_avatar_widget(
            self.avatar_preview,
            file_path,
            fallback=self.nickname_edit.text().strip() or _display_name(self._user),
            gender=str(self.gender_combo.currentData() or ""),
            seed=seed,
        )
        self.avatar_path_label.setText(os.path.basename(file_path))

    def _reset_avatar(self) -> None:
        self._avatar_file_path = ""
        self._reset_avatar_requested = True
        self.avatar_path_label.setText(
            tr("profile.edit.avatar.reset_pending", "Will restore the server default avatar after saving")
        )

    def _submit(self) -> None:
        if not self.nickname_edit.text().strip():
            InfoBar.warning(
                tr("profile.edit.title", "Edit Profile"),
                tr("profile.edit.nickname.required", "Nickname cannot be empty."),
                parent=self,
                duration=1800,
            )
            self.nickname_edit.setFocus()
            return

        email_value = self.email_edit.text().strip()
        if email_value and not _EMAIL_PATTERN.fullmatch(email_value):
            InfoBar.warning(
                tr("profile.edit.title", "Edit Profile"),
                tr("profile.edit.email.invalid", "Please enter a valid email address."),
                parent=self,
                duration=1800,
            )
            self.email_edit.setFocus()
            return

        phone_value = self.phone_edit.text().strip()
        if phone_value and not _PHONE_PATTERN.fullmatch(phone_value):
            InfoBar.warning(
                tr("profile.edit.title", "Edit Profile"),
                tr("profile.edit.phone.invalid", "Please enter a valid phone number."),
                parent=self,
                duration=1800,
            )
            self.phone_edit.setFocus()
            return

        self.accept()


class ProfileCard(QWidget):
    """Compact profile summary used at the top of the acrylic flyout."""

    editRequested = Signal()
    logoutRequested = Signal()

    def __init__(self, user: dict, parent=None):
        super().__init__(parent)
        self._user = dict(user or {})

        self.v_box_layout = QVBoxLayout(self)
        self.v_box_layout.setContentsMargins(0, 0, 0, 0)
        self.v_box_layout.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(12)

        self.avatar = AvatarWidget(self)
        self.avatar.setRadius(24)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)
        self.name_label = BodyLabel("", self)
        self.account_label = CaptionLabel("", self)
        self.account_label.setWordWrap(True)
        text_layout.addWidget(self.name_label)
        text_layout.addWidget(self.account_label)
        text_layout.addStretch(1)

        header_row.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)
        header_row.addLayout(text_layout, 1)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(12)
        self.edit_link = HyperlinkLabel(tr("profile.quick.action.edit", "Edit Profile"), self)
        self.logout_link = HyperlinkLabel(tr("profile.quick.action.logout", "Sign Out"), self)
        self.edit_link.clicked.connect(self.editRequested.emit)
        self.logout_link.clicked.connect(self.logoutRequested.emit)
        action_row.addWidget(self.edit_link, 0)
        action_row.addWidget(self.logout_link, 0)
        action_row.addStretch(1)

        self.v_box_layout.addLayout(header_row)
        self.v_box_layout.addLayout(action_row)
        self.setMinimumHeight(84)
        self.set_user(self._user)

    def set_user(self, user: dict) -> None:
        """Refresh the compact profile summary."""
        self._user = dict(user or {})
        display_name = _display_name(self._user)
        account_id = _assistim_id(
            self._user,
            default=tr("main_window.user_card.empty_subtitle", "AssistIM ID unavailable"),
        )
        _set_avatar_widget(
            self.avatar,
            self._user.get("avatar", ""),
            fallback=display_name,
            gender=self._user.get("gender", ""),
            seed=profile_avatar_seed(user_id=self._user.get("id"), username=self._user.get("username"), display_name=display_name),
        )

        self.name_label.setText(display_name)
        self.account_label.setText(account_id)


class AcrylicUserProfileFlyoutView(AcrylicFlyoutViewBase):
    """Acrylic profile flyout with a compact card and reserved blank space."""

    editRequested = Signal()
    logoutRequested = Signal()

    def __init__(self, user: dict, parent=None):
        super().__init__(parent)
        self._user = dict(user or {})

        self.v_box_layout = QVBoxLayout(self)
        self.v_box_layout.setContentsMargins(20, 16, 20, 16)
        self.v_box_layout.setSpacing(16)

        self.profile_card = ProfileCard(self._user, self)
        self.profile_card.editRequested.connect(self.editRequested.emit)
        self.profile_card.logoutRequested.connect(self.logoutRequested.emit)

        self.divider = FluentDivider(self, variant=FluentDivider.INSET, inset=12)
        self.blank_panel = QWidget(self)
        self.blank_panel.setFixedHeight(148)

        self.v_box_layout.addWidget(self.profile_card)
        self.v_box_layout.addWidget(self.divider)
        self.v_box_layout.addWidget(self.blank_panel, 1)
        self.setMinimumWidth(340)

    def set_user(self, user: dict) -> None:
        """Refresh the flyout summary fields."""
        self._user = dict(user or {})
        self.profile_card.set_user(self._user)


class UserProfileCoordinator(QWidget):
    """Own the profile edit/logout flows and keep the flyout/user-card state in sync."""

    profileChanged = Signal(object)
    logoutRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auth_controller = get_auth_controller()
        self._save_task: Optional[asyncio.Task] = None
        self._ui_tasks: set[asyncio.Task] = set()
        self._flyout = None
        self._auth_listener_attached = False
        self.hide()
        self._auth_controller.add_auth_state_listener(self._handle_auth_state_changed)
        self._auth_listener_attached = True
        self.destroyed.connect(self._on_destroyed)
        self._emit_profile_changed()

    def current_user_snapshot(self) -> dict:
        """Return the latest in-memory current-user payload."""
        return dict(self._auth_controller.current_user or {})

    def show_user_flyout(self, target: QWidget, parent: QWidget) -> None:
        """Toggle the acrylic flyout anchored to the navigation user card."""
        if self._flyout is not None and self._flyout.isVisible():
            self._flyout.close()
            return

        view = AcrylicUserProfileFlyoutView(self.current_user_snapshot(), parent)
        view.editRequested.connect(self._handle_edit_from_flyout)
        view.logoutRequested.connect(self._handle_logout_from_flyout)

        self._flyout = AcrylicFlyout.make(
            view,
            target,
            parent,
            aniType=FlyoutAnimationType.SLIDE_RIGHT,
        )
        self._flyout.closed.connect(self._clear_flyout)

    def open_profile_editor(self) -> None:
        """Open the profile editor dialog."""
        user = self.current_user_snapshot()
        if not user or self._save_task is not None:
            return

        dialog = ProfileEditDialog(user, self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._set_save_task(self._save_profile_async(dialog.profile_payload()))

    def request_logout(self) -> None:
        """Confirm and emit a logout request."""
        if not self.current_user_snapshot():
            return

        dialog = LogoutConfirmDialog(self.window())
        if not dialog.exec():
            return

        self.logoutRequested.emit()

    def close_flyout(self) -> None:
        """Close the active flyout if it is visible."""
        self._close_flyout()

    def _handle_edit_from_flyout(self) -> None:
        self._close_flyout()
        self.open_profile_editor()

    def _handle_logout_from_flyout(self) -> None:
        self._close_flyout()
        self.request_logout()

    async def _save_profile_async(self, payload: dict[str, str | bool | None]) -> None:
        avatar_file_path = str(payload.get("avatar_file_path", "") or "").strip()
        reset_avatar = bool(payload.get("reset_avatar", False))

        try:
            update_result = await self._auth_controller.update_profile(
                nickname=str(payload.get("nickname", "") or "").strip(),
                signature=str(payload.get("signature", "") or "").strip(),
                region=str(payload.get("region", "") or "").strip(),
                email=str(payload.get("email", "") or "").strip(),
                phone=str(payload.get("phone", "") or "").strip(),
                birthday=payload.get("birthday"),
                gender=normalize_profile_gender(payload.get("gender")),
                status=str(payload.get("status", "") or "").strip(),
                avatar_file_path=avatar_file_path or None,
                reset_avatar=reset_avatar and not avatar_file_path,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            InfoBar.error(
                tr("profile.edit.title", "Edit Profile"),
                tr("profile.edit.failed", "Unable to update profile right now."),
                parent=self.window(),
                duration=2400,
            )
            raise
        else:
            user = dict(update_result.user or {})
            snapshot = update_result.session_snapshot
            self.profileChanged.emit(user)
            if snapshot is not None and not snapshot.authoritative:
                InfoBar.warning(
                    tr("profile.edit.title", "Edit Profile"),
                    tr("profile.edit.session_refresh_degraded", "Profile updated. Some conversations may refresh later."),
                    parent=self.window(),
                    duration=2400,
                )
            elif snapshot is not None and not snapshot.unread_synchronized:
                InfoBar.info(
                    tr("profile.edit.title", "Edit Profile"),
                    tr("profile.edit.unread_refresh_degraded", "Profile updated. Unread counters may update shortly."),
                    parent=self.window(),
                    duration=2200,
                )
            else:
                InfoBar.success(
                    tr("profile.edit.title", "Edit Profile"),
                    tr("profile.edit.success", "Profile updated."),
                    parent=self.window(),
                    duration=1800,
                )
        finally:
            self._close_flyout()

    def _emit_profile_changed(self) -> None:
        self.profileChanged.emit(self.current_user_snapshot())

    def _handle_auth_state_changed(self, payload: object) -> None:
        """Project committed auth-state changes into the shell identity surfaces."""
        self._close_flyout()
        self.profileChanged.emit(dict(payload or {}))

    def _close_flyout(self) -> None:
        if self._flyout is not None:
            self._flyout.close()

    def _clear_flyout(self) -> None:
        self._flyout = None

    def _cancel_pending_task(self, task: Optional[asyncio.Task]) -> None:
        if task is not None and not task.done():
            task.cancel()

    def _create_ui_task(self, coro, context: str, *, on_done=None) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._ui_tasks.add(task)
        task.add_done_callback(
            lambda finished, name=context, callback=on_done: self._finalize_ui_task(finished, name, callback)
        )
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
            logger.exception("UserProfileCoordinator task failed: %s", context)

    def _set_save_task(self, coro) -> None:
        self._cancel_pending_task(self._save_task)
        self._save_task = self._create_ui_task(coro, "save profile", on_done=self._clear_save_task)

    def _clear_save_task(self, task: asyncio.Task) -> None:
        if self._save_task is task:
            self._save_task = None

    def quiesce(self) -> None:
        """Cancel logout-sensitive UI work before the shell is destroyed."""
        self._cancel_pending_task(self._save_task)
        self._save_task = None
        self._close_flyout()
        for task in list(self._ui_tasks):
            if not task.done():
                task.cancel()

    def closeEvent(self, event) -> None:
        self.quiesce()
        super().closeEvent(event)

    def _on_destroyed(self, *_args) -> None:
        if self._auth_listener_attached:
            self._auth_controller.remove_auth_state_listener(self._handle_auth_state_changed)
            self._auth_listener_attached = False
        self.quiesce()


