"""Message service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.message_repo import MessageRepository
from app.repositories.session_repo import SessionRepository


class MessageService:
    RECALL_LIMIT = timedelta(minutes=2)

    def __init__(self, db: Session) -> None:
        self.messages = MessageRepository(db)
        self.sessions = SessionRepository(db)

    def list_messages(
        self,
        current_user: User,
        session_id: str,
        limit: int = 50,
        before: datetime | None = None,
        before_id: str | None = None,
    ) -> list[dict]:
        self._ensure_membership(current_user.id, session_id)
        items = self.messages.list_session_messages(session_id, limit=limit, before=before, before_id=before_id)
        return [self.serialize_message(item, current_user.id) for item in items]

    def send_message(
        self,
        current_user: User,
        session_id: str,
        content: str,
        message_type: str = "text",
        message_id: str | None = None,
    ) -> dict:
        self._ensure_membership(current_user.id, session_id)
        message = self.messages.create(
            session_id=session_id,
            sender_id=current_user.id,
            content=content,
            message_type=message_type,
            message_id=message_id,
        )
        self.sessions.touch(session_id)
        return self.serialize_message(message, current_user.id)

    def send_ws_message(
        self,
        sender_id: str,
        session_id: str,
        content: str,
        message_type: str = "text",
        message_id: str | None = None,
    ) -> dict:
        existing_session = self.sessions.get_by_id(session_id)
        if existing_session is None:
            created = self.sessions.create_with_id(session_id, "Auto Session", "private")
            self.sessions.add_member(created.id, sender_id)
        else:
            self._ensure_membership(sender_id, session_id)
        message = self.messages.create(
            session_id=session_id,
            sender_id=sender_id,
            content=content,
            message_type=message_type,
            message_id=message_id,
        )
        self.sessions.touch(session_id)
        return self.serialize_message(message, sender_id)

    def mark_read(self, current_user: User, message_id: str) -> dict:
        message = self.messages.get_by_id(message_id)
        if message is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "message not found", 404)
        self._ensure_membership(current_user.id, message.session_id)
        self.messages.mark_read(message_id, current_user.id)
        return {"status": "read"}

    def batch_read(self, current_user: User, session_id: str, last_read_id: str) -> dict:
        self._ensure_membership(current_user.id, session_id)
        self.messages.mark_read_batch(session_id, current_user.id, last_read_id)
        return {"success": True}

    def recall(self, current_user: User, message_id: str) -> dict:
        message = self.messages.get_by_id(message_id)
        if message is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "message not found", 404)
        if message.sender_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "cannot recall this message", 403)
        if message.created_at and datetime.utcnow() - message.created_at.replace(tzinfo=None) > self.RECALL_LIMIT:
            raise AppError(ErrorCode.FORBIDDEN, "recall time limit exceeded", 403)
        self.messages.update_status(message, "recalled")
        return {
            "status": "recalled",
            "message_id": message.id,
            "msg_id": message.id,
            "session_id": message.session_id,
            "user_id": current_user.id,
        }

    def edit(self, current_user: User, message_id: str, content: str) -> dict:
        message = self.messages.get_by_id(message_id)
        if message is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "message not found", 404)
        if message.sender_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "cannot edit this message", 403)
        message = self.messages.update_content(message, content)
        message = self.messages.update_status(message, "edited")
        return self.serialize_message(message, current_user.id)

    def delete(self, current_user: User, message_id: str) -> dict:
        message = self.messages.get_by_id(message_id)
        if message is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "message not found", 404)
        if message.sender_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "cannot delete this message", 403)
        payload = {
            "status": "deleted",
            "message_id": message.id,
            "msg_id": message.id,
            "session_id": message.session_id,
            "user_id": current_user.id,
        }
        self.messages.delete(message)
        return payload

    def unread_summary(self, current_user: User) -> dict:
        return {"total": self.messages.unread_total_for_user(current_user.id)}

    def session_unread_counts(self, current_user: User) -> list[dict]:
        return self.messages.unread_by_session_for_user(current_user.id)

    def sync_since_timestamp(self, since_timestamp: float, current_user_id: str) -> list[dict]:
        since = datetime.fromtimestamp(since_timestamp, tz=timezone.utc).replace(tzinfo=None)
        return [
            self.serialize_message(item, current_user_id)
            for item in self.messages.list_messages_since_for_user(since, current_user_id)
        ]

    def get_session_member_ids(self, session_id: str, user_id: str | None = None) -> list[str]:
        member_ids = self.sessions.list_member_ids(session_id)
        if user_id is not None and user_id not in member_ids:
            raise AppError(ErrorCode.FORBIDDEN, "not a session member", 403)
        return member_ids

    def _ensure_membership(self, user_id: str, session_id: str) -> None:
        member_ids = self.sessions.list_member_ids(session_id)
        if user_id not in member_ids:
            raise AppError(ErrorCode.FORBIDDEN, "not a session member", 403)

    @staticmethod
    def serialize_message(message, current_user_id: str) -> dict:
        return {
            "id": message.id,
            "message_id": message.id,
            "msg_id": message.id,
            "session_id": message.session_id,
            "sender_id": message.sender_id,
            "content": message.content,
            "type": message.type,
            "message_type": message.type,
            "status": message.status,
            "created_at": message.created_at.isoformat() if message.created_at else None,
            "timestamp": message.created_at.isoformat() if message.created_at else None,
            "updated_at": message.updated_at.isoformat() if message.updated_at else None,
            "is_self": message.sender_id == current_user_id,
            "is_ai": False,
            "extra": {},
        }
