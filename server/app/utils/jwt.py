"""Minimal HS256 JWT implementation without external crypto helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import timedelta

from app.core.errors import AppError, ErrorCode


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def encode_token(payload: dict, secret_key: str, expires_delta: timedelta) -> str:
    """Encode a signed JWT string."""
    header = {"alg": "HS256", "typ": "JWT"}
    issued_at = int(time.time())
    body = {
        **payload,
        "iat": issued_at,
        "exp": issued_at + int(expires_delta.total_seconds()),
    }

    header_part = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_part = _b64url_encode(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_part}.{payload_part}".encode("ascii")
    signature = hmac.new(
        secret_key.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    signature_part = _b64url_encode(signature)
    return f"{header_part}.{payload_part}.{signature_part}"


def decode_token(token: str, secret_key: str) -> dict:
    """Decode and validate a signed JWT string."""
    try:
        header_part, payload_part, signature_part = token.split(".")
    except ValueError as exc:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="invalid token format",
            status_code=401,
        ) from exc

    signing_input = f"{header_part}.{payload_part}".encode("ascii")
    expected_signature = hmac.new(
        secret_key.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    provided_signature = _b64url_decode(signature_part)

    if not hmac.compare_digest(expected_signature, provided_signature):
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="invalid token signature",
            status_code=401,
        )

    try:
        payload = json.loads(_b64url_decode(payload_part).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="invalid token payload",
            status_code=401,
        ) from exc

    if payload.get("exp", 0) < int(time.time()):
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="token expired",
            status_code=401,
        )

    return payload
