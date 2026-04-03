"""Contact Service Module.

HTTP-facing contact service that centralizes friend and group requests.
"""

from __future__ import annotations

from typing import Any, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.network.http_client import get_http_client


setup_logging()
logger = logging.get_logger(__name__)


class ContactService:
    """Encapsulate contact-related HTTP operations."""

    def __init__(self) -> None:
        self._http = get_http_client()

    async def fetch_friends(self) -> list[dict[str, Any]]:
        """Fetch the current user's friends."""
        payload = await self._http.get("/friends")
        if not isinstance(payload, list):
            logger.warning("Unexpected friends payload: %r", payload)
            return []
        return [dict(item) for item in payload if isinstance(item, dict)]

    async def fetch_groups(self) -> list[dict[str, Any]]:
        """Fetch the current user's groups."""
        payload = await self._http.get("/groups")
        if not isinstance(payload, list):
            logger.warning("Unexpected groups payload: %r", payload)
            return []
        return [dict(item) for item in payload if isinstance(item, dict)]

    async def fetch_friend_requests(self) -> list[dict[str, Any]]:
        """Fetch the current user's friend requests."""
        payload = await self._http.get("/friends/requests")
        if not isinstance(payload, list):
            logger.warning("Unexpected friend requests payload: %r", payload)
            return []
        return [dict(item) for item in payload if isinstance(item, dict)]

    async def send_friend_request(self, user_id: str, message: str = "") -> dict[str, Any]:
        """Create one friend request."""
        payload = await self._http.post(
            "/friends/requests",
            json={
                "receiver_id": user_id,
                "message": message,
            },
        )
        return dict(payload or {})

    async def create_group(self, name: str, member_ids: list[str]) -> dict[str, Any]:
        """Create one group."""
        payload = await self._http.post(
            "/groups",
            json={
                "name": name,
                "member_ids": member_ids,
            },
        )
        return dict(payload or {})

    async def update_group_profile(self, group_id: str, *, name: str | None = None, announcement: str | None = None) -> dict[str, Any]:
        """Update shared group metadata."""
        payload = await self._http.patch(
            f"/groups/{group_id}",
            json={
                "name": name,
                "announcement": announcement,
            },
        )
        return dict(payload or {})

    async def update_my_group_profile(
        self,
        group_id: str,
        *,
        note: str | None = None,
        my_group_nickname: str | None = None,
    ) -> dict[str, Any]:
        """Update the current user's group-scoped metadata."""
        payload = await self._http.patch(
            f"/groups/{group_id}/me",
            json={
                "note": note,
                "my_group_nickname": my_group_nickname,
            },
        )
        return dict(payload or {})

    async def accept_friend_request(self, request_id: str) -> dict[str, Any]:
        """Accept one pending friend request."""
        payload = await self._http.post(f"/friends/requests/{request_id}/accept", json={})
        return dict(payload or {})

    async def reject_friend_request(self, request_id: str) -> dict[str, Any]:
        """Reject one pending friend request."""
        payload = await self._http.post(f"/friends/requests/{request_id}/reject", json={})
        return dict(payload or {})

    async def remove_friend(self, friend_id: str) -> None:
        """Remove one existing friend."""
        await self._http.delete(f"/friends/{friend_id}")


_contact_service: Optional[ContactService] = None


def get_contact_service() -> ContactService:
    """Get the global contact service instance."""
    global _contact_service
    if _contact_service is None:
        _contact_service = ContactService()
    return _contact_service
