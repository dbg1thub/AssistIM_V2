"""Shared websocket authentication helpers."""

from __future__ import annotations

from app.core.config import Settings
from app.core.database import SessionLocal
from app.core.errors import AppError, ErrorCode
from app.core.security import decode_access_token, token_session_version
from app.repositories.user_repo import UserRepository


def require_websocket_user_id(token: str | None, *, settings: Settings) -> str:
    """Validate one websocket access token and return the bound user id."""
    if not token:
        raise AppError(ErrorCode.UNAUTHORIZED, "websocket authentication token required", 401)

    payload = decode_access_token(token, settings=settings)
    user_id = str(payload.get("sub") or "").strip()
    if not user_id:
        raise AppError(ErrorCode.UNAUTHORIZED, "invalid access token", 401)

    with SessionLocal() as db:
        user = UserRepository(db).get_by_id(user_id)
        if user is None:
            raise AppError(ErrorCode.UNAUTHORIZED, "user not found for websocket connection", 401)
        if token_session_version(payload) != int(getattr(user, "auth_session_version", 0) or 0):
            raise AppError(ErrorCode.UNAUTHORIZED, "session expired", 401)

    return user_id
