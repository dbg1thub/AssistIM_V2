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
from app.repositories.group_repo import GroupRepository
from app.repositories.message_repo import MessageIdConflictError, MessageRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.user_repo import UserRepository
from app.services.avatar_service import AvatarService
from app.utils.time import ensure_utc, isoformat_utc, utcnow


class MessageService:
    RECALL_LIMIT = timedelta(minutes=2)
    EDIT_LIMIT = timedelta(minutes=2)

    def __init__(self, db: Session) -> None:
        self.db = db
        self.messages = MessageRepository(db)
        self.sessions = SessionRepository(db)
        self.groups = GroupRepository(db)
        self.users = UserRepository(db)
        self.avatars = AvatarService(db)

    def list_messages(
        self,
        current_user: User,
        session_id: str,
        limit: int = 50,
        before: datetime | None = None,
    ) -> list[dict]:
        self._ensure_membership(current_user.id, session_id)
        items = self.messages.list_session_messages(session_id, limit=limit, before=before)
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
        normalized_extra = self._normalize_message_extra(
            sender_id=current_user.id,
            session_id=session_id,
            content=content,
            message_type=message_type,
            extra=extra,
        )
        try:
            message, _ = self.messages.create(
                session_id=session_id,
                sender_id=current_user.id,
                content=content,
                message_type=message_type,
                message_id=message_id,
                extra=normalized_extra,
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
        normalized_extra = self._normalize_message_extra(
            sender_id=sender_id,
            session_id=session_id,
            content=content,
            message_type=message_type,
            extra=extra,
        )
        try:
            message, created = self.messages.create(
                session_id=session_id,
                sender_id=sender_id,
                content=content,
                message_type=message_type,
                message_id=message_id,
                extra=normalized_extra,
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

    def batch_read(self, current_user: User, session_id: str, message_id: str) -> dict:
        self._ensure_membership(current_user.id, session_id)
        last_message = self.messages.get_by_id(message_id)
        if last_message is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "message not found", 404)
        if last_message.session_id != session_id:
            raise AppError(ErrorCode.INVALID_REQUEST, "message does not belong to the session", 422)

        payload = self.messages.mark_read_batch(session_id, current_user.id, message_id, commit=False)
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
            "message_id": message.id,
            "user_id": current_user.id,
            "status": "recalled",
            "updated_at": isoformat_utc(message.updated_at),
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

    def _normalize_message_extra(
        self,
        *,
        sender_id: str,
        session_id: str,
        content: str,
        message_type: str,
        extra: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        normalized_extra = dict(extra or {})
        mentions = self._normalize_mentions(normalized_extra.get("mentions"), content=content)
        if str(message_type or "text").strip().lower() != "text":
            mentions = []

        if any(str(item.get("mention_type", "") or "") == "all" for item in mentions):
            self._ensure_can_mention_everyone(sender_id, session_id)

        if mentions:
            normalized_extra["mentions"] = mentions
        else:
            normalized_extra.pop("mentions", None)
        return normalized_extra or None

    def _ensure_can_mention_everyone(self, sender_id: str, session_id: str) -> None:
        session = self.sessions.get_by_id(session_id)
        if session is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)
        if str(session.type or "") != "group":
            raise AppError(ErrorCode.INVALID_REQUEST, "@all is only available in group chats", 422)

        group = self.groups.get_by_session_id(session_id)
        if group is None:
            raise AppError(ErrorCode.INVALID_REQUEST, "group metadata not found", 422)
        if str(group.owner_id or "") == sender_id:
            return

        membership = self.groups.get_member(group.id, sender_id)
        role = str(getattr(membership, "role", "") or "").strip().lower()
        if role not in {"owner", "admin"}:
            raise AppError(ErrorCode.FORBIDDEN, "@all requires owner or admin privileges", 403)

    @staticmethod
    def _normalize_mentions(raw_mentions: Any, *, content: str) -> list[dict[str, Any]]:
        if not isinstance(raw_mentions, list):
            return []

        text = str(content or "")
        text_length = len(text)
        normalized: list[dict[str, Any]] = []
        for item in raw_mentions:
            if not isinstance(item, dict):
                continue
            try:
                start = int(item.get("start", -1))
                end = int(item.get("end", -1))
            except (TypeError, ValueError):
                continue

            if start < 0 or end <= start or start >= text_length:
                continue
            end = min(end, text_length)
            if end <= start:
                continue

            display_name = str(item.get("display_name", "") or "").strip()
            if not display_name or text[start:end] != f"@{display_name}":
                continue

            mention_type = str(item.get("mention_type", "member") or "member").strip().lower()
            if mention_type not in {"member", "all"}:
                mention_type = "member"

            payload: dict[str, Any] = {
                "start": start,
                "end": end,
                "display_name": display_name,
                "mention_type": mention_type,
            }
            if mention_type == "member":
                member_id = str(item.get("member_id", "") or "").strip()
                if not member_id:
                    continue
                payload["member_id"] = member_id
            normalized.append(payload)

        normalized.sort(key=lambda item: (int(item["start"]), int(item["end"])))
        return normalized

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
        session_ids = {message.session_id for message in messages}
        session_members_by_session = {
            session_id: self._load_session_members(session_id)
            for session_id in session_ids
        }
        session_metadata_by_session = {
            session_id: self._load_session_metadata(
                session_id,
                session_members=session_members_by_session.get(session_id, []),
            )
            for session_id in session_ids
        }
        sender_ids = sorted(
            {
                str(message.sender_id or "")
                for message in messages
                if str(message.sender_id or "")
            }
        )
        sender_users_by_id = self.users.list_users_by_ids(sender_ids) if sender_ids else {}
        return [
            self.serialize_message(
                message,
                current_user_id,
                session_members=session_members_by_session.get(message.session_id, []),
                session_metadata=session_metadata_by_session.get(message.session_id),
                sender_users_by_id=sender_users_by_id,
            )
            for message in messages
        ]

    def serialize_message(
        self,
        message,
        current_user_id: str,
        session_members: list | None = None,
        session_metadata: dict[str, Any] | None = None,
        sender_users_by_id: dict[str, User] | None = None,
    ) -> dict:
        if session_members is None:
            session_members = self._load_session_members(message.session_id)
        if session_metadata is None:
            session_metadata = self._load_session_metadata(
                message.session_id,
                session_members=session_members,
            )
        read_metadata = self._message_read_metadata(message, current_user_id, session_members)
        extra = self._message_extra(message, read_metadata)
        sender_profile = self._serialize_sender_profile(
            str(message.sender_id or ""),
            users_by_id=sender_users_by_id,
        )
        return {
            "message_id": message.id,
            "session_id": message.session_id,
            "sender_id": message.sender_id,
            "content": self._serialize_message_content(message, current_user_id),
            "message_type": message.type,
            "status": message.status,
            "created_at": isoformat_utc(message.created_at),
            "timestamp": isoformat_utc(message.created_at),
            "updated_at": isoformat_utc(message.updated_at),
            "is_self": message.sender_id == current_user_id,
            "is_ai": False,
            "session_type": session_metadata.get("session_type", ""),
            "session_name": session_metadata.get("session_name", ""),
            "session_avatar": session_metadata.get("session_avatar"),
            "participant_ids": session_metadata.get("participant_ids", []),
            "is_ai_session": session_metadata.get("is_ai_session", False),
            "sender_profile": sender_profile,
            "session_seq": read_metadata["session_seq"],
            "read_count": read_metadata["read_count"],
            "read_target_count": read_metadata["read_target_count"],
            "read_by_user_ids": read_metadata["read_by_user_ids"],
            "is_read_by_me": read_metadata["is_read_by_me"],
            "extra": extra,
        }

    def _load_session_metadata(
        self,
        session_id: str,
        *,
        session_members: list | None = None,
    ) -> dict[str, Any]:
        session = self.sessions.get_by_id(session_id)
        if session is None:
            return {
                "session_type": "",
                "session_name": "",
                "session_avatar": None,
                "participant_ids": [],
                "is_ai_session": False,
            }

        members = session_members if session_members is not None else self._load_session_members(session_id)
        normalized_session_type = "direct" if session.type == "private" else str(session.type or "")
        participant_ids = list(dict.fromkeys(str(member.user_id or "") for member in members if str(member.user_id or "")))
        return {
            "session_type": normalized_session_type,
            "session_name": str(session.name or ""),
            "session_avatar": session.avatar,
            "participant_ids": participant_ids,
            "is_ai_session": bool(session.is_ai_session),
        }

    def _serialize_sender_profile(
        self,
        user_id: str,
        *,
        users_by_id: dict[str, User] | None = None,
    ) -> dict[str, Any] | None:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return None

        user = (users_by_id or {}).get(normalized_user_id)
        if user is None:
            user = self.users.get_by_id(normalized_user_id)
        if user is None:
            return None

        user = self.avatars.backfill_user_avatar_state(user)
        nickname = str(user.nickname or "")
        username = str(user.username or "")
        return {
            "id": user.id,
            "username": username,
            "nickname": nickname,
            "display_name": nickname or username or user.id,
            "avatar": self.avatars.resolve_user_avatar_url(user),
            "avatar_kind": str(getattr(user, "avatar_kind", "") or ""),
            "gender": str(user.gender or ""),
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
            "last_read_seq": int(payload.get("last_read_seq", 0) or 0),
            "user_id": payload.get("user_id", ""),
            "read_at": payload.get("read_at"),
        }

    @staticmethod
    def _event_message_id(event_type: str, data: dict[str, Any]) -> str:
        return str(data.get("message_id") or "")









