"""User and friendship models."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Index, String, Text, UniqueConstraint, Uuid, column, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("idx_users_username", "username"),
        Index("uq_users_username_lower", func.lower(column("username")), unique=True),
        Index("idx_users_email", "email"),
        Index("idx_users_phone", "phone"),
    )

    username: Mapped[str] = mapped_column(unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(nullable=False)
    nickname: Mapped[str] = mapped_column(nullable=False)
    avatar: Mapped[str | None] = mapped_column(nullable=True)
    avatar_kind: Mapped[str] = mapped_column(String(length=16), nullable=False, default="default")
    avatar_default_key: Mapped[str | None] = mapped_column(String(length=128), nullable=True)
    avatar_file_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), ForeignKey("files.id"), nullable=True)
    email: Mapped[str | None] = mapped_column(String(length=255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(length=32), nullable=True)
    birthday: Mapped[date | None] = mapped_column(Date(), nullable=True)
    region: Mapped[str | None] = mapped_column(String(length=128), nullable=True)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(length=32), nullable=True)
    auth_session_version: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(default="offline")


class FriendRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "friend_requests"
    __table_args__ = (
        Index("idx_friend_requests_sender_id", "sender_id"),
        Index("idx_friend_requests_receiver_id", "receiver_id"),
    )

    sender_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False)
    receiver_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(default="pending")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Friendship(IdMixin, TimestampMixin, Base):
    __tablename__ = "friends"
    __table_args__ = (
        UniqueConstraint("user_id", "friend_id", name="uq_friend_pair"),
        Index("idx_friends_user_id", "user_id"),
    )

    user_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False)
    friend_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False)
