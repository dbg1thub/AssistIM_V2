"""Schemas for device registration and prekey APIs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SignedPreKeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_id: int = Field(ge=1)
    public_key: str = Field(min_length=32, max_length=256)
    signature: str = Field(min_length=64, max_length=512)


class OneTimePreKeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prekey_id: int = Field(ge=1)
    public_key: str = Field(min_length=32, max_length=256)


class DeviceRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=3, max_length=64)
    device_name: str = Field(default="AssistIM Desktop", min_length=1, max_length=128)
    identity_key_public: str = Field(min_length=32, max_length=256)
    signing_key_public: str = Field(min_length=32, max_length=256)
    signed_prekey: SignedPreKeyIn
    prekeys: list[OneTimePreKeyIn] = Field(min_length=1, max_length=100)


class DeviceKeysRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signed_prekey: SignedPreKeyIn | None = None
    prekeys: list[OneTimePreKeyIn] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _require_key_material(self) -> "DeviceKeysRefreshRequest":
        if self.signed_prekey is None and not self.prekeys:
            raise ValueError("signed_prekey or prekeys is required")
        return self


class DeviceOut(BaseModel):
    device_id: str
    user_id: str
    device_name: str
    identity_key_public: str
    signing_key_public: str
    is_active: bool
    available_prekey_count: int
    created_at: str | None = None
    updated_at: str | None = None
    last_seen_at: str | None = None


class SignedPreKeyOut(BaseModel):
    key_id: int
    public_key: str
    signature: str


class OneTimePreKeyOut(BaseModel):
    prekey_id: int
    public_key: str


class PreKeyBundleOut(BaseModel):
    device_id: str
    user_id: str
    device_name: str
    identity_key_public: str
    signing_key_public: str
    signed_prekey: SignedPreKeyOut
    one_time_prekey: OneTimePreKeyOut | None = None
    available_prekey_count: int
    last_seen_at: str | None = None


class PreKeyClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_ids: list[str] = Field(min_length=1, max_length=50)

    @field_validator("device_ids", mode="before")
    @classmethod
    def _normalize_device_ids(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return value
        normalized: list[str] = []
        for raw_item in value:
            device_id = str(raw_item or "").strip()
            if device_id and device_id not in normalized:
                normalized.append(device_id)
        return normalized
