"""add user session events table

Revision ID: 20260403_0008
Revises: 20260403_0007
Create Date: 2026-04-03 23:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260403_0008"
down_revision = "20260403_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_session_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("event_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_user_session_event_seq", "user_session_events", ["session_id", "user_id", "event_seq"], unique=True)
    op.create_index("idx_user_session_events_session_id", "user_session_events", ["session_id"], unique=False)
    op.create_index("idx_user_session_events_user_id", "user_session_events", ["user_id"], unique=False)
    op.create_index("idx_user_session_events_type", "user_session_events", ["type"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_user_session_events_type", table_name="user_session_events")
    op.drop_index("idx_user_session_events_user_id", table_name="user_session_events")
    op.drop_index("idx_user_session_events_session_id", table_name="user_session_events")
    op.drop_index("uq_user_session_event_seq", table_name="user_session_events")
    op.drop_table("user_session_events")
