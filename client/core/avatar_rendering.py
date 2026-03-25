"""Shared avatar rendering helpers with cached remote-image loading."""

from __future__ import annotations

import time
import weakref
from pathlib import Path

from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from client.core.avatar_utils import default_avatar_path, resolve_avatar_source
from client.core.image_cache import get_image_cache


_REMOTE_PREFIXES = ("http://", "https://")
_WIDGET_SOURCE_ATTR = "_assistim_avatar_source"
_WIDGET_GENDER_ATTR = "_assistim_avatar_gender"
_WIDGET_SEED_ATTR = "_assistim_avatar_seed"
_WIDGET_BOUND_ATTR = "_assistim_avatar_bound"
_WIDGET_LISTENER_ATTR = "_assistim_avatar_listener"


def is_remote_avatar_source(value: object) -> bool:
    """Return whether one avatar source points to a remote image URL."""
    text = str(value or "").strip()
    return text.startswith(_REMOTE_PREFIXES)


class AvatarImageStore(QObject):
    """Resolve avatar display paths and download remote avatars into the local cache."""

    avatar_ready = Signal(str)
    REMOTE_RETRY_COOLDOWN_SECONDS = 15.0

    def __init__(self) -> None:
        super().__init__()
        self._cache = get_image_cache()
        self._network_manager = QNetworkAccessManager(self)
        self._pending_urls: set[str] = set()
        self._failed_urls: dict[str, float] = {}

    def resolve_display_path(self, avatar: object = "", *, gender: object = "", seed: object = "") -> tuple[str, str]:
        """Return the canonical avatar source together with a currently renderable local path."""
        source = resolve_avatar_source(avatar, gender=gender, seed=seed)
        return source, self.display_path_for_source(source, gender=gender, seed=seed)

    def display_path_for_source(self, source: object = "", *, gender: object = "", seed: object = "") -> str:
        """Return one local path for the avatar source, kicking off remote downloads when needed."""
        fallback_path = default_avatar_path(gender=gender, seed=seed)
        text = str(source or "").strip()
        if not text:
            return fallback_path

        if is_remote_avatar_source(text):
            cached_pixmap = self._cache.load_image(text)
            cache_path = self._cache.get_cache_path(text)
            if cached_pixmap is not None and cache_path.exists():
                return str(cache_path)
            self._ensure_remote_download(text)
            return fallback_path

        candidate = Path(text)
        if candidate.is_file():
            return str(candidate)
        return fallback_path

    def _ensure_remote_download(self, url: str) -> None:
        if not url or url in self._pending_urls:
            return

        failed_at = self._failed_urls.get(url, 0.0)
        if failed_at and (time.time() - failed_at) < self.REMOTE_RETRY_COOLDOWN_SECONDS:
            return

        self._pending_urls.add(url)
        request = QNetworkRequest(QUrl(url))
        reply = self._network_manager.get(request)
        reply.finished.connect(lambda url=url, reply=reply: self._finalize_remote_download(url, reply))

    def _finalize_remote_download(self, url: str, reply) -> None:
        self._pending_urls.discard(url)
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._failed_urls[url] = time.time()
                return

            pixmap = QPixmap()
            payload = bytes(reply.readAll())
            if not payload or not pixmap.loadFromData(payload):
                self._failed_urls[url] = time.time()
                return

            self._cache.put(url, pixmap)
            self._failed_urls.pop(url, None)
            self.avatar_ready.emit(url)
        finally:
            reply.deleteLater()


_avatar_image_store: AvatarImageStore | None = None


def get_avatar_image_store() -> AvatarImageStore:
    """Return the shared avatar image store."""
    global _avatar_image_store
    if _avatar_image_store is None:
        _avatar_image_store = AvatarImageStore()
    return _avatar_image_store


def apply_avatar_widget_image(widget, avatar: object = "", *, gender: object = "", seed: object = "") -> bool:
    """Apply one avatar path to an AvatarWidget-like object and keep remote URLs refreshed."""
    store = get_avatar_image_store()
    source, display_path = store.resolve_display_path(avatar, gender=gender, seed=seed)

    setattr(widget, _WIDGET_SOURCE_ATTR, source)
    setattr(widget, _WIDGET_GENDER_ATTR, str(gender or ""))
    setattr(widget, _WIDGET_SEED_ATTR, str(seed or ""))
    _ensure_widget_avatar_binding(widget)

    if not display_path:
        return False

    if hasattr(widget, "setText"):
        widget.setText("")
    widget.setImage(display_path)
    return True


def _ensure_widget_avatar_binding(widget) -> None:
    if getattr(widget, _WIDGET_BOUND_ATTR, False):
        return

    store = get_avatar_image_store()
    widget_ref = weakref.ref(widget)

    def _handle_avatar_ready(source: str) -> None:
        target = widget_ref()
        if target is None:
            return
        if str(getattr(target, _WIDGET_SOURCE_ATTR, "") or "") != source:
            return

        display_path = store.display_path_for_source(
            source,
            gender=getattr(target, _WIDGET_GENDER_ATTR, ""),
            seed=getattr(target, _WIDGET_SEED_ATTR, ""),
        )
        if not display_path:
            return

        if hasattr(target, "setText"):
            target.setText("")
        target.setImage(display_path)
        if hasattr(target, "update"):
            target.update()

    store.avatar_ready.connect(_handle_avatar_ready)
    setattr(widget, _WIDGET_BOUND_ATTR, True)
    setattr(widget, _WIDGET_LISTENER_ATTR, _handle_avatar_ready)
