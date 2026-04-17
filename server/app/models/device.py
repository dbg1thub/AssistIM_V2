"""Device and key models for private-chat E2EE."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, generate_id
from app.utils.time import utcnow


class UserDevice(TimestampMixin, Base):
    __tablename__ = "user_devices"
    __table_args__ = (
        Index("idx_user_devices_user_id", "user_id"),
        Index("idx_user_devices_is_active", "is_active"),
    )

    device_id: Mapped[str] = mapped_column(String(length=64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(length=36), ForeignKey("users.id"), nullable=False)
    identity_key_public: Mapped[str] = mapped_column(Text, nullable=False)
    signing_key_public: Mapped[str] = mapped_column(Text, nullable=False)
    device_name: Mapped[str] = mapped_column(String(length=128), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)


class UserSignedPreKey(TimestampMixin, Base):
    __tablename__ = "user_signed_prekeys"
    __table_args__ = (
        UniqueConstraint("device_id", "key_id", name="uq_user_signed_prekeys_device_key"),
        Index("idx_user_signed_prekeys_device_id", "device_id"),
        Index("idx_user_signed_prekeys_is_active", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(length=36), primary_key=True, default=generate_id)
    device_id: Mapped[str] = mapped_column(String(length=64), ForeignKey("user_devices.device_id"), nullable=False)
    key_id: Mapped[int] = mapped_column(Integer, nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class UserPreKey(Base):
    __tablename__ = "user_prekeys"
    __table_args__ = (
        UniqueConstraint("device_id", "prekey_id", name="uq_user_prekeys_device_key"),
        Index("idx_user_prekeys_device_id", "device_id"),
        Index("idx_user_prekeys_claim_state", "device_id", "is_consumed"),
    )

    id: Mapped[str] = mapped_column(String(length=36), primary_key=True, default=generate_id)
    device_id: Mapped[str] = mapped_column(String(length=64), ForeignKey("user_devices.device_id"), nullable=False)
    prekey_id: Mapped[int] = mapped_column(Integer, nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    is_consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=utcnow)
    claimed_at: Mapped[datetime | None] = mapped_column(nullable=True)

