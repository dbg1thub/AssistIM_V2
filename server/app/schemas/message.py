"""Message schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class MessageCreate(BaseModel):
    session_id: str | None = None
    content: str = ""
    type: str = Field(default="text", pattern="^(text|image|file|video|voice|system)$")
    extra: dict[str, Any] = Field(default_factory=dict)


class MessageUpdate(BaseModel):
    content: str


class MessageOut(ORMModel):
    id: str
    session_id: str
    sender_id: str
    type: str
    content: str
    status: str
    extra: dict[str, Any] = Field(default_factory=dict)
