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


class AdminDatabaseBackup(IdMixin, Base):
    __tablename__ = "admin_database_backups"
    __table_args__ = (
        Index("idx_admin_database_backups_created_by_user_id", "created_by_user_id"),
        Index("idx_admin_database_backups_status", "status"),
        Index("idx_admin_database_backups_created_at", "created_at"),
    )

    created_by_user_id: Mapped[str | None] = mapped_column(String(length=36), nullable=True)
    created_by_username: Mapped[str] = mapped_column(String(length=255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(length=32), nullable=False, default="pending")
    database_dialect: Mapped[str] = mapped_column(String(length=32), nullable=False, default="")
    backup_format: Mapped[str] = mapped_column(String(length=32), nullable=False, default="")
    storage_key: Mapped[str] = mapped_column(String(length=512), nullable=False, default="")
    file_name: Mapped[str] = mapped_column(String(length=255), nullable=False, default="")
    file_path: Mapped[str] = mapped_column(String(length=1024), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(nullable=False, default=0)
    checksum_sha256: Mapped[str] = mapped_column(String(length=64), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    verification_status: Mapped[str] = mapped_column(String(length=32), nullable=False, default="")
    verification_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
