"""Group service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
import json
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
    changed: bool = False


@dataclass(frozen=True)
class GroupSelfProfileUpdateResult:
    profile: dict[str, object]
    changed: bool = False


class GroupService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.groups = GroupRepository(db)
        self.messages = MessageRepository(db)
        self.sessions = SessionRepository(db)
        self.users = UserRepository(db)
        self.avatars = AvatarService(db)

    @staticmethod
    def group_mutation_result(
        action: str,
        group: dict[str, object] | None,
        *,
        group_id: str = "",
        session_id: str = "",
        changed: bool = True,
        **meta: object,
    ) -> dict[str, object]:
        resolved_group_id = str((group or {}).get("id", "") or group_id or "").strip()
        resolved_session_id = str((group or {}).get("session_id", "") or session_id or "").strip()
        mutation = {
            "action": action,
            "changed": bool(changed),
            "group_id": resolved_group_id,
            "session_id": resolved_session_id,
        }
        mutation.update(meta)
        return {
            "group": group,
            "mutation": mutation,
        }

    def list_groups(self, current_user: User) -> list[dict]:
        groups = self.groups.list_user_groups(current_user.id)
        return [self.serialize_group(item, include_members=False, include_self_fields=False, current_user_id=current_user.id) for item in groups]

    def create_group(
        self,
        current_user: User,
        name: str,
        member_ids: list[str],
        encryption_mode: str = "plain",
    ) -> dict:
        members = self._normalize_group_members(current_user, member_ids)
        normalized_name = str(name or "").strip()
        normalized_encryption_mode = (
            "e2ee_group"
            if str(encryption_mode or "").strip().lower() == "e2ee_group"
            else "plain"
        )

        def action() -> object:
            session = self.sessions.create(
                normalized_name,
                "group",
                encryption_mode=normalized_encryption_mode,
                commit=False,
            )
            for member_id in members:
                self.sessions.add_member(session.id, member_id, commit=False)

            group = self.groups.create(normalized_name, current_user.id, session.id, announcement="", commit=False)
            for member_id in members:
                role = "owner" if member_id == current_user.id else "member"
                self.groups.add_member(group.id, member_id, role, commit=False)
            self.avatars.ensure_group_avatar(group)
            return group

        group = self._run_transaction(action)
        group_payload = self.serialize_group(group, include_members=True, include_self_fields=False, current_user_id=None)
        return self.group_mutation_result("created", group_payload)

    def get_group(self, current_user: User, group_id: str) -> dict:
        group = self._get_group_or_404(group_id)
        self._ensure_group_member(group, current_user.id)
        return self.serialize_group(group, include_members=True, include_self_fields=True, current_user_id=current_user.id)

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
        previous_name = str(getattr(group, "name", "") or "")
        normalized_name = str(name or "").strip() if name is not None else None
        normalized_announcement = str(announcement or "").strip() if announcement is not None else None
        name_changed = name is not None and normalized_name != previous_name
        announcement_changed = announcement is not None and normalized_announcement != previous_announcement
        changed = name_changed or announcement_changed
        if not changed:
            return GroupProfileUpdateResult(
                group=self.serialize_group(group, include_members=True, current_user_id=None),
                changed=False,
            )

        def action():
            announcement_message = None
            if name_changed:
                group.name = normalized_name or ""
                self.sessions.rename(group.session_id, group.name, commit=False)

            if announcement_changed:
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
            group=self.serialize_group(group, include_members=True, current_user_id=None),
            announcement_message_id=(str(getattr(announcement_message, "id", "") or "") if announcement_changed and announcement_message is not None else ""),
            participant_ids=participant_ids if announcement_changed and announcement_message is not None else [],
            changed=True,
        )

    def update_my_group_profile(
        self,
        current_user: User,
        group_id: str,
        note: str | None,
        my_group_nickname: str | None,
    ) -> GroupSelfProfileUpdateResult:
        group = self._get_group_or_404(group_id)
        self._ensure_group_member(group, current_user.id)
        member = self.groups.get_member(group.id, current_user.id)
        if member is None:
            raise AppError(ErrorCode.SESSION_CONFLICT, "group member profile missing", 409)

        current_note = str(getattr(member, "note", "") or "")
        current_group_nickname = str(getattr(member, "group_nickname", "") or "")
        next_note = str(note or "") if note is not None else current_note
        next_group_nickname = str(my_group_nickname or "") if my_group_nickname is not None else current_group_nickname
        changed = next_note != current_note or next_group_nickname != current_group_nickname

        if changed:
            def action() -> None:
                member.note = next_note
                member.group_nickname = next_group_nickname
                self.db.add(member)
                self.db.flush()

            self._run_transaction(action)

        return GroupSelfProfileUpdateResult(
            profile=self.serialize_group_self_profile(group, current_user.id, member=member),
            changed=changed,
        )

    @staticmethod
    def _build_announcement_message_body(announcement: str) -> str:
        normalized = str(announcement or "").strip()
        return f"群公告\n{normalized}" if normalized else "群公告"

    def record_group_profile_update_event(
        self,
        group_id: str,
        *,
        actor_user_id: str,
        mutation: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        """Append one shared group-profile update event for offline sync and realtime fan-out."""
        group = self._get_group_or_404(group_id)
        participant_ids = [
            value
            for value in dict.fromkeys(self.sessions.list_member_ids(group.session_id))
            if str(value or "").strip()
        ]
        if not participant_ids:
            return None

        payload = self.serialize_group(group, include_members=True, include_self_fields=False, current_user_id=None)
        payload["group_id"] = group.id
        payload["session_id"] = group.session_id
        payload.pop("group_note", None)
        payload.pop("my_group_nickname", None)
        if mutation:
            payload["mutation"] = dict(mutation)
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

    def serialize_group_self_profile(self, group, user_id: str, *, member=None) -> dict[str, object]:
        """Serialize only the current user's group-scoped profile fields."""
        resolved_member = member if member is not None else self.groups.get_member(group.id, user_id)
        if resolved_member is None:
            raise AppError(ErrorCode.SESSION_CONFLICT, "group member profile missing", 409)
        return {
            "group_id": group.id,
            "session_id": group.session_id,
            "group_note": str(getattr(resolved_member, "note", "") or ""),
            "my_group_nickname": str(getattr(resolved_member, "group_nickname", "") or ""),
        }

    def build_group_self_profile_payload(self, current_user: User, group_id: str) -> dict[str, object]:
        """Build one self-scoped group-profile payload for the current user's other clients."""
        group = self._get_group_or_404(group_id)
        self._ensure_group_member(group, current_user.id)
        return self.serialize_group_self_profile(group, current_user.id)

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
        if self.groups.get_member(group.id, normalized_user_id) is not None or self.sessions.has_member(group.session_id, normalized_user_id):
            raise AppError(ErrorCode.SESSION_CONFLICT, "user is already a group member", 409)

        def action() -> None:
            self.sessions.add_member(group.session_id, normalized_user_id, commit=False)
            self.groups.add_member(group.id, normalized_user_id, normalized_role, commit=False)
            self.avatars.bump_group_avatar_version(group)
            self.avatars.ensure_group_avatar(group)
            self.sessions.touch_without_commit(group.session_id)

        self._run_transaction(action)
        group_payload = self.serialize_group(group, include_members=True, include_self_fields=False, current_user_id=None)
        return self.group_mutation_result(
            "member_added",
            group_payload,
            target_user_id=normalized_user_id,
            role=normalized_role,
        )

    def remove_member(self, current_user: User, group_id: str, user_id: str) -> dict[str, object]:
        group = self._get_group_or_404(group_id)
        normalized_user_id = self._normalize_target_user_id(user_id)
        if group.owner_id == normalized_user_id:
            raise AppError(ErrorCode.FORBIDDEN, "owner must transfer ownership first", 403)
        if group.owner_id != current_user.id and current_user.id != normalized_user_id:
            raise AppError(ErrorCode.FORBIDDEN, "cannot remove member", 403)
        if self.groups.get_member(group.id, normalized_user_id) is None or not self.sessions.has_member(group.session_id, normalized_user_id):
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "group member not found", 404)

        def action() -> None:
            removed_group_member = self.groups.remove_member(group.id, normalized_user_id, commit=False)
            removed_session_member = self.sessions.remove_member(group.session_id, normalized_user_id, commit=False)
            if not removed_group_member or not removed_session_member:
                raise AppError(ErrorCode.SESSION_CONFLICT, "group membership drift detected", 409)
            self.avatars.bump_group_avatar_version(group)
            self.avatars.ensure_group_avatar(group)
            self.sessions.touch_without_commit(group.session_id)

        self._run_transaction(action)
        group_payload = None
        if current_user.id != normalized_user_id:
            group_payload = self.serialize_group(group, include_members=True, include_self_fields=False, current_user_id=None)
        return self.group_mutation_result(
            "member_removed",
            group_payload,
            group_id=group.id,
            session_id=group.session_id,
            target_user_id=normalized_user_id,
        )

    def update_member_role(self, current_user: User, group_id: str, user_id: str, role: str) -> dict:
        group = self._get_group_or_404(group_id)
        if group.owner_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "only owner can update member roles", 403)

        normalized_user_id = self._normalize_target_user_id(user_id)
        self._ensure_group_member(group, normalized_user_id)
        if group.owner_id == normalized_user_id:
            raise AppError(ErrorCode.FORBIDDEN, "owner role can only be changed via transfer", 403)

        normalized_role = self._normalize_member_role_update(role)
        current_role = self._member_role(group.id, normalized_user_id, owner_id=group.owner_id)
        changed = current_role != normalized_role

        def action() -> None:
            if not changed:
                return
            self.groups.update_member_role(group.id, normalized_user_id, normalized_role, commit=False)
            self.sessions.touch_without_commit(group.session_id)

        self._run_transaction(action)
        group_payload = self.serialize_group(group, include_members=True, include_self_fields=False, current_user_id=None)
        return self.group_mutation_result(
            "member_role_updated",
            group_payload,
            changed=changed,
            target_user_id=normalized_user_id,
            role=normalized_role,
        )

    def delete_group(self, current_user: User, group_id: str) -> dict[str, object]:
        group = self._get_group_or_404(group_id)
        if group.owner_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "only owner can delete group", 403)
        session_id = group.session_id
        participant_ids = [
            value
            for value in dict.fromkeys(self.sessions.list_member_ids(session_id))
            if str(value or "").strip()
        ]

        def action() -> None:
            self.avatars.cleanup_group_avatar_assets(group)
            self.groups.delete_group(group, commit=False)
            self.sessions.delete_session(group.session_id, commit=False)

        self._run_transaction(action)
        return self.group_mutation_result(
            "deleted",
            None,
            group_id=group_id,
            session_id=session_id,
            participant_ids=participant_ids,
        )

    def leave_group(self, current_user: User, group_id: str) -> dict:
        group = self._get_group_or_404(group_id)
        if group.owner_id == current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "owner must transfer ownership first", 403)
        self._ensure_group_member(group, current_user.id)

        def action() -> None:
            removed_group_member = self.groups.remove_member(group.id, current_user.id, commit=False)
            removed_session_member = self.sessions.remove_member(group.session_id, current_user.id, commit=False)
            if not removed_group_member or not removed_session_member:
                raise AppError(ErrorCode.SESSION_CONFLICT, "group membership drift detected", 409)
            self.avatars.bump_group_avatar_version(group)
            self.avatars.ensure_group_avatar(group)
            self.sessions.touch_without_commit(group.session_id)

        self._run_transaction(action)
        return self.group_mutation_result(
            "left",
            None,
            group_id=group.id,
            session_id=group.session_id,
        )

    def transfer_ownership(self, current_user: User, group_id: str, new_owner_id: str) -> dict:
        group = self._get_group_or_404(group_id)
        if group.owner_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "only owner can transfer ownership", 403)
        normalized_new_owner_id = self._normalize_target_user_id(new_owner_id)
        if normalized_new_owner_id == current_user.id:
            raise AppError(ErrorCode.SESSION_CONFLICT, "new owner must be a different group member", 409)
        self._ensure_group_member(group, normalized_new_owner_id)

        def action() -> None:
            self.groups.update_member_role(group.id, current_user.id, "member", commit=False)
            self.groups.update_member_role(group.id, normalized_new_owner_id, "owner", commit=False)
            self.groups.transfer_owner(group, normalized_new_owner_id, commit=False)
            self.sessions.touch_without_commit(group.session_id)

        self._run_transaction(action)
        group_payload = self.serialize_group(group, include_members=True, include_self_fields=False, current_user_id=None)
        return self.group_mutation_result(
            "ownership_transferred",
            group_payload,
            previous_owner_id=current_user.id,
            new_owner_id=normalized_new_owner_id,
        )

    def serialize_group(
        self,
        group,
        include_members: bool = False,
        *,
        include_self_fields: bool = False,
        current_user_id: str | None = None,
    ) -> dict:
        avatar = self.avatars.resolve_group_avatar_url(group)
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
        user_ids = [str(item.user_id or "") for item in group_members if str(item.user_id or "")]
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
            "member_count": len(group_members),
            "member_version": self._group_member_version_from_members(group_members, owner_id=group.owner_id),
            "created_at": group.created_at.isoformat() if group.created_at else None,
        }
        if include_self_fields:
            data["group_note"] = str(current_member_meta.get("note", "") or "")
            data["my_group_nickname"] = str(current_member_meta.get("group_nickname", "") or "")
        if include_members:
            members = []
            for item in group_members:
                user = users_by_id.get(str(item.user_id or ""))
                if user is None:
                    continue
                member_meta = member_meta_by_user_id.get(str(item.user_id or ""), {})
                members.append(
                    self._serialize_member_summary(
                        user,
                        joined_at=item.joined_at,
                        role=role_by_user_id.get(item.user_id, "owner" if item.user_id == group.owner_id else "member"),
                        group_nickname=str(member_meta.get("group_nickname", "") or "") if str(current_user_id or "") == str(item.user_id or "") else "",
                    )
                )
            data["members"] = members
        return data

    def _serialize_member_summary(
        self,
        user,
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
            "joined_at": joined_at.isoformat() if joined_at else None,
        }

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

    @staticmethod
    def _group_member_version_from_members(members: list, *, owner_id: str) -> int:
        payload_items = []
        for member in members or []:
            user_id = str(getattr(member, "user_id", "") or "").strip()
            if not user_id:
                continue
            payload_items.append(
                {
                    "user_id": user_id,
                    "role": str(getattr(member, "role", "") or "member"),
                    "owner": user_id == str(owner_id or ""),
                    "joined_at": getattr(member, "joined_at", None).isoformat() if getattr(member, "joined_at", None) else "",
                }
            )
        payload = json.dumps(sorted(payload_items, key=lambda item: item["user_id"]), ensure_ascii=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return int(digest[:16], 16)

    def _get_group_or_404(self, group_id: str):
        group = self.groups.get_by_id(group_id)
        if group is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "group not found", 404)
        return group

    def _ensure_group_member(self, group, user_id: str) -> None:
        if not self.sessions.has_member(group.session_id, user_id):
            raise AppError(ErrorCode.FORBIDDEN, "not a group member", 403)
        if self.groups.get_member(group.id, user_id) is None:
            raise AppError(ErrorCode.SESSION_CONFLICT, "group member profile missing", 409)

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
            raise AppError(ErrorCode.SESSION_CONFLICT, "group member profile missing", 409)
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






