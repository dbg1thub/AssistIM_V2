"""Friend routes."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limit import rate_limiter
from app.dependencies.auth_dependency import get_current_user
from app.dependencies.settings_dependency import get_request_settings
from app.models.user import User
from app.schemas.friend import FriendRequestCreate
from app.services.friend_service import FriendService
from app.utils.response import success_response
from app.websocket.manager import connection_manager


router = APIRouter()
logger = logging.getLogger(__name__)


def _friend_request_limit(request: Request) -> int:
    """Return the current friend-request rate limit for this app snapshot."""
    return get_request_settings(request).rate_limit_friend_request


def _contact_refresh_message(reason: str, payload: dict | None = None) -> dict:
    """Build one lightweight realtime contact-refresh event."""
    data = dict(payload or {})
    data.setdefault("reason", reason)
    return {
        "type": "contact_refresh",
        "seq": 0,
        "msg_id": str(data.get("request_id") or data.get("friend_id") or ""),
        "timestamp": int(time.time()),
        "data": data,
    }


async def _broadcast_contact_refresh(user_ids: list[str], reason: str, payload: dict | None = None) -> None:
    """Broadcast one contact-refresh event to the affected users."""
    deduped_user_ids = [user_id for index, user_id in enumerate(user_ids) if user_id and user_id not in user_ids[:index]]
    if not deduped_user_ids:
        return
    try:
        await connection_manager.send_json_to_users(
            deduped_user_ids,
            _contact_refresh_message(reason, payload),
        )
    except Exception:
        logger.exception("Contact refresh fanout failed after committed friendship mutation")


@router.get("")
def list_friends(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(FriendService(db).list_friends(current_user))


@router.get("/check/{user_id}")
def check_friendship(user_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(FriendService(db).check_relationship(current_user, user_id))


@router.post("/requests", dependencies=[Depends(rate_limiter.dynamic_dependency("friend-request", _friend_request_limit))])
async def send_request(
    payload: FriendRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    target_user_id = payload.target_user_id
    result = FriendService(db).create_request(current_user, target_user_id, payload.message)
    reason = "friendship_created" if result.get("action") == "friendship_created" or result.get("status") == "accepted" else "friend_request_created"
    await _broadcast_contact_refresh([current_user.id, target_user_id], reason, result)
    return success_response(result)


@router.get("/requests")
def list_requests(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(FriendService(db).list_requests(current_user))


@router.post("/requests/{request_id}/accept")
async def accept_request(request_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    result = FriendService(db).accept_request(current_user, request_id)
    await _broadcast_contact_refresh(
        [
            str((result.get("sender") or {}).get("id", "") or ""),
            str((result.get("receiver") or {}).get("id", "") or ""),
        ],
        "friendship_created",
        result,
    )
    return success_response(result)


@router.post("/requests/{request_id}/reject")
async def reject_request(request_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    result = FriendService(db).reject_request(current_user, request_id)
    await _broadcast_contact_refresh(
        [
            str((result.get("sender") or {}).get("id", "") or ""),
            str((result.get("receiver") or {}).get("id", "") or ""),
        ],
        "friend_request_updated",
        result,
    )
    return success_response(result)


@router.delete("/{friend_id}")
async def remove_friend(friend_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    result = FriendService(db).remove_friend(current_user, friend_id)
    if result.get("changed"):
        await _broadcast_contact_refresh(
            [current_user.id, friend_id],
            "friendship_removed",
            result,
        )
    return success_response(result)

