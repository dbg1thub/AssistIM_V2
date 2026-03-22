"""Group service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.repositories.group_repo import GroupRepository
from app.repositories.session_repo import SessionRepository


class GroupService:
    def __init__(self, db: Session) -> None:
        self.groups = GroupRepository(db)
        self.sessions = SessionRepository(db)

    def list_groups(self, current_user: User) -> list[dict]:
        groups = self.groups.list_user_groups(current_user.id)
        for group in groups:
            self._ensure_group_session_members(group.id, group.session_id)
        return [self.serialize_group(item, include_members=False) for item in groups]

    def create_group(self, current_user: User, name: str, member_ids: list[str]) -> dict:
        unique_member_ids = [member_id for member_id in dict.fromkeys(member_ids or []) if member_id != current_user.id]
        session = self.sessions.create(name, "group")
        self.sessions.add_member(session.id, current_user.id)
        for member_id in unique_member_ids:
            self.sessions.add_member(session.id, member_id)

        group = self.groups.create(name, current_user.id, session.id)
        self.groups.add_member(group.id, current_user.id, "owner")
        for member_id in unique_member_ids:
            self.groups.add_member(group.id, member_id)
        return self.serialize_group(group, include_members=True)

    def get_group(self, current_user: User, group_id: str) -> dict:
        group = self.groups.get_by_id(group_id)
        if group is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "group not found", 404)
        if self.groups.get_member(group_id, current_user.id) is None:
            raise AppError(ErrorCode.FORBIDDEN, "not a group member", 403)
        self._ensure_group_session_members(group.id, group.session_id)
        return self.serialize_group(group, include_members=True)

    def add_member(self, current_user: User, group_id: str, user_id: str, role: str = "member") -> dict:
        group = self.groups.get_by_id(group_id)
        if group is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "group not found", 404)
        if group.owner_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "only owner can add members", 403)
        self.groups.add_member(group_id, user_id, role)
        self.sessions.add_member(group.session_id, user_id)
        return {"status": "added"}

    def remove_member(self, current_user: User, group_id: str, user_id: str) -> None:
        group = self.groups.get_by_id(group_id)
        if group is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "group not found", 404)
        if group.owner_id != current_user.id and current_user.id != user_id:
            raise AppError(ErrorCode.FORBIDDEN, "cannot remove member", 403)
        self.groups.remove_member(group_id, user_id)
        self.sessions.remove_member(group.session_id, user_id)

    def delete_group(self, current_user: User, group_id: str) -> None:
        group = self.groups.get_by_id(group_id)
        if group is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "group not found", 404)
        if group.owner_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "only owner can delete group", 403)
        self.groups.delete_group(group)
        self.sessions.delete_session(group.session_id)

    def leave_group(self, current_user: User, group_id: str) -> dict:
        group = self.groups.get_by_id(group_id)
        if group is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "group not found", 404)
        if group.owner_id == current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "owner must transfer ownership first", 403)
        self.groups.remove_member(group_id, current_user.id)
        self.sessions.remove_member(group.session_id, current_user.id)
        return {"status": "left"}

    def transfer_ownership(self, current_user: User, group_id: str, new_owner_id: str) -> dict:
        group = self.groups.get_by_id(group_id)
        if group is None:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND, "group not found", 404)
        if group.owner_id != current_user.id:
            raise AppError(ErrorCode.FORBIDDEN, "only owner can transfer ownership", 403)
        if self.groups.get_member(group_id, new_owner_id) is None:
            raise AppError(ErrorCode.INVALID_REQUEST, "new owner must be a group member", 422)
        self.groups.update_member_role(group_id, current_user.id, "member")
        self.groups.update_member_role(group_id, new_owner_id, "owner")
        group = self.groups.transfer_owner(group, new_owner_id)
        self._ensure_group_session_members(group.id, group.session_id)
        return self.serialize_group(group, include_members=True)

    def serialize_group(self, group, include_members: bool = True) -> dict:
        data = {
            "id": group.id,
            "name": group.name,
            "owner_id": group.owner_id,
            "session_id": group.session_id,
            "member_count": len(self.groups.list_members(group.id)),
            "created_at": group.created_at.isoformat() if group.created_at else None,
        }
        if include_members:
            data["members"] = [
                {"user_id": item.user_id, "role": item.role}
                for item in self.groups.list_members(group.id)
            ]
        return data

    def _ensure_group_session_members(self, group_id: str, session_id: str) -> None:
        for member in self.groups.list_members(group_id):
            self.sessions.add_member(session_id, member.user_id)
