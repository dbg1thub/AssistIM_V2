"""Small in-memory rate limiter for sensitive endpoints."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request

from app.core.errors import AppError, ErrorCode


class RateLimiter:
    """Simple fixed-window rate limiter."""

    def __init__(self) -> None:
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def dependency(self, key_prefix: str, limit: int, window_seconds: int = 60) -> Callable:
        """Return a FastAPI dependency enforcing the limit."""

        async def enforce(request: Request) -> None:
            client_host = request.client.host if request.client else "unknown"
            key = f"{key_prefix}:{client_host}"
            now = time.time()
            bucket = self._buckets[key]

            while bucket and now - bucket[0] > window_seconds:
                bucket.popleft()

            if len(bucket) >= limit:
                raise AppError(
                    code=ErrorCode.RATE_LIMITED,
                    message="rate limit exceeded",
                    status_code=429,
                )

            bucket.append(now)

        return enforce


rate_limiter = RateLimiter()
