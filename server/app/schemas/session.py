"""Session schemas."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.schemas.common import ORMModel


MAX_SESSION_IDENTIFIER_LENGTH = 128
SessionIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_SESSION_IDENTIFIER_LENGTH),
]


class CreateDirectSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participant_ids: list[SessionIdentifier] = Field(min_length=1)
    encryption_mode: Literal["plain", "e2ee_private"] = "plain"

    @field_validator("participant_ids")
    @classmethod
    def _normalize_participants(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value or []))
        if len(normalized) != 1:
            raise ValueError("participant_ids must contain exactly one participant")
        return normalized


class SessionMemberOut(ORMModel):
    id: str
    username: str = ""
    nickname: str = ""
    avatar: str | None = None
    group_nickname: str = ""
    role: str = "member"
    joined_at: str | None = None


class SessionOut(ORMModel):
    id: str
    session_type: str
    name: str
    participant_ids: list[str] = Field(default_factory=list)
    last_message: str | None = None
    last_message_id: str | None = None
    last_message_status: str | None = None
    last_message_sender_id: str | None = None
    last_message_time: str | None = None
    updated_at: str | None = None
    unread_count: int = 0
    avatar: str | None = None
    is_ai_session: bool
    encryption_mode: str = 'plain'
    call_capabilities: dict[str, bool] = Field(default_factory=dict)
    member_version: int = 0
    created_at: str | None = None
    group_id: str | None = None
    owner_id: str | None = None
    group_announcement: str = ""
    announcement_message_id: str | None = None
    announcement_author_id: str | None = None
    announcement_published_at: str | None = None
    group_note: str = ""
    my_group_nickname: str = ""
    counterpart_id: str | None = None
    counterpart_name: str | None = None
    counterpart_username: str | None = None
    counterpart_avatar: str | None = None
    counterpart_gender: str | None = None
    members: list[SessionMemberOut] = Field(default_factory=list)
