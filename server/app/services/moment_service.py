"""Moment service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.moment_repo import MomentRepository
from app.services.user_service import UserService


MOMENT_COMMENT_PREVIEW_LIMIT = 3


class MomentService:
    def __init__(self, db: Session) -> None:
        self.moments = MomentRepository(db)
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
        total = self.moments.count_moments(user_id=user_id)
        moments = self.moments.list_moments(
            user_id=user_id,
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

    def create_moment(self, current_user: User, content: str) -> dict:
        moment = self.moments.create(current_user.id, content)
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
        self._ensure_exists(moment_id)
        changed = self.moments.like(moment_id, current_user.id)
        return {"liked": True, "changed": changed}

    def unlike(self, current_user: User, moment_id: str) -> dict:
        self._ensure_exists(moment_id)
        changed = self.moments.unlike(moment_id, current_user.id)
        return {"liked": False, "changed": changed}

    def comment(self, current_user: User, moment_id: str, content: str) -> dict:
        self._ensure_exists(moment_id)
        comment = self.moments.comment(moment_id, current_user.id, content)
        return self.serialize_comment(comment, current_user)

    def _ensure_exists(self, moment_id: str) -> None:
        if self.moments.get_by_id(moment_id) is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "moment not found", 404)

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
        return {
            "id": moment.id,
            "user_id": moment.user_id,
            "content": moment.content,
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
            "created_at": comment.created_at.isoformat() if comment.created_at else None,
            "author": self.user_payloads.serialize_public_user(user) if user else None,
        }
