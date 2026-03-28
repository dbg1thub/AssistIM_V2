"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _env_str(name: str, default: str) -> str:
    """Read one string setting from the environment."""
    return os.getenv(name, default)


def _env_bool(name: str, default: bool) -> bool:
    """Read one boolean setting from the environment."""
    fallback = "true" if default else "false"
    return os.getenv(name, fallback).lower() == "true"


def _env_int(name: str, default: int) -> int:
    """Read one integer setting from the environment."""
    return int(os.getenv(name, str(default)))


def _env_csv(name: str, default: str) -> tuple[str, ...]:
    """Read one comma-separated setting from the environment."""
    return tuple(
        item.strip()
        for item in os.getenv(name, default).split(",")
        if item.strip()
    )


@dataclass(slots=True)
class Settings:
    app_name: str = field(default_factory=lambda: _env_str("APP_NAME", "AssistIM API"))
    app_version: str = field(default_factory=lambda: _env_str("APP_VERSION", "1.0"))
    debug: bool = field(default_factory=lambda: _env_bool("DEBUG", False))

    database_url: str = field(
        default_factory=lambda: _env_str(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/assistim",
        )
    )
    secret_key: str = field(
        default_factory=lambda: _env_str(
            "SECRET_KEY",
            "assistim-dev-secret-change-me",
        )
    )
    access_token_expire_minutes: int = field(default_factory=lambda: _env_int("ACCESS_TOKEN_EXPIRE", 60))
    refresh_token_expire_days: int = field(default_factory=lambda: _env_int("REFRESH_TOKEN_EXPIRE_DAYS", 7))

    upload_dir: str = field(default_factory=lambda: _env_str("UPLOAD_DIR", "data/uploads"))
    media_storage_backend: str = field(default_factory=lambda: _env_str("MEDIA_STORAGE_BACKEND", "local"))
    media_public_base_url: str = field(default_factory=lambda: _env_str("MEDIA_PUBLIC_BASE_URL", "/uploads"))
    max_upload_bytes: int = field(default_factory=lambda: _env_int("MAX_UPLOAD_BYTES", 25 * 1024 * 1024))
    api_v1_prefix: str = field(default_factory=lambda: _env_str("API_V1_PREFIX", "/api/v1"))
    cors_origins: tuple[str, ...] = field(default_factory=lambda: _env_csv("CORS_ORIGINS", "*"))
    rate_limit_login: int = field(default_factory=lambda: _env_int("RATE_LIMIT_LOGIN", 5))
    rate_limit_register: int = field(default_factory=lambda: _env_int("RATE_LIMIT_REGISTER", 3))
    rate_limit_friend_request: int = field(default_factory=lambda: _env_int("RATE_LIMIT_FRIEND_REQUEST", 10))


@lru_cache
def get_settings() -> Settings:
    """Return cached settings."""
    return Settings()


def reload_settings() -> Settings:
    """Clear the settings cache and rebuild it from the current environment."""
    get_settings.cache_clear()
    return get_settings()

