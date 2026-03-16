"""Group repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.group import Group, GroupMember


class GroupRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, name: str, owner_id: str, session_id: str) -> Group:
        group = Group(name=name, owner_id=owner_id, session_id=session_id)
        self.db.add(group)
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
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(GroupMember.user_id == user_id)
            .order_by(Group.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_members(self, group_id: str) -> list[GroupMember]:
        stmt = select(GroupMember).where(GroupMember.group_id == group_id)
        return list(self.db.execute(stmt).scalars().all())

    def get_member(self, group_id: str, user_id: str) -> GroupMember | None:
        return self.db.get(GroupMember, {"group_id": group_id, "user_id": user_id})

    def add_member(self, group_id: str, user_id: str, role: str = "member") -> None:
        existing = self.db.get(GroupMember, {"group_id": group_id, "user_id": user_id})
        if existing is None:
            self.db.add(GroupMember(group_id=group_id, user_id=user_id, role=role))
            self.db.commit()

    def update_member_role(self, group_id: str, user_id: str, role: str) -> None:
        existing = self.get_member(group_id, user_id)
        if existing is not None:
            existing.role = role
            self.db.add(existing)
            self.db.commit()

    def remove_member(self, group_id: str, user_id: str) -> None:
        member = self.db.get(GroupMember, {"group_id": group_id, "user_id": user_id})
        if member is not None:
            self.db.delete(member)
            self.db.commit()

    def delete_group(self, group: Group) -> None:
        for member in self.list_members(group.id):
            self.db.delete(member)
        self.db.delete(group)
        self.db.commit()

    def transfer_owner(self, group: Group, new_owner_id: str) -> Group:
        group.owner_id = new_owner_id
        self.db.add(group)
        self.db.commit()
        self.db.refresh(group)
        return group
