"""Discovery Service Module.

HTTP-facing discovery service that centralizes moments-related requests.
"""

from __future__ import annotations

from typing import Any, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.network.http_client import get_http_client


setup_logging()
logger = logging.get_logger(__name__)


class DiscoveryService:
    """Encapsulate moments/discovery HTTP operations."""

    def __init__(self) -> None:
        self._http = get_http_client()

    async def fetch_moments(self, *, user_id: str | None = None) -> list[dict[str, Any]]:
        """Fetch one discovery timeline snapshot."""
        params = {"user_id": user_id} if user_id else None
        payload = await self._http.get("/moments", params=params)
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            logger.warning("Unexpected moments payload: %r", payload)
            return []
        payload = payload["items"]
        return [dict(item) for item in payload if isinstance(item, dict)]

    async def get_moment(self, moment_id: str) -> dict[str, Any]:
        """Fetch one full moment detail payload."""
        payload = await self._http.get(f"/moments/{moment_id}")
        if not isinstance(payload, dict):
            logger.warning("Unexpected moment detail payload for %s: %r", moment_id, payload)
            return {}
        return dict(payload)

    async def create_moment(
        self,
        content: str,
        *,
        media: list[dict[str, Any]] | None = None,
        visibility_scope: str = "public",
        visibility_user_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create one moment."""
        payload = await self._http.post(
            "/moments",
            json={
                "content": content,
                "media": media or [],
                "visibility_scope": visibility_scope,
                "visibility_user_ids": list(visibility_user_ids or []),
            },
        )
        return dict(payload or {})

    async def fetch_moment_privacy_settings(self) -> dict[str, Any]:
        """Fetch the current user's moments privacy settings."""
        payload = await self._http.get("/moments/privacy")
        if not isinstance(payload, dict):
            logger.warning("Unexpected moment privacy settings payload: %r", payload)
            return {}
        return dict(payload)

    async def update_moment_privacy_settings(
        self,
        *,
        hide_my_moments_user_ids: list[str] | None = None,
        hide_their_moments_user_ids: list[str] | None = None,
        visible_time_scope: str | None = None,
    ) -> dict[str, Any]:
        """Update the current user's moments privacy settings."""
        body: dict[str, Any] = {}
        if hide_my_moments_user_ids is not None:
            body["hide_my_moments_user_ids"] = list(hide_my_moments_user_ids)
        if hide_their_moments_user_ids is not None:
            body["hide_their_moments_user_ids"] = list(hide_their_moments_user_ids)
        if visible_time_scope is not None:
            body["visible_time_scope"] = visible_time_scope
        payload = await self._http.patch("/moments/privacy", json=body)
        return dict(payload or {})

    async def like_moment(self, moment_id: str) -> None:
        """Like one moment."""
        await self._http.post(f"/moments/{moment_id}/likes", json={})

    async def unlike_moment(self, moment_id: str) -> None:
        """Unlike one moment."""
        await self._http.delete(f"/moments/{moment_id}/likes")

    async def add_comment(
        self,
        moment_id: str,
        content: str,
        *,
        image: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create one moment comment."""
        body: dict[str, Any] = {"content": content}
        if image:
            body["image"] = dict(image)
        payload = await self._http.post(
            f"/moments/{moment_id}/comments",
            json=body,
        )
        return dict(payload or {})


_discovery_service: Optional[DiscoveryService] = None


def get_discovery_service() -> DiscoveryService:
    """Get the global discovery service instance."""
    global _discovery_service
    if _discovery_service is None:
        _discovery_service = DiscoveryService()
    return _discovery_service
