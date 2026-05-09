"""Quick user-profile flyout and profile actions for the main window."""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    AvatarWidget,
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FlyoutAnimationType,
    HyperlinkLabel,
    InfoBar,
    LineEdit,
    MessageBoxBase,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    SingleDirectionScrollArea,
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
)
from client.ui.controllers.auth_controller import get_auth_controller
from client.ui.widgets.fluent_divider import FluentDivider
from client.ui.widgets.fluent_dialog import FluentDialog


setup_logging()
logger = logging.get_logger(__name__)

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_REGION_OPTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("", ("",)),
    (
        "中国大陆",
        (
            "",
            "北京",
            "上海",
            "天津",
            "重庆",
            "河北",
            "山西",
            "辽宁",
            "吉林",
            "黑龙江",
            "江苏",
            "浙江",
            "安徽",
            "福建",
            "江西",
            "山东",
            "河南",
            "湖北",
            "湖南",
            "广东",
            "海南",
            "四川",
            "贵州",
            "云南",
            "陕西",
            "甘肃",
            "青海",
            "内蒙古",
            "广西",
            "西藏",
            "宁夏",
            "新疆",
        ),
    ),
    ("中国香港", ("",)),
    ("中国澳门", ("",)),
    ("中国台湾", ("",)),
    ("韩国", ("", "首尔", "釜山", "大邱", "仁川", "光州", "大田", "蔚山", "世宗", "京畿道", "江原道", "忠清北道", "忠清南道", "全罗北道", "全罗南道", "庆尚北道", "庆尚南道", "济州")),
    ("美国", ("",)),
    ("日本", ("",)),
    ("其他", ("",)),
)


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


class ChangePasswordDialog(FluentDialog):
    """Dialog for changing the current authenticated user's password."""

    def __init__(self, parent=None):
        super().__init__(parent, title=tr("profile.password.change.title", "Change Password"))
        self.setWindowTitle(tr("profile.password.change.title", "Change Password"))
        self.setMinimumWidth(420)
        self.setModal(True)
        self.setObjectName("ChangePasswordDialog")

        layout = self.content_layout
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = SubtitleLabel(tr("profile.password.change.title", "Change Password"), self)
        subtitle = CaptionLabel(
            tr("profile.password.change.subtitle", "Enter your current password before setting a new one."),
            self,
        )
        subtitle.setWordWrap(True)

        self.current_password_edit = PasswordLineEdit(self)
        self.current_password_edit.setPlaceholderText(
            tr("profile.password.change.current.placeholder", "Current Password")
        )
        self.current_password_edit.setMinimumHeight(40)

        self.new_password_edit = PasswordLineEdit(self)
        self.new_password_edit.setPlaceholderText(tr("profile.password.change.new.placeholder", "New Password"))
        self.new_password_edit.setMinimumHeight(40)

        self.confirm_password_edit = PasswordLineEdit(self)
        self.confirm_password_edit.setPlaceholderText(
            tr("profile.password.change.confirm.placeholder", "Confirm New Password")
        )
        self.confirm_password_edit.setMinimumHeight(40)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.cancel_button = PushButton(tr("common.cancel", "Cancel"), self)
        self.submit_button = PrimaryPushButton(tr("profile.password.change.action", "Change Password"), self)
        self.cancel_button.clicked.connect(self.reject)
        self.submit_button.clicked.connect(self._submit)
        button_row.addWidget(self.cancel_button, 0)
        button_row.addWidget(self.submit_button, 0)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.current_password_edit)
        layout.addWidget(self.new_password_edit)
        layout.addWidget(self.confirm_password_edit)
        layout.addSpacing(4)
        layout.addLayout(button_row)

    def password_payload(self) -> tuple[str, str]:
        return self.current_password_edit.text(), self.new_password_edit.text()

    def _submit(self) -> None:
        current_password = self.current_password_edit.text()
        new_password = self.new_password_edit.text()
        confirm_password = self.confirm_password_edit.text()

        if len(current_password) < 6:
            InfoBar.warning(
                tr("profile.password.change.title", "Change Password"),
                tr("profile.password.change.current.required", "Enter your current password."),
                parent=self,
                duration=1800,
            )
            self.current_password_edit.setFocus()
            return
        if len(new_password) < 6:
            InfoBar.warning(
                tr("profile.password.change.title", "Change Password"),
                tr("profile.password.change.new.required", "New password must be at least 6 characters."),
                parent=self,
                duration=1800,
            )
            self.new_password_edit.setFocus()
            return
        if new_password != confirm_password:
            InfoBar.warning(
                tr("profile.password.change.title", "Change Password"),
                tr("profile.password.change.mismatch", "New passwords do not match."),
                parent=self,
                duration=1800,
            )
            self.confirm_password_edit.setFocus()
            return
        self.accept()


class DeviceSecurityDialog(FluentDialog):
    """Read-only E2EE device inventory for the current account."""

    def __init__(self, parent=None, auth_controller=None):
        super().__init__(parent, title=tr("profile.security.title", "Account Security"))
        self._auth_controller = auth_controller or get_auth_controller()
        self._load_task: Optional[asyncio.Task] = None
        self._action_task: Optional[asyncio.Task] = None

        self.setWindowTitle(tr("profile.security.title", "Account Security"))
        self.setMinimumSize(560, 500)
        self.setModal(False)
        self.setObjectName("DeviceSecurityDialog")

        layout = self.content_layout
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = SubtitleLabel(tr("profile.security.title", "Account Security"), self)
        subtitle = CaptionLabel(
            tr(
                "profile.security.subtitle",
                "Review the E2EE devices registered to this account.",
            ),
            self,
        )
        subtitle.setWordWrap(True)

        self.status_label = CaptionLabel("", self)
        self.status_label.setWordWrap(True)

        self.scroll_area = SingleDirectionScrollArea(self, orient=Qt.Orientation.Vertical)
        self.scroll_area.setObjectName("DeviceSecurityScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.device_container = QWidget(self.scroll_area)
        self.device_container.setObjectName("DeviceSecurityDeviceContainer")
        self.device_layout = QVBoxLayout(self.device_container)
        self.device_layout.setContentsMargins(0, 0, 0, 0)
        self.device_layout.setSpacing(10)
        self.scroll_area.setWidget(self.device_container)

        button_row = QHBoxLayout()
        self.import_button = PushButton(tr("profile.security.import", "Import Recovery Package"), self)
        self.import_button.clicked.connect(self._select_recovery_package_import)
        button_row.addWidget(self.import_button, 0)
        button_row.addStretch(1)
        self.refresh_button = PushButton(tr("common.refresh", "Refresh"), self)
        self.close_button = PrimaryPushButton(tr("common.close", "Close"), self)
        self.refresh_button.clicked.connect(self.reload_devices)
        self.close_button.clicked.connect(self.close)
        button_row.addWidget(self.refresh_button, 0)
        button_row.addWidget(self.close_button, 0)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.status_label)
        layout.addWidget(self.scroll_area, 1)
        layout.addLayout(button_row)

        self.finished.connect(lambda _result: self._cancel_pending_tasks())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._load_task is None:
            self.reload_devices()

    def closeEvent(self, event) -> None:
        self._cancel_pending_tasks()
        super().closeEvent(event)

    def reload_devices(self) -> None:
        """Refresh the readonly device snapshot."""
        self._cancel_load_task()
        self._load_task = asyncio.create_task(self._load_devices_async())
        self._load_task.add_done_callback(self._finalize_load_task)

    async def _load_devices_async(self) -> None:
        self.refresh_button.setEnabled(False)
        self.import_button.setEnabled(False)
        self.status_label.setText(tr("profile.security.loading", "Loading registered devices..."))
        self._render_loading()
        try:
            devices = await self._auth_controller.list_my_e2ee_devices()
            diagnostics = await self._auth_controller.get_history_recovery_diagnostics()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to load E2EE devices for profile security dialog")
            self.status_label.setText(
                tr("profile.security.load_failed", "Unable to load registered devices right now.")
            )
            self._render_empty(tr("profile.security.load_failed_hint", "Try refreshing again later."))
        else:
            local_device_id = str(diagnostics.get("local_device_id", "") or "").strip()
            self._render_devices(devices, local_device_id=local_device_id)
            self.status_label.setText(
                tr(
                    "profile.security.summary",
                    "{count} registered devices.",
                    count=len([item for item in devices if isinstance(item, dict)]),
                )
            )
        finally:
            self.refresh_button.setEnabled(True)
            self.import_button.setEnabled(True)

    def _finalize_load_task(self, task: asyncio.Task) -> None:
        if self._load_task is task:
            self._load_task = None
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Device security dialog task failed")

    def _cancel_load_task(self) -> None:
        if self._load_task is not None and not self._load_task.done():
            self._load_task.cancel()
        self._load_task = None

    def _cancel_action_task(self) -> None:
        if self._action_task is not None and not self._action_task.done():
            self._action_task.cancel()
        self._action_task = None

    def _cancel_pending_tasks(self) -> None:
        self._cancel_load_task()
        self._cancel_action_task()

    def _set_action_task(self, coro) -> None:
        self._cancel_action_task()
        self._action_task = asyncio.create_task(coro)
        self._action_task.add_done_callback(self._finalize_action_task)

    def _finalize_action_task(self, task: asyncio.Task) -> None:
        if self._action_task is task:
            self._action_task = None
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Device security action task failed")

    def _set_action_busy(self, busy: bool, status: str = "") -> None:
        self.refresh_button.setEnabled(not busy)
        self.import_button.setEnabled(not busy)
        if status:
            self.status_label.setText(status)

    def _clear_device_layout(self) -> None:
        while self.device_layout.count():
            item = self.device_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_loading(self) -> None:
        self._render_empty(tr("profile.security.loading", "Loading registered devices..."))

    def _render_empty(self, text: str) -> None:
        self._clear_device_layout()
        label = BodyLabel(text, self.device_container)
        label.setWordWrap(True)
        self.device_layout.addWidget(label)
        self.device_layout.addStretch(1)

    def _render_devices(self, devices: list[dict[str, Any]], *, local_device_id: str) -> None:
        normalized_devices = [dict(item) for item in devices if isinstance(item, dict)]
        normalized_devices.sort(
            key=lambda item: (
                str(item.get("device_id", "") or "").strip() != local_device_id,
                not bool(item.get("is_active", True)),
                str(item.get("device_name", "") or "").lower(),
                str(item.get("device_id", "") or ""),
            )
        )
        self._clear_device_layout()
        if not normalized_devices:
            self._render_empty(tr("profile.security.empty", "No registered E2EE devices were found."))
            return

        for device in normalized_devices:
            device_id = str(device.get("device_id", "") or "").strip()
            self.device_layout.addWidget(
                self._create_device_card(
                    device,
                    is_local=bool(local_device_id and device_id == local_device_id),
                )
            )
        self.device_layout.addStretch(1)

    def _create_device_card(self, device: dict[str, Any], *, is_local: bool) -> QWidget:
        card = QWidget(self.device_container)
        card.setObjectName("DeviceSecurityDeviceCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(
            "QWidget#DeviceSecurityDeviceCard {"
            f"background: {'rgba(255,255,255,0.06)' if isDarkTheme() else 'rgba(0,0,0,0.035)'};"
            "border-radius: 8px;"
            "}"
        )

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        device_name = str(device.get("device_name", "") or "").strip() or tr(
            "profile.security.device.unnamed",
            "Unnamed Device",
        )
        if is_local:
            device_name = tr(
                "profile.security.device.current",
                "{name} · This device",
                name=device_name,
            )
        title = BodyLabel(device_name, card)
        title.setWordWrap(True)
        layout.addWidget(title)

        layout.addWidget(
            self._device_detail_label(
                tr(
                    "profile.security.device.id",
                    "Device ID: {device_id}",
                    device_id=str(device.get("device_id", "") or "-"),
                ),
                card,
            )
        )
        layout.addWidget(
            self._device_detail_label(
                tr(
                    "profile.security.device.prekeys",
                    "Available one-time prekeys: {count}",
                    count=int(device.get("available_prekey_count") or 0),
                ),
                card,
            )
        )
        layout.addWidget(
            self._device_detail_label(
                tr(
                    "profile.security.device.status",
                    "Status: {status}",
                    status=tr("profile.security.device.active", "Active")
                    if bool(device.get("is_active", True))
                    else tr("profile.security.device.inactive", "Inactive"),
                ),
                card,
            )
        )
        timestamp = str(device.get("last_seen_at") or device.get("updated_at") or device.get("created_at") or "").strip()
        if timestamp:
            layout.addWidget(
                self._device_detail_label(
                    tr("profile.security.device.last_seen", "Last activity: {time}", time=timestamp),
                    card,
                )
            )
        device_id = str(device.get("device_id", "") or "").strip()
        if device_id and not is_local:
            action_row = QHBoxLayout()
            action_row.setContentsMargins(0, 6, 0, 0)
            action_row.addStretch(1)
            export_button = PushButton(tr("profile.security.export", "Export Recovery Package"), card)
            export_button.clicked.connect(lambda _checked=False, did=device_id: self._select_recovery_package_export(did))
            action_row.addWidget(export_button, 0)
            layout.addLayout(action_row)
        return card

    @staticmethod
    def _device_detail_label(text: str, parent: QWidget) -> CaptionLabel:
        label = CaptionLabel(text, parent)
        label.setWordWrap(True)
        return label

    def _select_recovery_package_export(self, device_id: str) -> None:
        normalized_device_id = str(device_id or "").strip()
        if not normalized_device_id or self._action_task is not None:
            return
        default_name = f"assistim-recovery-{normalized_device_id}.json"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("profile.security.export.title", "Export Recovery Package"),
            default_name,
            tr("profile.security.recovery_filter", "JSON Files (*.json);;All Files (*.*)"),
        )
        if not file_path:
            return
        self._set_action_task(self._export_recovery_package_async(normalized_device_id, file_path))

    async def _export_recovery_package_async(self, device_id: str, file_path: str) -> None:
        self._set_action_busy(
            True,
            tr("profile.security.export.running", "Exporting recovery package..."),
        )
        try:
            result = await self._auth_controller.export_history_recovery_package(device_id)
            with open(file_path, "w", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to export E2EE history recovery package")
            InfoBar.error(
                tr("profile.security.export.title", "Export Recovery Package"),
                tr("profile.security.export.failed", "Unable to export the recovery package."),
                parent=self,
                duration=2400,
            )
        else:
            InfoBar.success(
                tr("profile.security.export.title", "Export Recovery Package"),
                tr("profile.security.export.success", "Recovery package exported."),
                parent=self,
                duration=2000,
            )
            self.reload_devices()
        finally:
            self._set_action_busy(False)

    def _select_recovery_package_import(self) -> None:
        if self._action_task is not None:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("profile.security.import.title", "Import Recovery Package"),
            "",
            tr("profile.security.recovery_filter", "JSON Files (*.json);;All Files (*.*)"),
        )
        if not file_path:
            return
        self._set_action_task(self._import_recovery_package_async(file_path))

    async def _import_recovery_package_async(self, file_path: str) -> None:
        self._set_action_busy(
            True,
            tr("profile.security.import.running", "Importing recovery package..."),
        )
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                package = self._extract_recovery_package(json.load(handle))
            result = await self._auth_controller.import_history_recovery_package(package)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to import E2EE history recovery package")
            InfoBar.error(
                tr("profile.security.import.title", "Import Recovery Package"),
                tr("profile.security.import.failed", "Unable to import the recovery package."),
                parent=self,
                duration=2400,
            )
        else:
            InfoBar.success(
                tr("profile.security.import.title", "Import Recovery Package"),
                self._format_recovery_import_success(result),
                parent=self,
                duration=2200,
            )
            self.reload_devices()
        finally:
            self._set_action_busy(False)

    @staticmethod
    def _format_recovery_import_success(result: dict[str, Any]) -> str:
        source_device_id = str(result.get("source_device_id", "") or "").strip()
        base_message = (
            tr("profile.security.import.success", "Recovery package imported.")
            if not source_device_id
            else tr(
                "profile.security.import.success_from",
                "Recovery package imported from {device_id}.",
                device_id=source_device_id,
            )
        )
        session_recovery = dict(result.get("session_recovery") or {})
        session_count = int(session_recovery.get("session_count", 0) or 0)
        updated = int(session_recovery.get("updated", 0) or 0)
        failed = int(session_recovery.get("failed_session_count", 0) or 0)
        if session_count <= 0:
            return base_message
        if failed:
            return tr(
                "profile.security.import.success_with_failures",
                "{message} Retried {count} encrypted chats; {failed} failed.",
                message=base_message,
                count=session_count,
                failed=failed,
            )
        return tr(
            "profile.security.import.success_with_recovery",
            "{message} Retried {count} encrypted chats and updated {updated} messages.",
            message=base_message,
            count=session_count,
            updated=updated,
        )

    @staticmethod
    def _extract_recovery_package(payload: object) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("recovery package must be a JSON object")
        package = payload.get("package")
        if isinstance(package, dict):
            return dict(package)
        return dict(payload)


class ProfileEditDialog(FluentDialog):
    """Profile editor for public identity fields."""

    def __init__(self, user: dict, parent=None, auth_controller=None):
        super().__init__(parent, title=tr("profile.edit.window_title", "Edit Profile"))
        self._user = dict(user or {})
        self._auth_controller = auth_controller or get_auth_controller()
        self._original_email = str(self._user.get("email", "") or "").strip().lower()
        self._avatar_file_path = ""
        self._reset_avatar_requested = False
        self._email_code_task: asyncio.Task | None = None
        self._email_code_busy = False
        self._email_countdown = 0
        self._email_timer = QTimer(self)
        self._email_timer.setInterval(1000)
        self._email_timer.timeout.connect(self._tick_email_countdown)
        self.finished.connect(lambda _result: self._cancel_email_code_task())

        self.setWindowTitle(tr("profile.edit.window_title", "Edit Profile"))
        self.setMinimumWidth(520)
        self.setModal(True)
        self.setObjectName("ProfileEditDialog")

        layout = self.content_layout
        layout.setContentsMargins(24, 10, 24, 24)
        layout.setSpacing(16)

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

        form_widget = QWidget(self)
        form_layout = QVBoxLayout(form_widget)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(12)

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

        self.region_country_combo = ComboBox(self)
        self.region_area_combo = ComboBox(self)
        self._populate_region_country_combo(str(self._user.get("region", "") or ""))
        self.region_country_combo.currentIndexChanged.connect(lambda _index: self._sync_region_area_options())

        self.email_edit = LineEdit(self)
        self.email_edit.setText(str(self._user.get("email", "") or ""))
        self.email_edit.setPlaceholderText(tr("profile.edit.email.placeholder", "Email"))
        self.email_edit.setClearButtonEnabled(True)
        self.email_edit.setMaxLength(255)
        self.email_edit.textChanged.connect(self._sync_email_code_visibility)

        self.email_code_row = QWidget(self)
        email_code_layout = QHBoxLayout(self.email_code_row)
        email_code_layout.setContentsMargins(0, 0, 0, 0)
        email_code_layout.setSpacing(8)
        self.email_code_edit = LineEdit(self)
        self.email_code_edit.setPlaceholderText(tr("auth.field.email_code", "Email Verification Code"))
        self.email_code_edit.setMaxLength(6)
        self.email_send_code_button = PushButton(tr("auth.button.send_email_code", "Send Code"), self)
        self.email_send_code_button.clicked.connect(self._submit_email_code)
        email_code_layout.addWidget(self.email_code_edit, 1)
        email_code_layout.addWidget(self.email_send_code_button, 0)

        self.gender_combo = ComboBox(self)
        for value, label in profile_gender_options(include_blank=True):
            self.gender_combo.addItem(label, userData=value)
        self._set_combo_value(self.gender_combo, self._user.get("gender", ""))

        form_layout.addWidget(self._create_form_row(tr("contact.detail.label.nickname", "Nickname"), self.nickname_edit))
        form_layout.addWidget(self._create_form_row(tr("contact.detail.label.signature", "Signature"), self.signature_edit))
        form_layout.addWidget(self._create_form_row(tr("contact.detail.label.region", "Region"), self._create_region_row()))
        form_layout.addWidget(self._create_form_row(tr("contact.detail.label.email", "Email"), self.email_edit))
        self.email_code_label = CaptionLabel(tr("auth.field.email_code", "Email Verification Code"), self)
        form_layout.addWidget(self._create_form_row(self.email_code_label, self.email_code_row))
        form_layout.addWidget(self._create_form_row(tr("contact.detail.label.gender", "Gender"), self.gender_combo))

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.cancel_button = PushButton(tr("common.cancel", "Cancel"), self)
        self.save_button = PrimaryPushButton(tr("common.save", "Save"), self)
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._submit)
        button_row.addWidget(self.cancel_button, 0)
        button_row.addWidget(self.save_button, 0)

        layout.addWidget(subtitle)
        layout.addWidget(self.avatar_preview, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(avatar_actions)
        layout.addWidget(self.avatar_path_label)
        layout.addWidget(form_widget)
        layout.addStretch(1)
        layout.addLayout(button_row)
        self._sync_email_code_visibility()

    def closeEvent(self, event) -> None:
        self._cancel_email_code_task()
        super().closeEvent(event)

    def profile_payload(self) -> dict[str, str | bool | None]:
        """Return dialog values after acceptance."""
        return {
            "nickname": self.nickname_edit.text().strip(),
            "signature": self.signature_edit.text().strip(),
            "region": self._region_value(),
            "email": self.email_edit.text().strip(),
            "email_code": self.email_code_edit.text().strip() if self._email_changed() and self.email_edit.text().strip() else None,
            "gender": str(self.gender_combo.currentData() or ""),
            "avatar_file_path": self._avatar_file_path,
            "reset_avatar": self._reset_avatar_requested,
        }

    def _set_combo_value(self, combo: ComboBox, value: object) -> None:
        normalized = normalize_profile_choice(value)
        for index in range(combo.count()):
            if normalize_profile_choice(combo.itemData(index)) == normalized:
                combo.setCurrentIndex(index)
                return
        if combo.count() > 0:
            combo.setCurrentIndex(0)

    def _create_form_row(self, label: str | CaptionLabel, field: QWidget) -> QWidget:
        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(14)
        label_widget = label if isinstance(label, CaptionLabel) else CaptionLabel(label, row)
        label_widget.setFixedWidth(76)
        label_widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        field.setSizePolicy(QSizePolicy.Policy.Expanding, field.sizePolicy().verticalPolicy())
        row_layout.addWidget(label_widget, 0, Qt.AlignmentFlag.AlignVCenter)
        row_layout.addWidget(field, 1)
        return row

    def _create_region_row(self) -> QWidget:
        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        row_layout.addWidget(self.region_country_combo, 1)
        row_layout.addWidget(self.region_area_combo, 1)
        return row

    def _populate_region_country_combo(self, region: str) -> None:
        country, area = self._split_region_value(region)
        known_countries = {item[0] for item in _REGION_OPTIONS}
        for value, _areas in _REGION_OPTIONS:
            label = value or tr("profile.edit.region.empty", "Not set")
            self.region_country_combo.addItem(label, userData=value)
        if country and country not in known_countries:
            self.region_country_combo.addItem(country, userData=country)
        self._set_combo_value(self.region_country_combo, country)
        self._sync_region_area_options(area)

    def _sync_region_area_options(self, selected_area: str = "") -> None:
        country = str(self.region_country_combo.currentData() or "")
        previous_area = selected_area or str(self.region_area_combo.currentData() or "")
        areas = next((item_areas for item_country, item_areas in _REGION_OPTIONS if item_country == country), ("",))
        known_areas = set(areas)
        self.region_area_combo.clear()
        for value in areas:
            label = value or tr("profile.edit.region.area_empty", "Not set")
            self.region_area_combo.addItem(label, userData=value)
        if previous_area and previous_area not in known_areas:
            self.region_area_combo.addItem(previous_area, userData=previous_area)
        self._set_combo_value(self.region_area_combo, previous_area)

    @staticmethod
    def _split_region_value(region: str) -> tuple[str, str]:
        text = str(region or "").strip()
        if not text:
            return "", ""
        for country, areas in _REGION_OPTIONS:
            if not country:
                continue
            if text == country:
                return country, ""
            prefix = f"{country} "
            if text.startswith(prefix):
                return country, text[len(prefix) :].strip()
            if text in areas:
                return country, text
        return text, ""

    def _region_value(self) -> str:
        country = str(self.region_country_combo.currentData() or "").strip()
        area = str(self.region_area_combo.currentData() or "").strip()
        if country and area:
            return f"{country} {area}"
        return country or area

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

    def _email_changed(self) -> bool:
        return self.email_edit.text().strip().lower() != self._original_email

    def _sync_email_code_visibility(self, *_args) -> None:
        email_value = self.email_edit.text().strip().lower()
        show_code = self._email_changed() and bool(email_value)
        self.email_code_row.setVisible(show_code)
        if self.email_code_label is not None:
            self.email_code_label.setVisible(show_code)
        if not show_code:
            self.email_code_edit.clear()
        self._sync_email_send_button()

    def _sync_email_send_button(self) -> None:
        email_value = self.email_edit.text().strip().lower()
        valid_email = bool(email_value and _EMAIL_PATTERN.fullmatch(email_value))
        if self._email_code_busy:
            self.email_send_code_button.setDisabled(True)
            self.email_send_code_button.setText(tr("auth.button.send_email_code_busy", "Sending..."))
        elif self._email_countdown > 0:
            self.email_send_code_button.setDisabled(True)
            self.email_send_code_button.setText(
                tr("auth.button.send_email_code_countdown", "Resend ({seconds}s)", seconds=self._email_countdown)
            )
        else:
            self.email_send_code_button.setDisabled(not (self._email_changed() and valid_email))
            self.email_send_code_button.setText(tr("auth.button.send_email_code", "Send Code"))

    def _submit_email_code(self) -> None:
        email = self.email_edit.text().strip().lower()
        if not self._email_changed() or not email:
            return
        if not _EMAIL_PATTERN.fullmatch(email):
            InfoBar.warning(
                tr("profile.edit.title", "Edit Profile"),
                tr("profile.edit.email.invalid", "Please enter a valid email address."),
                parent=self,
                duration=1800,
            )
            self.email_edit.setFocus()
            return
        self._set_email_code_task(self._send_email_code_async(email))

    async def _send_email_code_async(self, email: str) -> None:
        self._email_code_busy = True
        self._sync_email_send_button()
        try:
            payload = await self._auth_controller.send_email_verification(email, purpose="profile_email")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Profile email verification request failed")
            InfoBar.error(
                tr("profile.edit.title", "Edit Profile"),
                tr("profile.edit.email_code_failed", "Unable to send the email verification code."),
                parent=self,
                duration=2400,
            )
        else:
            self._email_countdown = max(1, int(payload.get("cooldown_seconds") or 60))
            self._email_timer.start()
            InfoBar.success(
                tr("profile.edit.title", "Edit Profile"),
                tr("auth.success.email_code_sent", "Verification code sent."),
                parent=self,
                duration=1800,
            )
        finally:
            self._email_code_busy = False
            self._sync_email_send_button()

    def _tick_email_countdown(self) -> None:
        if self._email_countdown > 0:
            self._email_countdown -= 1
        if self._email_countdown <= 0:
            self._email_timer.stop()
        self._sync_email_send_button()

    def _set_email_code_task(self, coro) -> None:
        self._cancel_email_code_task()
        task = asyncio.create_task(coro)
        self._email_code_task = task
        task.add_done_callback(self._clear_email_code_task)

    def _clear_email_code_task(self, task: asyncio.Task) -> None:
        if self._email_code_task is task:
            self._email_code_task = None
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            pass

    def _cancel_email_code_task(self) -> None:
        self._email_timer.stop()
        if self._email_code_task is not None and not self._email_code_task.done():
            self._email_code_task.cancel()
        self._email_code_task = None

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

        if self._email_changed() and email_value:
            email_code = self.email_code_edit.text().strip()
            if len(email_code) != 6 or not email_code.isdigit():
                InfoBar.warning(
                    tr("profile.edit.title", "Edit Profile"),
                    tr("profile.edit.email_code.required", "Enter the 6-digit email verification code."),
                    parent=self,
                    duration=1800,
                )
                self.email_code_edit.setFocus()
                return

        self.accept()


class ProfileCard(QWidget):
    """Compact profile summary used at the top of the acrylic flyout."""

    editRequested = Signal()
    passwordChangeRequested = Signal()
    securityRequested = Signal()
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
        self.change_password_link = HyperlinkLabel(tr("profile.password.change.link", "Change Password"), self)
        self.security_link = HyperlinkLabel(tr("profile.security.link", "Account Security"), self)
        self.logout_link = HyperlinkLabel(tr("profile.quick.action.logout", "Sign Out"), self)
        self.edit_link.clicked.connect(self.editRequested.emit)
        self.change_password_link.clicked.connect(self.passwordChangeRequested.emit)
        self.security_link.clicked.connect(self.securityRequested.emit)
        self.logout_link.clicked.connect(self.logoutRequested.emit)
        action_row.addWidget(self.edit_link, 0)
        action_row.addWidget(self.change_password_link, 0)
        action_row.addWidget(self.security_link, 0)
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
    passwordChangeRequested = Signal()
    securityRequested = Signal()
    logoutRequested = Signal()

    def __init__(self, user: dict, parent=None):
        super().__init__(parent)
        self._user = dict(user or {})

        self.v_box_layout = QVBoxLayout(self)
        self.v_box_layout.setContentsMargins(20, 16, 20, 16)
        self.v_box_layout.setSpacing(16)

        self.profile_card = ProfileCard(self._user, self)
        self.profile_card.editRequested.connect(self.editRequested.emit)
        self.profile_card.passwordChangeRequested.connect(self.passwordChangeRequested.emit)
        self.profile_card.securityRequested.connect(self.securityRequested.emit)
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
        self._password_task: Optional[asyncio.Task] = None
        self._ui_tasks: set[asyncio.Task] = set()
        self._flyout = None
        self._device_dialog: Optional[DeviceSecurityDialog] = None
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
        view.passwordChangeRequested.connect(self._handle_password_change_from_flyout)
        view.securityRequested.connect(self._handle_security_from_flyout)
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

        dialog = ProfileEditDialog(user, self.window(), auth_controller=self._auth_controller)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._set_save_task(self._save_profile_async(dialog.profile_payload()))

    def open_password_change_dialog(self) -> None:
        """Open the authenticated password-change dialog."""
        if not self.current_user_snapshot() or self._password_task is not None:
            return

        dialog = ChangePasswordDialog(self.window())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._set_password_task(self._change_password_async(dialog.password_payload()))

    def open_device_security_dialog(self) -> None:
        """Open the readonly E2EE device inventory dialog."""
        if not self.current_user_snapshot():
            return
        if self._device_dialog is not None and self._device_dialog.isVisible():
            self._device_dialog.raise_()
            self._device_dialog.activateWindow()
            return

        dialog = DeviceSecurityDialog(self.window(), auth_controller=self._auth_controller)
        self._device_dialog = dialog
        dialog.finished.connect(lambda _result=0, dlg=dialog: self._clear_device_dialog(dlg))
        dialog.destroyed.connect(lambda *_args, dlg=dialog: self._clear_device_dialog(dlg))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

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

    def _handle_password_change_from_flyout(self) -> None:
        self._close_flyout()
        self.open_password_change_dialog()

    def _handle_security_from_flyout(self) -> None:
        self._close_flyout()
        self.open_device_security_dialog()

    def _handle_logout_from_flyout(self) -> None:
        self._close_flyout()
        self.request_logout()

    async def _change_password_async(self, payload: tuple[str, str]) -> None:
        current_password, new_password = payload
        try:
            await self._auth_controller.change_password(current_password, new_password)
        except asyncio.CancelledError:
            raise
        except Exception:
            InfoBar.error(
                tr("profile.password.change.title", "Change Password"),
                tr(
                    "profile.password.change.failed",
                    "Unable to change password. Check the current password and try again.",
                ),
                parent=self.window(),
                duration=2400,
            )
            raise
        else:
            InfoBar.success(
                tr("profile.password.change.title", "Change Password"),
                tr("profile.password.change.success", "Password changed."),
                parent=self.window(),
                duration=1800,
            )

    async def _save_profile_async(self, payload: dict[str, str | bool | None]) -> None:
        avatar_file_path = str(payload.get("avatar_file_path", "") or "").strip()
        reset_avatar = bool(payload.get("reset_avatar", False))

        try:
            update_result = await self._auth_controller.update_profile(
                nickname=str(payload.get("nickname", "") or "").strip(),
                signature=str(payload.get("signature", "") or "").strip(),
                region=str(payload.get("region", "") or "").strip(),
                email=str(payload.get("email", "") or "").strip(),
                email_code=str(payload.get("email_code", "") or "").strip() or None,
                gender=normalize_profile_gender(payload.get("gender")),
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

    def _detach_auth_state_listener(self) -> None:
        if not self._auth_listener_attached:
            return
        self._auth_controller.remove_auth_state_listener(self._handle_auth_state_changed)
        self._auth_listener_attached = False

    def _close_flyout(self) -> None:
        if self._flyout is not None:
            self._flyout.close()

    def _clear_flyout(self) -> None:
        self._flyout = None

    def _clear_device_dialog(self, dialog: DeviceSecurityDialog) -> None:
        if self._device_dialog is dialog:
            self._device_dialog = None

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

    def _set_password_task(self, coro) -> None:
        self._cancel_pending_task(self._password_task)
        self._password_task = self._create_ui_task(coro, "change password", on_done=self._clear_password_task)

    def _clear_password_task(self, task: asyncio.Task) -> None:
        if self._password_task is task:
            self._password_task = None

    def quiesce(self) -> None:
        """Cancel logout-sensitive UI work before the shell is destroyed."""
        self._detach_auth_state_listener()
        self._cancel_pending_task(self._save_task)
        self._save_task = None
        self._cancel_pending_task(self._password_task)
        self._password_task = None
        self._close_flyout()
        if self._device_dialog is not None:
            self._device_dialog.close()
            self._device_dialog = None
        for task in list(self._ui_tasks):
            if not task.done():
                task.cancel()

    def closeEvent(self, event) -> None:
        self.quiesce()
        super().closeEvent(event)

    def _on_destroyed(self, *_args) -> None:
        self._detach_auth_state_listener()
        self.quiesce()


