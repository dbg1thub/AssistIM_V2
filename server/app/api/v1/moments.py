"""Moment routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.schemas.moment import MomentCommentCreate, MomentCreate
from app.services.moment_service import MomentService
from app.utils.response import success_response


router = APIRouter()


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


@router.get("/{moment_id}")
def get_moment(moment_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(MomentService(db).get_moment(current_user, moment_id))


@router.post("")
def create_moment(payload: MomentCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(MomentService(db).create_moment(current_user, payload.content))


@router.post("/{moment_id}/likes")
def like_moment(moment_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(MomentService(db).like(current_user, moment_id))


@router.delete("/{moment_id}/likes")
def unlike_moment(moment_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(MomentService(db).unlike(current_user, moment_id))


@router.post("/{moment_id}/comments")
def comment_moment(
    moment_id: str,
    payload: MomentCommentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(MomentService(db).comment(current_user, moment_id, payload.content))
