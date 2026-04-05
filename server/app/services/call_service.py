"""Call signaling service for 1:1 voice and video sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode
from app.realtime.call_registry import ActiveCall, InMemoryCallRegistry, get_call_registry
from app.repositories.session_repo import SessionRepository
from app.utils.time import isoformat_utc, utcnow


class CallService:
    """Validate and shape websocket call signaling events."""

    SUPPORTED_MEDIA_TYPES = {"voice", "video"}

    def __init__(
        self,
        db: Session,
        *,
        registry: InMemoryCallRegistry | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.db = db
        self.sessions = SessionRepository(db)
        self.registry = registry or get_call_registry()
        self.settings = settings or get_settings()

    def invite(
        self,
        *,
        session_id: str,
        call_id: str,
        initiator_id: str,
        media_type: str,
        target_user_id: str | None = None,
    ) -> tuple[str, list[str], dict[str, Any]]:
        """Start one new private call or return a busy event for the caller."""
        session, member_ids = self._require_private_session(session_id, initiator_id)
        recipient_id = self._resolve_recipient_id(member_ids, initiator_id, target_user_id)
        normalized_media_type = self._normalize_media_type(media_type)

        initiator_call = self.registry.get_for_user(initiator_id)
        recipient_call = self.registry.get_for_user(recipient_id)
        if initiator_call is not None or recipient_call is not None:
            busy_call = initiator_call or recipient_call
            return (
                "call_busy",
                [initiator_id],
                {
                    "call_id": str(call_id or "").strip(),
                    "session_id": str(session.id or ""),
                    "busy_user_id": recipient_id if recipient_call is not None else initiator_id,
                    "active_call_id": busy_call.call_id if busy_call is not None else "",
                    "media_type": normalized_media_type,
                },
            )

        normalized_call_id = str(call_id or "").strip()
        if not normalized_call_id:
            raise AppError(ErrorCode.INVALID_REQUEST, "call_id is required", 422)

        call = self.registry.create(
            call_id=normalized_call_id,
            session_id=str(session.id),
            initiator_id=initiator_id,
            recipient_id=recipient_id,
            media_type=normalized_media_type,
        )
        return "call_invite", [recipient_id], self._call_payload(call)

    def ringing(self, *, call_id: str, user_id: str) -> tuple[str, list[str], dict[str, Any]]:
        """Relay one ringing state change to the caller."""
        call = self._require_participant_call(call_id, user_id)
        if user_id != call.recipient_id:
            raise AppError(ErrorCode.FORBIDDEN, "only the callee can mark the call as ringing", 403)
        call = self.registry.mark_ringing(call.call_id) or call
        return "call_ringing", [call.initiator_id], self._call_payload(call, actor_id=user_id)

    def accept(self, *, call_id: str, user_id: str) -> tuple[str, list[str], dict[str, Any]]:
        """Accept one inbound call."""
        call = self._require_participant_call(call_id, user_id)
        if user_id != call.recipient_id:
            raise AppError(ErrorCode.FORBIDDEN, "only the callee can accept the call", 403)
        call = self.registry.mark_accepted(call.call_id) or call
        return "call_accept", call.participant_ids(), self._call_payload(call, actor_id=user_id)

    def reject(self, *, call_id: str, user_id: str) -> tuple[str, list[str], dict[str, Any]]:
        """Reject one inbound call."""
        call = self._require_participant_call(call_id, user_id)
        if user_id != call.recipient_id:
            raise AppError(ErrorCode.FORBIDDEN, "only the callee can reject the call", 403)
        ended_call = self.registry.end(call.call_id) or call
        return "call_reject", ended_call.participant_ids(), self._call_payload(ended_call, actor_id=user_id, reason="rejected")

    def hangup(self, *, call_id: str, user_id: str, reason: str | None = None) -> tuple[str, list[str], dict[str, Any]]:
        """End one active or pending call."""
        call = self._require_participant_call(call_id, user_id)
        ended_call = self.registry.end(call.call_id) or call
        normalized_reason = str(reason or "").strip().lower() or "hangup"
        return "call_hangup", ended_call.participant_ids(), self._call_payload(ended_call, actor_id=user_id, reason=normalized_reason)

    def relay_offer(self, *, call_id: str, user_id: str, sdp: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        """Forward one WebRTC offer to the peer."""
        call = self._require_participant_call(call_id, user_id)
        return "call_offer", [self._peer_id(call, user_id)], self._signal_payload(call, user_id, {"sdp": dict(sdp or {})})

    def relay_answer(self, *, call_id: str, user_id: str, sdp: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        """Forward one WebRTC answer to the peer."""
        call = self._require_participant_call(call_id, user_id)
        return "call_answer", [self._peer_id(call, user_id)], self._signal_payload(call, user_id, {"sdp": dict(sdp or {})})

    def relay_ice(self, *, call_id: str, user_id: str, candidate: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
        """Forward one ICE candidate to the peer."""
        call = self._require_participant_call(call_id, user_id)
        return "call_ice", [self._peer_id(call, user_id)], self._signal_payload(call, user_id, {"candidate": dict(candidate or {})})

    def get_ice_servers(self, *, user_id: str) -> dict[str, Any]:
        """Return one normalized ICE server payload for the authenticated user."""
        now = utcnow()
        ice_servers: list[dict[str, Any]] = []
        turn_auth = self._turn_auth_payload(user_id=user_id, now_ts=int(now.timestamp()))

        self._append_ice_server(ice_servers, self.settings.webrtc_ice_server_urls)
        self._append_ice_server(ice_servers, self.settings.webrtc_stun_urls)
        self._append_ice_server(
            ice_servers,
            self.settings.webrtc_turn_urls,
            username=str(turn_auth.get("username", "") or ""),
            credential=str(turn_auth.get("credential", "") or ""),
        )

        payload: dict[str, Any] = {
            "ice_servers": ice_servers,
            "generated_at": isoformat_utc(now),
            "credential_mode": str(turn_auth.get("mode", "none") or "none"),
            "ttl_seconds": int(turn_auth["ttl_seconds"]) if turn_auth.get("ttl_seconds") is not None else None,
            "expires_at": int(turn_auth["expires_at"]) if turn_auth.get("expires_at") is not None else None,
        }
        return payload

    @staticmethod
    def _append_ice_server(
        servers: list[dict[str, Any]],
        urls: tuple[str, ...] | list[str],
        *,
        username: str = "",
        credential: str = "",
    ) -> None:
        normalized_urls = [str(url or "").strip() for url in list(urls or ()) if str(url or "").strip()]
        if not normalized_urls:
            return
        payload: dict[str, Any] = {"urls": normalized_urls}
        if username:
            payload["username"] = username
        if credential:
            payload["credential"] = credential
        servers.append(payload)

    def _turn_auth_payload(self, *, user_id: str, now_ts: int) -> dict[str, Any]:
        shared_secret = str(self.settings.webrtc_turn_shared_secret or "").strip()
        if shared_secret:
            ttl_seconds = max(int(self.settings.webrtc_turn_credential_ttl_seconds or 0), 1)
            expires_at = now_ts + ttl_seconds
            username = f"{expires_at}:{str(user_id or "").strip()}"
            digest = hmac.new(
                shared_secret.encode("utf-8"),
                username.encode("utf-8"),
                hashlib.sha1,
            ).digest()
            return {
                "mode": "shared_secret",
                "username": username,
                "credential": base64.b64encode(digest).decode("ascii"),
                "ttl_seconds": ttl_seconds,
                "expires_at": expires_at,
            }

        return {
            "mode": "static" if self.settings.webrtc_turn_urls else "none",
            "username": str(self.settings.webrtc_turn_username or "").strip(),
            "credential": str(self.settings.webrtc_turn_credential or "").strip(),
            "ttl_seconds": None,
            "expires_at": None,
        }

    def _require_private_session(self, session_id: str, user_id: str):
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise AppError(ErrorCode.INVALID_REQUEST, "session_id is required", 422)
        session = self.sessions.get_by_id(normalized_session_id)
        if session is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)
        if not self.sessions.has_member(normalized_session_id, user_id):
            raise AppError(ErrorCode.FORBIDDEN, "not a session member", 403)
        if session.type != "private" or session.is_ai_session:
            raise AppError(ErrorCode.INVALID_REQUEST, "calls only support private non-AI sessions", 422)
        member_ids = self.sessions.list_member_ids(normalized_session_id)
        if len(member_ids) != 2:
            raise AppError(ErrorCode.SESSION_CONFLICT, "private call requires exactly two session members", 409)
        return session, member_ids

    def _require_participant_call(self, call_id: str, user_id: str) -> ActiveCall:
        normalized_call_id = str(call_id or "").strip()
        if not normalized_call_id:
            raise AppError(ErrorCode.INVALID_REQUEST, "call_id is required", 422)
        call = self.registry.get(normalized_call_id)
        if call is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "call not found", 404)
        if not call.includes_user(user_id):
            raise AppError(ErrorCode.FORBIDDEN, "not a call participant", 403)
        self._require_private_session(call.session_id, user_id)
        return call

    def _resolve_recipient_id(self, member_ids: list[str], initiator_id: str, target_user_id: str | None) -> str:
        normalized_target_user_id = str(target_user_id or "").strip()
        if normalized_target_user_id:
            if normalized_target_user_id == initiator_id:
                raise AppError(ErrorCode.INVALID_REQUEST, "cannot call yourself", 422)
            if normalized_target_user_id not in member_ids:
                raise AppError(ErrorCode.INVALID_REQUEST, "target_user_id is not in the session", 422)
            return normalized_target_user_id
        for member_id in member_ids:
            if member_id != initiator_id:
                return member_id
        raise AppError(ErrorCode.SESSION_CONFLICT, "unable to resolve call recipient", 409)

    def _normalize_media_type(self, media_type: str) -> str:
        normalized_media_type = str(media_type or "").strip().lower()
        if normalized_media_type not in self.SUPPORTED_MEDIA_TYPES:
            raise AppError(ErrorCode.INVALID_REQUEST, "media_type must be 'voice' or 'video'", 422)
        return normalized_media_type

    @staticmethod
    def _peer_id(call: ActiveCall, user_id: str) -> str:
        return call.recipient_id if user_id == call.initiator_id else call.initiator_id

    def _call_payload(self, call: ActiveCall, *, actor_id: str | None = None, reason: str | None = None) -> dict[str, Any]:
        payload = {
            "call_id": call.call_id,
            "session_id": call.session_id,
            "initiator_id": call.initiator_id,
            "recipient_id": call.recipient_id,
            "media_type": call.media_type,
            "status": call.status,
            "created_at": isoformat_utc(call.created_at),
            "answered_at": isoformat_utc(call.answered_at),
        }
        if actor_id:
            payload["actor_id"] = actor_id
        if reason:
            payload["reason"] = reason
        return payload

    def _signal_payload(self, call: ActiveCall, from_user_id: str, extra: dict[str, Any]) -> dict[str, Any]:
        payload = self._call_payload(call, actor_id=from_user_id)
        payload["from_user_id"] = from_user_id
        payload["to_user_id"] = self._peer_id(call, from_user_id)
        payload.update(extra)
        return payload


