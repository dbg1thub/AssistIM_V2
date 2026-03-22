"""Chat websocket endpoints."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.database import SessionLocal
from app.core.errors import AppError
from app.services.message_service import MessageService
from app.websocket.manager import connection_manager
from app.websocket.presence_ws import bind_websocket_user, event_payload


websocket_router = APIRouter()


def _compat_message(msg_type: str, data: dict, msg_id: str | None = None, event: str | None = None) -> dict:
    payload = {
        "type": msg_type,
        "seq": 0,
        "msg_id": msg_id or "",
        "timestamp": int(time.time()),
        "data": data,
    }
    if event:
        payload["event"] = event
    return payload


async def _broadcast_offline_if_needed(user_id: str | None, became_offline: bool) -> None:
    if user_id and became_offline:
        await connection_manager.broadcast_json(event_payload("offline", {"user_id": user_id}, msg_type="offline"))


async def _handle_chat_socket(websocket: WebSocket) -> None:
    connection_id = await connection_manager.connect(websocket)
    user_id = bind_websocket_user(websocket, connection_id)
    await connection_manager.broadcast_json(event_payload("online", {"user_id": user_id}, msg_type="online"))

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")
            msg_id = message.get("msg_id") or str(uuid.uuid4())
            data = message.get("data", {}) if isinstance(message.get("data"), dict) else {}

            if msg_type == "auth":
                auth_token = data.get("token")
                if auth_token:
                    from app.core.security import decode_access_token
                    payload = decode_access_token(auth_token)
                    user_id = payload["sub"]
                    connection_manager.bind_user(connection_id, user_id)
                elif data.get("user_id"):
                    user_id = data["user_id"]
                    connection_manager.bind_user(connection_id, user_id)
                await connection_manager.send_json(
                    connection_id,
                    _compat_message("auth_ack", {"success": True, "user_id": user_id}, event="auth"),
                )
                continue

            if msg_type in {"heartbeat", "ping"}:
                await connection_manager.send_json(connection_id, event_payload("pong", {}, msg_type="pong"))
                continue

            if msg_type == "sync_messages":
                last_timestamp = float(data.get("last_timestamp", 0) or 0)
                with SessionLocal() as db:
                    service = MessageService(db)
                    messages = service.sync_since_timestamp(last_timestamp, user_id)
                await connection_manager.send_json(
                    connection_id,
                    _compat_message("history_messages", {"messages": messages}, event="history"),
                )
                continue

            if msg_type in {"chat_message", "message"}:
                session_id = data.get("session_id") or message.get("session_id", "")
                content = data.get("content") or message.get("content", "")
                message_type = data.get("message_type") or message.get("message_type") or data.get("type") or "text"
                with SessionLocal() as db:
                    service = MessageService(db)
                    try:
                        member_ids = service.get_session_member_ids(session_id, user_id)
                        saved = service.send_ws_message(
                            sender_id=user_id,
                            session_id=session_id,
                            content=content,
                            message_type=message_type,
                            message_id=msg_id,
                        )
                    except AppError as exc:
                        await connection_manager.send_json(
                            connection_id,
                            _compat_message("error", {"message": exc.message}, msg_id=msg_id, event="error"),
                        )
                        continue

                recipient_ids = [member_id for member_id in member_ids if member_id != user_id]
                await connection_manager.send_json(
                    connection_id,
                    _compat_message("message_ack", {"msg_id": msg_id, "success": True}, msg_id=msg_id, event="ack"),
                )
                payload = _compat_message(
                    "chat_message",
                    {
                        "session_id": session_id,
                        "sender_id": user_id,
                        "content": content,
                        "message_type": message_type,
                        "extra": data.get("extra", {}),
                    },
                    msg_id=saved["msg_id"],
                    event="message",
                )
                payload["data"]["id"] = saved["id"]
                delivered_user_ids = await connection_manager.send_json_to_users(
                    recipient_ids,
                    payload,
                    exclude_connection_id=connection_id,
                )
                if delivered_user_ids:
                    await connection_manager.send_json_to_users(
                        [user_id],
                        _compat_message(
                            "message_delivered",
                            {
                                "session_id": session_id,
                                "msg_id": saved["msg_id"],
                                "user_ids": sorted(delivered_user_ids),
                            },
                            msg_id=saved["msg_id"],
                            event="delivered",
                        ),
                    )
                continue

            if msg_type == "typing":
                session_id = data.get("session_id") or message.get("session_id", "")
                with SessionLocal() as db:
                    member_ids = MessageService(db).get_session_member_ids(session_id, user_id)
                await connection_manager.send_json_to_users(
                    member_ids,
                    event_payload("typing", {"session_id": session_id, "user_id": user_id}, msg_type="typing"),
                    exclude_connection_id=connection_id,
                )
                continue

            if msg_type in {"read_ack", "read"}:
                session_id = data.get("session_id") or message.get("session_id", "")
                message_id = data.get("message_id") or message.get("message_id", "")
                with SessionLocal() as db:
                    member_ids = MessageService(db).get_session_member_ids(session_id, user_id)
                await connection_manager.send_json_to_users(
                    member_ids,
                    event_payload(
                        "read",
                        {"session_id": session_id, "message_id": message_id, "user_id": user_id},
                        msg_type="read",
                    ),
                    exclude_connection_id=connection_id,
                )
                continue

            if msg_type == "message_recall":
                session_id = data.get("session_id", "")
                with SessionLocal() as db:
                    member_ids = MessageService(db).get_session_member_ids(session_id, user_id)
                await connection_manager.send_json_to_users(
                    member_ids,
                    _compat_message(
                        "message_recall",
                        {"session_id": session_id, "msg_id": data.get("msg_id", ""), "user_id": user_id},
                        event="recall",
                    ),
                )
                continue

            if msg_type == "message_edit":
                session_id = data.get("session_id", "")
                with SessionLocal() as db:
                    member_ids = MessageService(db).get_session_member_ids(session_id, user_id)
                await connection_manager.send_json_to_users(
                    member_ids,
                    _compat_message(
                        "message_edit",
                        {
                            "session_id": session_id,
                            "msg_id": data.get("msg_id", ""),
                            "user_id": user_id,
                            "content": data.get("content", ""),
                        },
                        event="edit",
                    ),
                )
                continue

            if msg_type == "message_delete":
                session_id = data.get("session_id", "")
                with SessionLocal() as db:
                    member_ids = MessageService(db).get_session_member_ids(session_id, user_id)
                await connection_manager.send_json_to_users(
                    member_ids,
                    _compat_message(
                        "message_delete",
                        {
                            "session_id": session_id,
                            "msg_id": data.get("msg_id", ""),
                            "user_id": user_id,
                        },
                        event="delete",
                    ),
                )
                continue

            await connection_manager.send_json(
                connection_id,
                _compat_message("error", {"message": f"unsupported message type: {msg_type}"}, msg_id=msg_id, event="error"),
            )

    except WebSocketDisconnect:
        pass
    finally:
        disconnected_user_id, became_offline = await connection_manager.disconnect(websocket)
        await _broadcast_offline_if_needed(disconnected_user_id or user_id, became_offline)


@websocket_router.websocket("/ws")
async def websocket_compat(websocket: WebSocket) -> None:
    await _handle_chat_socket(websocket)


@websocket_router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    await _handle_chat_socket(websocket)
