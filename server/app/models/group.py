"""Group models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin
from app.utils.time import utcnow


class Group(IdMixin, TimestampMixin, Base):
    __tablename__ = "groups"
    __table_args__ = (
        Index("idx_groups_owner_id", "owner_id"),
    )

    name: Mapped[str] = mapped_column(nullable=False)
    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("sessions.id"), nullable=False, unique=True)
    announcement: Mapped[str] = mapped_column(nullable=False, default="")
    announcement_message_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), ForeignKey("messages.id"), nullable=True)
    announcement_author_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=True)
    announcement_published_at: Mapped[datetime | None] = mapped_column(nullable=True)
    avatar_kind: Mapped[str] = mapped_column(String(length=16), nullable=False, default="generated")
    avatar_file_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), ForeignKey("files.id"), nullable=True)
    avatar_version: Mapped[int] = mapped_column(nullable=False, default=1)


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_member"),
        Index("idx_group_members_group_id", "group_id"),
    )

    group_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("groups.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(default="member")
    group_nickname: Mapped[str] = mapped_column(nullable=False, default="")
    note: Mapped[str] = mapped_column(nullable=False, default="")
    joined_at: Mapped[datetime] = mapped_column(default=utcnow)



