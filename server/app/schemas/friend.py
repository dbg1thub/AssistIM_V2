"""Friend schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import ORMModel


class FriendRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receiver_id: str | None = None
    user_id: str | None = None
    message: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _normalize_targets(self) -> "FriendRequestCreate":
        receiver_id = str(self.receiver_id or "").strip() or None
        user_id = str(self.user_id or "").strip() or None
        message = str(self.message or "").strip() or None

        if not receiver_id and not user_id:
            raise ValueError("receiver_id or user_id is required")
        if receiver_id and user_id and receiver_id != user_id:
            raise ValueError("receiver_id and user_id must match when both are provided")

        self.receiver_id = receiver_id or user_id
        self.user_id = user_id or receiver_id
        self.message = message
        return self

    @property
    def target_user_id(self) -> str:
        return str(self.receiver_id or self.user_id or "")


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
