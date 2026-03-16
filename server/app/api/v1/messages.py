"""Message routes, including client compatibility endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError, ErrorCode
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.schemas.message import MessageCreate, MessageUpdate
from app.services.message_service import MessageService
from app.utils.response import success_response
from app.websocket.manager import connection_manager


router = APIRouter()
legacy_router = APIRouter(prefix="/api/chat", tags=["chat-legacy"])


def _parse_before(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.fromtimestamp(float(value))


def _compat_message(msg_type: str, data: dict, msg_id: str | None = None, event: str | None = None) -> dict:
    payload = {
        "type": msg_type,
        "seq": 0,
        "msg_id": msg_id or "",
        "timestamp": int(datetime.now().timestamp()),
        "data": data,
    }
    if event:
        payload["event"] = event
    return payload


@router.get("/messages/history")
def history(
    session_id: str,
    before_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(MessageService(db).list_messages(current_user, session_id, limit, before_id=before_id))


@router.post("/messages")
def create_message(payload: MessageCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if not payload.session_id:
        raise AppError(ErrorCode.INVALID_REQUEST, "session_id is required", 422)
    return success_response(MessageService(db).send_message(current_user, payload.session_id, payload.content, payload.type))


@router.post("/messages/read")
def read_message(payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(MessageService(db).mark_read(current_user, payload.get("message_id", "")))


@router.post("/messages/read/batch")
def read_message_batch(payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(MessageService(db).batch_read(current_user, payload.get("session_id", ""), payload.get("last_read_id", "")))


@router.get("/messages/unread")
def unread_messages(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(MessageService(db).unread_summary(current_user))


@router.get("/sessions/{session_id}/messages")
def list_messages(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    before: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(MessageService(db).list_messages(current_user, session_id, limit, _parse_before(before)))


@router.post("/sessions/{session_id}/messages")
def send_message(
    session_id: str,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(
        MessageService(db).send_message(
            current_user,
            session_id,
            payload.content,
            payload.type,
        )
    )


@router.put("/messages/{message_id}")
async def edit_message(
    message_id: str,
    payload: MessageUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    service = MessageService(db)
    data = service.edit(current_user, message_id, payload.content)
    member_ids = service.get_session_member_ids(data["session_id"], current_user.id)
    await connection_manager.send_json_to_users(
        member_ids,
        _compat_message(
            "message_edit",
            {
                "session_id": data["session_id"],
                "msg_id": data["msg_id"],
                "user_id": current_user.id,
                "content": data["content"],
            },
            msg_id=data["msg_id"],
            event="edit",
        ),
    )
    return success_response(data)


@router.post("/messages/{message_id}/read")
def mark_read(message_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(MessageService(db).mark_read(current_user, message_id))


@router.post("/messages/{message_id}/recall")
async def recall_message(message_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    service = MessageService(db)
    data = service.recall(current_user, message_id)
    member_ids = service.get_session_member_ids(data["session_id"], current_user.id)
    await connection_manager.send_json_to_users(
        member_ids,
        _compat_message(
            "message_recall",
            {
                "session_id": data["session_id"],
                "msg_id": data["msg_id"],
                "user_id": current_user.id,
            },
            msg_id=data["msg_id"],
            event="recall",
        ),
    )
    return success_response(data)


@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(message_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    service = MessageService(db)
    data = service.delete(current_user, message_id)
    member_ids = service.get_session_member_ids(data["session_id"], current_user.id)
    await connection_manager.send_json_to_users(
        member_ids,
        _compat_message(
            "message_delete",
            {
                "session_id": data["session_id"],
                "msg_id": data["msg_id"],
                "user_id": current_user.id,
            },
            msg_id=data["msg_id"],
            event="delete",
        ),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@legacy_router.post("/send")
def legacy_send_message(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    session_id = payload.get("session_id", "")
    content = payload.get("content", "")
    message_type = payload.get("message_type", "text")
    msg_id = payload.get("msg_id")
    data = MessageService(db).send_message(current_user, session_id, content, message_type, msg_id)
    return success_response(data)


@legacy_router.get("/history")
def legacy_history(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    before: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response({"messages": MessageService(db).list_messages(current_user, session_id, limit, _parse_before(before))})


@legacy_router.post("/sync")
def legacy_sync(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    session_id = payload.get("session_id", "")
    data = MessageService(db).list_messages(current_user, session_id, 100, None)
    return success_response({"messages": data})


@legacy_router.delete("/message/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def legacy_delete(
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    MessageService(db).delete(current_user, message_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@legacy_router.post("/read")
def legacy_read(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    message_id = payload.get("message_id", "")
    data = MessageService(db).mark_read(current_user, message_id)
    return success_response(data)
