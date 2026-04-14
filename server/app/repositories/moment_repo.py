"""Moment repository."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.moment import Moment, MomentComment, MomentLike
from app.models.user import User


class MomentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_moments(self, user_id: str | None = None, *, offset: int = 0, limit: int | None = None) -> list[Moment]:
        stmt = select(Moment)
        if user_id:
            stmt = stmt.where(Moment.user_id == user_id)
        stmt = stmt.order_by(desc(Moment.created_at))
        if limit is not None:
            stmt = stmt.offset(max(0, offset)).limit(max(0, limit))
        return list(self.db.execute(stmt).scalars().all())

    def count_moments(self, user_id: str | None = None) -> int:
        stmt = select(func.count()).select_from(Moment)
        if user_id:
            stmt = stmt.where(Moment.user_id == user_id)
        return int(self.db.execute(stmt).scalar_one() or 0)

    def get_comments_map(
        self,
        moment_ids: list[str],
        *,
        limit_per_moment: int | None = None,
    ) -> dict[str, list[MomentComment]]:
        """Return comments grouped by moment ID."""
        if not moment_ids:
            return {}

        if limit_per_moment is None:
            stmt = (
                select(MomentComment)
                .where(MomentComment.moment_id.in_(moment_ids))
                .order_by(MomentComment.created_at.asc())
            )
        else:
            ranked = (
                select(
                    MomentComment.id.label("id"),
                    func.row_number()
                    .over(
                        partition_by=MomentComment.moment_id,
                        order_by=MomentComment.created_at.asc(),
                    )
                    .label("row_number"),
                )
                .where(MomentComment.moment_id.in_(moment_ids))
                .subquery()
            )
            stmt = (
                select(MomentComment)
                .join(ranked, MomentComment.id == ranked.c.id)
                .where(ranked.c.row_number <= max(0, limit_per_moment))
                .order_by(MomentComment.moment_id.asc(), MomentComment.created_at.asc())
            )
        grouped: dict[str, list[MomentComment]] = defaultdict(list)
        for comment in self.db.execute(stmt).scalars().all():
            grouped[comment.moment_id].append(comment)
        return dict(grouped)

    def get_comment_counts_map(self, moment_ids: list[str]) -> dict[str, int]:
        """Return comment counts grouped by moment ID."""
        if not moment_ids:
            return {}

        stmt = (
            select(MomentComment.moment_id, func.count(MomentComment.id))
            .where(MomentComment.moment_id.in_(moment_ids))
            .group_by(MomentComment.moment_id)
        )
        return {moment_id: int(count or 0) for moment_id, count in self.db.execute(stmt).all()}

    def get_like_counts_map(self, moment_ids: list[str]) -> dict[str, int]:
        """Return like counts grouped by moment ID."""
        if not moment_ids:
            return {}

        stmt = (
            select(MomentLike.moment_id, func.count(MomentLike.user_id))
            .where(MomentLike.moment_id.in_(moment_ids))
            .group_by(MomentLike.moment_id)
        )
        return {moment_id: int(count or 0) for moment_id, count in self.db.execute(stmt).all()}

    def get_liked_moment_ids(self, moment_ids: list[str], user_id: str) -> set[str]:
        """Return moment IDs liked by one user."""
        if not moment_ids or not user_id:
            return set()

        stmt = select(MomentLike.moment_id).where(
            MomentLike.moment_id.in_(moment_ids),
            MomentLike.user_id == user_id,
        )
        return {str(moment_id) for moment_id in self.db.execute(stmt).scalars().all()}

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

    def like(self, moment_id: str, user_id: str) -> bool:
        existing = self.db.get(MomentLike, {"moment_id": moment_id, "user_id": user_id})
        if existing is not None:
            return False
        self.db.add(MomentLike(moment_id=moment_id, user_id=user_id))
        self.db.commit()
        return True

    def unlike(self, moment_id: str, user_id: str) -> bool:
        existing = self.db.get(MomentLike, {"moment_id": moment_id, "user_id": user_id})
        if existing is None:
            return False
        self.db.delete(existing)
        self.db.commit()
        return True

    def comment(self, moment_id: str, user_id: str, content: str) -> MomentComment:
        comment = MomentComment(moment_id=moment_id, user_id=user_id, content=content)
        self.db.add(comment)
        self.db.commit()
        self.db.refresh(comment)
        return comment
