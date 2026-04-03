"""User service."""

from __future__ import annotations

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

    def list_users(self) -> list[dict]:
        return [self.serialize_user(self.avatars.backfill_user_avatar_state(user)) for user in self.users.list_users()]

    def get_user(self, user_id: str) -> dict:
        user = self.users.get_by_id(user_id)
        if user is None:
            raise AppError(ErrorCode.USER_NOT_FOUND, "user not found", 404)
        user = self.avatars.backfill_user_avatar_state(user)
        return self.serialize_user(user)

    def search_users(self, keyword: str, page: int = 1, size: int = 20) -> dict:
        total, users = self.users.search_users(keyword, page, size)
        return {
            "total": total,
            "page": page,
            "size": size,
            "items": [self.serialize_user(self.avatars.backfill_user_avatar_state(user)) for user in users],
        }

    def update_me(self, current_user: User, **fields: object) -> dict:
        normalized_fields: dict[str, object] = {}
        for key, value in fields.items():
            if key in self._NULLABLE_FIELDS and isinstance(value, str) and not value.strip():
                normalized_fields[key] = None
            else:
                normalized_fields[key] = value
        user = self.users.update(current_user, **normalized_fields)
        user = self.avatars.backfill_user_avatar_state(user)
        return self.serialize_user(user)

    def record_profile_update_events(self, user: User) -> list[dict[str, object]]:
        updated_user = self.avatars.backfill_user_avatar_state(user)
        profile_payload = self.serialize_profile_event_user(updated_user)
        events: list[dict[str, object]] = []
        for session in self.sessions.list_user_sessions(updated_user.id):
            participant_ids = [
                value
                for value in self.sessions.list_member_ids(session.id)
                if str(value or "").strip()
            ]
            if session.type == "private" and not session.is_ai_session and len(set(participant_ids)) < 2:
                continue
            payload = {
                "session_id": session.id,
                "user_id": updated_user.id,
                "profile": dict(profile_payload),
                "session_avatar": session.avatar,
            }
            event = self.messages.append_session_event(
                session.id,
                "user_profile_update",
                payload,
                actor_user_id=updated_user.id,
                commit=False,
            )
            payload["event_seq"] = int(event.event_seq or 0)
            events.append(
                {
                    "session_id": session.id,
                    "participant_ids": participant_ids,
                    "payload": payload,
                }
            )
        if events:
            self.db.commit()
        return events

    @staticmethod
    def serialize_profile_event_user(user: User) -> dict[str, object]:
        nickname = str(user.nickname or "")
        username = str(user.username or "")
        return {
            "id": user.id,
            "username": username,
            "nickname": nickname,
            "display_name": nickname or username or user.id,
            "avatar": user.avatar,
            "avatar_kind": str(getattr(user, "avatar_kind", "default") or "default"),
            "gender": str(user.gender or ""),
            "signature": str(user.signature or ""),
            "status": str(user.status or ""),
        }

    @staticmethod
    def serialize_user(user: User) -> dict:
        return {
            "id": user.id,
            "username": user.username,
            "nickname": user.nickname,
            "avatar": user.avatar,
            "avatar_kind": str(getattr(user, "avatar_kind", "default") or "default"),
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
