"""User service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.user_repo import UserRepository


class UserService:
    def __init__(self, db: Session) -> None:
        self.users = UserRepository(db)

    def list_users(self) -> list[dict]:
        return [self.serialize_user(user) for user in self.users.list_users()]

    def get_user(self, user_id: str) -> dict:
        user = self.users.get_by_id(user_id)
        if user is None:
            raise AppError(ErrorCode.USER_NOT_FOUND, "user not found", 404)
        return self.serialize_user(user)

    def search_users(self, keyword: str, page: int = 1, size: int = 20) -> dict:
        total, users = self.users.search_users(keyword, page, size)
        return {
            "total": total,
            "page": page,
            "size": size,
            "items": [self.serialize_user(user) for user in users],
        }

    def update_me(self, current_user: User, **fields: object) -> dict:
        user = self.users.update(current_user, **fields)
        return self.serialize_user(user)

    @staticmethod
    def serialize_user(user: User) -> dict:
        return {
            "id": user.id,
            "username": user.username,
            "nickname": user.nickname,
            "avatar": user.avatar,
            "status": user.status,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        }
