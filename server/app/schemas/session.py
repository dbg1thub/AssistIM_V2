"""Session schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class CreateDirectSessionRequest(BaseModel):
    participant_ids: list[str] = Field(min_length=1)
    name: str | None = None


class SessionMemberOut(ORMModel):
    id: str
    nickname: str = ""
    username: str = ""
    avatar: str | None = None
    gender: str = ""
    joined_at: str | None = None


class SessionOut(ORMModel):
    id: str
    session_id: str
    session_type: str
    name: str
    participant_ids: list[str] = Field(default_factory=list)
    last_message: str | None = None
    last_message_status: str | None = None
    last_message_sender_id: str | None = None
    last_message_time: str | None = None
    updated_at: str | None = None
    unread_count: int = 0
    avatar: str | None = None
    is_ai_session: bool
    created_at: str | None = None
    counterpart_id: str | None = None
    counterpart_name: str | None = None
    counterpart_username: str | None = None
    counterpart_avatar: str | None = None
    counterpart_gender: str | None = None
    members: list[SessionMemberOut] = Field(default_factory=list)
