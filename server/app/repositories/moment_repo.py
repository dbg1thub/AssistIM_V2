"""Moment repository."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.moment import Moment, MomentComment, MomentLike
from app.models.user import User


class MomentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_moments(self, user_id: str | None = None) -> list[Moment]:
        stmt = select(Moment)
        if user_id:
            stmt = stmt.where(Moment.user_id == user_id)
        stmt = stmt.order_by(desc(Moment.created_at))
        return list(self.db.execute(stmt).scalars().all())

    def get_comments_map(self, moment_ids: list[str]) -> dict[str, list[MomentComment]]:
        """Return comments grouped by moment ID."""
        if not moment_ids:
            return {}

        stmt = (
            select(MomentComment)
            .where(MomentComment.moment_id.in_(moment_ids))
            .order_by(MomentComment.created_at.asc())
        )
        grouped: dict[str, list[MomentComment]] = defaultdict(list)
        for comment in self.db.execute(stmt).scalars().all():
            grouped[comment.moment_id].append(comment)
        return dict(grouped)

    def get_like_user_ids_map(self, moment_ids: list[str]) -> dict[str, list[str]]:
        """Return liked user IDs grouped by moment ID."""
        if not moment_ids:
            return {}

        stmt = select(MomentLike.moment_id, MomentLike.user_id).where(MomentLike.moment_id.in_(moment_ids))
        grouped: dict[str, list[str]] = defaultdict(list)
        for moment_id, user_id in self.db.execute(stmt).all():
            grouped[moment_id].append(user_id)
        return dict(grouped)

    def get_users_map(self, user_ids: list[str]) -> dict[str, User]:
        """Return users keyed by ID."""
        if not user_ids:
            return {}

        stmt = select(User).where(User.id.in_(user_ids))
        return {user.id: user for user in self.db.execute(stmt).scalars().all()}

    def create(self, user_id: str, content: str) -> Moment:
        moment = Moment(user_id=user_id, content=content)
        self.db.add(moment)
        self.db.commit()
        self.db.refresh(moment)
        return moment

    def get_by_id(self, moment_id: str) -> Moment | None:
        return self.db.get(Moment, moment_id)

    def like(self, moment_id: str, user_id: str) -> None:
        existing = self.db.get(MomentLike, {"moment_id": moment_id, "user_id": user_id})
        if existing is None:
            self.db.add(MomentLike(moment_id=moment_id, user_id=user_id))
            self.db.commit()

    def unlike(self, moment_id: str, user_id: str) -> None:
        existing = self.db.get(MomentLike, {"moment_id": moment_id, "user_id": user_id})
        if existing is not None:
            self.db.delete(existing)
            self.db.commit()

    def comment(self, moment_id: str, user_id: str, content: str) -> MomentComment:
        comment = MomentComment(moment_id=moment_id, user_id=user_id, content=content)
        self.db.add(comment)
        self.db.commit()
        self.db.refresh(comment)
        return comment
