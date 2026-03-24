"""Clipboard helpers for serializing mixed composer content."""

from __future__ import annotations

import json
import os
from typing import Any

from client.models.message import MessageType

COMPOSER_SEGMENTS_MIME = "application/x-assistim-composer-segments+json"
_COMPOSER_CLIPBOARD_VERSION = 1

_ATTACHMENT_FALLBACK_LABELS = {
    MessageType.IMAGE.value: "Image",
    MessageType.VIDEO.value: "Video",
    MessageType.FILE.value: "File",
    MessageType.VOICE.value: "Voice",
}


def _normalize_segment_type(value: Any) -> str | None:
    """Return a stable string form for a segment type."""
    if isinstance(value, MessageType):
        return value.value

    normalized = str(value or "").strip()
    if not normalized:
        return None

    try:
        return MessageType(normalized).value
    except ValueError:
        return normalized


def normalize_clipboard_segments(segments: list[dict] | None) -> list[dict]:
    """Normalize mixed composer segments into a JSON-safe structure."""
    normalized_segments: list[dict] = []

    for raw_segment in segments or []:
        segment = dict(raw_segment or {})
        segment_type = _normalize_segment_type(segment.get("type"))
        if not segment_type:
            continue

        if segment_type == MessageType.TEXT.value:
            content = str(segment.get("content", "") or "")
            if content:
                normalized_segments.append(
                    {
                        "type": MessageType.TEXT.value,
                        "content": content,
                    }
                )
            continue

        file_path = str(segment.get("file_path", "") or "")
        if not file_path:
            continue

        normalized_attachment = {
            "type": segment_type,
            "file_path": file_path,
        }
        display_name = str(segment.get("display_name") or "") or os.path.basename(file_path) or "Attachment"
        normalized_attachment["display_name"] = display_name
        normalized_segments.append(normalized_attachment)

    return normalized_segments


def serialize_clipboard_segments(segments: list[dict] | None) -> bytes:
    """Serialize composer segments for an app-private clipboard MIME payload."""
    payload = {
        "version": _COMPOSER_CLIPBOARD_VERSION,
        "segments": normalize_clipboard_segments(segments),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def deserialize_clipboard_segments(raw_payload: bytes | bytearray | memoryview | str | None) -> list[dict]:
    """Deserialize a clipboard payload back into normalized composer segments."""
    if raw_payload is None:
        return []

    if isinstance(raw_payload, (bytes, bytearray, memoryview)):
        if not raw_payload:
            return []
        try:
            payload_text = bytes(raw_payload).decode("utf-8")
        except Exception:
            return []
    else:
        payload_text = str(raw_payload or "")

    if not payload_text:
        return []

    try:
        payload = json.loads(payload_text)
    except Exception:
        return []

    if not isinstance(payload, dict):
        return []

    return normalize_clipboard_segments(payload.get("segments"))


def clipboard_plain_text(segments: list[dict] | None) -> str:
    """Build a sensible plain-text clipboard fallback for mixed composer content."""
    plain_parts: list[str] = []

    for segment in normalize_clipboard_segments(segments):
        segment_type = str(segment.get("type") or "")
        if segment_type == MessageType.TEXT.value:
            plain_parts.append(str(segment.get("content", "") or ""))
            continue

        display_name = str(segment.get("display_name") or "") or os.path.basename(str(segment.get("file_path") or ""))
        label = _ATTACHMENT_FALLBACK_LABELS.get(segment_type, "Attachment")
        plain_parts.append(f"[{label}: {display_name or 'Attachment'}]")

    return "".join(plain_parts)


def clipboard_file_paths(segments: list[dict] | None) -> list[str]:
    """Return local attachment paths that should also be exposed as clipboard URLs."""
    file_paths: list[str] = []

    for segment in normalize_clipboard_segments(segments):
        if str(segment.get("type") or "") == MessageType.TEXT.value:
            continue
        file_path = str(segment.get("file_path", "") or "")
        if file_path:
            file_paths.append(file_path)

    return file_paths
