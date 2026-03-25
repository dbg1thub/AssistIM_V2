"""Presence websocket helpers and endpoint."""

from __future__ import annotations

import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.database import SessionLocal
from app.core.security import decode_access_token, token_session_version
from app.dependencies.settings_dependency import get_websocket_settings
from app.repositories.user_repo import UserRepository
from app.websocket.manager import connection_manager


presence_router = APIRouter()


def event_payload(event: str, data: dict, msg_type: str | None = None, msg_id: str = "") -> dict:
    payload = {
        "event": event,
        "data": data,
        "timestamp": int(time.time()),
    }
    if msg_type is not None:
        payload.update(
            {
                "type": msg_type,
                "seq": 0,
                "msg_id": msg_id,
            }
        )
    return payload


def bind_websocket_user(websocket: WebSocket, connection_id: str) -> str | None:
    token = websocket.query_params.get("token")
    if not token:
        return None
    try:
        payload = decode_access_token(token, settings=get_websocket_settings(websocket))
    except Exception:
        return None
    user_id = payload["sub"]
    with SessionLocal() as db:
        user = UserRepository(db).get_by_id(user_id)
        if user is None:
            return None
        if token_session_version(payload) != int(getattr(user, "auth_session_version", 0) or 0):
            return None
    connection_manager.bind_user(connection_id, user_id)
    return user_id


async def _broadcast_offline_if_needed(user_id: str | None, became_offline: bool) -> None:
    if user_id and became_offline:
        await connection_manager.broadcast_json(event_payload("offline", {"user_id": user_id}, msg_type="offline"))


@presence_router.websocket("/ws/presence")
async def presence_endpoint(websocket: WebSocket) -> None:
    connection_id = await connection_manager.connect(websocket)
    user_id = bind_websocket_user(websocket, connection_id)
    if user_id is None:
        connection_manager.disconnect_by_connection_id(connection_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await connection_manager.broadcast_json(event_payload("online", {"user_id": user_id}, msg_type="online"))

    try:
        await connection_manager.send_json(
            connection_id,
            event_payload("presence", {"online_users": connection_manager.online_user_ids()}, msg_type="presence"),
        )
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")
            if msg_type in {"ping", "heartbeat"}:
                await connection_manager.send_json(connection_id, event_payload("pong", {}, msg_type="pong"))
            elif msg_type == "presence_query":
                await connection_manager.send_json(
                    connection_id,
                    event_payload("presence", {"online_users": connection_manager.online_user_ids()}, msg_type="presence"),
                )
    except WebSocketDisconnect:
        pass
    finally:
        disconnected_user_id, became_offline = await connection_manager.disconnect(websocket)
        await _broadcast_offline_if_needed(disconnected_user_id or user_id, became_offline)
