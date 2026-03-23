"""Session service."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.group_repo import GroupRepository
from app.repositories.message_repo import MessageRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.user_repo import UserRepository


T = TypeVar("T")


class SessionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.sessions = SessionRepository(db)
        self.messages = MessageRepository(db)
        self.users = UserRepository(db)
        self.groups = GroupRepository(db)

    def list_sessions(self, current_user: User) -> list[dict]:
        payload: list[dict] = []
        seen_private_keys: set[tuple[str, ...]] = set()
        for item in self.sessions.list_user_sessions(current_user.id):
            member_ids = self.sessions.list_member_ids(item.id)
            if not self._is_visible_private_session(item, member_ids):
                continue
            private_key = self._private_session_key(item, member_ids)
            if private_key is not None and private_key in seen_private_keys:
                continue
            if private_key is not None:
                seen_private_keys.add(private_key)
            payload.append(
                self.serialize_session(
                    item,
                    viewer_user_id=current_user.id,
                    include_members=True,
                    participant_ids=member_ids,
                )
            )
        return payload

    def create_private(self, current_user: User, participant_ids: list[str], name: str | None = None) -> dict:
        members = self._normalize_private_members(current_user, participant_ids)
        existing = self.sessions.find_private_session_by_members(members)
        if existing is not None:
            return self.serialize_session(existing, viewer_user_id=current_user.id, include_members=True, participant_ids=members)

        def action() -> object:
            session = self.sessions.create(name or "Private Chat", "private", commit=False)
            for member_id in members:
                self.sessions.add_member(session.id, member_id, commit=False)
            return session

        session = self._run_transaction(action)
        return self.serialize_session(session, viewer_user_id=current_user.id, include_members=True, participant_ids=members)

    def create_group(self, current_user: User, name: str, participant_ids: list[str]) -> dict:
        members = self._normalize_group_members(current_user, participant_ids)

        def action() -> object:
            session = self.sessions.create(name, "group", commit=False)
            for member_id in members:
                self.sessions.add_member(session.id, member_id, commit=False)
            return session

        session = self._run_transaction(action)
        return self.serialize_session(session, viewer_user_id=current_user.id, include_members=True, participant_ids=members)

    def create_generic(self, current_user: User, payload: dict) -> dict:
        session_type = payload.get("type", "private")
        if session_type == "private":
            user_id = payload.get("user_id")
            if not user_id:
                raise AppError(ErrorCode.INVALID_REQUEST, "user_id is required", 422)
            return self.create_private(current_user, [user_id], payload.get("name"))
        if session_type == "group":
            members = payload.get("members") or payload.get("participant_ids") or []
            return self.create_group(current_user, payload.get("name", "Group Chat"), members)
        raise AppError(ErrorCode.INVALID_REQUEST, "invalid session type", 422)

    def get_session(self, current_user: User, session_id: str) -> dict:
        session = self.sessions.get_by_id(session_id)
        if session is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)

        member_ids = self.sessions.list_member_ids(session_id)
        if current_user.id not in member_ids:
            raise AppError(ErrorCode.FORBIDDEN, "not a session member", 403)
        if not self._is_visible_private_session(session, member_ids):
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)
        return self.serialize_session(session, viewer_user_id=current_user.id, include_members=True, participant_ids=member_ids)

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

    def ensure_session(self, session_id: str, fallback_name: str, current_user_id: str) -> dict:
        session = self.sessions.get_by_id(session_id)
        if session is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)

        member_ids = self.sessions.list_member_ids(session_id)
        if current_user_id not in member_ids:
            raise AppError(ErrorCode.FORBIDDEN, "not a session member", 403)
        if not self._is_visible_private_session(session, member_ids):
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)
        return self.serialize_session(session, viewer_user_id=current_user_id, include_members=False, participant_ids=member_ids)

    def serialize_session(
        self,
        session,
        *,
        viewer_user_id: str = "",
        include_members: bool = True,
        participant_ids: list[str] | None = None,
    ) -> dict:
        member_ids = participant_ids if participant_ids is not None else self.sessions.list_member_ids(session.id)
        messages = self.messages.list_session_messages(session.id, limit=1)
        last_message = messages[-1] if messages else None
        data = {
            "id": session.id,
            "session_id": session.id,
            "type": session.type,
            "session_type": session.type,
            "name": session.name,
            "participant_ids": member_ids,
            "last_message": self._serialize_last_message_preview(last_message),
            "last_message_status": last_message.status if last_message else None,
            "last_message_sender_id": last_message.sender_id if last_message else None,
            "last_message_time": (
                last_message.created_at.isoformat() if last_message and last_message.created_at else None
            ),
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
            "unread_count": 0,
            "avatar": session.avatar,
            "is_ai_session": session.is_ai_session,
            "created_at": session.created_at.isoformat() if session.created_at else None,
        }
        if include_members:
            members = []
            for member in self.sessions.list_members(session.id):
                user = self.users.get_by_id(member.user_id)
                if user is not None:
                    members.append(
                        {
                            "id": user.id,
                            "nickname": user.nickname,
                            "username": user.username,
                            "joined_at": member.joined_at.isoformat() if member.joined_at else None,
                        }
                    )
            data["members"] = members
        return data

    @staticmethod
    def _serialize_last_message_preview(last_message) -> str | None:
        if last_message is None:
            return None
        if last_message.status == "recalled":
            return ""
        return last_message.content

    @staticmethod
    def _private_session_key(session, member_ids: list[str]) -> tuple[str, ...] | None:
        if session.type != "private" or session.is_ai_session:
            return None
        key = tuple(sorted({str(member_id or "") for member_id in member_ids if str(member_id or "")}))
        return key if len(key) >= 2 else None

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

    def _normalize_group_members(self, current_user: User, participant_ids: list[str]) -> list[str]:
        members = list(dict.fromkeys([current_user.id, *[str(item or "").strip() for item in participant_ids if str(item or "").strip()]]))
        for member_id in members:
            self._require_existing_user(member_id)
        return members

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