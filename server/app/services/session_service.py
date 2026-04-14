"""Session service."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
from typing import TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.group_repo import GroupRepository
from app.repositories.message_repo import MessageRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.user_repo import UserRepository
from app.services.avatar_service import AvatarService
from app.utils.time import isoformat_utc


T = TypeVar("T")


class SessionService:
    RECALLED_MESSAGE_PLACEHOLDER = "[message recalled]"
    ENCRYPTED_MESSAGE_PLACEHOLDER = "[encrypted message]"
    ATTACHMENT_MESSAGE_PREVIEW_PLACEHOLDERS = {
        "file": "[file]",
        "image": "[image]",
        "video": "[video]",
        "voice": "[voice]",
    }
    ENCRYPTION_MODE_PLAIN = 'plain'
    ENCRYPTION_MODE_E2EE_PRIVATE = 'e2ee_private'
    ENCRYPTION_MODE_E2EE_GROUP = 'e2ee_group'
    ENCRYPTION_MODE_SERVER_VISIBLE_AI = 'server_visible_ai'
    SUPPORTED_ENCRYPTION_MODES = {
        ENCRYPTION_MODE_PLAIN,
        ENCRYPTION_MODE_E2EE_PRIVATE,
        ENCRYPTION_MODE_E2EE_GROUP,
        ENCRYPTION_MODE_SERVER_VISIBLE_AI,
    }

    def __init__(self, db: Session) -> None:
        self.db = db
        self.sessions = SessionRepository(db)
        self.messages = MessageRepository(db)
        self.users = UserRepository(db)
        self.groups = GroupRepository(db)
        self.avatars = AvatarService(db)

    def list_sessions(self, current_user: User) -> list[dict]:
        session_items = self.sessions.list_user_sessions(current_user.id)
        session_ids = [item.id for item in session_items]
        members_by_session = self.sessions.list_members_for_sessions(session_ids)
        last_messages_by_session = self.messages.list_last_messages_for_sessions(session_ids)
        unread_counts_by_session = self._unread_counts_by_session(current_user.id)
        group_sessions = [
            item
            for item in session_items
            if str(getattr(item, "type", "") or "").strip().lower() == "group"
        ]
        groups_by_session = self.groups.list_by_session_ids([item.id for item in group_sessions])
        group_members_by_group = self.groups.list_members_for_groups(
            [
                str(group.id or "")
                for group in groups_by_session.values()
                if str(group.id or "")
            ]
        )
        user_ids = sorted(
            {
                str(member.user_id or "")
                for members in members_by_session.values()
                for member in members
                if str(member.user_id or "")
            }
        )
        users_by_id = self.users.list_users_by_ids(user_ids)

        payload: list[dict] = []
        for item in session_items:
            session_members = members_by_session.get(item.id, [])
            member_ids = [str(member.user_id or "") for member in session_members if str(member.user_id or "")]
            if not self._is_visible_private_session(item, member_ids):
                continue
            payload.append(
                self.serialize_session(
                    item,
                    include_members=False,
                    include_self_fields=False,
                    participant_ids=member_ids,
                    last_message=last_messages_by_session.get(item.id),
                    session_members=session_members,
                    group=groups_by_session.get(str(item.id or "")),
                    group_members=group_members_by_group.get(
                        str(getattr(groups_by_session.get(str(item.id or "")), "id", "") or "")
                    ),
                    users_by_id=users_by_id,
                    current_user_id=current_user.id,
                    unread_count=unread_counts_by_session.get(str(item.id or ""), 0),
                )
            )
        return payload

    def create_private(
        self,
        current_user: User,
        participant_ids: list[str],
        encryption_mode: str = 'plain',
    ) -> dict:
        members = self._normalize_private_members(current_user, participant_ids)
        direct_key = self.sessions.build_private_direct_key(members)
        normalized_encryption_mode = (
            self.ENCRYPTION_MODE_E2EE_PRIVATE
            if str(encryption_mode or '').strip().lower() == self.ENCRYPTION_MODE_E2EE_PRIVATE
            else self.ENCRYPTION_MODE_PLAIN
        )
        existing = self.sessions.get_private_session_by_direct_key(direct_key)
        if existing is not None:
            existing_member_ids = self.sessions.list_member_ids(existing.id)
            if (
                not self._is_visible_private_session(existing, existing_member_ids)
                or set(existing_member_ids) != set(members)
            ):
                raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)
            unread_count = self._unread_counts_by_session(current_user.id).get(str(existing.id or ""), 0)
            payload = self.serialize_session(
                existing,
                include_members=False,
                include_self_fields=False,
                participant_ids=existing_member_ids,
                current_user_id=current_user.id,
                unread_count=unread_count,
            )
            payload["created"] = False
            payload["reused"] = True
            return payload

        def action() -> object:
            session = self.sessions.create(
                "Private Chat",
                "private",
                direct_key=direct_key,
                commit=False,
                encryption_mode=normalized_encryption_mode,
            )
            for member_id in members:
                self.sessions.add_member(session.id, member_id, commit=False)
            return session

        created = True
        try:
            session = self._run_transaction(action)
        except IntegrityError:
            existing = self.sessions.get_private_session_by_direct_key(direct_key)
            if existing is None:
                raise
            session = existing
            created = False
        unread_count = self._unread_counts_by_session(current_user.id).get(str(session.id or ""), 0)
        existing_member_ids = self.sessions.list_member_ids(str(session.id or ""))
        payload = self.serialize_session(
            session,
            include_members=False,
            include_self_fields=False,
            participant_ids=existing_member_ids,
            current_user_id=current_user.id,
            unread_count=unread_count,
        )
        payload["created"] = created
        payload["reused"] = not created
        return payload

    def get_session(self, current_user: User, session_id: str) -> dict:
        session = self.sessions.get_by_id(session_id)
        if session is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)

        member_ids = self.sessions.list_member_ids(session_id)
        if current_user.id not in member_ids:
            raise AppError(ErrorCode.FORBIDDEN, "not a session member", 403)
        if not self._is_visible_private_session(session, member_ids):
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "session not found", 404)
        unread_count = self._unread_counts_by_session(current_user.id).get(str(session.id or ""), 0)
        session_type = "direct" if session.type == "private" else session.type
        return self.serialize_session(
            session,
            include_members=session_type == "group",
            include_self_fields=session_type == "group",
            participant_ids=member_ids,
            current_user_id=current_user.id,
            unread_count=unread_count,
        )

    def list_member_ids(self, session_id: str) -> list[str]:
        return self.sessions.list_member_ids(session_id)

    def serialize_session(
        self,
        session,
        *,
        include_members: bool = False,
        include_self_fields: bool = False,
        participant_ids: list[str] | None = None,
        last_message=None,
        session_members: list | None = None,
        group=None,
        group_members: list | None = None,
        users_by_id: dict[str, User] | None = None,
        current_user_id: str | None = None,
        unread_count: int = 0,
    ) -> dict:
        member_ids = participant_ids if participant_ids is not None else self.sessions.list_member_ids(session.id)
        if last_message is None:
            messages = self.messages.list_session_messages(session.id, limit=1)
            last_message = messages[-1] if messages else None
        normalized_session_type = "direct" if session.type == "private" else session.type
        avatar = session.avatar
        member_rows = session_members if session_members is not None else None
        user_map = users_by_id or {}
        owner_id = ""
        group_id = ""
        group_announcement = ""
        group_note = ""
        my_group_nickname = ""
        role_by_user_id: dict[str, str] = {}
        member_profile_by_user_id: dict[str, dict[str, str]] = {}
        announcement_message_id = ""
        announcement_author_id = ""
        announcement_published_at = None
        if normalized_session_type == "group":
            group = group if group is not None else self.groups.get_by_session_id(session.id)
            if group is not None:
                avatar = self.avatars.resolve_group_avatar_url(group)
                group_id = str(group.id or "")
                owner_id = str(group.owner_id or "")
                group_announcement = str(getattr(group, "announcement", "") or "")
                announcement_message_id = str(getattr(group, "announcement_message_id", "") or "")
                announcement_author_id = str(getattr(group, "announcement_author_id", "") or "")
                announcement_published_at = getattr(group, "announcement_published_at", None)
                group_members = group_members if group_members is not None else self.groups.list_members(group.id)
                role_by_user_id = {
                    str(item.user_id or ""): str(item.role or "member")
                    for item in group_members
                }
                member_profile_by_user_id = {
                    str(item.user_id or ""): {
                        "group_nickname": str(getattr(item, "group_nickname", "") or ""),
                        "note": str(getattr(item, "note", "") or ""),
                    }
                    for item in group_members
                }
                current_member_profile = member_profile_by_user_id.get(str(current_user_id or ""), {})
                group_note = str(current_member_profile.get("note", "") or "")
                my_group_nickname = str(current_member_profile.get("group_nickname", "") or "")

        if include_members or normalized_session_type == "direct":
            member_rows = member_rows if member_rows is not None else self.sessions.list_members(session.id)
            if not user_map:
                user_map = self.users.list_users_by_ids([member.user_id for member in member_rows])

        counterpart = self._serialize_counterpart_profile(
            normalized_session_type,
            member_rows or [],
            user_map,
            current_user_id=current_user_id,
        )

        data = {
            "id": session.id,
            "session_type": normalized_session_type,
            "name": session.name,
            "participant_ids": member_ids,
            "last_message": self._serialize_last_message_preview(last_message),
            "last_message_id": str(last_message.id or "") if last_message else None,
            "last_message_status": last_message.status if last_message else None,
            "last_message_sender_id": last_message.sender_id if last_message else None,
            "last_message_time": (
                isoformat_utc(last_message.created_at) if last_message else None
            ),
            "updated_at": isoformat_utc(session.updated_at),
            "unread_count": max(0, int(unread_count or 0)),
            "avatar": avatar,
            "is_ai_session": session.is_ai_session,
            "encryption_mode": self._resolve_encryption_mode(
                encryption_mode=getattr(session, "encryption_mode", None),
                session_type=normalized_session_type,
                is_ai_session=bool(session.is_ai_session),
            ),
            "call_capabilities": self._call_capabilities(
                session_type=normalized_session_type,
                is_ai_session=bool(session.is_ai_session),
            ),
            "created_at": isoformat_utc(session.created_at),
            "group_id": group_id or None,
            "owner_id": owner_id or None,
            "group_announcement": group_announcement,
            "announcement_message_id": announcement_message_id or None,
            "announcement_author_id": announcement_author_id or None,
            "announcement_published_at": announcement_published_at.isoformat() if announcement_published_at else None,
            "counterpart_id": counterpart.get("id") or None,
            "counterpart_name": counterpart.get("display_name") or None,
            "counterpart_username": counterpart.get("username") or None,
            "counterpart_avatar": counterpart.get("avatar") or None,
            "counterpart_gender": counterpart.get("gender") or None,
        }
        if normalized_session_type == "group":
            data["member_version"] = self._group_member_version(member_ids)
            if include_self_fields:
                data["group_note"] = group_note
                data["my_group_nickname"] = my_group_nickname
        if include_members and normalized_session_type == "group":
            members = []
            for member in member_rows or []:
                user = user_map.get(str(member.user_id or ""))
                if user is not None:
                    members.append(
                        self._serialize_member_summary(
                            user,
                            joined_at=member.joined_at,
                            role=role_by_user_id.get(str(user.id or ""), "owner" if str(user.id or "") == owner_id else "member"),
                            group_nickname=member_profile_by_user_id.get(str(user.id or ""), {}).get("group_nickname", ""),
                        )
                    )
            data["members"] = members
        return data

    def _serialize_member_summary(
        self,
        user: User,
        *,
        joined_at=None,
        role: str = "",
        group_nickname: str = "",
    ) -> dict[str, str | None]:
        return {
            "id": str(user.id or ""),
            "username": str(user.username or ""),
            "nickname": str(user.nickname or ""),
            "avatar": self.avatars.resolve_user_avatar_url(user),
            "group_nickname": str(group_nickname or ""),
            "role": str(role or "member"),
            "joined_at": isoformat_utc(joined_at),
        }

    def _serialize_counterpart_profile(
        self,
        session_type: str,
        member_rows: list,
        users_by_id: dict[str, User],
        *,
        current_user_id: str | None = None,
    ) -> dict[str, str]:
        if session_type != "direct":
            return {}

        normalized_current_user_id = str(current_user_id or "").strip()
        for member in member_rows:
            member_user_id = str(member.user_id or "")
            if normalized_current_user_id and member_user_id == normalized_current_user_id:
                continue
            user = users_by_id.get(member_user_id)
            if user is None:
                continue
            nickname = str(user.nickname or "")
            username = str(user.username or "")
            return {
                "id": user.id,
                "username": username,
                "nickname": nickname,
                "display_name": nickname or username or user.id,
                "avatar": self.avatars.resolve_user_avatar_url(user) or "",
                "gender": str(user.gender or ""),
            }
        return {}

    @staticmethod
    def _serialize_last_message_preview(last_message) -> str | None:
        if last_message is None:
            return None
        if last_message.status == "recalled":
            return SessionService.RECALLED_MESSAGE_PLACEHOLDER

        message_type = str(getattr(last_message, "type", "text") or "text").strip().lower()
        attachment_preview = SessionService.ATTACHMENT_MESSAGE_PREVIEW_PLACEHOLDERS.get(message_type)
        if attachment_preview is not None:
            return attachment_preview

        if message_type == "text":
            extra = SessionService._last_message_extra(last_message)
            encryption = extra.get("encryption") if isinstance(extra.get("encryption"), dict) else {}
            if encryption.get("enabled"):
                return SessionService.ENCRYPTED_MESSAGE_PLACEHOLDER

        return str(getattr(last_message, "content", "") or "")

    @staticmethod
    def _last_message_extra(last_message) -> dict:
        raw_extra = getattr(last_message, "extra", None)
        if isinstance(raw_extra, dict):
            return raw_extra

        raw_extra_json = getattr(last_message, "extra_json", None)
        if not raw_extra_json:
            return {}
        try:
            payload = json.loads(raw_extra_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

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

    def _require_existing_user(self, user_id: str) -> None:
        if self.users.get_by_id(user_id) is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "user not found", 404)

    @staticmethod
    def _is_visible_private_session(session, member_ids: list[str]) -> bool:
        if session.type != "private" or session.is_ai_session:
            return True
        return len(set(member_ids)) >= 2

    @staticmethod
    def _group_member_version(member_ids: list[str]) -> int:
        normalized_member_ids = [
            value
            for value in dict.fromkeys(str(raw_id or "").strip() for raw_id in member_ids or [])
            if value
        ]
        payload = json.dumps(sorted(normalized_member_ids), ensure_ascii=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return int(digest[:16], 16)

    def _unread_counts_by_session(self, user_id: str) -> dict[str, int]:
        return {
            str(item.get("session_id") or ""): max(0, int(item.get("unread", 0) or 0))
            for item in self.messages.unread_by_session_for_user(user_id)
            if str(item.get("session_id") or "")
        }

    def _run_transaction(self, action: Callable[[], T]) -> T:
        try:
            result = action()
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    @staticmethod
    def _call_capabilities(*, session_type: str, is_ai_session: bool) -> dict[str, bool]:
        normalized_session_type = str(session_type or "").strip().lower()
        supports_direct_call = normalized_session_type == "direct" and not is_ai_session
        return {
            "voice": supports_direct_call,
            "video": supports_direct_call,
        }

    @classmethod
    def _resolve_encryption_mode(cls, *, encryption_mode: str | None, session_type: str, is_ai_session: bool) -> str:
        """Return the authoritative encryption mode for one session payload."""
        normalized_session_type = str(session_type or "").strip().lower()
        if is_ai_session or normalized_session_type == "ai":
            return cls.ENCRYPTION_MODE_SERVER_VISIBLE_AI
        normalized_mode = str(encryption_mode or "").strip().lower()
        if normalized_mode in cls.SUPPORTED_ENCRYPTION_MODES:
            return normalized_mode
        return cls.ENCRYPTION_MODE_PLAIN
