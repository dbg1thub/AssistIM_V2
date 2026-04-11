"""Session schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from app.schemas.common import ORMModel


class CreateDirectSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participant_ids: list[str] = Field(min_length=1, max_length=1)
    encryption_mode: Literal["plain", "e2ee_private"] = "plain"

    @field_validator("participant_ids")
    @classmethod
    def _normalize_participants(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw_id in list(value or []):
            normalized_id = str(raw_id or "").strip()
            if not normalized_id:
                raise ValueError("participant_ids cannot contain blank values")
            if normalized_id not in normalized:
                normalized.append(normalized_id)
        if len(normalized) != 1:
            raise ValueError("participant_ids must contain exactly one participant")
        return normalized



class SessionTypingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    typing: StrictBool = True


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
    last_message_id: str | None = None
    last_message_status: str | None = None
    last_message_sender_id: str | None = None
    last_message_time: str | None = None
    updated_at: str | None = None
    unread_count: int = 0
    avatar: str | None = None
    is_ai_session: bool
    encryption_mode: str = 'plain'
    session_crypto_state: dict[str, Any] = Field(default_factory=dict)
    call_capabilities: dict[str, bool] = Field(default_factory=dict)
    group_member_version: int = 0
    created_at: str | None = None
    counterpart_id: str | None = None
    counterpart_name: str | None = None
    counterpart_username: str | None = None
    counterpart_avatar: str | None = None
    counterpart_gender: str | None = None
    members: list[SessionMemberOut] = Field(default_factory=list)
