"""Fluent authentication window for login and registration."""

from __future__ import annotations

import asyncio
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
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
    FluentIcon,
    IconWidget,
    InfoBar,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    SegmentedWidget,
    SubtitleLabel,
    TitleLabel,
    FluentWidget,
)

from client.core import logging
from client.core.exceptions import APIError, NetworkError
from client.core.i18n import tr
from client.core.logging import setup_logging
from client.ui.styles import StyleSheet
from client.ui.controllers.auth_controller import get_auth_controller


setup_logging()
logger = logging.get_logger(__name__)


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
        self._centered_once = False

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

        self.brand_icon = IconWidget(FluentIcon.CHAT, self.brand_card)
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
        self.register_button.clicked.connect(self._submit_register)

        self.login_username_edit.returnPressed.connect(self._submit_login)
        self.login_password_edit.returnPressed.connect(self._submit_login)

        self.register_username_edit.returnPressed.connect(self._submit_register)
        self.register_nickname_edit.returnPressed.connect(self._submit_register)
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
            self.register_username_edit,
            self.register_nickname_edit,
            self.register_password_edit,
            self.register_confirm_edit,
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

    def _clear_validation_state(self) -> None:
        for widget in (
            self.login_username_edit,
            self.login_password_edit,
            self.register_username_edit,
            self.register_nickname_edit,
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

    def _submit_register(self) -> None:
        if self._busy_mode:
            return

        self._clear_validation_state()
        username = self.register_username_edit.text().strip()
        nickname = self.register_nickname_edit.text().strip()
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

        self._set_submit_task(self._perform_register(username, nickname, password))

    async def _perform_login(self, username: str, password: str) -> None:
        self._set_busy("login")
        try:
            user = await self._auth_controller.login(username, password)
        except asyncio.CancelledError:
            raise
        except (APIError, NetworkError) as exc:
            logger.warning("Login failed: %s", exc)
            self._show_error(str(exc))
        except Exception:
            logger.exception("Unexpected login error")
            self._show_error(tr("auth.error.unexpected_sign_in", "Unexpected error while signing in."))
        else:
            self._show_success(
                tr(
                    "auth.success.welcome_back",
                    "Welcome back, {name}",
                    name=user.get("nickname") or user.get("username", ""),
                )
            )
            self.authenticated.emit(user)
            self.close()
        finally:
            self._set_busy(None)

    async def _perform_register(self, username: str, nickname: str, password: str) -> None:
        self._set_busy("register")
        try:
            user = await self._auth_controller.register(username, nickname, password)
        except asyncio.CancelledError:
            raise
        except (APIError, NetworkError) as exc:
            logger.warning("Registration failed: %s", exc)
            self._show_error(str(exc))
        except Exception:
            logger.exception("Unexpected registration error")
            self._show_error(tr("auth.error.unexpected_register", "Unexpected error while creating account."))
        else:
            self._show_success(
                tr(
                    "auth.success.account_created",
                    "Account created for {name}",
                    name=user.get("nickname") or user.get("username", ""),
                )
            )
            self.authenticated.emit(user)
            self.close()
        finally:
            self._set_busy(None)

    def _show_error(self, message: str) -> None:
        InfoBar.error(tr("auth.feedback.title", "Authentication"), message, parent=self.form_card)

    def _show_success(self, message: str) -> None:
        InfoBar.success(tr("auth.feedback.title", "Authentication"), message, parent=self.form_card)

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
        self._cancel_pending_task(self._submit_task)
        self.closed.emit()
        super().closeEvent(event)

    def _on_destroyed(self, *_args) -> None:
        """Cancel outstanding submit work when the widget is torn down."""
        self._cancel_pending_task(self._submit_task)
        self._submit_task = None
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
