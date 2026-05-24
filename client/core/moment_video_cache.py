"""Local cache for protected moments video playback and thumbnails."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from urllib.parse import unquote, urlsplit

from client.network.http_client import get_http_client


class MomentVideoCache:
    """Cache remote moments videos locally before playback or thumbnailing."""

    DEFAULT_SUFFIX = ".mp4"

    def __init__(self, cache_dir: str | Path | None = None) -> None:
        self._cache_dir = Path(cache_dir) if cache_dir is not None else Path("data") / "moment_video_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._pending: dict[tuple[str, bool], asyncio.Task[Path]] = {}

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def get_cache_path(self, source: str, *, original_name: str = "") -> Path:
        normalized_source = self._normalize_source(source)
        source_hash = hashlib.sha256(normalized_source.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{source_hash}{self._suffix_for(normalized_source, original_name)}"

    def get_cached_path(self, source: str, *, original_name: str = "") -> Path | None:
        local_path = self._existing_local_path(source)
        if local_path is not None:
            return local_path
        cache_path = self.get_cache_path(source, original_name=original_name)
        return cache_path if cache_path.exists() else None

    async def ensure_cached(self, source: str, *, original_name: str = "", use_auth: bool = False) -> Path:
        normalized_source = self._normalize_source(source)
        local_path = self._existing_local_path(normalized_source)
        if local_path is not None:
            return local_path
        if not self._is_remote_source(normalized_source):
            raise FileNotFoundError(normalized_source)

        cache_path = self.get_cache_path(normalized_source, original_name=original_name)
        if cache_path.exists():
            return cache_path

        pending_key = (normalized_source, bool(use_auth))
        task = self._pending.get(pending_key)
        if task is None:
            task = asyncio.create_task(
                self._download_to_cache(
                    normalized_source,
                    cache_path,
                    use_auth=bool(use_auth),
                )
            )
            self._pending[pending_key] = task

        try:
            return await asyncio.shield(task)
        finally:
            if task.done() and self._pending.get(pending_key) is task:
                self._pending.pop(pending_key, None)

    async def _download_to_cache(self, source: str, cache_path: Path, *, use_auth: bool) -> Path:
        payload = await get_http_client().download_bytes(source, use_auth=use_auth)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = cache_path.with_name(f"{cache_path.name}.tmp")
        temp_path.write_bytes(payload)
        temp_path.replace(cache_path)
        return cache_path

    @classmethod
    def _suffix_for(cls, source: str, original_name: str = "") -> str:
        source_suffix = Path(unquote(urlsplit(source).path)).suffix
        original_suffix = Path(str(original_name or "")).suffix
        suffix = (source_suffix or original_suffix or cls.DEFAULT_SUFFIX).lower()
        if not suffix.startswith(".") or len(suffix) > 12 or any(char in suffix for char in ("/", "\\")):
            return cls.DEFAULT_SUFFIX
        return suffix

    @staticmethod
    def _normalize_source(source: str) -> str:
        normalized = str(source or "").strip()
        if not normalized:
            raise ValueError("video source is required")
        return normalized

    @staticmethod
    def _existing_local_path(source: str) -> Path | None:
        if MomentVideoCache._is_remote_source(str(source or "")):
            return None
        path = Path(str(source or "").strip())
        return path if path.exists() else None

    @staticmethod
    def _is_remote_source(source: str) -> bool:
        return str(source or "").startswith(("http://", "https://"))


_moment_video_cache: MomentVideoCache | None = None


def get_moment_video_cache() -> MomentVideoCache:
    global _moment_video_cache
    if _moment_video_cache is None:
        _moment_video_cache = MomentVideoCache()
    return _moment_video_cache
