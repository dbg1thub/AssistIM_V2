"""Session service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.group_repo import GroupRepository
from app.repositories.message_repo import MessageRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.user_repo import UserRepository


class SessionService:
    def __init__(self, db: Session) -> None:
        self.sessions = SessionRepository(db)
        self.messages = MessageRepository(db)
        self.users = UserRepository(db)
        self.groups = GroupRepository(db)

    def list_sessions(self, current_user: User) -> list[dict]:
        return [self.serialize_session(item, include_members=False) for item in self.sessions.list_user_sessions(current_user.id)]

    def create_private(self, current_user: User, participant_ids: list[str], name: str | None = None) -> dict:
        members = list(dict.fromkeys([current_user.id, *participant_ids]))
        session = self.sessions.create(name or "Private Chat", "private")
        for member_id in members:
            self.sessions.add_member(session.id, member_id)
        return self.serialize_session(session, include_members=True)

    def create_group(self, current_user: User, name: str, participant_ids: list[str]) -> dict:
        members = list(dict.fromkeys([current_user.id, *participant_ids]))
        session = self.sessions.create(name, "group")
        for member_id in members:
            self.sessions.add_member(session.id, member_id)
        return self.serialize_session(session, include_members=True)

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
        return self.serialize_session(session, include_members=True)

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
            session = self.sessions.create_with_id(session_id, fallback_name, "private")
            self.sessions.add_member(session.id, current_user_id)
        return self.serialize_session(session, include_members=False)

    def serialize_session(self, session, include_members: bool = True) -> dict:
        messages = self.messages.list_session_messages(session.id, limit=1)
        last_message = messages[-1] if messages else None
        data = {
            "id": session.id,
            "session_id": session.id,
            "type": session.type,
            "session_type": session.type,
            "name": session.name,
            "participant_ids": self.sessions.list_member_ids(session.id),
            "last_message": last_message.content if last_message else None,
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
