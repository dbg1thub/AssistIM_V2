"""Email verification models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class EmailVerificationCode(IdMixin, TimestampMixin, Base):
    __tablename__ = "email_verification_codes"
    __table_args__ = (
        Index("idx_email_verification_email_purpose", "email", "purpose"),
        Index("idx_email_verification_expires_at", "expires_at"),
    )

    email: Mapped[str] = mapped_column(String(length=255), nullable=False)
    purpose: Mapped[str] = mapped_column(String(length=32), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(length=64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_ip: Mapped[str] = mapped_column(String(length=64), nullable=False, default="", server_default="")
