"""Shared model helpers."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.utils.time import utcnow

from sqlalchemy import DateTime, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def generate_id() -> str:
    """Generate a UUID primary key."""
    return str(uuid.uuid4())


class IdMixin:
    """UUID primary key mixin using PostgreSQL native UUID where available."""

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=generate_id)


class TimestampMixin:
    """Created/updated timestamp mixin."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


__all__ = ["Base", "IdMixin", "TimestampMixin", "generate_id"]
