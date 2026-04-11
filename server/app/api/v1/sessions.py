"""Session routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.schemas.session import CreateDirectSessionRequest, SessionTypingRequest
from app.services.message_service import MessageService
from app.services.session_service import SessionService
from app.utils.response import success_response
from app.websocket.manager import connection_manager
from app.websocket.presence_ws import event_payload


router = APIRouter()


@router.get("/unread")
def session_unread(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(MessageService(db).session_unread_counts(current_user))


@router.get("")
def list_sessions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(SessionService(db).list_sessions(current_user))


@router.post("/direct")
def create_direct_session(
    payload: CreateDirectSessionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(
        SessionService(db).create_private(current_user, payload.participant_ids, payload.encryption_mode)
    )


@router.post("/{session_id}/typing")
async def typing_session(
    session_id: str,
    payload: SessionTypingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    SessionService(db).get_session(current_user, session_id)
    service = MessageService(db)
    member_ids = [
        member_id
        for member_id in service.get_session_member_ids(session_id, current_user.id)
        if member_id != current_user.id
    ]
    typing_event = event_payload(
        "typing",
        {"session_id": session_id, "user_id": current_user.id, "typing": payload.typing},
    )
    await connection_manager.send_json_to_users(
        member_ids,
        typing_event,
    )
    return success_response(typing_event)


@router.get("/{session_id}")
def get_session(session_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(SessionService(db).get_session(current_user, session_id))


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    SessionService(db).delete_session(current_user, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
