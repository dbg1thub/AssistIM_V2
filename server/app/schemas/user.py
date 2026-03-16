"""User schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class UserOut(ORMModel):
    id: str
    username: str
    nickname: str
    avatar: str | None = None
    status: str


class UserUpdateRequest(BaseModel):
    nickname: str | None = Field(default=None, min_length=1, max_length=64)
    avatar: str | None = None
    status: str | None = None
