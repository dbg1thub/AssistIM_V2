"""User routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User
from app.schemas.user import UserUpdateRequest
from app.services.avatar_service import AvatarService
from app.services.user_service import UserService
from app.utils.response import success_response


router = APIRouter()


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
def list_users(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(UserService(db).list_users())


@router.get("/{user_id}")
def get_user(user_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return success_response(UserService(db).get_user(user_id))


@router.put("/me")
def update_me(
    payload: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return success_response(
        UserService(db).update_me(
            current_user,
            **payload.model_dump(exclude_unset=True),
        )
    )


@router.post("/me/avatar")
def upload_me_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    avatar_service = AvatarService(db)
    updated_user = avatar_service.upload_user_avatar(current_user, file)
    return success_response(UserService.serialize_user(updated_user))


@router.delete("/me/avatar")
def reset_me_avatar(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    avatar_service = AvatarService(db)
    updated_user = avatar_service.reset_user_avatar(current_user)
    return success_response(UserService.serialize_user(updated_user))
