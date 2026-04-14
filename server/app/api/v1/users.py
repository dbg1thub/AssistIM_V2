"""User routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.schemas.user import UserUpdateRequest
from app.services.avatar_service import AvatarService
from app.services.user_service import UserService
from app.utils.response import success_response
from app.websocket.manager import connection_manager
from app.websocket.payloads import ws_message


router = APIRouter()
logger = logging.getLogger(__name__)


async def _broadcast_profile_update_events(db: Session, user_id: str) -> None:
    service = UserService(db)
    user = service.users.get_by_id(user_id)
    if user is None:
        return
    result = service.record_profile_update_events(user)
    payload = dict(result.get("payload") or {})
    participant_ids = [
        value
        for value in dict.fromkeys(str(raw_id or "").strip() for raw_id in result.get("participant_ids", []))
        if value
    ]
    if not participant_ids:
        return
    try:
        await connection_manager.send_json_to_users(
            participant_ids,
            ws_message(
                "user_profile_update",
                payload,
                msg_id=str(payload.get("profile_event_id") or f"user-profile:{user_id}"),
            ),
        )
    except Exception:
        logger.exception("User profile fanout failed after committed profile mutation")


@router.get("/search")
def search_users(
    keyword: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(UserService(db).search_users(keyword, page, size))


@router.get("")
def list_users(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(UserService(db).list_users(page=page, size=size))


@router.get("/{user_id}")
def get_user(user_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(UserService(db).get_user(user_id))


@router.put("/me")
async def update_me(
    payload: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    data = UserService(db).update_me(
        current_user,
        **payload.model_dump(exclude_unset=True),
    )
    await _broadcast_profile_update_events(db, current_user.id)
    return success_response(data)


@router.post("/me/avatar")
async def upload_me_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    avatar_service = AvatarService(db)
    updated_user = avatar_service.upload_user_avatar(current_user, file)
    await _broadcast_profile_update_events(db, current_user.id)
    return success_response(UserService(db).serialize_user(updated_user))


@router.delete("/me/avatar")
async def reset_me_avatar(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    avatar_service = AvatarService(db)
    updated_user = avatar_service.reset_user_avatar(current_user)
    await _broadcast_profile_update_events(db, current_user.id)
    return success_response(UserService(db).serialize_user(updated_user))
