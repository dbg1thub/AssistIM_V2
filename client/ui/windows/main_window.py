import asyncio
import sys

import darkdetect
from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from qfluentwidgets import (
    Action,
    BodyLabel,
    CheckBox,
    FluentWindow,
    InfoBar,
    MessageBoxBase,
    NavigationItemPosition,
    RoundMenu,
    SubtitleLabel,
    Theme,
    isDarkTheme,
    setTheme,
)

from client.core.app_icons import AppIcon
from client.core import logging
from client.core.config import cfg
from client.core.i18n import tr
from client.core.logging import setup_logging
from client.core.avatar_rendering import get_avatar_image_store
from client.core.avatar_utils import avatar_seed, profile_avatar_seed
from client.ui.windows.chat_interface import ChatInterface
from client.ui.windows.contact_interface import ContactInterface
from client.ui.windows.discovery_interface import DiscoveryInterface
from client.ui.windows.settings_interface import SettingsInterface
from client.ui.widgets.navigation_user_card import RegularWeightNavigationUserCard
from client.ui.widgets.user_profile_flyout import UserProfileCoordinator
from client.ui.widgets.acrylic_surface import configure_acrylic_infobar


setup_logging()
logger = logging.get_logger(__name__)


class ExitConfirmDialog(MessageBoxBase):
    """Fluent exit confirmation dialog with do-not-show-again option."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.title_label = SubtitleLabel(tr("main_window.exit_dialog.title", "Exit AssistIM"), self.widget)
        self.content_label = BodyLabel(
            tr("main_window.exit_dialog.content", "Are you sure you want to exit AssistIM?"),
            self.widget,
        )
        self.content_label.setWordWrap(True)
        self.remember_check_box = CheckBox(
            tr("main_window.exit_dialog.remember", "Don't show this again"),
            self.widget,
        )

        self.viewLayout.addWidget(self.title_label)
        self.viewLayout.addWidget(self.content_label)
        self.viewLayout.addWidget(self.remember_check_box)
        self.viewLayout.addStretch(1)

        self.yesButton.setText(tr("main_window.exit_dialog.confirm", "Exit"))
        self.cancelButton.setText(tr("main_window.exit_dialog.cancel", "Cancel"))
        self.widget.setMinimumWidth(360)


class MainWindow(FluentWindow):
    """Main application window."""

    closed = Signal()
    logoutRequested = Signal()
    NAVIGATION_MENU_THRESHOLD = 1400

    def __init__(self):
        super().__init__()
        self.resize(1200, 900)
        self.setWindowTitle(tr("common.app_name", "AssistIM"))
        self.setWindowIcon(AppIcon.CHAT.icon())

        self._allow_exit = False
        self._tray_message_shown = False
        self._tray_icon: QSystemTrayIcon | None = None
        self._tray_menu: RoundMenu | None = None
        self._ui_tasks: set[asyncio.Task] = set()
        self._contact_open_task: asyncio.Task | None = None
        self._force_logout_pending = False
        self._force_logout_info_bar = None
        self._force_logout_timer = QTimer(self)
        self._force_logout_timer.setSingleShot(True)
        self._force_logout_timer.timeout.connect(self._request_forced_exit)
        self.user_card = None
        self._avatar_store = get_avatar_image_store()
        self._avatar_store.avatar_ready.connect(self._on_avatar_ready)

        self.setMicaEffectEnabled(cfg.get(cfg.micaEnabled))

        self._theme_poll_timer = QTimer(self)
        self._theme_poll_timer.setInterval(1500)
        self._theme_poll_timer.timeout.connect(self._poll_system_theme)
        self._last_system_theme = ""

        self.chat_interface = ChatInterface(self)
        self.contact_interface = ContactInterface(self)
        self.discovery_interface = DiscoveryInterface(self)
        self.user_profile = UserProfileCoordinator(self)
        self.settingsInterface = SettingsInterface(self)
        self.contact_interface.message_requested.connect(self._on_contact_message_requested)
        self.user_profile.logoutRequested.connect(self.logoutRequested.emit)
        self.user_profile.profileChanged.connect(self._on_profile_changed)
        self.settingsInterface.micaChanged.connect(self._on_mica_changed)

        self.navigationInterface.setAcrylicEnabled(cfg.get(cfg.micaEnabled))
        self.navigationInterface.setMinimumExpandWidth(self.NAVIGATION_MENU_THRESHOLD)
        self.initNavigation()
        self._init_system_tray()
        self.destroyed.connect(self._on_destroyed)

        if sys.platform == "win32":
            self._last_system_theme = self._detect_system_theme()
            self._theme_poll_timer.start()

        primary_screen = QApplication.primaryScreen()
        if primary_screen:
            screen_geometry = primary_screen.availableGeometry()
            w, h = screen_geometry.width(), screen_geometry.height()
            self.move(w // 2 - self.width() // 2, h // 2 - self.height() // 2)

        QTimer.singleShot(0, self.chat_interface.load_sessions)

    def initNavigation(self):
        """Initialize left navigation."""
        self._init_user_card()
        self.addSubInterface(self.chat_interface, AppIcon.CHAT, tr("common.chat", "Chat"))
        self.addSubInterface(self.contact_interface, AppIcon.PEOPLE, tr("common.contacts", "Contacts"))
        self.addSubInterface(self.discovery_interface, AppIcon.GLOBE, tr("common.moments", "Moments"))
        self.addSubInterface(
            self.settingsInterface,
            AppIcon.SETTING,
            tr("common.settings", "Settings"),
            NavigationItemPosition.BOTTOM,
        )
        self.navigationInterface.panel.setReturnButtonVisible(False)
        self._sync_user_card(self.user_profile.current_user_snapshot())

    def _init_user_card(self) -> None:
        """Insert the current-account user card into the navigation area."""
        self.user_card = RegularWeightNavigationUserCard(self.navigationInterface)
        placeholder_source, placeholder_avatar = self._avatar_store.resolve_display_path(
            "",
            seed=avatar_seed("main-user-card"),
        )
        self._user_card_avatar_source = placeholder_source
        self._user_card_avatar_gender = ""
        self._user_card_avatar_seed = avatar_seed("main-user-card")
        if placeholder_avatar:
            self.user_card.setAvatar(placeholder_avatar)

        self.user_card.setTitle(tr("profile.placeholder.name", "Not Signed In"))
        self.user_card.setSubtitle(tr("main_window.user_card.empty_subtitle", "AssistIM ID unavailable"))
        self.navigationInterface.addWidget(
            "main.userCard",
            self.user_card,
            self._toggle_profile_card,
            NavigationItemPosition.TOP,
        )

    def _toggle_profile_card(self) -> None:
        """Toggle the quick profile flyout anchored to the sidebar user card."""
        if self.user_card is None:
            return
        self.user_profile.show_user_flyout(self.user_card, self)

    def _on_profile_changed(self, payload: object) -> None:
        """Keep the sidebar user card in sync with the current profile."""
        user = dict(payload or {})
        self._sync_user_card(user)

    def _on_avatar_ready(self, source: str) -> None:
        """Refresh the sidebar user avatar when a remote image finishes downloading."""
        if self.user_card is None or source != self._user_card_avatar_source:
            return

        avatar_path = self._avatar_store.display_path_for_source(
            source,
            gender=self._user_card_avatar_gender,
            seed=self._user_card_avatar_seed,
        )
        if avatar_path:
            self.user_card.setAvatar(avatar_path)

    def _sync_user_card(self, user: dict | None) -> None:
        """Refresh the sidebar user-card title/subtitle from one user payload."""
        if self.user_card is None:
            return

        user = dict(user or {})
        title = (
            str(user.get("nickname", "") or "")
            or str(user.get("username", "") or "")
            or tr("profile.placeholder.name", "Not Signed In")
        )
        subtitle = (
            str(user.get("username", "") or "")
            or tr("main_window.user_card.empty_subtitle", "AssistIM ID unavailable")
        )
        self.user_card.setTitle(title)
        self.user_card.setSubtitle(subtitle)
        avatar_seed_value = profile_avatar_seed(
            user_id=user.get("id", ""),
            username=user.get("username", ""),
            display_name=title,
        )
        avatar_source, avatar_path = self._avatar_store.resolve_display_path(
            user.get("avatar", ""),
            gender=user.get("gender", ""),
            seed=avatar_seed_value,
        )
        self._user_card_avatar_source = avatar_source
        self._user_card_avatar_gender = str(user.get("gender", "") or "")
        self._user_card_avatar_seed = avatar_seed_value
        if avatar_path:
            self.user_card.setAvatar(avatar_path)

    def _init_system_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("System tray is not available on this platform")
            return

        self._tray_icon = QSystemTrayIcon(self)
        self._tray_icon.setIcon(self.windowIcon())
        self._tray_icon.setToolTip(tr("common.app_name", "AssistIM"))
        self._tray_icon.activated.connect(self._on_tray_activated)

        self._tray_menu = RoundMenu(parent=self)
        show_action = Action(AppIcon.HOME, tr("common.show_main_window", "Show Main Window"), self)
        exit_action = Action(AppIcon.CLOSE, tr("common.exit", "Exit"), self)
        show_action.triggered.connect(self.show_from_tray)
        exit_action.triggered.connect(self.request_exit)
        self._tray_menu.addAction(show_action)
        self._tray_menu.addAction(exit_action)
        self._tray_icon.setContextMenu(self._tray_menu)
        self._tray_icon.show()

    def _onThemeChangedFinished(self):
        """Refresh mica effect after theme changes."""
        super()._onThemeChangedFinished()
        if self.isMicaEffectEnabled():
            QTimer.singleShot(100, lambda: self.windowEffect.setMicaEffect(self.winId(), isDarkTheme()))

    def _detect_system_theme(self) -> str:
        """Return current Windows theme label."""
        theme = darkdetect.theme()
        if theme not in {"Dark", "Light"}:
            return "Light"
        return theme

    def _poll_system_theme(self) -> None:
        """Keep theme synced with system setting when Theme.AUTO is enabled."""
        if cfg.get(cfg.themeMode) != Theme.AUTO:
            self._last_system_theme = self._detect_system_theme()
            return

        current_theme = self._detect_system_theme()
        if current_theme == self._last_system_theme:
            return

        self._last_system_theme = current_theme
        setTheme(Theme.AUTO, lazy=True)

    def _on_mica_changed(self, enabled: bool) -> None:
        self.setMicaEffectEnabled(enabled)
        self.navigationInterface.setAcrylicEnabled(enabled)
        if enabled:
            QTimer.singleShot(100, lambda: self.windowEffect.setMicaEffect(self.winId(), isDarkTheme()))

    def show_from_tray(self) -> None:
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick}:
            self.show_from_tray()

    def show_session_replaced_warning(self) -> None:
        """Warn the user that this client was replaced by a newer login and close shortly after."""
        if self._force_logout_pending:
            return

        self._force_logout_pending = True
        self.show_from_tray()
        self.user_profile.close_flyout()
        self._force_logout_info_bar = configure_acrylic_infobar(
            InfoBar.warning(
                tr("main_window.session_replaced.title", "Signed Out"),
                tr(
                    "main_window.session_replaced.message",
                    "This account signed in on another client. This window will close in a moment.",
                ),
                parent=self,
                duration=3000,
            )
        )
        if hasattr(self._force_logout_info_bar, "closedSignal"):
            self._force_logout_info_bar.closedSignal.connect(self._request_forced_exit)
        self._force_logout_timer.start(3000)

    def _request_forced_exit(self) -> None:
        """Close the window immediately without showing the normal exit confirmation."""
        if self._allow_exit:
            return

        if self._force_logout_timer.isActive():
            self._force_logout_timer.stop()
        self._allow_exit = True
        self.close()


    def request_exit(self) -> None:
        if cfg.get(cfg.exitConfirmEnabled):
            dialog = ExitConfirmDialog(self)
            if not dialog.exec():
                return
            if dialog.remember_check_box.isChecked():
                cfg.set(cfg.exitConfirmEnabled, False)

        self._allow_exit = True
        self.close()

    def closeEvent(self, event: QCloseEvent):
        self.user_profile.close_flyout()
        if self._allow_exit:
            logger.info("MainWindow closeEvent, exiting application")
            if self._theme_poll_timer.isActive():
                self._theme_poll_timer.stop()
            if self._tray_icon and self._tray_icon.isVisible():
                self._tray_icon.hide()
            self.closed.emit()
            super().closeEvent(event)
            return

        if self._tray_icon and self._tray_icon.isVisible():
            logger.info("MainWindow closeEvent, hiding to tray")
            event.ignore()
            self.hide()
            if not self._tray_message_shown:
                self._tray_message_shown = True
                self._tray_icon.showMessage(
                    tr("common.app_name", "AssistIM"),
                    tr(
                        "main_window.tray.background_message",
                        "AssistIM is still running in the background. Restore or quit it from the system tray.",
                    ),
                    QSystemTrayIcon.MessageIcon.Information,
                    2500,
                )
            return

        logger.info("MainWindow closeEvent, tray unavailable, request exit")
        event.ignore()
        self.request_exit()

    def _on_contact_message_requested(self, payload: object) -> None:
        """Open the selected contact or group in the chat interface."""
        self._set_contact_open_task(self._open_contact_target(payload))

    def _on_destroyed(self, *_args) -> None:
        """Cancel outstanding UI tasks when the window is torn down."""
        self.user_profile.close()
        self._cancel_pending_task(self._contact_open_task)
        self._contact_open_task = None
        for task in list(self._ui_tasks):
            if not task.done():
                task.cancel()

    def _cancel_pending_task(self, task: asyncio.Task | None) -> None:
        """Cancel a tracked task if it is still running."""
        if task is not None and not task.done():
            task.cancel()

    def _create_ui_task(self, coro, context: str, *, on_done=None) -> asyncio.Task:
        """Create a tracked UI task that logs failures and clears bookkeeping."""
        task = asyncio.create_task(coro)
        self._ui_tasks.add(task)
        task.add_done_callback(lambda finished, name=context, callback=on_done: self._finalize_ui_task(finished, name, callback))
        return task

    def _finalize_ui_task(self, task: asyncio.Task, context: str, on_done=None) -> None:
        """Remove completed tasks from tracking and report failures."""
        self._ui_tasks.discard(task)
        if on_done is not None:
            on_done(task)

        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("MainWindow UI task failed: %s", context)

    def _set_contact_open_task(self, coro) -> None:
        """Keep only the latest contact-jump task alive."""
        self._cancel_pending_task(self._contact_open_task)
        self._contact_open_task = self._create_ui_task(coro, "open contact target", on_done=self._clear_contact_open_task)

    def _clear_contact_open_task(self, task: asyncio.Task) -> None:
        """Clear the tracked contact-open task when it finishes."""
        if self._contact_open_task is task:
            self._contact_open_task = None

    async def _open_contact_target(self, payload: object) -> None:
        """Route contact actions into the chat page."""
        if hasattr(self, "switchTo"):
            self.switchTo(self.chat_interface)
        else:
            self.stackedWidget.setCurrentWidget(self.chat_interface)

        if not isinstance(payload, dict):
            InfoBar.warning(
                tr("main_window.contact_jump.invalid_title", "Chat"),
                tr("main_window.contact_jump.invalid_message", "Unable to resolve contact jump data."),
                parent=self,
                duration=2000,
            )
            return

        target_type = payload.get("type", "")
        target = payload.get("data")
        opened = False

        if target_type == "group":
            session_id = getattr(target, "session_id", "")
            if session_id:
                opened = await self.chat_interface.open_group_session(session_id)
        else:
            contact_id = getattr(target, "id", "")
            if contact_id:
                opened = await self.chat_interface.open_direct_session(
                    contact_id,
                    getattr(target, "display_name", "") or getattr(target, "name", ""),
                    getattr(target, "avatar", ""),
                )

        if not opened:
            InfoBar.warning(
                tr("main_window.contact_jump.unavailable_title", "Chat"),
                tr("main_window.contact_jump.unavailable_message", "Unable to open this conversation right now."),
                parent=self,
                duration=2200,
            )

