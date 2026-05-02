"""add admin role and audit logs

Revision ID: 20260503_0015
Revises: 20260424_0014
Create Date: 2026-05-03 03:55:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260503_0015"
down_revision = "20260424_0014"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if "users" in _table_names(bind) and "role" not in _column_names(bind, "users"):
        op.add_column(
            "users",
            sa.Column("role", sa.String(length=32), nullable=False, server_default="user"),
        )

    if "admin_audit_logs" not in _table_names(bind):
        op.create_table(
            "admin_audit_logs",
            sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
            sa.Column("actor_user_id", sa.String(length=36), nullable=True),
            sa.Column("actor_username", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("action", sa.String(length=128), nullable=False),
            sa.Column("target_type", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("target_id", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("request_path", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("request_method", sa.String(length=16), nullable=False, server_default=""),
            sa.Column("client_ip", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("error_code", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_admin_audit_logs_actor_user_id", "admin_audit_logs", ["actor_user_id"])
        op.create_index("idx_admin_audit_logs_action", "admin_audit_logs", ["action"])
        op.create_index("idx_admin_audit_logs_created_at", "admin_audit_logs", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if "admin_audit_logs" in _table_names(bind):
        op.drop_index("idx_admin_audit_logs_created_at", table_name="admin_audit_logs")
        op.drop_index("idx_admin_audit_logs_action", table_name="admin_audit_logs")
        op.drop_index("idx_admin_audit_logs_actor_user_id", table_name="admin_audit_logs")
        op.drop_table("admin_audit_logs")
