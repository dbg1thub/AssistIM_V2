"""Cleanup helpers for authenticated realtime runtime replacement."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.realtime.call_registry import get_call_registry
from app.services.call_service import CallService
from app.websocket.payloads import ws_message


logger = logging.getLogger(__name__)


async def end_active_calls_for_auth_runtime(user_id: str, *, reason: str, connection_manager: Any) -> None:
    """End active call state when one authenticated runtime is forcibly torn down."""
    normalized_user_id = str(user_id or "").strip()
    normalized_reason = str(reason or "").strip() or "auth_runtime_closed"
    if not normalized_user_id:
        return

    registry = get_call_registry()
    ended_calls = registry.end_for_offline_user(normalized_user_id, reason=normalized_reason)
    for ended_call in ended_calls:
        payload = CallService._call_payload(
            ended_call,
            actor_id=normalized_user_id,
            reason=normalized_reason,
        )
        try:
            await connection_manager.send_json_to_users(
                ended_call.participant_ids(),
                ws_message("call_hangup", payload, msg_id=str(uuid.uuid4())),
            )
        except Exception:
            logger.exception(
                "Failed to broadcast call hangup during auth runtime cleanup: user_id=%s call_id=%s reason=%s",
                normalized_user_id,
                ended_call.call_id,
                normalized_reason,
            )
