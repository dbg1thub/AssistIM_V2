"""File schemas."""

from __future__ import annotations

from app.schemas.common import ORMModel


class FileSummaryOut(ORMModel):
    id: str
    url: str
    mime_type: str | None = None
    original_name: str
    size_bytes: int


class FileOut(FileSummaryOut):
    created_at: str | None = None