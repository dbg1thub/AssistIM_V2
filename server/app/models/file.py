"""Stored file model."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class StoredFile(IdMixin, TimestampMixin, Base):
    __tablename__ = "files"
    __table_args__ = (
        Index("idx_files_user_id", "user_id"),
    )

    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False)
    file_url: Mapped[str] = mapped_column(nullable=False)
    file_type: Mapped[str | None] = mapped_column(nullable=True)
    file_name: Mapped[str] = mapped_column(nullable=False)
