"""Add user block relationships."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260505_0021"
down_revision = "20260505_0020"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _index_names(bind, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if "user_blocks" not in _table_names(bind):
        op.create_table(
            "user_blocks",
            sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("user_id", sa.Uuid(as_uuid=False), nullable=False),
            sa.Column("blocked_user_id", sa.Uuid(as_uuid=False), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["blocked_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "blocked_user_id", name="uq_user_block_pair"),
        )

    existing_indexes = _index_names(bind, "user_blocks") if "user_blocks" in _table_names(bind) else set()
    if "idx_user_blocks_user_id" not in existing_indexes:
        op.create_index("idx_user_blocks_user_id", "user_blocks", ["user_id"], unique=False)
    if "idx_user_blocks_blocked_user_id" not in existing_indexes:
        op.create_index("idx_user_blocks_blocked_user_id", "user_blocks", ["blocked_user_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if "user_blocks" not in _table_names(bind):
        return
    existing_indexes = _index_names(bind, "user_blocks")
    if "idx_user_blocks_blocked_user_id" in existing_indexes:
        op.drop_index("idx_user_blocks_blocked_user_id", table_name="user_blocks")
    if "idx_user_blocks_user_id" in existing_indexes:
        op.drop_index("idx_user_blocks_user_id", table_name="user_blocks")
    op.drop_table("user_blocks")
