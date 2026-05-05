"""Admin contacts and friendship inspection service."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import FriendRequest, Friendship, User, UserBlock
from app.services.admin_audit_service import AdminAuditService
from app.utils.time import isoformat_utc


VALID_FRIEND_REQUEST_STATUSES = {"accepted", "expired", "pending", "rejected"}


class AdminContactsInspectionService:
    """Read-only contacts data queries and integrity checks for admin tooling."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AdminAuditService(db)

    def list_friend_requests(
        self,
        *,
        actor: User,
        status: str = "",
        sender_id: str = "",
        receiver_id: str = "",
        page: int = 1,
        size: int = 20,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        normalized_page, normalized_size = self._pagination(page, size)
        statement = select(FriendRequest)
        normalized_status = str(status or "").strip()
        normalized_sender_id = str(sender_id or "").strip()
        normalized_receiver_id = str(receiver_id or "").strip()
        if normalized_status:
            statement = statement.where(FriendRequest.status == normalized_status)
        if normalized_sender_id:
            statement = statement.where(FriendRequest.sender_id == normalized_sender_id)
        if normalized_receiver_id:
            statement = statement.where(FriendRequest.receiver_id == normalized_receiver_id)

        total = self._count(statement)
        requests = list(
            self.db.execute(
                statement.order_by(FriendRequest.created_at.desc(), FriendRequest.id.desc())
                .offset((normalized_page - 1) * normalized_size)
                .limit(normalized_size)
            )
            .scalars()
            .all()
        )
        users_by_id = self._users_by_id(
            [
                user_id
                for item in requests
                for user_id in (str(item.sender_id or ""), str(item.receiver_id or ""))
            ]
        )
        payload = {
            "total": total,
            "page": normalized_page,
            "size": normalized_size,
            "items": [
                self._serialize_friend_request(item, users_by_id=users_by_id)
                for item in requests
            ],
        }
        self.audit.record(
            actor=actor,
            action="admin.contacts.friend_requests.read",
            target_type="friend_requests",
            target_id="list",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "status": normalized_status,
                "sender_id": normalized_sender_id,
                "receiver_id": normalized_receiver_id,
                "page": normalized_page,
                "size": normalized_size,
                "total": total,
            },
        )
        return payload

    def list_friendships(
        self,
        *,
        actor: User,
        user_id: str = "",
        friend_id: str = "",
        page: int = 1,
        size: int = 20,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        normalized_page, normalized_size = self._pagination(page, size)
        statement = select(Friendship)
        normalized_user_id = str(user_id or "").strip()
        normalized_friend_id = str(friend_id or "").strip()
        if normalized_user_id:
            statement = statement.where(Friendship.user_id == normalized_user_id)
        if normalized_friend_id:
            statement = statement.where(Friendship.friend_id == normalized_friend_id)

        total = self._count(statement)
        friendships = list(
            self.db.execute(
                statement.order_by(Friendship.created_at.desc(), Friendship.id.desc())
                .offset((normalized_page - 1) * normalized_size)
                .limit(normalized_size)
            )
            .scalars()
            .all()
        )
        users_by_id = self._users_by_id(
            [
                user_id
                for item in friendships
                for user_id in (str(item.user_id or ""), str(item.friend_id or ""))
            ]
        )
        payload = {
            "total": total,
            "page": normalized_page,
            "size": normalized_size,
            "items": [
                self._serialize_friendship(item, users_by_id=users_by_id)
                for item in friendships
            ],
        }
        self.audit.record(
            actor=actor,
            action="admin.contacts.friendships.read",
            target_type="friendships",
            target_id="list",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "user_id": normalized_user_id,
                "friend_id": normalized_friend_id,
                "page": normalized_page,
                "size": normalized_size,
                "total": total,
            },
        )
        return payload

    def list_blocks(
        self,
        *,
        actor: User,
        user_id: str = "",
        blocked_user_id: str = "",
        page: int = 1,
        size: int = 20,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        normalized_page, normalized_size = self._pagination(page, size)
        statement = select(UserBlock)
        normalized_user_id = str(user_id or "").strip()
        normalized_blocked_user_id = str(blocked_user_id or "").strip()
        if normalized_user_id:
            statement = statement.where(UserBlock.user_id == normalized_user_id)
        if normalized_blocked_user_id:
            statement = statement.where(UserBlock.blocked_user_id == normalized_blocked_user_id)

        total = self._count(statement)
        blocks = list(
            self.db.execute(
                statement.order_by(UserBlock.created_at.desc(), UserBlock.id.desc())
                .offset((normalized_page - 1) * normalized_size)
                .limit(normalized_size)
            )
            .scalars()
            .all()
        )
        users_by_id = self._users_by_id(
            [
                user_id
                for item in blocks
                for user_id in (str(item.user_id or ""), str(item.blocked_user_id or ""))
            ]
        )
        payload = {
            "total": total,
            "page": normalized_page,
            "size": normalized_size,
            "items": [
                self._serialize_block(item, users_by_id=users_by_id)
                for item in blocks
            ],
        }
        self.audit.record(
            actor=actor,
            action="admin.contacts.blocks.read",
            target_type="blocks",
            target_id="list",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "user_id": normalized_user_id,
                "blocked_user_id": normalized_blocked_user_id,
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
        users = list(self.db.execute(select(User)).scalars().all())
        friendships = list(self.db.execute(select(Friendship)).scalars().all())
        requests = list(self.db.execute(select(FriendRequest)).scalars().all())
        blocks = list(self.db.execute(select(UserBlock)).scalars().all())
        user_ids = {str(user.id or "") for user in users}
        issues = self._health_issues(user_ids=user_ids, friendships=friendships, requests=requests, blocks=blocks)
        payload = {
            "status": "ok" if not issues else "warning",
            "issue_count": len(issues),
            "issues": issues,
            "checks": {
                "users": len(users),
                "friendships": len(friendships),
                "friend_requests": len(requests),
                "blocks": len(blocks),
            },
        }
        self.audit.record(
            actor=actor,
            action="admin.contacts.health.read",
            target_type="contacts_health",
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
        user_ids: set[str],
        friendships: list[Friendship],
        requests: list[FriendRequest],
        blocks: list[UserBlock],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        friendship_pairs = {
            (str(item.user_id or ""), str(item.friend_id or ""))
            for item in friendships
        }
        for friendship in friendships:
            user_id = str(friendship.user_id or "")
            friend_id = str(friendship.friend_id or "")
            if user_id not in user_ids:
                issues.append(
                    {
                        "issue_type": "friendship_user_missing",
                        "severity": "error",
                        "friendship_id": str(friendship.id or ""),
                        "user_id": user_id,
                        "friend_id": friend_id,
                    }
                )
            if friend_id not in user_ids:
                issues.append(
                    {
                        "issue_type": "friendship_friend_missing",
                        "severity": "error",
                        "friendship_id": str(friendship.id or ""),
                        "user_id": user_id,
                        "friend_id": friend_id,
                    }
                )
            if user_id == friend_id:
                issues.append(
                    {
                        "issue_type": "self_friendship",
                        "severity": "error",
                        "friendship_id": str(friendship.id or ""),
                        "user_id": user_id,
                        "friend_id": friend_id,
                    }
                )
                continue
            if user_id in user_ids and friend_id in user_ids and (friend_id, user_id) not in friendship_pairs:
                issues.append(
                    {
                        "issue_type": "friendship_missing_reverse",
                        "severity": "warning",
                        "friendship_id": str(friendship.id or ""),
                        "user_id": user_id,
                        "friend_id": friend_id,
                    }
                )

        request_groups = Counter(
            (str(item.sender_id or ""), str(item.receiver_id or ""), str(item.status or ""))
            for item in requests
        )
        emitted_duplicate_keys: set[tuple[str, str, str]] = set()
        for request in requests:
            sender_id = str(request.sender_id or "")
            receiver_id = str(request.receiver_id or "")
            status = str(request.status or "")
            if sender_id not in user_ids:
                issues.append(
                    {
                        "issue_type": "friend_request_sender_missing",
                        "severity": "error",
                        "request_id": str(request.id or ""),
                        "sender_id": sender_id,
                        "receiver_id": receiver_id,
                        "status": status,
                    }
                )
            if receiver_id not in user_ids:
                issues.append(
                    {
                        "issue_type": "friend_request_receiver_missing",
                        "severity": "error",
                        "request_id": str(request.id or ""),
                        "sender_id": sender_id,
                        "receiver_id": receiver_id,
                        "status": status,
                    }
                )
            if sender_id == receiver_id:
                issues.append(
                    {
                        "issue_type": "self_friend_request",
                        "severity": "error",
                        "request_id": str(request.id or ""),
                        "sender_id": sender_id,
                        "receiver_id": receiver_id,
                        "status": status,
                    }
                )
            if status not in VALID_FRIEND_REQUEST_STATUSES:
                issues.append(
                    {
                        "issue_type": "invalid_friend_request_status",
                        "severity": "warning",
                        "request_id": str(request.id or ""),
                        "sender_id": sender_id,
                        "receiver_id": receiver_id,
                        "status": status,
                    }
                )

            duplicate_key = (sender_id, receiver_id, status)
            duplicate_count = request_groups[duplicate_key]
            if duplicate_count > 1 and duplicate_key not in emitted_duplicate_keys:
                emitted_duplicate_keys.add(duplicate_key)
                issues.append(
                    {
                        "issue_type": "duplicate_friend_request",
                        "severity": "warning",
                        "sender_id": sender_id,
                        "receiver_id": receiver_id,
                        "status": status,
                        "count": duplicate_count,
                    }
                )

        block_groups = Counter(
            (str(item.user_id or ""), str(item.blocked_user_id or ""))
            for item in blocks
        )
        blocked_pairs = {
            frozenset((str(item.user_id or ""), str(item.blocked_user_id or "")))
            for item in blocks
            if str(item.user_id or "").strip() and str(item.blocked_user_id or "").strip()
        }
        emitted_duplicate_block_keys: set[tuple[str, str]] = set()
        for block in blocks:
            user_id = str(block.user_id or "")
            blocked_user_id = str(block.blocked_user_id or "")
            if user_id not in user_ids:
                issues.append(
                    {
                        "issue_type": "block_user_missing",
                        "severity": "error",
                        "block_id": str(block.id or ""),
                        "user_id": user_id,
                        "blocked_user_id": blocked_user_id,
                    }
                )
            if blocked_user_id not in user_ids:
                issues.append(
                    {
                        "issue_type": "block_blocked_user_missing",
                        "severity": "error",
                        "block_id": str(block.id or ""),
                        "user_id": user_id,
                        "blocked_user_id": blocked_user_id,
                    }
                )
            if user_id == blocked_user_id:
                issues.append(
                    {
                        "issue_type": "self_block",
                        "severity": "error",
                        "block_id": str(block.id or ""),
                        "user_id": user_id,
                        "blocked_user_id": blocked_user_id,
                    }
                )
            duplicate_key = (user_id, blocked_user_id)
            duplicate_count = block_groups[duplicate_key]
            if duplicate_count > 1 and duplicate_key not in emitted_duplicate_block_keys:
                emitted_duplicate_block_keys.add(duplicate_key)
                issues.append(
                    {
                        "issue_type": "duplicate_user_block",
                        "severity": "warning",
                        "block_id": str(block.id or ""),
                        "user_id": user_id,
                        "blocked_user_id": blocked_user_id,
                        "count": duplicate_count,
                    }
                )

        for friendship in friendships:
            user_id = str(friendship.user_id or "")
            friend_id = str(friendship.friend_id or "")
            if user_id and friend_id and frozenset((user_id, friend_id)) in blocked_pairs:
                issues.append(
                    {
                        "issue_type": "blocked_friendship_conflict",
                        "severity": "error",
                        "friendship_id": str(friendship.id or ""),
                        "user_id": user_id,
                        "friend_id": friend_id,
                    }
                )

        for request in requests:
            sender_id = str(request.sender_id or "")
            receiver_id = str(request.receiver_id or "")
            status = str(request.status or "")
            if status == "pending" and sender_id and receiver_id and frozenset((sender_id, receiver_id)) in blocked_pairs:
                issues.append(
                    {
                        "issue_type": "blocked_friend_request_conflict",
                        "severity": "error",
                        "request_id": str(request.id or ""),
                        "sender_id": sender_id,
                        "receiver_id": receiver_id,
                        "status": status,
                    }
                )

        return sorted(issues, key=self._issue_sort_key)

    def _serialize_friend_request(
        self,
        request: FriendRequest,
        *,
        users_by_id: dict[str, User],
    ) -> dict[str, Any]:
        sender_id = str(request.sender_id or "")
        receiver_id = str(request.receiver_id or "")
        return {
            "id": str(request.id or ""),
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "status": str(request.status or ""),
            "message": request.message,
            "sender": self._serialize_user_summary(users_by_id.get(sender_id), fallback_id=sender_id),
            "receiver": self._serialize_user_summary(users_by_id.get(receiver_id), fallback_id=receiver_id),
            "created_at": isoformat_utc(request.created_at),
            "updated_at": isoformat_utc(request.updated_at),
        }

    def _serialize_friendship(
        self,
        friendship: Friendship,
        *,
        users_by_id: dict[str, User],
    ) -> dict[str, Any]:
        user_id = str(friendship.user_id or "")
        friend_id = str(friendship.friend_id or "")
        return {
            "id": str(friendship.id or ""),
            "user_id": user_id,
            "friend_id": friend_id,
            "user": self._serialize_user_summary(users_by_id.get(user_id), fallback_id=user_id),
            "friend": self._serialize_user_summary(users_by_id.get(friend_id), fallback_id=friend_id),
            "created_at": isoformat_utc(friendship.created_at),
            "updated_at": isoformat_utc(friendship.updated_at),
        }

    def _serialize_block(
        self,
        block: UserBlock,
        *,
        users_by_id: dict[str, User],
    ) -> dict[str, Any]:
        user_id = str(block.user_id or "")
        blocked_user_id = str(block.blocked_user_id or "")
        return {
            "id": str(block.id or ""),
            "user_id": user_id,
            "blocked_user_id": blocked_user_id,
            "user": self._serialize_user_summary(users_by_id.get(user_id), fallback_id=user_id),
            "blocked_user": self._serialize_user_summary(users_by_id.get(blocked_user_id), fallback_id=blocked_user_id),
            "created_at": isoformat_utc(block.created_at),
            "updated_at": isoformat_utc(block.updated_at),
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

    def _users_by_id(self, user_ids: list[str]) -> dict[str, User]:
        normalized_ids = sorted({str(user_id or "").strip() for user_id in user_ids if str(user_id or "").strip()})
        if not normalized_ids:
            return {}
        users = self.db.execute(select(User).where(User.id.in_(normalized_ids))).scalars().all()
        return {str(user.id or ""): user for user in users}

    def _count(self, statement) -> int:
        return int(self.db.execute(select(func.count()).select_from(statement.order_by(None).subquery())).scalar_one() or 0)

    def _pagination(self, page: int, size: int, *, max_size: int = 100) -> tuple[int, int]:
        return max(1, int(page or 1)), min(max_size, max(1, int(size or 20)))

    def _issue_sort_key(self, issue: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(issue.get("issue_type") or ""),
            str(issue.get("user_id") or issue.get("sender_id") or ""),
            str(issue.get("friend_id") or issue.get("receiver_id") or issue.get("blocked_user_id") or ""),
            str(issue.get("friendship_id") or issue.get("request_id") or issue.get("block_id") or ""),
        )
