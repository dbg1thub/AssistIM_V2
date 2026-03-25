"""Add auth session version to users."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260325_0003"
down_revision = "20260322_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auth_session_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("users", "auth_session_version", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "auth_session_version")
