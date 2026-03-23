"""File schemas."""

from __future__ import annotations

from typing import Any

from app.schemas.common import ORMModel


class FileOut(ORMModel):
    id: str
    user_id: str
    storage_provider: str
    storage_key: str
    url: str
    file_url: str
    mime_type: str | None = None
    file_type: str | None = None
    original_name: str
    file_name: str
    name: str
    size_bytes: int
    checksum_sha256: str
    media: dict[str, Any]
    created_at: str | None = None
