"""Auth schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.auth_contract import (
    NICKNAME_MAX_LENGTH,
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    REFRESH_TOKEN_MAX_LENGTH,
    REFRESH_TOKEN_MIN_LENGTH,
    TOKEN_TYPE_BEARER,
    USERNAME_MAX_LENGTH,
    USERNAME_MIN_LENGTH,
    canonicalize_nickname,
    canonicalize_refresh_token,
    canonicalize_username,
    validate_username,
)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=USERNAME_MIN_LENGTH, max_length=USERNAME_MAX_LENGTH)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    nickname: str = Field(min_length=1, max_length=NICKNAME_MAX_LENGTH)

    @field_validator("username", mode="before")
    @classmethod
    def _normalize_username(cls, value):
        if isinstance(value, str):
            return canonicalize_username(value)
        return value

    @field_validator("username")
    @classmethod
    def _validate_username(cls, value: str) -> str:
        return validate_username(value)

    @field_validator("nickname", mode="before")
    @classmethod
    def _normalize_nickname(cls, value):
        if isinstance(value, str):
            return canonicalize_nickname(value)
        return value


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=USERNAME_MIN_LENGTH, max_length=USERNAME_MAX_LENGTH)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    force: bool = False

    @field_validator("username", mode="before")
    @classmethod
    def _normalize_username(cls, value):
        if isinstance(value, str):
            return canonicalize_username(value)
        return value

    @field_validator("username")
    @classmethod
    def _validate_username(cls, value: str) -> str:
        return validate_username(value)


class RefreshTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=REFRESH_TOKEN_MIN_LENGTH, max_length=REFRESH_TOKEN_MAX_LENGTH)

    @field_validator("refresh_token", mode="before")
    @classmethod
    def _normalize_refresh_token(cls, value):
        if isinstance(value, str):
            return canonicalize_refresh_token(value)
        return value


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = TOKEN_TYPE_BEARER
