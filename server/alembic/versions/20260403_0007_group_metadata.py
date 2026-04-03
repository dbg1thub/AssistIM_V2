"""Add editable group metadata fields."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260403_0007"
down_revision = "20260329_0006"
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
    _add_column_if_missing("groups", sa.Column("announcement", sa.Text(), nullable=False, server_default=""))
    _add_column_if_missing("group_members", sa.Column("group_nickname", sa.String(length=64), nullable=False, server_default=""))
    _add_column_if_missing("group_members", sa.Column("note", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    return None
