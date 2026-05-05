"""Add email verification for registration."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260505_0020"
down_revision = "20260505_0019"
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
    if "users" in _table_names(bind):
        _add_column_if_missing(
            "users",
            sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_lower ON users (lower(email)) WHERE email IS NOT NULL")

    if "email_verification_codes" not in _table_names(bind):
        op.create_table(
            "email_verification_codes",
            sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("purpose", sa.String(length=32), nullable=False),
            sa.Column("code_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("request_ip", sa.String(length=64), nullable=False, server_default=""),
            sa.PrimaryKeyConstraint("id"),
        )
    existing_indexes = _index_names(bind, "email_verification_codes") if "email_verification_codes" in _table_names(bind) else set()
    if "idx_email_verification_email_purpose" not in existing_indexes:
        op.create_index(
            "idx_email_verification_email_purpose",
            "email_verification_codes",
            ["email", "purpose"],
            unique=False,
        )
    if "idx_email_verification_expires_at" not in existing_indexes:
        op.create_index(
            "idx_email_verification_expires_at",
            "email_verification_codes",
            ["expires_at"],
            unique=False,
        )


def downgrade() -> None:
    return None
