"""Schema compatibility helpers for environments without Alembic upgrades applied."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine


USER_PROFILE_COLUMN_DDL: dict[str, str] = {
    "email": "VARCHAR(255)",
    "phone": "VARCHAR(32)",
    "birthday": "DATE",
    "region": "VARCHAR(128)",
    "signature": "TEXT",
    "gender": "VARCHAR(32)",
}

USER_PROFILE_INDEX_DDL: dict[str, str] = {
    "idx_users_email": "CREATE INDEX IF NOT EXISTS idx_users_email ON users (email)",
    "idx_users_phone": "CREATE INDEX IF NOT EXISTS idx_users_phone ON users (phone)",
}

MESSAGE_COLUMN_DDL: dict[str, str] = {
    "session_seq": "INTEGER NOT NULL DEFAULT 0",
    "extra_json": "TEXT NOT NULL DEFAULT '{}'",
}

SESSION_COLUMN_DDL: dict[str, str] = {
    "last_message_seq": "INTEGER NOT NULL DEFAULT 0",
    "last_event_seq": "INTEGER NOT NULL DEFAULT 0",
}

SESSION_MEMBER_COLUMN_DDL: dict[str, str] = {
    "last_read_seq": "INTEGER NOT NULL DEFAULT 0",
    "last_read_message_id": "VARCHAR(36)",
    "last_read_at": "TIMESTAMP",
}

FILE_COLUMN_DDL: dict[str, str] = {
    "storage_provider": "VARCHAR(32) NOT NULL DEFAULT 'local'",
    "storage_key": "VARCHAR(512) NOT NULL DEFAULT ''",
    "size_bytes": "INTEGER NOT NULL DEFAULT 0",
    "checksum_sha256": "VARCHAR(64) NOT NULL DEFAULT ''",
}

CHAT_INDEX_DDL: dict[str, str] = {
    "idx_messages_session_seq": "CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_session_seq ON messages (session_id, session_seq)",
}

FILE_INDEX_DDL: dict[str, str] = {
    "idx_files_storage_provider_key": "CREATE UNIQUE INDEX IF NOT EXISTS idx_files_storage_provider_key ON files (storage_provider, storage_key)",
}


def _get_table_names(bind: Engine | Connection) -> set[str]:
    return set(inspect(bind).get_table_names())


def _get_column_names(bind: Engine | Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(bind).get_columns(table_name)}


def _get_index_names(bind: Engine | Connection, table_name: str) -> set[str]:
    return {index["name"] for index in inspect(bind).get_indexes(table_name)}


def _ensure_columns(connection: Connection, table_name: str, column_ddl: dict[str, str], applied: list[str]) -> None:
    if table_name not in _get_table_names(connection):
        return

    columns = _get_column_names(connection, table_name)
    for column_name, ddl in column_ddl.items():
        if column_name in columns:
            continue
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))
        applied.append(f"{table_name}.{column_name}")
        columns.add(column_name)


def _ensure_indexes(connection: Connection, table_name: str, index_ddl: dict[str, str], applied: list[str]) -> None:
    if table_name not in _get_table_names(connection):
        return

    indexes = _get_index_names(connection, table_name)
    for index_name, ddl in index_ddl.items():
        if index_name in indexes:
            continue
        connection.execute(text(ddl))
        applied.append(index_name)
        indexes.add(index_name)


def _backfill_message_session_seq(connection: Connection, applied: list[str]) -> None:
    if "messages" not in _get_table_names(connection):
        return

    pending_count = connection.execute(
        text("SELECT COUNT(*) FROM messages WHERE COALESCE(session_seq, 0) = 0")
    ).scalar_one()
    if int(pending_count or 0) == 0:
        return

    rows = connection.execute(
        text(
            """
            SELECT id, session_id
            FROM messages
            ORDER BY session_id ASC, created_at ASC, id ASC
            """
        )
    ).mappings()

    current_session_id = None
    session_seq = 0
    touched = False
    for row in rows:
        if row["session_id"] != current_session_id:
            current_session_id = row["session_id"]
            session_seq = 1
        else:
            session_seq += 1

        connection.execute(
            text("UPDATE messages SET session_seq = :session_seq WHERE id = :message_id"),
            {"session_seq": session_seq, "message_id": row["id"]},
        )
        touched = True

    if touched:
        applied.append("messages.session_seq.backfill")


def _backfill_session_last_message_seq(connection: Connection, applied: list[str]) -> None:
    table_names = _get_table_names(connection)
    if "sessions" not in table_names or "messages" not in table_names:
        return

    pending_count = connection.execute(
        text(
            """
            SELECT COUNT(*)
            FROM sessions
            WHERE COALESCE(last_message_seq, 0) <> COALESCE(
                (
                    SELECT MAX(m.session_seq)
                    FROM messages AS m
                    WHERE m.session_id = sessions.id
                ),
                0
            )
            """
        )
    ).scalar_one()
    if int(pending_count or 0) == 0:
        return

    connection.execute(
        text(
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
    applied.append("sessions.last_message_seq.backfill")


def _backfill_session_last_event_seq(connection: Connection, applied: list[str]) -> None:
    table_names = _get_table_names(connection)
    if "sessions" not in table_names or "session_events" not in table_names:
        return

    pending_count = connection.execute(
        text(
            """
            SELECT COUNT(*)
            FROM sessions
            WHERE COALESCE(last_event_seq, 0) <> COALESCE(
                (
                    SELECT MAX(se.event_seq)
                    FROM session_events AS se
                    WHERE se.session_id = sessions.id
                ),
                0
            )
            """
        )
    ).scalar_one()
    if int(pending_count or 0) == 0:
        return

    connection.execute(
        text(
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
    applied.append("sessions.last_event_seq.backfill")


def _backfill_group_chat_membership(connection: Connection, applied: list[str]) -> None:
    table_names = _get_table_names(connection)
    if {"groups", "group_members", "session_members"} - table_names:
        return

    missing_session_members = connection.execute(
        text(
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
        connection.execute(
            text(
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
        applied.append("session_members.group_members.backfill")

    missing_group_members = connection.execute(
        text(
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
        connection.execute(
            text(
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
        applied.append("group_members.session_members.backfill")

    owner_role_mismatch = connection.execute(
        text(
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
        connection.execute(
            text(
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
        applied.append("group_members.owner_role.normalize")

    extra_owner_roles = connection.execute(
        text(
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
        connection.execute(
            text(
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
        applied.append("group_members.owner_role.cleanup")


def _backfill_session_member_read_state(connection: Connection, applied: list[str]) -> None:
    table_names = _get_table_names(connection)
    if "session_members" not in table_names or "messages" not in table_names:
        return

    connection.execute(text("UPDATE session_members SET last_read_seq = COALESCE(last_read_seq, 0)"))

    if "message_reads" not in table_names:
        return

    rows = connection.execute(
        text(
            """
            SELECT m.session_id, mr.user_id, m.id AS message_id, m.session_seq, mr.read_at
            FROM message_reads AS mr
            JOIN messages AS m ON m.id = mr.message_id
            ORDER BY m.session_id ASC, mr.user_id ASC, m.session_seq DESC, mr.read_at DESC, m.id DESC
            """
        )
    ).mappings()

    seen_pairs: set[tuple[str, str]] = set()
    touched = False
    for row in rows:
        pair = (row["session_id"], row["user_id"])
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        result = connection.execute(
            text(
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
        if int(result.rowcount or 0) > 0:
            touched = True

    if touched:
        applied.append("session_members.read_state.backfill")



def _backfill_file_storage_metadata(connection: Connection, applied: list[str]) -> None:
    table_names = _get_table_names(connection)
    if "files" not in table_names:
        return

    pending = connection.execute(
        text(
            """
            SELECT COUNT(*)
            FROM files
            WHERE COALESCE(storage_provider, '') = ''
               OR COALESCE(storage_key, '') = ''
            """
        )
    ).scalar_one()
    if int(pending or 0) == 0:
        return

    rows = connection.execute(
        text(
            """
            SELECT id, file_url
            FROM files
            WHERE COALESCE(storage_provider, '') = ''
               OR COALESCE(storage_key, '') = ''
            """
        )
    ).mappings()

    touched = False
    for row in rows:
        file_url = str(row["file_url"] or "")
        storage_key = file_url.removeprefix("/uploads/").lstrip("/")
        connection.execute(
            text(
                """
                UPDATE files
                SET storage_provider = 'local',
                    storage_key = :storage_key
                WHERE id = :file_id
                """
            ),
            {"storage_key": storage_key, "file_id": row["id"]},
        )
        touched = True

    if touched:
        applied.append("files.storage_metadata.backfill")


def ensure_schema_compatibility(engine: Engine) -> list[str]:
    """Apply lightweight idempotent schema fixes for known legacy drift."""
    applied: list[str] = []

    with engine.begin() as connection:
        _ensure_columns(connection, "users", USER_PROFILE_COLUMN_DDL, applied)
        _ensure_indexes(connection, "users", USER_PROFILE_INDEX_DDL, applied)

        _ensure_columns(connection, "messages", MESSAGE_COLUMN_DDL, applied)
        _ensure_columns(connection, "sessions", SESSION_COLUMN_DDL, applied)
        _ensure_columns(connection, "session_members", SESSION_MEMBER_COLUMN_DDL, applied)
        _ensure_columns(connection, "files", FILE_COLUMN_DDL, applied)

        _backfill_message_session_seq(connection, applied)
        _backfill_session_last_message_seq(connection, applied)
        _backfill_session_last_event_seq(connection, applied)
        _backfill_group_chat_membership(connection, applied)
        _backfill_session_member_read_state(connection, applied)
        _backfill_file_storage_metadata(connection, applied)

        _ensure_indexes(connection, "messages", CHAT_INDEX_DDL, applied)
        _ensure_indexes(connection, "files", FILE_INDEX_DDL, applied)

    return applied


def describe_schema_compatibility(applied: Iterable[str]) -> str:
    items = list(applied)
    if not items:
        return "Schema compatibility already up to date."
    return "Applied schema compatibility updates: " + ", ".join(items)




