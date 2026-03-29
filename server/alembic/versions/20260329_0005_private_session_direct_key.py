"""Formalize unique direct-session identity and remove legacy duplicate private sessions."""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "20260329_0005"
down_revision = "20260328_0004"
branch_labels = None
depends_on = None


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


def _update_payload_session_id(raw_payload: str | None, canonical_session_id: str) -> str:
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


def _merge_duplicate_private_session(bind, canonical_session_id: str, duplicate_session_id: str) -> None:
    table_names = _table_names(bind)
    duplicate_updated_at = bind.execute(
        sa.text("SELECT updated_at FROM sessions WHERE id = :session_id"),
        {"session_id": duplicate_session_id},
    ).scalar_one_or_none()

    if "messages" in table_names:
        next_session_seq = int(
            bind.execute(
                sa.text("SELECT COALESCE(MAX(session_seq), 0) FROM messages WHERE session_id = :session_id"),
                {"session_id": canonical_session_id},
            ).scalar_one()
            or 0
        )
        message_ids = bind.execute(
            sa.text(
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
            bind.execute(
                sa.text(
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
            bind.execute(
                sa.text("SELECT COALESCE(MAX(event_seq), 0) FROM session_events WHERE session_id = :session_id"),
                {"session_id": canonical_session_id},
            ).scalar_one()
            or 0
        )
        events = bind.execute(
            sa.text(
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
            bind.execute(
                sa.text(
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
                    "payload": _update_payload_session_id(row["payload"], canonical_session_id),
                    "event_id": row["id"],
                },
            )

    if "session_members" in table_names:
        duplicate_members = bind.execute(
            sa.text(
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
                bind.execute(
                    sa.text(
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
                read_seq = bind.execute(
                    sa.text(
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
                        bind.execute(
                            sa.text(
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
                        bind.execute(
                            sa.text(
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

        bind.execute(
            sa.text("DELETE FROM session_members WHERE session_id = :session_id"),
            {"session_id": duplicate_session_id},
        )

    if duplicate_updated_at is not None:
        bind.execute(
            sa.text(
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

    bind.execute(
        sa.text("DELETE FROM sessions WHERE id = :session_id"),
        {"session_id": duplicate_session_id},
    )


def _backfill_private_direct_keys(bind) -> None:
    table_names = _table_names(bind)
    if {"sessions", "session_members"} - table_names:
        return
    if "direct_key" not in _column_names(bind, "sessions"):
        return

    rows = bind.execute(
        sa.text(
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
    for row in rows:
        session_id = row["id"]
        member_ids = [
            str(user_id or "").strip()
            for user_id in bind.execute(
                sa.text(
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
        bind.execute(
            sa.text("UPDATE sessions SET direct_key = NULL WHERE id = :session_id"),
            {"session_id": session_id},
        )

    for direct_key, session_ids in grouped_session_ids.items():
        canonical_session_id = session_ids[0]
        bind.execute(
            sa.text("UPDATE sessions SET direct_key = :direct_key WHERE id = :session_id"),
            {"direct_key": direct_key, "session_id": canonical_session_id},
        )
        for duplicate_session_id in session_ids[1:]:
            _merge_duplicate_private_session(bind, canonical_session_id, duplicate_session_id)

    bind.execute(
        sa.text(
            """
            UPDATE sessions
            SET direct_key = NULL
            WHERE type <> 'private'
               OR COALESCE(is_ai_session, FALSE) <> FALSE
            """
        )
    )

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
    if "session_events" in table_names:
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


def upgrade() -> None:
    bind = op.get_bind()

    _add_column_if_missing(
        "sessions",
        sa.Column("direct_key", sa.String(length=255), nullable=True),
    )
    _backfill_private_direct_keys(bind)
    _create_index_if_missing("sessions", "idx_sessions_direct_key", ["direct_key"], unique=True)


def downgrade() -> None:
    return None
