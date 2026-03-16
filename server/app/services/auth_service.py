"""Authentication service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.repositories.user_repo import UserRepository


class AuthService:
    def __init__(self, db: Session) -> None:
        self.users = UserRepository(db)

    def register(self, username: str, password: str, nickname: str) -> dict:
        if self.users.get_by_username(username) is not None:
            raise AppError(ErrorCode.USER_EXISTS, "user already exists", 409)

        user = self.users.create(
            username=username,
            password_hash=hash_password(password),
            nickname=nickname,
        )
        return self._build_auth_payload(user)

    def register_user_only(self, username: str, password: str, nickname: str) -> dict:
        if self.users.get_by_username(username) is not None:
            raise AppError(ErrorCode.USER_EXISTS, "user already exists", 409)
        user = self.users.create(
            username=username,
            password_hash=hash_password(password),
            nickname=nickname,
        )
        return {
            "id": user.id,
            "username": user.username,
            "nickname": user.nickname,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }

    def login(self, username: str, password: str) -> dict:
        user = self.users.get_by_username(username)
        if user is None or not verify_password(password, user.password_hash):
            raise AppError(ErrorCode.INVALID_CREDENTIALS, "invalid credentials", 401)
        return self._build_auth_payload(user)

    def refresh(self, refresh_token: str) -> dict:
        payload = decode_refresh_token(refresh_token)
        user = self.users.get_by_id(payload["sub"])
        if user is None:
            raise AppError(ErrorCode.USER_NOT_FOUND, "user not found", 404)
        return self._build_auth_payload(user)

    def refresh_access_token(self, refresh_token: str) -> dict:
        payload = decode_refresh_token(refresh_token)
        user = self.users.get_by_id(payload["sub"])
        if user is None:
            raise AppError(ErrorCode.USER_NOT_FOUND, "user not found", 404)
        return {
            "access_token": create_access_token(user.id, user.username),
            "token_type": "Bearer",
            "expires_in": 60 * 60,
        }

    def _build_auth_payload(self, user: User) -> dict:
        access_token = create_access_token(user.id, user.username)
        refresh_token = create_refresh_token(user.id, user.username)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": 60 * 60,
            "user": {
                "id": user.id,
                "username": user.username,
                "nickname": user.nickname,
                "avatar": user.avatar,
                "status": user.status,
            },
        }
