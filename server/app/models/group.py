"""Group models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class Group(IdMixin, TimestampMixin, Base):
    __tablename__ = "groups"
    __table_args__ = (
        Index("idx_groups_owner_id", "owner_id"),
    )

    name: Mapped[str] = mapped_column(nullable=False)
    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("sessions.id"), nullable=False, unique=True)


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_member"),
        Index("idx_group_members_group_id", "group_id"),
    )

    group_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("groups.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(default="member")
    joined_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
