"""Add moment privacy controls."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260505_0022"
down_revision = "20260505_0021"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _index_names(bind, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    bind = op.get_bind()
    if table_name not in _table_names(bind):
        return
    if column.name in _column_names(bind, table_name):
        return
    op.add_column(table_name, column)


def upgrade() -> None:
    bind = op.get_bind()
    _add_column_if_missing(
        "moments",
        sa.Column("visibility_scope", sa.String(length=16), nullable=False, server_default="public"),
    )
    _add_column_if_missing(
        "moments",
        sa.Column("visibility_user_ids_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
    )

    if "moment_privacy_settings" not in _table_names(bind):
        op.create_table(
            "moment_privacy_settings",
            sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("user_id", sa.Uuid(as_uuid=False), nullable=False),
            sa.Column("hide_my_moments_user_ids_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("hide_their_moments_user_ids_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("visible_time_scope", sa.String(length=16), nullable=False, server_default="all"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", name="uq_moment_privacy_settings_user_id"),
        )

    existing_indexes = (
        _index_names(bind, "moment_privacy_settings") if "moment_privacy_settings" in _table_names(bind) else set()
    )
    if "idx_moment_privacy_settings_user_id" not in existing_indexes:
        op.create_index(
            "idx_moment_privacy_settings_user_id",
            "moment_privacy_settings",
            ["user_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "moment_privacy_settings" not in _table_names(bind):
        return
    existing_indexes = _index_names(bind, "moment_privacy_settings")
    if "idx_moment_privacy_settings_user_id" in existing_indexes:
        op.drop_index("idx_moment_privacy_settings_user_id", table_name="moment_privacy_settings")
    op.drop_table("moment_privacy_settings")
