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

        normalized = dict(payload)
        file_url = str(normalized.get("url") or normalized.get("file_url") or normalized.get("avatar") or "")
        if not file_url:
            logger.error("Upload response missing url for %s: %r", file_path, payload)
            raise ServerError("Upload response missing url")

        original_name = str(
            normalized.get("original_name")
            or normalized.get("file_name")
            or normalized.get("name")
            or os.path.basename(file_path)
            or "upload.bin"
        )
        mime_type = str(normalized.get("mime_type") or normalized.get("file_type") or "")
        storage_provider = str(normalized.get("storage_provider") or "")
        storage_key = str(normalized.get("storage_key") or "")
        checksum_sha256 = str(normalized.get("checksum_sha256") or "")
        size_bytes = self._coerce_size_bytes(normalized.get("size_bytes"), fallback_path=file_path)

        media = dict(normalized.get("media") or {})
        media.setdefault("url", file_url)
        media.setdefault("original_name", original_name)
        media.setdefault("mime_type", mime_type)
        media.setdefault("storage_provider", storage_provider)
        media.setdefault("storage_key", storage_key)
        media.setdefault("size_bytes", size_bytes)
        media.setdefault("checksum_sha256", checksum_sha256)

        normalized["url"] = file_url
        normalized.setdefault("file_url", file_url)
        normalized["original_name"] = original_name
        normalized.setdefault("file_name", original_name)
        normalized.setdefault("name", original_name)
        normalized["mime_type"] = mime_type
        normalized.setdefault("file_type", mime_type)
        normalized["storage_provider"] = storage_provider
        normalized["storage_key"] = storage_key
        normalized["size_bytes"] = size_bytes
        normalized["checksum_sha256"] = checksum_sha256
        normalized["media"] = media
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


_file_service: Optional[FileService] = None


def get_file_service() -> FileService:
    """Get the global file service instance."""
    global _file_service
    if _file_service is None:
        _file_service = FileService()
    return _file_service

