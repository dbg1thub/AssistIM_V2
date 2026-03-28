"""Add the current chat runtime schema managed by the service layer."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260328_0004"
down_revision = "20260325_0003"
branch_labels = None
depends_on = None

UUID = sa.Uuid(as_uuid=False)


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _index_names(bind, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    bind = op.get_bind()
    if table_name not in _table_names(bind):
        return
    if column.name in _column_names(bind, table_name):
        return
    op.add_column(table_name, column)


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str], *, unique: bool = False) -> None:
    bind = op.get_bind()
    if table_name not in _table_names(bind):
        return
    if index_name in _index_names(bind, table_name):
        return
    op.create_index(index_name, table_name, columns, unique=unique)



def _backfill_message_session_seq(bind) -> None:
    table_names = _table_names(bind)
    if "messages" not in table_names or "session_seq" not in _column_names(bind, "messages"):
        return

    pending_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM messages WHERE COALESCE(session_seq, 0) = 0")
    ).scalar_one()
    if int(pending_count or 0) == 0:
        return

    rows = bind.execute(
        sa.text(
            """
            SELECT id, session_id
            FROM messages
            ORDER BY session_id ASC, created_at ASC, id ASC
            """
        )
    ).mappings()

    current_session_id = None
    session_seq = 0
    for row in rows:
        if row["session_id"] != current_session_id:
            current_session_id = row["session_id"]
            session_seq = 1
        else:
            session_seq += 1

        bind.execute(
            sa.text("UPDATE messages SET session_seq = :session_seq WHERE id = :message_id"),
            {"session_seq": session_seq, "message_id": row["id"]},
        )



def _backfill_session_last_message_seq(bind) -> None:
    table_names = _table_names(bind)
    if {"sessions", "messages"} - table_names:
        return
    session_columns = _column_names(bind, "sessions")
    message_columns = _column_names(bind, "messages")
    if "last_message_seq" not in session_columns or "session_seq" not in message_columns:
        return

    bind.execute(
        sa.text(
            """
            UPDATE sessions
            SET last_message_seq = COALESCE(
                (
                    SELECT MAX(m.session_seq)
                    FROM messages AS m
                    WHERE m.session_id = sessions.id
                ),
                0
            )
            """
        )
    )



def _backfill_session_last_event_seq(bind) -> None:
    table_names = _table_names(bind)
    if {"sessions", "session_events"} - table_names:
        return
    if "last_event_seq" not in _column_names(bind, "sessions"):
        return

    bind.execute(
        sa.text(
            """
            UPDATE sessions
            SET last_event_seq = COALESCE(
                (
                    SELECT MAX(se.event_seq)
                    FROM session_events AS se
                    WHERE se.session_id = sessions.id
                ),
                0
            )
            """
        )
    )



def _backfill_group_chat_membership(bind) -> None:
    table_names = _table_names(bind)
    if {"groups", "group_members", "session_members"} - table_names:
        return

    missing_session_members = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM group_members AS gm
            JOIN groups AS g ON g.id = gm.group_id
            LEFT JOIN session_members AS sm
              ON sm.session_id = g.session_id
             AND sm.user_id = gm.user_id
            WHERE sm.session_id IS NULL
            """
        )
    ).scalar_one()
    if int(missing_session_members or 0) > 0:
        bind.execute(
            sa.text(
                """
                INSERT INTO session_members (
                    session_id,
                    user_id,
                    joined_at,
                    last_read_seq,
                    last_read_message_id,
                    last_read_at
                )
                SELECT
                    g.session_id,
                    gm.user_id,
                    COALESCE(gm.joined_at, CURRENT_TIMESTAMP),
                    0,
                    NULL,
                    NULL
                FROM group_members AS gm
                JOIN groups AS g ON g.id = gm.group_id
                LEFT JOIN session_members AS sm
                  ON sm.session_id = g.session_id
                 AND sm.user_id = gm.user_id
                WHERE sm.session_id IS NULL
                """
            )
        )

    missing_group_members = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM groups AS g
            JOIN session_members AS sm ON sm.session_id = g.session_id
            LEFT JOIN group_members AS gm
              ON gm.group_id = g.id
             AND gm.user_id = sm.user_id
            WHERE gm.group_id IS NULL
            """
        )
    ).scalar_one()
    if int(missing_group_members or 0) > 0:
        bind.execute(
            sa.text(
                """
                INSERT INTO group_members (group_id, user_id, role, joined_at)
                SELECT
                    g.id,
                    sm.user_id,
                    CASE WHEN sm.user_id = g.owner_id THEN 'owner' ELSE 'member' END,
                    COALESCE(sm.joined_at, CURRENT_TIMESTAMP)
                FROM groups AS g
                JOIN session_members AS sm ON sm.session_id = g.session_id
                LEFT JOIN group_members AS gm
                  ON gm.group_id = g.id
                 AND gm.user_id = sm.user_id
                WHERE gm.group_id IS NULL
                """
            )
        )

    owner_role_mismatch = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM groups AS g
            JOIN group_members AS gm
              ON gm.group_id = g.id
             AND gm.user_id = g.owner_id
            WHERE COALESCE(gm.role, 'member') <> 'owner'
            """
        )
    ).scalar_one()
    if int(owner_role_mismatch or 0) > 0:
        bind.execute(
            sa.text(
                """
                UPDATE group_members
                SET role = 'owner'
                WHERE EXISTS (
                    SELECT 1
                    FROM groups AS g
                    WHERE g.id = group_members.group_id
                      AND g.owner_id = group_members.user_id
                )
                """
            )
        )

    extra_owner_roles = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM group_members AS gm
            JOIN groups AS g ON g.id = gm.group_id
            WHERE gm.user_id <> g.owner_id
              AND COALESCE(gm.role, 'member') = 'owner'
            """
        )
    ).scalar_one()
    if int(extra_owner_roles or 0) > 0:
        bind.execute(
            sa.text(
                """
                UPDATE group_members
                SET role = 'member'
                WHERE EXISTS (
                    SELECT 1
                    FROM groups AS g
                    WHERE g.id = group_members.group_id
                      AND group_members.user_id <> g.owner_id
                )
                  AND COALESCE(role, 'member') = 'owner'
                """
            )
        )



def _backfill_session_member_read_state(bind) -> None:
    table_names = _table_names(bind)
    if {"session_members", "messages"} - table_names:
        return
    member_columns = _column_names(bind, "session_members")
    if {"last_read_seq", "last_read_message_id", "last_read_at"} - member_columns:
        return

    bind.execute(sa.text("UPDATE session_members SET last_read_seq = COALESCE(last_read_seq, 0)"))

    if "message_reads" not in table_names:
        return

    rows = bind.execute(
        sa.text(
            """
            SELECT m.session_id, mr.user_id, m.id AS message_id, m.session_seq, mr.read_at
            FROM message_reads AS mr
            JOIN messages AS m ON m.id = mr.message_id
            ORDER BY m.session_id ASC, mr.user_id ASC, m.session_seq DESC, mr.read_at DESC, m.id DESC
            """
        )
    ).mappings()

    seen_pairs: set[tuple[str, str]] = set()
    for row in rows:
        pair = (row["session_id"], row["user_id"])
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        bind.execute(
            sa.text(
                """
                UPDATE session_members
                SET last_read_seq = :last_read_seq,
                    last_read_message_id = :last_read_message_id,
                    last_read_at = :last_read_at
                WHERE session_id = :session_id
                  AND user_id = :user_id
                  AND COALESCE(last_read_seq, 0) = 0
                  AND last_read_message_id IS NULL
                """
            ),
            {
                "last_read_seq": int(row["session_seq"] or 0),
                "last_read_message_id": row["message_id"],
                "last_read_at": row["read_at"],
                "session_id": row["session_id"],
                "user_id": row["user_id"],
            },
        )



def _backfill_file_storage_metadata(bind) -> None:
    table_names = _table_names(bind)
    if "files" not in table_names:
        return
    file_columns = _column_names(bind, "files")
    if {"storage_provider", "storage_key"} - file_columns:
        return

    rows = bind.execute(
        sa.text(
            """
            SELECT id, file_url
            FROM files
            WHERE COALESCE(storage_provider, '') = ''
               OR COALESCE(storage_key, '') = ''
            """
        )
    ).mappings()

    for row in rows:
        file_url = str(row["file_url"] or "")
        storage_key = file_url
        if storage_key.startswith("/uploads/"):
            storage_key = storage_key[len("/uploads/"):]
        storage_key = storage_key.lstrip("/")
        bind.execute(
            sa.text(
                """
                UPDATE files
                SET storage_provider = 'local',
                    storage_key = :storage_key
                WHERE id = :file_id
                """
            ),
            {"storage_key": storage_key, "file_id": row["id"]},
        )



def upgrade() -> None:
    bind = op.get_bind()

    _add_column_if_missing(
        "messages",
        sa.Column("session_seq", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "messages",
        sa.Column("extra_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
    )
    _add_column_if_missing(
        "sessions",
        sa.Column("last_message_seq", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "sessions",
        sa.Column("last_event_seq", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "session_members",
        sa.Column("last_read_seq", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "session_members",
        sa.Column("last_read_message_id", UUID, nullable=True),
    )
    _add_column_if_missing(
        "session_members",
        sa.Column("last_read_at", sa.DateTime(), nullable=True),
    )
    _add_column_if_missing(
        "files",
        sa.Column("storage_provider", sa.String(length=32), nullable=False, server_default=sa.text("'local'")),
    )
    _add_column_if_missing(
        "files",
        sa.Column("storage_key", sa.String(length=512), nullable=False, server_default=sa.text("''")),
    )
    _add_column_if_missing(
        "files",
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "files",
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False, server_default=sa.text("''")),
    )

    if "session_events" not in _table_names(bind):
        op.create_table(
            "session_events",
            sa.Column("session_id", UUID, nullable=False),
            sa.Column("event_seq", sa.Integer(), nullable=False),
            sa.Column("type", sa.String(), nullable=False),
            sa.Column("message_id", UUID, nullable=True),
            sa.Column("actor_user_id", UUID, nullable=True),
            sa.Column("payload", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("id", UUID, nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("session_id", "event_seq", name="uq_session_event_seq"),
        )

    _backfill_message_session_seq(bind)
    _backfill_session_last_message_seq(bind)
    _backfill_session_last_event_seq(bind)
    _backfill_group_chat_membership(bind)
    _backfill_session_member_read_state(bind)
    _backfill_file_storage_metadata(bind)

    _create_index_if_missing("messages", "idx_messages_session_seq", ["session_id", "session_seq"], unique=True)
    _create_index_if_missing("files", "idx_files_storage_provider_key", ["storage_provider", "storage_key"], unique=True)
    _create_index_if_missing("session_events", "idx_session_events_session_id", ["session_id"])
    _create_index_if_missing("session_events", "idx_session_events_type", ["type"])



def downgrade() -> None:
    # This migration formalizes schema that was previously created by runtime compatibility.
    # Keep downgrade as a no-op to avoid destructive column drops on existing databases.
    return None