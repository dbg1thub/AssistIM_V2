"""Fluent authentication window for login and registration."""

from __future__ import annotations

import asyncio
import re
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    IconWidget,
    InfoBar,
    LineEdit,
    MessageBoxBase,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    SegmentedWidget,
    SubtitleLabel,
    TitleLabel,
    FluentWidget,
)

from client.core.app_icons import AppIcon
from client.core import logging
from client.core.exceptions import APIError, NetworkError
from client.core.i18n import tr
from client.core.logging import setup_logging
from client.ui.styles import StyleSheet
from client.ui.controllers.auth_controller import get_auth_controller


setup_logging()
logger = logging.get_logger(__name__)

SESSION_CONFLICT_ERROR_CODE = 1009
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SessionConflictDialog(MessageBoxBase):
    """Confirm whether a new login should replace the current online session."""

    def __init__(self, username: str, parent=None):
        super().__init__(parent=parent)
        title = SubtitleLabel(tr("auth.session_conflict.title", "Account Already Online"), self.widget)
        content = BodyLabel(
            tr(
                "auth.session_conflict.content",
                "{username} is currently signed in on another client. Continue here and sign out the other client?",
                username=username or tr("auth.field.username", "this account"),
            ),
            self.widget,
        )
        content.setWordWrap(True)

        self.viewLayout.addWidget(title)
        self.viewLayout.addWidget(content)
        self.viewLayout.addStretch(1)

        self.yesButton.setText(tr("auth.session_conflict.confirm", "Continue Login"))
        self.cancelButton.setText(tr("common.cancel", "Cancel"))
        self.widget.setMinimumWidth(400)


class PasswordResetDialog(QDialog):
    """Password-reset dialog driven by email verification."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._countdown = 0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick_countdown)
        self.finished.connect(lambda _result: self._timer.stop())

        self.setWindowTitle(tr("auth.password_reset.title", "Reset Password"))
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = SubtitleLabel(tr("auth.password_reset.title", "Reset Password"), self)
        copy = CaptionLabel(
            tr("auth.password_reset.copy", "Use your verified email to reset the account password."),
            self,
        )
        copy.setWordWrap(True)

        self.email_edit = LineEdit(self)
        self.email_edit.setPlaceholderText(tr("auth.field.email", "Email"))
        self.email_edit.setMinimumHeight(40)

        code_row = QWidget(self)
        code_layout = QHBoxLayout(code_row)
        code_layout.setContentsMargins(0, 0, 0, 0)
        code_layout.setSpacing(8)
        self.code_edit = LineEdit(code_row)
        self.code_edit.setPlaceholderText(tr("auth.field.email_code", "Email Verification Code"))
        self.code_edit.setMaxLength(6)
        self.code_edit.setMinimumHeight(40)
        self.send_code_button = PushButton(tr("auth.button.send_email_code", "Send Code"), code_row)
        self.send_code_button.setMinimumHeight(40)
        code_layout.addWidget(self.code_edit, 1)
        code_layout.addWidget(self.send_code_button, 0)

        self.password_edit = PasswordLineEdit(self)
        self.password_edit.setPlaceholderText(tr("auth.field.new_password", "New Password"))
        self.password_edit.setMinimumHeight(40)

        self.confirm_edit = PasswordLineEdit(self)
        self.confirm_edit.setPlaceholderText(tr("auth.field.confirm_password", "Confirm Password"))
        self.confirm_edit.setMinimumHeight(40)

        button_row = QWidget(self)
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(8)
        button_layout.addStretch(1)
        self.cancel_button = PushButton(tr("common.cancel", "Cancel"), button_row)
        self.reset_button = PrimaryPushButton(tr("auth.password_reset.confirm", "Reset Password"), button_row)
        self.cancel_button.setMinimumHeight(36)
        self.reset_button.setMinimumHeight(36)
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.reset_button)

        layout.addWidget(title)
        layout.addWidget(copy)
        layout.addWidget(self.email_edit)
        layout.addWidget(code_row)
        layout.addWidget(self.password_edit)
        layout.addWidget(self.confirm_edit)
        layout.addSpacing(4)
        layout.addWidget(button_row)

    def set_send_busy(self, busy: bool) -> None:
        self.send_code_button.setDisabled(busy)
        self.send_code_button.setText(
            tr("auth.button.send_email_code_busy", "Sending...")
            if busy
            else tr("auth.button.send_email_code", "Send Code")
        )

    def set_reset_busy(self, busy: bool) -> None:
        for widget in (self.email_edit, self.code_edit, self.password_edit, self.confirm_edit, self.reset_button):
            widget.setDisabled(busy)
        if busy:
            self.send_code_button.setDisabled(True)
            self.reset_button.setText(tr("auth.password_reset.busy", "Resetting..."))
        else:
            self.reset_button.setText(tr("auth.password_reset.confirm", "Reset Password"))
            self._sync_send_button()

    def start_countdown(self, seconds: int) -> None:
        self._countdown = max(1, int(seconds or 60))
        self._timer.start()
        self._sync_send_button()

    def _tick_countdown(self) -> None:
        if self._countdown > 0:
            self._countdown -= 1
        if self._countdown <= 0:
            self._timer.stop()
        self._sync_send_button()

    def _sync_send_button(self) -> None:
        if self._countdown > 0:
            self.send_code_button.setDisabled(True)
            self.send_code_button.setText(
                tr("auth.button.send_email_code_countdown", "Resend ({seconds}s)", seconds=self._countdown)
            )
        else:
            self.send_code_button.setDisabled(False)
            self.send_code_button.setText(tr("auth.button.send_email_code", "Send Code"))



class AuthInterface(FluentWidget):
    """Authentication window styled with Win11 Fluent spacing and controls."""

    authenticated = Signal(dict)
    closed = Signal()

    OUTER_MARGIN = 32
    PANEL_GAP = 24
    SECTION_GAP = 24
    FIELD_GAP = 12
    CARD_RADIUS = 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auth_controller = get_auth_controller()
        self._submit_task: Optional[asyncio.Task] = None
        self._ui_tasks: set[asyncio.Task] = set()
        self._busy_mode: Optional[str] = None
        self._submit_commit_in_progress = False
        self._centered_once = False
        self._transient_dialogs: set[QDialog] = set()
        self._auth_committed = False
        self._email_code_countdown = 0
        self._email_code_timer = QTimer(self)
        self._email_code_timer.setInterval(1000)
        self._email_code_timer.timeout.connect(self._tick_email_code_countdown)
        self.last_success_message = ""

        self._setup_ui()
        self._connect_signals()
        self._switch_to(self.login_page)
        self.destroyed.connect(self._on_destroyed)

    def _setup_ui(self) -> None:
        self.setObjectName("AuthInterface")
        self.setWindowTitle(tr("common.app_name", "AssistIM"))
        self.resize(980, 640)
        self.setMinimumSize(920, 580)

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(
            self.OUTER_MARGIN,
            self.OUTER_MARGIN,
            self.OUTER_MARGIN,
            self.OUTER_MARGIN,
        )
        root_layout.setSpacing(self.PANEL_GAP)

        self.brand_card = CardWidget(self)
        self.brand_card.setObjectName("brandCard")
        self.brand_card.setMinimumWidth(320)
        self.brand_card.setMaximumWidth(360)
        brand_layout = QVBoxLayout(self.brand_card)
        brand_layout.setContentsMargins(32, 32, 32, 32)
        brand_layout.setSpacing(16)

        self.brand_icon = IconWidget(AppIcon.CHAT, self.brand_card)
        self.brand_icon.setFixedSize(52, 52)

        brand_title = TitleLabel(tr("common.app_name", "AssistIM"), self.brand_card)
        brand_subtitle = SubtitleLabel(
            tr("auth.brand.subtitle", "Desktop messaging with AI assistance"),
            self.brand_card,
        )
        brand_copy = BodyLabel(
            tr(
                "auth.brand.copy",
                "Sign in to sync conversations, reconnect WebSocket messaging, and continue the same account across devices.",
            ),
            self.brand_card,
        )
        brand_copy.setWordWrap(True)

        brand_feature_1 = CaptionLabel(
            tr("auth.brand.feature.token_storage", "Encrypted local token storage via Windows DPAPI"),
            self.brand_card,
        )
        brand_feature_2 = CaptionLabel(
            tr("auth.brand.feature.fast_login", "Fast login, register, and session restore flow"),
            self.brand_card,
        )
        brand_feature_3 = CaptionLabel(
            tr("auth.brand.feature.fluent_layout", "Fluent layout tuned to Win11 spacing rhythm"),
            self.brand_card,
        )

        for label in (brand_feature_1, brand_feature_2, brand_feature_3):
            label.setWordWrap(True)

        brand_layout.addWidget(self.brand_icon, 0, Qt.AlignmentFlag.AlignLeft)
        brand_layout.addSpacing(4)
        brand_layout.addWidget(brand_title)
        brand_layout.addWidget(brand_subtitle)
        brand_layout.addSpacing(8)
        brand_layout.addWidget(brand_copy)
        brand_layout.addSpacing(4)
        brand_layout.addWidget(brand_feature_1)
        brand_layout.addWidget(brand_feature_2)
        brand_layout.addWidget(brand_feature_3)
        brand_layout.addStretch(1)

        self.form_card = CardWidget(self)
        self.form_card.setObjectName("formCard")
        self.form_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        form_layout = QVBoxLayout(self.form_card)
        form_layout.setContentsMargins(40, 36, 40, 36)
        form_layout.setSpacing(self.SECTION_GAP)

        self.form_title = TitleLabel(tr("auth.form.access_title", "Account Access"), self.form_card)
        self.form_subtitle = CaptionLabel(
            tr("auth.form.access_subtitle", "Use your AssistIM backend account to enter the desktop client."),
            self.form_card,
        )
        self.form_subtitle.setWordWrap(True)

        self.page_switcher = SegmentedWidget(self.form_card)
        self.form_pages = QStackedWidget(self.form_card)

        self.login_page = self._build_login_page()
        self.register_page = self._build_register_page()
        self.form_pages.addWidget(self.login_page)
        self.form_pages.addWidget(self.register_page)

        self.page_switcher.addItem(
            routeKey=self.login_page.objectName(),
            text=tr("auth.switch.sign_in", "Sign In"),
            onClick=lambda: self._switch_to(self.login_page),
        )
        self.page_switcher.addItem(
            routeKey=self.register_page.objectName(),
            text=tr("auth.switch.create_account", "Create Account"),
            onClick=lambda: self._switch_to(self.register_page),
        )

        form_layout.addWidget(self.form_title)
        form_layout.addWidget(self.form_subtitle)
        form_layout.addWidget(self.page_switcher, 0, Qt.AlignmentFlag.AlignLeft)
        form_layout.addWidget(self.form_pages, 1)

        root_layout.addWidget(self.brand_card, 0)
        root_layout.addWidget(self.form_card, 1)

        StyleSheet.AUTH_INTERFACE.apply(self)

    def _build_login_page(self) -> QWidget:
        page = QWidget(self.form_pages)
        page.setObjectName("loginPage")

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(self.FIELD_GAP)

        intro = SubtitleLabel(tr("auth.login.welcome_back", "Welcome Back"), page)
        copy = CaptionLabel(
            tr("auth.login.copy", "Enter your username and password to restore synced chat access."),
            page,
        )
        copy.setWordWrap(True)

        self.login_username_edit = LineEdit(page)
        self._configure_text_field(self.login_username_edit, tr("auth.field.username", "Username"))

        self.login_password_edit = PasswordLineEdit(page)
        self._configure_text_field(self.login_password_edit, tr("auth.field.password", "Password"))

        self.login_button = PrimaryPushButton(tr("auth.button.sign_in", "Sign In"), page)
        self.login_button.setMinimumHeight(40)

        forgot_row = QWidget(page)
        forgot_layout = QHBoxLayout(forgot_row)
        forgot_layout.setContentsMargins(0, 0, 0, 0)
        forgot_layout.addStretch(1)
        self.forgot_password_button = PushButton(tr("auth.password_reset.link", "Forgot Password"), forgot_row)
        forgot_layout.addWidget(self.forgot_password_button)

        self.login_hint = CaptionLabel(
            tr(
                "auth.login.hint",
                "Your access and refresh tokens are saved locally with Windows DPAPI encryption.",
            ),
            page,
        )
        self.login_hint.setWordWrap(True)

        layout.addWidget(intro)
        layout.addWidget(copy)
        layout.addSpacing(8)
        layout.addWidget(self.login_username_edit)
        layout.addWidget(self.login_password_edit)
        layout.addSpacing(8)
        layout.addWidget(self.login_button)
        layout.addWidget(forgot_row)
        layout.addStretch(1)
        layout.addWidget(self.login_hint)
        return page

    def _build_register_page(self) -> QWidget:
        page = QWidget(self.form_pages)
        page.setObjectName("registerPage")

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(self.FIELD_GAP)

        intro = SubtitleLabel(tr("auth.register.title", "Create a New Account"), page)
        copy = CaptionLabel(
            tr(
                "auth.register.copy",
                "Registration will create the account and return an authenticated session immediately.",
            ),
            page,
        )
        copy.setWordWrap(True)

        self.register_username_edit = LineEdit(page)
        self._configure_text_field(self.register_username_edit, tr("auth.field.username", "Username"))

        self.register_nickname_edit = LineEdit(page)
        self._configure_text_field(self.register_nickname_edit, tr("auth.field.nickname", "Nickname"))

        self.register_email_edit = LineEdit(page)
        self._configure_text_field(self.register_email_edit, tr("auth.field.email", "Email"))

        code_row = QWidget(page)
        code_layout = QHBoxLayout(code_row)
        code_layout.setContentsMargins(0, 0, 0, 0)
        code_layout.setSpacing(8)
        self.register_email_code_edit = LineEdit(code_row)
        self._configure_text_field(self.register_email_code_edit, tr("auth.field.email_code", "Email Verification Code"))
        self.register_email_code_edit.setMaxLength(6)
        self.register_send_code_button = PushButton(tr("auth.button.send_email_code", "Send Code"), code_row)
        self.register_send_code_button.setMinimumHeight(40)
        code_layout.addWidget(self.register_email_code_edit, 1)
        code_layout.addWidget(self.register_send_code_button, 0)

        self.register_password_edit = PasswordLineEdit(page)
        self._configure_text_field(self.register_password_edit, tr("auth.field.password", "Password"))

        self.register_confirm_edit = PasswordLineEdit(page)
        self._configure_text_field(
            self.register_confirm_edit,
            tr("auth.field.confirm_password", "Confirm Password"),
        )

        self.register_button = PrimaryPushButton(tr("auth.button.create_account", "Create Account"), page)
        self.register_button.setMinimumHeight(40)

        self.register_hint = CaptionLabel(
            tr(
                "auth.register.hint",
                "Keep the password strong. The backend will return fresh access and refresh tokens after registration.",
            ),
            page,
        )
        self.register_hint.setWordWrap(True)

        layout.addWidget(intro)
        layout.addWidget(copy)
        layout.addSpacing(8)
        layout.addWidget(self.register_username_edit)
        layout.addWidget(self.register_nickname_edit)
        layout.addWidget(self.register_email_edit)
        layout.addWidget(code_row)
        layout.addWidget(self.register_password_edit)
        layout.addWidget(self.register_confirm_edit)
        layout.addSpacing(8)
        layout.addWidget(self.register_button)
        layout.addStretch(1)
        layout.addWidget(self.register_hint)
        return page

    def _configure_text_field(self, widget: QWidget, placeholder: str) -> None:
        widget.setPlaceholderText(placeholder)
        widget.setMinimumHeight(40)
        if hasattr(widget, "setClearButtonEnabled"):
            widget.setClearButtonEnabled(True)

    def _connect_signals(self) -> None:
        self.form_pages.currentChanged.connect(self._sync_switcher)
        self.login_button.clicked.connect(self._submit_login)
        self.forgot_password_button.clicked.connect(self._show_password_reset_dialog)
        self.register_button.clicked.connect(self._submit_register)
        self.register_send_code_button.clicked.connect(self._submit_register_email_code)

        self.login_username_edit.returnPressed.connect(self._submit_login)
        self.login_password_edit.returnPressed.connect(self._submit_login)

        self.register_username_edit.returnPressed.connect(self._submit_register)
        self.register_nickname_edit.returnPressed.connect(self._submit_register)
        self.register_email_edit.returnPressed.connect(self._submit_register_email_code)
        self.register_email_code_edit.returnPressed.connect(self._submit_register)
        self.register_password_edit.returnPressed.connect(self._submit_register)
        self.register_confirm_edit.returnPressed.connect(self._submit_register)

    def _switch_to(self, page: QWidget) -> None:
        self.form_pages.setCurrentWidget(page)
        self.page_switcher.setCurrentItem(page.objectName())
        self._clear_validation_state()

        if page is self.login_page:
            self.form_title.setText(tr("auth.form.access_title", "Account Access"))
            self.form_subtitle.setText(
                tr("auth.form.access_subtitle", "Use your AssistIM backend account to enter the desktop client.")
            )
            self.login_username_edit.setFocus()
        else:
            self.form_title.setText(tr("auth.form.create_title", "Create Your Account"))
            self.form_subtitle.setText(
                tr(
                    "auth.form.create_subtitle",
                    "Register a new desktop account and continue without a second sign-in step.",
                )
            )
            self.register_username_edit.setFocus()

    def _sync_switcher(self, index: int) -> None:
        page = self.form_pages.widget(index)
        if page is not None:
            self.page_switcher.setCurrentItem(page.objectName())

    def _set_busy(self, mode: Optional[str]) -> None:
        self._busy_mode = mode
        is_busy = mode is not None

        for widget in (
            self.page_switcher,
            self.login_username_edit,
            self.login_password_edit,
            self.forgot_password_button,
            self.register_username_edit,
            self.register_nickname_edit,
            self.register_email_edit,
            self.register_email_code_edit,
            self.register_password_edit,
            self.register_confirm_edit,
            self.register_send_code_button,
            self.login_button,
            self.register_button,
        ):
            widget.setDisabled(is_busy)

        self.login_button.setText(
            tr("auth.button.sign_in_busy", "Signing In...")
            if mode == "login"
            else tr("auth.button.sign_in", "Sign In")
        )
        self.register_button.setText(
            tr("auth.button.create_account_busy", "Creating Account...")
            if mode == "register"
            else tr("auth.button.create_account", "Create Account")
        )
        if not is_busy:
            self._sync_email_code_button()

    def _clear_validation_state(self) -> None:
        for widget in (
            self.login_username_edit,
            self.login_password_edit,
            self.register_username_edit,
            self.register_nickname_edit,
            self.register_email_edit,
            self.register_email_code_edit,
            self.register_password_edit,
            self.register_confirm_edit,
        ):
            if hasattr(widget, "setError"):
                widget.setError(False)

    def _mark_invalid(self, widget: QWidget, message: str) -> None:
        if hasattr(widget, "setError"):
            widget.setError(True)
        widget.setFocus()
        self._show_error(message)

    def _submit_login(self) -> None:
        if self._busy_mode:
            return

        self._clear_validation_state()
        username = self.login_username_edit.text().strip()
        password = self.login_password_edit.text()

        if not username:
            self._mark_invalid(self.login_username_edit, tr("auth.validation.username_required", "Username is required."))
            return

        if not password:
            self._mark_invalid(self.login_password_edit, tr("auth.validation.password_required", "Password is required."))
            return

        self._set_submit_task(self._perform_login(username, password))

    def _submit_register_email_code(self) -> None:
        if self._busy_mode or self._email_code_countdown > 0:
            return

        self._clear_validation_state()
        email = self.register_email_edit.text().strip().lower()
        if not EMAIL_PATTERN.fullmatch(email):
            self._mark_invalid(self.register_email_edit, tr("auth.validation.email_invalid", "Enter a valid email address."))
            return

        self._create_ui_task(self._perform_send_register_code(email), "send register email code")

    def _show_password_reset_dialog(self) -> None:
        if self._busy_mode:
            return
        dialog = PasswordResetDialog(self)
        candidate_email = self.login_username_edit.text().strip().lower()
        if EMAIL_PATTERN.fullmatch(candidate_email):
            dialog.email_edit.setText(candidate_email)
        self._transient_dialogs.add(dialog)
        dialog.finished.connect(lambda _result, item=dialog: self._transient_dialogs.discard(item))
        dialog.cancel_button.clicked.connect(dialog.reject)
        dialog.send_code_button.clicked.connect(lambda _checked=False, item=dialog: self._submit_password_reset_code(item))
        dialog.reset_button.clicked.connect(lambda _checked=False, item=dialog: self._submit_password_reset(item))
        dialog.open()

    def _submit_password_reset_code(self, dialog: PasswordResetDialog) -> None:
        email = dialog.email_edit.text().strip().lower()
        if not EMAIL_PATTERN.fullmatch(email):
            self._mark_invalid(dialog.email_edit, tr("auth.validation.email_invalid", "Enter a valid email address."))
            return
        self._create_ui_task(self._perform_send_password_reset_code(dialog, email), "send password reset code")

    def _submit_password_reset(self, dialog: PasswordResetDialog) -> None:
        email = dialog.email_edit.text().strip().lower()
        email_code = dialog.code_edit.text().strip()
        new_password = dialog.password_edit.text()
        confirm = dialog.confirm_edit.text()

        if not EMAIL_PATTERN.fullmatch(email):
            self._mark_invalid(dialog.email_edit, tr("auth.validation.email_invalid", "Enter a valid email address."))
            return
        if len(email_code) != 6 or not email_code.isdigit():
            self._mark_invalid(
                dialog.code_edit,
                tr("auth.validation.email_code_required", "Enter the 6-digit email verification code."),
            )
            return
        if len(new_password) < 6:
            self._mark_invalid(
                dialog.password_edit,
                tr("auth.validation.password_min_length", "Password must be at least 6 characters."),
            )
            return
        if new_password != confirm:
            self._mark_invalid(
                dialog.confirm_edit,
                tr("auth.validation.password_mismatch", "Passwords do not match."),
            )
            return
        self._create_ui_task(
            self._perform_password_reset(dialog, email, email_code, new_password),
            "password reset",
        )

    def _submit_register(self) -> None:
        if self._busy_mode:
            return

        self._clear_validation_state()
        username = self.register_username_edit.text().strip()
        nickname = self.register_nickname_edit.text().strip()
        email = self.register_email_edit.text().strip().lower()
        email_code = self.register_email_code_edit.text().strip()
        password = self.register_password_edit.text()
        confirm = self.register_confirm_edit.text()

        if len(username) < 3:
            self._mark_invalid(
                self.register_username_edit,
                tr("auth.validation.username_min_length", "Username must be at least 3 characters."),
            )
            return

        if not nickname:
            self._mark_invalid(self.register_nickname_edit, tr("auth.validation.nickname_required", "Nickname is required."))
            return

        if not EMAIL_PATTERN.fullmatch(email):
            self._mark_invalid(self.register_email_edit, tr("auth.validation.email_invalid", "Enter a valid email address."))
            return

        if len(email_code) != 6 or not email_code.isdigit():
            self._mark_invalid(
                self.register_email_code_edit,
                tr("auth.validation.email_code_required", "Enter the 6-digit email verification code."),
            )
            return

        if len(password) < 6:
            self._mark_invalid(
                self.register_password_edit,
                tr("auth.validation.password_min_length", "Password must be at least 6 characters."),
            )
            return

        if password != confirm:
            self._mark_invalid(
                self.register_confirm_edit,
                tr("auth.validation.password_mismatch", "Passwords do not match."),
            )
            return

        self._set_submit_task(self._perform_register(username, nickname, password, email, email_code))

    async def _perform_login(self, username: str, password: str, *, force: bool = False) -> None:
        retry_force_login = False
        self._set_busy("login")
        try:
            payload = await self._auth_controller.request_login_payload(username, password, force=force)
            self._submit_commit_in_progress = True
            user = await self._auth_controller.commit_auth_payload(payload, reset_local_chat_state=True)
        except asyncio.CancelledError:
            raise
        except NetworkError as exc:
            logger.warning("Login failed: %s", exc)
            self._show_error(
                tr("auth.error.network", "Unable to connect right now. Please try again later.")
            )
        except APIError as exc:
            if not force and self._is_session_conflict_error(exc):
                logger.info("Login conflict detected for %s", username)
                retry_force_login = await self._prompt_force_login(username)
            else:
                logger.warning("Login failed: %s", exc)
                self._show_error(
                    tr(
                        "auth.error.sign_in_failed",
                        "Unable to sign in with the current account information.",
                    )
                )
        except Exception:
            logger.exception("Unexpected login error")
            self._show_error(tr("auth.error.unexpected_sign_in", "Unexpected error while signing in."))
        else:
            self.last_success_message = tr(
                "auth.success.welcome_back",
                "Welcome back, {name}",
                name=user.get("nickname") or user.get("username", ""),
            )
            self._auth_committed = True
            self.authenticated.emit(user)
        finally:
            self._submit_commit_in_progress = False
            if not self._auth_committed:
                self._set_busy(None)

        if retry_force_login:
            self._set_submit_task(self._perform_login(username, password, force=True))

    @staticmethod
    def _is_session_conflict_error(exc: APIError) -> bool:
        """Return whether an auth error asks the user to confirm replacing another session."""
        return int(getattr(exc, "status_code", 0) or 0) == 409 and int(getattr(exc, "code", 0) or 0) == SESSION_CONFLICT_ERROR_CODE

    async def _prompt_force_login(self, username: str) -> bool:
        """Ask whether the current login should replace the already-online client."""
        dialog = SessionConflictDialog(username, self)
        dialog.setModal(True)
        loop = asyncio.get_running_loop()
        decision = loop.create_future()
        self._transient_dialogs.add(dialog)

        def _finish(result: int) -> None:
            self._transient_dialogs.discard(dialog)
            if not decision.done():
                decision.set_result(result == int(QDialog.DialogCode.Accepted))

        dialog.finished.connect(_finish)
        dialog.open()
        return bool(await decision)

    async def _perform_send_register_code(self, email: str) -> None:
        self.register_send_code_button.setDisabled(True)
        self.register_send_code_button.setText(tr("auth.button.send_email_code_busy", "Sending..."))
        try:
            payload = await self._auth_controller.send_email_verification(email)
        except asyncio.CancelledError:
            raise
        except NetworkError as exc:
            logger.warning("Email verification request failed: %s", exc)
            self._show_error(tr("auth.error.network", "Unable to connect right now. Please try again later."))
            self._sync_email_code_button()
        except APIError as exc:
            logger.warning("Email verification request failed: %s", exc)
            self._show_error(
                tr(
                    "auth.error.email_code_failed",
                    "Unable to send the email verification code. Check the email address and try again.",
                )
            )
            self._sync_email_code_button()
        except Exception:
            logger.exception("Unexpected email verification error")
            self._show_error(tr("auth.error.email_code_unexpected", "Unexpected error while sending email code."))
            self._sync_email_code_button()
        else:
            cooldown = int(payload.get("cooldown_seconds") or 60)
            self._start_email_code_countdown(cooldown)
            InfoBar.success(
                tr("auth.feedback.title", "Authentication"),
                tr("auth.success.email_code_sent", "Verification code sent."),
                parent=self.form_card,
            )

    async def _perform_send_password_reset_code(self, dialog: PasswordResetDialog, email: str) -> None:
        dialog.set_send_busy(True)
        try:
            payload = await self._auth_controller.send_password_reset_code(email)
        except asyncio.CancelledError:
            raise
        except NetworkError as exc:
            logger.warning("Password reset code request failed: %s", exc)
            self._show_error(tr("auth.error.network", "Unable to connect right now. Please try again later."))
            dialog.set_send_busy(False)
        except APIError as exc:
            logger.warning("Password reset code request failed: %s", exc)
            self._show_error(
                tr(
                    "auth.error.email_code_failed",
                    "Unable to send the email verification code. Check the email address and try again.",
                )
            )
            dialog.set_send_busy(False)
        except Exception:
            logger.exception("Unexpected password reset code error")
            self._show_error(tr("auth.error.email_code_unexpected", "Unexpected error while sending email code."))
            dialog.set_send_busy(False)
        else:
            cooldown = int(payload.get("cooldown_seconds") or 60)
            dialog.start_countdown(cooldown)
            InfoBar.success(
                tr("auth.feedback.title", "Authentication"),
                tr("auth.success.email_code_sent", "Verification code sent."),
                parent=self.form_card,
            )

    async def _perform_password_reset(
        self,
        dialog: PasswordResetDialog,
        email: str,
        email_code: str,
        new_password: str,
    ) -> None:
        dialog.set_reset_busy(True)
        try:
            await self._auth_controller.reset_password(email, email_code, new_password)
        except asyncio.CancelledError:
            raise
        except NetworkError as exc:
            logger.warning("Password reset failed: %s", exc)
            self._show_error(tr("auth.error.network", "Unable to connect right now. Please try again later."))
            dialog.set_reset_busy(False)
        except APIError as exc:
            logger.warning("Password reset failed: %s", exc)
            self._show_error(
                tr(
                    "auth.error.password_reset_failed",
                    "Unable to reset the password. Check the code and try again.",
                )
            )
            dialog.set_reset_busy(False)
        except Exception:
            logger.exception("Unexpected password reset error")
            self._show_error(tr("auth.error.password_reset_unexpected", "Unexpected error while resetting password."))
            dialog.set_reset_busy(False)
        else:
            InfoBar.success(
                tr("auth.feedback.title", "Authentication"),
                tr("auth.success.password_reset", "Password reset. Sign in with the new password."),
                parent=self.form_card,
            )
            dialog.accept()

    async def _perform_register(self, username: str, nickname: str, password: str, email: str, email_code: str) -> None:
        self._set_busy("register")
        try:
            payload = await self._auth_controller.request_register_payload(username, nickname, password, email, email_code)
            self._submit_commit_in_progress = True
            user = await self._auth_controller.commit_auth_payload(payload, reset_local_chat_state=True)
        except asyncio.CancelledError:
            raise
        except (APIError, NetworkError) as exc:
            logger.warning("Registration failed: %s", exc)
            if isinstance(exc, NetworkError):
                self._show_error(
                    tr("auth.error.network", "Unable to connect right now. Please try again later.")
                )
            else:
                self._show_error(
                    tr(
                        "auth.error.register_failed",
                        "Unable to create the account right now. Please try again later.",
                    )
                )
        except Exception:
            logger.exception("Unexpected registration error")
            self._show_error(tr("auth.error.unexpected_register", "Unexpected error while creating account."))
        else:
            self.last_success_message = tr(
                "auth.success.account_created",
                "Account created for {name}",
                name=user.get("nickname") or user.get("username", ""),
            )
            self._auth_committed = True
            self.authenticated.emit(user)
        finally:
            self._submit_commit_in_progress = False
            if not self._auth_committed:
                self._set_busy(None)

    def _start_email_code_countdown(self, seconds: int) -> None:
        self._email_code_countdown = max(1, int(seconds or 60))
        self._email_code_timer.start()
        self._sync_email_code_button()

    def _tick_email_code_countdown(self) -> None:
        if self._email_code_countdown > 0:
            self._email_code_countdown -= 1
        if self._email_code_countdown <= 0:
            self._email_code_timer.stop()
        self._sync_email_code_button()

    def _sync_email_code_button(self) -> None:
        if self._busy_mode:
            return
        if self._email_code_countdown > 0:
            self.register_send_code_button.setDisabled(True)
            self.register_send_code_button.setText(
                tr("auth.button.send_email_code_countdown", "Resend ({seconds}s)", seconds=self._email_code_countdown)
            )
        else:
            self.register_send_code_button.setDisabled(False)
            self.register_send_code_button.setText(tr("auth.button.send_email_code", "Send Code"))

    def _show_error(self, message: str) -> None:
        InfoBar.error(tr("auth.feedback.title", "Authentication"), message, parent=self.form_card)


    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._centered_once:
            return

        self._centered_once = True
        screen = QApplication.primaryScreen()
        if not screen:
            return

        geometry = screen.availableGeometry()
        self.move(
            geometry.center().x() - self.width() // 2,
            geometry.center().y() - self.height() // 2,
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._submit_commit_in_progress:
            event.ignore()
            return
        if not self._auth_committed:
            self._cancel_pending_task(self._submit_task)
            self.closed.emit()
        super().closeEvent(event)

    def has_committed_auth(self) -> bool:
        """Return whether this auth shell has already committed one login/register result."""
        return self._auth_committed

    def _on_destroyed(self, *_args) -> None:
        """Cancel outstanding submit work when the widget is torn down."""
        self._email_code_timer.stop()
        self._cancel_pending_task(self._submit_task)
        self._submit_task = None
        for dialog in list(self._transient_dialogs):
            dialog.close()
        self._transient_dialogs.clear()
        for task in list(self._ui_tasks):
            if not task.done():
                task.cancel()

    def _cancel_pending_task(self, task: Optional[asyncio.Task]) -> None:
        """Cancel a tracked task if it is still running."""
        if task is not None and not task.done():
            task.cancel()

    def _create_ui_task(self, coro, context: str, *, on_done=None) -> asyncio.Task:
        """Track auth coroutines for consistent cleanup and error logging."""
        task = asyncio.create_task(coro)
        self._ui_tasks.add(task)
        task.add_done_callback(lambda finished, name=context, callback=on_done: self._finalize_ui_task(finished, name, callback))
        return task

    def _finalize_ui_task(self, task: asyncio.Task, context: str, on_done=None) -> None:
        """Drop bookkeeping and report task failures."""
        self._ui_tasks.discard(task)
        if on_done is not None:
            on_done(task)

        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("AuthInterface task failed: %s", context)

    def _set_submit_task(self, coro) -> None:
        """Keep only the latest auth submit task alive."""
        self._cancel_pending_task(self._submit_task)
        self._submit_task = self._create_ui_task(coro, "auth submit", on_done=self._clear_submit_task)

    def _clear_submit_task(self, task: asyncio.Task) -> None:
        """Clear the tracked submit task when it finishes."""
        if self._submit_task is task:
            self._submit_task = None
