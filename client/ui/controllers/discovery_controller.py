"""Controller for moments/discovery data loading and mutations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from client.core import logging
from client.core.logging import setup_logging
from client.services.discovery_service import get_discovery_service
from client.services.user_service import get_user_service
from client.ui.controllers.auth_controller import get_auth_controller


setup_logging()
logger = logging.get_logger(__name__)


@dataclass
class MomentMediaRecord:
    """Normalized moment media attachment."""

    media_type: str
    url: str
    original_name: str = ""
    mime_type: str = ""
    size_bytes: int = 0
    local_path: str = ""

    @property
    def is_image(self) -> bool:
        return self.media_type == "image"

    @property
    def is_video(self) -> bool:
        return self.media_type == "video"


@dataclass
class MomentCommentRecord:
    """Normalized comment data."""

    id: str
    moment_id: str
    user_id: str
    content: str
    created_at: str = ""
    username: str = ""
    nickname: str = ""
    avatar: str = ""
    gender: str = ""
    image: MomentMediaRecord | None = None

    @property
    def display_name(self) -> str:
        """Return the best display name."""
        return self.nickname or self.username or self.user_id or "Unknown User"


@dataclass
class MomentRecord:
    """Normalized moment/timeline item."""

    id: str
    user_id: str
    content: str
    created_at: str = ""
    username: str = ""
    nickname: str = ""
    avatar: str = ""
    gender: str = ""
    media: list[MomentMediaRecord] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    videos: list[str] = field(default_factory=list)
    visibility_scope: str = "public"
    visibility_user_ids: list[str] = field(default_factory=list)
    comments: list[MomentCommentRecord] = field(default_factory=list)
    like_count: int = 0
    comment_count: int = 0
    is_liked: bool = False
    comments_truncated: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """Return the best display name."""
        return self.nickname or self.username or self.user_id or "Unknown User"


@dataclass
class MomentPrivacySettings:
    """Normalized moments privacy settings for the current user."""

    hide_my_moments_user_ids: list[str] = field(default_factory=list)
    hide_their_moments_user_ids: list[str] = field(default_factory=list)
    visible_time_scope: str = "all"


class DiscoveryController:
    """Provide discovery timeline data to the UI."""

    def __init__(self) -> None:
        self._discovery_service = get_discovery_service()
        self._user_service = get_user_service()
        self._auth = get_auth_controller()
        self._user_cache: dict[str, dict[str, Any]] = {}
        self._cache_owner_user_id = ""
        self._closed = False

    def _runtime_user_id(self) -> str:
        """Return the authenticated runtime user id for cache scoping."""
        current_user = self._auth.current_user or {}
        return str(current_user.get("id", "") or "").strip()

    def _clear_caches(self) -> None:
        """Drop all account-scoped discovery caches."""
        self._user_cache.clear()

    def _capture_runtime_user_id(self) -> str:
        """Capture the live account id for one discovery task."""
        if self._closed:
            raise asyncio.CancelledError
        user_id = self._runtime_user_id()
        if not user_id:
            raise asyncio.CancelledError
        return user_id

    def _ensure_runtime_user_id(self, expected_user_id: str) -> None:
        """Reject late discovery results after logout or relogin."""
        if self._closed:
            raise asyncio.CancelledError
        current_user_id = self._runtime_user_id()
        if not expected_user_id or current_user_id != expected_user_id:
            raise asyncio.CancelledError

    def _sync_cache_scope(self, owner_user_id: str) -> None:
        """Keep the global discovery cache scoped to the active account."""
        normalized_owner = str(owner_user_id or "").strip()
        if self._cache_owner_user_id == normalized_owner:
            return
        self._clear_caches()
        self._cache_owner_user_id = normalized_owner

    async def load_moments(self, user_id: Optional[str] = None) -> list[MomentRecord]:
        """Load moments and enrich authors from the user API when needed."""
        owner_user_id = self._capture_runtime_user_id()
        self._sync_cache_scope(owner_user_id)
        payload = await self._discovery_service.fetch_moments(user_id=user_id)
        self._ensure_runtime_user_id(owner_user_id)
        items = list(payload or [])

        author_ids = {
            str(item.get("user_id", "") or "")
            for item in items
            if item.get("user_id")
        }
        for item in items:
            for comment in item.get("comments") or []:
                if comment.get("user_id"):
                    author_ids.add(str(comment.get("user_id", "") or ""))
        await asyncio.gather(
            *[self._ensure_user_loaded(user_id, owner_user_id=owner_user_id) for user_id in author_ids],
            return_exceptions=True,
        )
        self._ensure_runtime_user_id(owner_user_id)

        moments = [self._normalize_moment(item) for item in items]
        moments.sort(key=lambda item: item.created_at, reverse=True)
        return moments

    async def load_moment_detail(self, moment_id: str) -> MomentRecord:
        """Load one moment detail payload with full comments."""
        owner_user_id = self._capture_runtime_user_id()
        self._sync_cache_scope(owner_user_id)
        payload = await self._discovery_service.get_moment(moment_id)
        self._ensure_runtime_user_id(owner_user_id)
        data = dict(payload or {})
        author_ids = {
            str(data.get("user_id", "") or ""),
            str((data.get("author") or {}).get("id", "") or "") if isinstance(data.get("author"), dict) else "",
        }
        for comment in data.get("comments") or []:
            if isinstance(comment, dict):
                author_ids.add(str(comment.get("user_id", "") or ""))
                author = comment.get("author")
                if isinstance(author, dict):
                    author_ids.add(str(author.get("id", "") or ""))
        await asyncio.gather(
            *[
                self._ensure_user_loaded(user_id, owner_user_id=owner_user_id)
                for user_id in author_ids
                if user_id
            ],
            return_exceptions=True,
        )
        self._ensure_runtime_user_id(owner_user_id)
        return self._normalize_moment(data)

    async def create_moment(
        self,
        content: str,
        *,
        media: list[dict[str, Any]] | None = None,
        visibility_scope: str = "public",
        visibility_user_ids: list[str] | None = None,
    ) -> MomentRecord:
        """Create a new moment."""
        owner_user_id = self._capture_runtime_user_id()
        self._sync_cache_scope(owner_user_id)
        payload = await self._discovery_service.create_moment(
            content,
            media=media or [],
            visibility_scope=visibility_scope,
            visibility_user_ids=self._normalize_user_id_list(visibility_user_ids),
        )
        self._ensure_runtime_user_id(owner_user_id)
        return self._normalize_moment(payload or {})

    async def load_moment_privacy_settings(self) -> MomentPrivacySettings:
        """Load the current user's moments privacy settings."""
        owner_user_id = self._capture_runtime_user_id()
        self._sync_cache_scope(owner_user_id)
        payload = await self._discovery_service.fetch_moment_privacy_settings()
        self._ensure_runtime_user_id(owner_user_id)
        return self._normalize_privacy_settings(payload)

    async def update_moment_privacy_settings(
        self,
        *,
        hide_my_moments_user_ids: list[str] | None = None,
        hide_their_moments_user_ids: list[str] | None = None,
        visible_time_scope: str | None = None,
    ) -> MomentPrivacySettings:
        """Persist the current user's moments privacy settings."""
        owner_user_id = self._capture_runtime_user_id()
        self._sync_cache_scope(owner_user_id)
        payload = await self._discovery_service.update_moment_privacy_settings(
            hide_my_moments_user_ids=self._normalize_user_id_list(hide_my_moments_user_ids)
            if hide_my_moments_user_ids is not None
            else None,
            hide_their_moments_user_ids=self._normalize_user_id_list(hide_their_moments_user_ids)
            if hide_their_moments_user_ids is not None
            else None,
            visible_time_scope=visible_time_scope,
        )
        self._ensure_runtime_user_id(owner_user_id)
        return self._normalize_privacy_settings(payload)

    async def set_liked(self, moment_id: str, liked: bool, like_count: Optional[int] = None) -> bool:
        """Update like state for a moment."""
        owner_user_id = self._capture_runtime_user_id()
        self._sync_cache_scope(owner_user_id)
        if liked:
            await self._discovery_service.like_moment(moment_id)
        else:
            await self._discovery_service.unlike_moment(moment_id)
        self._ensure_runtime_user_id(owner_user_id)
        return liked

    async def add_comment(
        self,
        moment_id: str,
        content: str,
        *,
        image: dict[str, Any] | None = None,
    ) -> MomentCommentRecord:
        """Add a new comment to a moment."""
        owner_user_id = self._capture_runtime_user_id()
        self._sync_cache_scope(owner_user_id)
        payload = await self._discovery_service.add_comment(moment_id, content, image=image)
        self._ensure_runtime_user_id(owner_user_id)
        return self._normalize_comment(payload or {}, moment_id=moment_id)

    async def _ensure_user_loaded(self, user_id: str, *, owner_user_id: str) -> None:
        """Load a user profile into cache if absent."""
        if not user_id or user_id in self._user_cache:
            return

        try:
            payload = await self._user_service.fetch_user(user_id)
        except Exception:
            logger.debug("Discovery user enrichment failed for %s", user_id, exc_info=True)
            self._ensure_runtime_user_id(owner_user_id)
            self._user_cache[user_id] = {}
            return

        self._ensure_runtime_user_id(owner_user_id)
        self._user_cache[user_id] = dict(payload or {})

    async def close(self) -> None:
        """Drop discovery caches and retire the global singleton."""
        self._closed = True
        self._cache_owner_user_id = ""
        self._clear_caches()
        global _discovery_controller
        if _discovery_controller is self:
            _discovery_controller = None

    def _normalize_moment(self, payload: dict[str, Any]) -> MomentRecord:
        """Convert backend payload to UI model."""
        data = dict(payload or {})
        author = dict(data.get("author") or {})
        user_id = str(data.get("user_id", "") or author.get("id", "") or "")
        cached_user = self._user_cache.get(user_id, {})
        current_user = self._auth.current_user or {}
        if user_id and user_id == str(current_user.get("id", "") or ""):
            cached_user = {
                **cached_user,
                "username": current_user.get("username", cached_user.get("username", "")),
                "nickname": current_user.get("nickname", cached_user.get("nickname", "")),
                "avatar": current_user.get("avatar", cached_user.get("avatar", "")),
                "gender": current_user.get("gender", cached_user.get("gender", "")),
            }

        moment_id = str(data.get("id", "") or "")
        comments_payload = list(data.get("comments") or [])
        normalized_comments = [
            self._normalize_comment(comment, moment_id=moment_id)
            for comment in comments_payload
        ]

        media = self._normalize_media_items(data.get("media") or data.get("images") or [])
        images = [item.url for item in media if item.is_image]
        videos = [item.url for item in media if item.is_video]
        like_count = int(data.get("like_count", 0) or 0)
        is_liked = bool(data.get("is_liked", False))

        return MomentRecord(
            id=moment_id,
            user_id=user_id,
            content=str(data.get("content", "") or ""),
            created_at=str(data.get("created_at", "") or ""),
            username=str(author.get("username", "") or cached_user.get("username", "") or ""),
            nickname=str(author.get("nickname", "") or cached_user.get("nickname", "") or ""),
            avatar=str(author.get("avatar", "") or cached_user.get("avatar", "") or ""),
            gender=str(author.get("gender", "") or cached_user.get("gender", "") or ""),
            media=media,
            images=images,
            videos=videos,
            visibility_scope=self._normalize_visibility_scope(data.get("visibility_scope")),
            visibility_user_ids=self._normalize_user_id_list(data.get("visibility_user_ids")),
            comments=normalized_comments,
            like_count=like_count,
            comment_count=max(int(data.get("comment_count", len(normalized_comments)) or 0), len(normalized_comments)),
            is_liked=is_liked,
            comments_truncated=bool(data.get("comments_truncated", False)),
            extra=data,
        )

    def _normalize_comment(self, payload: dict[str, Any], moment_id: str = "") -> MomentCommentRecord:
        """Convert backend payload to comment UI model."""
        data = dict(payload or {})
        author = dict(data.get("author") or {})
        user_id = str(data.get("user_id", "") or author.get("id", "") or "")
        cached_user = self._user_cache.get(user_id, {})
        current_user = self._auth.current_user or {}

        if user_id and user_id == str(current_user.get("id", "") or ""):
            cached_user = {
                **cached_user,
                "username": current_user.get("username", cached_user.get("username", "")),
                "nickname": current_user.get("nickname", cached_user.get("nickname", "")),
                "avatar": current_user.get("avatar", cached_user.get("avatar", "")),
                "gender": current_user.get("gender", cached_user.get("gender", "")),
            }

        return MomentCommentRecord(
            id=str(data.get("id", "") or ""),
            moment_id=str(data.get("moment_id", "") or moment_id),
            user_id=user_id,
            content=str(data.get("content", "") or ""),
            created_at=str(data.get("created_at", "") or ""),
            username=str(author.get("username", "") or cached_user.get("username", "") or ""),
            nickname=str(author.get("nickname", "") or cached_user.get("nickname", "") or ""),
            avatar=str(author.get("avatar", "") or cached_user.get("avatar", "") or ""),
            gender=str(author.get("gender", "") or cached_user.get("gender", "") or ""),
            image=self._normalize_media_item(data.get("image")),
        )

    def _normalize_privacy_settings(self, payload: dict[str, Any]) -> MomentPrivacySettings:
        data = dict(payload or {})
        return MomentPrivacySettings(
            hide_my_moments_user_ids=self._normalize_user_id_list(data.get("hide_my_moments_user_ids")),
            hide_their_moments_user_ids=self._normalize_user_id_list(data.get("hide_their_moments_user_ids")),
            visible_time_scope=self._normalize_visible_time_scope(data.get("visible_time_scope")),
        )

    def _normalize_media_items(self, payload: object) -> list[MomentMediaRecord]:
        """Convert backend media payloads into normalized attachment records."""
        if not isinstance(payload, list):
            return []
        items: list[MomentMediaRecord] = []
        for item in payload:
            normalized = self._normalize_media_item(item)
            if normalized is not None:
                items.append(normalized)
        return items

    def _normalize_media_item(self, payload: object) -> MomentMediaRecord | None:
        """Normalize one media object or legacy string image URL."""
        if isinstance(payload, str):
            url = payload.strip()
            if not url:
                return None
            return MomentMediaRecord(media_type="image", url=url)

        if not isinstance(payload, dict):
            return None

        media_type = str(payload.get("type") or payload.get("media_type") or "").strip().lower()
        url = str(payload.get("url") or "").strip()
        if not url:
            return None
        if media_type not in {"image", "video"}:
            media_type = "video" if self._looks_like_video(url, str(payload.get("mime_type") or "")) else "image"

        try:
            size_bytes = max(0, int(payload.get("size_bytes") or 0))
        except (TypeError, ValueError):
            size_bytes = 0

        return MomentMediaRecord(
            media_type=media_type,
            url=url,
            original_name=str(payload.get("original_name") or payload.get("name") or "").strip(),
            mime_type=str(payload.get("mime_type") or "").strip(),
            size_bytes=size_bytes,
            local_path=str(payload.get("local_path") or "").strip(),
        )

    @staticmethod
    def _normalize_user_id_list(payload: object) -> list[str]:
        if not isinstance(payload, list):
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_user_id in payload:
            user_id = str(raw_user_id or "").strip()
            if not user_id or user_id in seen:
                continue
            normalized.append(user_id)
            seen.add(user_id)
        return normalized

    @staticmethod
    def _normalize_visibility_scope(payload: object) -> str:
        value = str(payload or "public").strip().lower()
        return value if value in {"public", "private", "include", "exclude"} else "public"

    @staticmethod
    def _normalize_visible_time_scope(payload: object) -> str:
        value = str(payload or "all").strip().lower()
        return value if value in {"all", "half_year", "month", "three_days"} else "all"

    @staticmethod
    def _looks_like_video(url: str, mime_type: str = "") -> bool:
        lowered_mime = str(mime_type or "").strip().lower()
        if lowered_mime.startswith("video/"):
            return True
        lowered_url = str(url or "").strip().lower()
        return lowered_url.endswith((".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"))


_discovery_controller: Optional[DiscoveryController] = None


def peek_discovery_controller() -> Optional[DiscoveryController]:
    """Return the existing discovery controller singleton if it was created."""
    return _discovery_controller


def get_discovery_controller() -> DiscoveryController:
    """Return the global discovery controller instance."""
    global _discovery_controller
    if _discovery_controller is None:
        _discovery_controller = DiscoveryController()
    return _discovery_controller
