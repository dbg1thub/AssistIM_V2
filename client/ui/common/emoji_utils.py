"""Helpers for detecting emoji-heavy text so it can be rendered larger than plain text."""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPixmap


_EMOJI_RANGES = (
    (0x1F1E6, 0x1F1FF),  # flags
    (0x1F300, 0x1F5FF),  # symbols & pictographs
    (0x1F600, 0x1F64F),  # emoticons
    (0x1F680, 0x1F6FF),  # transport & map
    (0x1F700, 0x1F77F),
    (0x1F780, 0x1F7FF),
    (0x1F800, 0x1F8FF),
    (0x1F900, 0x1F9FF),  # supplemental symbols & pictographs
    (0x1FA70, 0x1FAFF),
    (0x2600, 0x26FF),    # misc symbols
    (0x2700, 0x27BF),    # dingbats
)

_EMOJI_MODIFIERS = {
    0x200D,  # zero-width joiner
    0x20E3,  # keycap
    0xFE0E,
    0xFE0F,  # variation selectors
}

EMOJI_FONT_FAMILIES = [
    "Segoe UI Emoji",
    "Apple Color Emoji",
    "Noto Color Emoji",
    "Segoe UI",
    "Microsoft YaHei UI",
]

COMPOSER_EMOJI_PIXEL_SIZE = 19
BUBBLE_EMOJI_PIXEL_SIZE = 19
PREVIEW_EMOJI_PIXEL_SIZE = 19
PREVIEW_ONLY_EMOJI_PIXEL_SIZE = 22
PICKER_EMOJI_PIXEL_SIZE = 22
MIXED_EMOJI_TEXT_GAP = 1
EMOJI_PIXMAP_CACHE_LIMIT = 256

_EMOJI_RESOURCE_ROOT = Path(__file__).resolve().parents[2] / "resources" / "fluent_emoji"
_EMOJI_INDEX_PATH = _EMOJI_RESOURCE_ROOT / "index.json"
_EMOJI_PIXMAP_CACHE: OrderedDict[tuple[str, int, int], QPixmap] = OrderedDict()
_EMOJI_INDEX_CACHE: dict[str, dict] | None = None


def build_emoji_font(pixel_size: int, *, letter_spacing: float = 0.5) -> QFont:
    """Return a shared emoji-first font used across composer, session list, and bubbles."""
    font = QFont()
    font.setPixelSize(pixel_size)
    try:
        font.setFamilies(EMOJI_FONT_FAMILIES)
    except AttributeError:
        font.setFamily("Segoe UI Emoji")
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
    return font


def emoji_font_for_context(context: str) -> QFont:
    """Return the shared emoji font tuned for a specific UI context."""
    context_sizes = {
        "composer": COMPOSER_EMOJI_PIXEL_SIZE,
        "bubble": BUBBLE_EMOJI_PIXEL_SIZE,
        "preview": PREVIEW_EMOJI_PIXEL_SIZE,
        "preview_only": PREVIEW_ONLY_EMOJI_PIXEL_SIZE,
        "picker": PICKER_EMOJI_PIXEL_SIZE,
    }
    return build_emoji_font(context_sizes.get(context, BUBBLE_EMOJI_PIXEL_SIZE), letter_spacing=0.5)


def emoji_box_size(pixel_size: int) -> tuple[int, int]:
    """Return a conservative box size that leaves a little room around the glyph."""
    return pixel_size + 6, pixel_size + 8


def emoji_box_size_for_context(context: str) -> tuple[int, int]:
    """Return a shared inline emoji box size for the given UI context."""
    context_sizes = {
        "composer": COMPOSER_EMOJI_PIXEL_SIZE,
        "bubble": BUBBLE_EMOJI_PIXEL_SIZE,
        "preview": PREVIEW_EMOJI_PIXEL_SIZE,
        "preview_only": PREVIEW_ONLY_EMOJI_PIXEL_SIZE,
        "picker": PICKER_EMOJI_PIXEL_SIZE,
    }
    return emoji_box_size(context_sizes.get(context, BUBBLE_EMOJI_PIXEL_SIZE))


def centered_emoji_top(
    line_top: int | float,
    line_height: int | float,
    emoji_height: int | float,
    *,
    vertical_nudge: int = 0,
) -> int:
    """Return the top coordinate for centering an emoji image inside a line box."""
    return round(float(line_top) + max(0.0, (float(line_height) - float(emoji_height)) / 2.0) + vertical_nudge)


def _cache_get(cache, key):
    """Return a cached pixmap while updating LRU order."""
    value = cache.get(key)
    if value is None:
        return None
    cache.move_to_end(key)
    return value


def _cache_put(cache, key, value, limit: int) -> None:
    """Store a cached pixmap and trim the oldest entries."""
    if key in cache:
        cache.pop(key)
    cache[key] = value
    while len(cache) > limit:
        cache.popitem(last=False)


def emoji_asset_index() -> dict[str, dict]:
    """Load the bundled Fluent Emoji asset index."""
    global _EMOJI_INDEX_CACHE
    if _EMOJI_INDEX_CACHE is not None:
        return _EMOJI_INDEX_CACHE
    if not _EMOJI_INDEX_PATH.exists():
        _EMOJI_INDEX_CACHE = {}
        return _EMOJI_INDEX_CACHE
    try:
        _EMOJI_INDEX_CACHE = json.loads(_EMOJI_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        _EMOJI_INDEX_CACHE = {}
    return _EMOJI_INDEX_CACHE


def emoji_asset_path(emoji: str) -> str | None:
    """Return the local Fluent Emoji PNG path for a glyph, if bundled."""
    info = emoji_asset_index().get(emoji)
    if not info:
        return None
    relative_path = info.get("file")
    if not relative_path:
        return None
    path = _EMOJI_RESOURCE_ROOT / relative_path
    return str(path) if path.exists() else None


def load_emoji_pixmap(emoji: str, width: int, height: int) -> QPixmap:
    """Load and scale a bundled Fluent Emoji pixmap for the given glyph."""
    width = max(1, int(width))
    height = max(1, int(height))
    cache_key = (emoji, width, height)
    cached = _cache_get(_EMOJI_PIXMAP_CACHE, cache_key)
    if cached is not None:
        return cached

    path = emoji_asset_path(emoji)
    if not path:
        return QPixmap()

    source = QPixmap(path)
    if source.isNull():
        return QPixmap()

    scaled = source.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    _cache_put(_EMOJI_PIXMAP_CACHE, cache_key, scaled, EMOJI_PIXMAP_CACHE_LIMIT)
    return scaled


def centered_text_baseline(rect: QRect | QRectF, metrics: QFontMetrics, *, vertical_nudge: int = 0) -> int:
    """Return a vertically centered text baseline inside the given rect."""
    rect_height = rect.height()
    rect_y = rect.y()
    return round(rect_y + (rect_height + metrics.ascent() - metrics.descent()) / 2) + vertical_nudge


def _is_emoji_codepoint(codepoint: int) -> bool:
    """Return whether a codepoint is within a commonly used emoji range."""
    if 0x1F3FB <= codepoint <= 0x1F3FF:
        return True
    for start, end in _EMOJI_RANGES:
        if start <= codepoint <= end:
            return True
    return False


def is_emoji_text(text: str) -> bool:
    """Return whether non-whitespace characters in text are exclusively emoji glyphs."""
    value = (text or "").strip()
    if not value:
        return False

    has_emoji = False
    for char in value:
        if char.isspace():
            continue

        codepoint = ord(char)
        if codepoint in _EMOJI_MODIFIERS:
            continue

        if _is_emoji_codepoint(codepoint):
            has_emoji = True
            continue

        return False

    return has_emoji


def is_emoji_char(char: str) -> bool:
    """Return whether a character participates in an emoji glyph sequence."""
    if not char:
        return False
    codepoint = ord(char)
    return codepoint in _EMOJI_MODIFIERS or _is_emoji_codepoint(codepoint)


def iter_emoji_runs(text: str):
    """Yield contiguous runs of either emoji or normal text."""
    value = text or ""
    if not value:
        return

    current_kind = is_emoji_char(value[0])
    buffer = [value[0]]

    for char in value[1:]:
        char_kind = is_emoji_char(char)
        if char_kind == current_kind:
            buffer.append(char)
            continue

        yield "".join(buffer), current_kind
        buffer = [char]
        current_kind = char_kind

    if buffer:
        yield "".join(buffer), current_kind


def _is_regional_indicator(char: str) -> bool:
    """Return whether a character is a regional-indicator codepoint."""
    if not char:
        return False
    codepoint = ord(char)
    return 0x1F1E6 <= codepoint <= 0x1F1FF


def iter_text_and_emoji_clusters(text: str):
    """Yield mixed text/emoji clusters while keeping emoji sequences together."""
    value = text or ""
    if not value:
        return

    text_buffer: list[str] = []
    index = 0
    length = len(value)

    while index < length:
        char = value[index]
        if not is_emoji_char(char):
            text_buffer.append(char)
            index += 1
            continue

        if text_buffer:
            yield "".join(text_buffer), False
            text_buffer.clear()

        if _is_regional_indicator(char) and index + 1 < length and _is_regional_indicator(value[index + 1]):
            yield value[index:index + 2], True
            index += 2
            continue

        cluster = [char]
        index += 1
        while index < length:
            next_char = value[index]
            if ord(next_char) in _EMOJI_MODIFIERS:
                cluster.append(next_char)
                index += 1
                continue
            if cluster[-1] == "\u200d" and is_emoji_char(next_char):
                cluster.append(next_char)
                index += 1
                continue
            if next_char == "\u200d":
                cluster.append(next_char)
                index += 1
                continue
            break

        yield "".join(cluster), True

    if text_buffer:
        yield "".join(text_buffer), False
