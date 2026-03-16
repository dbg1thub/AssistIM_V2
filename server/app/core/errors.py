"""Application error types and codes."""

from __future__ import annotations

from dataclasses import dataclass


class ErrorCode:
    INVALID_CREDENTIALS = 1001
    USER_EXISTS = 1002
    USER_NOT_FOUND = 1003
    UNAUTHORIZED = 1004
    INVALID_REQUEST = 1005
    RESOURCE_NOT_FOUND = 1006
    RATE_LIMITED = 1007
    FORBIDDEN = 1008
    INTERNAL_ERROR = 1500


@dataclass
class AppError(Exception):
    """Structured application exception."""

    code: int
    message: str
    status_code: int = 400
