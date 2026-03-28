"""Message routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.schemas.message import MessageCreate, MessageReadBatch, MessageUpdate
from app.services.message_service import MessageService
from app.utils.response import success_response
from app.utils.time import ensure_utc, utcnow
from app.websocket.manager import connection_manager


router = APIRouter()


def _parse_before(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return ensure_utc(datetime.fromisoformat(value))
    except ValueError:
        return datetime.fromtimestamp(float(value), tz=UTC)


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
        "timestamp": int(utcnow().timestamp()),
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


@router.get("/messages/unread")
def unread_messages(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(MessageService(db).unread_summary(current_user))


@router.post("/messages/read/batch")
async def read_message_batch(payload: MessageReadBatch, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    service = MessageService(db)
    data = service.batch_read(current_user, payload.session_id, payload.message_id)
    if data.get("advanced"):
        member_ids = service.get_session_member_ids(data["session_id"], current_user.id)
        await connection_manager.send_json_to_users(
            member_ids,
            _ws_message(
                "read",
                _read_broadcast_payload(data),
                msg_id=data.get("message_id", ""),
                seq=int(data.get("event_seq", 0) or 0),
            ),
        )
    return success_response(data)


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
            payload.message_type,
            extra=payload.extra,
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
        _ws_message(
            "message_edit",
            data,
            msg_id=data["message_id"],
            seq=int(data.get("event_seq", 0) or 0),
        ),
    )
    return success_response(data)


@router.post("/messages/{message_id}/recall")
async def recall_message(message_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    service = MessageService(db)
    data = service.recall(current_user, message_id)
    member_ids = service.get_session_member_ids(data["session_id"], current_user.id)
    await connection_manager.send_json_to_users(
        member_ids,
        _ws_message(
            "message_recall",
            data,
            msg_id=data["message_id"],
            seq=int(data.get("event_seq", 0) or 0),
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
        _ws_message(
            "message_delete",
            data,
            msg_id=data["message_id"],
            seq=int(data.get("event_seq", 0) or 0),
        ),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

