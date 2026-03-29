"""Schema compatibility helpers for environments without Alembic upgrades applied."""

from __future__ import annotations

import json

from collections.abc import Iterable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from app.media.default_avatars import choose_seeded_default_avatar_key, default_avatar_key_from_url

USER_PROFILE_COLUMN_DDL: dict[str, str] = {
    "email": "VARCHAR(255)",
    "phone": "VARCHAR(32)",
    "birthday": "DATE",
    "region": "VARCHAR(128)",
    "signature": "TEXT",
    "gender": "VARCHAR(32)",
    "auth_session_version": "INTEGER NOT NULL DEFAULT 0",
}

USER_AVATAR_COLUMN_DDL: dict[str, str] = {
    "avatar_kind": "VARCHAR(16) NOT NULL DEFAULT 'default'",
    "avatar_default_key": "VARCHAR(128)",
    "avatar_file_id": "VARCHAR(36)",
}

USER_PROFILE_INDEX_DDL: dict[str, str] = {
    "idx_users_email": "CREATE INDEX IF NOT EXISTS idx_users_email ON users (email)",
    "idx_users_phone": "CREATE INDEX IF NOT EXISTS idx_users_phone ON users (phone)",
}

GROUP_AVATAR_COLUMN_DDL: dict[str, str] = {
    "avatar_kind": "VARCHAR(16) NOT NULL DEFAULT 'generated'",
    "avatar_file_id": "VARCHAR(36)",
    "avatar_version": "INTEGER NOT NULL DEFAULT 1",
}

MESSAGE_COLUMN_DDL: dict[str, str] = {
    "session_seq": "INTEGER NOT NULL DEFAULT 0",
    "extra_json": "TEXT NOT NULL DEFAULT '{}'",
}

SESSION_COLUMN_DDL: dict[str, str] = {
    "last_message_seq": "INTEGER NOT NULL DEFAULT 0",
    "last_event_seq": "INTEGER NOT NULL DEFAULT 0",
    "direct_key": "VARCHAR(255)",
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

SESSION_INDEX_DDL: dict[str, str] = {
    "idx_sessions_direct_key": "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_direct_key ON sessions (direct_key)",
}

FILE_INDEX_DDL: dict[str, str] = {
    "idx_files_storage_provider_key": "CREATE UNIQUE INDEX IF NOT EXISTS idx_files_storage_provider_key ON files (storage_provider, storage_key)",
}

SESSION_EVENT_INDEX_DDL: dict[str, str] = {
    "idx_session_events_session_id": "CREATE INDEX IF NOT EXISTS idx_session_events_session_id ON session_events (session_id)",
    "idx_session_events_type": "CREATE INDEX IF NOT EXISTS idx_session_events_type ON session_events (type)",
}


def _get_table_names(bind: Engine | Connection) -> set[str]:
    return set(inspect(bind).get_table_names())


def _get_column_names(bind: Engine | Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(bind).get_columns(table_name)}


def _get_index_names(bind: Engine | Connection, table_name: str) -> set[str]:
    return {index["name"] for index in inspect(bind).get_indexes(table_name)}


def _has_columns(bind: Engine | Connection, table_name: str, required_columns: Iterable[str]) -> bool:
    if table_name not in _get_table_names(bind):
        return False
    columns = _get_column_names(bind, table_name)
    return all(column_name in columns for column_name in required_columns)


def _has_indexes(bind: Engine | Connection, table_name: str, required_indexes: Iterable[str]) -> bool:
    if table_name not in _get_table_names(bind):
        return False
    indexes = _get_index_names(bind, table_name)
    return all(index_name in indexes for index_name in required_indexes)


RUNTIME_SCHEMA_ALEMBIC_REVISION = "20260329_0006"

def _parse_revision(revision: str) -> tuple[int, int] | None:
    candidate = str(revision or "").strip()
    if "_" not in candidate:
        return None
    date_part, seq_part = candidate.split("_", 1)
    if len(date_part) != 8 or len(seq_part) != 4 or not date_part.isdigit() or not seq_part.isdigit():
        return None
    return int(date_part), int(seq_part)


def _has_runtime_schema_migration(bind: Engine | Connection) -> bool:
    if "alembic_version" not in _get_table_names(bind):
        return False

    target_revision = _parse_revision(RUNTIME_SCHEMA_ALEMBIC_REVISION)
    if target_revision is None:
        return False

    rows = bind.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    if not rows:
        return False

    parsed_rows = [_parse_revision(str(row or "")) for row in rows]
    if any(parsed is None for parsed in parsed_rows):
        return False

    return all(parsed >= target_revision for parsed in parsed_rows if parsed is not None)



def _has_current_runtime_schema(bind: Engine | Connection) -> bool:
    required_tables = {"users", "messages", "sessions", "session_members", "files", "session_events", "groups"}
    if required_tables - _get_table_names(bind):
        return False

    return (
        _has_columns(bind, "users", USER_PROFILE_COLUMN_DDL)
        and _has_columns(bind, "users", USER_AVATAR_COLUMN_DDL)
        and _has_columns(bind, "messages", MESSAGE_COLUMN_DDL)
        and _has_columns(bind, "sessions", SESSION_COLUMN_DDL)
        and _has_columns(bind, "session_members", SESSION_MEMBER_COLUMN_DDL)
        and _has_columns(bind, "files", FILE_COLUMN_DDL)
        and _has_indexes(bind, "users", USER_PROFILE_INDEX_DDL)
        and _has_indexes(bind, "messages", CHAT_INDEX_DDL)
        and _has_indexes(bind, "sessions", SESSION_INDEX_DDL)
        and _has_indexes(bind, "files", FILE_INDEX_DDL)
        and _has_columns(bind, "groups", GROUP_AVATAR_COLUMN_DDL)
        and _has_indexes(bind, "session_events", SESSION_EVENT_INDEX_DDL)
    )


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



def _update_session_event_payload_session_id(raw_payload: str | None, canonical_session_id: str) -> str:
    if not raw_payload:
        return "{}"
    try:
        payload = json.loads(raw_payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return raw_payload
    if not isinstance(payload, dict):
        return raw_payload
    if payload.get("session_id") == canonical_session_id:
        return raw_payload
    payload["session_id"] = canonical_session_id
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def _merge_duplicate_private_session(connection: Connection, canonical_session_id: str, duplicate_session_id: str) -> None:
    table_names = _get_table_names(connection)
    duplicate_updated_at = connection.execute(
        text("SELECT updated_at FROM sessions WHERE id = :session_id"),
        {"session_id": duplicate_session_id},
    ).scalar_one_or_none()

    if "messages" in table_names:
        next_session_seq = int(
            connection.execute(
                text("SELECT COALESCE(MAX(session_seq), 0) FROM messages WHERE session_id = :session_id"),
                {"session_id": canonical_session_id},
            ).scalar_one()
            or 0
        )
        message_ids = connection.execute(
            text(
                """
                SELECT id
                FROM messages
                WHERE session_id = :session_id
                ORDER BY created_at ASC, session_seq ASC, id ASC
                """
            ),
            {"session_id": duplicate_session_id},
        ).scalars().all()
        for message_id in message_ids:
            next_session_seq += 1
            connection.execute(
                text(
                    """
                    UPDATE messages
                    SET session_id = :canonical_session_id,
                        session_seq = :session_seq
                    WHERE id = :message_id
                    """
                ),
                {
                    "canonical_session_id": canonical_session_id,
                    "session_seq": next_session_seq,
                    "message_id": message_id,
                },
            )

    if "session_events" in table_names:
        next_event_seq = int(
            connection.execute(
                text("SELECT COALESCE(MAX(event_seq), 0) FROM session_events WHERE session_id = :session_id"),
                {"session_id": canonical_session_id},
            ).scalar_one()
            or 0
        )
        events = connection.execute(
            text(
                """
                SELECT id, payload
                FROM session_events
                WHERE session_id = :session_id
                ORDER BY created_at ASC, event_seq ASC, id ASC
                """
            ),
            {"session_id": duplicate_session_id},
        ).mappings().all()
        for row in events:
            next_event_seq += 1
            connection.execute(
                text(
                    """
                    UPDATE session_events
                    SET session_id = :canonical_session_id,
                        event_seq = :event_seq,
                        payload = :payload
                    WHERE id = :event_id
                    """
                ),
                {
                    "canonical_session_id": canonical_session_id,
                    "event_seq": next_event_seq,
                    "payload": _update_session_event_payload_session_id(row["payload"], canonical_session_id),
                    "event_id": row["id"],
                },
            )

    if "session_members" in table_names:
        duplicate_members = connection.execute(
            text(
                """
                SELECT user_id, joined_at, last_read_message_id, last_read_at
                FROM session_members
                WHERE session_id = :session_id
                ORDER BY user_id ASC
                """
            ),
            {"session_id": duplicate_session_id},
        ).mappings().all()
        for row in duplicate_members:
            member_exists = int(
                connection.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM session_members
                        WHERE session_id = :session_id
                          AND user_id = :user_id
                        """
                    ),
                    {"session_id": canonical_session_id, "user_id": row["user_id"]},
                ).scalar_one()
                or 0
            )
            if member_exists == 0:
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
                        VALUES (
                            :session_id,
                            :user_id,
                            :joined_at,
                            0,
                            NULL,
                            NULL
                        )
                        """
                    ),
                    {
                        "session_id": canonical_session_id,
                        "user_id": row["user_id"],
                        "joined_at": row["joined_at"],
                    },
                )

            last_read_message_id = row["last_read_message_id"]
            if last_read_message_id:
                read_seq = connection.execute(
                    text(
                        """
                        SELECT session_seq
                        FROM messages
                        WHERE id = :message_id
                          AND session_id = :session_id
                        """
                    ),
                    {"message_id": last_read_message_id, "session_id": canonical_session_id},
                ).scalar_one_or_none()
                if read_seq is not None:
                    current_seq = int(
                        connection.execute(
                            text(
                                """
                                SELECT COALESCE(last_read_seq, 0)
                                FROM session_members
                                WHERE session_id = :session_id
                                  AND user_id = :user_id
                                """
                            ),
                            {"session_id": canonical_session_id, "user_id": row["user_id"]},
                        ).scalar_one()
                        or 0
                    )
                    if int(read_seq or 0) > current_seq:
                        connection.execute(
                            text(
                                """
                                UPDATE session_members
                                SET last_read_seq = :last_read_seq,
                                    last_read_message_id = :last_read_message_id,
                                    last_read_at = :last_read_at
                                WHERE session_id = :session_id
                                  AND user_id = :user_id
                                """
                            ),
                            {
                                "last_read_seq": int(read_seq or 0),
                                "last_read_message_id": last_read_message_id,
                                "last_read_at": row["last_read_at"],
                                "session_id": canonical_session_id,
                                "user_id": row["user_id"],
                            },
                        )

        connection.execute(
            text("DELETE FROM session_members WHERE session_id = :session_id"),
            {"session_id": duplicate_session_id},
        )

    if duplicate_updated_at is not None:
        connection.execute(
            text(
                """
                UPDATE sessions
                SET updated_at = CASE
                    WHEN updated_at IS NULL OR updated_at < :updated_at THEN :updated_at
                    ELSE updated_at
                END
                WHERE id = :session_id
                """
            ),
            {"updated_at": duplicate_updated_at, "session_id": canonical_session_id},
        )

    connection.execute(
        text("DELETE FROM sessions WHERE id = :session_id"),
        {"session_id": duplicate_session_id},
    )


def _backfill_private_session_direct_keys(connection: Connection, applied: list[str]) -> None:
    table_names = _get_table_names(connection)
    if {"sessions", "session_members"} - table_names:
        return
    if "direct_key" not in _get_column_names(connection, "sessions"):
        return

    rows = connection.execute(
        text(
            """
            SELECT id
            FROM sessions
            WHERE type = 'private'
              AND COALESCE(is_ai_session, FALSE) = FALSE
            ORDER BY COALESCE(updated_at, created_at) DESC,
                     COALESCE(created_at, updated_at) DESC,
                     id ASC
            """
        )
    ).mappings().all()

    grouped_session_ids: dict[str, list[str]] = {}
    invalid_session_ids: list[str] = []
    touched = False
    for row in rows:
        session_id = row["id"]
        member_ids = [
            str(user_id or "").strip()
            for user_id in connection.execute(
                text(
                    """
                    SELECT user_id
                    FROM session_members
                    WHERE session_id = :session_id
                    ORDER BY user_id ASC
                    """
                ),
                {"session_id": session_id},
            ).scalars().all()
            if str(user_id or "").strip()
        ]
        member_key = tuple(sorted(set(member_ids)))
        if len(member_key) != 2:
            invalid_session_ids.append(session_id)
            continue
        grouped_session_ids.setdefault(":".join(member_key), []).append(session_id)

    for session_id in invalid_session_ids:
        connection.execute(
            text("UPDATE sessions SET direct_key = NULL WHERE id = :session_id"),
            {"session_id": session_id},
        )
        touched = True

    for direct_key, session_ids in grouped_session_ids.items():
        canonical_session_id = session_ids[0]
        connection.execute(
            text("UPDATE sessions SET direct_key = :direct_key WHERE id = :session_id"),
            {"direct_key": direct_key, "session_id": canonical_session_id},
        )
        touched = True
        for duplicate_session_id in session_ids[1:]:
            _merge_duplicate_private_session(connection, canonical_session_id, duplicate_session_id)
            touched = True

    connection.execute(
        text(
            """
            UPDATE sessions
            SET direct_key = NULL
            WHERE type <> 'private'
               OR COALESCE(is_ai_session, FALSE) <> FALSE
            """
        )
    )

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
    if "session_events" in table_names:
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

    if touched:
        applied.append("sessions.direct_key.backfill")


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



def _backfill_user_avatar_state(connection: Connection, applied: list[str]) -> None:
    if "users" not in _get_table_names(connection):
        return

    required_columns = {"avatar_kind", "avatar_default_key", "avatar_file_id", "avatar"}
    if not required_columns.issubset(_get_column_names(connection, "users")):
        return

    rows = connection.execute(
        text(
            """
            SELECT id, username, gender, avatar, avatar_kind, avatar_default_key, avatar_file_id
            FROM users
            ORDER BY created_at ASC, id ASC
            """
        )
    ).mappings().all()

    touched = False
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
            connection.execute(
                text(
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
            touched = True

    if touched:
        applied.append("users.avatar_state.backfill")


def _backfill_group_avatar_state(connection: Connection, applied: list[str]) -> None:
    if "groups" not in _get_table_names(connection):
        return

    required_columns = {"avatar_kind", "avatar_file_id", "avatar_version"}
    if not required_columns.issubset(_get_column_names(connection, "groups")):
        return

    updated = connection.execute(
        text(
            """
            UPDATE groups
            SET avatar_kind = COALESCE(NULLIF(TRIM(avatar_kind), ''), 'generated'),
                avatar_version = CASE
                    WHEN COALESCE(avatar_version, 0) > 0 THEN avatar_version
                    ELSE 1
                END
            WHERE COALESCE(NULLIF(TRIM(avatar_kind), ''), 'generated') <> avatar_kind
               OR COALESCE(avatar_version, 0) <= 0
            """
        )
    )
    if int(getattr(updated, "rowcount", 0) or 0) > 0:
        applied.append("groups.avatar_state.backfill")
def ensure_schema_compatibility(engine: Engine) -> list[str]:
    """Apply fallback-only schema fixes for databases that skipped migrations."""
    applied: list[str] = []

    with engine.begin() as connection:
        if _has_runtime_schema_migration(connection):
            return applied

        if _has_current_runtime_schema(connection):
            return applied

        _ensure_columns(connection, "users", USER_PROFILE_COLUMN_DDL, applied)
        _ensure_columns(connection, "users", USER_AVATAR_COLUMN_DDL, applied)
        _ensure_indexes(connection, "users", USER_PROFILE_INDEX_DDL, applied)

        _ensure_columns(connection, "messages", MESSAGE_COLUMN_DDL, applied)
        _ensure_columns(connection, "sessions", SESSION_COLUMN_DDL, applied)
        _ensure_columns(connection, "session_members", SESSION_MEMBER_COLUMN_DDL, applied)
        _ensure_columns(connection, "files", FILE_COLUMN_DDL, applied)
        _ensure_columns(connection, "groups", GROUP_AVATAR_COLUMN_DDL, applied)

        _backfill_message_session_seq(connection, applied)
        _backfill_group_chat_membership(connection, applied)
        _backfill_private_session_direct_keys(connection, applied)
        _backfill_session_last_message_seq(connection, applied)
        _backfill_session_last_event_seq(connection, applied)
        _backfill_session_member_read_state(connection, applied)
        _backfill_file_storage_metadata(connection, applied)
        _backfill_user_avatar_state(connection, applied)
        _backfill_group_avatar_state(connection, applied)

        _ensure_indexes(connection, "messages", CHAT_INDEX_DDL, applied)
        _ensure_indexes(connection, "sessions", SESSION_INDEX_DDL, applied)
        _ensure_indexes(connection, "files", FILE_INDEX_DDL, applied)
        _ensure_indexes(connection, "session_events", SESSION_EVENT_INDEX_DDL, applied)

    return applied


def describe_schema_compatibility(applied: Iterable[str]) -> str:
    items = list(applied)
    if not items:
        return "Schema compatibility already up to date."
    return "Applied schema compatibility updates: " + ", ".join(items)











