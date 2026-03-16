"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(slots=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "AssistIM API")
    app_version: str = os.getenv("APP_VERSION", "1.0")
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"

    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/assistim",
    )
    secret_key: str = os.getenv(
        "SECRET_KEY",
        "assistim-dev-secret-change-me",
    )
    access_token_expire_minutes: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE", "60"),
    )
    refresh_token_expire_days: int = int(
        os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"),
    )

    upload_dir: str = os.getenv("UPLOAD_DIR", "data/uploads")
    api_v1_prefix: str = os.getenv("API_V1_PREFIX", "/api/v1")
    api_compat_prefix: str = os.getenv("API_COMPAT_PREFIX", "/api")
    cors_origins: list[str] = tuple(
        item.strip()
        for item in os.getenv("CORS_ORIGINS", "*").split(",")
        if item.strip()
    )
    rate_limit_login: int = int(os.getenv("RATE_LIMIT_LOGIN", "5"))
    rate_limit_register: int = int(os.getenv("RATE_LIMIT_REGISTER", "3"))
    rate_limit_friend_request: int = int(os.getenv("RATE_LIMIT_FRIEND_REQUEST", "10"))


@lru_cache
def get_settings() -> Settings:
    """Return cached settings."""
    return Settings()
