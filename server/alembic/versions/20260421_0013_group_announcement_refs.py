"""add missing group announcement reference columns

Revision ID: 20260421_0013
Revises: 20260413_0012
Create Date: 2026-04-21 21:40:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260421_0013"
down_revision = "20260413_0012"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    bind = op.get_bind()
    if table_name not in _table_names(bind):
        return
    if column.name in _column_names(bind, table_name):
        return
    op.add_column(table_name, column)


def upgrade() -> None:
    _add_column_if_missing(
        "groups",
        sa.Column("announcement_message_id", sa.Uuid(as_uuid=False), sa.ForeignKey("messages.id"), nullable=True),
    )
    _add_column_if_missing(
        "groups",
        sa.Column("announcement_author_id", sa.Uuid(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
    )
    _add_column_if_missing(
        "groups",
        sa.Column("announcement_published_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    return None
