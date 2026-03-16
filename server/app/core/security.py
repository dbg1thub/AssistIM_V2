"""Authentication helpers."""

from __future__ import annotations

from datetime import timedelta

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.utils.jwt import decode_token, encode_token
from app.utils.password import hash_password, verify_password


ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def create_access_token(user_id: str, username: str) -> str:
    """Create an access token."""
    settings = get_settings()
    return encode_token(
        payload={
            "sub": user_id,
            "username": username,
            "type": ACCESS_TOKEN_TYPE,
        },
        secret_key=settings.secret_key,
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(user_id: str, username: str) -> str:
    """Create a refresh token."""
    settings = get_settings()
    return encode_token(
        payload={
            "sub": user_id,
            "username": username,
            "type": REFRESH_TOKEN_TYPE,
        },
        secret_key=settings.secret_key,
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
    )


def decode_access_token(token: str) -> dict:
    """Decode and validate an access token."""
    settings = get_settings()
    payload = decode_token(token, settings.secret_key)
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="invalid access token",
            status_code=401,
        )
    return payload


def decode_refresh_token(token: str) -> dict:
    """Decode and validate a refresh token."""
    settings = get_settings()
    payload = decode_token(token, settings.secret_key)
    if payload.get("type") != REFRESH_TOKEN_TYPE:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="invalid refresh token",
            status_code=401,
        )
    return payload


__all__ = [
    "create_access_token",
    "create_refresh_token",
    "decode_access_token",
    "decode_refresh_token",
    "hash_password",
    "verify_password",
]
