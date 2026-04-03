"""Group schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class GroupCreate(BaseModel):
    name: str = Field(default="", max_length=128)
    member_ids: list[str] = Field(default_factory=list)
    members: list[str] = Field(default_factory=list)


class GroupMemberAdd(BaseModel):
    user_id: str
    role: str = "member"


class GroupMemberRoleUpdate(BaseModel):
    role: str = "member"


class GroupTransferOwner(BaseModel):
    new_owner_id: str


class GroupOut(ORMModel):
    id: str
    name: str
    avatar: str | None = None
    avatar_kind: str = "generated"
    owner_id: str
    session_id: str

