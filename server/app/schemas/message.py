"""Message schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ORMModel


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str | None = None
    content: str = ""
    message_type: str = Field(default="text", pattern="^(text|image|file|video|voice|system)$")
    extra: dict[str, Any] = Field(default_factory=dict)


class MessageUpdate(BaseModel):
    content: str
    extra: dict[str, Any] | None = None


class MessageReadBatch(BaseModel):
    session_id: str
    message_id: str


class SenderProfileOut(ORMModel):
    id: str
    username: str = ""
    nickname: str = ""
    display_name: str = ""
    avatar: str | None = None
    avatar_kind: str = ""
    gender: str = ""


class MessageOut(ORMModel):
    message_id: str
    session_id: str
    sender_id: str
    message_type: str
    content: str
    status: str
    created_at: str | None = None
    timestamp: str | None = None
    updated_at: str | None = None
    is_self: bool = False
    is_ai: bool = False
    session_type: str = ""
    session_name: str = ""
    session_avatar: str | None = None
    participant_ids: list[str] = Field(default_factory=list)
    is_ai_session: bool = False
    sender_profile: SenderProfileOut | None = None
    session_seq: int = 0
    read_count: int = 0
    read_target_count: int = 0
    read_by_user_ids: list[str] = Field(default_factory=list)
    is_read_by_me: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)
