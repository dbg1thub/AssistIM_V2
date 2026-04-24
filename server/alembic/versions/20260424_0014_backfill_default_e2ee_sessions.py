"""backfill default e2ee session modes

Revision ID: 20260424_0014
Revises: 20260421_0013
Create Date: 2026-04-24 13:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260424_0014"
down_revision = "20260421_0013"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if "sessions" not in _table_names(bind):
        return
    if "encryption_mode" not in _column_names(bind, "sessions"):
        return

    bind.execute(
        sa.text(
            """
            UPDATE sessions
            SET encryption_mode = 'e2ee_private'
            WHERE type = 'private'
              AND COALESCE(is_ai_session, FALSE) = FALSE
              AND COALESCE(NULLIF(TRIM(encryption_mode), ''), 'plain') = 'plain'
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE sessions
            SET encryption_mode = 'e2ee_group'
            WHERE type = 'group'
              AND COALESCE(is_ai_session, FALSE) = FALSE
              AND COALESCE(NULLIF(TRIM(encryption_mode), ''), 'plain') = 'plain'
            """
        )
    )


def downgrade() -> None:
    return None
