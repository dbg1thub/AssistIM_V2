"""Add media fields for moments."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260505_0019"
down_revision = "20260503_0018"
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
        "moments",
        sa.Column("media_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
    )
    _add_column_if_missing(
        "moment_comments",
        sa.Column("image_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    return None
