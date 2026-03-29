from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
import sys
import time
import types
from datetime import datetime
from pathlib import Path


if "aiosqlite" not in sys.modules:
    aiosqlite = types.ModuleType("aiosqlite")

    class _Cursor:
        def __init__(self, cursor: sqlite3.Cursor) -> None:
            self._cursor = cursor
            self.rowcount = cursor.rowcount

        async def fetchone(self):
            return self._cursor.fetchone()

        async def fetchall(self):
            return self._cursor.fetchall()

    class _Connection:
        def __init__(self, path: str) -> None:
            self._conn = sqlite3.connect(path)
            self._row_factory = None

        @property
        def row_factory(self):
            return self._row_factory

        @row_factory.setter
        def row_factory(self, value) -> None:
            self._row_factory = value
            self._conn.row_factory = value

        async def execute(self, sql: str, params=()):
            return _Cursor(self._conn.execute(sql, params))

        async def executescript(self, script: str):
            self._conn.executescript(script)

        async def commit(self) -> None:
            self._conn.commit()

        async def close(self) -> None:
            self._conn.close()

    async def _connect(path: str):
        return _Connection(path)

    aiosqlite.Row = sqlite3.Row
    aiosqlite.Connection = _Connection
    aiosqlite.connect = _connect
    sys.modules["aiosqlite"] = aiosqlite

from client.storage.database import Database
from client.models.message import ChatMessage, MessageStatus, MessageType, Session


def test_database_connect_normalizes_legacy_private_sessions() -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-normalize.db"
    now = int(time.time())
    try:
        db_path.unlink(missing_ok=True)
        with sqlite3.connect(str(db_path)) as connection:
            connection.executescript(
                """
                CREATE TABLE sessions (
                    session_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    session_type TEXT NOT NULL DEFAULT 'direct',
                    participant_ids TEXT NOT NULL DEFAULT '[]',
                    last_message TEXT,
                    last_message_time INTEGER,
                    unread_count INTEGER NOT NULL DEFAULT 0,
                    avatar TEXT,
                    is_ai_session INTEGER NOT NULL DEFAULT 0,
                    extra TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                """
            )
            connection.execute(
                """
                INSERT INTO sessions
                (session_id, name, session_type, participant_ids, last_message,
                 last_message_time, unread_count, avatar, is_ai_session, extra,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "session-legacy-1",
                    "Legacy Private Chat",
                    "private",
                    json.dumps(["alice", "bob"]),
                    None,
                    None,
                    0,
                    None,
                    0,
                    "{}",
                    now,
                    now,
                ),
            )
            connection.commit()

        async def scenario() -> None:
            database = Database(db_path=str(db_path))
            await database.connect()
            try:
                session = await database.get_session("session-legacy-1")
                assert session is not None
                assert session.session_type == "direct"
            finally:
                await database.close()

        asyncio.run(scenario())

        with sqlite3.connect(str(db_path)) as connection:
            session_type = connection.execute(
                "SELECT session_type FROM sessions WHERE session_id = ?",
                ("session-legacy-1",),
            ).fetchone()[0]

        assert session_type == "direct"
    finally:
        try:
            db_path.unlink(missing_ok=True)
        except PermissionError:
            pass
        shutil.rmtree(temp_root, ignore_errors=True)


def test_database_local_directory_cache_search_and_clear() -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-directory-cache.db"
    try:
        db_path.unlink(missing_ok=True)

        async def scenario() -> None:
            database = Database(db_path=str(db_path))
            await database.connect()
            try:
                await database.replace_contacts_cache(
                    [
                        {
                            "id": "user-1",
                            "display_name": "Alice Core",
                            "username": "alice",
                            "nickname": "Alice",
                            "remark": "Core teammate",
                            "assistim_id": "alice",
                            "region": "Shenzhen",
                            "signature": "Build core features",
                        },
                        {
                            "id": "user-2",
                            "display_name": "Bob",
                            "username": "bob",
                            "nickname": "Bob",
                            "remark": "",
                            "assistim_id": "bob",
                            "region": "Seoul",
                            "signature": "",
                        },
                    ]
                )
                await database.replace_groups_cache(
                    [
                        {
                            "id": "group-1",
                            "name": "Core Team",
                            "session_id": "session-group-1",
                            "member_count": 3,
                            "member_search_text": "Alice Shenzhen Carol Busan",
                        },
                        {
                            "id": "group-2",
                            "name": "Weekend Club",
                            "session_id": "session-group-2",
                            "member_count": 5,
                        },
                    ]
                )

                contacts = await database.search_contacts("core", limit=10)
                groups = await database.search_groups("core", limit=10)
                region_contacts = await database.search_contacts("shenzhen", limit=10)
                member_groups = await database.search_groups("busan", limit=10)
                assert [item["id"] for item in contacts] == ["user-1"]
                assert [item["id"] for item in groups] == ["group-1"]
                assert [item["id"] for item in region_contacts] == ["user-1"]
                assert [item["id"] for item in member_groups] == ["group-1"]

                await database.clear_chat_state()
                assert await database.search_contacts("core", limit=10) == []
                assert await database.search_groups("core", limit=10) == []
            finally:
                await database.close()

        asyncio.run(scenario())
    finally:
        try:
            db_path.unlink(missing_ok=True)
        except PermissionError:
            pass
        shutil.rmtree(temp_root, ignore_errors=True)


def test_database_message_search_tracks_updates_and_deletes() -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-message-search-sync.db"
    try:
        db_path.unlink(missing_ok=True)

        async def scenario() -> None:
            database = Database(str(db_path))
            await database.connect()
            try:
                session = Session(
                    session_id="session-1",
                    name="Direct Chat",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                await database.save_session(session)

                message = ChatMessage(
                    message_id="message-1",
                    session_id="session-1",
                    sender_id="user-1",
                    content="Launch roadmap alpha",
                    message_type=MessageType.TEXT,
                    status=MessageStatus.SENT,
                    timestamp=datetime.now(),
                    updated_at=datetime.now(),
                )
                await database.save_message(message)

                launch_results = await database.search_messages("launch", session_id="session-1", limit=10)
                assert [item.message_id for item in launch_results] == ["message-1"]

                await database.update_message_content("message-1", "Beta roadmap only")
                assert await database.search_messages("launch", session_id="session-1", limit=10) == []
                beta_results = await database.search_messages("beta", session_id="session-1", limit=10)
                assert [item.message_id for item in beta_results] == ["message-1"]

                await database.delete_message("message-1")
                assert await database.search_messages("beta", session_id="session-1", limit=10) == []
            finally:
                await database.close()

        asyncio.run(scenario())
    finally:
        try:
            db_path.unlink(missing_ok=True)
        except PermissionError:
            pass
        shutil.rmtree(temp_root, ignore_errors=True)


def test_database_connect_upgrades_local_search_cache_columns() -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-cache-schema-upgrade.db"
    try:
        db_path.unlink(missing_ok=True)
        with sqlite3.connect(str(db_path)) as connection:
            connection.executescript(
                """
                CREATE TABLE contacts_cache (
                    contact_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL DEFAULT '',
                    username TEXT NOT NULL DEFAULT '',
                    nickname TEXT NOT NULL DEFAULT '',
                    remark TEXT NOT NULL DEFAULT '',
                    assistim_id TEXT NOT NULL DEFAULT '',
                    avatar TEXT NOT NULL DEFAULT '',
                    signature TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT 'friend',
                    status TEXT NOT NULL DEFAULT '',
                    extra TEXT NOT NULL DEFAULT '{}',
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE groups_cache (
                    group_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    avatar TEXT NOT NULL DEFAULT '',
                    owner_id TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    member_count INTEGER NOT NULL DEFAULT 0,
                    extra TEXT NOT NULL DEFAULT '{}',
                    updated_at INTEGER NOT NULL
                );
                """
            )
            connection.commit()

        async def scenario() -> None:
            database = Database(db_path=str(db_path))
            await database.connect()
            try:
                cursor = await database._db.execute("PRAGMA table_info(contacts_cache)")
                contact_columns = {row["name"] for row in await cursor.fetchall()}
                cursor = await database._db.execute("PRAGMA table_info(groups_cache)")
                group_columns = {row["name"] for row in await cursor.fetchall()}
                assert "region" in contact_columns
                assert "member_search_text" in group_columns
            finally:
                await database.close()

        asyncio.run(scenario())
    finally:
        try:
            db_path.unlink(missing_ok=True)
        except PermissionError:
            pass
        shutil.rmtree(temp_root, ignore_errors=True)


def test_database_read_cursor_overlay_updates_cached_self_messages_without_row_rewrites() -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-read-cursor-overlay.db"
    try:
        db_path.unlink(missing_ok=True)

        async def scenario() -> None:
            database = Database(str(db_path))
            await database.connect()
            try:
                session = Session(
                    session_id="session-1",
                    name="Core Team",
                    session_type="group",
                    participant_ids=["alice", "bob", "charlie"],
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                await database.save_session(session)

                base_time = datetime(2026, 3, 29, 10, 0, 0)
                await database.save_messages_batch(
                    [
                        ChatMessage(
                            message_id="m-1",
                            session_id="session-1",
                            sender_id="alice",
                            content="one",
                            message_type=MessageType.TEXT,
                            status=MessageStatus.SENT,
                            timestamp=base_time,
                            updated_at=base_time,
                            is_self=True,
                            extra={
                                "session_seq": 1,
                                "read_target_count": 2,
                                "read_count": 0,
                                "read_by_user_ids": [],
                            },
                        ),
                        ChatMessage(
                            message_id="m-2",
                            session_id="session-1",
                            sender_id="alice",
                            content="two",
                            message_type=MessageType.TEXT,
                            status=MessageStatus.SENT,
                            timestamp=base_time.replace(second=1),
                            updated_at=base_time.replace(second=1),
                            is_self=True,
                            extra={
                                "session_seq": 2,
                                "read_target_count": 2,
                                "read_count": 0,
                                "read_by_user_ids": [],
                            },
                        ),
                        ChatMessage(
                            message_id="m-3",
                            session_id="session-1",
                            sender_id="alice",
                            content="three",
                            message_type=MessageType.TEXT,
                            status=MessageStatus.SENT,
                            timestamp=base_time.replace(second=2),
                            updated_at=base_time.replace(second=2),
                            is_self=True,
                            extra={
                                "session_seq": 3,
                                "read_target_count": 2,
                                "read_count": 0,
                                "read_by_user_ids": [],
                            },
                        ),
                    ]
                )

                changed_ids = await database.apply_read_receipt("session-1", "bob", "m-2", 2)
                loaded_messages = await database.get_messages("session-1", limit=10)

                assert changed_ids == []
                assert [message.message_id for message in loaded_messages] == ["m-1", "m-2", "m-3"]
                assert loaded_messages[0].extra["read_by_user_ids"] == ["bob"]
                assert loaded_messages[1].extra["read_by_user_ids"] == ["bob"]
                assert loaded_messages[2].extra["read_by_user_ids"] == []
                assert loaded_messages[0].status == MessageStatus.DELIVERED
                assert loaded_messages[1].status == MessageStatus.DELIVERED
                assert loaded_messages[2].status == MessageStatus.SENT
            finally:
                await database.close()

        asyncio.run(scenario())

        with sqlite3.connect(str(db_path)) as connection:
            cursor_seq = connection.execute(
                "SELECT last_read_seq FROM session_read_cursors WHERE session_id = ? AND reader_id = ?",
                ("session-1", "bob"),
            ).fetchone()[0]
            persisted_extra = json.loads(
                connection.execute(
                    "SELECT extra FROM messages WHERE message_id = ?",
                    ("m-1",),
                ).fetchone()[0]
            )

        assert cursor_seq == 2
        assert persisted_extra["read_by_user_ids"] == []
    finally:
        try:
            db_path.unlink(missing_ok=True)
        except PermissionError:
            pass
        shutil.rmtree(temp_root, ignore_errors=True)
