"""Friend routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.rate_limit import rate_limiter
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.schemas.friend import FriendRequestCreate
from app.services.friend_service import FriendService
from app.utils.response import success_response


router = APIRouter()
settings = get_settings()


@router.get("")
def list_friends(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(FriendService(db).list_friends(current_user))


@router.get("/check/{user_id}")
def check_friendship(user_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(FriendService(db).check_relationship(current_user, user_id))


@router.post("/requests", dependencies=[Depends(rate_limiter.dependency("friend-request", settings.rate_limit_friend_request))])
def send_request(
    payload: FriendRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    receiver_id = payload.receiver_id or payload.user_id
    return success_response(FriendService(db).create_request(current_user, receiver_id, payload.message))


@router.get("/requests")
def list_requests(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(FriendService(db).list_requests(current_user))


@router.post("/requests/{request_id}/accept")
def accept_request(request_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(FriendService(db).accept_request(current_user, request_id))


@router.post("/requests/{request_id}/reject")
def reject_request(request_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(FriendService(db).reject_request(current_user, request_id))


@router.delete("/{friend_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_friend(friend_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    FriendService(db).remove_friend(current_user, friend_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
