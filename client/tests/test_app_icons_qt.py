from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

if (
    ("PySide6.QtCore" in sys.modules and not hasattr(sys.modules["PySide6.QtCore"], "QSize"))
    or ("qfluentwidgets" in sys.modules and not hasattr(sys.modules["qfluentwidgets"], "FluentIcon"))
):
    for module_name in list(sys.modules):
        if (
            module_name == "PySide6"
            or module_name.startswith("PySide6.")
            or module_name == "qfluentwidgets"
            or module_name.startswith("qfluentwidgets.")
            or module_name == "client.core.app_icons"
        ):
            sys.modules.pop(module_name, None)

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication
from qfluentwidgets import Theme

from client.core.app_icons import AppIcon, CollectionIcon


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _opaque_rgb_values(icon) -> list[tuple[int, int, int]]:
    _ensure_app()
    pixmap = icon.pixmap(QSize(32, 32))
    image = pixmap.toImage()
    values: list[tuple[int, int, int]] = []

    for x in range(image.width()):
        for y in range(image.height()):
            color = image.pixelColor(x, y)
            if color.alpha() > 20:
                values.append((color.red(), color.green(), color.blue()))

    return values


def test_app_icon_qicon_uses_strong_contrast_theme_colors() -> None:
    dark_values = _opaque_rgb_values(AppIcon.SEND_FILL.icon(Theme.DARK))
    light_values = _opaque_rgb_values(AppIcon.SEND_FILL.icon(Theme.LIGHT))

    assert dark_values
    assert light_values
    assert min(channel for rgb in dark_values for channel in rgb) >= 245
    assert max(channel for rgb in light_values for channel in rgb) <= 10


def test_collection_icon_qicon_uses_strong_contrast_theme_colors() -> None:
    icon = CollectionIcon("arrow_down")
    dark_values = _opaque_rgb_values(icon.icon(Theme.DARK))
    light_values = _opaque_rgb_values(icon.icon(Theme.LIGHT))

    assert dark_values
    assert light_values
    assert min(channel for rgb in dark_values for channel in rgb) >= 245
    assert max(channel for rgb in light_values for channel in rgb) <= 10
