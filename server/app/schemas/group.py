"""Group schemas."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationInfo, field_validator, model_validator

from app.schemas.common import ORMModel


MAX_GROUP_IDENTIFIER_LENGTH = 128
GroupIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_GROUP_IDENTIFIER_LENGTH),
]
GroupMemberRole = Literal["member", "admin"]


class GroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., max_length=128)
    member_ids: list[GroupIdentifier] = Field(default_factory=list)
    encryption_mode: Literal["plain", "e2ee_group"] = "plain"
    members: list[GroupIdentifier] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("group name is required")
        return normalized

    @field_validator("member_ids", "members")
    @classmethod
    def _dedupe_member_list(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values or []))

    @model_validator(mode="after")
    def _validate_member_sources(self) -> "GroupCreate":
        if self.member_ids and self.members and self.member_ids != self.members:
            raise ValueError("member_ids and members must match when both are provided")
        if not (self.member_ids or self.members):
            raise ValueError("at least one group member is required")
        return self

    @property
    def requested_member_ids(self) -> list[str]:
        return list(self.member_ids or self.members)


class GroupMemberAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: GroupIdentifier
    role: Literal["member"] = "member"

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("role must be a string")
        return value.strip().lower()


class GroupMemberRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: GroupMemberRole

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("role must be a string")
        return value.strip().lower()


class GroupTransferOwner(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_owner_id: GroupIdentifier


class GroupProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=128)
    announcement: str | None = Field(default=None, max_length=1000)

    @field_validator("name", "announcement")
    @classmethod
    def _normalize_optional_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized and info.field_name == "name":
            raise ValueError("field cannot be blank")
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
