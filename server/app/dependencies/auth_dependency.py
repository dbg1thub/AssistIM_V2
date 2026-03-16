"""Authentication dependencies."""

from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError, ErrorCode
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.user_repo import UserRepository


security_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the current authenticated user."""
    if credentials is None or not credentials.credentials:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="authorization required",
            status_code=401,
        )

    payload = decode_access_token(credentials.credentials)
    user = UserRepository(db).get_by_id(payload["sub"])
    if user is None:
        raise AppError(
            code=ErrorCode.USER_NOT_FOUND,
            message="user not found",
            status_code=404,
        )
    return user
