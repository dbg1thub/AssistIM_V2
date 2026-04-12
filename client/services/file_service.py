"""File Service Module.

Centralized file-upload boundary used by chat/media/profile flows.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from client.core import logging
from client.core.exceptions import ServerError
from client.core.logging import setup_logging
from client.network.http_client import get_http_client


setup_logging()
logger = logging.get_logger(__name__)


class FileService:
    """Encapsulate file upload operations behind explicit service boundaries."""

    DEFAULT_UPLOAD_PATH = "/files/upload"
    PROFILE_AVATAR_UPLOAD_PATH = "/users/me/avatar"

    def __init__(self) -> None:
        self._http = get_http_client()

    async def upload_file(
        self,
        file_path: str,
        *,
        upload_path: str | None = None,
    ) -> dict[str, Any]:
        """Upload one file and return one normalized payload with stable media metadata."""
        target_path = upload_path or self.DEFAULT_UPLOAD_PATH
        payload = await self._http.upload_file(file_path, upload_path=target_path)
        if not isinstance(payload, dict):
            logger.error("Upload response must be a JSON object for %s: %r", file_path, payload)
            raise ServerError("Upload response must be a JSON object")

        file_url = str(payload.get("url") or "")
        if not file_url:
            logger.error("Upload response missing url for %s: %r", file_path, payload)
            raise ServerError("Upload response missing url")

        original_name = str(payload.get("original_name") or os.path.basename(file_path) or "upload.bin")
        mime_type = str(payload.get("mime_type") or "")
        size_bytes = self._coerce_size_bytes(payload.get("size_bytes"), fallback_path=file_path)

        media = {
            "url": file_url,
            "original_name": original_name,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
        }
        normalized = {
            "url": file_url,
            "original_name": original_name,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "media": media,
        }
        if "id" in payload:
            normalized["id"] = payload["id"]
        if "created_at" in payload:
            normalized["created_at"] = payload["created_at"]
        return normalized

    @staticmethod
    def _coerce_size_bytes(raw_value: Any, *, fallback_path: str) -> int:
        try:
            if raw_value is not None:
                return max(0, int(raw_value))
        except (TypeError, ValueError):
            pass

        try:
            return max(0, int(os.path.getsize(fallback_path)))
        except OSError:
            return 0

    async def upload_chat_attachment(self, file_path: str) -> dict[str, Any]:
        """Upload one chat attachment using the standard file endpoint."""
        return await self.upload_file(file_path)

    async def download_chat_attachment(self, file_url: str) -> bytes:
        """Download one chat attachment as raw bytes."""
        return await self._http.download_bytes(file_url)

    async def upload_profile_avatar(self, file_path: str) -> dict[str, Any]:
        """Upload one profile avatar using the dedicated avatar endpoint."""
        payload = await self._http.upload_file(file_path, upload_path=self.PROFILE_AVATAR_UPLOAD_PATH)
        if not isinstance(payload, dict):
            logger.error("Avatar upload response must be a JSON object for %s: %r", file_path, payload)
            raise ServerError("Avatar upload response must be a JSON object")
        avatar_url = str(payload.get("avatar") or "")
        if not avatar_url:
            logger.error("Avatar upload response missing avatar for %s: %r", file_path, payload)
            raise ServerError("Avatar upload response missing avatar")
        return dict(payload)

    async def reset_profile_avatar(self) -> dict[str, Any]:
        """Reset the current user's avatar to the server-assigned default avatar."""
        payload = await self._http.delete(self.PROFILE_AVATAR_UPLOAD_PATH)
        if not isinstance(payload, dict):
            logger.error("Avatar reset response must be a JSON object: %r", payload)
            raise ServerError("Avatar reset response must be a JSON object")
        return dict(payload)

    async def close(self) -> None:
        """Retire the file service without closing the shared HTTP transport."""
        global _file_service
        if _file_service is self:
            _file_service = None


_file_service: Optional[FileService] = None


def get_file_service() -> FileService:
    """Get the global file service instance."""
    global _file_service
    if _file_service is None:
        _file_service = FileService()
    return _file_service
