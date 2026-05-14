"""Helpers for local image-summary metadata."""

from __future__ import annotations

from typing import Any


IMAGE_SUMMARY_EXTRA_KEY = "image_summary"


def image_summary_context_text(extra: dict[str, Any] | None, *, max_chars: int) -> str:
    """Return ready local image summary text for AI context."""
    payload = dict((extra or {}).get(IMAGE_SUMMARY_EXTRA_KEY) or {})
    if str(payload.get("status") or "").strip() != "ready":
        return ""
    text = " ".join(str(payload.get("text") or "").split())
    if not text:
        return ""
    normalized_max = max(1, int(max_chars or 1))
    if len(text) <= normalized_max:
        return text
    return text[:normalized_max].rstrip()
