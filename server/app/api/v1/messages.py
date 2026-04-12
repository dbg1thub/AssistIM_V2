"""Message routes."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.schemas.message import MessageCreate, MessageReadBatch, MessageUpdate
from app.services.message_service import MessageService
from app.utils.response import success_response
from app.websocket.manager import connection_manager
from app.websocket.payloads import read_broadcast_payload, ws_message


router = APIRouter()
logger = logging.getLogger(__name__)



async def _broadcast_message_event(member_ids: list[str], payload: dict) -> None:
    """Best-effort websocket fanout for committed message mutations."""
    try:
        await connection_manager.send_json_to_users(member_ids, payload)
    except Exception:
        logger.exception("Message realtime fanout failed after committed mutation")


@router.get("/messages/unread")
def unread_messages(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(MessageService(db).unread_summary(current_user))


@router.post("/messages/read/batch")
async def read_message_batch(payload: MessageReadBatch, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    service = MessageService(db)
    data = service.batch_read(current_user, payload.session_id, payload.message_id)
    if data.get("advanced"):
        member_ids = service.get_session_member_ids(data["session_id"], current_user.id)
        await _broadcast_message_event(
            member_ids,
            ws_message(
                "read",
                read_broadcast_payload(data),
                msg_id=data.get("message_id", ""),
                seq=int(data.get("event_seq", 0) or 0),
            ),
        )
    return success_response(data)


@router.get("/sessions/{session_id}/messages")
def list_messages(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    before_seq: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(MessageService(db).list_messages(current_user, session_id, limit, before_seq))


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    service = MessageService(db)
    data, created = service.send_message(
        current_user,
        session_id,
        payload.content,
        payload.message_type,
        message_id=str(payload.msg_id),
        extra=payload.extra,
    )
    if created:
        member_ids = service.get_session_member_ids(session_id, current_user.id)
        stored_message = service.messages.get_by_id(data["message_id"])
        for member_id in member_ids:
            if member_id == current_user.id:
                continue
            recipient_payload = data
            if stored_message is not None:
                recipient_payload = service.serialize_message(stored_message, member_id)
            await _broadcast_message_event(
                [member_id],
                ws_message(
                    "chat_message",
                    recipient_payload,
                    msg_id=data["message_id"],
                    seq=int(recipient_payload.get("session_seq", 0) or 0),
                ),
            )
    return success_response(data)


@router.put("/messages/{message_id}")
async def edit_message(
    message_id: str,
    payload: MessageUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    service = MessageService(db)
    data = service.edit(current_user, message_id, payload.content, extra=payload.extra)
    member_ids = service.get_session_member_ids(data["session_id"], current_user.id)
    await _broadcast_message_event(
        member_ids,
        ws_message(
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
    await _broadcast_message_event(
        member_ids,
        ws_message(
            "message_recall",
            data,
            msg_id=data["message_id"],
            seq=int(data.get("event_seq", 0) or 0),
        ),
    )
    return success_response(data)


@router.delete("/messages/{message_id}")
async def delete_message(message_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    service = MessageService(db)
    data = service.delete(current_user, message_id)
    member_ids = service.get_session_member_ids(data["session_id"], current_user.id)
    await _broadcast_message_event(
        member_ids,
        ws_message(
            "message_delete",
            data,
            msg_id=data["message_id"],
            seq=int(data.get("event_seq", 0) or 0),
        ),
    )
    return success_response(data)
