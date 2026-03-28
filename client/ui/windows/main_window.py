import asyncio
import sys
from collections import OrderedDict

import darkdetect
from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QColor, QCursor, QIcon, QPainter
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from qfluentwidgets import (
    Action,
    BodyLabel,
    CheckBox,
    FluentWindow,
    InfoBar,
    MessageBoxBase,
    NavigationItemPosition,
    SubtitleLabel,
    Theme,
    isDarkTheme,
    setTheme,
)
from qfluentwidgets.components.material import AcrylicMenu, AcrylicSystemTrayMenu

from client.core.app_icons import AppIcon
from client.core import logging
from client.core.config import cfg
from client.core.i18n import tr
from client.core.logging import setup_logging
from client.core.avatar_rendering import get_avatar_image_store
from client.core.avatar_utils import avatar_seed, profile_avatar_seed
from client.events.event_bus import get_event_bus
from client.managers.session_manager import SessionEvent
from client.ui.windows.chat_interface import ChatInterface
from client.ui.windows.contact_interface import ContactInterface
from client.ui.windows.discovery_interface import DiscoveryInterface
from client.ui.windows.settings_interface import SettingsInterface
from client.ui.widgets.navigation_user_card import RegularWeightNavigationUserCard
from client.ui.widgets.tray_message_flyout import TrayAlertEntry, TrayMessageFlyoutView
from client.ui.widgets.user_profile_flyout import UserProfileCoordinator
from qfluentwidgets.components.material import AcrylicFlyout
from qfluentwidgets.components.widgets.flyout import FlyoutAnimationType


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
        self._tray_menu: AcrylicMenu | None = None
        self._tray_alert_entries: OrderedDict[str, TrayAlertEntry] = OrderedDict()
        self._tray_attention_enabled = False
        self._tray_flash_on = False
        self._tray_normal_icon: QIcon = self.windowIcon()
        self._tray_attention_icon: QIcon = self._build_attention_tray_icon(self._tray_normal_icon)
        self._tray_flyout = None
        self._tray_flyout_view: TrayMessageFlyoutView | None = None
        self._tray_flash_timer = QTimer(self)
        self._tray_flash_timer.setInterval(480)
        self._tray_flash_timer.timeout.connect(self._toggle_tray_flash)
        self._tray_hover_timer = QTimer(self)
        self._tray_hover_timer.setInterval(120)
        self._tray_hover_timer.timeout.connect(self._poll_tray_hover)
        self._tray_leave_timer = QTimer(self)
        self._tray_leave_timer.setSingleShot(True)
        self._tray_leave_timer.setInterval(240)
        self._tray_leave_timer.timeout.connect(self._close_tray_alert_flyout)
        self._ui_tasks: set[asyncio.Task] = set()
        self._contact_open_task: asyncio.Task | None = None
        self._event_bus = get_event_bus()
        self._event_subscriptions: list[tuple[str, object]] = []
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
        self._subscribe_to_events()
        if hasattr(self, "stackedWidget"):
            self.stackedWidget.currentChanged.connect(self._on_sub_interface_changed)
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
        QTimer.singleShot(0, self._sync_chat_session_activity)

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

    def _on_sub_interface_changed(self, index: int) -> None:
        """Close chat-only transient layers when navigation leaves the chat page."""
        if not hasattr(self, "stackedWidget"):
            return
        current_widget = self.stackedWidget.widget(index)
        if current_widget is not self.chat_interface:
            self.chat_interface.close_transient_panels()
        self._sync_chat_session_activity()

    def switchTo(self, interface):
        """Close chat overlays before switching to another top-level page."""
        if interface is not self.chat_interface:
            self.chat_interface.close_transient_panels()
        result = super().switchTo(interface)
        QTimer.singleShot(0, self._sync_chat_session_activity)
        return result

    def changeEvent(self, event) -> None:
        """Keep chat read-state visibility in sync with focus and window-state changes."""
        super().changeEvent(event)
        if event.type() in {
            QEvent.Type.ActivationChange,
            QEvent.Type.WindowStateChange,
        }:
            QTimer.singleShot(0, self._sync_chat_session_activity)

    def _is_chat_session_active(self) -> bool:
        """Return whether the chat page is truly foreground-visible to the user."""
        if not hasattr(self, "stackedWidget") or not hasattr(self, "chat_interface"):
            return False

        return bool(
            self.stackedWidget.currentWidget() is self.chat_interface
            and self.isVisible()
            and not self.isMinimized()
            and self.isActiveWindow()
        )

    def _sync_chat_session_activity(self) -> None:
        """Propagate current page/window visibility into chat read-state handling."""
        if not hasattr(self, "chat_interface"):
            return
        self.chat_interface.set_session_visibility_active(self._is_chat_session_active())

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

        self._tray_menu = AcrylicSystemTrayMenu(parent=self)
        show_action = Action(AppIcon.HOME, tr("common.show_main_window", "Show Main Window"), self)
        exit_action = Action(AppIcon.CLOSE, tr("common.exit", "Exit"), self)
        show_action.triggered.connect(self.show_from_tray)
        exit_action.triggered.connect(self.request_exit)
        self._tray_menu.addAction(show_action)
        self._tray_menu.addAction(exit_action)
        self._tray_icon.setContextMenu(self._tray_menu)
        self._tray_icon.show()
        self._apply_tray_icon()

    def _onThemeChangedFinished(self):
        """Refresh mica effect after theme changes."""
        super()._onThemeChangedFinished()
        if self.isMicaEffectEnabled():
            QTimer.singleShot(100, lambda: self.windowEffect.setMicaEffect(self.winId(), isDarkTheme()))
        self._refresh_tray_icons()

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
        self._dismiss_tray_attention(clear_entries=True)
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, self._sync_chat_session_activity)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick}:
            self.show_from_tray()
        elif reason == QSystemTrayIcon.ActivationReason.Context:
            self._close_tray_alert_flyout()

    def show_session_replaced_warning(self) -> None:
        """Warn the user that this client was replaced by a newer login and close shortly after."""
        if self._force_logout_pending:
            return

        self._force_logout_pending = True
        self.show_from_tray()
        self.user_profile.close_flyout()
        self._force_logout_info_bar = InfoBar.warning(
            tr("main_window.session_replaced.title", "Signed Out"),
            tr(
                "main_window.session_replaced.message",
                "This account signed in on another client. This window will close in a moment.",
            ),
            parent=self,
            duration=3000,
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
        self.chat_interface.set_session_visibility_active(False)
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
        self._unsubscribe_from_events()
        self._dismiss_tray_attention(clear_entries=True)
        self.user_profile.close()
        self._cancel_pending_task(self._contact_open_task)
        self._contact_open_task = None
        for task in list(self._ui_tasks):
            if not task.done():
                task.cancel()

    def _subscribe_to_events(self) -> None:
        """Subscribe to session updates relevant to tray alerts."""
        self._subscribe_sync(SessionEvent.MESSAGE_ADDED, self._on_tray_message_added)
        self._subscribe_sync(SessionEvent.UNREAD_CHANGED, self._on_tray_unread_changed)
        self._subscribe_sync(SessionEvent.UPDATED, self._on_tray_session_updated)
        self._subscribe_sync(SessionEvent.DELETED, self._on_tray_session_deleted)

    def _subscribe_sync(self, event_type: str, handler) -> None:
        self._event_subscriptions.append((event_type, handler))
        self._event_bus.subscribe_sync(event_type, handler)

    def _unsubscribe_from_events(self) -> None:
        while self._event_subscriptions:
            event_type, handler = self._event_subscriptions.pop()
            self._event_bus.unsubscribe_sync(event_type, handler)

    def _on_tray_message_added(self, data: dict | None) -> None:
        """Raise tray attention when a background message lands in any visible session."""
        payload = dict(data or {})
        message = payload.get("message")
        session_id = str(payload.get("session_id", "") or getattr(message, "session_id", "") or "")
        if not session_id or message is None or getattr(message, "is_self", False):
            return

        session = self.chat_interface.get_session(session_id)
        if session is None or not self._can_trigger_tray_alert(session):
            return

        existing = self._tray_alert_entries.get(session_id)
        session_unread = int(getattr(session, "unread_count", 0) or 0)
        fallback_unread = int(existing.unread_count if existing is not None else 0) + 1
        display_unread = session_unread if session_unread > 0 else max(1, fallback_unread)
        self._upsert_tray_alert(session, unread_count=display_unread)
        self._set_tray_attention_enabled(True)

    def _on_tray_unread_changed(self, data: dict | None) -> None:
        """Start or stop tray attention based on unread-count changes."""
        payload = dict(data or {})
        session_id = str(payload.get("session_id", "") or "")
        unread_count = int(payload.get("unread_count", 0) or 0)
        if not session_id:
            return

        session = self.chat_interface.get_session(session_id)
        if unread_count <= 0 or session is None:
            self._remove_tray_alert(session_id)
            return

        if session_id in self._tray_alert_entries:
            self._upsert_tray_alert(session, unread_count=unread_count, keep_order=True)
        elif self._can_trigger_tray_alert(session):
            self._upsert_tray_alert(session, unread_count=unread_count)
            self._set_tray_attention_enabled(True)

    def _on_tray_session_updated(self, data: dict | None) -> None:
        """Keep existing tray-alert rows in sync with session state."""
        payload = dict(data or {})
        sessions = payload.get("sessions")
        session_objects = []
        if isinstance(sessions, list):
            session_objects.extend(sessions)
        elif payload.get("session") is not None:
            session_objects.append(payload.get("session"))

        for session in session_objects:
            session_id = getattr(session, "session_id", "")
            if not session_id:
                continue
            if session_id in self._tray_alert_entries:
                if not self._can_display_tray_alert(session):
                    self._remove_tray_alert(session_id)
                    continue
                self._upsert_tray_alert(
                    session,
                    unread_count=max(
                        int(getattr(session, "unread_count", 0) or 0),
                        int(self._tray_alert_entries[session_id].unread_count or 0),
                    ),
                    keep_order=True,
                )

    def _on_tray_session_deleted(self, data: dict | None) -> None:
        payload = dict(data or {})
        session_id = str(payload.get("session_id", "") or "")
        if session_id:
            self._remove_tray_alert(session_id)

    def _can_display_tray_alert(self, session) -> bool:
        """Return whether one session can be shown inside tray-alert UI."""
        if self._tray_icon is None or not self._tray_icon.isVisible():
            return False
        if session is None or getattr(session, "is_ai_session", False):
            return False
        if bool(getattr(session, "extra", {}).get("is_muted", False)):
            return False
        return True

    def _can_trigger_tray_alert(self, session) -> bool:
        """Return whether one session should start tray flashing right now."""
        if not self._can_display_tray_alert(session):
            return False

        app = QApplication.instance()
        is_foreground = bool(
            app
            and app.applicationState() == Qt.ApplicationState.ApplicationActive
            and self.isVisible()
            and not self.isMinimized()
            and self.isActiveWindow()
        )
        return not is_foreground

    def _build_tray_alert_entry(self, session, *, unread_count: int | None = None) -> TrayAlertEntry:
        extra = dict(getattr(session, "extra", {}) or {})
        return TrayAlertEntry(
            session_id=str(getattr(session, "session_id", "") or ""),
            name=str(getattr(session, "name", "") or tr("session.unnamed", "Untitled Session")),
            avatar=str(getattr(session, "avatar", "") or ""),
            unread_count=int(unread_count if unread_count is not None else (getattr(session, "unread_count", 0) or 0)),
            counterpart_id=str(extra.get("counterpart_id", "") or ""),
            counterpart_username=str(extra.get("counterpart_username", "") or ""),
        )

    def _upsert_tray_alert(self, session, *, unread_count: int | None = None, keep_order: bool = False) -> None:
        entry = self._build_tray_alert_entry(session, unread_count=unread_count)
        if not entry.session_id:
            return
        if keep_order and entry.session_id in self._tray_alert_entries:
            self._tray_alert_entries[entry.session_id] = entry
            self._refresh_tray_flyout_entries()
            return
        if entry.session_id in self._tray_alert_entries:
            self._tray_alert_entries.pop(entry.session_id, None)
        self._tray_alert_entries[entry.session_id] = entry
        self._tray_alert_entries.move_to_end(entry.session_id, last=False)
        self._refresh_tray_flyout_entries()

    def _remove_tray_alert(self, session_id: str) -> None:
        if not session_id:
            return
        if session_id in self._tray_alert_entries:
            self._tray_alert_entries.pop(session_id, None)
            self._refresh_tray_flyout_entries()
        if not self._tray_alert_entries:
            self._dismiss_tray_attention(clear_entries=False)

    def _set_tray_attention_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled and self._tray_alert_entries and self._tray_icon and self._tray_icon.isVisible())
        self._tray_attention_enabled = enabled
        if not enabled:
            self._tray_flash_timer.stop()
            self._tray_hover_timer.stop()
            self._tray_leave_timer.stop()
            self._tray_flash_on = False
            self._apply_tray_icon()
            return

        if not self._tray_hover_timer.isActive():
            self._tray_hover_timer.start()
        if not self._tray_flash_timer.isActive():
            self._tray_flash_on = True
            self._tray_flash_timer.start()
        self._apply_tray_icon()

    def _dismiss_tray_attention(self, *, clear_entries: bool) -> None:
        self._tray_leave_timer.stop()
        self._close_tray_alert_flyout()
        if clear_entries:
            self._tray_alert_entries.clear()
        self._set_tray_attention_enabled(False)

    def _toggle_tray_flash(self) -> None:
        if not self._tray_attention_enabled:
            self._tray_flash_timer.stop()
            self._apply_tray_icon()
            return

        if self._tray_flyout is not None and self._tray_flyout.isVisible():
            self._tray_flash_on = True
        elif self._tray_menu is not None and self._tray_menu.isVisible():
            self._tray_flash_on = True
        else:
            self._tray_flash_on = not self._tray_flash_on
        self._apply_tray_icon()

    def _apply_tray_icon(self) -> None:
        if self._tray_icon is None:
            return
        if self._tray_attention_enabled and self._tray_flash_on:
            self._tray_icon.setIcon(self._tray_attention_icon)
        else:
            self._tray_icon.setIcon(self._tray_normal_icon)

    def _refresh_tray_icons(self) -> None:
        self._tray_normal_icon = self.windowIcon()
        self._tray_attention_icon = self._build_attention_tray_icon(self._tray_normal_icon)
        self._apply_tray_icon()

    @staticmethod
    def _build_attention_tray_icon(base_icon: QIcon) -> QIcon:
        """Overlay a small red dot onto the normal tray icon."""
        icon = QIcon()
        for size in (16, 20, 24, 32):
            pixmap = base_icon.pixmap(size, size)
            if pixmap.isNull():
                continue

            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            badge_size = max(8, int(size * 0.58))
            badge_rect = QRect(size - badge_size - 1, 0, badge_size, badge_size)
            painter.setPen(QColor("#FFFFFF"))
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawEllipse(badge_rect.adjusted(-1, -1, 1, 1))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#FF4D4F"))
            painter.drawEllipse(badge_rect)
            painter.end()
            icon.addPixmap(pixmap)

        return icon if not icon.isNull() else base_icon

    def _poll_tray_hover(self) -> None:
        if not self._tray_attention_enabled or self._tray_icon is None or not self._tray_icon.isVisible():
            return
        if self._tray_menu is not None and self._tray_menu.isVisible():
            self._close_tray_alert_flyout()
            return

        tray_rect = self._tray_icon.geometry()
        if not tray_rect.isValid() or tray_rect.isNull():
            return

        cursor_pos = QCursor.pos()
        hovered_tray = tray_rect.adjusted(-2, -2, 2, 2).contains(cursor_pos)
        hovered_flyout = bool(
            self._tray_flyout is not None
            and self._tray_flyout.isVisible()
            and self._tray_flyout.frameGeometry().adjusted(-4, -4, 4, 4).contains(cursor_pos)
        )

        if hovered_tray or hovered_flyout:
            self._tray_leave_timer.stop()
            if hovered_tray and (self._tray_flyout is None or not self._tray_flyout.isVisible()):
                self._show_tray_alert_flyout(tray_rect)
            return

        if self._tray_flyout is not None and self._tray_flyout.isVisible() and not self._tray_leave_timer.isActive():
            self._tray_leave_timer.start()

    def _show_tray_alert_flyout(self, tray_rect: QRect | None = None) -> None:
        if not self._tray_alert_entries:
            return
        if self._tray_menu is not None and self._tray_menu.isVisible():
            return

        tray_rect = tray_rect or (self._tray_icon.geometry() if self._tray_icon is not None else QRect())
        if not tray_rect.isValid() or tray_rect.isNull():
            return

        if self._tray_flyout is not None and self._tray_flyout.isVisible() and self._tray_flyout_view is not None:
            self._tray_flyout_view.set_entries(list(self._tray_alert_entries.values()))
            self._tray_flyout.adjustSize()
            return

        view = TrayMessageFlyoutView()
        view.set_entries(list(self._tray_alert_entries.values()))
        view.sessionActivated.connect(self._on_tray_alert_session_activated)
        view.ignoreRequested.connect(self._on_tray_alert_ignore_requested)
        view.hoverEntered.connect(self._tray_leave_timer.stop)
        view.hoverLeft.connect(lambda: self._tray_leave_timer.start())

        flyout = AcrylicFlyout(view, None)
        flyout.closed.connect(self._clear_tray_flyout)
        flyout.show()
        flyout.adjustSize()

        ani_type = self._tray_flyout_animation_type(tray_rect)
        target_pos = self._tray_flyout_top_left(tray_rect, flyout.sizeHint(), ani_type)
        self._tray_flyout = flyout
        self._tray_flyout_view = view
        flyout.exec(target_pos, aniType=ani_type)
        self._tray_flash_on = True
        self._apply_tray_icon()

    def _refresh_tray_flyout_entries(self) -> None:
        if self._tray_flyout_view is None:
            return
        entries = list(self._tray_alert_entries.values())
        self._tray_flyout_view.set_entries(entries)
        if self._tray_flyout is not None:
            self._tray_flyout.adjustSize()
            tray_rect = self._tray_icon.geometry() if self._tray_icon is not None else QRect()
            if self._tray_flyout.isVisible() and tray_rect.isValid() and not tray_rect.isNull():
                ani_type = self._tray_flyout_animation_type(tray_rect)
                self._tray_flyout.move(self._tray_flyout_top_left(tray_rect, self._tray_flyout.sizeHint(), ani_type))
        if not entries:
            self._close_tray_alert_flyout()

    def _tray_flyout_animation_type(self, tray_rect: QRect) -> FlyoutAnimationType:
        screen = QApplication.screenAt(tray_rect.center()) or QApplication.primaryScreen()
        if screen is None:
            return FlyoutAnimationType.PULL_UP

        geometry = screen.availableGeometry()
        distances = {
            FlyoutAnimationType.DROP_DOWN: abs(tray_rect.top() - geometry.top()),
            FlyoutAnimationType.PULL_UP: abs(geometry.bottom() - tray_rect.bottom()),
            FlyoutAnimationType.SLIDE_RIGHT: abs(tray_rect.left() - geometry.left()),
            FlyoutAnimationType.SLIDE_LEFT: abs(geometry.right() - tray_rect.right()),
        }
        return min(distances, key=distances.get)

    def _tray_flyout_top_left(self, tray_rect: QRect, size: QSize, ani_type: FlyoutAnimationType) -> QPoint:
        screen = QApplication.screenAt(tray_rect.center()) or QApplication.primaryScreen()
        if screen is None:
            return tray_rect.topLeft()
        geometry = screen.availableGeometry()
        width = max(0, size.width())
        height = max(0, size.height())

        if ani_type == FlyoutAnimationType.DROP_DOWN:
            point = QPoint(tray_rect.center().x() - width // 2, tray_rect.bottom() - 6)
        elif ani_type == FlyoutAnimationType.SLIDE_LEFT:
            point = QPoint(tray_rect.left() - width + 8, tray_rect.center().y() - height // 2)
        elif ani_type == FlyoutAnimationType.SLIDE_RIGHT:
            point = QPoint(tray_rect.right() - 8, tray_rect.center().y() - height // 2)
        else:
            point = QPoint(tray_rect.center().x() - width // 2, tray_rect.top() - height + 6)

        x = min(max(geometry.left() + 8, point.x()), geometry.right() - width - 8)
        y = min(max(geometry.top() + 8, point.y()), geometry.bottom() - height - 8)
        return QPoint(x, y)

    def _close_tray_alert_flyout(self) -> None:
        self._tray_leave_timer.stop()
        if self._tray_flyout is not None and self._tray_flyout.isVisible():
            self._tray_flyout.close()
        else:
            self._clear_tray_flyout()

    def _clear_tray_flyout(self) -> None:
        self._tray_flyout = None
        self._tray_flyout_view = None
        if self._tray_attention_enabled:
            self._tray_flash_on = False
            self._apply_tray_icon()

    def _on_tray_alert_ignore_requested(self) -> None:
        self._dismiss_tray_attention(clear_entries=False)

    def _on_tray_alert_session_activated(self, session_id: str) -> None:
        self._dismiss_tray_attention(clear_entries=True)
        self._create_ui_task(self._open_tray_session(session_id), f"open tray session {session_id}")

    async def _open_tray_session(self, session_id: str) -> None:
        self.show_from_tray()
        if hasattr(self, "switchTo"):
            self.switchTo(self.chat_interface)
        else:
            self.stackedWidget.setCurrentWidget(self.chat_interface)

        opened = await self.chat_interface.open_session(session_id)
        if not opened:
            InfoBar.warning(
                tr("main_window.contact_jump.unavailable_title", "Chat"),
                tr("main_window.contact_jump.unavailable_message", "Unable to open this conversation right now."),
                parent=self,
                duration=2200,
            )

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

