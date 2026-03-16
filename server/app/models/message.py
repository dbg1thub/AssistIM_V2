"""Message models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class Message(IdMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_messages_session_id", "session_id"),
        Index("idx_messages_sender_id", "sender_id"),
    )

    session_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("sessions.id"), nullable=False)
    sender_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False)
    type: Mapped[str] = mapped_column(nullable=False, default="text")
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(default="sent")


class MessageRead(Base):
    __tablename__ = "message_reads"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_message_read"),
        Index("idx_message_reads_user_id", "user_id"),
    )

    message_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("messages.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), primary_key=True)
    read_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
