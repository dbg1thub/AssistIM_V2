"""Helpers for local voice-message transcription metadata."""

from __future__ import annotations

from typing import Any

VOICE_TRANSCRIPT_EXTRA_KEY = "voice_transcript"
VOICE_TRANSCRIPT_MAX_SECONDS = 30


def voice_transcript_display_text(extra: dict[str, Any] | None) -> str:
    """Return the default display text for one voice transcript payload."""
    payload = dict((extra or {}).get(VOICE_TRANSCRIPT_EXTRA_KEY) or {})
    status = str(payload.get("status") or "").strip()
    if status == "ready":
        return str(payload.get("text") or "").strip()
    if status == "pending":
        return "正在转文字..."
    if status == "failed":
        return "转文字失败"
    if status == "skipped" and str(payload.get("reason") or "").strip() == "audio_too_long":
        return f"语音超过 {VOICE_TRANSCRIPT_MAX_SECONDS} 秒，暂不支持转文字"
    return ""
