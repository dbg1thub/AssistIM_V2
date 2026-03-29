"""Formalize avatar state for users and groups."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.media.default_avatars import choose_seeded_default_avatar_key, default_avatar_key_from_url


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
    if {"avatar_kind", "avatar_default_key", "avatar_file_id", "avatar"} - _column_names(bind, "users"):
        return

    rows = bind.execute(
        sa.text(
            """
            SELECT id, username, gender, avatar, avatar_kind, avatar_default_key, avatar_file_id
            FROM users
            ORDER BY created_at ASC, id ASC
            """
        )
    ).mappings().all()

    for row in rows:
        avatar_value = str(row["avatar"] or "").strip()
        avatar_kind = str(row["avatar_kind"] or "").strip().lower()
        avatar_default_key = str(row["avatar_default_key"] or "").strip()
        avatar_file_id = str(row["avatar_file_id"] or "").strip() or None

        inferred_default_key = avatar_default_key or default_avatar_key_from_url(avatar_value)
        if inferred_default_key:
            resolved_kind = "default"
            resolved_default_key = inferred_default_key
            resolved_file_id = None
            resolved_avatar = avatar_value or f"/uploads/default_avatars/{inferred_default_key}"
        elif avatar_value:
            resolved_kind = "custom"
            resolved_default_key = avatar_default_key or None
            resolved_file_id = avatar_file_id
            resolved_avatar = avatar_value
        else:
            resolved_kind = "default"
            resolved_default_key = choose_seeded_default_avatar_key(
                str(row["id"] or "") or str(row["username"] or ""),
                gender=row["gender"],
            )
            resolved_file_id = None
            resolved_avatar = f"/uploads/default_avatars/{resolved_default_key}" if resolved_default_key else None

        if (
            avatar_kind != resolved_kind
            or avatar_default_key != str(resolved_default_key or "")
            or str(avatar_file_id or "") != str(resolved_file_id or "")
            or avatar_value != str(resolved_avatar or "")
        ):
            bind.execute(
                sa.text(
                    """
                    UPDATE users
                    SET avatar_kind = :avatar_kind,
                        avatar_default_key = :avatar_default_key,
                        avatar_file_id = :avatar_file_id,
                        avatar = :avatar
                    WHERE id = :user_id
                    """
                ),
                {
                    "avatar_kind": resolved_kind,
                    "avatar_default_key": resolved_default_key,
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

    _add_column_if_missing("users", sa.Column("avatar_kind", sa.String(length=16), nullable=False, server_default="default"))
    _add_column_if_missing("users", sa.Column("avatar_default_key", sa.String(length=128), nullable=True))
    _add_column_if_missing("users", sa.Column("avatar_file_id", sa.String(length=36), nullable=True))

    _add_column_if_missing("groups", sa.Column("avatar_kind", sa.String(length=16), nullable=False, server_default="generated"))
    _add_column_if_missing("groups", sa.Column("avatar_file_id", sa.String(length=36), nullable=True))
    _add_column_if_missing("groups", sa.Column("avatar_version", sa.Integer(), nullable=False, server_default="1"))

    _backfill_user_avatar_state(bind)
    _backfill_group_avatar_state(bind)


def downgrade() -> None:
    return None
