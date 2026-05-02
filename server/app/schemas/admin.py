"""Admin API schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.dependencies.admin_dependency import validate_user_role


class AdminSetUserRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1, max_length=32)

    @field_validator("role", mode="before")
    @classmethod
    def _strip_role(cls, value):
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("role")
    @classmethod
    def _validate_role(cls, value: str) -> str:
        return validate_user_role(value)


class AdminDisableUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=255)

    @field_validator("reason", mode="before")
    @classmethod
    def _strip_reason(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value
