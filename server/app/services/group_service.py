"""Group service."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.group_repo import GroupRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.user_repo import UserRepository
from app.services.avatar_service import AvatarService


T = TypeVar("T")


class GroupService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.groups = GroupRepository(db)
        self.sessions = SessionRepository(db)
        self.users = UserRepository(db)
        self.avatars = AvatarService(db)

    def list_groups(self, current_user: User) -> list[dict]:
        groups = self.groups.list_user_groups(current_user.id)
        return [self.serialize_group(item, include_members=True) for item in groups]

    def create_group(self, current_user: User, name: str, member_ids: list[str]) -> dict:
        members = self._normalize_group_members(current_user, member_ids)
        normalized_name = str(name or "").strip()

        def action() -> object:
            session = self.sessions.create(normalized_name, "group", commit=False)
            for member_id in members:
                self.sessions.add_member(session.id, member_id, commit=False)

            group = self.groups.create(normalized_name, current_user.id, session.id, commit=False)
            for member_id in members:
                role = "owner" if member_id == current_user.id else "member"
                self.groups.update_member_role(group.id, member_id, role, commit=False)
            self.avatars.ensure_group_avatar(group)
            return group

        group = self._run_transaction(action)
        return self.serialize_group(group, include_members=True)

    def get_group(self, current_user: User, group_id: str) -> dict:
        group = self._get_group_or_404(group_id)
        self._ensure_group_member(group, current_user.id)
        return self.serialize_group(group, include_members=True)

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
            "group": self.serialize_group(group, include_members=True),
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
            "group": self.serialize_group(group, include_members=True),
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
        return self.serialize_group(group, include_members=True)

    def serialize_group(self, group, include_members: bool = True) -> dict:
        avatar = self.avatars.ensure_group_avatar(group)
        session_members = self.sessions.list_members(group.session_id)
        role_by_user_id = {item.user_id: item.role for item in self.groups.list_members(group.id)}
        user_ids = [str(item.user_id or "") for item in session_members if str(item.user_id or "")]
        users_by_id = self.users.list_users_by_ids(user_ids)
        data = {
            "id": group.id,
            "name": group.name,
            "avatar": avatar,
            "avatar_kind": str(getattr(group, "avatar_kind", "generated") or "generated"),
            "owner_id": group.owner_id,
            "session_id": group.session_id,
            "member_count": len(session_members),
            "created_at": group.created_at.isoformat() if group.created_at else None,
        }
        if include_members:
            members = []
            for item in session_members:
                user = users_by_id.get(str(item.user_id or ""))
                if user is None:
                    continue
                members.append(
                    {
                        "user_id": item.user_id,
                        "id": user.id,
                        "username": user.username,
                        "nickname": user.nickname,
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




