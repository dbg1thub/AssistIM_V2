"""Session routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.schemas.session import CreateGroupSessionRequest, CreatePrivateSessionRequest
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


@router.post("")
def create_session(payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(SessionService(db).create_generic(current_user, payload))


@router.post("/private")
def create_private_session(
    payload: CreatePrivateSessionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(
        SessionService(db).create_private(current_user, payload.participant_ids, payload.name)
    )


@router.post("/group")
def create_group_session(
    payload: CreateGroupSessionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(SessionService(db).create_group(current_user, payload.name, payload.participant_ids))


@router.post("/{session_id}/typing")
async def typing_session(session_id: str, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    service = MessageService(db)
    member_ids = service.get_session_member_ids(session_id, current_user.id)
    await connection_manager.send_json_to_users(
        member_ids,
        event_payload(
            event="typing",
            msg_type="typing",
            data={"session_id": session_id, "user_id": current_user.id, "typing": payload.get("typing", True)},
        ),
    )
    return success_response({"typing": payload.get("typing", True)})


@router.get("/{session_id}")
def get_session(session_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(SessionService(db).get_session(current_user, session_id))


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    SessionService(db).delete_session(current_user, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
