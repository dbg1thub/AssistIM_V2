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

    def list_users_by_ids(self, user_ids: list[str]) -> dict[str, User]:
        normalized_user_ids = [str(user_id or "").strip() for user_id in user_ids if str(user_id or "").strip()]
        if not normalized_user_ids:
            return {}
        stmt = select(User).where(User.id.in_(normalized_user_ids))
        return {str(user.id or ""): user for user in self.db.execute(stmt).scalars().all()}

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

    def create(
        self,
        username: str,
        password_hash: str,
        nickname: str,
        *,
        avatar: str | None = None,
        avatar_kind: str = "default",
        avatar_default_key: str | None = None,
        avatar_file_id: str | None = None,
    ) -> User:
        user = User(
            username=username,
            password_hash=password_hash,
            nickname=nickname,
            avatar=avatar,
            avatar_kind=avatar_kind,
            avatar_default_key=avatar_default_key,
            avatar_file_id=avatar_file_id,
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

    def update_avatar_state(
        self,
        user: User,
        *,
        avatar_kind: str,
        avatar_default_key: str | None,
        avatar_file_id: str | None,
        avatar: str | None,
    ) -> User:
        return self.update(
            user,
            avatar_kind=avatar_kind,
            avatar_default_key=avatar_default_key,
            avatar_file_id=avatar_file_id,
            avatar=avatar,
        )

    def advance_auth_session_version(self, user: User) -> User:
        current_version = int(getattr(user, "auth_session_version", 0) or 0)
        return self.update(user, auth_session_version=current_version + 1)
