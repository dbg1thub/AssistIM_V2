"""Rate limit boundary with pluggable stores."""

from __future__ import annotations

import inspect
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth_contract import canonicalize_username
from app.core.config import Settings
from app.core.database import get_engine
from app.core.errors import AppError, ErrorCode


class RateLimitStore(ABC):
    """Abstract counter store for fixed-window rate limiting."""

    @abstractmethod
    def allow(self, key: str, *, limit: int, window_seconds: int, now: float) -> bool:
        """Record one hit and return whether the request is still allowed."""

    @abstractmethod
    def reset(self) -> None:
        """Clear all runtime state."""


class InMemoryRateLimitStore(RateLimitStore):
    """Single-process fixed-window counters."""

    def __init__(self) -> None:
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, limit: int, window_seconds: int, now: float) -> bool:
        bucket = self._buckets[key]

        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()

        if len(bucket) >= limit:
            return False

        bucket.append(now)
        return True

    def reset(self) -> None:
        self._buckets.clear()


class DatabaseRateLimitStore(RateLimitStore):
    """Database-backed fixed-window counters shared by app instances using one database."""

    def __init__(self, engine_factory: Callable = get_engine) -> None:
        self._engine_factory = engine_factory
        self._initialized = False

    def _ensure_table(self) -> None:
        if self._initialized:
            return
        engine = self._engine_factory()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS rate_limit_hits ("
                    "key VARCHAR(255) NOT NULL, "
                    "hit_at FLOAT NOT NULL"
                    ")"
                )
            )
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS idx_rate_limit_hits_key_hit_at ON rate_limit_hits (key, hit_at)")
            )
        self._initialized = True

    def allow(self, key: str, *, limit: int, window_seconds: int, now: float) -> bool:
        self._ensure_table()
        cutoff = now - window_seconds
        engine = self._engine_factory()
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM rate_limit_hits WHERE key = :key AND hit_at <= :cutoff"), {"key": key, "cutoff": cutoff})
            count = int(
                connection.execute(
                    text("SELECT COUNT(*) FROM rate_limit_hits WHERE key = :key"),
                    {"key": key},
                ).scalar_one()
            )
            if count >= limit:
                return False
            connection.execute(text("INSERT INTO rate_limit_hits (key, hit_at) VALUES (:key, :hit_at)"), {"key": key, "hit_at": now})
            return True

    def reset(self) -> None:
        try:
            self._ensure_table()
            engine = self._engine_factory()
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM rate_limit_hits"))
        except SQLAlchemyError:
            self._initialized = False


class RateLimiter:
    """Fixed-window rate limiter backed by a replaceable store."""

    _SUBJECT_FIELDS_BY_PREFIX = {
        "login": ("username",),
        "register": ("username",),
        "friend-request": ("target_user_id", "receiver_id", "user_id"),
    }

    def __init__(self, store: RateLimitStore | None = None) -> None:
        self._store = store or InMemoryRateLimitStore()
        self._configured_backend = "custom" if store is not None else "memory"

    @property
    def store(self) -> RateLimitStore:
        """Return the underlying store implementation."""
        return self._store

    def configure_from_settings(self, settings: Settings) -> None:
        backend = str(settings.rate_limit_store_backend or "database").strip().lower()
        if backend == self._configured_backend:
            return
        if backend == "database":
            self._store = DatabaseRateLimitStore()
        elif backend == "memory":
            self._store = InMemoryRateLimitStore()
        else:
            raise RuntimeError(f"unsupported rate limit store backend: {backend}")
        self._configured_backend = backend

    async def _request_subject(self, request: Request, key_prefix: str) -> str:
        fields = self._SUBJECT_FIELDS_BY_PREFIX.get(key_prefix, ())
        if not fields or not hasattr(request, "json"):
            return "anonymous"
        try:
            payload = await request.json()
        except Exception:
            return "anonymous"
        if not isinstance(payload, dict):
            return "anonymous"
        for field_name in fields:
            value = str(payload.get(field_name, "") or "").strip()
            if not value:
                continue
            if field_name == "username":
                return canonicalize_username(value) or "anonymous"
            return value.lower()
        return "anonymous"

    async def _enforce_request(
        self,
        request: Request,
        *,
        key_prefix: str,
        limit: int,
        window_seconds: int,
    ) -> None:
        client_host = request.client.host if request.client else "unknown"
        subject = await self._request_subject(request, key_prefix)
        key = f"{key_prefix}:{client_host}:{subject}"
        now = time.time()
        allowed = self._store.allow(
            key,
            limit=max(1, int(limit)),
            window_seconds=window_seconds,
            now=now,
        )

        if not allowed:
            raise AppError(
                code=ErrorCode.RATE_LIMITED,
                message="rate limit exceeded",
                status_code=429,
            )

    def dependency(self, key_prefix: str, limit: int, window_seconds: int = 60) -> Callable:
        """Return one FastAPI dependency enforcing a fixed limit."""

        async def enforce(request: Request) -> None:
            await self._enforce_request(
                request,
                key_prefix=key_prefix,
                limit=limit,
                window_seconds=window_seconds,
            )

        return enforce

    def dynamic_dependency(
        self,
        key_prefix: str,
        limit_factory: Callable[..., int],
        window_seconds: int = 60,
    ) -> Callable:
        """Return one FastAPI dependency that reads the current limit lazily."""
        try:
            takes_request = len(inspect.signature(limit_factory).parameters) > 0
        except (TypeError, ValueError):
            takes_request = False

        async def enforce(request: Request) -> None:
            limit = limit_factory(request) if takes_request else limit_factory()
            await self._enforce_request(
                request,
                key_prefix=key_prefix,
                limit=limit,
                window_seconds=window_seconds,
            )

        return enforce

    def reset(self) -> None:
        """Reset the runtime store state."""
        self._store.reset()


rate_limiter = RateLimiter()
