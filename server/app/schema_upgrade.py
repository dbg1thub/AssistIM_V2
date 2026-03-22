"""Run lightweight schema compatibility upgrades without Alembic."""

from __future__ import annotations

from app.core.database import engine
from app.core.schema_compat import describe_schema_compatibility, ensure_schema_compatibility


def main() -> None:
    applied = ensure_schema_compatibility(engine)
    print(describe_schema_compatibility(applied))


if __name__ == "__main__":
    main()
