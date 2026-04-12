"""add shared rate limit hit store

Revision ID: 20260413_0012
Revises: 20260413_0011
Create Date: 2026-04-13 00:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260413_0012"
down_revision = "20260413_0011"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _index_names(bind, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if "rate_limit_hits" not in _table_names(bind):
        op.create_table(
            "rate_limit_hits",
            sa.Column("key", sa.String(length=255), nullable=False),
            sa.Column("hit_at", sa.Float(), nullable=False),
        )
    if "idx_rate_limit_hits_key_hit_at" not in _index_names(bind, "rate_limit_hits"):
        op.create_index(
            "idx_rate_limit_hits_key_hit_at",
            "rate_limit_hits",
            ["key", "hit_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "rate_limit_hits" not in _table_names(bind):
        return
    if "idx_rate_limit_hits_key_hit_at" in _index_names(bind, "rate_limit_hits"):
        op.drop_index("idx_rate_limit_hits_key_hit_at", table_name="rate_limit_hits")
    op.drop_table("rate_limit_hits")
