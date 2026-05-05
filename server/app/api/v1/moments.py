"""Moment routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.schemas.moment import MomentCommentCreate, MomentCreate, MomentPrivacySettingsUpdate
from app.services.moment_service import MomentService
from app.utils.response import success_response
from app.websocket.manager import connection_manager
from app.websocket.payloads import ws_message


router = APIRouter()
logger = logging.getLogger(__name__)


def _moment_refresh_message(
    *,
    action: str,
    moment_id: str,
    actor_user_id: str,
    owner_user_id: str,
    changed: bool,
) -> dict:
    """Build one lightweight realtime moment-refresh event."""
    normalized_action = str(action or "").strip()
    normalized_moment_id = str(moment_id or "").strip()
    return ws_message(
        "moment_refresh",
        {
            "reason": normalized_action,
            "action": normalized_action,
            "moment_id": normalized_moment_id,
            "actor_user_id": str(actor_user_id or "").strip(),
            "owner_user_id": str(owner_user_id or "").strip(),
            "changed": bool(changed),
        },
        msg_id=f"moment:{normalized_action}:{normalized_moment_id}",
    )


def _moment_owner_user_id(service: MomentService, moment_id: str) -> str:
    """Return the author of a moment after the mutation has been committed."""
    moment = service.moments.get_by_id(moment_id)
    return str(getattr(moment, "user_id", "") or "") if moment is not None else ""


async def _broadcast_moment_refresh(
    *,
    action: str,
    moment_id: str,
    actor_user_id: str,
    owner_user_id: str,
    changed: bool = True,
) -> None:
    """Broadcast a moment refresh hint to currently online clients."""
    if not changed:
        return
    recipient_ids = [
        value
        for value in dict.fromkeys(str(raw_id or "").strip() for raw_id in connection_manager.online_user_ids())
        if value
    ]
    if not recipient_ids:
        return
    try:
        await connection_manager.send_json_to_users(
            recipient_ids,
            _moment_refresh_message(
                action=action,
                moment_id=moment_id,
                actor_user_id=actor_user_id,
                owner_user_id=owner_user_id,
                changed=changed,
            ),
        )
    except Exception:
        logger.exception("Moment refresh fanout failed after committed moment mutation")


@router.get("")
def list_moments(
    user_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(
        MomentService(db).list_moments(
            current_user,
            user_id=user_id,
            page=page,
            size=size,
        )
    )


@router.get("/privacy")
def get_moment_privacy_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(MomentService(db).get_privacy_settings(current_user))


@router.patch("/privacy")
async def update_moment_privacy_settings(
    payload: MomentPrivacySettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    service = MomentService(db)
    result = service.update_privacy_settings(
        current_user,
        hide_my_moments_user_ids=payload.hide_my_moments_user_ids,
        hide_their_moments_user_ids=payload.hide_their_moments_user_ids,
        visible_time_scope=payload.visible_time_scope,
    )
    await _broadcast_moment_refresh(
        action="moment_privacy_updated",
        moment_id="",
        actor_user_id=current_user.id,
        owner_user_id=current_user.id,
        changed=True,
    )
    return success_response(result)


@router.get("/{moment_id}")
def get_moment(moment_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(MomentService(db).get_moment(current_user, moment_id))


@router.post("")
async def create_moment(payload: MomentCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    service = MomentService(db)
    result = service.create_moment(
        current_user,
        payload.content,
        payload.media,
        visibility_scope=payload.visibility_scope,
        visibility_user_ids=payload.visibility_user_ids,
    )
    await _broadcast_moment_refresh(
        action="moment_created",
        moment_id=str(result.get("id", "") or ""),
        actor_user_id=current_user.id,
        owner_user_id=str(result.get("user_id", "") or current_user.id),
        changed=True,
    )
    return success_response(result)


@router.post("/{moment_id}/likes")
async def like_moment(moment_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    service = MomentService(db)
    result = service.like(current_user, moment_id)
    await _broadcast_moment_refresh(
        action="moment_liked",
        moment_id=moment_id,
        actor_user_id=current_user.id,
        owner_user_id=_moment_owner_user_id(service, moment_id),
        changed=bool(result.get("changed")),
    )
    return success_response(result)


@router.delete("/{moment_id}/likes")
async def unlike_moment(moment_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    service = MomentService(db)
    result = service.unlike(current_user, moment_id)
    await _broadcast_moment_refresh(
        action="moment_unliked",
        moment_id=moment_id,
        actor_user_id=current_user.id,
        owner_user_id=_moment_owner_user_id(service, moment_id),
        changed=bool(result.get("changed")),
    )
    return success_response(result)


@router.post("/{moment_id}/comments")
async def comment_moment(
    moment_id: str,
    payload: MomentCommentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    service = MomentService(db)
    result = service.comment(current_user, moment_id, payload.content, payload.image)
    await _broadcast_moment_refresh(
        action="moment_commented",
        moment_id=moment_id,
        actor_user_id=current_user.id,
        owner_user_id=_moment_owner_user_id(service, moment_id),
        changed=True,
    )
    return success_response(result)
