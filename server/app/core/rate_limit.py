"""Rate limit boundary with one in-memory default backend."""

from __future__ import annotations

import inspect
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request

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


class RateLimiter:
    """Fixed-window rate limiter backed by a replaceable store."""

    def __init__(self, store: RateLimitStore | None = None) -> None:
        self._store = store or InMemoryRateLimitStore()

    @property
    def store(self) -> RateLimitStore:
        """Return the underlying store implementation."""
        return self._store

    async def _enforce_request(
        self,
        request: Request,
        *,
        key_prefix: str,
        limit: int,
        window_seconds: int,
    ) -> None:
        client_host = request.client.host if request.client else "unknown"
        key = f"{key_prefix}:{client_host}"
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
