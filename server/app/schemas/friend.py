"""Friend schemas."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import ORMModel


class FriendRequestCreate(BaseModel):
    receiver_id: str | None = None
    user_id: str | None = None
    message: str | None = None


class FriendRequestOut(ORMModel):
    request_id: str
    sender_id: str
    receiver_id: str
    status: str
    message: str | None = None
    created_at: str | None = None


class FriendOut(BaseModel):
    id: str
    username: str
    nickname: str
    avatar: str | None = None
