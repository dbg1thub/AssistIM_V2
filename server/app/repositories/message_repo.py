"""Message repository."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import and_, desc, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.message import Message, MessageRead
from app.models.session import ChatSession, SessionEvent, SessionMember, UserSessionEvent
from app.utils.time import isoformat_utc, utcnow


class MessageIdConflictError(ValueError):
    """Raised when one message id is reused for another logical message."""


class MessageRepository:
    _UNSET = object()

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
        extra: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> tuple[Message, bool]:
        if message_id is not None:
            existing = self.get_by_id(message_id)
            if existing is not None:
                return self._resolve_existing_message(existing, session_id, sender_id, content, message_type, extra), False

        payload = {
            "session_id": session_id,
            "sender_id": sender_id,
            "session_seq": self._reserve_next_session_seq(session_id),
            "content": content,
            "type": message_type,
            "extra_json": self._dump_extra(extra),
            "status": status,
        }
        if message_id is not None:
            payload["id"] = message_id

        message = Message(**payload)
        self.db.add(message)
        try:
            self.db.flush()
            if commit:
                self.db.commit()
        except IntegrityError:
            self.db.rollback()
            if message_id is not None:
                existing = self.get_by_id(message_id)
                if existing is not None:
                    return self._resolve_existing_message(existing, session_id, sender_id, content, message_type, extra), False
            raise

        if commit:
            self.db.refresh(message)
        return message, True

    def get_by_id(self, message_id: str) -> Message | None:
        return self.db.get(Message, message_id)

    def list_session_messages(
        self,
        session_id: str,
        limit: int = 50,
        before: datetime | None = None,
    ) -> list[Message]:
        stmt = select(Message).where(Message.session_id == session_id)
        if before is not None:
            stmt = stmt.where(Message.created_at < before)
        stmt = stmt.order_by(desc(Message.session_seq), desc(Message.created_at)).limit(limit)
        return list(reversed(self.db.execute(stmt).scalars().all()))

    def list_last_messages_for_sessions(self, session_ids: list[str]) -> dict[str, Message]:
        normalized_session_ids = [str(session_id or "").strip() for session_id in session_ids if str(session_id or "").strip()]
        if not normalized_session_ids:
            return {}

        latest_seq_subquery = (
            select(
                Message.session_id.label("session_id"),
                func.max(Message.session_seq).label("last_session_seq"),
            )
            .where(Message.session_id.in_(normalized_session_ids))
            .group_by(Message.session_id)
            .subquery()
        )
        stmt = (
            select(Message)
            .join(
                latest_seq_subquery,
                and_(
                    Message.session_id == latest_seq_subquery.c.session_id,
                    Message.session_seq == latest_seq_subquery.c.last_session_seq,
                ),
            )
        )
        return {str(message.session_id or ""): message for message in self.db.execute(stmt).scalars().all()}

    def list_missing_messages_for_user(self, session_cursors: dict[str, int], user_id: str) -> list[Message]:
        session_ids = list(
            self.db.execute(
                select(SessionMember.session_id).where(SessionMember.user_id == user_id)
            ).scalars().all()
        )
        if not session_ids:
            return []

        conditions = [
            and_(
                Message.session_id == session_id,
                Message.session_seq > max(0, int(session_cursors.get(session_id, 0) or 0)),
            )
            for session_id in session_ids
        ]
        if not conditions:
            return []

        stmt = (
            select(Message)
            .where(or_(*conditions))
            .order_by(Message.created_at.asc(), Message.session_id.asc(), Message.session_seq.asc(), Message.id.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_missing_events_for_user(self, event_cursors: dict[str, int], user_id: str) -> list[SessionEvent | UserSessionEvent]:
        normalized_user_id = str(user_id or '').strip()
        session_ids = list(
            self.db.execute(
                select(SessionMember.session_id).where(SessionMember.user_id == normalized_user_id)
            ).scalars().all()
        )
        if not session_ids:
            return []

        shared_conditions = [
            and_(
                SessionEvent.session_id == str(session_id or "").strip(),
                SessionEvent.event_seq > max(0, int(event_cursors.get(session_id, 0) or 0)),
            )
            for session_id in session_ids
        ]
        private_conditions = [
            and_(
                UserSessionEvent.session_id == str(session_id or "").strip(),
                UserSessionEvent.user_id == normalized_user_id,
                UserSessionEvent.event_seq > max(0, int(event_cursors.get(session_id, 0) or 0)),
            )
            for session_id in session_ids
        ]

        shared_events: list[SessionEvent] = []
        private_events: list[UserSessionEvent] = []
        if shared_conditions:
            shared_events = list(
                self.db.execute(
                    select(SessionEvent)
                    .where(or_(*shared_conditions))
                    .order_by(SessionEvent.session_id.asc(), SessionEvent.event_seq.asc(), SessionEvent.created_at.asc(), SessionEvent.id.asc())
                ).scalars().all()
            )
        if private_conditions:
            private_events = list(
                self.db.execute(
                    select(UserSessionEvent)
                    .where(or_(*private_conditions))
                    .order_by(UserSessionEvent.session_id.asc(), UserSessionEvent.event_seq.asc(), UserSessionEvent.created_at.asc(), UserSessionEvent.id.asc())
                ).scalars().all()
            )

        events: list[SessionEvent | UserSessionEvent] = [*shared_events, *private_events]
        events.sort(
            key=lambda item: (
                str(item.session_id or ''),
                int(item.event_seq or 0),
                item.created_at or utcnow(),
                str(item.id or ''),
            )
        )
        return events

    def append_session_event(
        self,
        session_id: str,
        event_type: str,
        data: dict,
        *,
        message_id: str | None = None,
        actor_user_id: str | None = None,
        commit: bool = True,
    ) -> SessionEvent:
        event = SessionEvent(
            session_id=session_id,
            event_seq=self._reserve_next_event_seq(session_id),
            type=event_type,
            message_id=message_id,
            actor_user_id=actor_user_id,
            payload=json.dumps(data, ensure_ascii=True, sort_keys=True),
        )
        self.db.add(event)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(event)
        return event


    def append_private_session_event(
        self,
        session_id: str,
        user_id: str,
        event_type: str,
        data: dict,
        *,
        actor_user_id: str | None = None,
        commit: bool = True,
    ) -> UserSessionEvent:
        event = UserSessionEvent(
            session_id=session_id,
            user_id=user_id,
            event_seq=self._reserve_next_event_seq(session_id),
            type=event_type,
            actor_user_id=actor_user_id,
            payload=json.dumps(data, ensure_ascii=True, sort_keys=True),
        )
        self.db.add(event)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(event)
        return event

    def update_status(self, message: Message, status: str, *, commit: bool = True) -> Message:
        message.status = status
        self.db.add(message)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(message)
        return message

    def update_content(
        self,
        message: Message,
        content: str,
        *,
        extra: dict[str, Any] | object = _UNSET,
        commit: bool = True,
    ) -> Message:
        message.content = content
        if extra is not self._UNSET:
            message.extra_json = self._dump_extra(extra if isinstance(extra, dict) else None)
        self.db.add(message)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(message)
        return message

    def delete(self, message: Message, *, commit: bool = True) -> None:
        self.db.query(MessageRead).filter(MessageRead.message_id == message.id).delete()
        self.db.execute(
            update(SessionMember)
            .where(SessionMember.last_read_message_id == message.id)
            .values(last_read_message_id=None)
        )
        self.db.delete(message)
        self.db.flush()
        if commit:
            self.db.commit()

    def mark_read(self, message_id: str, user_id: str, *, commit: bool = True) -> dict | None:
        message = self.get_by_id(message_id)
        if message is None:
            return None
        return self._advance_read_cursor(message.session_id, user_id, message, commit=commit)

    def mark_read_batch(self, session_id: str, user_id: str, message_id: str, *, commit: bool = True) -> dict | None:
        last_message = self.get_by_id(message_id)
        if last_message is None or last_message.session_id != session_id:
            return None
        return self._advance_read_cursor(session_id, user_id, last_message, commit=commit)

    def unread_total_for_user(self, user_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(Message)
            .join(
                SessionMember,
                and_(
                    SessionMember.session_id == Message.session_id,
                    SessionMember.user_id == user_id,
                ),
            )
            .where(
                and_(
                    Message.sender_id != user_id,
                    Message.session_seq > func.coalesce(SessionMember.last_read_seq, 0),
                )
            )
        )
        return int(self.db.execute(stmt).scalar_one())

    def unread_by_session_for_user(self, user_id: str) -> list[dict]:
        stmt = (
            select(Message.session_id, func.count().label("unread"))
            .join(
                SessionMember,
                and_(
                    SessionMember.session_id == Message.session_id,
                    SessionMember.user_id == user_id,
                ),
            )
            .where(
                and_(
                    Message.sender_id != user_id,
                    Message.session_seq > func.coalesce(SessionMember.last_read_seq, 0),
                )
            )
            .group_by(Message.session_id)
        )
        return [
            {"session_id": row.session_id, "unread": int(row.unread)}
            for row in self.db.execute(stmt).all()
        ]

    def load_extra(self, message: Message) -> dict[str, Any]:
        return self._load_extra_json(message.extra_json)

    def _advance_read_cursor(self, session_id: str, user_id: str, message: Message, *, commit: bool = True) -> dict | None:
        member = self.db.get(SessionMember, {"session_id": session_id, "user_id": user_id})
        if member is None:
            return None

        current_seq = int(member.last_read_seq or 0)
        target_seq = int(message.session_seq or 0)
        advanced = target_seq > current_seq
        if advanced:
            member.last_read_seq = target_seq
            member.last_read_message_id = message.id
            member.last_read_at = utcnow()
            self.db.add(member)
            self.db.flush()
            if commit:
                self.db.commit()
                self.db.refresh(member)

        return {
            "session_id": session_id,
            "message_id": message.id,
            "last_read_seq": int(member.last_read_seq or target_seq),
            "user_id": user_id,
            "read_at": isoformat_utc(member.last_read_at),
            "advanced": advanced,
        }

    def _reserve_next_session_seq(self, session_id: str) -> int:
        now = utcnow()
        result = self.db.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(
                last_message_seq=func.coalesce(ChatSession.last_message_seq, 0) + 1,
                updated_at=now,
            )
        )
        if int(result.rowcount or 0) == 0:
            raise ValueError(f"session not found: {session_id}")

        next_seq = self.db.execute(
            select(ChatSession.last_message_seq).where(ChatSession.id == session_id)
        ).scalar_one()
        return int(next_seq or 0)

    def _reserve_next_event_seq(self, session_id: str) -> int:
        result = self.db.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(last_event_seq=func.coalesce(ChatSession.last_event_seq, 0) + 1)
        )
        if int(result.rowcount or 0) == 0:
            raise ValueError(f"session not found: {session_id}")

        next_seq = self.db.execute(
            select(ChatSession.last_event_seq).where(ChatSession.id == session_id)
        ).scalar_one()
        return int(next_seq or 0)

    def _resolve_existing_message(
        self,
        existing: Message,
        session_id: str,
        sender_id: str,
        content: str,
        message_type: str,
        extra: dict[str, Any] | None,
    ) -> Message:
        if (
            existing.session_id != session_id
            or existing.sender_id != sender_id
            or existing.content != content
            or existing.type != message_type
            or existing.extra_json != self._dump_extra(extra)
        ):
            raise MessageIdConflictError("message id already used for another message")
        return existing

    @staticmethod
    def _dump_extra(extra: dict[str, Any] | None) -> str:
        if not extra:
            return "{}"
        return json.dumps(extra, ensure_ascii=True, sort_keys=True)

    @staticmethod
    def _load_extra_json(raw_value: str | None) -> dict[str, Any]:
        if not raw_value:
            return {}
        try:
            payload = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}








