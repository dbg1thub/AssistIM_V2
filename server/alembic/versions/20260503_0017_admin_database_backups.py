"""add admin database backup records

Revision ID: 20260503_0017
Revises: 20260503_0016
Create Date: 2026-05-03 05:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260503_0017"
down_revision = "20260503_0016"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    if "admin_database_backups" in _table_names(bind):
        return

    op.create_table(
        "admin_database_backups",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_username", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("database_dialect", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("backup_format", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("storage_key", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("file_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("file_path", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_admin_database_backups_created_by_user_id",
        "admin_database_backups",
        ["created_by_user_id"],
    )
    op.create_index("idx_admin_database_backups_status", "admin_database_backups", ["status"])
    op.create_index("idx_admin_database_backups_created_at", "admin_database_backups", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if "admin_database_backups" not in _table_names(bind):
        return

    op.drop_index("idx_admin_database_backups_created_at", table_name="admin_database_backups")
    op.drop_index("idx_admin_database_backups_status", table_name="admin_database_backups")
    op.drop_index("idx_admin_database_backups_created_by_user_id", table_name="admin_database_backups")
    op.drop_table("admin_database_backups")
