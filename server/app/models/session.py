"""Chat session models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class ChatSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "sessions"

    type: Mapped[str] = mapped_column(nullable=False, default="private")
    name: Mapped[str] = mapped_column(nullable=False, default="New Session")
    avatar: Mapped[str | None] = mapped_column(nullable=True)
    is_ai_session: Mapped[bool] = mapped_column(default=False)


class SessionMember(Base):
    __tablename__ = "session_members"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_session_member"),
        Index("idx_session_members_session_id", "session_id"),
        Index("idx_session_members_user_id", "user_id"),
    )

    session_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("sessions.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
