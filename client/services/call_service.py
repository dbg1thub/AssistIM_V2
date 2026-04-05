"""Call service module.

HTTP-facing call service for runtime ICE/TURN configuration.
"""

from __future__ import annotations

from typing import Any, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.network.http_client import get_http_client


setup_logging()
logger = logging.get_logger(__name__)


class CallService:
    """Encapsulate call-related HTTP operations."""

    def __init__(self) -> None:
        self._http = get_http_client()

    async def fetch_ice_servers(self) -> list[dict[str, Any]]:
        """Fetch one normalized ICE server list from the backend."""
        payload = await self._http.get("/calls/ice-servers")
        if not isinstance(payload, dict):
            logger.warning("Unexpected ICE server payload: %r", payload)
            return []

        raw_servers = payload.get("ice_servers")
        if not isinstance(raw_servers, list):
            logger.warning("Unexpected ICE server list payload: %r", payload)
            return []

        normalized: list[dict[str, Any]] = []
        for item in raw_servers:
            if not isinstance(item, dict):
                continue
            urls_value = item.get("urls")
            if isinstance(urls_value, str):
                urls = [urls_value.strip()] if urls_value.strip() else []
            elif isinstance(urls_value, list):
                urls = [str(url or "").strip() for url in urls_value if str(url or "").strip()]
            else:
                urls = []
            if not urls:
                continue
            server_payload: dict[str, Any] = {"urls": urls}
            username = str(item.get("username", "") or "").strip()
            credential = str(item.get("credential", "") or "").strip()
            if username:
                server_payload["username"] = username
            if credential:
                server_payload["credential"] = credential
            normalized.append(server_payload)
        return normalized


_call_service: Optional[CallService] = None


def get_call_service() -> CallService:
    """Get the global call service instance."""
    global _call_service
    if _call_service is None:
        _call_service = CallService()
    return _call_service
