"""Manager for websocket call signaling state."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Optional

from client.core import logging
from client.core.exceptions import ValidationError
from client.core.logging import setup_logging
from client.events.event_bus import get_event_bus
from client.managers.connection_manager import get_connection_manager
from client.models.call import ActiveCallState, CallDirection, CallMediaType, CallStatus
from client.models.message import Session


setup_logging()
logger = logging.get_logger(__name__)


class CallEvent:
    """Event bus topics emitted by the call manager."""

    INVITE_SENT = "call.invite_sent"
    INVITE_RECEIVED = "call.invite_received"
    RINGING = "call.ringing"
    ACCEPTED = "call.accepted"
    REJECTED = "call.rejected"
    ENDED = "call.ended"
    BUSY = "call.busy"
    FAILED = "call.failed"
    SIGNAL = "call.signal"


class CallManager:
    """Track one pending or active 1:1 call and relay websocket events."""

    UNANSWERED_TIMEOUT_SECONDS = 45

    SIGNALING_EVENT_TYPES = {
        "call_invite",
        "call_ringing",
        "call_accept",
        "call_reject",
        "call_hangup",
        "call_busy",
        "call_offer",
        "call_answer",
        "call_ice",
        "error",
    }

    def __init__(self) -> None:
        self._conn_manager = get_connection_manager()
        self._event_bus = get_event_bus()
        self._user_id = ""
        self._active_call: Optional[ActiveCallState] = None
        self._unanswered_timeout_task: asyncio.Task | None = None
        self._initialized = False
        self._timing_origins: dict[str, float] = {}

    @property
    def active_call(self) -> Optional[ActiveCallState]:
        """Return the current active or pending call."""
        return self._active_call

    async def initialize(self) -> None:
        """Attach the websocket listener once."""
        if self._initialized:
            return
        self._conn_manager.add_message_listener(self._handle_ws_message)
        self._initialized = True

    async def close(self) -> None:
        """Detach listeners and reset runtime state."""
        if self._initialized:
            self._conn_manager.remove_message_listener(self._handle_ws_message)
        self._cancel_unanswered_timeout()
        self._active_call = None
        self._initialized = False

    def set_user_id(self, user_id: str) -> None:
        """Set the current authenticated user id."""
        self._user_id = str(user_id or "")
        if not self._user_id:
            self._cancel_unanswered_timeout()
            self._active_call = None

    async def start_call(self, session: Session, media_type: str) -> ActiveCallState:
        """Start one outbound voice or video call invite."""
        self._ensure_call_target(session)
        normalized_media_type = self._normalize_media_type(media_type)
        if self._active_call is not None and self._active_call.status not in {CallStatus.ENDED.value, CallStatus.REJECTED.value, CallStatus.FAILED.value, CallStatus.BUSY.value}:
            raise ValidationError("Another call is already active")

        peer_user_id = self._resolve_peer_user_id(session)
        call_id = str(uuid.uuid4())
        sent = await self._conn_manager.send_call_event(
            "call_invite",
            {
                "call_id": call_id,
                "session_id": session.session_id,
                "media_type": normalized_media_type,
                "target_user_id": peer_user_id,
            },
            msg_id=call_id,
        )
        if not sent:
            raise ValidationError("Unable to send call invite")

        self._active_call = ActiveCallState(
            call_id=call_id,
            session_id=session.session_id,
            initiator_id=self._user_id,
            recipient_id=peer_user_id,
            media_type=normalized_media_type,
            direction=CallDirection.OUTGOING.value,
            status=CallStatus.INVITING.value,
        )
        self._arm_unanswered_timeout(call_id)
        self._log_timing(call_id, "invite_sent", session_id=session.session_id, peer_user_id=peer_user_id)
        await self._event_bus.emit(CallEvent.INVITE_SENT, {"call": self._active_call, "session": session})
        return self._active_call

    async def accept_call(self, call_id: str) -> bool:
        """Accept one inbound call."""
        normalized_call_id = str(call_id or "").strip()
        if not normalized_call_id:
            raise ValidationError("call_id is required")
        self._log_timing(normalized_call_id, "accept_requested")
        return await self._conn_manager.send_call_event(
            "call_accept",
            {"call_id": normalized_call_id},
            msg_id=normalized_call_id,
        )

    async def reject_call(self, call_id: str) -> bool:
        """Reject one inbound call."""
        normalized_call_id = str(call_id or "").strip()
        if not normalized_call_id:
            raise ValidationError("call_id is required")
        return await self._conn_manager.send_call_event(
            "call_reject",
            {"call_id": normalized_call_id},
            msg_id=normalized_call_id,
        )

    async def hangup_call(self, call_id: str, *, reason: str | None = None) -> bool:
        """Hang up one current call."""
        normalized_call_id = str(call_id or "").strip()
        if not normalized_call_id:
            raise ValidationError("call_id is required")
        payload = {"call_id": normalized_call_id}
        normalized_reason = str(reason or "").strip().lower()
        if normalized_reason:
            payload["reason"] = normalized_reason
        return await self._conn_manager.send_call_event(
            "call_hangup",
            payload,
            msg_id=normalized_call_id,
        )

    async def send_ringing(self, call_id: str) -> bool:
        """Notify the caller that the local user is being alerted."""
        normalized_call_id = str(call_id or "").strip()
        if not normalized_call_id:
            raise ValidationError("call_id is required")
        self._log_timing(normalized_call_id, "ringing_requested")
        return await self._conn_manager.send_call_event(
            "call_ringing",
            {"call_id": normalized_call_id},
            msg_id=normalized_call_id,
        )

    async def send_offer(self, call_id: str, sdp: dict[str, Any]) -> bool:
        """Forward one WebRTC offer."""
        return await self._send_signal_payload("call_offer", call_id, {"sdp": dict(sdp or {})})

    async def send_answer(self, call_id: str, sdp: dict[str, Any]) -> bool:
        """Forward one WebRTC answer."""
        return await self._send_signal_payload("call_answer", call_id, {"sdp": dict(sdp or {})})

    async def send_ice_candidate(self, call_id: str, candidate: dict[str, Any]) -> bool:
        """Forward one ICE candidate."""
        return await self._send_signal_payload("call_ice", call_id, {"candidate": dict(candidate or {})})

    async def _send_signal_payload(self, event_type: str, call_id: str, extra: dict[str, Any]) -> bool:
        normalized_call_id = str(call_id or "").strip()
        if not normalized_call_id:
            raise ValidationError("call_id is required")
        payload = {"call_id": normalized_call_id}
        payload.update(extra)
        self._log_timing(normalized_call_id, f"{event_type}_send")
        return await self._conn_manager.send_call_event(event_type, payload, msg_id=normalized_call_id)

    async def _handle_ws_message(self, message: dict[str, Any]) -> None:
        """React to websocket signaling events relevant to calls."""
        message_type = str(message.get("type") or "")
        if message_type not in self.SIGNALING_EVENT_TYPES:
            return

        if message_type == "error":
            await self._handle_error_message(message)
            return

        payload = message.get("data", {}) if isinstance(message.get("data"), dict) else {}
        call_id = str(payload.get("call_id") or "")
        if call_id:
            self._log_timing(call_id, f"ws_{message_type}_received")
        if message_type == "call_invite":
            await self._handle_invite(payload)
            return
        if message_type == "call_ringing":
            await self._handle_state_event(payload, CallStatus.RINGING, CallEvent.RINGING)
            return
        if message_type == "call_accept":
            await self._handle_state_event(payload, CallStatus.ACCEPTED, CallEvent.ACCEPTED)
            return
        if message_type == "call_reject":
            await self._handle_terminal_event(payload, CallStatus.REJECTED, CallEvent.REJECTED)
            return
        if message_type == "call_hangup":
            await self._handle_terminal_event(payload, CallStatus.ENDED, CallEvent.ENDED)
            return
        if message_type == "call_busy":
            await self._handle_busy(payload)
            return
        await self._event_bus.emit(CallEvent.SIGNAL, {"type": message_type, "data": payload})

    async def _handle_invite(self, payload: dict[str, Any]) -> None:
        direction = CallDirection.INCOMING.value
        if str(payload.get("initiator_id") or "") == self._user_id:
            direction = CallDirection.OUTGOING.value
        self._active_call = ActiveCallState.from_payload(
            payload,
            direction=direction,
            fallback_status=CallStatus.INVITING.value,
        )
        await self._event_bus.emit(CallEvent.INVITE_RECEIVED, {"call": self._active_call, "payload": payload})

    async def _handle_state_event(self, payload: dict[str, Any], status: CallStatus, event_type: str) -> None:
        state = self._merge_state(payload, status=status.value)
        if status == CallStatus.ACCEPTED:
            self._cancel_unanswered_timeout()
        await self._event_bus.emit(event_type, {"call": state, "payload": payload})

    async def _handle_terminal_event(self, payload: dict[str, Any], status: CallStatus, event_type: str) -> None:
        state = self._merge_state(payload, status=status.value)
        self._cancel_unanswered_timeout()
        await self._event_bus.emit(event_type, {"call": state, "payload": payload})
        self._timing_origins.pop(state.call_id, None)
        self._active_call = None

    async def _handle_busy(self, payload: dict[str, Any]) -> None:
        state = self._merge_state(payload, status=CallStatus.BUSY.value)
        self._cancel_unanswered_timeout()
        await self._event_bus.emit(CallEvent.BUSY, {"call": state, "payload": payload})
        self._timing_origins.pop(state.call_id, None)
        self._active_call = None

    async def _handle_error_message(self, message: dict[str, Any]) -> None:
        if self._active_call is None:
            return
        if str(message.get("msg_id") or "") != self._active_call.call_id:
            return
        payload = message.get("data", {}) if isinstance(message.get("data"), dict) else {}
        failed_call = self._active_call
        failed_call.status = CallStatus.FAILED.value
        failed_call.reason = str(payload.get("message") or "Call signaling failed")
        self._cancel_unanswered_timeout()
        await self._event_bus.emit(CallEvent.FAILED, {"call": failed_call, "payload": payload})
        self._timing_origins.pop(failed_call.call_id, None)
        self._active_call = None

    def _arm_unanswered_timeout(self, call_id: str) -> None:
        self._cancel_unanswered_timeout()
        self._unanswered_timeout_task = asyncio.create_task(self._run_unanswered_timeout(call_id))

    def _cancel_unanswered_timeout(self) -> None:
        task = self._unanswered_timeout_task
        if task is None:
            return
        self._unanswered_timeout_task = None
        task.cancel()

    async def _run_unanswered_timeout(self, call_id: str) -> None:
        try:
            await asyncio.sleep(self.UNANSWERED_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            return

        active_call = self._active_call
        if active_call is None or active_call.call_id != call_id:
            return
        if active_call.direction != CallDirection.OUTGOING.value:
            return
        if active_call.status not in {CallStatus.INVITING.value, CallStatus.RINGING.value}:
            return

        self._log_timing(call_id, "timeout_reached")
        await self.hangup_call(call_id, reason="timeout")

    def _log_timing(self, call_id: str, stage: str, **extra: Any) -> None:
        """Log one call-timeline checkpoint with a stable relative timestamp."""
        normalized_call_id = str(call_id or "").strip()
        if not normalized_call_id:
            return
        now = time.perf_counter()
        origin = self._timing_origins.setdefault(normalized_call_id, now)
        delta_ms = int((now - origin) * 1000)
        details = " ".join(f"{key}={value}" for key, value in extra.items() if value not in {None, ""})
        suffix = f" {details}" if details else ""
        logger.info("[call-timing] call_id=%s t=+%dms stage=%s%s", normalized_call_id, delta_ms, stage, suffix)

    def _merge_state(self, payload: dict[str, Any], *, status: str) -> ActiveCallState:
        current_state = self._active_call
        direction = CallDirection.OUTGOING.value
        if current_state is not None and current_state.call_id == str(payload.get("call_id") or ""):
            direction = current_state.direction
        elif str(payload.get("recipient_id") or "") == self._user_id:
            direction = CallDirection.INCOMING.value

        merged = ActiveCallState.from_payload(payload, direction=direction, fallback_status=status)
        if not merged.initiator_id and current_state is not None:
            merged.initiator_id = current_state.initiator_id
        if not merged.recipient_id and current_state is not None:
            merged.recipient_id = current_state.recipient_id
        if not merged.media_type and current_state is not None:
            merged.media_type = current_state.media_type
        merged.status = status
        self._active_call = merged
        return merged

    def _ensure_call_target(self, session: Session) -> None:
        if session.is_ai_session:
            raise ValidationError("AI sessions do not support calls")
        if session.session_type != "direct":
            raise ValidationError("Only direct sessions support calls right now")
        if not self._user_id:
            raise ValidationError("Current user is not authenticated")
        if not self._resolve_peer_user_id(session):
            raise ValidationError("Unable to resolve the other participant")

    def _resolve_peer_user_id(self, session: Session) -> str:
        for participant_id in session.participant_ids:
            normalized_participant_id = str(participant_id or "").strip()
            if normalized_participant_id and normalized_participant_id != self._user_id:
                return normalized_participant_id
        counterpart_id = str(session.extra.get("counterpart_id") or "").strip()
        if counterpart_id and counterpart_id != self._user_id:
            return counterpart_id
        return ""

    @staticmethod
    def _normalize_media_type(media_type: str) -> str:
        normalized_media_type = str(media_type or "").strip().lower()
        if normalized_media_type not in {CallMediaType.VOICE.value, CallMediaType.VIDEO.value}:
            raise ValidationError("Unsupported call type")
        return normalized_media_type


_call_manager: Optional[CallManager] = None


def get_call_manager() -> CallManager:
    """Return the global call manager instance."""
    global _call_manager
    if _call_manager is None:
        _call_manager = CallManager()
    return _call_manager
