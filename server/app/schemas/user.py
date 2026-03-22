"""User schemas."""

from __future__ import annotations

import re
from datetime import date
from typing import ClassVar

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel


class UserOut(ORMModel):
    id: str
    username: str
    nickname: str
    avatar: str | None = None
    email: str | None = None
    phone: str | None = None
    birthday: date | None = None
    region: str | None = None
    signature: str | None = None
    gender: str | None = None
    status: str


class UserUpdateRequest(BaseModel):
    _EMAIL_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    _PHONE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"^\+?[0-9][0-9()\-\.\s]{5,31}$")
    _GENDER_VALUES: ClassVar[set[str]] = {"female", "male", "non_binary", "other"}
    _STATUS_VALUES: ClassVar[set[str]] = {"online", "busy", "away", "invisible", "offline"}

    nickname: str | None = Field(default=None, min_length=1, max_length=64)
    avatar: str | None = Field(default=None, max_length=512)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    birthday: date | None = None
    region: str | None = Field(default=None, max_length=128)
    signature: str | None = Field(default=None, max_length=255)
    gender: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=32)

    @field_validator("nickname", "avatar", "email", "phone", "region", "signature", "gender", "status", mode="before")
    @classmethod
    def _strip_string_fields(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("avatar", "email", "phone", "region", "signature", "gender", mode="before")
    @classmethod
    def _empty_string_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("birthday", mode="before")
    @classmethod
    def _empty_birthday_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not cls._EMAIL_PATTERN.fullmatch(value):
            raise ValueError("invalid email format")
        return value

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not cls._PHONE_PATTERN.fullmatch(value):
            raise ValueError("invalid phone format")
        return value

    @field_validator("gender")
    @classmethod
    def _validate_gender(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.lower()
        if normalized not in cls._GENDER_VALUES:
            raise ValueError("invalid gender value")
        return normalized

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.lower()
        if normalized not in cls._STATUS_VALUES:
            raise ValueError("invalid status value")
        return normalized
