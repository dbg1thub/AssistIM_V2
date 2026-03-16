"""
Video Thumbnail Cache Module

Generate and cache video thumbnails.
"""
import os
import shutil
import subprocess
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal, QObject
from PySide6.QtGui import QPixmap, QImage, QImageReader
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget

from client.core import logging
from client.core.logging import setup_logging
from client.core.config_backend import get_config


setup_logging()
logger = logging.get_logger(__name__)


class VideoThumbnailCache:
    """
    Video thumbnail cache with local file storage.

    Uses QMediaPlayer to capture frame or ffmpeg as fallback.

    Features:
        - LRU cache (max 50 thumbnails)
        - Local file storage in data/video_thumbnail/
        - Async thumbnail generation
    """

    MAX_CACHE_SIZE = 50
    CACHE_DIR = "data/video_thumbnail"

    def __init__(self):
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._config = get_config()

        # Setup cache directory
        self._cache_dir = Path("data") / "video_thumbnail"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        # Check ffmpeg availability
        self._has_ffmpeg = self._check_ffmpeg()

        logger.info(f"VideoThumbnailCache initialized: {self._cache_dir}, ffmpeg: {self._has_ffmpeg}")

    def _check_ffmpeg(self) -> bool:
        """Check if ffmpeg is available."""
        try:
            subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                timeout=5
            )
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def get_cache_path(self, url: str) -> Path:
        """Get local cache file path for URL."""
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return self._cache_dir / f"{url_hash}.jpg"

    def get_thumbnail(self, video_url: str) -> Optional[QPixmap]:
        """
        Get video thumbnail from cache.

        Args:
            video_url: Video URL or file path

        Returns:
            QPixmap or None
        """
        # Check if it's a local file
        if not video_url.startswith("http://") and not video_url.startswith("https://"):
            return self._load_thumbnail_from_file(video_url)

        # Check memory cache
        if video_url in self._cache:
            self._cache.move_to_end(video_url)
            return self._cache[video_url]

        # Check local file cache
        cache_path = self.get_cache_path(video_url)
        if cache_path.exists():
            pixmap = QPixmap(str(cache_path))
            if not pixmap.isNull():
                self._cache[video_url] = pixmap
                self._evict_if_needed()
                logger.debug(f"Loaded thumbnail from cache: {video_url}")
                return pixmap

        return None

    def _load_thumbnail_from_file(self, file_path: str) -> Optional[QPixmap]:
        """Load thumbnail from local video file."""
        # Check memory cache
        if file_path in self._cache:
            self._cache.move_to_end(file_path)
            return self._cache[file_path]

        # Check disk cache
        cache_path = self.get_cache_path(file_path)
        if cache_path.exists():
            pixmap = QPixmap(str(cache_path))
            if not pixmap.isNull():
                self._cache[file_path] = pixmap
                self._evict_if_needed()
                return pixmap

        # Generate thumbnail
        pixmap = self._generate_thumbnail(file_path)
        if pixmap:
            self._cache[file_path] = pixmap
            self._evict_if_needed()
            pixmap.save(str(cache_path))

        return pixmap

    def _generate_thumbnail(self, video_path: str) -> Optional[QPixmap]:
        """Generate thumbnail from video."""
        if self._has_ffmpeg:
            return self._generate_with_ffmpeg(video_path)
        else:
            return self._generate_with_qmediaplayer(video_path)

    def _generate_with_ffmpeg(self, video_path: str) -> Optional[QPixmap]:
        """Generate thumbnail using ffmpeg."""
        cache_path = self.get_cache_path(video_path)

        try:
            # Extract frame at 1 second
            cmd = [
                "ffmpeg",
                "-y",  # Overwrite output
                "-i", video_path,
                "-ss", "00:00:01",
                "-vframes", "1",
                "-vf", "scale=320:-1",
                str(cache_path)
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=30
            )

            if result.returncode == 0 and cache_path.exists():
                pixmap = QPixmap(str(cache_path))
                if not pixmap.isNull():
                    logger.debug(f"Generated thumbnail with ffmpeg: {video_path}")
                    return pixmap

        except Exception as e:
            logger.error(f"ffmpeg error: {e}")

        return None

    def _generate_with_qmediaplayer(self, video_path: str) -> Optional[QPixmap]:
        """Generate thumbnail using QMediaPlayer."""
        try:
            from PySide6.QtCore import QEventLoop, QTimer

            player = QMediaPlayer()
            widget = QVideoWidget()

            result = {"pixmap": None, "finished": False}

            def on_position_changed(position):
                if position > 0 and not result["finished"]:
                    result["finished"] = True

                    # Capture frame
                    image = player.videoSurface().present()
                    if image and not image.isNull():
                        result["pixmap"] = QPixmap.fromImage(image)

                    player.stop()

            def on_state_changed(state):
                if state == QMediaPlayer.MediaState.StoppedState and not result["finished"]:
                    result["finished"] = True
                    # Try to capture at end
                    player.setPosition(1000)
                    player.play()

            player.positionChanged.connect(on_position_changed)
            player.stateChanged.connect(on_state_changed)

            # Load video
            player.setSource(video_path)
            player.play()

            # Wait for thumbnail
            loop = QEventLoop()
            QTimer.singleShot(3000, loop.quit)  # Timeout 3s
            loop.exec()

            player.stop()

            if result["pixmap"]:
                logger.debug(f"Generated thumbnail with QMediaPlayer: {video_path}")
                return result["pixmap"]

        except Exception as e:
            logger.error(f"QMediaPlayer error: {e}")

        return None

    def put(self, url: str, pixmap: QPixmap) -> None:
        """Add thumbnail to cache."""
        if url in self._cache:
            self._cache.move_to_end(url)
            return

        self._cache[url] = pixmap
        self._evict_if_needed()

        cache_path = self.get_cache_path(url)
        pixmap.save(str(cache_path))

        logger.debug(f"Cached thumbnail: {url}")

    def _evict_if_needed(self) -> None:
        """Evict oldest item if cache is full."""
        while len(self._cache) > self.MAX_CACHE_SIZE:
            oldest_url, _ = self._cache.popitem(last=False)
            logger.debug(f"Evicted from cache: {oldest_url}")

    def clear(self) -> None:
        """Clear memory cache."""
        self._cache.clear()
        logger.info("Video thumbnail cache cleared")

    def clear_disk_cache(self) -> None:
        """Clear disk cache."""
        if self._cache_dir.exists():
            shutil.rmtree(self._cache_dir)
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache.clear()
        logger.info("Disk thumbnail cache cleared")


class VideoThumbnailGenerator(QThread):
    """
    Background thread for generating video thumbnails.
    """

    thumbnail_ready = Signal(str, QPixmap)
    thumbnail_failed = Signal(str)

    def __init__(self, video_url: str, parent=None):
        super().__init__(parent)
        self._video_url = video_url
        self._cache = VideoThumbnailCache()

    def run(self) -> None:
        """Generate thumbnail in background."""
        try:
            pixmap = self._cache._generate_thumbnail(self._video_url)

            if pixmap:
                self._cache.put(self._video_url, pixmap)
                self.thumbnail_ready.emit(self._video_url, pixmap)
                return

            self.thumbnail_failed.emit(self._video_url)

        except Exception as e:
            logger.error(f"Thumbnail generation error: {e}")
            self.thumbnail_failed.emit(self._video_url)


# Global instance
_video_thumbnail_cache: Optional[VideoThumbnailCache] = None


def get_video_thumbnail_cache() -> VideoThumbnailCache:
    """Get the global video thumbnail cache instance."""
    global _video_thumbnail_cache
    if _video_thumbnail_cache is None:
        _video_thumbnail_cache = VideoThumbnailCache()
    return _video_thumbnail_cache


def get_thumbnail(video_url: str) -> Optional[QPixmap]:
    """Get video thumbnail."""
    cache = get_video_thumbnail_cache()
    return cache.get_thumbnail(video_url)
