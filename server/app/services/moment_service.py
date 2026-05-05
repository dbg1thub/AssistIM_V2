"""Moment service."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.friend_repo import FriendRepository
from app.repositories.moment_repo import MomentRepository
from app.services.user_service import UserService


MOMENT_COMMENT_PREVIEW_LIMIT = 3


class MomentService:
    def __init__(self, db: Session) -> None:
        self.moments = MomentRepository(db)
        self.friends = FriendRepository(db)
        self.user_payloads = UserService(db)

    def list_moments(
        self,
        current_user: User | None = None,
        user_id: str | None = None,
        *,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        normalized_page = max(1, page)
        normalized_size = max(1, size)
        visible_user_ids: list[str] | None = None
        if current_user is not None:
            if user_id:
                self._ensure_can_view_author(current_user, user_id)
            else:
                visible_user_ids = self._visible_author_ids(current_user)
        total = self.moments.count_moments(user_id=user_id, user_ids=visible_user_ids)
        moments = self.moments.list_moments(
            user_id=user_id,
            user_ids=visible_user_ids,
            offset=(normalized_page - 1) * normalized_size,
            limit=normalized_size,
        )
        moment_ids = [item.id for item in moments]
        comments_map = self.moments.get_comments_map(
            moment_ids,
            limit_per_moment=MOMENT_COMMENT_PREVIEW_LIMIT,
        )
        comment_counts_map = self.moments.get_comment_counts_map(moment_ids)
        like_counts_map = self.moments.get_like_counts_map(moment_ids)
        liked_moment_ids = (
            self.moments.get_liked_moment_ids(moment_ids, current_user.id)
            if current_user is not None
            else set()
        )

        user_ids = {item.user_id for item in moments}
        for comments in comments_map.values():
            for comment in comments:
                user_ids.add(comment.user_id)

        users_map = self.moments.get_users_map(list(user_ids))
        return {
            "total": total,
            "page": normalized_page,
            "size": normalized_size,
            "items": [
                self.serialize_moment(
                    item,
                    author=users_map.get(item.user_id),
                    comments=comments_map.get(item.id, []),
                    comment_count=comment_counts_map.get(item.id, 0),
                    like_count=like_counts_map.get(item.id, 0),
                    is_liked=item.id in liked_moment_ids,
                    users_map=users_map,
                    comments_truncated=comment_counts_map.get(item.id, 0)
                    > len(comments_map.get(item.id, [])),
                )
                for item in moments
            ],
        }

    def get_moment(self, current_user: User, moment_id: str) -> dict:
        moment = self.moments.get_by_id(moment_id)
        if moment is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "moment not found", 404)
        self._ensure_can_view_author(current_user, moment.user_id)

        comments_map = self.moments.get_comments_map([moment_id])
        like_counts_map = self.moments.get_like_counts_map([moment_id])
        liked_moment_ids = self.moments.get_liked_moment_ids([moment_id], current_user.id)
        comments = comments_map.get(moment_id, [])
        user_ids = {moment.user_id}
        for comment in comments:
            user_ids.add(comment.user_id)
        users_map = self.moments.get_users_map(list(user_ids))
        return self.serialize_moment(
            moment,
            author=users_map.get(moment.user_id),
            comments=comments,
            comment_count=len(comments),
            like_count=like_counts_map.get(moment_id, 0),
            is_liked=moment_id in liked_moment_ids,
            users_map=users_map,
            comments_truncated=False,
        )

    def create_moment(self, current_user: User, content: str, media: list | None = None) -> dict:
        moment = self.moments.create(
            current_user.id,
            content,
            media_json=self._dump_media_items(media or []),
        )
        return self.serialize_moment(
            moment,
            author=current_user,
            comments=[],
            comment_count=0,
            like_count=0,
            is_liked=False,
            users_map={current_user.id: current_user},
        )

    def like(self, current_user: User, moment_id: str) -> dict:
        self._get_visible_moment(current_user, moment_id)
        changed = self.moments.like(moment_id, current_user.id)
        return {"liked": True, "changed": changed}

    def unlike(self, current_user: User, moment_id: str) -> dict:
        self._get_visible_moment(current_user, moment_id)
        changed = self.moments.unlike(moment_id, current_user.id)
        return {"liked": False, "changed": changed}

    def comment(self, current_user: User, moment_id: str, content: str, image: object | None = None) -> dict:
        self._get_visible_moment(current_user, moment_id)
        comment = self.moments.comment(
            moment_id,
            current_user.id,
            content,
            image_json=self._dump_image_item(image),
        )
        return self.serialize_comment(comment, current_user)

    def _get_visible_moment(self, current_user: User, moment_id: str):
        moment = self.moments.get_by_id(moment_id)
        if moment is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "moment not found", 404)
        self._ensure_can_view_author(current_user, moment.user_id)
        return moment

    def _visible_author_ids(self, current_user: User) -> list[str]:
        friend_ids = [friendship.friend_id for friendship in self.friends.list_friends(current_user.id)]
        return [current_user.id, *friend_ids]

    def _ensure_can_view_author(self, current_user: User, author_user_id: str | None) -> None:
        normalized_author_id = str(author_user_id or "").strip()
        if not normalized_author_id:
            raise AppError(ErrorCode.FORBIDDEN, "moment not visible", 403)
        if normalized_author_id == current_user.id:
            return
        if self.friends.is_friend(current_user.id, normalized_author_id):
            return
        raise AppError(ErrorCode.FORBIDDEN, "moment not visible", 403)

    def serialize_moment(
        self,
        moment,
        *,
        author: User | None = None,
        comments: list | None = None,
        comment_count: int | None = None,
        like_count: int = 0,
        is_liked: bool = False,
        users_map: dict[str, User] | None = None,
        comments_truncated: bool = False,
    ) -> dict:
        author = author or (users_map or {}).get(moment.user_id)
        comments = comments or []
        users_map = users_map or {}
        media = self._load_media_items(getattr(moment, "media_json", "[]"))
        return {
            "id": moment.id,
            "user_id": moment.user_id,
            "content": moment.content,
            "media": media,
            "images": [item["url"] for item in media if item.get("type") == "image"],
            "videos": [item["url"] for item in media if item.get("type") == "video"],
            "created_at": moment.created_at.isoformat() if moment.created_at else None,
            "author": self.user_payloads.serialize_public_user(author) if author else None,
            "comments": [
                self.serialize_comment(comment, users_map.get(comment.user_id))
                for comment in comments
            ],
            "like_count": max(0, int(like_count or 0)),
            "comment_count": max(int(comment_count if comment_count is not None else len(comments)), len(comments)),
            "comments_truncated": comments_truncated,
            "is_liked": bool(is_liked),
        }

    def serialize_comment(self, comment, user: User | None = None) -> dict:
        return {
            "id": comment.id,
            "moment_id": comment.moment_id,
            "user_id": comment.user_id,
            "content": comment.content,
            "image": self._load_image_item(getattr(comment, "image_json", "{}")),
            "created_at": comment.created_at.isoformat() if comment.created_at else None,
            "author": self.user_payloads.serialize_public_user(user) if user else None,
        }

    @classmethod
    def _dump_media_items(cls, media: list | None) -> str:
        items = [cls._normalize_media_item(item) for item in (media or [])]
        return json.dumps(items, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def _dump_image_item(cls, image: object | None) -> str:
        if image is None:
            return "{}"
        return json.dumps(cls._normalize_media_item(image), ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _normalize_media_item(item: object) -> dict[str, Any]:
        if hasattr(item, "model_dump"):
            data = dict(item.model_dump())
        elif isinstance(item, dict):
            data = dict(item)
        else:
            data = {}
        return {
            "type": str(data.get("type") or "").strip().lower(),
            "url": str(data.get("url") or "").strip(),
            "original_name": str(data.get("original_name") or "").strip(),
            "mime_type": str(data.get("mime_type") or "").strip(),
            "size_bytes": max(0, int(data.get("size_bytes") or 0)),
        }

    @classmethod
    def _load_media_items(cls, raw_value: str | None) -> list[dict[str, Any]]:
        try:
            payload = json.loads(raw_value or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        items: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            normalized = cls._normalize_media_item(item)
            if normalized["type"] in {"image", "video"} and normalized["url"]:
                items.append(normalized)
        return items

    @classmethod
    def _load_image_item(cls, raw_value: str | None) -> dict[str, Any] | None:
        try:
            payload = json.loads(raw_value or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or not payload:
            return None
        normalized = cls._normalize_media_item(payload)
        if normalized["type"] != "image" or not normalized["url"]:
            return None
        return normalized
