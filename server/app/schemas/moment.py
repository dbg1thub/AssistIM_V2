"""Moment schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import ORMModel


MAX_MOMENT_CONTENT_LENGTH = 2_000
MAX_MOMENT_COMMENT_LENGTH = 1_000


class MomentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=MAX_MOMENT_CONTENT_LENGTH)

    @field_validator("content", mode="before")
    @classmethod
    def _normalize_content(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("content must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError("content cannot be blank")
        return normalized


class MomentCommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=MAX_MOMENT_COMMENT_LENGTH)

    @field_validator("content", mode="before")
    @classmethod
    def _normalize_content(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("content must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError("content cannot be blank")
        return normalized


class MomentAuthorOut(ORMModel):
    id: str
    username: str
    nickname: str | None = None
    avatar: str | None = None


class MomentOut(ORMModel):
    id: str
    user_id: str
    content: str
    author: MomentAuthorOut | None = None


class MomentCommentOut(ORMModel):
    id: str
    moment_id: str
    user_id: str
    content: str
    author: MomentAuthorOut | None = None
