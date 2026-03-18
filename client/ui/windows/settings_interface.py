# coding: utf-8
"""Settings interface built with qfluentwidgets."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    ComboBoxSettingCard,
    CustomColorSettingCard,
    ExpandLayout,
    FluentIcon,
    InfoBar,
    OptionsSettingCard,
    ScrollArea,
    SettingCardGroup,
    SwitchSettingCard,
    Theme,
    setTheme,
    setThemeColor,
)

from client.core.config import cfg, is_win11


class SettingsInterface(ScrollArea):
    """Application settings page."""

    micaChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SettingsInterface")

        self.scroll_widget = QWidget(self)
        self.scroll_widget.setObjectName("settingsScrollWidget")
        self.expand_layout = ExpandLayout(self.scroll_widget)

        self.personal_group = SettingCardGroup("\u4e2a\u6027\u5316", self.scroll_widget)
        self.app_group = SettingCardGroup("\u5e94\u7528", self.scroll_widget)

        self.mica_card = SwitchSettingCard(
            FluentIcon.TRANSPARENT,
            "Mica \u6548\u679c",
            "\u4e3a\u7a97\u53e3\u8868\u9762\u542f\u7528 Win11 Mica \u80cc\u666f\u6548\u679c",
            configItem=cfg.micaEnabled,
            parent=self.personal_group,
        )
        self.theme_card = OptionsSettingCard(
            cfg.themeMode,
            FluentIcon.PALETTE,
            "\u5e94\u7528\u4e3b\u9898",
            "\u5207\u6362\u6d45\u8272\u3001\u6df1\u8272\u6216\u8ddf\u968f\u7cfb\u7edf",
            texts=["\u6d45\u8272", "\u6df1\u8272", "\u8ddf\u968f\u7cfb\u7edf"],
            parent=self.personal_group,
        )
        self.theme_color_card = CustomColorSettingCard(
            cfg.themeColor,
            FluentIcon.BRUSH,
            "\u4e3b\u9898\u8272",
            "\u66f4\u6539\u5e94\u7528\u5f3a\u8c03\u8272",
            parent=self.personal_group,
        )
        self.zoom_card = OptionsSettingCard(
            cfg.dpiScale,
            FluentIcon.ZOOM,
            "\u754c\u9762\u7f29\u653e",
            "\u8c03\u6574\u754c\u9762\u548c\u5b57\u4f53\u7684\u663e\u793a\u6bd4\u4f8b",
            texts=["100%", "125%", "150%", "175%", "200%", "\u8ddf\u968f\u7cfb\u7edf"],
            parent=self.personal_group,
        )
        self.language_card = ComboBoxSettingCard(
            cfg.language,
            FluentIcon.LANGUAGE,
            "\u754c\u9762\u8bed\u8a00",
            "\u9009\u62e9\u5e94\u7528\u754c\u9762\u7684\u663e\u793a\u8bed\u8a00",
            texts=["\u7b80\u4f53\u4e2d\u6587", "English", "\ud55c\uad6d\uc5b4", "\u8ddf\u968f\u7cfb\u7edf"],
            parent=self.personal_group,
        )

        self.exit_confirm_card = SwitchSettingCard(
            FluentIcon.CLOSE,
            "\u9000\u51fa\u524d\u786e\u8ba4",
            "\u4ece\u7cfb\u7edf\u6258\u76d8\u9000\u51fa\u5e94\u7528\u524d\u663e\u793a\u786e\u8ba4\u5bf9\u8bdd\u6846",
            configItem=cfg.exitConfirmEnabled,
            parent=self.app_group,
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
            self.mica_card.setContent("\u5f53\u524d\u7cfb\u7edf\u4e0d\u652f\u6301 Mica\uff0c\u9700 Windows 11 \u53ca\u4ee5\u4e0a")

    def _init_layout(self) -> None:
        self.personal_group.addSettingCard(self.mica_card)
        self.personal_group.addSettingCard(self.theme_card)
        self.personal_group.addSettingCard(self.theme_color_card)
        self.personal_group.addSettingCard(self.zoom_card)
        self.personal_group.addSettingCard(self.language_card)

        self.app_group.addSettingCard(self.exit_confirm_card)

        self.expand_layout.setSpacing(28)
        self.expand_layout.setContentsMargins(36, 0, 36, 0)
        self.expand_layout.addWidget(self.personal_group)
        self.expand_layout.addWidget(self.app_group)

    def _connect_signals(self) -> None:
        cfg.themeChanged.connect(self._on_theme_changed)
        cfg.themeColorChanged.connect(setThemeColor)
        cfg.appRestartSig.connect(self._show_restart_tooltip)
        self.mica_card.checkedChanged.connect(self.micaChanged.emit)

    def _apply_initial_values(self) -> None:
        setTheme(cfg.get(cfg.themeMode), lazy=True)
        setThemeColor(cfg.get(cfg.themeColor))

    def _on_theme_changed(self, theme: Theme) -> None:
        setTheme(theme, lazy=True)

    def _show_restart_tooltip(self) -> None:
        InfoBar.info(
            "\u9700\u8981\u91cd\u542f",
            "\u754c\u9762\u7f29\u653e\u548c\u8bed\u8a00\u8bbe\u7f6e\u5c06\u5728\u91cd\u542f\u5e94\u7528\u540e\u751f\u6548\u3002",
            parent=self.window(),
            duration=2500,
        )
