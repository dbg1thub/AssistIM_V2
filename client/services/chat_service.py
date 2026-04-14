"""Chat Service Module.

HTTP-facing chat service that centralizes message-related backend calls.
"""

from __future__ import annotations

from typing import Any, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.network.http_client import get_http_client


setup_logging()
logger = logging.get_logger(__name__)


class ChatService:
    """Encapsulate chat-related HTTP operations."""

    def __init__(self) -> None:
        self._http = get_http_client()

    async def fetch_messages(
        self,
        session_id: str,
        *,
        limit: int = 50,
        before_seq: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Fetch one message page for a session from the backend."""
        params: dict[str, Any] = {"limit": limit}
        if before_seq is not None:
            params["before_seq"] = int(before_seq)

        payload = await self._http.get(f"/sessions/{session_id}/messages", params=params)
        if not isinstance(payload, dict):
            logger.warning("Unexpected messages payload for %s: %r", session_id, payload)
            return []
        items = payload.get("messages")
        if not isinstance(items, list):
            logger.warning("Unexpected messages payload for %s: %r", session_id, payload)
            return []
        return [dict(item) for item in items if isinstance(item, dict)]

    async def persist_read_receipt(self, session_id: str, message_id: str) -> None:
        """Persist one cumulative read receipt via HTTP."""
        await self._http.post(
            "/messages/read/batch",
            json={
                "session_id": session_id,
                "message_id": message_id,
            },
        )

    async def recall_message(self, message_id: str) -> None:
        """Recall one previously sent message."""
        await self._http.post(f"/messages/{message_id}/recall")

    async def edit_message(self, message_id: str, new_content: str, *, extra: Optional[dict[str, Any]] = None) -> None:
        """Edit one previously sent message."""
        payload: dict[str, Any] = {"content": new_content}
        if extra is not None:
            payload["extra"] = dict(extra)
        await self._http.put(f"/messages/{message_id}", json=payload)


_chat_service: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    """Get the global chat service instance."""
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service
