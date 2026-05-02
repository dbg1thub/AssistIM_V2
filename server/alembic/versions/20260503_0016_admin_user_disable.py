"""add admin user disable fields

Revision ID: 20260503_0016
Revises: 20260503_0015
Create Date: 2026-05-03 04:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260503_0016"
down_revision = "20260503_0015"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if "users" not in _table_names(bind):
        return

    columns = _column_names(bind, "users")
    if "is_disabled" not in columns:
        op.add_column(
            "users",
            sa.Column("is_disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "disabled_at" not in columns:
        op.add_column("users", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))
    if "disabled_reason" not in columns:
        op.add_column(
            "users",
            sa.Column("disabled_reason", sa.Text(), nullable=False, server_default=""),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "users" not in _table_names(bind):
        return

    columns = _column_names(bind, "users")
    with op.batch_alter_table("users") as batch_op:
        if "disabled_reason" in columns:
            batch_op.drop_column("disabled_reason")
        if "disabled_at" in columns:
            batch_op.drop_column("disabled_at")
        if "is_disabled" in columns:
            batch_op.drop_column("is_disabled")
