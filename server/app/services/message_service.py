"""Message service."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.session import SessionEvent
from app.models.user import User
from app.repositories.message_repo import MessageIdConflictError, MessageRepository
from app.repositories.session_repo import SessionRepository
from app.utils.time import ensure_utc, utcnow


class MessageService:
    RECALL_LIMIT = timedelta(minutes=2)
    EDIT_LIMIT = timedelta(minutes=2)

    def __init__(self, db: Session) -> None:
        self.db = db
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
        return self._serialize_messages(items, current_user.id)

    def send_message(
        self,
        current_user: User,
        session_id: str,
        content: str,
        message_type: str = "text",
        message_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict:
        self._ensure_membership(current_user.id, session_id)
        try:
            message, _ = self.messages.create(
                session_id=session_id,
                sender_id=current_user.id,
                content=content,
                message_type=message_type,
                message_id=message_id,
                extra=extra,
            )
        except MessageIdConflictError as exc:
            raise AppError(ErrorCode.INVALID_REQUEST, str(exc), 409) from exc
        return self.serialize_message(message, current_user.id)

    def send_ws_message(
        self,
        sender_id: str,
        session_id: str,
        content: str,
        message_type: str = "text",
        message_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> tuple[dict, bool]:
        existing_session = self.sessions.get_by_id(session_id)
        if existing_session is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)

        self._ensure_membership(sender_id, session_id)
        try:
            message, created = self.messages.create(
                session_id=session_id,
                sender_id=sender_id,
                content=content,
                message_type=message_type,
                message_id=message_id,
                extra=extra,
            )
        except MessageIdConflictError as exc:
            raise AppError(ErrorCode.INVALID_REQUEST, str(exc), 409) from exc
        return self.serialize_message(message, sender_id), created

    def mark_read(self, current_user: User, message_id: str) -> dict:
        message = self.messages.get_by_id(message_id)
        if message is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "message not found", 404)
        self._ensure_membership(current_user.id, message.session_id)
        payload = self.messages.mark_read(message_id, current_user.id, commit=False)
        if payload is None:
            raise AppError(ErrorCode.INVALID_REQUEST, "invalid read target", 422)

        if payload.get("advanced"):
            event_payload = self._record_session_event(
                message.session_id,
                "read",
                self._read_event_data(payload),
                message_id=message.id,
                actor_user_id=current_user.id,
            )
            payload = {**payload, **event_payload}

        self.db.commit()
        return {
            "status": "read",
            **payload,
        }

    def batch_read(self, current_user: User, session_id: str, last_read_id: str) -> dict:
        self._ensure_membership(current_user.id, session_id)
        last_message = self.messages.get_by_id(last_read_id)
        if last_message is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "message not found", 404)
        if last_message.session_id != session_id:
            raise AppError(ErrorCode.INVALID_REQUEST, "message does not belong to the session", 422)

        payload = self.messages.mark_read_batch(session_id, current_user.id, last_read_id, commit=False)
        if payload is None:
            raise AppError(ErrorCode.INVALID_REQUEST, "invalid read target", 422)

        if payload.get("advanced"):
            event_payload = self._record_session_event(
                session_id,
                "read",
                self._read_event_data(payload),
                message_id=last_message.id,
                actor_user_id=current_user.id,
            )
            payload = {**payload, **event_payload}

        self.db.commit()
        return {
            "success": True,
            **payload,
        }

    def recall(self, current_user: User, message_id: str) -> dict:
        message = self.messages.get_by_id(message_id)
        if message is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "message not found", 404)
        if message.sender_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "cannot recall this message", 403)
        if message.created_at and utcnow() - ensure_utc(message.created_at) > self.RECALL_LIMIT:
            raise AppError(ErrorCode.FORBIDDEN, "recall time limit exceeded", 403)

        self.messages.update_status(message, "recalled", commit=False)
        payload = {
            "session_id": message.session_id,
            "msg_id": message.id,
            "message_id": message.id,
            "user_id": current_user.id,
            "status": "recalled",
            "updated_at": message.updated_at.isoformat() if message.updated_at else None,
            "session_seq": int(message.session_seq or 0),
        }
        payload = self._record_session_event(
            message.session_id,
            "message_recall",
            payload,
            message_id=message.id,
            actor_user_id=current_user.id,
        )
        self.db.commit()
        return payload

    def edit(self, current_user: User, message_id: str, content: str) -> dict:
        message = self.messages.get_by_id(message_id)
        if message is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "message not found", 404)
        if message.sender_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "cannot edit this message", 403)
        if message.created_at and utcnow() - ensure_utc(message.created_at) > self.EDIT_LIMIT:
            raise AppError(ErrorCode.FORBIDDEN, "edit time limit exceeded", 403)

        self.messages.update_content(message, content, commit=False)
        self.messages.update_status(message, "edited", commit=False)
        serialized = self.serialize_message(message, current_user.id)
        payload = {
            "session_id": serialized["session_id"],
            "msg_id": serialized["msg_id"],
            "message_id": serialized["message_id"],
            "user_id": current_user.id,
            "content": serialized["content"],
            "status": serialized["status"],
            "updated_at": serialized["updated_at"],
            "session_seq": serialized.get("session_seq", 0),
            "read_count": serialized.get("read_count", 0),
            "read_target_count": serialized.get("read_target_count", 0),
            "read_by_user_ids": serialized.get("read_by_user_ids", []),
            "extra": dict(serialized.get("extra") or {}),
        }
        payload = self._record_session_event(
            serialized["session_id"],
            "message_edit",
            payload,
            message_id=serialized["message_id"],
            actor_user_id=current_user.id,
        )
        self.db.commit()
        return payload

    def delete(self, current_user: User, message_id: str) -> dict:
        message = self.messages.get_by_id(message_id)
        if message is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "message not found", 404)
        if message.sender_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "cannot delete this message", 403)

        payload = {
            "session_id": message.session_id,
            "msg_id": message.id,
            "message_id": message.id,
            "user_id": current_user.id,
            "status": "deleted",
        }
        self.messages.delete(message, commit=False)
        payload = self._record_session_event(
            payload["session_id"],
            "message_delete",
            payload,
            message_id=payload["message_id"],
            actor_user_id=current_user.id,
        )
        self.db.commit()
        return payload

    def unread_summary(self, current_user: User) -> dict:
        return {"total": self.messages.unread_total_for_user(current_user.id)}

    def session_unread_counts(self, current_user: User) -> list[dict]:
        return self.messages.unread_by_session_for_user(current_user.id)

    def sync_missing_messages(self, session_cursors: dict | None, current_user_id: str) -> list[dict]:
        items = self.messages.list_missing_messages_for_user(
            self._normalize_session_cursors(session_cursors),
            current_user_id,
        )
        return self._serialize_messages(items, current_user_id)

    def sync_missing_events(self, event_cursors: dict | None, current_user_id: str) -> list[dict]:
        items = self.messages.list_missing_events_for_user(
            self._normalize_event_cursors(event_cursors),
            current_user_id,
        )
        return [self.serialize_session_event(item) for item in items]

    def get_session_member_ids(self, session_id: str, user_id: str | None = None) -> list[str]:
        member_ids = self.sessions.list_member_ids(session_id)
        if user_id is not None and user_id not in member_ids:
            raise AppError(ErrorCode.FORBIDDEN, "not a session member", 403)
        return member_ids

    def _ensure_membership(self, user_id: str, session_id: str) -> None:
        if not self.sessions.has_member(session_id, user_id):
            raise AppError(ErrorCode.FORBIDDEN, "not a session member", 403)

    @staticmethod
    def _normalize_session_cursors(raw_cursors: dict | None) -> dict[str, int]:
        if not isinstance(raw_cursors, dict):
            return {}

        normalized: dict[str, int] = {}
        for session_id, raw_value in raw_cursors.items():
            normalized_session_id = str(session_id or "").strip()
            if not normalized_session_id:
                continue
            try:
                session_seq = max(0, int(raw_value or 0))
            except (TypeError, ValueError):
                continue
            normalized[normalized_session_id] = session_seq
        return normalized

    @staticmethod
    def _normalize_event_cursors(raw_cursors: dict | None) -> dict[str, int]:
        if not isinstance(raw_cursors, dict):
            return {}

        normalized: dict[str, int] = {}
        for session_id, raw_value in raw_cursors.items():
            normalized_session_id = str(session_id or "").strip()
            if not normalized_session_id:
                continue
            try:
                event_seq = max(0, int(raw_value or 0))
            except (TypeError, ValueError):
                continue
            normalized[normalized_session_id] = event_seq
        return normalized

    def _load_session_members(self, session_id: str):
        return self.sessions.list_members(session_id)

    def _message_read_metadata(self, message, current_user_id: str, session_members: list) -> dict:
        read_by_user_ids = sorted(
            member.user_id
            for member in session_members
            if member.user_id != message.sender_id and int(member.last_read_seq or 0) >= int(message.session_seq or 0)
        )
        viewer_member = next((member for member in session_members if member.user_id == current_user_id), None)
        viewer_last_read_seq = int(viewer_member.last_read_seq or 0) if viewer_member is not None else 0
        read_target_count = max(0, len(session_members) - 1)
        return {
            "session_seq": int(message.session_seq or 0),
            "read_count": len(read_by_user_ids),
            "read_target_count": read_target_count,
            "read_by_user_ids": read_by_user_ids,
            "is_read_by_me": message.sender_id == current_user_id or viewer_last_read_seq >= int(message.session_seq or 0),
        }

    def _serialize_message_content(self, message, current_user_id: str) -> str:
        if message.status == "recalled":
            return ""
        return message.content

    def _serialize_messages(self, messages: list, current_user_id: str) -> list[dict]:
        session_members_by_session = {
            session_id: self._load_session_members(session_id)
            for session_id in {message.session_id for message in messages}
        }
        return [
            self.serialize_message(
                message,
                current_user_id,
                session_members=session_members_by_session.get(message.session_id, []),
            )
            for message in messages
        ]

    def serialize_message(self, message, current_user_id: str, session_members: list | None = None) -> dict:
        if session_members is None:
            session_members = self._load_session_members(message.session_id)
        read_metadata = self._message_read_metadata(message, current_user_id, session_members)
        extra = self._message_extra(message, read_metadata)
        return {
            "id": message.id,
            "message_id": message.id,
            "msg_id": message.id,
            "session_id": message.session_id,
            "sender_id": message.sender_id,
            "content": self._serialize_message_content(message, current_user_id),
            "type": message.type,
            "message_type": message.type,
            "status": message.status,
            "created_at": message.created_at.isoformat() if message.created_at else None,
            "timestamp": message.created_at.isoformat() if message.created_at else None,
            "updated_at": message.updated_at.isoformat() if message.updated_at else None,
            "is_self": message.sender_id == current_user_id,
            "is_ai": False,
            "session_seq": read_metadata["session_seq"],
            "read_count": read_metadata["read_count"],
            "read_target_count": read_metadata["read_target_count"],
            "read_by_user_ids": read_metadata["read_by_user_ids"],
            "is_read_by_me": read_metadata["is_read_by_me"],
            "extra": extra,
        }

    def _message_extra(self, message, read_metadata: dict[str, Any]) -> dict[str, Any]:
        extra = self.messages.load_extra(message)
        extra.update(read_metadata)
        return extra

    def serialize_session_event(self, event: SessionEvent) -> dict:
        try:
            data = json.loads(event.payload or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}

        event_seq = int(event.event_seq or 0)
        data.setdefault("event_seq", event_seq)
        timestamp = int(event.created_at.timestamp()) if event.created_at else int(time.time())
        return {
            "type": event.type,
            "seq": event_seq,
            "msg_id": self._event_message_id(event.type, data),
            "timestamp": timestamp,
            "data": data,
        }

    def _record_session_event(
        self,
        session_id: str,
        event_type: str,
        data: dict[str, Any],
        *,
        message_id: str | None = None,
        actor_user_id: str | None = None,
    ) -> dict:
        payload = dict(data or {})
        event = self.messages.append_session_event(
            session_id,
            event_type,
            payload,
            message_id=message_id,
            actor_user_id=actor_user_id,
            commit=False,
        )
        payload["event_seq"] = int(event.event_seq or 0)
        return payload

    @staticmethod
    def _read_event_data(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": payload.get("session_id", ""),
            "message_id": payload.get("message_id", ""),
            "last_read_message_id": payload.get("last_read_message_id", ""),
            "last_read_seq": int(payload.get("last_read_seq", 0) or 0),
            "user_id": payload.get("user_id", ""),
            "read_at": payload.get("read_at"),
        }

    @staticmethod
    def _event_message_id(event_type: str, data: dict[str, Any]) -> str:
        if event_type == "read":
            return str(data.get("last_read_message_id") or data.get("message_id") or "")
        return str(data.get("msg_id") or data.get("message_id") or "")
