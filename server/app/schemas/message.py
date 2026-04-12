"""Message schemas."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import ORMModel


MAX_MESSAGE_CONTENT_LENGTH = 20_000
MAX_MESSAGE_IDENTIFIER_LENGTH = 128


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    msg_id: UUID
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CONTENT_LENGTH)
    message_type: str = Field(default="text", pattern="^(text|image|file|video|voice)$")
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def _require_non_blank_content(cls, value: str) -> str:
        if not str(value or "").strip():
            raise ValueError("content cannot be blank")
        return value


class MessageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CONTENT_LENGTH)
    extra: dict[str, Any] | None = None

    @field_validator("content")
    @classmethod
    def _require_non_blank_content(cls, value: str) -> str:
        if not str(value or "").strip():
            raise ValueError("content cannot be blank")
        return value


class MessageReadBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=MAX_MESSAGE_IDENTIFIER_LENGTH)
    message_id: str = Field(min_length=1, max_length=MAX_MESSAGE_IDENTIFIER_LENGTH)

    @field_validator("session_id", "message_id", mode="before")
    @classmethod
    def _normalize_identifier(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("identifier must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError("identifier cannot be blank")
        return normalized


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
    updated_at: str | None = None
    is_self: bool = False
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
