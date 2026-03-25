"""Authentication dependencies."""

from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import get_db
from app.core.errors import AppError, ErrorCode
from app.core.security import decode_access_token, token_session_version
from app.dependencies.settings_dependency import get_request_settings
from app.models.user import User
from app.repositories.user_repo import UserRepository


security_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_request_settings),
) -> User:
    """Resolve the current authenticated user."""
    if credentials is None or not credentials.credentials:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="authorization required",
            status_code=401,
        )

    payload = decode_access_token(credentials.credentials, settings=settings)
    user = UserRepository(db).get_by_id(payload["sub"])
    if user is None:
        raise AppError(
            code=ErrorCode.USER_NOT_FOUND,
            message="user not found",
            status_code=404,
        )
    if token_session_version(payload) != int(getattr(user, "auth_session_version", 0) or 0):
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="session expired",
            status_code=401,
        )
    return user
