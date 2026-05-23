"""Switch user avatars to generated/custom semantics."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.core.config import get_settings
from app.media.generated_avatars import build_generated_user_avatar


revision = "20260524_0025"
down_revision = "20260516_0024"
branch_labels = None
depends_on = None


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if "users" not in set(sa.inspect(bind).get_table_names()):
        return

    columns = _column_names(bind, "users")
    if "avatar_kind" in columns:
        settings = get_settings()
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
            avatar_kind = str(row["avatar_kind"] or "").strip().lower()
            avatar_value = str(row["avatar"] or "").strip()
            avatar_file_id = str(row["avatar_file_id"] or "").strip() or None
            if avatar_kind == "custom" and avatar_value:
                resolved_kind = "custom"
                resolved_file_id = avatar_file_id
                resolved_avatar = avatar_value
            else:
                resolved_kind = "generated"
                resolved_file_id = None
                resolved_avatar = build_generated_user_avatar(
                    settings,
                    user_id=row["id"],
                    username=row["username"],
                    nickname=row["nickname"],
                )
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

    if "avatar_default_key" in columns:
        op.drop_column("users", "avatar_default_key")


def downgrade() -> None:
    return None
