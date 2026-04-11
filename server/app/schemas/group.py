"""Group schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import ORMModel


class GroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=128)
    member_ids: list[str] = Field(default_factory=list)
    encryption_mode: Literal["plain", "e2ee_group"] = "plain"
    members: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        return str(value or "").strip()

    @field_validator("member_ids", "members")
    @classmethod
    def _normalize_member_list(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw_id in list(values or []):
            normalized_id = str(raw_id or "").strip()
            if not normalized_id:
                raise ValueError("member ids cannot contain blank values")
            if normalized_id not in normalized:
                normalized.append(normalized_id)
        return normalized

    @model_validator(mode="after")
    def _validate_member_sources(self) -> "GroupCreate":
        if self.member_ids and self.members and self.member_ids != self.members:
            raise ValueError("member_ids and members must match when both are provided")
        return self

    @property
    def requested_member_ids(self) -> list[str]:
        return list(self.member_ids or self.members)


class GroupMemberAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    role: Literal["member"] = "member"

    @field_validator("user_id")
    @classmethod
    def _normalize_user_id(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("user_id is required")
        return normalized


class GroupMemberRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["member", "admin"] = "member"


class GroupTransferOwner(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_owner_id: str

    @field_validator("new_owner_id")
    @classmethod
    def _normalize_new_owner_id(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("new_owner_id is required")
        return normalized


class GroupProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=128)
    announcement: str | None = Field(default=None, max_length=1000)

    @field_validator("name", "announcement")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class GroupSelfProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=1000)
    my_group_nickname: str | None = Field(default=None, max_length=64)

    @field_validator("note", "my_group_nickname")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class GroupOut(ORMModel):
    id: str
    name: str
    announcement: str = ""
    announcement_message_id: str | None = None
    announcement_author_id: str | None = None
    announcement_published_at: str | None = None
    avatar: str | None = None
    avatar_kind: str = "generated"
    owner_id: str
    session_id: str
    member_version: int = 0
    group_member_version: int = 0
