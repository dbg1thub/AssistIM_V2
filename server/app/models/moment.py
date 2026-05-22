"""Moment and interaction models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class Moment(IdMixin, TimestampMixin, Base):
    __tablename__ = "moments"
    __table_args__ = (
        Index("idx_moments_user_id", "user_id"),
    )

    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    media_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    visibility_scope: Mapped[str] = mapped_column(String(16), nullable=False, default="public")
    visibility_user_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")


class MomentPrivacySetting(IdMixin, TimestampMixin, Base):
    __tablename__ = "moment_privacy_settings"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_moment_privacy_settings_user_id"),
        Index("idx_moment_privacy_settings_user_id", "user_id"),
    )

    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False)
    hide_my_moments_user_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    hide_their_moments_user_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    visible_time_scope: Mapped[str] = mapped_column(String(16), nullable=False, default="all")


class MomentLike(TimestampMixin, Base):
    __tablename__ = "moment_likes"
    __table_args__ = (
        UniqueConstraint("moment_id", "user_id", name="uq_moment_like"),
        Index("idx_moment_likes_moment_id", "moment_id"),
    )

    moment_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("moments.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), primary_key=True)


class MomentComment(IdMixin, TimestampMixin, Base):
    __tablename__ = "moment_comments"
    __table_args__ = (
        Index("idx_moment_comments_moment_id", "moment_id"),
    )

    moment_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("moments.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    image_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class MomentNotification(IdMixin, TimestampMixin, Base):
    __tablename__ = "moment_notifications"
    __table_args__ = (
        UniqueConstraint(
            "recipient_user_id",
            "notification_type",
            "moment_id",
            "comment_id",
            "actor_user_id",
            name="uq_moment_notification_comment",
        ),
        Index("idx_moment_notifications_recipient_read", "recipient_user_id", "read_at"),
        Index("idx_moment_notifications_moment_id", "moment_id"),
    )

    recipient_user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False)
    moment_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False)
    comment_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content_preview: Mapped[str] = mapped_column(Text, nullable=False, default="")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
