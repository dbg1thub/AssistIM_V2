"""Server-local CLI for assigning admin roles."""

from __future__ import annotations

import argparse
import json
import sys

from app.core.config import get_settings
from app.core.database import SessionLocal, configure_database
from app.core.errors import AppError
from app.services.admin_user_service import AdminUserService


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set one AssistIM user's admin role.")
    parser.add_argument("--username", required=True, help="Canonical username to update.")
    parser.add_argument("--role", default="admin", choices=["user", "admin"], help="Target role.")
    parser.add_argument("--actor", default="server-script", help="Audit actor username.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv if argv is not None else sys.argv[1:]))
    settings = get_settings()
    configure_database(settings)
    try:
        with SessionLocal() as db:
            result = AdminUserService(db).set_user_role_by_username(
                args.username,
                args.role,
                actor_username=args.actor,
            )
    except AppError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "message": exc.message}, ensure_ascii=False))
        return 1
    except Exception as exc:
        print(json.dumps({"ok": False, "code": "ERROR", "message": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps({"ok": True, "data": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
