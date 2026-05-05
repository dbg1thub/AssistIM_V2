"""Admin moments inspection service."""

from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import UUID

from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.moment import Moment, MomentComment, MomentLike
from app.models.user import User
from app.services.admin_audit_service import AdminAuditService
from app.utils.time import isoformat_utc


class AdminMomentsInspectionService:
    """Read-only moments data queries and integrity checks for admin tooling."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AdminAuditService(db)

    def list_moments(
        self,
        *,
        actor: User,
        keyword: str = "",
        user_id: str = "",
        page: int = 1,
        size: int = 20,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        normalized_page, normalized_size = self._pagination(page, size)
        normalized_keyword = str(keyword or "").strip()
        normalized_user_id = str(user_id or "").strip()
        statement = select(Moment)
        if normalized_keyword:
            pattern = f"%{normalized_keyword}%"
            conditions = [Moment.content.ilike(pattern)]
            if self._is_uuid(normalized_keyword):
                conditions.extend([Moment.id == normalized_keyword, Moment.user_id == normalized_keyword])
            statement = statement.where(or_(*conditions))
        if normalized_user_id:
            statement = (
                statement.where(Moment.user_id == normalized_user_id)
                if self._is_uuid(normalized_user_id)
                else statement.where(false())
            )

        total = self._count(statement)
        moments = list(
            self.db.execute(
                statement.order_by(Moment.created_at.desc(), Moment.id.desc())
                .offset((normalized_page - 1) * normalized_size)
                .limit(normalized_size)
            )
            .scalars()
            .all()
        )
        context = self._summary_context(moments)
        payload = {
            "total": total,
            "page": normalized_page,
            "size": normalized_size,
            "items": [self._serialize_moment(moment, context=context) for moment in moments],
        }
        self.audit.record(
            actor=actor,
            action="admin.moments.read",
            target_type="moments",
            target_id="list",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "keyword": normalized_keyword,
                "user_id": normalized_user_id,
                "page": normalized_page,
                "size": normalized_size,
                "total": total,
            },
        )
        return payload

    def get_moment(
        self,
        moment_id: str,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        moment = self._get_moment_or_404(moment_id)
        payload = self._serialize_moment(moment, context=self._summary_context([moment]))
        self.audit.record(
            actor=actor,
            action="admin.moment.read",
            target_type="moment",
            target_id=str(moment.id or ""),
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={"moment_id": str(moment.id or "")},
        )
        return payload

    def list_comments(
        self,
        moment_id: str,
        *,
        actor: User,
        user_id: str = "",
        page: int = 1,
        size: int = 20,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        moment = self._get_moment_or_404(moment_id)
        normalized_page, normalized_size = self._pagination(page, size, max_size=200)
        normalized_user_id = str(user_id or "").strip()
        statement = select(MomentComment).where(MomentComment.moment_id == str(moment.id or ""))
        if normalized_user_id:
            statement = (
                statement.where(MomentComment.user_id == normalized_user_id)
                if self._is_uuid(normalized_user_id)
                else statement.where(false())
            )

        total = self._count(statement)
        comments = list(
            self.db.execute(
                statement.order_by(MomentComment.created_at.asc(), MomentComment.id.asc())
                .offset((normalized_page - 1) * normalized_size)
                .limit(normalized_size)
            )
            .scalars()
            .all()
        )
        users_by_id = self._users_by_id([str(comment.user_id or "") for comment in comments])
        payload = {
            "total": total,
            "page": normalized_page,
            "size": normalized_size,
            "moment": self._serialize_moment_reference(moment),
            "items": [
                self._serialize_comment(comment, user=users_by_id.get(str(comment.user_id or "")))
                for comment in comments
            ],
        }
        self.audit.record(
            actor=actor,
            action="admin.moment.comments.read",
            target_type="moment",
            target_id=str(moment.id or ""),
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "moment_id": str(moment.id or ""),
                "user_id": normalized_user_id,
                "page": normalized_page,
                "size": normalized_size,
                "total": total,
            },
        )
        return payload

    def list_likes(
        self,
        moment_id: str,
        *,
        actor: User,
        user_id: str = "",
        page: int = 1,
        size: int = 20,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        moment = self._get_moment_or_404(moment_id)
        normalized_page, normalized_size = self._pagination(page, size, max_size=200)
        normalized_user_id = str(user_id or "").strip()
        statement = select(MomentLike).where(MomentLike.moment_id == str(moment.id or ""))
        if normalized_user_id:
            statement = (
                statement.where(MomentLike.user_id == normalized_user_id)
                if self._is_uuid(normalized_user_id)
                else statement.where(false())
            )

        total = self._count(statement)
        likes = list(
            self.db.execute(
                statement.order_by(MomentLike.created_at.asc(), MomentLike.user_id.asc())
                .offset((normalized_page - 1) * normalized_size)
                .limit(normalized_size)
            )
            .scalars()
            .all()
        )
        users_by_id = self._users_by_id([str(like.user_id or "") for like in likes])
        payload = {
            "total": total,
            "page": normalized_page,
            "size": normalized_size,
            "moment": self._serialize_moment_reference(moment),
            "items": [
                self._serialize_like(like, user=users_by_id.get(str(like.user_id or "")))
                for like in likes
            ],
        }
        self.audit.record(
            actor=actor,
            action="admin.moment.likes.read",
            target_type="moment",
            target_id=str(moment.id or ""),
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "moment_id": str(moment.id or ""),
                "user_id": normalized_user_id,
                "page": normalized_page,
                "size": normalized_size,
                "total": total,
            },
        )
        return payload

    def build_health(
        self,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        moments = list(self.db.execute(select(Moment)).scalars().all())
        comments = list(self.db.execute(select(MomentComment)).scalars().all())
        likes = list(self.db.execute(select(MomentLike)).scalars().all())
        users_by_id = self._users_by_id(
            [str(moment.user_id or "") for moment in moments]
            + [str(comment.user_id or "") for comment in comments]
            + [str(like.user_id or "") for like in likes]
        )
        moments_by_id = self._moments_by_id(
            [str(moment.id or "") for moment in moments]
            + [str(comment.moment_id or "") for comment in comments]
            + [str(like.moment_id or "") for like in likes]
        )
        issues = self._health_issues(
            moments=moments,
            comments=comments,
            likes=likes,
            users_by_id=users_by_id,
            moments_by_id=moments_by_id,
        )
        payload = {
            "status": "ok" if not issues else "warning",
            "issue_count": len(issues),
            "issues": issues,
            "checks": {
                "moments": len(moments),
                "moment_comments": len(comments),
                "moment_likes": len(likes),
            },
        }
        self.audit.record(
            actor=actor,
            action="admin.moments.health.read",
            target_type="moments_health",
            target_id="health",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={"status": payload["status"], "issue_count": len(issues)},
        )
        return payload

    def _health_issues(
        self,
        *,
        moments: list[Moment],
        comments: list[MomentComment],
        likes: list[MomentLike],
        users_by_id: dict[str, User],
        moments_by_id: dict[str, Moment],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for moment in moments:
            user_id = str(moment.user_id or "")
            if user_id not in users_by_id:
                issues.append(
                    self._issue(
                        "moment_author_missing",
                        severity="error",
                        moment_id=str(moment.id or ""),
                        user_id=user_id,
                    )
                )

        for comment in comments:
            moment_id = str(comment.moment_id or "")
            user_id = str(comment.user_id or "")
            if moment_id not in moments_by_id:
                issues.append(
                    self._issue(
                        "moment_comment_moment_missing",
                        severity="error",
                        comment_id=str(comment.id or ""),
                        moment_id=moment_id,
                        user_id=user_id,
                    )
                )
            if user_id not in users_by_id:
                issues.append(
                    self._issue(
                        "moment_comment_user_missing",
                        severity="error",
                        comment_id=str(comment.id or ""),
                        moment_id=moment_id,
                        user_id=user_id,
                    )
                )

        like_keys = Counter((str(like.moment_id or ""), str(like.user_id or "")) for like in likes)
        emitted_duplicate_keys: set[tuple[str, str]] = set()
        for like in likes:
            moment_id = str(like.moment_id or "")
            user_id = str(like.user_id or "")
            if moment_id not in moments_by_id:
                issues.append(
                    self._issue(
                        "moment_like_moment_missing",
                        severity="error",
                        moment_id=moment_id,
                        user_id=user_id,
                    )
                )
            if user_id not in users_by_id:
                issues.append(
                    self._issue(
                        "moment_like_user_missing",
                        severity="error",
                        moment_id=moment_id,
                        user_id=user_id,
                    )
                )

            duplicate_key = (moment_id, user_id)
            duplicate_count = like_keys[duplicate_key]
            if duplicate_count > 1 and duplicate_key not in emitted_duplicate_keys:
                emitted_duplicate_keys.add(duplicate_key)
                issues.append(
                    self._issue(
                        "duplicate_moment_like",
                        severity="warning",
                        moment_id=moment_id,
                        user_id=user_id,
                        count=duplicate_count,
                    )
                )

        return sorted(issues, key=self._issue_sort_key)

    def _serialize_moment(self, moment: Moment, *, context: dict[str, Any]) -> dict[str, Any]:
        moment_id = str(moment.id or "")
        user_id = str(moment.user_id or "")
        return {
            "id": moment_id,
            "user_id": user_id,
            "author": self._serialize_user_summary(context["users_by_id"].get(user_id), fallback_id=user_id),
            "content": str(moment.content or ""),
            "visibility_scope": str(getattr(moment, "visibility_scope", "") or "public"),
            "comment_count": int(context["comment_counts"].get(moment_id, 0) or 0),
            "like_count": int(context["like_counts"].get(moment_id, 0) or 0),
            "created_at": isoformat_utc(moment.created_at),
            "updated_at": isoformat_utc(moment.updated_at),
        }

    def _serialize_comment(self, comment: MomentComment, *, user: User | None) -> dict[str, Any]:
        user_id = str(comment.user_id or "")
        return {
            "id": str(comment.id or ""),
            "moment_id": str(comment.moment_id or ""),
            "user_id": user_id,
            "user": self._serialize_user_summary(user, fallback_id=user_id),
            "content": str(comment.content or ""),
            "created_at": isoformat_utc(comment.created_at),
            "updated_at": isoformat_utc(comment.updated_at),
        }

    def _serialize_like(self, like: MomentLike, *, user: User | None) -> dict[str, Any]:
        user_id = str(like.user_id or "")
        return {
            "moment_id": str(like.moment_id or ""),
            "user_id": user_id,
            "user": self._serialize_user_summary(user, fallback_id=user_id),
            "created_at": isoformat_utc(like.created_at),
            "updated_at": isoformat_utc(like.updated_at),
        }

    def _serialize_moment_reference(self, moment: Moment) -> dict[str, Any]:
        return {
            "id": str(moment.id or ""),
            "user_id": str(moment.user_id or ""),
            "content": str(moment.content or ""),
            "visibility_scope": str(getattr(moment, "visibility_scope", "") or "public"),
        }

    def _serialize_user_summary(self, user: User | None, *, fallback_id: str = "") -> dict[str, Any]:
        if user is None:
            return {"id": str(fallback_id or ""), "exists": False}
        return {
            "id": str(user.id or ""),
            "username": str(user.username or ""),
            "nickname": str(user.nickname or ""),
            "avatar": user.avatar,
            "is_disabled": bool(user.is_disabled),
            "exists": True,
        }

    def _summary_context(self, moments: list[Moment]) -> dict[str, Any]:
        moment_ids = [str(moment.id or "") for moment in moments]
        return {
            "users_by_id": self._users_by_id([str(moment.user_id or "") for moment in moments]),
            "comment_counts": self._comment_counts(moment_ids),
            "like_counts": self._like_counts(moment_ids),
        }

    def _users_by_id(self, user_ids: list[str]) -> dict[str, User]:
        normalized_ids = sorted({str(user_id or "").strip() for user_id in user_ids if str(user_id or "").strip()})
        if not normalized_ids:
            return {}
        users = self.db.execute(select(User).where(User.id.in_(normalized_ids))).scalars().all()
        return {str(user.id or ""): user for user in users}

    def _moments_by_id(self, moment_ids: list[str]) -> dict[str, Moment]:
        normalized_ids = sorted({str(moment_id or "").strip() for moment_id in moment_ids if str(moment_id or "").strip()})
        if not normalized_ids:
            return {}
        moments = self.db.execute(select(Moment).where(Moment.id.in_(normalized_ids))).scalars().all()
        return {str(moment.id or ""): moment for moment in moments}

    def _comment_counts(self, moment_ids: list[str]) -> dict[str, int]:
        normalized_ids = [moment_id for moment_id in {str(moment_id or "").strip() for moment_id in moment_ids} if moment_id]
        if not normalized_ids:
            return {}
        rows = self.db.execute(
            select(MomentComment.moment_id, func.count(MomentComment.id))
            .where(MomentComment.moment_id.in_(normalized_ids))
            .group_by(MomentComment.moment_id)
        ).all()
        return {str(moment_id or ""): int(count or 0) for moment_id, count in rows}

    def _like_counts(self, moment_ids: list[str]) -> dict[str, int]:
        normalized_ids = [moment_id for moment_id in {str(moment_id or "").strip() for moment_id in moment_ids} if moment_id]
        if not normalized_ids:
            return {}
        rows = self.db.execute(
            select(MomentLike.moment_id, func.count(MomentLike.user_id))
            .where(MomentLike.moment_id.in_(normalized_ids))
            .group_by(MomentLike.moment_id)
        ).all()
        return {str(moment_id or ""): int(count or 0) for moment_id, count in rows}

    def _get_moment_or_404(self, moment_id: str) -> Moment:
        normalized_id = str(moment_id or "").strip()
        if not self._is_uuid(normalized_id):
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "moment not found", 404)
        moment = self.db.get(Moment, normalized_id)
        if moment is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "moment not found", 404)
        return moment

    def _count(self, statement) -> int:
        return int(self.db.execute(select(func.count()).select_from(statement.order_by(None).subquery())).scalar_one() or 0)

    def _pagination(self, page: int, size: int, *, max_size: int = 100) -> tuple[int, int]:
        return max(1, int(page or 1)), min(max_size, max(1, int(size or 20)))

    def _is_uuid(self, value: str) -> bool:
        try:
            UUID(str(value or ""))
        except ValueError:
            return False
        return True

    def _issue(self, issue_type: str, *, severity: str, **extra: Any) -> dict[str, Any]:
        payload = {"issue_type": issue_type, "severity": severity}
        payload.update(extra)
        return payload

    def _issue_sort_key(self, issue: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(issue.get("issue_type") or ""),
            str(issue.get("moment_id") or ""),
            str(issue.get("user_id") or ""),
            str(issue.get("comment_id") or ""),
        )
