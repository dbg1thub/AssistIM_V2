"""Shared constants and helpers for per-session AI feature toggles."""

from __future__ import annotations

from client.models.message import Session

AI_FEATURE_SMART_REPLY = "smart_reply"
AI_FEATURE_AUTO_TRANSLATE = "auto_translate"

SESSION_AI_REPLY_SUGGESTIONS_ENABLED_KEY = "ai_reply_suggestions_enabled"
SESSION_AI_AUTO_TRANSLATE_ENABLED_KEY = "ai_auto_translate_enabled"


def session_ai_feature_key(feature: str) -> str:
    normalized = str(feature or "").strip()
    if normalized == AI_FEATURE_SMART_REPLY:
        return SESSION_AI_REPLY_SUGGESTIONS_ENABLED_KEY
    if normalized == AI_FEATURE_AUTO_TRANSLATE:
        return SESSION_AI_AUTO_TRANSLATE_ENABLED_KEY
    raise ValueError(f"unsupported ai feature: {normalized}")


def session_ai_feature_enabled(session: Session | None, feature: str) -> bool:
    if session is None:
        return False
    key = session_ai_feature_key(feature)
    return bool(dict(getattr(session, "extra", {}) or {}).get(key, False))
