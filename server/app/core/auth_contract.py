"""Canonical auth request normalization and validation helpers."""

from __future__ import annotations

import re
import unicodedata


USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 32
PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 128
NICKNAME_MAX_LENGTH = 64
REFRESH_TOKEN_MIN_LENGTH = 32
REFRESH_TOKEN_MAX_LENGTH = 4096
TOKEN_TYPE_BEARER = "Bearer"
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def canonicalize_username(value: str) -> str:
    """Collapse compatibility-equivalent username forms and trim edges."""
    return unicodedata.normalize("NFKC", value).strip().lower()


def validate_username(value: str) -> str:
    """Validate one canonical username against the public auth contract."""
    if not USERNAME_PATTERN.fullmatch(value):
        raise ValueError("username may contain only letters, numbers, dots, underscores, and hyphens")
    return value


def canonicalize_nickname(value: str) -> str:
    """Trim presentation-only nickname whitespace."""
    return value.strip()


def canonicalize_refresh_token(value: str) -> str:
    """Trim transport padding around one refresh token."""
    return value.strip()

