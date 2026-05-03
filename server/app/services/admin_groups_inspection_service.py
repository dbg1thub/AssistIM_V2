"""Admin group inspection service."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.file import StoredFile
from app.models.group import Group, GroupMember
from app.models.message import Message
from app.models.session import ChatSession, SessionMember
from app.models.user import User
from app.services.admin_audit_service import AdminAuditService
from app.utils.time import isoformat_utc


class AdminGroupsInspectionService:
    """Read-only group data queries and integrity checks for admin tooling."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AdminAuditService(db)

    def list_groups(
        self,
        *,
        actor: User,
        keyword: str = "",
        owner_id: str = "",
        page: int = 1,
        size: int = 20,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        normalized_page, normalized_size = self._pagination(page, size)
        normalized_keyword = str(keyword or "").strip()
        normalized_owner_id = str(owner_id or "").strip()
        statement = select(Group)
        if normalized_keyword:
            pattern = f"%{normalized_keyword}%"
            statement = statement.where(
                Group.name.ilike(pattern)
                | (Group.id == normalized_keyword)
                | (Group.session_id == normalized_keyword)
            )
        if normalized_owner_id:
            statement = statement.where(Group.owner_id == normalized_owner_id)

        total = self._count(statement)
        groups = list(
            self.db.execute(
                statement.order_by(Group.created_at.desc(), Group.id.desc())
                .offset((normalized_page - 1) * normalized_size)
                .limit(normalized_size)
            )
            .scalars()
            .all()
        )
        context = self._summary_context(groups)
        payload = {
            "total": total,
            "page": normalized_page,
            "size": normalized_size,
            "items": [self._serialize_group_summary(group, context=context) for group in groups],
        }
        self.audit.record(
            actor=actor,
            action="admin.groups.read",
            target_type="groups",
            target_id="list",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "keyword": normalized_keyword,
                "owner_id": normalized_owner_id,
                "page": normalized_page,
                "size": normalized_size,
                "total": total,
            },
        )
        return payload

    def get_group(
        self,
        group_id: str,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        group = self._get_group_or_404(group_id)
        payload = self._serialize_group_detail(group)
        self.audit.record(
            actor=actor,
            action="admin.group.read",
            target_type="group",
            target_id=str(group.id or ""),
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={"group_id": str(group.id or "")},
        )
        return payload

    def list_members(
        self,
        group_id: str,
        *,
        actor: User,
        role: str = "",
        user_id: str = "",
        page: int = 1,
        size: int = 20,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        group = self._get_group_or_404(group_id)
        normalized_page, normalized_size = self._pagination(page, size, max_size=200)
        normalized_role = str(role or "").strip()
        normalized_user_id = str(user_id or "").strip()
        statement = select(GroupMember).where(GroupMember.group_id == str(group.id or ""))
        if normalized_role:
            statement = statement.where(GroupMember.role == normalized_role)
        if normalized_user_id:
            statement = statement.where(GroupMember.user_id == normalized_user_id)

        total = self._count(statement)
        members = list(
            self.db.execute(
                statement.order_by(GroupMember.joined_at.asc(), GroupMember.user_id.asc())
                .offset((normalized_page - 1) * normalized_size)
                .limit(normalized_size)
            )
            .scalars()
            .all()
        )
        users_by_id = self._users_by_id([str(member.user_id or "") for member in members])
        session_members_by_user_id = self._session_members_by_user_id(str(group.session_id or ""))
        payload = {
            "total": total,
            "page": normalized_page,
            "size": normalized_size,
            "group": self._serialize_group_reference(group),
            "items": [
                self._serialize_member(
                    member,
                    user=users_by_id.get(str(member.user_id or "")),
                    session_member=session_members_by_user_id.get(str(member.user_id or "")),
                )
                for member in members
            ],
        }
        self.audit.record(
            actor=actor,
            action="admin.group.members.read",
            target_type="group",
            target_id=str(group.id or ""),
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "group_id": str(group.id or ""),
                "role": normalized_role,
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
        groups = list(self.db.execute(select(Group)).scalars().all())
        users_by_id = self._users_by_id(
            [str(group.owner_id or "") for group in groups]
            + [str(member.user_id or "") for member in self.db.execute(select(GroupMember)).scalars().all()]
        )
        sessions_by_id = self._sessions_by_id([str(group.session_id or "") for group in groups])
        messages_by_id = self._messages_by_id([str(group.announcement_message_id or "") for group in groups])
        files_by_id = self._files_by_id([str(group.avatar_file_id or "") for group in groups])
        group_members_by_group = self._group_members_by_group([str(group.id or "") for group in groups])
        session_members_by_session = self._session_members_by_session([str(group.session_id or "") for group in groups])
        issues = self._health_issues(
            groups=groups,
            users_by_id=users_by_id,
            sessions_by_id=sessions_by_id,
            messages_by_id=messages_by_id,
            files_by_id=files_by_id,
            group_members_by_group=group_members_by_group,
            session_members_by_session=session_members_by_session,
        )
        payload = {
            "status": "ok" if not issues else "warning",
            "issue_count": len(issues),
            "issues": issues,
            "checks": {
                "groups": len(groups),
                "group_members": sum(len(items) for items in group_members_by_group.values()),
                "session_members_for_group_sessions": sum(len(items) for items in session_members_by_session.values()),
            },
        }
        self.audit.record(
            actor=actor,
            action="admin.groups.health.read",
            target_type="groups_health",
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
        groups: list[Group],
        users_by_id: dict[str, User],
        sessions_by_id: dict[str, ChatSession],
        messages_by_id: dict[str, Message],
        files_by_id: dict[str, StoredFile],
        group_members_by_group: dict[str, list[GroupMember]],
        session_members_by_session: dict[str, list[SessionMember]],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for group in groups:
            group_id = str(group.id or "")
            session_id = str(group.session_id or "")
            owner_id = str(group.owner_id or "")
            session = sessions_by_id.get(session_id)
            group_members = group_members_by_group.get(group_id, [])
            group_member_ids = {str(member.user_id or "") for member in group_members}
            session_members = session_members_by_session.get(session_id, [])
            session_member_ids = {str(member.user_id or "") for member in session_members}

            if session is None:
                issues.append(self._issue("group_session_missing", group, severity="error", session_id=session_id))
            elif str(session.type or "") != "group":
                issues.append(
                    self._issue(
                        "group_session_type_invalid",
                        group,
                        severity="error",
                        session_id=session_id,
                        actual_type=str(session.type or ""),
                    )
                )

            if owner_id not in users_by_id:
                issues.append(self._issue("group_owner_missing", group, severity="error", owner_id=owner_id))
            if owner_id not in group_member_ids:
                issues.append(self._issue("group_owner_not_member", group, severity="warning", owner_id=owner_id))
            if not group_members:
                issues.append(self._issue("group_without_members", group, severity="warning"))

            for member in group_members:
                member_user_id = str(member.user_id or "")
                if member_user_id not in users_by_id:
                    issues.append(
                        self._issue(
                            "group_member_user_missing",
                            group,
                            severity="error",
                            user_id=member_user_id,
                        )
                    )
                if session is not None and member_user_id not in session_member_ids:
                    issues.append(
                        self._issue(
                            "group_member_missing_session_member",
                            group,
                            severity="warning",
                            user_id=member_user_id,
                            session_id=session_id,
                        )
                    )

            if session is not None:
                for session_user_id in sorted(session_member_ids - group_member_ids):
                    issues.append(
                        self._issue(
                            "session_member_missing_group_member",
                            group,
                            severity="warning",
                            user_id=session_user_id,
                            session_id=session_id,
                        )
                    )

            announcement_message_id = str(group.announcement_message_id or "").strip()
            if announcement_message_id:
                announcement_message = messages_by_id.get(announcement_message_id)
                if announcement_message is None:
                    issues.append(
                        self._issue(
                            "group_announcement_message_missing",
                            group,
                            severity="warning",
                            announcement_message_id=announcement_message_id,
                        )
                    )
                elif str(announcement_message.session_id or "") != session_id:
                    issues.append(
                        self._issue(
                            "group_announcement_message_session_mismatch",
                            group,
                            severity="warning",
                            announcement_message_id=announcement_message_id,
                            message_session_id=str(announcement_message.session_id or ""),
                            group_session_id=session_id,
                        )
                    )

            avatar_file_id = str(group.avatar_file_id or "").strip()
            if avatar_file_id and avatar_file_id not in files_by_id:
                issues.append(
                    self._issue(
                        "group_avatar_file_missing",
                        group,
                        severity="warning",
                        avatar_file_id=avatar_file_id,
                    )
                )

        return sorted(issues, key=self._issue_sort_key)

    def _serialize_group_detail(self, group: Group) -> dict[str, Any]:
        context = self._summary_context([group])
        payload = self._serialize_group_summary(group, context=context)
        members = context["group_members_by_group"].get(str(group.id or ""), [])
        users_by_id = self._users_by_id([str(member.user_id or "") for member in members])
        session_members_by_user_id = self._session_members_by_user_id(str(group.session_id or ""))
        announcement_message_id = str(group.announcement_message_id or "").strip()
        payload["announcement_message"] = self._serialize_message(context["messages_by_id"].get(announcement_message_id))
        payload["members"] = [
            self._serialize_member(
                member,
                user=users_by_id.get(str(member.user_id or "")),
                session_member=session_members_by_user_id.get(str(member.user_id or "")),
            )
            for member in members
        ]
        return payload

    def _serialize_group_summary(self, group: Group, *, context: dict[str, Any]) -> dict[str, Any]:
        group_id = str(group.id or "")
        session_id = str(group.session_id or "")
        owner_id = str(group.owner_id or "")
        avatar_file_id = str(group.avatar_file_id or "").strip()
        group_members = context["group_members_by_group"].get(group_id, [])
        session_members = context["session_members_by_session"].get(session_id, [])
        return {
            "id": group_id,
            "name": str(group.name or ""),
            "owner_id": owner_id,
            "owner": self._serialize_user_summary(context["users_by_id"].get(owner_id), fallback_id=owner_id),
            "session_id": session_id,
            "session": self._serialize_session(context["sessions_by_id"].get(session_id), fallback_id=session_id),
            "announcement": str(group.announcement or ""),
            "announcement_message_id": str(group.announcement_message_id or "") or None,
            "announcement_author_id": str(group.announcement_author_id or "") or None,
            "announcement_published_at": isoformat_utc(group.announcement_published_at),
            "avatar_kind": str(group.avatar_kind or ""),
            "avatar_file_id": avatar_file_id or None,
            "avatar_file": self._serialize_file(context["files_by_id"].get(avatar_file_id), fallback_id=avatar_file_id),
            "avatar_version": int(group.avatar_version or 0),
            "member_count": len(group_members),
            "session_member_count": len(session_members),
            "created_at": isoformat_utc(group.created_at),
            "updated_at": isoformat_utc(group.updated_at),
        }

    def _serialize_group_reference(self, group: Group) -> dict[str, Any]:
        return {"id": str(group.id or ""), "name": str(group.name or ""), "session_id": str(group.session_id or "")}

    def _serialize_member(
        self,
        member: GroupMember,
        *,
        user: User | None,
        session_member: SessionMember | None,
    ) -> dict[str, Any]:
        user_id = str(member.user_id or "")
        return {
            "group_id": str(member.group_id or ""),
            "user_id": user_id,
            "user": self._serialize_user_summary(user, fallback_id=user_id),
            "role": str(member.role or ""),
            "group_nickname": str(member.group_nickname or ""),
            "note": str(member.note or ""),
            "joined_at": isoformat_utc(member.joined_at),
            "session_member": {
                "exists": session_member is not None,
                "last_read_seq": int(getattr(session_member, "last_read_seq", 0) or 0),
                "last_read_message_id": str(getattr(session_member, "last_read_message_id", "") or ""),
                "last_read_at": isoformat_utc(getattr(session_member, "last_read_at", None)),
            },
        }

    def _serialize_session(self, session: ChatSession | None, *, fallback_id: str = "") -> dict[str, Any]:
        if session is None:
            return {"id": str(fallback_id or ""), "exists": False}
        return {
            "id": str(session.id or ""),
            "exists": True,
            "type": str(session.type or ""),
            "name": str(session.name or ""),
            "is_ai_session": bool(session.is_ai_session),
            "encryption_mode": str(session.encryption_mode or ""),
            "last_message_seq": int(session.last_message_seq or 0),
            "last_event_seq": int(session.last_event_seq or 0),
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

    def _serialize_file(self, stored_file: StoredFile | None, *, fallback_id: str = "") -> dict[str, Any] | None:
        if not fallback_id and stored_file is None:
            return None
        if stored_file is None:
            return {"id": str(fallback_id or ""), "exists": False}
        return {
            "id": str(stored_file.id or ""),
            "exists": True,
            "storage_provider": str(stored_file.storage_provider or ""),
            "storage_key": str(stored_file.storage_key or ""),
            "file_name": str(stored_file.file_name or ""),
            "file_type": str(stored_file.file_type or ""),
            "size_bytes": int(stored_file.size_bytes or 0),
        }

    def _serialize_message(self, message: Message | None) -> dict[str, Any] | None:
        if message is None:
            return None
        return {
            "id": str(message.id or ""),
            "session_id": str(message.session_id or ""),
            "sender_id": str(message.sender_id or ""),
            "session_seq": int(message.session_seq or 0),
            "type": str(message.type or ""),
            "content": str(message.content or ""),
            "status": str(message.status or ""),
            "created_at": isoformat_utc(message.created_at),
            "updated_at": isoformat_utc(message.updated_at),
        }

    def _summary_context(self, groups: list[Group]) -> dict[str, Any]:
        group_ids = [str(group.id or "") for group in groups]
        session_ids = [str(group.session_id or "") for group in groups]
        owner_ids = [str(group.owner_id or "") for group in groups]
        avatar_file_ids = [str(group.avatar_file_id or "") for group in groups]
        announcement_message_ids = [str(group.announcement_message_id or "") for group in groups]
        return {
            "users_by_id": self._users_by_id(owner_ids),
            "sessions_by_id": self._sessions_by_id(session_ids),
            "files_by_id": self._files_by_id(avatar_file_ids),
            "messages_by_id": self._messages_by_id(announcement_message_ids),
            "group_members_by_group": self._group_members_by_group(group_ids),
            "session_members_by_session": self._session_members_by_session(session_ids),
        }

    def _group_members_by_group(self, group_ids: list[str]) -> dict[str, list[GroupMember]]:
        normalized_ids = [group_id for group_id in {str(group_id or "").strip() for group_id in group_ids} if group_id]
        if not normalized_ids:
            return {}
        rows = self.db.execute(
            select(GroupMember)
            .where(GroupMember.group_id.in_(normalized_ids))
            .order_by(GroupMember.group_id.asc(), GroupMember.joined_at.asc(), GroupMember.user_id.asc())
        ).scalars().all()
        result: dict[str, list[GroupMember]] = defaultdict(list)
        for row in rows:
            result[str(row.group_id or "")].append(row)
        return result

    def _session_members_by_session(self, session_ids: list[str]) -> dict[str, list[SessionMember]]:
        normalized_ids = [session_id for session_id in {str(session_id or "").strip() for session_id in session_ids} if session_id]
        if not normalized_ids:
            return {}
        rows = self.db.execute(
            select(SessionMember)
            .where(SessionMember.session_id.in_(normalized_ids))
            .order_by(SessionMember.session_id.asc(), SessionMember.joined_at.asc(), SessionMember.user_id.asc())
        ).scalars().all()
        result: dict[str, list[SessionMember]] = defaultdict(list)
        for row in rows:
            result[str(row.session_id or "")].append(row)
        return result

    def _session_members_by_user_id(self, session_id: str) -> dict[str, SessionMember]:
        return {
            str(member.user_id or ""): member
            for member in self._session_members_by_session([session_id]).get(str(session_id or ""), [])
        }

    def _users_by_id(self, user_ids: list[str]) -> dict[str, User]:
        normalized_ids = [user_id for user_id in {str(user_id or "").strip() for user_id in user_ids} if user_id]
        if not normalized_ids:
            return {}
        rows = self.db.execute(select(User).where(User.id.in_(normalized_ids))).scalars().all()
        return {str(row.id or ""): row for row in rows}

    def _sessions_by_id(self, session_ids: list[str]) -> dict[str, ChatSession]:
        normalized_ids = [session_id for session_id in {str(session_id or "").strip() for session_id in session_ids} if session_id]
        if not normalized_ids:
            return {}
        rows = self.db.execute(select(ChatSession).where(ChatSession.id.in_(normalized_ids))).scalars().all()
        return {str(row.id or ""): row for row in rows}

    def _messages_by_id(self, message_ids: list[str]) -> dict[str, Message]:
        normalized_ids = [message_id for message_id in {str(message_id or "").strip() for message_id in message_ids} if message_id]
        if not normalized_ids:
            return {}
        rows = self.db.execute(select(Message).where(Message.id.in_(normalized_ids))).scalars().all()
        return {str(row.id or ""): row for row in rows}

    def _files_by_id(self, file_ids: list[str]) -> dict[str, StoredFile]:
        normalized_ids = [file_id for file_id in {str(file_id or "").strip() for file_id in file_ids} if file_id]
        if not normalized_ids:
            return {}
        rows = self.db.execute(select(StoredFile).where(StoredFile.id.in_(normalized_ids))).scalars().all()
        return {str(row.id or ""): row for row in rows}

    def _get_group_or_404(self, group_id: str) -> Group:
        group = self.db.get(Group, str(group_id or "").strip())
        if group is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "group not found", 404)
        return group

    def _count(self, statement) -> int:
        return int(self.db.execute(select(func.count()).select_from(statement.order_by(None).subquery())).scalar_one() or 0)

    def _pagination(self, page: int, size: int, *, max_size: int = 100) -> tuple[int, int]:
        return max(1, int(page or 1)), min(max_size, max(1, int(size or 20)))

    def _issue(
        self,
        issue_type: str,
        group: Group,
        *,
        severity: str,
        **extra: Any,
    ) -> dict[str, Any]:
        payload = {
            "issue_type": issue_type,
            "severity": severity,
            "group_id": str(group.id or ""),
            "group_name": str(group.name or ""),
        }
        payload.update(extra)
        return payload

    def _issue_sort_key(self, issue: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(issue.get("issue_type") or ""),
            str(issue.get("group_id") or ""),
            str(issue.get("user_id") or issue.get("session_id") or issue.get("announcement_message_id") or ""),
        )
