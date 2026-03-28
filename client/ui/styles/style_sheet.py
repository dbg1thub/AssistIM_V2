"""Style sheet registry for client UI pages."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from qfluentwidgets import StyleSheetBase, Theme, qconfig

STYLE_TOKENS = {
    Theme.LIGHT: {
        "{{TEXT_PRIMARY}}": "rgb(17, 24, 39)",
        "{{CARD_BG}}": "rgba(255, 255, 255, 0.84)",
        "{{CARD_BG_STRONG}}": "rgba(255, 255, 255, 0.88)",
        "{{PANEL_BG}}": "rgba(255, 255, 255, 0.72)",
        "{{SURFACE_BG}}": "rgba(248, 250, 252, 0.92)",
        "{{BORDER_COLOR}}": "rgba(0, 0, 0, 0.05)",
        "{{BORDER_COLOR_STRONG}}": "rgba(0, 0, 0, 0.08)",
        "{{TEXT_SECONDARY}}": "rgb(95, 95, 95)",
        "{{TEXT_TERTIARY}}": "rgb(71, 85, 105)",
        "{{HANDLE_COLOR}}": "rgba(15, 23, 42, 0.08)",
        "{{HANDLE_HOVER}}": "rgba(15, 23, 42, 0.12)",
        "{{TILE_BG}}": "rgba(241, 245, 249, 0.92)",
        "{{TILE_BORDER}}": "rgba(148, 163, 184, 0.18)",
        "{{TILE_TEXT}}": "rgb(72, 97, 123)",
        "{{RADIUS_CARD}}": "10px",
        "{{RADIUS_PILL}}": "8px",
    },
    Theme.DARK: {
        "{{TEXT_PRIMARY}}": "rgb(241, 245, 249)",
        "{{CARD_BG}}": "rgba(39, 43, 48, 0.88)",
        "{{CARD_BG_STRONG}}": "rgba(32, 35, 39, 0.92)",
        "{{PANEL_BG}}": "rgba(39, 43, 48, 0.76)",
        "{{SURFACE_BG}}": "rgba(20, 23, 27, 0.82)",
        "{{BORDER_COLOR}}": "rgba(255, 255, 255, 0.06)",
        "{{BORDER_COLOR_STRONG}}": "rgba(255, 255, 255, 0.10)",
        "{{TEXT_SECONDARY}}": "rgb(216, 216, 216)",
        "{{TEXT_TERTIARY}}": "rgb(226, 232, 240)",
        "{{HANDLE_COLOR}}": "rgba(255, 255, 255, 0.08)",
        "{{HANDLE_HOVER}}": "rgba(255, 255, 255, 0.14)",
        "{{TILE_BG}}": "rgba(52, 59, 66, 0.92)",
        "{{TILE_BORDER}}": "rgba(255, 255, 255, 0.08)",
        "{{TILE_TEXT}}": "rgb(226, 232, 240)",
        "{{RADIUS_CARD}}": "10px",
        "{{RADIUS_PILL}}": "8px",
    },
}


class StyleSheet(StyleSheetBase, Enum):
    """Local QSS registry that mirrors the gallery demo structure."""

    AUTH_INTERFACE = "auth_interface"
    CHAT_INTERFACE = "chat_interface"
    CHAT_PANEL = "chat_panel"
    CHAT_HEADER = "chat_header"
    MESSAGE_INPUT = "message_input"
    SESSION_PANEL = "session_panel"
    CONTACT_INTERFACE = "contact_interface"
    DISCOVERY_INTERFACE = "discovery_interface"
    SETTINGS_INTERFACE = "settings_interface"
    MESSAGE_VIDEO_WIDGET = "message_video_widget"

    def path(self, theme=Theme.AUTO):
        current_theme = qconfig.theme if theme == Theme.AUTO else theme
        base = Path(__file__).resolve().parent / "qss" / current_theme.value.lower()
        return str(base / f"{self.value}.qss")

    def content(self, theme=Theme.AUTO):
        current_theme = qconfig.theme if theme == Theme.AUTO else theme
        content = Path(self.path(current_theme)).read_text(encoding="utf-8")
        for key, value in STYLE_TOKENS[current_theme].items():
            content = content.replace(key, value)
        return content
