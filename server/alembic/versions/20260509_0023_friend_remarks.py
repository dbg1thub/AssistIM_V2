"""Add per-user friend remarks.

Revision ID: 20260509_0023
Revises: 20260505_0022
Create Date: 2026-05-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260509_0023"
down_revision = "20260505_0022"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    return any(column["name"] == column_name for column in sa.inspect(bind).get_columns(table_name))


def upgrade() -> None:
    if not _has_column("friends", "remark"):
        op.add_column("friends", sa.Column("remark", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    if _has_column("friends", "remark"):
        op.drop_column("friends", "remark")
