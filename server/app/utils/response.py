"""Unified API response helpers."""

from __future__ import annotations

from typing import Any


def success_response(data: Any = None, message: str = "success") -> dict[str, Any]:
    """Return a successful API response."""
    return {
        "code": 0,
        "message": message,
        "data": data if data is not None else {},
    }


def error_response(code: int, message: str) -> dict[str, Any]:
    """Return an error API response."""
    return {
        "code": code,
        "message": message,
    }
