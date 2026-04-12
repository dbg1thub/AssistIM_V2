"""User Service Module.

HTTP-facing user service that centralizes profile and user lookup requests.
"""

from __future__ import annotations

from typing import Any, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.network.http_client import get_http_client


setup_logging()
logger = logging.get_logger(__name__)


class UserService:
    """Encapsulate user-related HTTP operations."""

    def __init__(self) -> None:
        self._http = get_http_client()

    async def search_users(self, keyword: str, *, page: int = 1, size: int = 20) -> dict[str, Any]:
        """Search users for contact and discovery flows."""
        payload = await self._http.get(
            "/users/search",
            params={
                "keyword": keyword,
                "page": page,
                "size": size,
            },
        )
        if not isinstance(payload, dict):
            logger.warning("Unexpected user search payload: %r", payload)
            return {"items": []}
        return dict(payload)

    async def fetch_user(self, user_id: str) -> dict[str, Any]:
        """Fetch one user profile."""
        payload = await self._http.get(f"/users/{user_id}")
        return dict(payload or {})

    async def update_me(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Update the current user's profile."""
        response = await self._http.put("/users/me", json=payload)
        return dict(response or {})

    async def close(self) -> None:
        """Retire the user service without closing the shared HTTP transport."""
        global _user_service
        if _user_service is self:
            _user_service = None


_user_service: Optional[UserService] = None


def get_user_service() -> UserService:
    """Get the global user service instance."""
    global _user_service
    if _user_service is None:
        _user_service = UserService()
    return _user_service
