"""User service."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.message_repo import MessageRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.user_repo import UserRepository
from app.services.avatar_service import AvatarService


class UserService:
    _NULLABLE_FIELDS = {"email", "phone", "birthday", "region", "signature", "gender"}

    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.sessions = SessionRepository(db)
        self.messages = MessageRepository(db)
        self.avatars = AvatarService(db)

    def list_users(self, *, page: int = 1, size: int = 20) -> dict:
        normalized_page = max(1, page)
        normalized_size = max(1, size)
        users = self.users.list_users()
        start = (normalized_page - 1) * normalized_size
        end = start + normalized_size
        return {
            "total": len(users),
            "page": normalized_page,
            "size": normalized_size,
            "items": [self.serialize_public_user(user) for user in users[start:end]],
        }

    def get_user(self, user_id: str) -> dict:
        user = self.users.get_by_id(user_id)
        if user is None:
            raise AppError(ErrorCode.USER_NOT_FOUND, "user not found", 404)
        return self.serialize_public_user(user)

    def search_users(self, keyword: str, page: int = 1, size: int = 20) -> dict:
        total, users = self.users.search_users(keyword, page, size)
        return {
            "total": total,
            "page": page,
            "size": size,
            "items": [self.serialize_public_user(user) for user in users],
        }

    def update_me(self, current_user: User, **fields: object) -> dict:
        normalized_fields: dict[str, object] = {}
        for key, value in fields.items():
            if key in self._NULLABLE_FIELDS and isinstance(value, str) and not value.strip():
                normalized_fields[key] = None
            else:
                normalized_fields[key] = value
        user = self.users.update(current_user, **normalized_fields)
        return self.serialize_user(user)

    def record_profile_update_events(self, user: User) -> dict[str, object]:
        updated_user = self.avatars.backfill_user_avatar_state(user)
        profile_payload = self.serialize_public_user(updated_user)
        profile_event_id = f"user-profile:{updated_user.id}:{uuid.uuid4()}"
        event_payload = {
            "profile_event_id": profile_event_id,
            "user_id": updated_user.id,
            "profile": dict(profile_payload),
        }
        history_events: list[dict[str, object]] = []
        participant_ids_by_user: dict[str, str] = {}
        for session in self.sessions.list_user_sessions(updated_user.id):
            participant_ids = [
                value
                for value in self.sessions.list_member_ids(session.id)
                if str(value or "").strip()
            ]
            if session.type == "private" and not session.is_ai_session and len(set(participant_ids)) < 2:
                continue
            for participant_id in participant_ids:
                participant_ids_by_user[str(participant_id)] = str(participant_id)
            payload = dict(event_payload)
            event = self.messages.append_session_event(
                session.id,
                "user_profile_update",
                payload,
                actor_user_id=updated_user.id,
                commit=False,
            )
            payload["event_seq"] = int(event.event_seq or 0)
            history_events.append(
                {
                    "session_id": session.id,
                    "participant_ids": participant_ids,
                    "payload": payload,
                }
            )
        if history_events:
            self.db.commit()
        return {
            "payload": event_payload,
            "participant_ids": sorted(participant_ids_by_user),
            "history_events": history_events,
        }

    def serialize_public_user(self, user: User) -> dict[str, object]:
        user = self.avatars.backfill_user_avatar_state(user)
        nickname = str(user.nickname or "")
        username = str(user.username or "")
        return {
            "id": user.id,
            "username": username,
            "nickname": nickname,
            "display_name": nickname or username or user.id,
            "avatar": self.avatars.resolve_user_avatar_url(user),
            "avatar_kind": str(getattr(user, "avatar_kind", "default") or "default"),
            "gender": str(user.gender or ""),
            "region": str(user.region or ""),
            "signature": str(user.signature or ""),
            "status": str(user.status or ""),
        }

    def serialize_user(self, user: User) -> dict:
        summary = self.serialize_public_user(user)
        return {
            **summary,
            "email": user.email,
            "phone": user.phone,
            "birthday": user.birthday.isoformat() if user.birthday else None,
            "region": user.region,
            "signature": user.signature,
            "gender": user.gender,
            "status": user.status,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        }
