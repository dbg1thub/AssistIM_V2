"""
Image Cache Module

LRU cache for images with local file storage.
"""
import os
import shutil
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from client.core import logging
from client.core.logging import setup_logging
from client.core.config_backend import get_config


setup_logging()
logger = logging.get_logger(__name__)


class ImageCache:
    """
    LRU image cache with local file storage.

    Features:
        - LRU cache (max 100 images)
        - Local file storage in data/image_cache/
        - Async download for remote images
    """

    MAX_CACHE_SIZE = 100
    CACHE_DIR = "data/image_cache"

    def __init__(self):
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._config = get_config()

        # Setup cache directory
        cache_dir = self._config.storage.db_path
        self._cache_dir = Path(cache_dir).parent / self.CACHE_DIR
        self._cache_dir = Path(str(self._cache_dir).replace("data/", ""))
        self._cache_dir = Path("data") / "image_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"ImageCache initialized: {self._cache_dir}")

    def get_cache_path(self, url: str) -> Path:
        """Get local cache file path for URL."""
        # Generate filename from URL hash
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()

        # Get extension from URL
        ext = ".jpg"
        if "." in url:
            url_ext = url.rsplit(".", 1)[-1].lower()
            if url_ext in ["png", "jpg", "jpeg", "gif", "webp", "bmp"]:
                ext = f".{url_ext}"

        return self._cache_dir / f"{url_hash}{ext}"

    def load_image(self, url: str) -> Optional[QPixmap]:
        """
        Load image from cache or file.

        Args:
            url: Image URL or file path

        Returns:
            QPixmap or None
        """
        # Check if it's a local file
        if not url.startswith("http://") and not url.startswith("https://"):
            pixmap = QPixmap(url)
            return pixmap if not pixmap.isNull() else None

        # Check memory cache
        if url in self._cache:
            # Move to end (most recently used)
            self._cache.move_to_end(url)
            return self._cache[url]

        # Check local file cache
        cache_path = self.get_cache_path(url)
        if cache_path.exists():
            pixmap = QPixmap(str(cache_path))
            if not pixmap.isNull():
                # Add to memory cache
                self._cache[url] = pixmap
                self._evict_if_needed()
                logger.debug(f"Loaded from file cache: {url}")
                return pixmap

        return None

    def get_cached(self, url: str) -> Optional[QPixmap]:
        """
        Get cached image without loading from disk.

        Args:
            url: Image URL

        Returns:
            QPixmap or None if not cached
        """
        return self._cache.get(url)

    def put(self, url: str, pixmap: QPixmap) -> None:
        """
        Add image to cache.

        Args:
            url: Image URL
            pixmap: Image pixmap
        """
        if url in self._cache:
            self._cache.move_to_end(url)
            return

        # Add to memory cache
        self._cache[url] = pixmap
        self._evict_if_needed()

        # Save to local file
        cache_path = self.get_cache_path(url)
        pixmap.save(str(cache_path))

        logger.debug(f"Cached image: {url}")

    def _evict_if_needed(self) -> None:
        """Evict oldest item if cache is full."""
        while len(self._cache) > self.MAX_CACHE_SIZE:
            oldest_url, _ = self._cache.popitem(last=False)
            logger.debug(f"Evicted from cache: {oldest_url}")

    def clear(self) -> None:
        """Clear memory cache."""
        self._cache.clear()
        logger.info("Image cache cleared")

    def clear_disk_cache(self) -> None:
        """Clear disk cache."""
        if self._cache_dir.exists():
            shutil.rmtree(self._cache_dir)
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache.clear()
        logger.info("Disk cache cleared")


class ImageDownloader(QThread):
    """
    Background thread for downloading images.
    """

    download_complete = Signal(str, QPixmap)
    download_failed = Signal(str)

    def __init__(self, url: str, cache: ImageCache, parent=None):
        super().__init__(parent)
        self._url = url
        self._cache = cache
        self._network_manager = QNetworkAccessManager()

    def run(self) -> None:
        """Download image in background."""
        try:
            request = QNetworkRequest(self._url)
            reply = self._network_manager.get(request)

            # Wait for download
            loop = __import__("asyncio").get_event_loop()
            future = loop.run_in_executor(None, self._wait_for_reply, reply)
            loop.run_until_complete(future)

            if reply.error() == QNetworkReply.NetworkError.NoError:
                data = reply.readAll()
                pixmap = QPixmap()
                if pixmap.loadFromData(data):
                    # Save to cache
                    self._cache.put(self._url, pixmap)
                    self.download_complete.emit(self._url, pixmap)
                    return

            self.download_failed.emit(self._url)

        except Exception as e:
            logger.error(f"Image download error: {e}")
            self.download_failed.emit(self._url)

    def _wait_for_reply(self, reply: QNetworkReply) -> None:
        """Wait for network reply."""
        import time
        while reply.isRunning():
            time.sleep(0.1)


# Global instance
_image_cache: Optional[ImageCache] = None


def get_image_cache() -> ImageCache:
    """Get the global image cache instance."""
    global _image_cache
    if _image_cache is None:
        _image_cache = ImageCache()
    return _image_cache
