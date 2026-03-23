"""Chat session models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin
from app.utils.time import utcnow


class ChatSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "sessions"

    type: Mapped[str] = mapped_column(nullable=False, default="private")
    name: Mapped[str] = mapped_column(nullable=False, default="New Session")
    avatar: Mapped[str | None] = mapped_column(nullable=True)
    is_ai_session: Mapped[bool] = mapped_column(default=False)
    last_message_seq: Mapped[int] = mapped_column(nullable=False, default=0)
    last_event_seq: Mapped[int] = mapped_column(nullable=False, default=0)


class SessionMember(Base):
    __tablename__ = "session_members"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_session_member"),
        Index("idx_session_members_session_id", "session_id"),
        Index("idx_session_members_user_id", "user_id"),
    )

    session_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("sessions.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_read_seq: Mapped[int] = mapped_column(nullable=False, default=0)
    last_read_message_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("messages.id"),
        nullable=True,
    )
    last_read_at: Mapped[datetime | None] = mapped_column(nullable=True)


class SessionEvent(IdMixin, Base):
    __tablename__ = "session_events"
    __table_args__ = (
        UniqueConstraint("session_id", "event_seq", name="uq_session_event_seq"),
        Index("idx_session_events_session_id", "session_id"),
        Index("idx_session_events_type", "type"),
    )

    session_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("sessions.id"), nullable=False)
    event_seq: Mapped[int] = mapped_column(nullable=False, default=0)
    type: Mapped[str] = mapped_column(nullable=False)
    message_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    actor_user_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)