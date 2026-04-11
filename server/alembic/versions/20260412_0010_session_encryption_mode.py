"""add authoritative session encryption mode

Revision ID: 20260412_0010
Revises: 20260405_0009
Create Date: 2026-04-12 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260412_0010"
down_revision = "20260405_0009"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if "sessions" not in _table_names(bind):
        return
    if "encryption_mode" in _column_names(bind, "sessions"):
        return
    op.add_column(
        "sessions",
        sa.Column("encryption_mode", sa.String(length=32), nullable=False, server_default="plain"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "sessions" not in _table_names(bind):
        return
    if "encryption_mode" not in _column_names(bind, "sessions"):
        return
    op.drop_column("sessions", "encryption_mode")
