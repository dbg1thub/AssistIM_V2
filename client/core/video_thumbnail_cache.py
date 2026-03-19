"""Video thumbnail cache with background generation."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QPixmap

from client.core import logging


logger = logging.get_logger(__name__)


class VideoThumbnailSignals(QObject):
    """Signals emitted when cached thumbnails change."""

    thumbnail_ready = Signal(str)


class VideoThumbnailGenerator(QThread):
    """Generate a thumbnail file in the background."""

    thumbnail_ready = Signal(str)
    thumbnail_failed = Signal(str)

    def __init__(self, video_url: str, cache_path: Path, parent=None):
        super().__init__(parent)
        self._video_url = video_url
        self._cache_path = cache_path

    def run(self) -> None:
        try:
            if self._generate_with_ffmpeg(self._video_url, self._cache_path):
                self.thumbnail_ready.emit(self._video_url)
                return
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Thumbnail generation error for %s: %s", self._video_url, exc)

        self.thumbnail_failed.emit(self._video_url)

    @staticmethod
    def _generate_with_ffmpeg(video_url: str, cache_path: Path) -> bool:
        if not video_url or video_url.startswith(("http://", "https://")):
            return False

        cache_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    "00:00:01",
                    "-i",
                    video_url,
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=480:-2",
                    str(cache_path),
                ],
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return False

        return result.returncode == 0 and cache_path.exists()


class VideoThumbnailCache:
    """In-memory and disk thumbnail cache."""

    MAX_CACHE_SIZE = 50

    def __init__(self):
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._pending: dict[str, VideoThumbnailGenerator] = {}
        self.signals = VideoThumbnailSignals()
        self._cache_dir = Path("data") / "video_thumbnail"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cache_path(self, url: str) -> Path:
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{url_hash}.jpg"

    def get_thumbnail(self, video_url: str) -> Optional[QPixmap]:
        """Return cached thumbnail only. Never generate synchronously."""
        if not video_url:
            return None

        cached = self._cache.get(video_url)
        if cached is not None:
            self._cache.move_to_end(video_url)
            return cached

        cache_path = self.get_cache_path(video_url)
        if not cache_path.exists():
            return None

        pixmap = QPixmap(str(cache_path))
        if pixmap.isNull():
            return None

        self._cache[video_url] = pixmap
        self._evict_if_needed()
        return pixmap

    def request_thumbnail(self, video_url: str) -> None:
        """Generate a thumbnail in the background if not already cached."""
        if not video_url or video_url in self._pending:
            return
        if video_url.startswith(("http://", "https://")):
            return
        if self.get_thumbnail(video_url) is not None:
            return

        worker = VideoThumbnailGenerator(video_url, self.get_cache_path(video_url))
        worker.thumbnail_ready.connect(self._on_thumbnail_ready)
        worker.thumbnail_failed.connect(self._on_thumbnail_failed)
        self._pending[video_url] = worker
        worker.start()

    def _on_thumbnail_ready(self, video_url: str) -> None:
        worker = self._pending.pop(video_url, None)
        if worker is not None:
            worker.deleteLater()

        if self.get_thumbnail(video_url) is not None:
            self.signals.thumbnail_ready.emit(video_url)

    def _on_thumbnail_failed(self, video_url: str) -> None:
        worker = self._pending.pop(video_url, None)
        if worker is not None:
            worker.deleteLater()

    def _evict_if_needed(self) -> None:
        while len(self._cache) > self.MAX_CACHE_SIZE:
            self._cache.popitem(last=False)

    def clear(self) -> None:
        self._cache.clear()

    def clear_disk_cache(self) -> None:
        if self._cache_dir.exists():
            shutil.rmtree(self._cache_dir)
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache.clear()


_video_thumbnail_cache: Optional[VideoThumbnailCache] = None


def get_video_thumbnail_cache() -> VideoThumbnailCache:
    global _video_thumbnail_cache
    if _video_thumbnail_cache is None:
        _video_thumbnail_cache = VideoThumbnailCache()
    return _video_thumbnail_cache


def get_thumbnail(video_url: str) -> Optional[QPixmap]:
    return get_video_thumbnail_cache().get_thumbnail(video_url)
