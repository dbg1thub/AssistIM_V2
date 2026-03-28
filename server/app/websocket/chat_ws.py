"""Chat websocket endpoints."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.database import SessionLocal
from app.core.errors import AppError, ErrorCode
from app.core.security import decode_access_token, token_session_version
from app.dependencies.settings_dependency import get_websocket_settings
from app.repositories.user_repo import UserRepository
from app.services.message_service import MessageService
from app.websocket.manager import connection_manager
from app.websocket.presence_ws import bind_websocket_user, event_payload


websocket_router = APIRouter()
logger = logging.getLogger(__name__)


def _ws_message(
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

def _read_broadcast_payload(data: dict) -> dict:
    return {
        "session_id": data.get("session_id", ""),
        "message_id": data.get("message_id", ""),
        "last_read_seq": int(data.get("last_read_seq", 0) or 0),
        "user_id": data.get("user_id", ""),
        "read_at": data.get("read_at"),
        "event_seq": int(data.get("event_seq", 0) or 0),
    }


async def _broadcast_offline_if_needed(user_id: str | None, became_offline: bool) -> None:
    if user_id and became_offline:
        await connection_manager.broadcast_json(event_payload("offline", {"user_id": user_id}))


async def _send_app_error(connection_id: str, msg_id: str, exc: AppError) -> None:
    """Return an application-level websocket error without tearing down the socket."""
    await connection_manager.send_json(
        connection_id,
        _ws_message("error", {"message": exc.message, "code": exc.code}, msg_id=msg_id),
    )


def _authenticate_connection(
    connection_id: str,
    current_user_id: str | None,
    token: str | None,
    *,
    secret_settings,
) -> str:
    if not token:
        raise AppError(ErrorCode.UNAUTHORIZED, "websocket authentication token required", 401)

    payload = decode_access_token(token, settings=secret_settings)
    user_id = payload.get("sub")
    if not user_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "invalid access token", 401)
    with SessionLocal() as db:
        user = UserRepository(db).get_by_id(user_id)
        if user is None:
            raise AppError(ErrorCode.UNAUTHORIZED, "user not found for websocket connection", 401)
        if token_session_version(payload) != int(getattr(user, "auth_session_version", 0) or 0):
            raise AppError(ErrorCode.UNAUTHORIZED, "session expired", 401)
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

def _outbound_message_data(saved: dict, *, content_override: str | None = None, extra_override: dict | None = None) -> dict:
    merged_extra = dict(saved.get("extra") or {})
    if extra_override:
        merged_extra.update(extra_override)
    return {
        "message_id": saved["message_id"],
        "session_id": saved["session_id"],
        "sender_id": saved["sender_id"],
        "content": saved["content"] if content_override is None else content_override,
        "message_type": saved.get("message_type") or "text",
        "status": saved.get("status", "sent"),
        "timestamp": saved.get("timestamp") or saved.get("created_at"),
        "created_at": saved.get("created_at"),
        "updated_at": saved.get("updated_at") or saved.get("created_at"),
        "session_seq": saved.get("session_seq", 0),
        "read_count": saved.get("read_count", 0),
        "read_target_count": saved.get("read_target_count", 0),
        "read_by_user_ids": saved.get("read_by_user_ids", []),
        "is_read_by_me": saved.get("is_read_by_me", False),
        "extra": merged_extra,
    }


async def _handle_chat_socket(websocket: WebSocket) -> None:
    ws_settings = get_websocket_settings(websocket)
    connection_id = await connection_manager.connect(websocket)
    user_id = bind_websocket_user(websocket, connection_id)
    if user_id is not None:
        await connection_manager.broadcast_json(event_payload("online", {"user_id": user_id}))

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")
            msg_id = message.get("msg_id") or str(uuid.uuid4())
            data = message.get("data", {}) if isinstance(message.get("data"), dict) else {}

            if msg_type == "auth":
                try:
                    was_authenticated = user_id is not None
                    user_id = _authenticate_connection(
                        connection_id,
                        user_id,
                        data.get("token"),
                        secret_settings=ws_settings,
                    )
                except AppError as exc:
                    await _send_app_error(connection_id, msg_id, exc)
                    continue

                if not was_authenticated:
                    await connection_manager.broadcast_json(
                        event_payload("online", {"user_id": user_id})
                    )
                await connection_manager.send_json(
                    connection_id,
                    _ws_message("auth_ack", {"success": True, "user_id": user_id}),
                )
                continue

            if msg_type in {"heartbeat", "ping"}:
                await connection_manager.send_json(connection_id, event_payload("pong", {}))
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
                    _ws_message("history_messages", {"messages": messages}),
                )
                await connection_manager.send_json(
                    connection_id,
                    _ws_message("history_events", {"events": events}),
                )
                continue

            if msg_type == "chat_message":
                session_id = data.get("session_id", "")
                content = data.get("content", "")
                message_type = data.get("message_type") or "text"
                message_extra = data.get("extra", {}) if isinstance(data.get("extra"), dict) else {}
                try:
                    with SessionLocal() as db:
                        service = MessageService(db)
                        member_ids = service.get_session_member_ids(session_id, current_user_id)
                        saved, created = service.send_ws_message(
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

                ack_message = _outbound_message_data(saved, content_override=content)
                recipient_ids = [member_id for member_id in member_ids if member_id != current_user_id]
                await connection_manager.send_json(
                    connection_id,
                    _ws_message(
                        "message_ack",
                        {"msg_id": msg_id, "success": True, "message": ack_message},
                        msg_id=msg_id,
                    ),
                )
                if not created:
                    logger.info("Idempotent websocket resend acknowledged without rebroadcast: %s", msg_id)
                    continue

                payload = _ws_message(
                    "chat_message",
                    ack_message,
                    msg_id=saved["message_id"],
                )
                delivered_user_ids = await connection_manager.send_json_to_users(
                    recipient_ids,
                    payload,
                    exclude_connection_id=connection_id,
                )
                if delivered_user_ids:
                    await connection_manager.send_json_to_users(
                        [current_user_id],
                        _ws_message(
                            "message_delivered",
                            {
                                "session_id": session_id,
                                "message_id": saved["message_id"],
                                "user_ids": sorted(delivered_user_ids),
                            },
                            msg_id=saved["message_id"],
                        ),
                    )
                continue

            if msg_type == "typing":
                session_id = data.get("session_id", "")
                try:
                    with SessionLocal() as db:
                        member_ids = MessageService(db).get_session_member_ids(session_id, current_user_id)
                except AppError as exc:
                    await _send_app_error(connection_id, msg_id, exc)
                    continue
                await connection_manager.send_json_to_users(
                    member_ids,
                    event_payload("typing", {"session_id": session_id, "user_id": current_user_id}),
                    exclude_connection_id=connection_id,
                )
                continue

            if msg_type in {"read_ack", "read"}:
                session_id = data.get("session_id", "")
                try:
                    target_message_id = _require_target_message_id(data)
                    with SessionLocal() as db:
                        service = MessageService(db)
                        current_user = _resolve_ws_user(db, current_user_id)
                        read_state = service.batch_read(current_user, session_id, target_message_id)
                        member_ids = service.get_session_member_ids(session_id, current_user_id)
                except AppError as exc:
                    await _send_app_error(connection_id, msg_id, exc)
                    continue
                if read_state.get("advanced"):
                    await connection_manager.send_json_to_users(
                        member_ids,
                        _ws_message(
                            "read",
                            _read_broadcast_payload(read_state),
                            msg_id=read_state.get("message_id", ""),
                            seq=int(read_state.get("event_seq", 0) or 0),
                        ),
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
                    _ws_message(
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
                        edited = service.edit(current_user, target_message_id, data.get("content", ""))
                        member_ids = service.get_session_member_ids(edited["session_id"], current_user_id)
                except AppError as exc:
                    await _send_app_error(connection_id, msg_id, exc)
                    continue
                await connection_manager.send_json_to_users(
                    member_ids,
                    _ws_message(
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
                    _ws_message(
                        "message_delete",
                        deleted,
                        msg_id=deleted["message_id"],
                        seq=int(deleted.get("event_seq", 0) or 0),
                    ),
                )
                continue

            await connection_manager.send_json(
                connection_id,
                _ws_message(
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
        await _broadcast_offline_if_needed(disconnected_user_id or user_id, became_offline)


@websocket_router.websocket("/ws")
async def websocket_chat(websocket: WebSocket) -> None:
    await _handle_chat_socket(websocket)







