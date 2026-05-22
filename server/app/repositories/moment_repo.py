"""Moment repository."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session

from app.models.moment import Moment, MomentComment, MomentLike, MomentNotification, MomentPrivacySetting
from app.models.user import User


class MomentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_moments(
        self,
        user_id: str | None = None,
        *,
        user_ids: list[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[Moment]:
        stmt = select(Moment)
        if user_id:
            stmt = stmt.where(Moment.user_id == user_id)
        elif user_ids is not None:
            normalized_user_ids = [item for item in dict.fromkeys(user_ids) if item]
            if not normalized_user_ids:
                return []
            stmt = stmt.where(Moment.user_id.in_(normalized_user_ids))
        stmt = stmt.order_by(desc(Moment.created_at))
        if limit is not None:
            stmt = stmt.offset(max(0, offset)).limit(max(0, limit))
        return list(self.db.execute(stmt).scalars().all())

    def count_moments(self, user_id: str | None = None, *, user_ids: list[str] | None = None) -> int:
        stmt = select(func.count()).select_from(Moment)
        if user_id:
            stmt = stmt.where(Moment.user_id == user_id)
        elif user_ids is not None:
            normalized_user_ids = [item for item in dict.fromkeys(user_ids) if item]
            if not normalized_user_ids:
                return 0
            stmt = stmt.where(Moment.user_id.in_(normalized_user_ids))
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

    def create(
        self,
        user_id: str,
        content: str,
        *,
        media_json: str = "[]",
        visibility_scope: str = "public",
        visibility_user_ids_json: str = "[]",
    ) -> Moment:
        moment = Moment(
            user_id=user_id,
            content=content,
            media_json=media_json,
            visibility_scope=visibility_scope,
            visibility_user_ids_json=visibility_user_ids_json,
        )
        self.db.add(moment)
        self.db.commit()
        self.db.refresh(moment)
        return moment

    def get_by_id(self, moment_id: str) -> Moment | None:
        return self.db.get(Moment, moment_id)

    def get_moments_map(self, moment_ids: list[str]) -> dict[str, Moment]:
        normalized_ids = [item for item in dict.fromkeys(moment_ids) if item]
        if not normalized_ids:
            return {}
        stmt = select(Moment).where(Moment.id.in_(normalized_ids))
        return {str(moment.id): moment for moment in self.db.execute(stmt).scalars().all()}

    def update_moment(
        self,
        moment: Moment,
        *,
        content: str,
        visibility_scope: str,
        visibility_user_ids_json: str,
    ) -> Moment:
        moment.content = content
        moment.visibility_scope = visibility_scope
        moment.visibility_user_ids_json = visibility_user_ids_json
        self.db.add(moment)
        self.db.commit()
        self.db.refresh(moment)
        return moment

    def get_comment_by_id(self, comment_id: str) -> MomentComment | None:
        return self.db.get(MomentComment, comment_id)

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

    def comment(self, moment_id: str, user_id: str, content: str, *, image_json: str = "{}") -> MomentComment:
        comment = MomentComment(moment_id=moment_id, user_id=user_id, content=content, image_json=image_json)
        self.db.add(comment)
        self.db.commit()
        self.db.refresh(comment)
        return comment

    def create_notification(
        self,
        *,
        recipient_user_id: str,
        actor_user_id: str,
        moment_id: str,
        comment_id: str,
        notification_type: str,
        content_preview: str,
    ) -> MomentNotification | None:
        existing = self.get_existing_notification(
            recipient_user_id=recipient_user_id,
            actor_user_id=actor_user_id,
            moment_id=moment_id,
            comment_id=comment_id,
            notification_type=notification_type,
        )
        if existing is not None:
            return None
        notification = MomentNotification(
            recipient_user_id=recipient_user_id,
            actor_user_id=actor_user_id,
            moment_id=moment_id,
            comment_id=comment_id,
            notification_type=notification_type,
            content_preview=content_preview,
        )
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)
        return notification

    def get_existing_notification(
        self,
        *,
        recipient_user_id: str,
        actor_user_id: str,
        moment_id: str,
        comment_id: str,
        notification_type: str,
    ) -> MomentNotification | None:
        stmt = select(MomentNotification).where(
            MomentNotification.recipient_user_id == recipient_user_id,
            MomentNotification.actor_user_id == actor_user_id,
            MomentNotification.moment_id == moment_id,
            MomentNotification.comment_id == comment_id,
            MomentNotification.notification_type == notification_type,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_notifications(
        self,
        recipient_user_id: str,
        *,
        unread_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> list[MomentNotification]:
        stmt = select(MomentNotification).where(MomentNotification.recipient_user_id == recipient_user_id)
        if unread_only:
            stmt = stmt.where(MomentNotification.read_at.is_(None))
        stmt = stmt.order_by(desc(MomentNotification.created_at)).offset(max(0, offset)).limit(max(0, limit))
        return list(self.db.execute(stmt).scalars().all())

    def count_unread_notifications(self, recipient_user_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(MomentNotification)
            .where(
                MomentNotification.recipient_user_id == recipient_user_id,
                MomentNotification.read_at.is_(None),
            )
        )
        return int(self.db.execute(stmt).scalar_one() or 0)

    def mark_notifications_read(
        self,
        recipient_user_id: str,
        *,
        notification_ids: list[str],
        read_at,
    ) -> int:
        normalized_ids = [item for item in dict.fromkeys(notification_ids) if item]
        if not normalized_ids:
            return 0
        notifications = list(
            self.db.execute(
                select(MomentNotification).where(
                    MomentNotification.recipient_user_id == recipient_user_id,
                    MomentNotification.id.in_(normalized_ids),
                    MomentNotification.read_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        for notification in notifications:
            notification.read_at = read_at
            self.db.add(notification)
        self.db.commit()
        return len(notifications)

    def delete_moment(self, moment: Moment) -> None:
        moment_id = str(moment.id or "")
        self.db.execute(delete(MomentLike).where(MomentLike.moment_id == moment_id))
        self.db.execute(delete(MomentComment).where(MomentComment.moment_id == moment_id))
        self.db.delete(moment)
        self.db.commit()

    def delete_comment(self, comment: MomentComment) -> None:
        self.db.delete(comment)
        self.db.commit()

    def get_privacy_setting(self, user_id: str) -> MomentPrivacySetting | None:
        stmt = select(MomentPrivacySetting).where(MomentPrivacySetting.user_id == user_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_privacy_settings_map(self, user_ids: list[str]) -> dict[str, MomentPrivacySetting]:
        normalized_user_ids = [item for item in dict.fromkeys(user_ids) if item]
        if not normalized_user_ids:
            return {}
        stmt = select(MomentPrivacySetting).where(MomentPrivacySetting.user_id.in_(normalized_user_ids))
        return {item.user_id: item for item in self.db.execute(stmt).scalars().all()}

    def save_privacy_setting(
        self,
        user_id: str,
        *,
        hide_my_moments_user_ids_json: str,
        hide_their_moments_user_ids_json: str,
        visible_time_scope: str,
    ) -> MomentPrivacySetting:
        setting = self.get_privacy_setting(user_id)
        if setting is None:
            setting = MomentPrivacySetting(user_id=user_id)
        setting.hide_my_moments_user_ids_json = hide_my_moments_user_ids_json
        setting.hide_their_moments_user_ids_json = hide_their_moments_user_ids_json
        setting.visible_time_scope = visible_time_scope
        self.db.add(setting)
        self.db.commit()
        self.db.refresh(setting)
        return setting
