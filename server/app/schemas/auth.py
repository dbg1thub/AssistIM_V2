"""Auth schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)
    nickname: str = Field(min_length=1, max_length=64)


class LoginRequest(BaseModel):
    username: str
    password: str
    force: bool = False


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
