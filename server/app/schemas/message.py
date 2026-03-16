"""Message schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class MessageCreate(BaseModel):
    session_id: str | None = None
    content: str = ""
    type: str = Field(default="text", pattern="^(text|image|file|video|voice|system)$")


class MessageUpdate(BaseModel):
    content: str


class MessageOut(ORMModel):
    id: str
    session_id: str
    sender_id: str
    type: str
    content: str
    status: str
