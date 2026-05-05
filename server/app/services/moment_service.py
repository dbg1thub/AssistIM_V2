"""Moment service."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.friend_repo import FriendRepository
from app.repositories.moment_repo import MomentRepository
from app.services.user_service import UserService


MOMENT_COMMENT_PREVIEW_LIMIT = 3
MOMENT_VISIBILITY_SCOPES = {"public", "private", "include", "exclude"}
MOMENT_VISIBLE_TIME_SCOPES = {"all", "half_year", "month", "three_days"}


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
        candidate_moments = self.moments.list_moments(
            user_id=user_id,
            user_ids=visible_user_ids,
        )
        moments = (
            self._filter_visible_moments(current_user, candidate_moments)
            if current_user is not None
            else candidate_moments
        )
        total = len(moments)
        offset = (normalized_page - 1) * normalized_size
        moments = moments[offset : offset + normalized_size]
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
                    viewer_user_id=current_user.id if current_user is not None else "",
                )
                for item in moments
            ],
        }

    def get_moment(self, current_user: User, moment_id: str) -> dict:
        moment = self.moments.get_by_id(moment_id)
        if moment is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "moment not found", 404)
        self._ensure_can_view_moment(current_user, moment)

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
            viewer_user_id=current_user.id,
        )

    def create_moment(
        self,
        current_user: User,
        content: str,
        media: list | None = None,
        *,
        visibility_scope: str = "public",
        visibility_user_ids: list[str] | None = None,
    ) -> dict:
        normalized_scope = self._normalize_visibility_scope(visibility_scope)
        normalized_visibility_user_ids = self._normalize_user_id_list(visibility_user_ids or [])
        self._ensure_valid_moment_visibility_targets(
            current_user,
            normalized_scope,
            normalized_visibility_user_ids,
        )
        moment = self.moments.create(
            current_user.id,
            content,
            media_json=self._dump_media_items(media or []),
            visibility_scope=normalized_scope,
            visibility_user_ids_json=self._dump_user_ids(normalized_visibility_user_ids),
        )
        return self.serialize_moment(
            moment,
            author=current_user,
            comments=[],
            comment_count=0,
            like_count=0,
            is_liked=False,
            users_map={current_user.id: current_user},
            viewer_user_id=current_user.id,
        )

    def get_privacy_settings(self, current_user: User) -> dict:
        return self.serialize_privacy_setting(self.moments.get_privacy_setting(current_user.id))

    def update_privacy_settings(
        self,
        current_user: User,
        *,
        hide_my_moments_user_ids: list[str] | None = None,
        hide_their_moments_user_ids: list[str] | None = None,
        visible_time_scope: str | None = None,
    ) -> dict:
        existing = self.serialize_privacy_setting(self.moments.get_privacy_setting(current_user.id))
        hide_my_ids = (
            existing["hide_my_moments_user_ids"]
            if hide_my_moments_user_ids is None
            else self._normalize_user_id_list(hide_my_moments_user_ids)
        )
        hide_their_ids = (
            existing["hide_their_moments_user_ids"]
            if hide_their_moments_user_ids is None
            else self._normalize_user_id_list(hide_their_moments_user_ids)
        )
        normalized_time_scope = str(visible_time_scope or existing["visible_time_scope"] or "all").strip()
        if normalized_time_scope not in MOMENT_VISIBLE_TIME_SCOPES:
            raise AppError(ErrorCode.INVALID_REQUEST, "invalid moment visible time scope", 400)
        self._ensure_friend_targets(current_user, hide_my_ids, "hide_my_moments_user_ids")
        self._ensure_friend_targets(current_user, hide_their_ids, "hide_their_moments_user_ids")
        setting = self.moments.save_privacy_setting(
            current_user.id,
            hide_my_moments_user_ids_json=self._dump_user_ids(hide_my_ids),
            hide_their_moments_user_ids_json=self._dump_user_ids(hide_their_ids),
            visible_time_scope=normalized_time_scope,
        )
        return self.serialize_privacy_setting(setting)

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

    def delete_moment(self, current_user: User, moment_id: str) -> dict:
        moment = self.moments.get_by_id(moment_id)
        if moment is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "moment not found", 404)
        owner_user_id = str(getattr(moment, "user_id", "") or "")
        if owner_user_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "moment delete forbidden", 403)
        self.moments.delete_moment(moment)
        return {
            "deleted": True,
            "moment_id": moment_id,
            "owner_user_id": owner_user_id,
        }

    def delete_comment(self, current_user: User, moment_id: str, comment_id: str) -> dict:
        moment = self.moments.get_by_id(moment_id)
        if moment is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "moment not found", 404)
        comment = self.moments.get_comment_by_id(comment_id)
        if comment is None or str(getattr(comment, "moment_id", "") or "") != moment_id:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "moment comment not found", 404)
        owner_user_id = str(getattr(moment, "user_id", "") or "")
        comment_author_id = str(getattr(comment, "user_id", "") or "")
        if current_user.id not in {owner_user_id, comment_author_id}:
            raise AppError(ErrorCode.FORBIDDEN, "moment comment delete forbidden", 403)
        self.moments.delete_comment(comment)
        return {
            "deleted": True,
            "moment_id": moment_id,
            "comment_id": comment_id,
            "owner_user_id": owner_user_id,
        }

    def _get_visible_moment(self, current_user: User, moment_id: str):
        moment = self.moments.get_by_id(moment_id)
        if moment is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "moment not found", 404)
        self._ensure_can_view_moment(current_user, moment)
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

    def _ensure_can_view_moment(self, current_user: User, moment) -> None:
        if self._can_view_moment(current_user, moment):
            return
        raise AppError(ErrorCode.FORBIDDEN, "moment not visible", 403)

    def _filter_visible_moments(self, current_user: User, moments: list) -> list:
        user_ids = [current_user.id]
        user_ids.extend(str(getattr(moment, "user_id", "") or "") for moment in moments)
        settings_map = self.moments.get_privacy_settings_map(user_ids)
        return [
            moment
            for moment in moments
            if self._can_view_moment(current_user, moment, settings_map=settings_map)
        ]

    def _can_view_moment(self, current_user: User, moment, *, settings_map: dict | None = None) -> bool:
        author_user_id = str(getattr(moment, "user_id", "") or "").strip()
        if not author_user_id:
            return False
        if author_user_id == current_user.id:
            return True
        if not self.friends.is_friend(current_user.id, author_user_id):
            return False

        settings_map = settings_map or self.moments.get_privacy_settings_map([current_user.id, author_user_id])
        viewer_setting = settings_map.get(current_user.id)
        author_setting = settings_map.get(author_user_id)
        if author_user_id in self._setting_hide_their_ids(viewer_setting):
            return False
        if current_user.id in self._setting_hide_my_ids(author_setting):
            return False
        if not self._is_within_author_visible_time(moment, author_setting):
            return False

        visibility_scope = self._normalize_visibility_scope(getattr(moment, "visibility_scope", "public"))
        visibility_user_ids = set(self._load_user_ids(getattr(moment, "visibility_user_ids_json", "[]")))
        if visibility_scope == "private":
            return False
        if visibility_scope == "include":
            return current_user.id in visibility_user_ids
        if visibility_scope == "exclude":
            return current_user.id not in visibility_user_ids
        return True

    def _ensure_valid_moment_visibility_targets(
        self,
        current_user: User,
        visibility_scope: str,
        visibility_user_ids: list[str],
    ) -> None:
        if visibility_scope in {"include", "exclude"} and not visibility_user_ids:
            raise AppError(ErrorCode.INVALID_REQUEST, "visibility targets are required", 400)
        if visibility_scope in {"public", "private"} and visibility_user_ids:
            raise AppError(ErrorCode.INVALID_REQUEST, "visibility targets are not allowed for this scope", 400)
        self._ensure_friend_targets(current_user, visibility_user_ids, "visibility_user_ids")

    def _ensure_friend_targets(self, current_user: User, user_ids: list[str], field_name: str) -> None:
        invalid_ids = [
            user_id
            for user_id in self._normalize_user_id_list(user_ids)
            if user_id == current_user.id or not self.friends.is_friend(current_user.id, user_id)
        ]
        if invalid_ids:
            raise AppError(ErrorCode.INVALID_REQUEST, f"{field_name} must only contain friends", 400)

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
        viewer_user_id: str = "",
    ) -> dict:
        author = author or (users_map or {}).get(moment.user_id)
        comments = comments or []
        users_map = users_map or {}
        media = self._load_media_items(getattr(moment, "media_json", "[]"))
        owner_view = str(viewer_user_id or "").strip() == str(moment.user_id or "").strip()
        visibility_scope = self._normalize_visibility_scope(getattr(moment, "visibility_scope", "public"))
        return {
            "id": moment.id,
            "user_id": moment.user_id,
            "content": moment.content,
            "media": media,
            "images": [item["url"] for item in media if item.get("type") == "image"],
            "videos": [item["url"] for item in media if item.get("type") == "video"],
            "visibility_scope": visibility_scope if owner_view else "public",
            "visibility_user_ids": self._load_user_ids(getattr(moment, "visibility_user_ids_json", "[]")) if owner_view else [],
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

    def serialize_privacy_setting(self, setting) -> dict:
        if setting is None:
            return {
                "hide_my_moments_user_ids": [],
                "hide_their_moments_user_ids": [],
                "visible_time_scope": "all",
            }
        visible_time_scope = str(getattr(setting, "visible_time_scope", "") or "all").strip()
        if visible_time_scope not in MOMENT_VISIBLE_TIME_SCOPES:
            visible_time_scope = "all"
        return {
            "hide_my_moments_user_ids": self._load_user_ids(
                getattr(setting, "hide_my_moments_user_ids_json", "[]")
            ),
            "hide_their_moments_user_ids": self._load_user_ids(
                getattr(setting, "hide_their_moments_user_ids_json", "[]")
            ),
            "visible_time_scope": visible_time_scope,
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
    def _dump_user_ids(cls, user_ids: list[str] | None) -> str:
        return json.dumps(cls._normalize_user_id_list(user_ids or []), ensure_ascii=False, separators=(",", ":"))

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

    @staticmethod
    def _normalize_visibility_scope(value: object) -> str:
        candidate = str(value or "public").strip().lower()
        return candidate if candidate in MOMENT_VISIBILITY_SCOPES else "public"

    @staticmethod
    def _normalize_user_id_list(user_ids: list[str] | None) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_user_id in user_ids or []:
            user_id = str(raw_user_id or "").strip()
            if not user_id or user_id in seen:
                continue
            normalized.append(user_id)
            seen.add(user_id)
        return normalized

    @classmethod
    def _load_user_ids(cls, raw_value: str | None) -> list[str]:
        try:
            payload = json.loads(raw_value or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return cls._normalize_user_id_list([str(item or "") for item in payload])

    @classmethod
    def _setting_hide_my_ids(cls, setting) -> set[str]:
        return set(cls._load_user_ids(getattr(setting, "hide_my_moments_user_ids_json", "[]")))

    @classmethod
    def _setting_hide_their_ids(cls, setting) -> set[str]:
        return set(cls._load_user_ids(getattr(setting, "hide_their_moments_user_ids_json", "[]")))

    def _is_within_author_visible_time(self, moment, author_setting) -> bool:
        scope = str(getattr(author_setting, "visible_time_scope", "") or "all").strip()
        if scope == "all" or scope not in MOMENT_VISIBLE_TIME_SCOPES:
            return True
        created_at = self._as_utc_datetime(getattr(moment, "created_at", None))
        if created_at is None:
            return False
        cutoff = datetime.now(timezone.utc) - self._visible_time_delta(scope)
        return created_at >= cutoff

    @staticmethod
    def _visible_time_delta(scope: str) -> timedelta:
        if scope == "three_days":
            return timedelta(days=3)
        if scope == "month":
            return timedelta(days=30)
        if scope == "half_year":
            return timedelta(days=183)
        return timedelta.max

    @staticmethod
    def _as_utc_datetime(value: object) -> datetime | None:
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

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
