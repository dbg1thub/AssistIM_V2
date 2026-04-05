"""Client-side call signaling models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class CallMediaType(StrEnum):
    """Supported call media modes."""

    VOICE = "voice"
    VIDEO = "video"


class CallDirection(StrEnum):
    """Whether the active call was initiated locally or remotely."""

    OUTGOING = "outgoing"
    INCOMING = "incoming"


class CallStatus(StrEnum):
    """High-level runtime call status used by the client UI."""

    INVITING = "inviting"
    RINGING = "ringing"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ENDED = "ended"
    BUSY = "busy"
    FAILED = "failed"


@dataclass
class ActiveCallState:
    """One active or pending call tracked by the desktop client."""

    call_id: str
    session_id: str
    initiator_id: str
    recipient_id: str
    media_type: str
    direction: str
    status: str
    actor_id: str = ""
    reason: str = ""
    created_at: datetime | None = None
    answered_at: datetime | None = None

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        direction: str,
        fallback_status: str,
    ) -> "ActiveCallState":
        """Build one state snapshot from a websocket payload."""
        return cls(
            call_id=str(payload.get("call_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            initiator_id=str(payload.get("initiator_id") or ""),
            recipient_id=str(payload.get("recipient_id") or ""),
            media_type=str(payload.get("media_type") or CallMediaType.VOICE.value),
            direction=direction,
            status=str(payload.get("status") or fallback_status),
            actor_id=str(payload.get("actor_id") or ""),
            reason=str(payload.get("reason") or ""),
            created_at=_parse_datetime(payload.get("created_at")),
            answered_at=_parse_datetime(payload.get("answered_at")),
        )

    def peer_user_id(self, current_user_id: str) -> str:
        """Return the other participant."""
        if current_user_id == self.initiator_id:
            return self.recipient_id
        return self.initiator_id


def _parse_datetime(value: Any) -> datetime | None:
    """Parse one ISO timestamp when present."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
