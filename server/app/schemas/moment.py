"""Moment schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import ORMModel


MAX_MOMENT_CONTENT_LENGTH = 2_000
MAX_MOMENT_COMMENT_LENGTH = 1_000
MAX_MOMENT_MEDIA_ITEMS = 9


class MomentMediaItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["image", "video"]
    url: str = Field(min_length=1, max_length=512)
    original_name: str = Field(default="", max_length=255)
    mime_type: str = Field(default="", max_length=128)
    size_bytes: int = Field(default=0, ge=0)

    @field_validator("type", mode="before")
    @classmethod
    def _normalize_type(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("type must be a string")
        return value.strip().lower()

    @field_validator("url", "original_name", "mime_type", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("value must be a string")
        return value.strip()


class MomentImageItem(MomentMediaItem):
    type: Literal["image"] = "image"


class MomentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(default="", max_length=MAX_MOMENT_CONTENT_LENGTH)
    media: list[MomentMediaItem] = Field(default_factory=list, max_length=MAX_MOMENT_MEDIA_ITEMS)

    @field_validator("content", mode="before")
    @classmethod
    def _normalize_content(cls, value: object) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("content must be a string")
        return value.strip()

    @model_validator(mode="after")
    def _require_content_or_media(self) -> "MomentCreate":
        if not self.content and not self.media:
            raise ValueError("content or media is required")
        video_count = sum(1 for item in self.media if item.type == "video")
        if video_count and len(self.media) != 1:
            raise ValueError("video moments support exactly one video and no images")
        return self


class MomentCommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(default="", max_length=MAX_MOMENT_COMMENT_LENGTH)
    image: MomentImageItem | None = None

    @field_validator("content", mode="before")
    @classmethod
    def _normalize_content(cls, value: object) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("content must be a string")
        return value.strip()

    @model_validator(mode="after")
    def _require_content_or_image(self) -> "MomentCommentCreate":
        if not self.content and self.image is None:
            raise ValueError("content or image is required")
        return self


class MomentAuthorOut(ORMModel):
    id: str
    username: str
    nickname: str | None = None
    avatar: str | None = None


class MomentOut(ORMModel):
    id: str
    user_id: str
    content: str
    media: list[MomentMediaItem] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    videos: list[str] = Field(default_factory=list)
    author: MomentAuthorOut | None = None


class MomentCommentOut(ORMModel):
    id: str
    moment_id: str
    user_id: str
    content: str
    image: MomentImageItem | None = None
    author: MomentAuthorOut | None = None
