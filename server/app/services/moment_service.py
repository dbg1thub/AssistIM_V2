"""Moment service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.moment_repo import MomentRepository


class MomentService:
    def __init__(self, db: Session) -> None:
        self.moments = MomentRepository(db)

    def list_moments(self, current_user: User | None = None, user_id: str | None = None) -> list[dict]:
        moments = self.moments.list_moments(user_id=user_id)
        moment_ids = [item.id for item in moments]
        comments_map = self.moments.get_comments_map(moment_ids)
        like_user_ids_map = self.moments.get_like_user_ids_map(moment_ids)

        user_ids = {item.user_id for item in moments}
        for comments in comments_map.values():
            for comment in comments:
                user_ids.add(comment.user_id)

        users_map = self.moments.get_users_map(list(user_ids))
        return [
            self.serialize_moment(
                item,
                current_user=current_user,
                author=users_map.get(item.user_id),
                comments=comments_map.get(item.id, []),
                like_user_ids=like_user_ids_map.get(item.id, []),
                users_map=users_map,
            )
            for item in moments
        ]

    def create_moment(self, current_user: User, content: str) -> dict:
        moment = self.moments.create(current_user.id, content)
        return self.serialize_moment(
            moment,
            current_user=current_user,
            author=current_user,
            comments=[],
            like_user_ids=[],
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

    @staticmethod
    def serialize_moment(
        moment,
        *,
        current_user: User | None = None,
        author: User | None = None,
        comments: list | None = None,
        like_user_ids: list[str] | None = None,
        users_map: dict[str, User] | None = None,
    ) -> dict:
        author = author or (users_map or {}).get(moment.user_id)
        comments = comments or []
        like_user_ids = list(like_user_ids or [])
        users_map = users_map or {}
        return {
            "id": moment.id,
            "user_id": moment.user_id,
            "content": moment.content,
            "created_at": moment.created_at.isoformat() if moment.created_at else None,
            "author": {
                "id": author.id,
                "username": author.username,
                "nickname": author.nickname,
                "avatar": author.avatar,
            }
            if author
            else None,
            "comments": [
                MomentService.serialize_comment(comment, users_map.get(comment.user_id))
                for comment in comments
            ],
            "like_count": len(like_user_ids),
            "comment_count": len(comments),
            "liked_user_ids": like_user_ids,
            "is_liked": bool(current_user and current_user.id in like_user_ids),
        }

    @staticmethod
    def serialize_comment(comment, user: User | None = None) -> dict:
        return {
            "id": comment.id,
            "moment_id": comment.moment_id,
            "user_id": comment.user_id,
            "content": comment.content,
            "created_at": comment.created_at.isoformat() if comment.created_at else None,
            "author": {
                "id": user.id,
                "username": user.username,
                "nickname": user.nickname,
                "avatar": user.avatar,
            }
            if user
            else None,
        }
