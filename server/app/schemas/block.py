"""Block schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BlockTargetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_user_id: str = Field(min_length=1)

    @field_validator("target_user_id", mode="before")
    @classmethod
    def _normalize_target_user_id(cls, value: object) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("target_user_id is required")
        return normalized
