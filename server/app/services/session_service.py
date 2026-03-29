"""Session service."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.group_repo import GroupRepository
from app.repositories.message_repo import MessageRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.user_repo import UserRepository
from app.services.avatar_service import AvatarService
from app.utils.time import isoformat_utc


T = TypeVar("T")


class SessionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.sessions = SessionRepository(db)
        self.messages = MessageRepository(db)
        self.users = UserRepository(db)
        self.groups = GroupRepository(db)
        self.avatars = AvatarService(db)

    def list_sessions(self, current_user: User) -> list[dict]:
        session_items = self.sessions.list_user_sessions(current_user.id)
        session_ids = [item.id for item in session_items]
        members_by_session = self.sessions.list_members_for_sessions(session_ids)
        last_messages_by_session = self.messages.list_last_messages_for_sessions(session_ids)
        user_ids = sorted(
            {
                str(member.user_id or "")
                for members in members_by_session.values()
                for member in members
                if str(member.user_id or "")
            }
        )
        users_by_id = self.users.list_users_by_ids(user_ids)

        payload: list[dict] = []
        for item in session_items:
            session_members = members_by_session.get(item.id, [])
            member_ids = [str(member.user_id or "") for member in session_members if str(member.user_id or "")]
            if not self._is_visible_private_session(item, member_ids):
                continue
            payload.append(
                self.serialize_session(
                    item,
                    include_members=True,
                    participant_ids=member_ids,
                    last_message=last_messages_by_session.get(item.id),
                    session_members=session_members,
                    users_by_id=users_by_id,
                    current_user_id=current_user.id,
                )
            )
        return payload

    def create_private(self, current_user: User, participant_ids: list[str], name: str | None = None) -> dict:
        members = self._normalize_private_members(current_user, participant_ids)
        direct_key = self.sessions.build_private_direct_key(members)
        existing = self.sessions.get_private_session_by_direct_key(direct_key)
        if existing is not None:
            return self.serialize_session(existing, include_members=True, participant_ids=members, current_user_id=current_user.id)

        def action() -> object:
            session = self.sessions.create(
                name or "Private Chat",
                "private",
                direct_key=direct_key,
                commit=False,
            )
            for member_id in members:
                self.sessions.add_member(session.id, member_id, commit=False)
            return session

        try:
            session = self._run_transaction(action)
        except IntegrityError:
            existing = self.sessions.get_private_session_by_direct_key(direct_key)
            if existing is None:
                raise
            session = existing
        return self.serialize_session(session, include_members=True, participant_ids=members, current_user_id=current_user.id)

    def get_session(self, current_user: User, session_id: str) -> dict:
        session = self.sessions.get_by_id(session_id)
        if session is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)

        member_ids = self.sessions.list_member_ids(session_id)
        if current_user.id not in member_ids:
            raise AppError(ErrorCode.FORBIDDEN, "not a session member", 403)
        if not self._is_visible_private_session(session, member_ids):
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)
        return self.serialize_session(session, include_members=True, participant_ids=member_ids, current_user_id=current_user.id)

    def delete_session(self, current_user: User, session_id: str) -> None:
        session = self.sessions.get_by_id(session_id)
        if session is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)
        member_ids = self.sessions.list_member_ids(session_id)
        if current_user.id not in member_ids:
            raise AppError(ErrorCode.FORBIDDEN, "not a session member", 403)
        if self.groups.get_by_session_id(session_id) is not None:
            raise AppError(ErrorCode.FORBIDDEN, "group sessions must be deleted via groups API", 403)
        self.sessions.delete_session(session_id)

    def list_member_ids(self, session_id: str) -> list[str]:
        return self.sessions.list_member_ids(session_id)

    def serialize_session(
        self,
        session,
        *,
        include_members: bool = True,
        participant_ids: list[str] | None = None,
        last_message=None,
        session_members: list | None = None,
        users_by_id: dict[str, User] | None = None,
        current_user_id: str | None = None,
    ) -> dict:
        member_ids = participant_ids if participant_ids is not None else self.sessions.list_member_ids(session.id)
        if last_message is None:
            messages = self.messages.list_session_messages(session.id, limit=1)
            last_message = messages[-1] if messages else None
        normalized_session_type = "direct" if session.type == "private" else session.type
        avatar = session.avatar
        member_rows = session_members if session_members is not None else None
        user_map = users_by_id or {}
        if normalized_session_type == "group":
            group = self.groups.get_by_session_id(session.id)
            if group is not None:
                avatar = self.avatars.ensure_group_avatar(group)

        if include_members or normalized_session_type == "direct":
            member_rows = member_rows if member_rows is not None else self.sessions.list_members(session.id)
            if not user_map:
                user_map = self.users.list_users_by_ids([member.user_id for member in member_rows])

        counterpart = self._serialize_counterpart_profile(
            normalized_session_type,
            member_rows or [],
            user_map,
            current_user_id=current_user_id,
        )

        data = {
            "id": session.id,
            "session_id": session.id,
            "session_type": normalized_session_type,
            "name": session.name,
            "participant_ids": member_ids,
            "last_message": self._serialize_last_message_preview(last_message),
            "last_message_status": last_message.status if last_message else None,
            "last_message_sender_id": last_message.sender_id if last_message else None,
            "last_message_time": (
                isoformat_utc(last_message.created_at) if last_message else None
            ),
            "updated_at": isoformat_utc(session.updated_at),
            "unread_count": 0,
            "avatar": avatar,
            "is_ai_session": session.is_ai_session,
            "created_at": isoformat_utc(session.created_at),
            "counterpart_id": counterpart.get("id") or None,
            "counterpart_name": counterpart.get("display_name") or None,
            "counterpart_username": counterpart.get("username") or None,
            "counterpart_avatar": counterpart.get("avatar") or None,
            "counterpart_gender": counterpart.get("gender") or None,
        }
        if include_members:
            members = []
            for member in member_rows or []:
                user = user_map.get(str(member.user_id or ""))
                if user is not None:
                    user = self.avatars.backfill_user_avatar_state(user)
                    members.append(
                        {
                            "id": user.id,
                            "nickname": user.nickname,
                            "username": user.username,
                            "avatar": self.avatars.resolve_user_avatar_url(user),
                            "gender": user.gender,
                            "joined_at": isoformat_utc(member.joined_at),
                        }
                    )
            data["members"] = members
        return data

    def _serialize_counterpart_profile(
        self,
        session_type: str,
        member_rows: list,
        users_by_id: dict[str, User],
        *,
        current_user_id: str | None = None,
    ) -> dict[str, str]:
        if session_type != "direct":
            return {}

        normalized_current_user_id = str(current_user_id or "").strip()
        for member in member_rows:
            member_user_id = str(member.user_id or "")
            if normalized_current_user_id and member_user_id == normalized_current_user_id:
                continue
            user = users_by_id.get(member_user_id)
            if user is None:
                continue
            user = self.avatars.backfill_user_avatar_state(user)
            nickname = str(user.nickname or "")
            username = str(user.username or "")
            return {
                "id": user.id,
                "username": username,
                "nickname": nickname,
                "display_name": nickname or username or user.id,
                "avatar": self.avatars.resolve_user_avatar_url(user) or "",
                "gender": str(user.gender or ""),
            }
        return {}

    @staticmethod
    def _serialize_last_message_preview(last_message) -> str | None:
        if last_message is None:
            return None
        if last_message.status == "recalled":
            return ""
        return last_message.content

    def _normalize_private_members(self, current_user: User, participant_ids: list[str]) -> list[str]:
        normalized_targets = []
        for participant_id in participant_ids:
            value = str(participant_id or "").strip()
            if not value:
                continue
            if value == current_user.id:
                continue
            normalized_targets.append(value)

        normalized_targets = list(dict.fromkeys(normalized_targets))
        if not normalized_targets:
            raise AppError(ErrorCode.INVALID_REQUEST, "cannot create a private chat with yourself", 422)
        if len(normalized_targets) != 1:
            raise AppError(ErrorCode.INVALID_REQUEST, "private chats require exactly one other participant", 422)

        self._require_existing_user(normalized_targets[0])
        return [current_user.id, normalized_targets[0]]

    def _require_existing_user(self, user_id: str) -> None:
        if self.users.get_by_id(user_id) is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "user not found", 404)

    @staticmethod
    def _is_visible_private_session(session, member_ids: list[str]) -> bool:
        if session.type != "private" or session.is_ai_session:
            return True
        return len(set(member_ids)) >= 2

    def _run_transaction(self, action: Callable[[], T]) -> T:
        try:
            result = action()
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise






