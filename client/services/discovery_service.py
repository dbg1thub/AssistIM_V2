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
        if not isinstance(payload, list):
            logger.warning("Unexpected moments payload: %r", payload)
            return []
        return [dict(item) for item in payload if isinstance(item, dict)]

    async def create_moment(self, content: str) -> dict[str, Any]:
        """Create one moment."""
        payload = await self._http.post("/moments", json={"content": content})
        return dict(payload or {})

    async def like_moment(self, moment_id: str) -> None:
        """Like one moment."""
        await self._http.post(f"/moments/{moment_id}/likes", json={})

    async def unlike_moment(self, moment_id: str) -> None:
        """Unlike one moment."""
        await self._http.delete(f"/moments/{moment_id}/likes")

    async def add_comment(self, moment_id: str, content: str) -> dict[str, Any]:
        """Create one moment comment."""
        payload = await self._http.post(
            f"/moments/{moment_id}/comments",
            json={"content": content},
        )
        return dict(payload or {})


_discovery_service: Optional[DiscoveryService] = None


def get_discovery_service() -> DiscoveryService:
    """Get the global discovery service instance."""
    global _discovery_service
    if _discovery_service is None:
        _discovery_service = DiscoveryService()
    return _discovery_service
