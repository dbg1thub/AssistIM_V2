"""File schemas."""

from __future__ import annotations

from app.schemas.common import ORMModel


class FileOut(ORMModel):
    id: str
    user_id: str
    file_url: str
    file_type: str | None = None
    file_name: str
