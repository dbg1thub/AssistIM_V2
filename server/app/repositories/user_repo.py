"""User repository."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, user_id: str) -> User | None:
        return self.db.get(User, user_id)

    def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_users(self) -> list[User]:
        stmt = select(User).order_by(User.created_at.desc())
        return list(self.db.execute(stmt).scalars().all())

    def search_users(self, keyword: str, page: int = 1, size: int = 20) -> tuple[int, list[User]]:
        pattern = f"%{keyword}%"
        base_stmt = select(User).where(
            or_(
                User.username.ilike(pattern),
                User.nickname.ilike(pattern),
                User.email.ilike(pattern),
                User.phone.ilike(pattern),
            )
        )
        total = self.db.execute(select(func.count()).select_from(base_stmt.subquery())).scalar_one()
        stmt = base_stmt.order_by(User.created_at.desc()).offset((page - 1) * size).limit(size)
        return total, list(self.db.execute(stmt).scalars().all())

    def create(self, username: str, password_hash: str, nickname: str, *, avatar: str | None = None) -> User:
        user = User(
            username=username,
            password_hash=password_hash,
            nickname=nickname,
            avatar=avatar,
            status="online",
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update(self, user: User, **fields: object) -> User:
        for key, value in fields.items():
            if hasattr(user, key):
                setattr(user, key, value)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def advance_auth_session_version(self, user: User) -> User:
        current_version = int(getattr(user, "auth_session_version", 0) or 0)
        return self.update(user, auth_session_version=current_version + 1)
