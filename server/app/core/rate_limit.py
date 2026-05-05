"""Rate limit boundary with pluggable stores."""

from __future__ import annotations

import inspect
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import inspect as sqlalchemy_inspect
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

    def diagnostics(
        self,
        *,
        now: float,
        max_window_seconds: int,
        bucket_limit: int,
    ) -> dict:
        """Return a read-only runtime diagnostics snapshot when supported."""
        _ = now, max_window_seconds, bucket_limit
        return {
            "supported": False,
            "status": "unsupported",
            "scope": "unknown",
            "bucket_count": 0,
            "hit_count": 0,
            "active_hit_count": 0,
            "stale_hit_count": 0,
            "buckets": [],
        }


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

    def diagnostics(
        self,
        *,
        now: float,
        max_window_seconds: int,
        bucket_limit: int,
    ) -> dict:
        cutoff = float(now) - max(1, int(max_window_seconds or 1))
        buckets = [
            _bucket_diagnostics(key, list(timestamps), cutoff=cutoff)
            for key, timestamps in sorted(self._buckets.items())
        ]
        return _store_diagnostics_payload(
            supported=True,
            status="ok",
            scope="process",
            bucket_count=len(buckets),
            buckets=buckets,
            bucket_limit=bucket_limit,
            table_exists=None,
            error="",
        )


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

    def diagnostics(
        self,
        *,
        now: float,
        max_window_seconds: int,
        bucket_limit: int,
    ) -> dict:
        cutoff = float(now) - max(1, int(max_window_seconds or 1))
        try:
            engine = self._engine_factory()
            table_exists = "rate_limit_hits" in set(sqlalchemy_inspect(engine).get_table_names())
            if not table_exists:
                return _store_diagnostics_payload(
                    supported=True,
                    status="ok",
                    scope="database",
                    bucket_count=0,
                    buckets=[],
                    bucket_limit=bucket_limit,
                    table_exists=False,
                    error="",
                )
            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT key, COUNT(*) AS hit_count, "
                        "SUM(CASE WHEN hit_at >= :cutoff THEN 1 ELSE 0 END) AS active_hit_count, "
                        "SUM(CASE WHEN hit_at < :cutoff THEN 1 ELSE 0 END) AS stale_hit_count, "
                        "MIN(hit_at) AS oldest_hit_at, MAX(hit_at) AS newest_hit_at "
                        "FROM rate_limit_hits GROUP BY key "
                        "ORDER BY active_hit_count DESC, key ASC LIMIT :bucket_limit"
                    ),
                    {"cutoff": cutoff, "bucket_limit": max(1, int(bucket_limit or 1))},
                ).mappings().all()
                all_count_row = connection.execute(
                    text(
                        "SELECT COUNT(DISTINCT key) AS bucket_count, COUNT(*) AS hit_count, "
                        "SUM(CASE WHEN hit_at >= :cutoff THEN 1 ELSE 0 END) AS active_hit_count, "
                        "SUM(CASE WHEN hit_at < :cutoff THEN 1 ELSE 0 END) AS stale_hit_count "
                        "FROM rate_limit_hits"
                    ),
                    {"cutoff": cutoff},
                ).mappings().one()
            buckets = [
                {
                    "key": str(row["key"] or ""),
                    "key_prefix": _key_prefix(str(row["key"] or "")),
                    "hit_count": int(row["hit_count"] or 0),
                    "active_hit_count": int(row["active_hit_count"] or 0),
                    "stale_hit_count": int(row["stale_hit_count"] or 0),
                    "oldest_hit_at": _iso_from_timestamp(row["oldest_hit_at"]),
                    "newest_hit_at": _iso_from_timestamp(row["newest_hit_at"]),
                }
                for row in rows
            ]
            return {
                "supported": True,
                "status": "ok",
                "scope": "database",
                "table_exists": True,
                "bucket_count": int(all_count_row["bucket_count"] or 0),
                "hit_count": int(all_count_row["hit_count"] or 0),
                "active_hit_count": int(all_count_row["active_hit_count"] or 0),
                "stale_hit_count": int(all_count_row["stale_hit_count"] or 0),
                "buckets": buckets,
                "bucket_sample_limit": max(1, int(bucket_limit or 1)),
            }
        except SQLAlchemyError as exc:
            return _store_diagnostics_payload(
                supported=True,
                status="error",
                scope="database",
                bucket_count=0,
                buckets=[],
                bucket_limit=bucket_limit,
                table_exists=None,
                error=type(exc).__name__,
            )


class RateLimiter:
    """Fixed-window rate limiter backed by a replaceable store."""

    _SUBJECT_FIELDS_BY_PREFIX = {
        "login": ("username",),
        "register": ("username",),
        "email-verification": ("email",),
        "friend-request": ("target_user_id",),
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

    def diagnostics(
        self,
        *,
        settings: Settings | None = None,
        now: float | None = None,
        bucket_limit: int = 100,
    ) -> dict:
        """Return a read-only snapshot for admin diagnostics."""
        current_now = time.time() if now is None else float(now)
        limits = self._limit_config(settings)
        max_window_seconds = max(item["window_seconds"] for item in limits.values())
        normalized_bucket_limit = min(500, max(1, int(bucket_limit or 100)))
        return {
            "backend": {
                "configured": self._configured_backend,
                "active_store": type(self._store).__name__,
            },
            "limits": limits,
            "store": self._store.diagnostics(
                now=current_now,
                max_window_seconds=max_window_seconds,
                bucket_limit=normalized_bucket_limit,
            ),
        }

    def _limit_config(self, settings: Settings | None) -> dict[str, dict[str, int]]:
        return {
            "login": {
                "limit": max(1, int(getattr(settings, "rate_limit_login", 5) if settings else 5)),
                "window_seconds": 60,
            },
            "register": {
                "limit": max(1, int(getattr(settings, "rate_limit_register", 3) if settings else 3)),
                "window_seconds": 60,
            },
            "email-verification": {
                "limit": max(1, int(getattr(settings, "rate_limit_email_verification", 5) if settings else 5)),
                "window_seconds": 60,
            },
            "friend-request": {
                "limit": max(1, int(getattr(settings, "rate_limit_friend_request", 10) if settings else 10)),
                "window_seconds": 60,
            },
        }


def _key_prefix(key: str) -> str:
    return str(key or "").split(":", 1)[0]


def _iso_from_timestamp(value: object) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _bucket_diagnostics(key: str, timestamps: list[float], *, cutoff: float) -> dict:
    active_hit_count = sum(1 for timestamp in timestamps if float(timestamp) >= cutoff)
    stale_hit_count = len(timestamps) - active_hit_count
    return {
        "key": str(key or ""),
        "key_prefix": _key_prefix(key),
        "hit_count": len(timestamps),
        "active_hit_count": active_hit_count,
        "stale_hit_count": stale_hit_count,
        "oldest_hit_at": _iso_from_timestamp(min(timestamps) if timestamps else None),
        "newest_hit_at": _iso_from_timestamp(max(timestamps) if timestamps else None),
    }


def _store_diagnostics_payload(
    *,
    supported: bool,
    status: str,
    scope: str,
    bucket_count: int,
    buckets: list[dict],
    bucket_limit: int,
    table_exists: bool | None,
    error: str,
) -> dict:
    hit_count = sum(int(item.get("hit_count", 0) or 0) for item in buckets)
    active_hit_count = sum(int(item.get("active_hit_count", 0) or 0) for item in buckets)
    stale_hit_count = sum(int(item.get("stale_hit_count", 0) or 0) for item in buckets)
    payload = {
        "supported": supported,
        "status": status,
        "scope": scope,
        "bucket_count": int(bucket_count or 0),
        "hit_count": hit_count,
        "active_hit_count": active_hit_count,
        "stale_hit_count": stale_hit_count,
        "buckets": sorted(
            buckets,
            key=lambda item: (-int(item.get("active_hit_count", 0) or 0), str(item.get("key") or "")),
        )[: max(1, int(bucket_limit or 1))],
        "bucket_sample_limit": max(1, int(bucket_limit or 1)),
    }
    if table_exists is not None:
        payload["table_exists"] = table_exists
    if error:
        payload["error"] = error
    return payload


rate_limiter = RateLimiter()
