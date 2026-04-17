"""Session routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.schemas.session import CreateDirectSessionRequest
from app.services.message_service import MessageService
from app.services.session_service import SessionService
from app.utils.response import success_response
from app.websocket.manager import connection_manager
from app.websocket.payloads import ws_message


router = APIRouter()
logger = logging.getLogger(__name__)


async def _broadcast_session_lifecycle_refresh(user_ids: list[str], payload: dict) -> None:
    recipients = [
        value
        for value in dict.fromkeys(str(raw_id or "").strip() for raw_id in user_ids)
        if value
    ]
    if not recipients:
        return
    await connection_manager.send_json_to_users(
        recipients,
        ws_message(
            "contact_refresh",
            payload,
        ),
    )


@router.get("/unread")
def session_unread(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(MessageService(db).session_unread_counts(current_user))


@router.get("")
def list_sessions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(SessionService(db).list_sessions(current_user))


@router.post("/direct")
async def create_direct_session(
    payload: CreateDirectSessionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    result = SessionService(db).create_private(current_user, payload.participant_ids, payload.encryption_mode)
    participant_ids = [
        value
        for value in dict.fromkeys(str(raw_id or "").strip() for raw_id in result.get("participant_ids", []))
        if value
    ]
    if result.get("created") is True and participant_ids:
        try:
            await _broadcast_session_lifecycle_refresh(
                participant_ids,
                {
                    "reason": "session_lifecycle_changed",
                    "session_id": str(result.get("session_id", "") or result.get("id", "") or ""),
                    "session": dict(result),
                },
            )
        except Exception:
            logger.exception("Session lifecycle fanout failed after committed direct-session mutation")
    return success_response(
        result
    )


@router.get("/{session_id}")
def get_session(session_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(SessionService(db).get_session(current_user, session_id))
