# coding: utf-8
"""Application UI configuration."""

from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QLocale
from qfluentwidgets import (
    BoolValidator,
    ColorConfigItem,
    ConfigItem,
    ConfigSerializer,
    OptionsConfigItem,
    OptionsValidator,
    QConfig,
    Theme,
    qconfig,
)


class Language(Enum):
    """Supported UI languages."""

    CHINESE_SIMPLIFIED = QLocale(QLocale.Language.Chinese, QLocale.Country.China)
    ENGLISH = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
    KOREAN = QLocale(QLocale.Language.Korean, QLocale.Country.SouthKorea)
    AUTO = QLocale()


class LanguageSerializer(ConfigSerializer):
    """Serialize language values into config."""

    def serialize(self, language: Language) -> str:
        return language.value.name() if language != Language.AUTO else "Auto"

    def deserialize(self, value: str) -> Language:
        if value == "Auto":
            return Language.AUTO

        locale = QLocale(value)
        for language in Language:
            if language == Language.AUTO:
                continue
            if language.value == locale:
                return language
        return Language.AUTO


class ThemeModeSerializer(ConfigSerializer):
    """Serialize theme mode values into config."""

    def serialize(self, mode: Theme) -> str:
        return mode.value

    def deserialize(self, value: str) -> Theme:
        return Theme(value)


def is_win11() -> bool:
    """Return whether the current system is Windows 11+."""
    return sys.platform == "win32" and sys.getwindowsversion().build >= 22000


class Config(QConfig):
    """Application config used by the desktop UI."""

    micaEnabled = ConfigItem("Window", "MicaEnabled", is_win11(), BoolValidator())
    dpiScale = OptionsConfigItem(
        "MainWindow",
        "DpiScale",
        "Auto",
        OptionsValidator([1, 1.25, 1.5, 1.75, 2, "Auto"]),
        restart=True,
    )
    language = OptionsConfigItem(
        "MainWindow",
        "Language",
        Language.AUTO,
        OptionsValidator(Language),
        LanguageSerializer(),
        restart=True,
    )

    themeMode = OptionsConfigItem(
        "Theme",
        "ThemeMode",
        Theme.AUTO,
        OptionsValidator(Theme),
        ThemeModeSerializer(),
    )
    themeColor = ColorConfigItem("Theme", "ThemeColor", "#07c160")

    exitConfirmEnabled = ConfigItem(
        "App",
        "ExitConfirmEnabled",
        True,
        BoolValidator(),
    )

    @property
    def appVersion(self) -> str:
        return "v1.0.0"

    @property
    def appName(self) -> str:
        return "AssistIM"


cfg = Config()
qconfig.load(Path("data/config.json"), cfg)


def save_config() -> None:
    """Persist current config values."""
    cfg.save()


def get_config_value(key: str, default=None):
    """Convenience getter for config values."""
    if hasattr(cfg, key):
        return cfg.get(getattr(cfg, key))
    return default


def set_config_value(key: str, value) -> None:
    """Convenience setter for config values."""
    if hasattr(cfg, key):
        cfg.set(getattr(cfg, key), value)
