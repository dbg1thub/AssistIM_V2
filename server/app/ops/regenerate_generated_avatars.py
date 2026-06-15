"""Server-local CLI for regenerating generated user avatars."""

from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal, configure_database
from app.models.user import User
from app.services.avatar_service import AvatarService


def regenerate_generated_user_avatars(db: Session, *, limit: int | None = None) -> list[dict[str, str]]:
    """Regenerate all server-generated user avatars with the current renderer."""
    stmt = (
        select(User)
        .where(User.avatar_kind == "generated")
        .order_by(User.created_at.asc(), User.id.asc())
    )
    if limit is not None:
        stmt = stmt.limit(max(0, int(limit)))

    users = list(db.execute(stmt).scalars().all())
    avatars = AvatarService(db, get_settings())
    changed: list[dict[str, str]] = []

    try:
        for user in users:
            old_avatar = str(user.avatar or "")
            updated = avatars.assign_generated_user_avatar(
                user,
                nickname=str(user.nickname or user.username or ""),
                commit=False,
            )
            changed.append(
                {
                    "id": str(updated.id or ""),
                    "username": str(updated.username or ""),
                    "nickname": str(updated.nickname or ""),
                    "old_avatar": old_avatar,
                    "new_avatar": str(updated.avatar or ""),
                }
            )
        db.commit()
        for user in users:
            db.refresh(user)
    except Exception:
        db.rollback()
        raise

    return changed


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Regenerate AssistIM generated user avatars.")
    parser.add_argument("--confirm-regenerate", action="store_true", help="Required. Rewrite generated avatar URLs.")
    parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of users to process.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv if argv is not None else sys.argv[1:]))
    if not args.confirm_regenerate:
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "CONFIRMATION_REQUIRED",
                    "message": "Refusing to regenerate avatars without --confirm-regenerate.",
                },
                ensure_ascii=False,
            )
        )
        return 2

    settings = get_settings()
    configure_database(settings)
    try:
        with SessionLocal() as db:
            users = regenerate_generated_user_avatars(db, limit=args.limit)
    except Exception as exc:
        print(json.dumps({"ok": False, "code": "REGENERATE_AVATARS_FAILED", "message": str(exc)}, ensure_ascii=False))
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "data": {
                    "count": len(users),
                    "users": users,
                },
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
