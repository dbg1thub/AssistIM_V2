"""Moment routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.schemas.moment import MomentCommentCreate, MomentCreate
from app.services.moment_service import MomentService
from app.utils.response import success_response


router = APIRouter()


@router.get("")
def list_moments(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(MomentService(db).list_moments(current_user))


@router.post("")
def create_moment(payload: MomentCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(MomentService(db).create_moment(current_user, payload.content))


@router.post("/{moment_id}/likes")
def like_moment(moment_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    MomentService(db).like(current_user, moment_id)
    return success_response()


@router.delete("/{moment_id}/likes")
def unlike_moment(moment_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    MomentService(db).unlike(current_user, moment_id)
    return success_response()


@router.post("/{moment_id}/comments")
def comment_moment(
    moment_id: str,
    payload: MomentCommentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(MomentService(db).comment(current_user, moment_id, payload.content))
