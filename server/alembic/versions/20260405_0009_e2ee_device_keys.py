"""add e2ee device key tables

Revision ID: 20260405_0009
Revises: 20260403_0008
Create Date: 2026-04-05 23:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260405_0009"
down_revision = "20260403_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_devices",
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("identity_key_public", sa.Text(), nullable=False),
        sa.Column("signing_key_public", sa.Text(), nullable=False),
        sa.Column("device_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("device_id"),
    )
    op.create_index("idx_user_devices_user_id", "user_devices", ["user_id"], unique=False)
    op.create_index("idx_user_devices_is_active", "user_devices", ["is_active"], unique=False)

    op.create_table(
        "user_signed_prekeys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["user_devices.device_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "key_id", name="uq_user_signed_prekeys_device_key"),
    )
    op.create_index("idx_user_signed_prekeys_device_id", "user_signed_prekeys", ["device_id"], unique=False)
    op.create_index("idx_user_signed_prekeys_is_active", "user_signed_prekeys", ["is_active"], unique=False)

    op.create_table(
        "user_prekeys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("prekey_id", sa.Integer(), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("is_consumed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["user_devices.device_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "prekey_id", name="uq_user_prekeys_device_key"),
    )
    op.create_index("idx_user_prekeys_device_id", "user_prekeys", ["device_id"], unique=False)
    op.create_index("idx_user_prekeys_claim_state", "user_prekeys", ["device_id", "is_consumed"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_user_prekeys_claim_state", table_name="user_prekeys")
    op.drop_index("idx_user_prekeys_device_id", table_name="user_prekeys")
    op.drop_table("user_prekeys")

    op.drop_index("idx_user_signed_prekeys_is_active", table_name="user_signed_prekeys")
    op.drop_index("idx_user_signed_prekeys_device_id", table_name="user_signed_prekeys")
    op.drop_table("user_signed_prekeys")

    op.drop_index("idx_user_devices_is_active", table_name="user_devices")
    op.drop_index("idx_user_devices_user_id", table_name="user_devices")
    op.drop_table("user_devices")
