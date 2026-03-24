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
    images: list[str] = field(default_factory=list)
    comments: list[MomentCommentRecord] = field(default_factory=list)
    like_count: int = 0
    comment_count: int = 0
    is_liked: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """Return the best display name."""
        return self.nickname or self.username or self.user_id or "Unknown User"


class DiscoveryController:
    """Provide discovery timeline data to the UI."""

    def __init__(self) -> None:
        self._discovery_service = get_discovery_service()
        self._user_service = get_user_service()
        self._auth = get_auth_controller()
        self._user_cache: dict[str, dict[str, Any]] = {}
        self._comment_cache: dict[str, list[MomentCommentRecord]] = {}
        self._like_state_cache: dict[str, bool] = {}
        self._like_count_cache: dict[str, int] = {}

    async def load_moments(self, user_id: Optional[str] = None) -> list[MomentRecord]:
        """Load moments and enrich authors from the user API when needed."""
        payload = await self._discovery_service.fetch_moments(user_id=user_id)
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
        await asyncio.gather(*[self._ensure_user_loaded(user_id) for user_id in author_ids], return_exceptions=True)

        moments = [self._normalize_moment(item) for item in items]
        moments.sort(key=lambda item: item.created_at, reverse=True)
        return moments

    async def create_moment(self, content: str) -> MomentRecord:
        """Create a new moment."""
        payload = await self._discovery_service.create_moment(content)
        return self._normalize_moment(payload or {})

    async def set_liked(self, moment_id: str, liked: bool, like_count: Optional[int] = None) -> bool:
        """Update like state for a moment."""
        if liked:
            await self._discovery_service.like_moment(moment_id)
        else:
            await self._discovery_service.unlike_moment(moment_id)
        self._like_state_cache[moment_id] = liked
        if like_count is not None:
            self._like_count_cache[moment_id] = max(0, like_count)
        return liked

    async def add_comment(self, moment_id: str, content: str) -> MomentCommentRecord:
        """Add a new comment to a moment."""
        payload = await self._discovery_service.add_comment(moment_id, content)
        comment = self._normalize_comment(payload or {}, moment_id=moment_id)
        self._comment_cache.setdefault(moment_id, []).append(comment)
        self._like_count_cache.setdefault(moment_id, self._like_count_cache.get(moment_id, 0))
        return comment

    async def _ensure_user_loaded(self, user_id: str) -> None:
        """Load a user profile into cache if absent."""
        if not user_id or user_id in self._user_cache:
            return

        try:
            payload = await self._user_service.fetch_user(user_id)
        except Exception:
            logger.debug("Discovery user enrichment failed for %s", user_id, exc_info=True)
            self._user_cache[user_id] = {}
            return

        self._user_cache[user_id] = dict(payload or {})

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
        cached_comments = list(self._comment_cache.get(moment_id, []))
        if cached_comments:
            known_ids = {item.id for item in normalized_comments if item.id}
            normalized_comments.extend(
                item for item in cached_comments if not item.id or item.id not in known_ids
            )

        images = list(data.get("images") or data.get("media") or [])
        like_count = int(data.get("like_count", len(data.get("likes", []) or [])) or 0)
        if moment_id in self._like_count_cache:
            like_count = self._like_count_cache[moment_id]
        is_liked = bool(
            data.get("is_liked", False)
            or str(current_user.get("id", "") or "") in [str(value) for value in (data.get("liked_user_ids") or [])]
        )
        if moment_id in self._like_state_cache:
            is_liked = self._like_state_cache[moment_id]

        return MomentRecord(
            id=moment_id,
            user_id=user_id,
            content=str(data.get("content", "") or ""),
            created_at=str(data.get("created_at", "") or ""),
            username=str(data.get("username", "") or author.get("username", "") or cached_user.get("username", "") or ""),
            nickname=str(data.get("nickname", "") or author.get("nickname", "") or cached_user.get("nickname", "") or ""),
            avatar=str(data.get("avatar", "") or author.get("avatar", "") or cached_user.get("avatar", "") or ""),
            gender=str(data.get("gender", "") or author.get("gender", "") or cached_user.get("gender", "") or ""),
            images=images,
            comments=normalized_comments,
            like_count=like_count,
            comment_count=max(int(data.get("comment_count", len(normalized_comments)) or 0), len(normalized_comments)),
            is_liked=is_liked,
            extra=data,
        )

    def _normalize_comment(self, payload: dict[str, Any], moment_id: str = "") -> MomentCommentRecord:
        """Convert backend payload to comment UI model."""
        data = dict(payload or {})
        user_id = str(data.get("user_id", "") or "")
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
            username=str(data.get("username", "") or cached_user.get("username", "") or ""),
            nickname=str(data.get("nickname", "") or cached_user.get("nickname", "") or ""),
            avatar=str(data.get("avatar", "") or cached_user.get("avatar", "") or ""),
            gender=str(data.get("gender", "") or cached_user.get("gender", "") or ""),
        )


_discovery_controller: Optional[DiscoveryController] = None


def get_discovery_controller() -> DiscoveryController:
    """Return the global discovery controller instance."""
    global _discovery_controller
    if _discovery_controller is None:
        _discovery_controller = DiscoveryController()
    return _discovery_controller
