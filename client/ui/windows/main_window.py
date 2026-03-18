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
    FluentIcon,
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

from client.core import logging
from client.core.config import cfg
from client.core.logging import setup_logging
from client.ui.windows.chat_interface import ChatInterface
from client.ui.windows.contact_interface import ContactInterface
from client.ui.windows.discovery_interface import DiscoveryInterface
from client.ui.windows.settings_interface import SettingsInterface


setup_logging()
logger = logging.get_logger(__name__)


class ExitConfirmDialog(MessageBoxBase):
    """Fluent exit confirmation dialog with do-not-show-again option."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.title_label = SubtitleLabel("\u9000\u51fa AssistIM", self.widget)
        self.content_label = BodyLabel("\u786e\u5b9a\u8981\u9000\u51fa AssistIM \u5417\uff1f", self.widget)
        self.content_label.setWordWrap(True)
        self.remember_check_box = CheckBox("\u4e0b\u6b21\u4e0d\u518d\u663e\u793a", self.widget)

        self.viewLayout.addWidget(self.title_label)
        self.viewLayout.addWidget(self.content_label)
        self.viewLayout.addWidget(self.remember_check_box)
        self.viewLayout.addStretch(1)

        self.yesButton.setText("\u9000\u51fa")
        self.cancelButton.setText("\u53d6\u6d88")
        self.widget.setMinimumWidth(360)


class MainWindow(FluentWindow):
    """Main application window."""

    closed = Signal()

    def __init__(self):
        super().__init__()
        self.resize(1200, 900)
        self.setWindowTitle("AssistIM")
        self.setWindowIcon(FluentIcon.CHAT.icon())

        self._allow_exit = False
        self._tray_message_shown = False
        self._tray_icon: QSystemTrayIcon | None = None
        self._tray_menu: RoundMenu | None = None

        self.setMicaEffectEnabled(cfg.get(cfg.micaEnabled))

        self._theme_poll_timer = QTimer(self)
        self._theme_poll_timer.setInterval(1500)
        self._theme_poll_timer.timeout.connect(self._poll_system_theme)
        self._last_system_theme = ""

        self.chat_interface = ChatInterface(self)
        self.contact_interface = ContactInterface(self)
        self.discovery_interface = DiscoveryInterface(self)
        self.settingsInterface = SettingsInterface(self)
        self.contact_interface.message_requested.connect(self._on_contact_message_requested)
        self.settingsInterface.micaChanged.connect(self._on_mica_changed)

        self.navigationInterface.setAcrylicEnabled(cfg.get(cfg.micaEnabled))
        self.initNavigation()
        self._init_system_tray()

        if sys.platform == "win32":
            self._last_system_theme = self._detect_system_theme()
            self._theme_poll_timer.start()

        primary_screen = QApplication.primaryScreen()
        if primary_screen:
            screen_geometry = primary_screen.availableGeometry()
            w, h = screen_geometry.width(), screen_geometry.height()
            self.move(w // 2 - self.width() // 2, h // 2 - self.height() // 2)

        self.chat_interface.load_sessions()

        self.show()
        QApplication.processEvents()

    def initNavigation(self):
        """Initialize left navigation."""
        self.addSubInterface(self.chat_interface, FluentIcon.CHAT, "Chat")
        self.addSubInterface(self.contact_interface, FluentIcon.PEOPLE, "Contacts")
        self.addSubInterface(self.discovery_interface, FluentIcon.GLOBE, "Moments")
        self.addSubInterface(
            self.settingsInterface,
            FluentIcon.SETTING,
            "Settings",
            NavigationItemPosition.BOTTOM,
        )
        self.navigationInterface.panel.setReturnButtonVisible(False)

    def _init_system_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("System tray is not available on this platform")
            return

        self._tray_icon = QSystemTrayIcon(self)
        self._tray_icon.setIcon(self.windowIcon())
        self._tray_icon.setToolTip("AssistIM")
        self._tray_icon.activated.connect(self._on_tray_activated)

        self._tray_menu = RoundMenu(parent=self)
        show_action = Action(FluentIcon.HOME, "\u663e\u793a\u4e3b\u754c\u9762", self)
        exit_action = Action(FluentIcon.CLOSE, "\u9000\u51fa", self)
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
                    "AssistIM",
                    "\u5e94\u7528\u4ecd\u5728\u540e\u53f0\u8fd0\u884c\uff0c\u53ef\u901a\u8fc7\u7cfb\u7edf\u6258\u76d8\u6062\u590d\u6216\u9000\u51fa\u3002",
                    QSystemTrayIcon.MessageIcon.Information,
                    2500,
                )
            return

        logger.info("MainWindow closeEvent, tray unavailable, request exit")
        event.ignore()
        self.request_exit()

    def _on_contact_message_requested(self, payload: object) -> None:
        """Open the selected contact or group in the chat interface."""
        asyncio.create_task(self._open_contact_target(payload))

    async def _open_contact_target(self, payload: object) -> None:
        """Route contact actions into the chat page."""
        if hasattr(self, "switchTo"):
            self.switchTo(self.chat_interface)
        else:
            self.stackedWidget.setCurrentWidget(self.chat_interface)

        if not isinstance(payload, dict):
            InfoBar.warning("Chat", "Unable to resolve contact jump data.", parent=self, duration=2000)
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
            InfoBar.warning("Chat", "Unable to open this conversation right now.", parent=self, duration=2200)
