"""Authentication service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    token_session_version,
    verify_password,
)
from app.media.default_avatars import random_default_avatar_url
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.services.user_service import UserService


class AuthService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.users = UserRepository(db)

    def register(self, username: str, password: str, nickname: str) -> dict:
        if self.users.get_by_username(username) is not None:
            raise AppError(ErrorCode.USER_EXISTS, "user already exists", 409)

        user = self.users.create(
            username=username,
            password_hash=hash_password(password),
            nickname=nickname,
            avatar=random_default_avatar_url(self.settings),
        )
        return self._build_auth_payload(user, rotate_session=True)

    def register_user_only(self, username: str, password: str, nickname: str) -> dict:
        if self.users.get_by_username(username) is not None:
            raise AppError(ErrorCode.USER_EXISTS, "user already exists", 409)
        user = self.users.create(
            username=username,
            password_hash=hash_password(password),
            nickname=nickname,
            avatar=random_default_avatar_url(self.settings),
        )
        return {
            "id": user.id,
            "username": user.username,
            "nickname": user.nickname,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }

    def login(self, username: str, password: str) -> dict:
        user = self.authenticate_credentials(username, password)
        return self.login_user(user, rotate_session=True)

    def authenticate_credentials(self, username: str, password: str) -> User:
        user = self.users.get_by_username(username)
        if user is None or not verify_password(password, user.password_hash):
            raise AppError(ErrorCode.INVALID_CREDENTIALS, "invalid credentials", 401)
        return user

    def login_user(self, user: User, *, rotate_session: bool = True) -> dict:
        return self._build_auth_payload(user, rotate_session=rotate_session)

    def refresh(self, refresh_token: str) -> dict:
        payload = decode_refresh_token(refresh_token, settings=self.settings)
        user = self.users.get_by_id(payload["sub"])
        if user is None:
            raise AppError(ErrorCode.USER_NOT_FOUND, "user not found", 404)
        self._ensure_active_session(user, payload)
        return self._build_auth_payload(user, rotate_session=False)

    def refresh_access_token(self, refresh_token: str) -> dict:
        payload = decode_refresh_token(refresh_token, settings=self.settings)
        user = self.users.get_by_id(payload["sub"])
        if user is None:
            raise AppError(ErrorCode.USER_NOT_FOUND, "user not found", 404)
        self._ensure_active_session(user, payload)
        return {
            "access_token": create_access_token(
                user.id,
                user.username,
                session_version=int(user.auth_session_version or 0),
                settings=self.settings,
            ),
            "token_type": "Bearer",
            "expires_in": self.settings.access_token_expire_minutes * 60,
            "refresh_expires_in": self.settings.refresh_token_expire_days * 24 * 60 * 60,
        }

    def logout(self, user: User) -> None:
        self.users.advance_auth_session_version(user)

    def _ensure_active_session(self, user: User, payload: dict) -> None:
        if token_session_version(payload) != int(user.auth_session_version or 0):
            raise AppError(ErrorCode.UNAUTHORIZED, "session expired", 401)

    def _build_auth_payload(self, user: User, *, rotate_session: bool) -> dict:
        if rotate_session:
            user = self.users.advance_auth_session_version(user)

        session_version = int(user.auth_session_version or 0)
        access_token = create_access_token(
            user.id,
            user.username,
            session_version=session_version,
            settings=self.settings,
        )
        refresh_token = create_refresh_token(
            user.id,
            user.username,
            session_version=session_version,
            settings=self.settings,
        )
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": self.settings.access_token_expire_minutes * 60,
            "refresh_expires_in": self.settings.refresh_token_expire_days * 24 * 60 * 60,
            "user": UserService.serialize_user(user),
        }
