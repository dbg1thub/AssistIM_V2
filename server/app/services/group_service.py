"""Group service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.group_repo import GroupRepository
from app.repositories.message_repo import MessageRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.user_repo import UserRepository
from app.services.avatar_service import AvatarService


T = TypeVar("T")


@dataclass(frozen=True)
class GroupProfileUpdateResult:
    group: dict[str, object]
    announcement_message_id: str = ""
    participant_ids: list[str] = field(default_factory=list)


class GroupService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.groups = GroupRepository(db)
        self.messages = MessageRepository(db)
        self.sessions = SessionRepository(db)
        self.users = UserRepository(db)
        self.avatars = AvatarService(db)

    def list_groups(self, current_user: User) -> list[dict]:
        groups = self.groups.list_user_groups(current_user.id)
        return [self.serialize_group(item, include_members=True, current_user_id=current_user.id) for item in groups]

    def create_group(self, current_user: User, name: str, member_ids: list[str]) -> dict:
        members = self._normalize_group_members(current_user, member_ids)
        normalized_name = str(name or "").strip()

        def action() -> object:
            session = self.sessions.create(normalized_name, "group", commit=False)
            for member_id in members:
                self.sessions.add_member(session.id, member_id, commit=False)

            group = self.groups.create(normalized_name, current_user.id, session.id, announcement="", commit=False)
            for member_id in members:
                role = "owner" if member_id == current_user.id else "member"
                self.groups.update_member_role(group.id, member_id, role, commit=False)
            self.avatars.ensure_group_avatar(group)
            return group

        group = self._run_transaction(action)
        return self.serialize_group(group, include_members=True, current_user_id=current_user.id)

    def get_group(self, current_user: User, group_id: str) -> dict:
        group = self._get_group_or_404(group_id)
        self._ensure_group_member(group, current_user.id)
        return self.serialize_group(group, include_members=True, current_user_id=current_user.id)

    def update_group_profile(self, current_user: User, group_id: str, name: str | None, announcement: str | None) -> GroupProfileUpdateResult:
        group = self._get_group_or_404(group_id)
        self._ensure_group_member(group, current_user.id)
        current_role = self._member_role(group.id, current_user.id, owner_id=group.owner_id)
        if current_role not in {"owner", "admin"}:
            raise AppError(ErrorCode.FORBIDDEN, "only owner or admin can update group profile", 403)

        participant_ids = [
            value
            for value in dict.fromkeys(self.sessions.list_member_ids(group.session_id))
            if str(value or "").strip()
        ]
        previous_announcement = str(getattr(group, "announcement", "") or "")
        normalized_name = str(name or "").strip() if name is not None else None
        normalized_announcement = str(announcement or "").strip() if announcement is not None else None
        announcement_changed = announcement is not None and normalized_announcement != previous_announcement

        def action():
            announcement_message = None
            if name is not None:
                group.name = normalized_name or ""
                self.sessions.rename(group.session_id, group.name, commit=False)

            if announcement is not None:
                group.announcement = normalized_announcement or ""
                if group.announcement:
                    announcement_message = self.messages.create(
                        session_id=group.session_id,
                        sender_id=current_user.id,
                        content=self._build_announcement_message_body(group.announcement),
                        message_type="text",
                        extra={
                            "group_announcement": True,
                            "group_announcement_text": group.announcement,
                        },
                        commit=False,
                    )[0]
                    group.announcement_message_id = announcement_message.id
                    group.announcement_author_id = current_user.id
                    group.announcement_published_at = announcement_message.created_at
                else:
                    group.announcement_message_id = None
                    group.announcement_author_id = None
                    group.announcement_published_at = None
                self.sessions.touch_without_commit(group.session_id)

            self.db.add(group)
            self.db.flush()
            return announcement_message

        announcement_message = self._run_transaction(action)
        return GroupProfileUpdateResult(
            group=self.serialize_group(group, include_members=True, current_user_id=current_user.id),
            announcement_message_id=(str(getattr(announcement_message, "id", "") or "") if announcement_changed and announcement_message is not None else ""),
            participant_ids=participant_ids if announcement_changed and announcement_message is not None else [],
        )

    def update_my_group_profile(self, current_user: User, group_id: str, note: str | None, my_group_nickname: str | None) -> dict:
        group = self._get_group_or_404(group_id)
        self._ensure_group_member(group, current_user.id)

        def action() -> None:
            self.groups.update_member_profile(
                group.id,
                current_user.id,
                note=note,
                group_nickname=my_group_nickname,
                commit=False,
            )
            self.sessions.touch_without_commit(group.session_id)

        self._run_transaction(action)
        return self.serialize_group(group, include_members=True, current_user_id=current_user.id)

    @staticmethod
    def _build_announcement_message_body(announcement: str) -> str:
        normalized = str(announcement or "").strip()
        return f"群公告\n{normalized}" if normalized else "群公告"

    def record_group_profile_update_event(self, group_id: str, *, actor_user_id: str) -> dict[str, object] | None:
        """Append one shared group-profile update event for offline sync and realtime fan-out."""
        group = self._get_group_or_404(group_id)
        participant_ids = [
            value
            for value in dict.fromkeys(self.sessions.list_member_ids(group.session_id))
            if str(value or "").strip()
        ]
        if not participant_ids:
            return None

        payload = self.serialize_group(group, include_members=True, current_user_id=None)
        payload["group_id"] = group.id
        payload["session_id"] = group.session_id
        event = self.messages.append_session_event(
            group.session_id,
            "group_profile_update",
            payload,
            actor_user_id=actor_user_id,
            commit=False,
        )
        payload["event_seq"] = int(event.event_seq or 0)
        self.db.commit()
        return {
            "participant_ids": participant_ids,
            "payload": payload,
        }

    def build_group_self_profile_payload(self, current_user: User, group_id: str) -> dict[str, object]:
        """Build one self-scoped group-profile payload for the current user's other clients."""
        group = self._get_group_or_404(group_id)
        self._ensure_group_member(group, current_user.id)
        serialized = self.serialize_group(group, include_members=False, current_user_id=current_user.id)
        return {
            "group_id": group.id,
            "session_id": group.session_id,
            "group_note": str(serialized.get("group_note", "") or ""),
            "my_group_nickname": str(serialized.get("my_group_nickname", "") or ""),
        }


    def record_group_self_profile_update_event(self, current_user: User, group_id: str) -> dict[str, object]:
        """Append one self-scoped group-profile update event for the current user's other clients and offline sync."""
        payload = self.build_group_self_profile_payload(current_user, group_id)
        session_id = str(payload.get("session_id", "") or "")
        event = self.messages.append_private_session_event(
            session_id,
            current_user.id,
            "group_self_profile_update",
            payload,
            actor_user_id=current_user.id,
            commit=False,
        )
        payload["event_seq"] = int(event.event_seq or 0)
        self.db.commit()
        return payload

    def add_member(self, current_user: User, group_id: str, user_id: str, role: str = "member") -> dict:
        group = self._get_group_or_404(group_id)
        if group.owner_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "only owner can add members", 403)
        normalized_user_id = self._normalize_target_user_id(user_id)
        normalized_role = self._normalize_new_member_role(role)

        def action() -> None:
            self.sessions.add_member(group.session_id, normalized_user_id, commit=False)
            self.groups.update_member_role(group.id, normalized_user_id, normalized_role, commit=False)
            self.avatars.bump_group_avatar_version(group)
            self.avatars.ensure_group_avatar(group)

        self._run_transaction(action)
        return {
            "status": "added",
            "group": self.serialize_group(group, include_members=True, current_user_id=current_user.id),
        }

    def remove_member(self, current_user: User, group_id: str, user_id: str) -> None:
        group = self._get_group_or_404(group_id)
        normalized_user_id = self._normalize_target_user_id(user_id)
        if group.owner_id == normalized_user_id:
            raise AppError(ErrorCode.FORBIDDEN, "owner must transfer ownership first", 403)
        if group.owner_id != current_user.id and current_user.id != normalized_user_id:
            raise AppError(ErrorCode.FORBIDDEN, "cannot remove member", 403)

        def action() -> None:
            self.groups.remove_member(group.id, normalized_user_id, commit=False)
            self.sessions.remove_member(group.session_id, normalized_user_id, commit=False)
            self.avatars.bump_group_avatar_version(group)
            self.avatars.ensure_group_avatar(group)

        self._run_transaction(action)

    def update_member_role(self, current_user: User, group_id: str, user_id: str, role: str) -> dict:
        group = self._get_group_or_404(group_id)
        if group.owner_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "only owner can update member roles", 403)

        normalized_user_id = self._normalize_target_user_id(user_id)
        self._ensure_group_member(group, normalized_user_id)
        if group.owner_id == normalized_user_id:
            raise AppError(ErrorCode.FORBIDDEN, "owner role can only be changed via transfer", 403)

        normalized_role = self._normalize_member_role_update(role)

        def action() -> None:
            self.groups.update_member_role(group.id, normalized_user_id, normalized_role, commit=False)

        self._run_transaction(action)
        return {
            "status": "role_updated",
            "group": self.serialize_group(group, include_members=True, current_user_id=current_user.id),
        }

    def delete_group(self, current_user: User, group_id: str) -> None:
        group = self._get_group_or_404(group_id)
        if group.owner_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "only owner can delete group", 403)

        def action() -> None:
            self.groups.delete_group(group, commit=False)
            self.sessions.delete_session(group.session_id, commit=False)

        self._run_transaction(action)

    def leave_group(self, current_user: User, group_id: str) -> dict:
        group = self._get_group_or_404(group_id)
        if group.owner_id == current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "owner must transfer ownership first", 403)
        self._ensure_group_member(group, current_user.id)

        def action() -> None:
            self.groups.remove_member(group.id, current_user.id, commit=False)
            self.sessions.remove_member(group.session_id, current_user.id, commit=False)
            self.avatars.bump_group_avatar_version(group)
            self.avatars.ensure_group_avatar(group)

        self._run_transaction(action)
        return {"status": "left"}

    def transfer_ownership(self, current_user: User, group_id: str, new_owner_id: str) -> dict:
        group = self._get_group_or_404(group_id)
        if group.owner_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "only owner can transfer ownership", 403)
        normalized_new_owner_id = self._normalize_target_user_id(new_owner_id)
        self._ensure_group_member(group, normalized_new_owner_id)

        def action() -> None:
            self.groups.update_member_role(group.id, current_user.id, "member", commit=False)
            self.groups.update_member_role(group.id, normalized_new_owner_id, "owner", commit=False)
            self.groups.transfer_owner(group, normalized_new_owner_id, commit=False)

        self._run_transaction(action)
        return self.serialize_group(group, include_members=True, current_user_id=current_user.id)

    def serialize_group(self, group, include_members: bool = True, *, current_user_id: str | None = None) -> dict:
        avatar = self.avatars.ensure_group_avatar(group)
        session_members = self.sessions.list_members(group.session_id)
        group_members = self.groups.list_members(group.id)
        role_by_user_id = {item.user_id: item.role for item in group_members}
        member_meta_by_user_id = {
            item.user_id: {
                "role": str(item.role or "member"),
                "group_nickname": str(getattr(item, "group_nickname", "") or ""),
                "note": str(getattr(item, "note", "") or ""),
            }
            for item in group_members
        }
        user_ids = [str(item.user_id or "") for item in session_members if str(item.user_id or "")]
        users_by_id = self.users.list_users_by_ids(user_ids)
        current_member_meta = member_meta_by_user_id.get(str(current_user_id or ""), {})
        data = {
            "id": group.id,
            "name": group.name,
            "announcement": str(getattr(group, "announcement", "") or ""),
            "announcement_message_id": str(getattr(group, "announcement_message_id", "") or "") or None,
            "announcement_author_id": str(getattr(group, "announcement_author_id", "") or "") or None,
            "announcement_published_at": group.announcement_published_at.isoformat() if getattr(group, "announcement_published_at", None) else None,
            "avatar": avatar,
            "avatar_kind": str(getattr(group, "avatar_kind", "generated") or "generated"),
            "owner_id": group.owner_id,
            "session_id": group.session_id,
            "member_count": len(session_members),
            "created_at": group.created_at.isoformat() if group.created_at else None,
            "group_note": str(current_member_meta.get("note", "") or ""),
            "my_group_nickname": str(current_member_meta.get("group_nickname", "") or ""),
        }
        if include_members:
            members = []
            for item in session_members:
                user = users_by_id.get(str(item.user_id or ""))
                if user is None:
                    continue
                member_meta = member_meta_by_user_id.get(str(item.user_id or ""), {})
                members.append(
                    {
                        "user_id": item.user_id,
                        "id": user.id,
                        "username": user.username,
                        "nickname": user.nickname,
                        "group_nickname": str(member_meta.get("group_nickname", "") or ""),
                        "avatar": self.avatars.resolve_user_avatar_url(user),
                        "gender": user.gender,
                        "region": user.region,
                        "role": role_by_user_id.get(item.user_id, "owner" if item.user_id == group.owner_id else "member"),
                        "joined_at": item.joined_at.isoformat() if item.joined_at else None,
                    }
                )
            data["members"] = members
        return data

    def _get_group_or_404(self, group_id: str):
        group = self.groups.get_by_id(group_id)
        if group is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "group not found", 404)
        return group

    def _ensure_group_member(self, group, user_id: str) -> None:
        if not self.sessions.has_member(group.session_id, user_id):
            raise AppError(ErrorCode.FORBIDDEN, "not a group member", 403)

    def _normalize_target_user_id(self, user_id: str) -> str:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise AppError(ErrorCode.INVALID_REQUEST, "user_id is required", 422)
        if self.users.get_by_id(normalized_user_id) is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "user not found", 404)
        return normalized_user_id

    def _normalize_group_members(self, current_user: User, member_ids: list[str]) -> list[str]:
        members = [current_user.id]
        for member_id in member_ids or []:
            normalized_user_id = self._normalize_target_user_id(member_id)
            if normalized_user_id == current_user.id:
                continue
            members.append(normalized_user_id)
        return list(dict.fromkeys(members))

    def _member_role(self, group_id: str, user_id: str, *, owner_id: str) -> str:
        member = self.groups.get_member(group_id, user_id)
        if member is None:
            return "owner" if str(user_id or "") == str(owner_id or "") else "member"
        return str(member.role or "member")

    @staticmethod
    def _normalize_new_member_role(role: str) -> str:
        normalized_role = str(role or "member").strip().lower() or "member"
        if normalized_role != "member":
            raise AppError(ErrorCode.INVALID_REQUEST, "new members must use the default member role", 422)
        return normalized_role

    @staticmethod
    def _normalize_member_role_update(role: str) -> str:
        normalized_role = str(role or "member").strip().lower() or "member"
        if normalized_role not in {"member", "admin"}:
            raise AppError(ErrorCode.INVALID_REQUEST, "role must be member or admin", 422)
        return normalized_role

    def _run_transaction(self, action: Callable[[], T]) -> T:
        try:
            result = action()
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise






