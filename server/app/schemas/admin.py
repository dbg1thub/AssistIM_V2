"""Admin API schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class AdminDatabaseBackupPruneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep_last: int | None = Field(default=None, ge=0, le=10000)
    older_than_days: int | None = Field(default=None, ge=0, le=36500)
    include_failed: bool = False
    include_deleted: bool = False
    dry_run: bool = True

    @model_validator(mode="after")
    def _validate_cleanup_criteria(self):
        if self.keep_last is None and self.older_than_days is None:
            raise ValueError("keep_last or older_than_days is required")
        return self
