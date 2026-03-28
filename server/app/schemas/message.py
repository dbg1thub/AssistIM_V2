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


class MessageReadBatch(BaseModel):
    session_id: str
    message_id: str


class MessageOut(ORMModel):
    message_id: str
    session_id: str
    sender_id: str
    message_type: str
    content: str
    status: str
    extra: dict[str, Any] = Field(default_factory=dict)