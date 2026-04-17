"""Chat websocket endpoints."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.database import SessionLocal
from app.core.errors import AppError, ErrorCode
from app.dependencies.settings_dependency import get_websocket_settings
from app.repositories.user_repo import UserRepository
from app.realtime.call_registry import get_call_registry
from app.services.call_service import CallService
from app.services.message_service import MessageService
from app.websocket.auth import require_websocket_user_id
from app.websocket.manager import connection_manager
from app.websocket.payloads import ws_message


websocket_router = APIRouter()
logger = logging.getLogger(__name__)


async def _send_app_error(connection_id: str, msg_id: str, exc: AppError) -> None:
    """Return an application-level websocket error without tearing down the socket."""
    logger.warning(
        "[ws-diag] send_app_error connection_id=%s msg_id=%s code=%s message=%s",
        connection_id,
        msg_id,
        exc.code,
        exc.message,
    )
    await connection_manager.send_json(
        connection_id,
        ws_message("error", {"message": exc.message, "code": exc.code}, msg_id=msg_id),
    )


def _authenticate_connection(
    connection_id: str,
    current_user_id: str | None,
    token: str | None,
    *,
    secret_settings,
) -> str:
    user_id = require_websocket_user_id(token, settings=secret_settings)
    if current_user_id is not None and current_user_id != user_id:
        raise AppError(ErrorCode.FORBIDDEN, "connection already authenticated as another user", 403)

    connection_manager.bind_user(connection_id, user_id)
    return user_id


def _require_authenticated_user(user_id: str | None) -> str:
    if user_id is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "websocket authentication required", 401)
    return user_id


def _resolve_ws_user(db, user_id: str):
    user = UserRepository(db).get_by_id(user_id)
    if user is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "user not found for websocket connection", 401)
    return user


def _require_target_message_id(data: dict) -> str:
    message_id = str(data.get("message_id") or "")
    if not message_id:
        raise AppError(ErrorCode.INVALID_REQUEST, "message_id is required", 422)
    return message_id


def _require_call_id(data: dict) -> str:
    call_id = str(data.get("call_id") or "")
    if not call_id:
        raise AppError(ErrorCode.INVALID_REQUEST, "call_id is required", 422)
    return call_id


def _require_typing_state(data: dict) -> bool:
    typing = data.get("typing")
    if not isinstance(typing, bool):
        raise AppError(ErrorCode.INVALID_REQUEST, "typing must be a boolean", 422)
    return typing


async def _handle_chat_socket(websocket: WebSocket) -> None:
    ws_settings = get_websocket_settings(websocket)
    connection_id = await connection_manager.connect(websocket)
    user_id: str | None = None

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")
            msg_id = message.get("msg_id") or str(uuid.uuid4())
            data = message.get("data", {}) if isinstance(message.get("data"), dict) else {}

            if msg_type == "auth":
                try:
                    user_id = _authenticate_connection(
                        connection_id,
                        user_id,
                        data.get("token"),
                        secret_settings=ws_settings,
                    )
                except AppError as exc:
                    await _send_app_error(connection_id, msg_id, exc)
                    await websocket.close(code=1008)
                    break

                await connection_manager.send_json(
                    connection_id,
                    ws_message("auth_ack", {"success": True, "user_id": user_id}),
                )
                continue

            try:
                current_user_id = _require_authenticated_user(user_id)
            except AppError as exc:
                await _send_app_error(connection_id, msg_id, exc)
                continue

            if msg_type == "sync_messages":
                session_cursors = data.get("session_cursors", {})
                event_cursors = data.get("event_cursors", {})
                try:
                    with SessionLocal() as db:
                        service = MessageService(db)
                        messages = service.sync_missing_messages(session_cursors, current_user_id)
                        events = service.sync_missing_events(event_cursors, current_user_id)
                except AppError as exc:
                    await _send_app_error(connection_id, msg_id, exc)
                    continue
                await connection_manager.send_json(
                    connection_id,
                    ws_message("history_messages", {"messages": messages}),
                )
                await connection_manager.send_json(
                    connection_id,
                    ws_message("history_events", {"events": events}),
                )
                continue

            if msg_type == "chat_message":
                session_id = data.get("session_id", "")
                content = data.get("content", "")
                message_type = data.get("message_type") or "text"
                message_extra = data.get("extra", {}) if isinstance(data.get("extra"), dict) else {}
                logger.info(
                    "[ws-diag] inbound_chat_message connection_id=%s user_id=%s session_id=%s msg_id=%s message_type=%s "
                    "encrypted=%s attachment_encrypted=%s content_len=%s extra_keys=%s",
                    connection_id,
                    current_user_id,
                    session_id,
                    msg_id,
                    message_type,
                    bool(dict(message_extra).get("encryption")),
                    bool(dict(message_extra).get("attachment_encryption")),
                    len(str(content or "")),
                    sorted(list(message_extra.keys())),
                )
                try:
                    with SessionLocal() as db:
                        dispatch = MessageService(db).send_websocket_message(
                            sender_id=current_user_id,
                            session_id=session_id,
                            content=content,
                            message_type=message_type,
                            message_id=msg_id,
                            extra=message_extra,
                        )
                except AppError as exc:
                    await _send_app_error(connection_id, msg_id, exc)
                    continue

                ack_message = dispatch["message"]
                recipient_ids = dispatch["recipient_ids"]
                recipient_payloads = dispatch["recipient_messages"]
                await connection_manager.send_json(
                    connection_id,
                    ws_message(
                        "message_ack",
                        {"msg_id": msg_id, "success": True, "message": ack_message},
                        msg_id=msg_id,
                    ),
                )
                if not dispatch["created"]:
                    logger.info("Idempotent websocket resend acknowledged without rebroadcast: %s", msg_id)
                    continue

                logger.info(
                    "[ws-diag] outbound_chat_dispatch session_id=%s msg_id=%s ack_message_id=%s recipient_count=%s created=%s",
                    session_id,
                    msg_id,
                    ack_message.get("message_id"),
                    len(recipient_ids),
                    dispatch["created"],
                )
                delivered_user_ids: set[str] = set()
                for recipient_id in recipient_ids:
                    recipient_message = recipient_payloads[recipient_id]
                    delivered = await connection_manager.send_json_to_users(
                        [recipient_id],
                        ws_message(
                            "chat_message",
                            recipient_message,
                            msg_id=ack_message["message_id"],
                        ),
                        exclude_connection_id=connection_id,
                    )
                    delivered_user_ids.update(delivered)
                if delivered_user_ids:
                    await connection_manager.send_json_to_users(
                        [current_user_id],
                        ws_message(
                            "message_delivered",
                            {
                                "session_id": session_id,
                                "message_id": ack_message["message_id"],
                                "user_ids": sorted(delivered_user_ids),
                            },
                            msg_id=ack_message["message_id"],
                        ),
                    )
                continue

            if msg_type == "typing":
                session_id = data.get("session_id", "")
                try:
                    typing = _require_typing_state(data)
                    with SessionLocal() as db:
                        member_ids = MessageService(db).get_session_member_ids(session_id, current_user_id)
                except AppError as exc:
                    await _send_app_error(connection_id, msg_id, exc)
                    continue
                recipient_ids = [member_id for member_id in member_ids if member_id != current_user_id]
                await connection_manager.send_json_to_users(
                    recipient_ids,
                    ws_message("typing", {"session_id": session_id, "user_id": current_user_id, "typing": typing}),
                    exclude_connection_id=connection_id,
                )
                continue

            if msg_type == "message_recall":
                try:
                    target_message_id = _require_target_message_id(data)
                    with SessionLocal() as db:
                        service = MessageService(db)
                        current_user = _resolve_ws_user(db, current_user_id)
                        recalled = service.recall(current_user, target_message_id)
                        member_ids = service.get_session_member_ids(recalled["session_id"], current_user_id)
                except AppError as exc:
                    await _send_app_error(connection_id, msg_id, exc)
                    continue
                await connection_manager.send_json_to_users(
                    member_ids,
                    ws_message(
                        "message_recall",
                        recalled,
                        msg_id=recalled["message_id"],
                        seq=int(recalled.get("event_seq", 0) or 0),
                    ),
                )
                continue

            if msg_type == "message_edit":
                try:
                    target_message_id = _require_target_message_id(data)
                    with SessionLocal() as db:
                        service = MessageService(db)
                        current_user = _resolve_ws_user(db, current_user_id)
                        edited = service.edit(
                            current_user,
                            target_message_id,
                            data.get("content", ""),
                            extra=data.get("extra", {}) if isinstance(data.get("extra"), dict) else None,
                        )
                        member_ids = service.get_session_member_ids(edited["session_id"], current_user_id)
                except AppError as exc:
                    await _send_app_error(connection_id, msg_id, exc)
                    continue
                await connection_manager.send_json_to_users(
                    member_ids,
                    ws_message(
                        "message_edit",
                        edited,
                        msg_id=edited["message_id"],
                        seq=int(edited.get("event_seq", 0) or 0),
                    ),
                )
                continue

            if msg_type == "message_delete":
                try:
                    target_message_id = _require_target_message_id(data)
                    with SessionLocal() as db:
                        service = MessageService(db)
                        current_user = _resolve_ws_user(db, current_user_id)
                        deleted = service.delete(current_user, target_message_id)
                        member_ids = service.get_session_member_ids(deleted["session_id"], current_user_id)
                except AppError as exc:
                    await _send_app_error(connection_id, msg_id, exc)
                    continue
                await connection_manager.send_json_to_users(
                    member_ids,
                    ws_message(
                        "message_delete",
                        deleted,
                        msg_id=deleted["message_id"],
                        seq=int(deleted.get("event_seq", 0) or 0),
                    ),
                )
                continue

            if msg_type in {"call_invite", "call_ringing", "call_accept", "call_reject", "call_hangup", "call_offer", "call_answer", "call_ice"}:
                logger.info(
                    "[ws-diag] inbound_call_event connection_id=%s user_id=%s type=%s msg_id=%s call_id=%s session_id=%s payload_keys=%s",
                    connection_id,
                    current_user_id,
                    msg_type,
                    msg_id,
                    str(data.get("call_id") or ""),
                    str(data.get("session_id") or ""),
                    sorted(list(data.keys())),
                )
                try:
                    with SessionLocal() as db:
                        service = CallService(db)
                        if msg_type == "call_invite":
                            outbound_type, target_user_ids, payload = service.invite(
                                session_id=str(data.get("session_id") or ""),
                                call_id=str(data.get("call_id") or msg_id),
                                initiator_id=current_user_id,
                                media_type=str(data.get("media_type") or "voice"),
                                target_user_id=str(data.get("target_user_id") or "") or None,
                            )
                        elif msg_type == "call_ringing":
                            outbound_type, target_user_ids, payload = service.ringing(
                                call_id=_require_call_id(data),
                                user_id=current_user_id,
                            )
                        elif msg_type == "call_accept":
                            outbound_type, target_user_ids, payload = service.accept(
                                call_id=_require_call_id(data),
                                user_id=current_user_id,
                            )
                        elif msg_type == "call_reject":
                            outbound_type, target_user_ids, payload = service.reject(
                                call_id=_require_call_id(data),
                                user_id=current_user_id,
                            )
                        elif msg_type == "call_hangup":
                            outbound_type, target_user_ids, payload = service.hangup(
                                call_id=_require_call_id(data),
                                user_id=current_user_id,
                                reason=str(data.get("reason") or "") or None,
                            )
                        elif msg_type == "call_offer":
                            outbound_type, target_user_ids, payload = service.relay_offer(
                                call_id=_require_call_id(data),
                                user_id=current_user_id,
                                sdp=data.get("sdp", {}) if isinstance(data.get("sdp"), dict) else {},
                            )
                        elif msg_type == "call_answer":
                            outbound_type, target_user_ids, payload = service.relay_answer(
                                call_id=_require_call_id(data),
                                user_id=current_user_id,
                                sdp=data.get("sdp", {}) if isinstance(data.get("sdp"), dict) else {},
                            )
                        else:
                            outbound_type, target_user_ids, payload = service.relay_ice(
                                call_id=_require_call_id(data),
                                user_id=current_user_id,
                                candidate=data.get("candidate", {}) if isinstance(data.get("candidate"), dict) else {},
                            )
                except AppError as exc:
                    await _send_app_error(connection_id, msg_id, exc)
                    continue

                payload["actor_connection_id"] = connection_id
                if outbound_type == "call_ringing":
                    payload["ringing_connection_id"] = connection_id
                elif outbound_type == "call_accept":
                    payload["accepted_connection_id"] = connection_id
                    payload["active_connection_id"] = connection_id
                elif outbound_type in {"call_offer", "call_answer", "call_ice"}:
                    payload["active_connection_id"] = connection_id

                outbound_message = ws_message(outbound_type, payload, msg_id=str(uuid.uuid4()))
                logger.info(
                    "[ws-diag] outbound_call_event type=%s call_id=%s target_user_ids=%s payload_keys=%s",
                    outbound_type,
                    str(payload.get("call_id") or ""),
                    list(target_user_ids),
                    sorted(list(payload.keys())),
                )
                if outbound_type == "call_invite":
                    for target_user_id in target_user_ids:
                        if target_user_id == current_user_id:
                            await connection_manager.send_json(connection_id, outbound_message)
                        else:
                            await connection_manager.send_json_to_one_user_connection(target_user_id, outbound_message)
                    continue

                await connection_manager.send_json_to_users(target_user_ids, outbound_message)
                continue

            await connection_manager.send_json(
                connection_id,
                ws_message(
                    "error",
                    {"message": f"unsupported message type: {msg_type}"},
                    msg_id=msg_id,
                ),
            )

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Chat websocket loop crashed for connection %s", connection_id)
    finally:
        disconnected_user_id, became_offline = await connection_manager.disconnect(websocket)
        if disconnected_user_id and became_offline:
            registry = get_call_registry()
            for ended_call in registry.end_for_offline_user(disconnected_user_id, reason="disconnect"):
                payload = CallService._call_payload(
                    ended_call,
                    actor_id=disconnected_user_id,
                    reason="disconnect",
                )
                await connection_manager.send_json_to_users(
                    ended_call.participant_ids(),
                    ws_message("call_hangup", payload, msg_id=str(uuid.uuid4())),
                )


@websocket_router.websocket("/ws")
async def websocket_chat(websocket: WebSocket) -> None:
    await _handle_chat_socket(websocket)
