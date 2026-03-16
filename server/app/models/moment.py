"""Moment and interaction models."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class Moment(IdMixin, TimestampMixin, Base):
    __tablename__ = "moments"
    __table_args__ = (
        Index("idx_moments_user_id", "user_id"),
    )

    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")


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
