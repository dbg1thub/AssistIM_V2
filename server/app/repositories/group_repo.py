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
        announcement: str = "",
        avatar_kind: str = "generated",
        avatar_file_id: str | None = None,
        avatar_version: int = 1,
        commit: bool = True,
    ) -> Group:
        group = Group(
            name=name,
            owner_id=owner_id,
            session_id=session_id,
            announcement=str(announcement or "").strip(),
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

    def list_by_session_ids(self, session_ids: list[str]) -> dict[str, Group]:
        normalized_session_ids = [
            str(session_id or "").strip()
            for session_id in session_ids
            if str(session_id or "").strip()
        ]
        if not normalized_session_ids:
            return {}
        stmt = select(Group).where(Group.session_id.in_(normalized_session_ids))
        return {
            str(group.session_id or ""): group
            for group in self.db.execute(stmt).scalars().all()
            if str(group.session_id or "")
        }

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

    def list_members_for_groups(self, group_ids: list[str]) -> dict[str, list[GroupMember]]:
        normalized_group_ids = [
            str(group_id or "").strip()
            for group_id in group_ids
            if str(group_id or "").strip()
        ]
        if not normalized_group_ids:
            return {}
        stmt = (
            select(GroupMember)
            .where(GroupMember.group_id.in_(normalized_group_ids))
            .order_by(GroupMember.group_id.asc(), GroupMember.joined_at.asc(), GroupMember.user_id.asc())
        )
        members_by_group: dict[str, list[GroupMember]] = {group_id: [] for group_id in normalized_group_ids}
        for member in self.db.execute(stmt).scalars().all():
            group_id = str(member.group_id or "")
            if not group_id:
                continue
            members_by_group.setdefault(group_id, []).append(member)
        return members_by_group

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

    def update_group_profile(
        self,
        group: Group,
        *,
        name: str | None = None,
        announcement: str | None = None,
        commit: bool = True,
    ) -> Group:
        if name is not None:
            group.name = str(name or "").strip()
        if announcement is not None:
            group.announcement = str(announcement or "").strip()
        self.db.add(group)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(group)
        return group

    def update_member_profile(
        self,
        group_id: str,
        user_id: str,
        *,
        group_nickname: str | None = None,
        note: str | None = None,
        commit: bool = True,
    ) -> GroupMember:
        member = self.get_member(group_id, user_id)
        if member is None:
            member = GroupMember(group_id=group_id, user_id=user_id)
        if group_nickname is not None:
            member.group_nickname = str(group_nickname or "").strip()
        if note is not None:
            member.note = str(note or "").strip()
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
