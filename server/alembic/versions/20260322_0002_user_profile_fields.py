"""Add extended user profile fields."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260322_0002"
down_revision = "20260316_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("birthday", sa.Date(), nullable=True))
    op.add_column("users", sa.Column("region", sa.String(length=128), nullable=True))
    op.add_column("users", sa.Column("signature", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("gender", sa.String(length=32), nullable=True))
    op.create_index("idx_users_email", "users", ["email"], unique=False)
    op.create_index("idx_users_phone", "users", ["phone"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_users_phone", table_name="users")
    op.drop_index("idx_users_email", table_name="users")
    op.drop_column("users", "gender")
    op.drop_column("users", "signature")
    op.drop_column("users", "region")
    op.drop_column("users", "birthday")
    op.drop_column("users", "phone")
    op.drop_column("users", "email")
