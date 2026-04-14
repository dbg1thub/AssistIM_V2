"""Friend schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import ORMModel


class FriendRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_user_id: str = Field(min_length=1)
    message: str | None = Field(default=None, max_length=500)

    @field_validator("target_user_id", mode="before")
    @classmethod
    def _normalize_target_user_id(cls, value: object) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("target_user_id is required")
        return normalized

    @field_validator("message", mode="before")
    @classmethod
    def _normalize_message(cls, value: object) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None


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
