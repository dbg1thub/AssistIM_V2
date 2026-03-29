"""Shared websocket payload helpers."""

from __future__ import annotations

import time


def ws_message(
    msg_type: str,
    data: dict,
    msg_id: str | None = None,
    seq: int = 0,
) -> dict:
    return {
        "type": msg_type,
        "seq": int(seq or 0),
        "msg_id": msg_id or "",
        "timestamp": int(time.time()),
        "data": data,
    }


def read_broadcast_payload(data: dict) -> dict:
    return {
        "session_id": data.get("session_id", ""),
        "message_id": data.get("message_id", ""),
        "last_read_seq": int(data.get("last_read_seq", 0) or 0),
        "user_id": data.get("user_id", ""),
        "read_at": data.get("read_at"),
        "event_seq": int(data.get("event_seq", 0) or 0),
    }