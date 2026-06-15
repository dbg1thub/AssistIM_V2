"""Server-local CLI for seeding reset test users."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal, configure_database
from app.core.security import hash_password
from app.repositories.user_repo import UserRepository
from app.services.avatar_service import AvatarService


DEFAULT_TEST_PASSWORD = "Test@123456"


@dataclass(frozen=True, slots=True)
class TestUserSpec:
    username: str
    nickname: str
    email: str


TEST_USER_SPECS: tuple[TestUserSpec, ...] = (
    TestUserSpec(username="test1", nickname="李小康", email="test1@example.test"),
    TestUserSpec(username="test2", nickname="邓斌", email="test2@example.test"),
    TestUserSpec(username="test3", nickname="蒋雨辰", email="test3@example.test"),
    TestUserSpec(username="test4", nickname="이소강", email="test4@example.test"),
    TestUserSpec(username="test5", nickname="등빈", email="test5@example.test"),
    TestUserSpec(username="test6", nickname="장우진", email="test6@example.test"),
)


def seed_test_users(db: Session, *, password: str = DEFAULT_TEST_PASSWORD) -> list[dict[str, str]]:
    """Create the fixed reset-test users in a freshly initialized database."""
    users = UserRepository(db)
    avatars = AvatarService(db, get_settings())
    _ensure_no_existing_test_users(users)

    created = []
    try:
        for spec in TEST_USER_SPECS:
            user = users.create(
                username=spec.username,
                password_hash=hash_password(password),
                nickname=spec.nickname,
                email=spec.email,
                email_verified=True,
                avatar_kind="generated",
                commit=False,
            )
            user = avatars.assign_generated_user_avatar(user, nickname=spec.nickname, commit=False)
            user = users.advance_auth_session_version(user, commit=False)
            created.append(user)
        db.commit()
        for user in created:
            db.refresh(user)
    except Exception:
        db.rollback()
        raise

    return [
        {
            "id": str(user.id or ""),
            "username": str(user.username or ""),
            "nickname": str(user.nickname or ""),
            "email": str(user.email or ""),
        }
        for user in created
    ]


def _ensure_no_existing_test_users(users: UserRepository) -> None:
    for spec in TEST_USER_SPECS:
        if users.get_by_username(spec.username) is not None:
            raise RuntimeError(f"test user already exists: {spec.username}")
        if users.get_by_email(spec.email) is not None:
            raise RuntimeError(f"test user email already exists: {spec.email}")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed AssistIM reset-test users.")
    parser.add_argument("--password", default=DEFAULT_TEST_PASSWORD, help="Password assigned to all test users.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv if argv is not None else sys.argv[1:]))
    settings = get_settings()
    configure_database(settings)
    try:
        with SessionLocal() as db:
            users = seed_test_users(db, password=args.password)
    except Exception as exc:
        print(json.dumps({"ok": False, "code": "SEED_TEST_USERS_FAILED", "message": str(exc)}, ensure_ascii=False))
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "data": {
                    "password": args.password,
                    "users": users,
                },
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
