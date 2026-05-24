from __future__ import annotations

import hashlib
from pathlib import Path

from client.core.moment_video_cache import MomentVideoCache


def test_moment_video_cache_path_is_hashed_and_keeps_video_suffix(tmp_path: Path) -> None:
    source = "http://localhost:8000/uploads/2026/05/demo-video.mp4?download=1"
    cache = MomentVideoCache(tmp_path)

    cache_path = cache.get_cache_path(source)

    expected_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    assert cache_path.parent == tmp_path
    assert cache_path.name == f"{expected_hash}.mp4"


def test_moment_video_cache_uses_original_name_suffix_when_url_has_none(tmp_path: Path) -> None:
    cache = MomentVideoCache(tmp_path)

    cache_path = cache.get_cache_path(
        "http://localhost:8000/uploads/opaque-storage-key",
        original_name="clip.webm",
    )

    assert cache_path.suffix == ".webm"
