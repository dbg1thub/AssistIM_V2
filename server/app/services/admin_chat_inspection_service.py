"""Admin chat data inspection service."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.message import Message
from app.models.session import ChatSession, SessionMember
from app.models.user import User
from app.services.admin_audit_service import AdminAuditService
from app.utils.time import isoformat_utc


class AdminChatInspectionService:
    """Read-only chat data queries and integrity checks for admin tooling."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AdminAuditService(db)

    def list_sessions(
        self,
        *,
        actor: User,
        session_type: str = "",
        keyword: str = "",
        user_id: str = "",
        page: int = 1,
        size: int = 20,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        normalized_page, normalized_size = self._pagination(page, size)
        statement = select(ChatSession)
        statement = self._apply_session_filters(
            statement,
            session_type=session_type,
            keyword=keyword,
            user_id=user_id,
        )
        total = self._count(statement)
        sessions = list(
            self.db.execute(
                statement.order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
                .offset((normalized_page - 1) * normalized_size)
                .limit(normalized_size)
            )
            .scalars()
            .all()
        )
        session_ids = [str(session.id or "") for session in sessions]
        member_counts = self._member_counts(session_ids)
        message_counts = self._message_counts(session_ids)
        last_messages = self._last_messages(session_ids)

        payload = {
            "total": total,
            "page": normalized_page,
            "size": normalized_size,
            "items": [
                self._serialize_session_summary(
                    session,
                    member_count=member_counts.get(str(session.id or ""), 0),
                    message_count=message_counts.get(str(session.id or ""), 0),
                    last_message=last_messages.get(str(session.id or "")),
                )
                for session in sessions
            ],
        }
        self.audit.record(
            actor=actor,
            action="admin.chat.sessions.read",
            target_type="chat_sessions",
            target_id="list",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "type": str(session_type or "").strip(),
                "keyword": str(keyword or "").strip(),
                "user_id": str(user_id or "").strip(),
                "page": normalized_page,
                "size": normalized_size,
                "total": total,
            },
        )
        return payload

    def get_session(
        self,
        session_id: str,
        *,
        actor: User,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        session = self._get_session_or_404(session_id)
        members = self._members_for_session(str(session.id or ""))
        message_count = self._message_count(str(session.id or ""))
        last_message = self._last_messages([str(session.id or "")]).get(str(session.id or ""))
        payload = self._serialize_session_detail(
            session,
            members=members,
            message_count=message_count,
            last_message=last_message,
        )
        self.audit.record(
            actor=actor,
            action="admin.chat.session.read",
            target_type="chat_session",
            target_id=str(session.id or ""),
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={"session_id": str(session.id or "")},
        )
        return payload

    def list_messages(
        self,
        session_id: str,
        *,
        actor: User,
        message_type: str = "",
        page: int = 1,
        size: int = 50,
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> dict[str, Any]:
        session = self._get_session_or_404(session_id)
        normalized_page, normalized_size = self._pagination(page, size, max_size=200)
        statement = select(Message).where(Message.session_id == str(session.id or ""))
        normalized_type = str(message_type or "").strip()
        if normalized_type:
            statement = statement.where(Message.type == normalized_type)
        total = self._count(statement)
        messages = list(
            self.db.execute(
                statement.order_by(Message.session_seq.asc(), Message.created_at.asc(), Message.id.asc())
                .offset((normalized_page - 1) * normalized_size)
                .limit(normalized_size)
            )
            .scalars()
            .all()
        )
        users_by_id = self._users_by_id([str(message.sender_id or "") for message in messages])
        payload = {
            "total": total,
            "page": normalized_page,
            "size": normalized_size,
            "session": self._serialize_session_reference(session),
            "items": [
                self._serialize_message(message, sender=users_by_id.get(str(message.sender_id or "")))
                for message in messages
            ],
        }
        self.audit.record(
            actor=actor,
            action="admin.chat.messages.read",
            target_type="chat_session",
            target_id=str(session.id or ""),
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={
                "session_id": str(session.id or ""),
                "type": normalized_type,
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
        sessions = list(self.db.execute(select(ChatSession)).scalars().all())
        messages = list(self.db.execute(select(Message)).scalars().all())
        members = list(self.db.execute(select(SessionMember)).scalars().all())
        issues = self._health_issues(sessions=sessions, messages=messages, members=members)
        payload = {
            "status": "ok" if not issues else "warning",
            "issue_count": len(issues),
            "issues": issues,
            "checks": {
                "sessions": len(sessions),
                "messages": len(messages),
                "session_members": len(members),
            },
        }
        self.audit.record(
            actor=actor,
            action="admin.chat.health.read",
            target_type="chat_health",
            target_id="health",
            request_path=request_path,
            request_method=request_method,
            client_ip=client_ip,
            success=True,
            detail={"status": payload["status"], "issue_count": len(issues)},
        )
        return payload

    def _apply_session_filters(
        self,
        statement,
        *,
        session_type: str,
        keyword: str,
        user_id: str,
    ):
        normalized_type = str(session_type or "").strip()
        if normalized_type:
            statement = statement.where(ChatSession.type == normalized_type)
        normalized_keyword = str(keyword or "").strip()
        if normalized_keyword:
            pattern = f"%{normalized_keyword}%"
            statement = statement.where(
                ChatSession.name.ilike(pattern) | (ChatSession.id == normalized_keyword)
            )
        normalized_user_id = str(user_id or "").strip()
        if normalized_user_id:
            statement = statement.join(SessionMember, SessionMember.session_id == ChatSession.id).where(
                SessionMember.user_id == normalized_user_id
            )
        return statement

    def _health_issues(
        self,
        *,
        sessions: list[ChatSession],
        messages: list[Message],
        members: list[SessionMember],
    ) -> list[dict[str, Any]]:
        session_ids = {str(session.id or "") for session in sessions}
        members_by_session: dict[str, set[str]] = defaultdict(set)
        for member in members:
            members_by_session[str(member.session_id or "")].add(str(member.user_id or ""))

        messages_by_session: dict[str, list[Message]] = defaultdict(list)
        issues: list[dict[str, Any]] = []
        for message in messages:
            message_session_id = str(message.session_id or "")
            if message_session_id not in session_ids:
                issues.append(
                    {
                        "issue_type": "orphan_message",
                        "severity": "error",
                        "message_id": str(message.id or ""),
                        "session_id": message_session_id,
                        "session_seq": int(message.session_seq or 0),
                    }
                )
                continue
            messages_by_session[message_session_id].append(message)
            sender_id = str(message.sender_id or "")
            if sender_id not in members_by_session.get(message_session_id, set()):
                issues.append(
                    {
                        "issue_type": "message_sender_not_member",
                        "severity": "warning",
                        "message_id": str(message.id or ""),
                        "session_id": message_session_id,
                        "sender_id": sender_id,
                        "session_seq": int(message.session_seq or 0),
                    }
                )

        for session in sessions:
            session_id = str(session.id or "")
            if not members_by_session.get(session_id):
                issues.append(
                    {
                        "issue_type": "session_without_members",
                        "severity": "warning",
                        "session_id": session_id,
                        "type": str(session.type or ""),
                        "name": str(session.name or ""),
                    }
                )

            session_messages = messages_by_session.get(session_id, [])
            positive_seqs = sorted(int(message.session_seq or 0) for message in session_messages if int(message.session_seq or 0) > 0)
            if positive_seqs:
                duplicate_seqs = sorted(seq for seq, count in self._seq_counts(positive_seqs).items() if count > 1)
                for duplicate_seq in duplicate_seqs:
                    issues.append(
                        {
                            "issue_type": "duplicate_session_seq",
                            "severity": "error",
                            "session_id": session_id,
                            "session_seq": duplicate_seq,
                            "count": self._seq_counts(positive_seqs)[duplicate_seq],
                        }
                    )

                missing = [seq for seq in range(1, max(positive_seqs) + 1) if seq not in set(positive_seqs)]
                if missing:
                    issues.append(
                        {
                            "issue_type": "session_seq_gap",
                            "severity": "warning",
                            "session_id": session_id,
                            "missing_session_seq": missing,
                            "max_session_seq": max(positive_seqs),
                        }
                    )

            expected_last_seq = max((int(message.session_seq or 0) for message in session_messages), default=0)
            recorded_last_seq = int(session.last_message_seq or 0)
            if expected_last_seq != recorded_last_seq:
                issues.append(
                    {
                        "issue_type": "last_message_seq_mismatch",
                        "severity": "warning",
                        "session_id": session_id,
                        "recorded_last_message_seq": recorded_last_seq,
                        "expected_last_message_seq": expected_last_seq,
                    }
                )

        return sorted(issues, key=self._issue_sort_key)

    def _serialize_session_summary(
        self,
        session: ChatSession,
        *,
        member_count: int,
        message_count: int,
        last_message: Message | None,
    ) -> dict[str, Any]:
        return {
            **self._serialize_session_reference(session),
            "avatar": session.avatar,
            "is_ai_session": bool(session.is_ai_session),
            "encryption_mode": str(session.encryption_mode or ""),
            "member_count": int(member_count or 0),
            "message_count": int(message_count or 0),
            "last_message_seq": int(session.last_message_seq or 0),
            "last_event_seq": int(session.last_event_seq or 0),
            "last_message": self._serialize_message(last_message) if last_message is not None else None,
            "created_at": isoformat_utc(session.created_at),
            "updated_at": isoformat_utc(session.updated_at),
        }

    def _serialize_session_detail(
        self,
        session: ChatSession,
        *,
        members: list[SessionMember],
        message_count: int,
        last_message: Message | None,
    ) -> dict[str, Any]:
        user_ids = [str(member.user_id or "") for member in members]
        users_by_id = self._users_by_id(user_ids)
        return {
            **self._serialize_session_summary(
                session,
                member_count=len(members),
                message_count=message_count,
                last_message=last_message,
            ),
            "members": [
                self._serialize_member(member, user=users_by_id.get(str(member.user_id or "")))
                for member in members
            ],
        }

    def _serialize_session_reference(self, session: ChatSession) -> dict[str, Any]:
        return {
            "id": str(session.id or ""),
            "type": str(session.type or ""),
            "name": str(session.name or ""),
        }

    def _serialize_member(self, member: SessionMember, *, user: User | None) -> dict[str, Any]:
        return {
            "user_id": str(member.user_id or ""),
            "username": str(getattr(user, "username", "") or ""),
            "nickname": str(getattr(user, "nickname", "") or ""),
            "joined_at": isoformat_utc(member.joined_at),
            "last_read_seq": int(member.last_read_seq or 0),
            "last_read_message_id": str(member.last_read_message_id or ""),
            "last_read_at": isoformat_utc(member.last_read_at),
        }

    def _serialize_message(self, message: Message | None, *, sender: User | None = None) -> dict[str, Any] | None:
        if message is None:
            return None
        return {
            "id": str(message.id or ""),
            "session_id": str(message.session_id or ""),
            "sender_id": str(message.sender_id or ""),
            "sender_username": str(getattr(sender, "username", "") or ""),
            "sender_nickname": str(getattr(sender, "nickname", "") or ""),
            "session_seq": int(message.session_seq or 0),
            "type": str(message.type or ""),
            "content": str(message.content or ""),
            "status": str(message.status or ""),
            "extra": self._load_extra(message.extra_json),
            "created_at": isoformat_utc(message.created_at),
            "updated_at": isoformat_utc(message.updated_at),
        }

    def _members_for_session(self, session_id: str) -> list[SessionMember]:
        return list(
            self.db.execute(
                select(SessionMember)
                .where(SessionMember.session_id == session_id)
                .order_by(SessionMember.joined_at.asc(), SessionMember.user_id.asc())
            )
            .scalars()
            .all()
        )

    def _member_counts(self, session_ids: list[str]) -> dict[str, int]:
        if not session_ids:
            return {}
        rows = self.db.execute(
            select(SessionMember.session_id, func.count())
            .where(SessionMember.session_id.in_(session_ids))
            .group_by(SessionMember.session_id)
        ).all()
        return {str(session_id or ""): int(count or 0) for session_id, count in rows}

    def _message_counts(self, session_ids: list[str]) -> dict[str, int]:
        if not session_ids:
            return {}
        rows = self.db.execute(
            select(Message.session_id, func.count())
            .where(Message.session_id.in_(session_ids))
            .group_by(Message.session_id)
        ).all()
        return {str(session_id or ""): int(count or 0) for session_id, count in rows}

    def _message_count(self, session_id: str) -> int:
        return int(
            self.db.execute(select(func.count()).select_from(Message).where(Message.session_id == session_id)).scalar_one()
            or 0
        )

    def _last_messages(self, session_ids: list[str]) -> dict[str, Message]:
        if not session_ids:
            return {}
        messages = list(
            self.db.execute(
                select(Message)
                .where(Message.session_id.in_(session_ids))
                .order_by(Message.session_id.asc(), Message.session_seq.desc(), Message.created_at.desc(), Message.id.desc())
            )
            .scalars()
            .all()
        )
        latest: dict[str, Message] = {}
        for message in messages:
            session_id = str(message.session_id or "")
            latest.setdefault(session_id, message)
        return latest

    def _users_by_id(self, user_ids: list[str]) -> dict[str, User]:
        normalized_ids = sorted({str(user_id or "").strip() for user_id in user_ids if str(user_id or "").strip()})
        if not normalized_ids:
            return {}
        users = self.db.execute(select(User).where(User.id.in_(normalized_ids))).scalars().all()
        return {str(user.id or ""): user for user in users}

    def _get_session_or_404(self, session_id: str) -> ChatSession:
        normalized_session_id = str(session_id or "").strip()
        session = self.db.get(ChatSession, normalized_session_id)
        if session is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)
        return session

    def _count(self, statement) -> int:
        return int(self.db.execute(select(func.count()).select_from(statement.order_by(None).subquery())).scalar_one() or 0)

    def _pagination(self, page: int, size: int, *, max_size: int = 100) -> tuple[int, int]:
        return max(1, int(page or 1)), min(max_size, max(1, int(size or 20)))

    def _seq_counts(self, seqs: list[int]) -> dict[int, int]:
        counts: dict[int, int] = {}
        for seq in seqs:
            counts[seq] = counts.get(seq, 0) + 1
        return counts

    def _issue_sort_key(self, issue: dict[str, Any]) -> tuple[str, str, int, str]:
        return (
            str(issue.get("issue_type") or ""),
            str(issue.get("session_id") or ""),
            int(issue.get("session_seq") or 0),
            str(issue.get("message_id") or ""),
        )

    def _load_extra(self, raw_value: str | None) -> dict[str, Any]:
        if not raw_value:
            return {}
        try:
            payload = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
