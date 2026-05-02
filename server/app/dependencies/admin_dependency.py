"""Admin authorization dependencies."""

from __future__ import annotations

from fastapi import Depends

from app.core.errors import AppError, ErrorCode
from app.dependencies.auth_dependency import get_current_user
from app.models.user import User


ROLE_USER = "user"
ROLE_ADMIN = "admin"
VALID_USER_ROLES = {ROLE_USER, ROLE_ADMIN}


def normalize_user_role(value: object) -> str:
    role = str(value or ROLE_USER).strip().lower()
    return role or ROLE_USER


def validate_user_role(value: object) -> str:
    role = normalize_user_role(value)
    if role not in VALID_USER_ROLES:
        raise ValueError(f"unsupported admin role: {role}")
    return role


def get_current_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """Resolve the current user and require the admin role."""
    if normalize_user_role(getattr(current_user, "role", ROLE_USER)) != ROLE_ADMIN:
        raise AppError(ErrorCode.FORBIDDEN, "admin privileges required", 403)
    return current_user
