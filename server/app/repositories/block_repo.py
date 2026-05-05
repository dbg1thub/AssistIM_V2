"""User block repository."""

from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.user import UserBlock


class BlockRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_block(self, user_id: str, blocked_user_id: str, *, commit: bool = True) -> UserBlock:
        block = UserBlock(user_id=user_id, blocked_user_id=blocked_user_id)
        self.db.add(block)
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(block)
        return block

    def get_block(self, user_id: str, blocked_user_id: str) -> UserBlock | None:
        stmt = select(UserBlock).where(
            and_(UserBlock.user_id == user_id, UserBlock.blocked_user_id == blocked_user_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_blocks(self, user_id: str) -> list[UserBlock]:
        stmt = (
            select(UserBlock)
            .where(UserBlock.user_id == user_id)
            .order_by(UserBlock.created_at.desc(), UserBlock.blocked_user_id.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def has_block_relation(self, user_id: str, other_user_id: str) -> bool:
        stmt = select(UserBlock).where(
            or_(
                and_(UserBlock.user_id == user_id, UserBlock.blocked_user_id == other_user_id),
                and_(UserBlock.user_id == other_user_id, UserBlock.blocked_user_id == user_id),
            )
        )
        return self.db.execute(stmt).scalar_one_or_none() is not None

    def remove_block(self, user_id: str, blocked_user_id: str, *, commit: bool = True) -> bool:
        block = self.get_block(user_id, blocked_user_id)
        if block is None:
            return False
        self.db.delete(block)
        self.db.flush()
        if commit:
            self.db.commit()
        return True
