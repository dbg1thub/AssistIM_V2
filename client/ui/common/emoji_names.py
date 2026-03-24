"""Localized emoji name resources for picker tooltips."""

from __future__ import annotations

import json
from pathlib import Path

from client.core.i18n import current_language_code


_RESOURCE_ROOT = Path(__file__).resolve().parents[2] / "resources"
_EMOJI_INDEX_PATH = _RESOURCE_ROOT / "fluent_emoji" / "index.json"
_EMOJI_NAMES_ROOT = _RESOURCE_ROOT / "emoji_names"
_EMOJI_INDEX_CACHE: dict[str, dict] | None = None
_EMOJI_NAME_CACHE: dict[str, dict[str, str]] = {}


def _emoji_index() -> dict[str, dict]:
    """Load the bundled Fluent Emoji index once."""
    global _EMOJI_INDEX_CACHE
    if _EMOJI_INDEX_CACHE is not None:
        return _EMOJI_INDEX_CACHE

    try:
        payload = json.loads(_EMOJI_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        payload = {}

    _EMOJI_INDEX_CACHE = payload if isinstance(payload, dict) else {}
    return _EMOJI_INDEX_CACHE


def emoji_name_map(language_code: str) -> dict[str, str]:
    """Load localized emoji tooltip names for one supported language code."""
    cached = _EMOJI_NAME_CACHE.get(language_code)
    if cached is not None:
        return cached

    path = _EMOJI_NAMES_ROOT / f"{language_code}.json"
    if not path.exists():
        _EMOJI_NAME_CACHE[language_code] = {}
        return _EMOJI_NAME_CACHE[language_code]

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}

    normalized = payload if isinstance(payload, dict) else {}
    _EMOJI_NAME_CACHE[language_code] = {
        str(key): str(value)
        for key, value in normalized.items()
        if str(key) and str(value)
    }
    return _EMOJI_NAME_CACHE[language_code]


def emoji_display_name(emoji: str, *, language_code: str | None = None) -> str:
    """Return the localized display name for one emoji."""
    resolved_language_code = language_code or current_language_code()
    localized_name = emoji_name_map(resolved_language_code).get(emoji)
    if localized_name:
        return localized_name

    info = _emoji_index().get(emoji) or {}
    default_name = str(info.get("name") or "").replace("-", " ").strip()
    return default_name or emoji
