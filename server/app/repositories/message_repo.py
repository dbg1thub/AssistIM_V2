"""Message repository."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.models.message import Message, MessageRead
from app.models.session import SessionMember


class MessageRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        session_id: str,
        sender_id: str,
        content: str,
        message_type: str = "text",
        message_id: str | None = None,
        status: str = "sent",
    ) -> Message:
        payload = {
            "session_id": session_id,
            "sender_id": sender_id,
            "content": content,
            "type": message_type,
            "status": status,
        }
        if message_id is not None:
            payload["id"] = message_id
        message = Message(**payload)
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message

    def get_by_id(self, message_id: str) -> Message | None:
        return self.db.get(Message, message_id)

    def list_session_messages(
        self,
        session_id: str,
        limit: int = 50,
        before: datetime | None = None,
        before_id: str | None = None,
    ) -> list[Message]:
        stmt = select(Message).where(Message.session_id == session_id)
        if before_id is not None:
            before_message = self.get_by_id(before_id)
            if before_message is not None:
                before = before_message.created_at
        if before is not None:
            stmt = stmt.where(Message.created_at < before)
        stmt = stmt.order_by(desc(Message.created_at)).limit(limit)
        return list(reversed(self.db.execute(stmt).scalars().all()))

    def list_messages_since_for_user(self, since: datetime, user_id: str) -> list[Message]:
        stmt = (
            select(Message)
            .join(SessionMember, SessionMember.session_id == Message.session_id)
            .where(
                and_(
                    Message.created_at > since,
                    SessionMember.user_id == user_id,
                )
            )
            .order_by(Message.created_at.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def update_status(self, message: Message, status: str) -> Message:
        message.status = status
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message

    def update_content(self, message: Message, content: str) -> Message:
        message.content = content
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message

    def delete(self, message: Message) -> None:
        self.db.query(MessageRead).filter(MessageRead.message_id == message.id).delete()
        self.db.delete(message)
        self.db.commit()

    def mark_read(self, message_id: str, user_id: str) -> None:
        existing = self.db.get(MessageRead, {"message_id": message_id, "user_id": user_id})
        if existing is None:
            self.db.add(MessageRead(message_id=message_id, user_id=user_id))
        message = self.get_by_id(message_id)
        if message is not None:
            message.status = "read"
            self.db.add(message)
        self.db.commit()

    def mark_read_batch(self, session_id: str, user_id: str, last_read_id: str) -> None:
        last_message = self.get_by_id(last_read_id)
        if last_message is None:
            return
        stmt = select(Message).where(
            and_(
                Message.session_id == session_id,
                Message.created_at <= last_message.created_at,
                Message.sender_id != user_id,
            )
        )
        for message in self.db.execute(stmt).scalars().all():
            existing = self.db.get(MessageRead, {"message_id": message.id, "user_id": user_id})
            if existing is None:
                self.db.add(MessageRead(message_id=message.id, user_id=user_id))
            message.status = "read"
            self.db.add(message)
        self.db.commit()

    def unread_total_for_user(self, user_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(Message)
            .join(SessionMember, SessionMember.session_id == Message.session_id)
            .outerjoin(
                MessageRead,
                and_(MessageRead.message_id == Message.id, MessageRead.user_id == user_id),
            )
            .where(
                and_(
                    SessionMember.user_id == user_id,
                    Message.sender_id != user_id,
                    MessageRead.message_id.is_(None),
                )
            )
        )
        return int(self.db.execute(stmt).scalar_one())

    def unread_by_session_for_user(self, user_id: str) -> list[dict]:
        stmt = (
            select(Message.session_id, func.count().label("unread"))
            .join(SessionMember, SessionMember.session_id == Message.session_id)
            .outerjoin(
                MessageRead,
                and_(MessageRead.message_id == Message.id, MessageRead.user_id == user_id),
            )
            .where(
                and_(
                    SessionMember.user_id == user_id,
                    Message.sender_id != user_id,
                    MessageRead.message_id.is_(None),
                )
            )
            .group_by(Message.session_id)
        )
        return [
            {"session_id": row.session_id, "unread": int(row.unread)}
            for row in self.db.execute(stmt).all()
        ]
