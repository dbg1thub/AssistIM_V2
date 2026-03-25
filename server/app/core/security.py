"""Authentication helpers."""

from __future__ import annotations

from datetime import timedelta

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode
from app.utils.jwt import decode_token, encode_token
from app.utils.password import hash_password, verify_password


ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def _resolve_settings(settings: Settings | None = None) -> Settings:
    """Return one explicit settings snapshot or fall back to the cached runtime settings."""
    return settings or get_settings()


def create_access_token(
    user_id: str,
    username: str,
    *,
    session_version: int = 0,
    settings: Settings | None = None,
) -> str:
    """Create an access token."""
    current_settings = _resolve_settings(settings)
    return encode_token(
        payload={
            "sub": user_id,
            "username": username,
            "type": ACCESS_TOKEN_TYPE,
            "session_version": int(session_version or 0),
        },
        secret_key=current_settings.secret_key,
        expires_delta=timedelta(minutes=current_settings.access_token_expire_minutes),
    )



def create_refresh_token(
    user_id: str,
    username: str,
    *,
    session_version: int = 0,
    settings: Settings | None = None,
) -> str:
    """Create a refresh token."""
    current_settings = _resolve_settings(settings)
    return encode_token(
        payload={
            "sub": user_id,
            "username": username,
            "type": REFRESH_TOKEN_TYPE,
            "session_version": int(session_version or 0),
        },
        secret_key=current_settings.secret_key,
        expires_delta=timedelta(days=current_settings.refresh_token_expire_days),
    )



def decode_access_token(token: str, *, settings: Settings | None = None) -> dict:
    """Decode and validate an access token."""
    current_settings = _resolve_settings(settings)
    payload = decode_token(token, current_settings.secret_key)
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="invalid access token",
            status_code=401,
        )
    return payload



def decode_refresh_token(token: str, *, settings: Settings | None = None) -> dict:
    """Decode and validate a refresh token."""
    current_settings = _resolve_settings(settings)
    payload = decode_token(token, current_settings.secret_key)
    if payload.get("type") != REFRESH_TOKEN_TYPE:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="invalid refresh token",
            status_code=401,
        )
    return payload



def token_session_version(payload: dict) -> int:
    """Return the auth session version embedded in a JWT payload."""
    try:
        return max(0, int(payload.get("session_version", 0) or 0))
    except (TypeError, ValueError):
        return 0


__all__ = [
    "create_access_token",
    "create_refresh_token",
    "decode_access_token",
    "decode_refresh_token",
    "hash_password",
    "token_session_version",
    "verify_password",
]
