"""In-memory runtime state for active 1:1 calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.utils.time import utcnow


CALL_STATUS_INVITED = "invited"
CALL_STATUS_RINGING = "ringing"
CALL_STATUS_ACCEPTED = "accepted"
CALL_STATUS_ENDED = "ended"
CALL_STATUS_REJECTED = "rejected"
CALL_STATUS_FAILED = "failed"
CALL_STATUS_TIMEOUT = "timeout"

ACTIVE_CALL_STATUSES = {CALL_STATUS_INVITED, CALL_STATUS_RINGING, CALL_STATUS_ACCEPTED}
TERMINAL_CALL_STATUSES = {CALL_STATUS_ENDED, CALL_STATUS_REJECTED, CALL_STATUS_FAILED, CALL_STATUS_TIMEOUT}


@dataclass
class ActiveCall:
    """One runtime call session tracked by the websocket layer."""

    call_id: str
    session_id: str
    initiator_id: str
    recipient_id: str
    media_type: str
    status: str = CALL_STATUS_INVITED
    created_at: datetime = field(default_factory=utcnow)
    answered_at: datetime | None = None
    ended_at: datetime | None = None
    ended_by: str = ""
    reason: str = ""

    def participant_ids(self) -> list[str]:
        """Return both unique participants."""
        return [self.initiator_id, self.recipient_id]

    def includes_user(self, user_id: str) -> bool:
        """Return whether the given user belongs to this call."""
        return user_id in {self.initiator_id, self.recipient_id}


class InMemoryCallRegistry:
    """Track one active call per user within the current process."""

    def __init__(self) -> None:
        self._calls: dict[str, ActiveCall] = {}
        self._call_id_by_user_id: dict[str, str] = {}

    def get(self, call_id: str) -> ActiveCall | None:
        """Return one call by id."""
        normalized_call_id = str(call_id or "").strip()
        if not normalized_call_id:
            return None
        call = self._calls.get(normalized_call_id)
        if call is None:
            return None
        if call.status not in ACTIVE_CALL_STATUSES:
            self._calls.pop(normalized_call_id, None)
            self._drop_user_mappings_for_call(call)
            return None
        return call

    def get_for_user(self, user_id: str) -> ActiveCall | None:
        """Return the user's current active call if one exists."""
        normalized_user_id = str(user_id or "").strip()
        call_id = self._call_id_by_user_id.get(normalized_user_id)
        if not call_id:
            return None
        call = self.get(call_id)
        if call is None or not call.includes_user(normalized_user_id):
            self._call_id_by_user_id.pop(normalized_user_id, None)
            return None
        return call

    def create(
        self,
        *,
        call_id: str,
        session_id: str,
        initiator_id: str,
        recipient_id: str,
        media_type: str,
    ) -> ActiveCall:
        """Register one brand-new call."""
        normalized_call_id = str(call_id or "").strip()
        if not normalized_call_id:
            raise ValueError("call_id is required")
        if self.get(normalized_call_id) is not None:
            raise ValueError("call_id already exists")
        active_call = ActiveCall(
            call_id=normalized_call_id,
            session_id=str(session_id or "").strip(),
            initiator_id=str(initiator_id or "").strip(),
            recipient_id=str(recipient_id or "").strip(),
            media_type=str(media_type or "").strip(),
        )
        self._calls[normalized_call_id] = active_call
        self._call_id_by_user_id[active_call.initiator_id] = normalized_call_id
        self._call_id_by_user_id[active_call.recipient_id] = normalized_call_id
        return active_call

    def mark_ringing(self, call_id: str) -> ActiveCall | None:
        """Mark one call as ringing."""
        call = self.get(call_id)
        if call is None:
            return None
        if call.status == CALL_STATUS_INVITED:
            call.status = CALL_STATUS_RINGING
        return call

    def mark_accepted(self, call_id: str) -> ActiveCall | None:
        """Mark one call as accepted."""
        call = self.get(call_id)
        if call is None:
            return None
        if call.status in {CALL_STATUS_INVITED, CALL_STATUS_RINGING}:
            call.status = CALL_STATUS_ACCEPTED
            call.answered_at = utcnow()
        return call

    def end(self, call_id: str, *, status: str = CALL_STATUS_ENDED, reason: str = "", actor_id: str = "") -> ActiveCall | None:
        """Remove one call from runtime state and return the terminal snapshot."""
        normalized_call_id = str(call_id or "").strip()
        if not normalized_call_id:
            return None
        call = self._calls.pop(normalized_call_id, None)
        if call is None:
            return None
        terminal_status = str(status or CALL_STATUS_ENDED).strip().lower()
        if terminal_status not in TERMINAL_CALL_STATUSES:
            terminal_status = CALL_STATUS_ENDED
        call.status = terminal_status
        call.reason = str(reason or terminal_status).strip().lower() or terminal_status
        call.ended_by = str(actor_id or "").strip()
        call.ended_at = utcnow()
        self._drop_user_mappings_for_call(call)
        return call

    def end_for_offline_user(self, user_id: str, *, reason: str = "disconnect") -> list[ActiveCall]:
        """End active calls for a user that has no remaining online connections."""
        call = self.get_for_user(user_id)
        if call is None:
            return []
        ended = self.end(call.call_id, status=CALL_STATUS_FAILED, reason=reason, actor_id=user_id)
        return [ended] if ended is not None else []

    def reset(self) -> None:
        """Clear all runtime state."""
        self._calls.clear()
        self._call_id_by_user_id.clear()

    def _drop_user_mappings_for_call(self, call: ActiveCall) -> None:
        """Remove user-to-call mappings that still point at the given call."""
        for participant_id in call.participant_ids():
            if self._call_id_by_user_id.get(participant_id) == call.call_id:
                self._call_id_by_user_id.pop(participant_id, None)


_call_registry: InMemoryCallRegistry | None = None


def get_call_registry() -> InMemoryCallRegistry:
    """Return the singleton call registry."""
    global _call_registry
    if _call_registry is None:
        _call_registry = InMemoryCallRegistry()
    return _call_registry
