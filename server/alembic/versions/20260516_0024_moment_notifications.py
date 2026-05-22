"""Add moment interaction notifications.

Revision ID: 20260516_0024
Revises: 20260509_0023
Create Date: 2026-05-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260516_0024"
down_revision = "20260509_0023"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _index_names(bind, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if "moment_notifications" not in _table_names(bind):
        op.create_table(
            "moment_notifications",
            sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("recipient_user_id", sa.Uuid(as_uuid=False), nullable=False),
            sa.Column("actor_user_id", sa.Uuid(as_uuid=False), nullable=False),
            sa.Column("moment_id", sa.Uuid(as_uuid=False), nullable=False),
            sa.Column("comment_id", sa.Uuid(as_uuid=False), nullable=False),
            sa.Column("notification_type", sa.String(length=32), nullable=False),
            sa.Column("content_preview", sa.Text(), nullable=False, server_default=""),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "recipient_user_id",
                "notification_type",
                "moment_id",
                "comment_id",
                "actor_user_id",
                name="uq_moment_notification_comment",
            ),
        )

    existing_indexes = _index_names(bind, "moment_notifications")
    if "idx_moment_notifications_recipient_read" not in existing_indexes:
        op.create_index(
            "idx_moment_notifications_recipient_read",
            "moment_notifications",
            ["recipient_user_id", "read_at"],
            unique=False,
        )
    if "idx_moment_notifications_moment_id" not in existing_indexes:
        op.create_index(
            "idx_moment_notifications_moment_id",
            "moment_notifications",
            ["moment_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "moment_notifications" not in _table_names(bind):
        return
    existing_indexes = _index_names(bind, "moment_notifications")
    if "idx_moment_notifications_moment_id" in existing_indexes:
        op.drop_index("idx_moment_notifications_moment_id", table_name="moment_notifications")
    if "idx_moment_notifications_recipient_read" in existing_indexes:
        op.drop_index("idx_moment_notifications_recipient_read", table_name="moment_notifications")
    op.drop_table("moment_notifications")
