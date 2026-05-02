"""add admin database backup verification fields

Revision ID: 20260503_0018
Revises: 20260503_0017
Create Date: 2026-05-03 05:55:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260503_0018"
down_revision = "20260503_0017"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if "admin_database_backups" not in _table_names(bind):
        return

    columns = _column_names(bind, "admin_database_backups")
    if "verification_status" not in columns:
        op.add_column(
            "admin_database_backups",
            sa.Column("verification_status", sa.String(length=32), nullable=False, server_default=""),
        )
    if "verification_message" not in columns:
        op.add_column(
            "admin_database_backups",
            sa.Column("verification_message", sa.Text(), nullable=False, server_default=""),
        )
    if "verified_at" not in columns:
        op.add_column("admin_database_backups", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if "admin_database_backups" not in _table_names(bind):
        return

    columns = _column_names(bind, "admin_database_backups")
    with op.batch_alter_table("admin_database_backups") as batch_op:
        if "verified_at" in columns:
            batch_op.drop_column("verified_at")
        if "verification_message" in columns:
            batch_op.drop_column("verification_message")
        if "verification_status" in columns:
            batch_op.drop_column("verification_status")
