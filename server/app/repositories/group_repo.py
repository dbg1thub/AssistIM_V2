"""Group repository."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.group import Group, GroupMember
from app.models.session import SessionMember


class GroupRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        name: str,
        owner_id: str,
        session_id: str,
        *,
        avatar_kind: str = "generated",
        avatar_file_id: str | None = None,
        avatar_version: int = 1,
        commit: bool = True,
    ) -> Group:
        group = Group(
            name=name,
            owner_id=owner_id,
            session_id=session_id,
            avatar_kind=avatar_kind,
            avatar_file_id=avatar_file_id,
            avatar_version=max(1, int(avatar_version or 1)),
        )
        self.db.add(group)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(group)
        return group

    def get_by_id(self, group_id: str) -> Group | None:
        return self.db.get(Group, group_id)

    def get_by_session_id(self, session_id: str) -> Group | None:
        stmt = select(Group).where(Group.session_id == session_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_user_groups(self, user_id: str) -> list[Group]:
        stmt = (
            select(Group)
            .join(SessionMember, SessionMember.session_id == Group.session_id)
            .where(SessionMember.user_id == user_id)
            .order_by(Group.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_members(self, group_id: str) -> list[GroupMember]:
        stmt = (
            select(GroupMember)
            .where(GroupMember.group_id == group_id)
            .order_by(GroupMember.joined_at.asc(), GroupMember.user_id.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_member(self, group_id: str, user_id: str) -> GroupMember | None:
        return self.db.get(GroupMember, {"group_id": group_id, "user_id": user_id})

    def add_member(
        self,
        group_id: str,
        user_id: str,
        role: str = "member",
        *,
        joined_at: datetime | None = None,
        commit: bool = True,
    ) -> GroupMember:
        member = self.get_member(group_id, user_id)
        if member is None:
            member = GroupMember(group_id=group_id, user_id=user_id, role=role)
            if joined_at is not None:
                member.joined_at = joined_at
            self.db.add(member)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(member)
        return member

    def update_member_role(self, group_id: str, user_id: str, role: str, *, commit: bool = True) -> GroupMember:
        member = self.get_member(group_id, user_id)
        if member is None:
            member = GroupMember(group_id=group_id, user_id=user_id, role=role)
        else:
            member.role = role
        self.db.add(member)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(member)
        return member

    def update_avatar_state(
        self,
        group: Group,
        *,
        avatar_kind: str,
        avatar_file_id: str | None,
        avatar_version: int,
        commit: bool = True,
    ) -> Group:
        group.avatar_kind = avatar_kind
        group.avatar_file_id = avatar_file_id
        group.avatar_version = max(1, int(avatar_version or 1))
        self.db.add(group)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(group)
        return group

    def remove_member(self, group_id: str, user_id: str, *, commit: bool = True) -> bool:
        member = self.get_member(group_id, user_id)
        if member is None:
            return False

        self.db.delete(member)
        self.db.flush()
        if commit:
            self.db.commit()
        return True

    def delete_group(self, group: Group, *, commit: bool = True) -> None:
        for member in self.list_members(group.id):
            self.db.delete(member)
        self.db.delete(group)
        self.db.flush()
        if commit:
            self.db.commit()

    def transfer_owner(self, group: Group, new_owner_id: str, *, commit: bool = True) -> Group:
        group.owner_id = new_owner_id
        self.db.add(group)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(group)
        return group
