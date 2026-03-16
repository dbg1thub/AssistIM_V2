"""Group schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    member_ids: list[str] = Field(default_factory=list)
    members: list[str] = Field(default_factory=list)


class GroupMemberAdd(BaseModel):
    user_id: str
    role: str = "member"


class GroupTransferOwner(BaseModel):
    new_owner_id: str


class GroupOut(ORMModel):
    id: str
    name: str
    owner_id: str
    session_id: str
