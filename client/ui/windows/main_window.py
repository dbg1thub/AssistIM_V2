import asyncio
import sys

import darkdetect
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QApplication
from qfluentwidgets import (
    FluentIcon,
    FluentWindow,
    InfoBar,
    NavigationItemPosition,
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


class MainWindow(FluentWindow):
    """Main application window."""

    closed = Signal()

    def __init__(self):
        super().__init__()
        self.resize(1200, 900)
        self.setWindowTitle("AssistIM")

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

        self.navigationInterface.setAcrylicEnabled(True)
        self.initNavigation()

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

    def closeEvent(self, event):
        logger.info("MainWindow closeEvent, accepting close")
        if self._theme_poll_timer.isActive():
            self._theme_poll_timer.stop()
        self.closed.emit()
        super().closeEvent(event)

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
