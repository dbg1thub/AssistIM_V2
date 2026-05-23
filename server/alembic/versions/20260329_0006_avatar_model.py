"""Formalize avatar state for users and groups."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.core.config import get_settings
from app.media.generated_avatars import build_generated_user_avatar


revision = "20260329_0006"
down_revision = "20260329_0005"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    bind = op.get_bind()
    if table_name not in _table_names(bind):
        return
    if column.name in _column_names(bind, table_name):
        return
    op.add_column(table_name, column)


def _backfill_user_avatar_state(bind) -> None:
    if "users" not in _table_names(bind):
        return
    if {"avatar_kind", "avatar_file_id", "avatar"} - _column_names(bind, "users"):
        return

    rows = bind.execute(
        sa.text(
            """
            SELECT id, username, nickname, avatar, avatar_kind, avatar_file_id
            FROM users
            ORDER BY created_at ASC, id ASC
            """
        )
    ).mappings().all()

    for row in rows:
        avatar_value = str(row["avatar"] or "").strip()
        avatar_kind = str(row["avatar_kind"] or "").strip().lower()
        avatar_file_id = str(row["avatar_file_id"] or "").strip() or None

        if avatar_kind == "custom" and avatar_value:
            resolved_kind = "custom"
            resolved_file_id = avatar_file_id
            resolved_avatar = avatar_value
        else:
            resolved_kind = "generated"
            resolved_file_id = None
            resolved_avatar = build_generated_user_avatar(
                get_settings(),
                user_id=row["id"],
                username=row["username"],
                nickname=row["nickname"],
            )

        if (
            avatar_kind != resolved_kind
            or str(avatar_file_id or "") != str(resolved_file_id or "")
            or avatar_value != str(resolved_avatar or "")
        ):
            bind.execute(
                sa.text(
                    """
                    UPDATE users
                    SET avatar_kind = :avatar_kind,
                        avatar_file_id = :avatar_file_id,
                        avatar = :avatar
                    WHERE id = :user_id
                    """
                ),
                {
                    "avatar_kind": resolved_kind,
                    "avatar_file_id": resolved_file_id,
                    "avatar": resolved_avatar,
                    "user_id": row["id"],
                },
            )


def _backfill_group_avatar_state(bind) -> None:
    if "groups" not in _table_names(bind):
        return
    if {"avatar_kind", "avatar_file_id", "avatar_version"} - _column_names(bind, "groups"):
        return

    bind.execute(
        sa.text(
            """
            UPDATE groups
            SET avatar_kind = COALESCE(NULLIF(TRIM(avatar_kind), ''), 'generated'),
                avatar_version = CASE
                    WHEN COALESCE(avatar_version, 0) > 0 THEN avatar_version
                    ELSE 1
                END
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()

    _add_column_if_missing("users", sa.Column("avatar_kind", sa.String(length=16), nullable=False, server_default="generated"))
    _add_column_if_missing("users", sa.Column("avatar_file_id", sa.String(length=36), nullable=True))

    _add_column_if_missing("groups", sa.Column("avatar_kind", sa.String(length=16), nullable=False, server_default="generated"))
    _add_column_if_missing("groups", sa.Column("avatar_file_id", sa.String(length=36), nullable=True))
    _add_column_if_missing("groups", sa.Column("avatar_version", sa.Integer(), nullable=False, server_default="1"))

    _backfill_user_avatar_state(bind)
    _backfill_group_avatar_state(bind)


def downgrade() -> None:
    return None
