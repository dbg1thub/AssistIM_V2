"""Profile and account management page."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Optional

from PySide6.QtCore import QDate, Qt, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    InfoBar,
    LineEdit,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SubtitleLabel,
    TitleLabel,
)

from client.core import logging
from client.core.config_backend import get_config
from client.core.i18n import tr
from client.core.logging import setup_logging
from client.core.profile_fields import (
    format_profile_birthday,
    localize_profile_gender,
    localize_profile_status,
    normalize_profile_choice,
    profile_gender_options,
    profile_status_options,
    qdate_from_profile_birthday,
)
from client.ui.controllers.auth_controller import get_auth_controller


setup_logging()
logger = logging.get_logger(__name__)

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9()\-\.\s]{5,31}$")
_EMPTY_BIRTHDAY = QDate(1900, 1, 1)


def _avatar_initials(name: str) -> str:
    text = (name or "").strip()
    if not text:
        return "?"
    if len(text) == 1:
        return text.upper()
    return text[:2].upper()


class AvatarPreview(QLabel):
    """Small avatar preview widget with local and remote image support."""

    def __init__(self, size: int = 88, parent=None):
        super().__init__(parent)
        self._size = size
        self._fallback_text = "?"
        self._network_manager = QNetworkAccessManager(self)
        self._network_manager.finished.connect(self._on_image_loaded)

        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("profileAvatarPreview")
        self._apply_fallback()

    def set_avatar(self, avatar_path: str = "", fallback: str = "") -> None:
        """Display one avatar source or initials fallback."""
        self._fallback_text = _avatar_initials(fallback)
        source = self._resolve_avatar_source(avatar_path)

        if source.startswith(("http://", "https://")):
            self._apply_fallback()
            reply = self._network_manager.get(QNetworkRequest(QUrl(source)))
            reply.setProperty("avatar_source", source)
            return

        if source:
            pixmap = QPixmap(source)
            if not pixmap.isNull():
                self._apply_pixmap(pixmap)
                return

        self._apply_fallback()

    def _resolve_avatar_source(self, value: str) -> str:
        if not value:
            return ""
        if os.path.exists(value):
            return value
        if value.startswith(("http://", "https://")):
            return value
        if value.startswith("/"):
            api_base = get_config().server.api_base_url.rstrip("/")
            host_base = api_base[:-4] if api_base.endswith("/api") else api_base
            return f"{host_base}{value}"
        return value

    def _apply_pixmap(self, pixmap: QPixmap) -> None:
        scaled = pixmap.scaled(
            self._size,
            self._size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)
        self.setText("")
        self.setStyleSheet(
            f"border-radius: {self._size // 2}px; background: rgba(0, 0, 0, 0.06);"
        )

    def _apply_fallback(self) -> None:
        self.setPixmap(QPixmap())
        self.setText(self._fallback_text)
        self.setStyleSheet(
            f"""
            border-radius: {self._size // 2}px;
            background: rgba(7, 193, 96, 0.16);
            color: rgb(7, 160, 84);
            font-size: {max(18, self._size // 3)}px;
            font-weight: 600;
            """
        )

    def _on_image_loaded(self, reply: QNetworkReply) -> None:
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._apply_fallback()
                return

            pixmap = QPixmap()
            if not pixmap.loadFromData(bytes(reply.readAll())):
                self._apply_fallback()
                return

            self._apply_pixmap(pixmap)
        finally:
            reply.deleteLater()


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

        self.setWindowTitle(tr("profile.edit.window_title", "Edit Profile"))
        self.setMinimumWidth(520)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = SubtitleLabel(tr("profile.edit.title", "Edit Profile"), self)
        subtitle = CaptionLabel(
            tr("profile.edit.subtitle", "Update your public nickname, avatar, and profile details."),
            self,
        )
        subtitle.setWordWrap(True)

        self.avatar_preview = AvatarPreview(80, self)
        self.avatar_preview.set_avatar(str(self._user.get("avatar", "") or ""), self._display_name())

        self.avatar_path_label = CaptionLabel(
            tr("profile.edit.avatar.current", "Using current avatar"),
            self,
        )
        self.avatar_path_label.setWordWrap(True)

        avatar_actions = QHBoxLayout()
        avatar_actions.setSpacing(10)
        choose_button = PushButton(tr("profile.edit.avatar.choose", "Choose Avatar"), self)
        choose_button.clicked.connect(self._choose_avatar)
        avatar_actions.addWidget(choose_button, 0)
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

    def profile_payload(self) -> dict[str, str | None]:
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
        }

    def _display_name(self) -> str:
        return (
            str(self._user.get("nickname", "") or "")
            or str(self._user.get("username", "") or "")
            or tr("common.app_name", "AssistIM")
        )

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
            tr(
                "profile.edit.avatar.dialog_filter",
                "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.webp)",
            ),
        )
        if not file_path:
            return

        self._avatar_file_path = file_path
        self.avatar_preview.set_avatar(file_path, self.nickname_edit.text().strip() or self._display_name())
        self.avatar_path_label.setText(os.path.basename(file_path))

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


class ProfileInterface(ScrollArea):
    """Dedicated account page with profile editing and logout actions."""

    logoutRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("ProfileInterface")

        self._auth_controller = get_auth_controller()
        self._save_task: Optional[asyncio.Task] = None
        self._ui_tasks: set[asyncio.Task] = set()

        self.scroll_widget = QWidget(self)
        self.scroll_widget.setObjectName("profileScrollWidget")
        self.setWidget(self.scroll_widget)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 24, 0, 24)

        root = QVBoxLayout(self.scroll_widget)
        root.setContentsMargins(36, 0, 36, 24)
        root.setSpacing(20)

        header = QWidget(self.scroll_widget)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        header_layout.addWidget(TitleLabel(tr("profile.page.title", "Profile"), header))
        subtitle = CaptionLabel(
            tr("profile.page.subtitle", "Manage your current account, public profile, and desktop sign-in state."),
            header,
        )
        subtitle.setWordWrap(True)
        header_layout.addWidget(subtitle)

        self.profile_card = CardWidget(self.scroll_widget)
        self.profile_card.setObjectName("profileSummaryCard")
        card_layout = QVBoxLayout(self.profile_card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.setSpacing(18)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(18)

        self.avatar_preview = AvatarPreview(88, self.profile_card)
        summary_text = QVBoxLayout()
        summary_text.setSpacing(6)
        self.name_label = TitleLabel("", self.profile_card)
        self.account_label = CaptionLabel("", self.profile_card)
        self.signature_label = BodyLabel("", self.profile_card)
        self.signature_label.setWordWrap(True)
        self.meta_primary_label = CaptionLabel("", self.profile_card)
        self.meta_primary_label.setWordWrap(True)
        self.meta_secondary_label = CaptionLabel("", self.profile_card)
        self.meta_secondary_label.setWordWrap(True)
        summary_text.addWidget(self.name_label)
        summary_text.addWidget(self.account_label)
        summary_text.addWidget(self.signature_label)
        summary_text.addWidget(self.meta_primary_label)
        summary_text.addWidget(self.meta_secondary_label)
        summary_text.addStretch(1)

        summary_row.addWidget(self.avatar_preview, 0, Qt.AlignmentFlag.AlignTop)
        summary_row.addLayout(summary_text, 1)

        meta_line = QFrame(self.profile_card)
        meta_line.setFrameShape(QFrame.Shape.HLine)
        meta_line.setFrameShadow(QFrame.Shadow.Plain)

        self.meta_id_label = CaptionLabel("", self.profile_card)
        self.meta_username_label = CaptionLabel("", self.profile_card)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.edit_button = PrimaryPushButton(tr("profile.action.edit", "Edit Profile"), self.profile_card)
        self.logout_button = PushButton(tr("profile.action.logout", "Sign Out"), self.profile_card)
        self.edit_button.clicked.connect(self._open_edit_dialog)
        self.logout_button.clicked.connect(self._request_logout)
        action_row.addWidget(self.edit_button, 0)
        action_row.addWidget(self.logout_button, 0)
        action_row.addStretch(1)

        card_layout.addLayout(summary_row)
        card_layout.addWidget(meta_line)
        card_layout.addWidget(self.meta_id_label)
        card_layout.addWidget(self.meta_username_label)
        card_layout.addLayout(action_row)

        root.addWidget(header)
        root.addWidget(self.profile_card)
        root.addStretch(1)

        self.destroyed.connect(self._on_destroyed)
        self._refresh_profile()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_profile()

    def _refresh_profile(self, avatar_override: str = "") -> None:
        user = dict(self._auth_controller.current_user or {})
        display_name = (
            str(user.get("nickname", "") or "")
            or str(user.get("username", "") or "")
            or tr("profile.placeholder.name", "Not Signed In")
        )
        username = str(user.get("username", "") or "")
        user_id = str(user.get("id", "") or "-")
        signature = str(user.get("signature", "") or "") or tr("profile.placeholder.signature", "No signature yet.")
        status = localize_profile_status(
            user.get("status", ""),
            default=tr("profile.summary.status_unknown", "Unknown"),
        )
        gender = localize_profile_gender(user.get("gender", ""))
        birthday = format_profile_birthday(user.get("birthday", ""))
        region = str(user.get("region", "") or "")
        email = str(user.get("email", "") or "")
        phone = str(user.get("phone", "") or "")

        primary_parts = [
            tr("profile.summary.status", "Status: {value}", value=status),
        ]
        if gender:
            primary_parts.append(tr("profile.summary.gender", "Gender: {value}", value=gender))
        if birthday:
            primary_parts.append(tr("profile.summary.birthday", "Birthday: {value}", value=birthday))
        if region:
            primary_parts.append(tr("profile.summary.region", "Region: {value}", value=region))

        secondary_parts = []
        if email:
            secondary_parts.append(tr("profile.summary.email", "Email: {value}", value=email))
        if phone:
            secondary_parts.append(tr("profile.summary.phone", "Phone: {value}", value=phone))

        self.name_label.setText(display_name)
        self.account_label.setText(
            tr("profile.summary.account", "@{username}", username=username) if username else tr("common.app_name", "AssistIM")
        )
        self.signature_label.setText(signature)
        self.meta_primary_label.setText("  |  ".join(primary_parts))
        self.meta_secondary_label.setText(
            "  |  ".join(secondary_parts) if secondary_parts else tr("profile.summary.more_empty", "Add contact details to complete your profile.")
        )
        self.meta_id_label.setText(tr("profile.summary.user_id", "User ID: {user_id}", user_id=user_id))
        self.meta_username_label.setText(
            tr("profile.summary.username", "Username: {username}", username=username or "-")
        )
        self.avatar_preview.set_avatar(
            avatar_override or str(user.get("avatar", "") or ""),
            display_name,
        )

        enabled = bool(user)
        self.edit_button.setEnabled(enabled and self._save_task is None)
        self.logout_button.setEnabled(enabled)

    def _set_busy(self, busy: bool) -> None:
        self.edit_button.setEnabled(not busy and bool(self._auth_controller.current_user))
        self.logout_button.setEnabled(not busy and bool(self._auth_controller.current_user))
        self.edit_button.setText(
            tr("profile.action.saving", "Saving...")
            if busy
            else tr("profile.action.edit", "Edit Profile")
        )

    def _open_edit_dialog(self) -> None:
        user = self._auth_controller.current_user or {}
        if not user or self._save_task is not None:
            return

        dialog = ProfileEditDialog(user, self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        payload = dialog.profile_payload()
        self._set_save_task(self._save_profile_async(payload))

    async def _save_profile_async(self, payload: dict[str, str | None]) -> None:
        self._set_busy(True)
        avatar_file_path = str(payload.get("avatar_file_path", "") or "").strip()

        try:
            user = await self._auth_controller.update_profile(
                nickname=str(payload.get("nickname", "") or "").strip(),
                signature=str(payload.get("signature", "") or "").strip(),
                region=str(payload.get("region", "") or "").strip(),
                email=str(payload.get("email", "") or "").strip(),
                phone=str(payload.get("phone", "") or "").strip(),
                birthday=payload.get("birthday"),
                gender=str(payload.get("gender", "") or "").strip(),
                status=str(payload.get("status", "") or "").strip(),
                avatar_file_path=avatar_file_path or None,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            InfoBar.error(
                tr("profile.edit.title", "Edit Profile"),
                str(exc),
                parent=self.window(),
                duration=2400,
            )
        else:
            self._refresh_profile(avatar_override=avatar_file_path or str(user.get("avatar", "") or ""))
            InfoBar.success(
                tr("profile.edit.title", "Edit Profile"),
                tr("profile.edit.success", "Profile updated."),
                parent=self.window(),
                duration=1800,
            )
        finally:
            self._set_busy(False)

    def _request_logout(self) -> None:
        if not self._auth_controller.current_user:
            return

        dialog = LogoutConfirmDialog(self.window())
        if not dialog.exec():
            return

        self._set_busy(True)
        self.logout_button.setText(tr("profile.action.logging_out", "Signing Out..."))
        self.logoutRequested.emit()

    def _cancel_pending_task(self, task: Optional[asyncio.Task]) -> None:
        if task is not None and not task.done():
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
            logger.exception("ProfileInterface task failed: %s", context)

    def _set_save_task(self, coro) -> None:
        self._cancel_pending_task(self._save_task)
        self._save_task = self._create_ui_task(coro, "save profile", on_done=self._clear_save_task)

    def _clear_save_task(self, task: asyncio.Task) -> None:
        if self._save_task is task:
            self._save_task = None

    def _on_destroyed(self, *_args) -> None:
        self._cancel_pending_task(self._save_task)
        self._save_task = None
        for task in list(self._ui_tasks):
            if not task.done():
                task.cancel()
