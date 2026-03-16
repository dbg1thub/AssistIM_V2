"""Moment schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class MomentCreate(BaseModel):
    content: str = Field(min_length=1)


class MomentCommentCreate(BaseModel):
    content: str = Field(min_length=1)


class MomentOut(ORMModel):
    id: str
    user_id: str
    content: str


class MomentCommentOut(ORMModel):
    id: str
    moment_id: str
    user_id: str
    content: str
