"""Runtime SVG icons that render directly into the requested rect."""

from __future__ import annotations

import json
import math
from enum import Enum
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET

from qfluentwidgets import FluentIconBase, Theme, getIconColor


_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_ICON_SOURCE_DIR = _WORKSPACE_ROOT / "client" / "resources" / "icons" / "iconfont_51777"
_ICON_MANIFEST_PATH = _ICON_SOURCE_DIR / "manifest.json"

_icon_render_scale = 1.2
_collection_names_cache: list[str] | None = None
_svg_template_cache: dict[str, str] = {}
_svg_markup_cache: dict[tuple[str, str, str, str], str] = {}

_THEME_ICON_COLOR = {
    Theme.LIGHT: "#797979",
    Theme.DARK: "#929292",
}


def get_icon_render_scale() -> float:
    return _icon_render_scale


def set_icon_render_scale(scale: float) -> None:
    global _icon_render_scale

    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Icon render scale must be a positive finite number")

    _icon_render_scale = float(scale)
    _svg_markup_cache.clear()


def _normalize_icon_name(name: str) -> str:
    text = str(name or "").strip().lower()
    text = text.replace("-", "_").replace(" ", "_")
    text = re.sub(r"[^0-9a-z_\u4e00-\u9fff]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "icon"


def _source_icon_path(icon_name: str) -> Path:
    normalized_name = _normalize_icon_name(icon_name)
    if not normalized_name:
        raise ValueError("Icon name must not be empty")

    return _ICON_SOURCE_DIR / f"{normalized_name}.svg"


def _load_svg_template(icon_name: str) -> str:
    normalized_name = _normalize_icon_name(icon_name)
    cached_svg = _svg_template_cache.get(normalized_name)
    if cached_svg is not None:
        return cached_svg

    source_path = _source_icon_path(normalized_name)
    if not source_path.is_file():
        raise FileNotFoundError(f"Icon asset not found: {source_path}")

    svg = source_path.read_text(encoding="utf-8")
    _svg_template_cache[normalized_name] = svg
    return svg


def _normalize_color(value: Any) -> str:
    if value is None:
        return "#000000"

    if hasattr(value, "name"):
        try:
            return str(value.name())
        except Exception:
            pass

    return str(value)


def _resolve_theme_mode(theme=Theme.AUTO):
    if theme == Theme.DARK:
        return Theme.DARK
    if theme == Theme.LIGHT:
        return Theme.LIGHT

    inferred_color = _normalize_color(getIconColor(theme)).strip().lower()
    if inferred_color in {"white", "#fff", "#ffffff", "#ffffffff", "rgb(255,255,255)"}:
        return Theme.DARK
    return Theme.LIGHT


def _coerce_opacity(value: Any, default: float = 1.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _mode_opacity(mode: Any) -> float:
    if mode is None:
        return 1.0

    from PySide6.QtGui import QIcon

    icon_mode = getattr(QIcon, "Mode", QIcon)
    disabled_mode = getattr(icon_mode, "Disabled", getattr(QIcon, "Disabled", None))
    selected_mode = getattr(icon_mode, "Selected", getattr(QIcon, "Selected", None))

    if mode == disabled_mode:
        return 0.5
    if mode == selected_mode:
        return 0.7
    return 1.0


def _resolve_icon_opacity(theme=Theme.AUTO, mode: Any = None, **attributes) -> float:
    explicit_opacity = attributes.get("opacity")
    base_opacity = _coerce_opacity(explicit_opacity, 1.0) if explicit_opacity is not None else 1.0
    return _coerce_opacity(base_opacity * _mode_opacity(mode), 1.0)


def _transform_svg_markup(svg: str, scale: float, opacity: float) -> str:
    if abs(scale - 1.0) < 1e-9 and abs(opacity - 1.0) < 1e-9:
        return svg

    root = ET.fromstring(svg)
    view_box = str(root.attrib.get("viewBox", "0 0 1024 1024")).split()
    if len(view_box) != 4:
        if abs(opacity - 1.0) >= 1e-9:
            root.set("opacity", format(opacity, ".4g"))
        return ET.tostring(root, encoding="unicode")

    min_x, min_y, width, height = (float(value) for value in view_box)
    center_x = min_x + width / 2
    center_y = min_y + height / 2
    namespace = root.tag.partition("}")[0] + "}" if root.tag.startswith("{") else ""
    group = ET.Element(f"{namespace}g")
    if abs(scale - 1.0) >= 1e-9:
        group.set(
            "transform",
            f"translate({center_x:g} {center_y:g}) scale({scale:g}) translate({-center_x:g} {-center_y:g})",
        )
    if abs(opacity - 1.0) >= 1e-9:
        group.set("opacity", format(opacity, ".4g"))

    for child in list(root):
        root.remove(child)
        group.append(child)

    root.append(group)
    return ET.tostring(root, encoding="unicode")


def _resolve_fill_color(theme=Theme.AUTO, **attributes) -> str:
    fill = attributes.get("fill")
    if fill:
        return _normalize_color(fill)

    resolved_theme = _resolve_theme_mode(theme)
    return _THEME_ICON_COLOR.get(resolved_theme, _normalize_color(getIconColor(theme)))


def _render_svg_markup(icon_name: str, theme=Theme.AUTO, mode: Any = None, **attributes) -> str:
    normalized_name = _normalize_icon_name(icon_name)
    fill_color = _resolve_fill_color(theme, **attributes)
    opacity = _resolve_icon_opacity(theme, mode, **attributes)
    scale = get_icon_render_scale()
    scale_token = format(scale, ".3f").rstrip("0").rstrip(".")
    opacity_token = format(opacity, ".4f").rstrip("0").rstrip(".")
    cache_key = (normalized_name, fill_color, scale_token, opacity_token)

    cached_markup = _svg_markup_cache.get(cache_key)
    if cached_markup is not None:
        return cached_markup

    svg = _load_svg_template(normalized_name)
    colored_svg = svg.replace("currentColor", fill_color)
    rendered_svg = _transform_svg_markup(colored_svg, scale, opacity)
    _svg_markup_cache[cache_key] = rendered_svg
    return rendered_svg


def _paint_icon(icon_name: str, painter, rect, theme=Theme.AUTO, mode: Any = None, **attributes) -> None:
    if rect.width() <= 0 or rect.height() <= 0:
        return

    from PySide6.QtCore import QByteArray, QRectF
    from PySide6.QtSvg import QSvgRenderer

    svg_markup = _render_svg_markup(icon_name, theme, mode=mode, **attributes)
    renderer = QSvgRenderer(QByteArray(svg_markup.encode("utf-8")))
    if not renderer.isValid():
        return

    painter.save()
    renderer.render(painter, QRectF(rect))
    painter.restore()


class _RuntimeSvgIconEngine:
    """Small icon engine wrapper so QIcon-backed widgets use rect-based SVG painting."""

    def __init__(self, icon_name: str, theme=Theme.AUTO, **attributes) -> None:
        from PySide6.QtGui import QIconEngine

        class _Engine(QIconEngine):
            def __init__(self, target_name: str, target_theme, render_attributes: dict[str, Any]) -> None:
                super().__init__()
                self._target_name = target_name
                self._target_theme = target_theme
                self._render_attributes = dict(render_attributes)

            def clone(self):
                return _Engine(self._target_name, self._target_theme, self._render_attributes)

            def paint(self, painter, rect, mode, state) -> None:
                _paint_icon(
                    self._target_name,
                    painter,
                    rect,
                    self._target_theme,
                    mode=mode,
                    **self._render_attributes,
                )

            def pixmap(self, size, mode, state):
                from PySide6.QtCore import Qt, QRect
                from PySide6.QtGui import QPainter, QPixmap

                pixmap = QPixmap(size)
                pixmap.fill(Qt.GlobalColor.transparent)

                painter = QPainter(pixmap)
                try:
                    _paint_icon(
                        self._target_name,
                        painter,
                        QRect(0, 0, size.width(), size.height()),
                        self._target_theme,
                        mode=mode,
                        **self._render_attributes,
                    )
                finally:
                    painter.end()

                return pixmap

        self.engine = _Engine(icon_name, theme, attributes)


def _resolve_icon_theme(theme=Theme.AUTO, *, reverse: bool = False):
    if not reverse:
        return theme

    if theme == Theme.DARK:
        return Theme.LIGHT
    if theme == Theme.LIGHT:
        return Theme.DARK
    return theme


def _load_collection_names() -> list[str]:
    global _collection_names_cache

    if _collection_names_cache is not None:
        return list(_collection_names_cache)

    payload = json.loads(_ICON_MANIFEST_PATH.read_text(encoding="utf-8"))
    _collection_names_cache = [str(icon["sanitized_name"]) for icon in payload.get("icons", [])]
    return list(_collection_names_cache)


def available_collection_icon_names() -> list[str]:
    return _load_collection_names()


class AppIcon(FluentIconBase, Enum):
    ADD = "add"
    BRUSH = "paint_brush"
    CANCEL_MEDIUM = "dismiss_circle"
    CHAT = "chat"
    CLOSE = "dismiss"
    COMPLETED = "checkmark_circle"
    CUT = "cut"
    EMOJI_TAB_SYMBOLS = "emoji"
    FOLDER = "folder"
    GLOBE = "globe"
    HOME = "home"
    INFO = "info"
    LANGUAGE = "local_language"
    PALETTE = "color"
    PEOPLE = "people"
    PHONE = "phone"
    PHOTO = "image"
    ROBOT = "bot"
    SEND_FILL = "send"
    SETTING = "settings"
    SYNC = "arrow_sync"
    TRANSPARENT = "blur"
    VIDEO = "video"
    ZOOM = "zoom_in"

    def path(self, theme=Theme.AUTO) -> str:
        return str(_source_icon_path(self.value))

    def render(self, painter, rect, theme=Theme.AUTO, indexes=None, **attributes) -> None:
        _paint_icon(self.value, painter, rect, theme, **attributes)

    def icon(self, theme=Theme.AUTO, reverse: bool = False):
        from PySide6.QtGui import QIcon

        resolved_theme = _resolve_icon_theme(theme, reverse=reverse)
        return QIcon(_RuntimeSvgIconEngine(self.value, resolved_theme).engine)


class CollectionIcon(FluentIconBase):
    def __init__(self, name: str) -> None:
        self.name = _normalize_icon_name(name)

    def path(self, theme=Theme.AUTO) -> str:
        return str(_source_icon_path(self.name))

    def render(self, painter, rect, theme=Theme.AUTO, indexes=None, **attributes) -> None:
        _paint_icon(self.name, painter, rect, theme, **attributes)

    def icon(self, theme=Theme.AUTO, reverse: bool = False):
        from PySide6.QtGui import QIcon

        resolved_theme = _resolve_icon_theme(theme, reverse=reverse)
        return QIcon(_RuntimeSvgIconEngine(self.name, resolved_theme).engine)
