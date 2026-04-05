"""In-memory runtime state for active 1:1 calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.utils.time import utcnow


ACTIVE_CALL_STATUSES = {"invited", "ringing", "accepted"}


@dataclass
class ActiveCall:
    """One runtime call session tracked by the websocket layer."""

    call_id: str
    session_id: str
    initiator_id: str
    recipient_id: str
    media_type: str
    status: str = "invited"
    created_at: datetime = field(default_factory=utcnow)
    answered_at: datetime | None = None

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
        return self._calls.get(str(call_id or "").strip())

    def get_for_user(self, user_id: str) -> ActiveCall | None:
        """Return the user's current active call if one exists."""
        normalized_user_id = str(user_id or "").strip()
        call_id = self._call_id_by_user_id.get(normalized_user_id)
        if not call_id:
            return None
        call = self._calls.get(call_id)
        if call is None or call.status not in ACTIVE_CALL_STATUSES:
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
        active_call = ActiveCall(
            call_id=call_id,
            session_id=session_id,
            initiator_id=initiator_id,
            recipient_id=recipient_id,
            media_type=media_type,
        )
        self._calls[call_id] = active_call
        self._call_id_by_user_id[initiator_id] = call_id
        self._call_id_by_user_id[recipient_id] = call_id
        return active_call

    def mark_ringing(self, call_id: str) -> ActiveCall | None:
        """Mark one call as ringing."""
        call = self.get(call_id)
        if call is None:
            return None
        call.status = "ringing"
        return call

    def mark_accepted(self, call_id: str) -> ActiveCall | None:
        """Mark one call as accepted."""
        call = self.get(call_id)
        if call is None:
            return None
        call.status = "accepted"
        call.answered_at = utcnow()
        return call

    def end(self, call_id: str) -> ActiveCall | None:
        """Remove one call from runtime state."""
        normalized_call_id = str(call_id or "").strip()
        if not normalized_call_id:
            return None
        call = self._calls.pop(normalized_call_id, None)
        if call is None:
            return None
        for participant_id in call.participant_ids():
            if self._call_id_by_user_id.get(participant_id) == normalized_call_id:
                self._call_id_by_user_id.pop(participant_id, None)
        return call

    def reset(self) -> None:
        """Clear all runtime state."""
        self._calls.clear()
        self._call_id_by_user_id.clear()


_call_registry: InMemoryCallRegistry | None = None


def get_call_registry() -> InMemoryCallRegistry:
    """Return the singleton call registry."""
    global _call_registry
    if _call_registry is None:
        _call_registry = InMemoryCallRegistry()
    return _call_registry
