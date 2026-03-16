"""Session schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class CreatePrivateSessionRequest(BaseModel):
    participant_ids: list[str] = Field(min_length=1)
    name: str | None = None


class CreateGroupSessionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    participant_ids: list[str] = Field(min_length=1)


class SessionOut(ORMModel):
    id: str
    type: str
    name: str
    avatar: str | None = None
    is_ai_session: bool
