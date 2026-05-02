"""Admin authorization and audit models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin
from app.utils.time import utcnow


class AdminAuditLog(IdMixin, Base):
    __tablename__ = "admin_audit_logs"
    __table_args__ = (
        Index("idx_admin_audit_logs_actor_user_id", "actor_user_id"),
        Index("idx_admin_audit_logs_action", "action"),
        Index("idx_admin_audit_logs_created_at", "created_at"),
    )

    actor_user_id: Mapped[str | None] = mapped_column(String(length=36), nullable=True)
    actor_username: Mapped[str] = mapped_column(String(length=255), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(length=128), nullable=False)
    target_type: Mapped[str] = mapped_column(String(length=64), nullable=False, default="")
    target_id: Mapped[str] = mapped_column(String(length=128), nullable=False, default="")
    request_path: Mapped[str] = mapped_column(String(length=255), nullable=False, default="")
    request_method: Mapped[str] = mapped_column(String(length=16), nullable=False, default="")
    client_ip: Mapped[str] = mapped_column(String(length=64), nullable=False, default="")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_code: Mapped[str] = mapped_column(String(length=64), nullable=False, default="")
    detail_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
