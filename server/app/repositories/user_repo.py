"""User repository."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.auth_contract import canonicalize_username
from app.models.user import User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, user_id: str) -> User | None:
        return self.db.get(User, user_id)

    def get_by_username(self, username: str) -> User | None:
        canonical_username = canonicalize_username(username)
        stmt = select(User).where(func.lower(User.username) == canonical_username)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_users_by_ids(self, user_ids: list[str]) -> dict[str, User]:
        normalized_user_ids = [str(user_id or "").strip() for user_id in user_ids if str(user_id or "").strip()]
        if not normalized_user_ids:
            return {}
        stmt = select(User).where(User.id.in_(normalized_user_ids))
        return {str(user.id or ""): user for user in self.db.execute(stmt).scalars().all()}

    def list_users(self, page: int = 1, size: int = 20) -> tuple[int, list[User]]:
        normalized_page = max(1, int(page or 1))
        normalized_size = max(1, int(size or 20))
        total = self.db.execute(select(func.count()).select_from(User)).scalar_one()
        stmt = (
            select(User)
            .order_by(User.created_at.desc())
            .offset((normalized_page - 1) * normalized_size)
            .limit(normalized_size)
        )
        return int(total or 0), list(self.db.execute(stmt).scalars().all())

    def search_users(self, keyword: str, page: int = 1, size: int = 20) -> tuple[int, list[User]]:
        normalized_keyword = canonicalize_username(keyword) if "." in str(keyword or "") else str(keyword or "").strip().lower()
        pattern = f"%{normalized_keyword}%"
        base_stmt = select(User).where(
            or_(
                func.lower(User.username).like(pattern),
                func.lower(func.coalesce(User.nickname, "")).like(pattern),
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
        commit: bool = True,
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
        self.db.flush()
        if commit:
            self.db.commit()
            self.db.refresh(user)
        return user

    def update(self, user: User, *, commit: bool = True, **fields: object) -> User:
        for key, value in fields.items():
            if hasattr(user, key):
                setattr(user, key, value)
        self.db.add(user)
        self.db.flush()
        if commit:
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
        commit: bool = True,
    ) -> User:
        return self.update(
            user,
            avatar_kind=avatar_kind,
            avatar_default_key=avatar_default_key,
            avatar_file_id=avatar_file_id,
            avatar=avatar,
            commit=commit,
        )

    def advance_auth_session_version(self, user: User, *, commit: bool = True) -> User:
        current_version = int(getattr(user, "auth_session_version", 0) or 0)
        return self.update(user, auth_session_version=current_version + 1, commit=commit)
