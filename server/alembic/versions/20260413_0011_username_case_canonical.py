"""add case canonical username uniqueness

Revision ID: 20260413_0011
Revises: 20260412_0010
Create Date: 2026-04-13 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260413_0011"
down_revision = "20260412_0010"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _index_names(bind, table_name: str) -> set[str]:
    if bind.dialect.name == "sqlite":
        rows = bind.execute(
            sa.text("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = :table_name"),
            {"table_name": table_name},
        ).scalars().all()
        return {str(row) for row in rows}
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if "users" not in _table_names(bind):
        return
    if "uq_users_username_lower" in _index_names(bind, "users"):
        return
    op.create_index(
        "uq_users_username_lower",
        "users",
        [sa.text("lower(username)")],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "users" not in _table_names(bind):
        return
    if "uq_users_username_lower" not in _index_names(bind, "users"):
        return
    op.drop_index("uq_users_username_lower", table_name="users")
