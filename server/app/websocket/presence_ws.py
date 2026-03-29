"""Presence websocket helpers and endpoint."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.dependencies.settings_dependency import get_websocket_settings
from app.websocket.auth import require_websocket_user_id
from app.websocket.payloads import ws_message
from app.websocket.manager import connection_manager


presence_router = APIRouter()


def event_payload(msg_type: str, data: dict, msg_id: str = "") -> dict:
    return ws_message(msg_type, data, msg_id=msg_id, seq=0)


def bind_websocket_user(websocket: WebSocket, connection_id: str) -> str | None:
    token = websocket.query_params.get("token")
    if not token:
        return None
    try:
        user_id = require_websocket_user_id(token, settings=get_websocket_settings(websocket))
    except Exception:
        return None
    connection_manager.bind_user(connection_id, user_id)
    return user_id


async def _broadcast_offline_if_needed(user_id: str | None, became_offline: bool) -> None:
    if user_id and became_offline:
        await connection_manager.broadcast_json(event_payload("offline", {"user_id": user_id}))


@presence_router.websocket("/ws/presence")
async def presence_endpoint(websocket: WebSocket) -> None:
    connection_id = await connection_manager.connect(websocket)
    user_id = bind_websocket_user(websocket, connection_id)
    if user_id is None:
        connection_manager.disconnect_by_connection_id(connection_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await connection_manager.broadcast_json(event_payload("online", {"user_id": user_id}))

    try:
        await connection_manager.send_json(
            connection_id,
            event_payload("presence", {"online_users": connection_manager.online_user_ids()}),
        )
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")
            if msg_type in {"ping", "heartbeat"}:
                await connection_manager.send_json(connection_id, event_payload("pong", {}))
            elif msg_type == "presence_query":
                await connection_manager.send_json(
                    connection_id,
                    event_payload("presence", {"online_users": connection_manager.online_user_ids()}),
                )
    except WebSocketDisconnect:
        pass
    finally:
        disconnected_user_id, became_offline = await connection_manager.disconnect(websocket)
        await _broadcast_offline_if_needed(disconnected_user_id or user_id, became_offline)
