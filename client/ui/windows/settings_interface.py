# coding: utf-8
"""Settings interface built with qfluentwidgets."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    ComboBoxSettingCard,
    CustomColorSettingCard,
    ExpandLayout,
    InfoBar,
    OptionsSettingCard,
    ScrollArea,
    SettingCardGroup,
    SwitchSettingCard,
    Theme,
    setTheme,
    setThemeColor,
)

from client.core.app_icons import AppIcon, CollectionIcon
from client.core.config import cfg, is_win11
from client.core.i18n import tr


class SettingsInterface(ScrollArea):
    """Application settings page."""

    micaChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SettingsInterface")

        self.scroll_widget = QWidget(self)
        self.scroll_widget.setObjectName("settingsScrollWidget")
        self.expand_layout = ExpandLayout(self.scroll_widget)

        self.personal_group = SettingCardGroup(tr("settings.group.personalization", "Personalization"), self.scroll_widget)
        self.notification_group = SettingCardGroup(tr("settings.group.notifications", "Notifications"), self.scroll_widget)
        self.app_group = SettingCardGroup(tr("settings.group.application", "Application"), self.scroll_widget)

        self.mica_card = SwitchSettingCard(
            AppIcon.TRANSPARENT,
            tr("settings.card.mica.title", "Mica Effect"),
            tr("settings.card.mica.content", "Enable the Windows 11 Mica background effect for the window surface."),
            configItem=cfg.micaEnabled,
            parent=self.personal_group,
        )
        self.theme_card = OptionsSettingCard(
            cfg.themeMode,
            AppIcon.PALETTE,
            tr("settings.card.theme.title", "Theme"),
            tr("settings.card.theme.content", "Switch between light, dark, or system theme."),
            texts=[
                tr("settings.card.theme.option.light", "Light"),
                tr("settings.card.theme.option.dark", "Dark"),
                tr("settings.card.theme.option.system", "Follow System"),
            ],
            parent=self.personal_group,
        )
        self.theme_color_card = CustomColorSettingCard(
            cfg.themeColor,
            AppIcon.BRUSH,
            tr("settings.card.theme_color.title", "Theme Color"),
            tr("settings.card.theme_color.content", "Change the application accent color."),
            parent=self.personal_group,
        )
        self.zoom_card = OptionsSettingCard(
            cfg.dpiScale,
            AppIcon.ZOOM,
            tr("settings.card.zoom.title", "Display Scale"),
            tr("settings.card.zoom.content", "Adjust the scale used for UI and text rendering."),
            texts=["100%", "125%", "150%", "175%", "200%", tr("settings.card.zoom.option.auto", "Follow System")],
            parent=self.personal_group,
        )
        self.language_card = ComboBoxSettingCard(
            cfg.language,
            AppIcon.LANGUAGE,
            tr("settings.card.language.title", "Language"),
            tr("settings.card.language.content", "Choose the language used by the application interface."),
            texts=[
                tr("settings.card.language.option.zh_cn", "Simplified Chinese"),
                tr("settings.card.language.option.en_us", "English"),
                tr("settings.card.language.option.ko_kr", "Korean"),
                tr("settings.card.language.option.auto", "Follow System"),
            ],
            parent=self.personal_group,
        )

        self.exit_confirm_card = SwitchSettingCard(
            AppIcon.CLOSE,
            tr("settings.card.exit_confirm.title", "Confirm Before Exit"),
            tr("settings.card.exit_confirm.content", "Show a confirmation dialog before quitting from the system tray."),
            configItem=cfg.exitConfirmEnabled,
            parent=self.app_group,
        )
        self.sound_enabled_card = SwitchSettingCard(
            CollectionIcon("speaker_2"),
            tr("settings.card.sound_enabled.title", "Enable Sound Effects"),
            tr("settings.card.sound_enabled.content", "Allow the desktop client to play notification sounds and future UI sound effects."),
            configItem=cfg.soundEnabled,
            parent=self.notification_group,
        )
        self.message_sound_card = SwitchSettingCard(
            CollectionIcon("alert"),
            tr("settings.card.message_sound.title", "Incoming Message Sound"),
            tr("settings.card.message_sound.content", "Play a prompt sound when a new real-time message arrives."),
            configItem=cfg.messageSoundEnabled,
            parent=self.notification_group,
        )

        self._init_widget()

    def _init_widget(self) -> None:
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 24, 0, 24)
        self.setWidget(self.scroll_widget)
        self.setWidgetResizable(True)

        self._init_layout()
        self._connect_signals()
        self._apply_initial_values()

        if not is_win11():
            self.mica_card.setChecked(False)
            self.mica_card.setEnabled(False)
            self.mica_card.setContent(
                tr(
                    "settings.mica.unsupported",
                    "Mica is unavailable on this system. Windows 11 or newer is required.",
                )
            )

    def _init_layout(self) -> None:
        self.personal_group.addSettingCard(self.mica_card)
        self.personal_group.addSettingCard(self.theme_card)
        self.personal_group.addSettingCard(self.theme_color_card)
        self.personal_group.addSettingCard(self.zoom_card)
        self.personal_group.addSettingCard(self.language_card)

        self.notification_group.addSettingCard(self.sound_enabled_card)
        self.notification_group.addSettingCard(self.message_sound_card)

        self.app_group.addSettingCard(self.exit_confirm_card)

        self.expand_layout.setSpacing(28)
        self.expand_layout.setContentsMargins(36, 0, 36, 0)
        self.expand_layout.addWidget(self.personal_group)
        self.expand_layout.addWidget(self.notification_group)
        self.expand_layout.addWidget(self.app_group)

    def _connect_signals(self) -> None:
        cfg.themeChanged.connect(self._on_theme_changed)
        cfg.themeColorChanged.connect(setThemeColor)
        cfg.appRestartSig.connect(self._show_restart_tooltip)
        self.mica_card.checkedChanged.connect(self.micaChanged.emit)
        self.sound_enabled_card.checkedChanged.connect(self.message_sound_card.setEnabled)

    def _apply_initial_values(self) -> None:
        setTheme(cfg.get(cfg.themeMode), lazy=True)
        setThemeColor(cfg.get(cfg.themeColor))
        self.message_sound_card.setEnabled(bool(cfg.get(cfg.soundEnabled)))

    def _on_theme_changed(self, theme: Theme) -> None:
        setTheme(theme, lazy=True)

    def _show_restart_tooltip(self) -> None:
        InfoBar.info(
            tr("settings.restart.title", "Restart Required"),
            tr(
                "settings.restart.content",
                "Display scale and language changes will apply after restarting the app.",
            ),
            parent=self.window(),
            duration=2500,
        )
