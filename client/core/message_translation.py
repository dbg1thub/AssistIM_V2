"""Helpers for local AI message translation."""

from __future__ import annotations

import re

AI_TRANSLATION_EXTRA_KEY = "ai_translation"
AI_TRANSLATION_NOOP_MARKER = "__ASSISTIM_NO_TRANSLATION__"


def language_name_for_code(language_code: str) -> str:
    normalized = str(language_code or "").strip()
    if normalized == "zh-CN":
        return "中文"
    if normalized == "ko-KR":
        return "韩文"
    return "英文"


def detect_text_language_code(text: str) -> str:
    """Return a coarse language code for obvious Chinese, English, or Korean text."""
    value = str(text or "").strip()
    if not value:
        return ""

    chinese = sum(1 for char in value if "\u4e00" <= char <= "\u9fff")
    korean = sum(1 for char in value if "\uac00" <= char <= "\ud7af")
    latin = sum(1 for char in value if ("a" <= char.lower() <= "z"))
    meaningful = chinese + korean + latin
    if meaningful <= 0:
        return ""

    if chinese >= 2 and chinese / meaningful >= 0.45:
        return "zh-CN"
    if korean >= 2 and korean / meaningful >= 0.45:
        return "ko-KR"
    if latin >= 3 and latin / meaningful >= 0.6:
        return "en-US"
    return ""


def should_auto_translate_text(text: str, target_language_code: str) -> bool:
    """Return whether auto-translation should run before involving the model."""
    normalized = re.sub(r"\s+", "", str(text or ""))
    if not normalized:
        return False
    detected = detect_text_language_code(normalized)
    if not detected:
        return False
    return detected != str(target_language_code or "").strip()
