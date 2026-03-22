"""Session repository."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.message import Message, MessageRead
from app.models.session import ChatSession, SessionMember


class SessionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, session_id: str) -> ChatSession | None:
        return self.db.get(ChatSession, session_id)

    def create(
        self,
        name: str,
        session_type: str,
        avatar: str | None = None,
        is_ai_session: bool = False,
    ) -> ChatSession:
        session = ChatSession(
            name=name,
            type=session_type,
            avatar=avatar,
            is_ai_session=is_ai_session,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def create_with_id(
        self,
        session_id: str,
        name: str,
        session_type: str,
        avatar: str | None = None,
        is_ai_session: bool = False,
    ) -> ChatSession:
        session = ChatSession(
            id=session_id,
            name=name,
            type=session_type,
            avatar=avatar,
            is_ai_session=is_ai_session,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def add_member(self, session_id: str, user_id: str) -> None:
        existing = self.db.get(SessionMember, {"session_id": session_id, "user_id": user_id})
        if existing is None:
            self.db.add(SessionMember(session_id=session_id, user_id=user_id))
            self.db.commit()

    def remove_member(self, session_id: str, user_id: str) -> None:
        existing = self.db.get(SessionMember, {"session_id": session_id, "user_id": user_id})
        if existing is not None:
            self.db.delete(existing)
            self.db.commit()

    def list_members(self, session_id: str) -> list[SessionMember]:
        stmt = select(SessionMember).where(SessionMember.session_id == session_id)
        return list(self.db.execute(stmt).scalars().all())

    def list_member_ids(self, session_id: str) -> list[str]:
        stmt = select(SessionMember.user_id).where(SessionMember.session_id == session_id)
        return list(self.db.execute(stmt).scalars().all())

    def list_user_sessions(self, user_id: str) -> list[ChatSession]:
        stmt = (
            select(ChatSession)
            .join(SessionMember, SessionMember.session_id == ChatSession.id)
            .where(SessionMember.user_id == user_id)
            .order_by(ChatSession.updated_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def find_private_session_by_members(self, user_ids: list[str]) -> ChatSession | None:
        normalized_ids = list(dict.fromkeys(user_ids))
        if len(normalized_ids) < 2:
            return None

        seed_user_id = normalized_ids[0]
        stmt = (
            select(ChatSession)
            .join(SessionMember, SessionMember.session_id == ChatSession.id)
            .where(ChatSession.type == "private", SessionMember.user_id == seed_user_id)
            .order_by(ChatSession.updated_at.desc())
        )
        candidates = list(self.db.execute(stmt).scalars().all())
        expected_members = set(normalized_ids)

        for session in candidates:
            member_ids = set(self.list_member_ids(session.id))
            if member_ids == expected_members:
                return session

        return None

    def touch(self, session_id: str) -> ChatSession | None:
        session = self.get_by_id(session_id)
        if session is None:
            return None
        session.updated_at = datetime.utcnow()
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def delete_session(self, session_id: str) -> None:
        message_ids = list(self.db.execute(select(Message.id).where(Message.session_id == session_id)).scalars().all())
        if message_ids:
            self.db.execute(delete(MessageRead).where(MessageRead.message_id.in_(message_ids)))
        self.db.execute(delete(Message).where(Message.session_id == session_id))
        self.db.execute(delete(SessionMember).where(SessionMember.session_id == session_id))
        session = self.get_by_id(session_id)
        if session is not None:
            self.db.delete(session)
        self.db.commit()

