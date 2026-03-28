from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
import sys
import time
import types
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
                            "signature": "Build core features",
                        },
                        {
                            "id": "user-2",
                            "display_name": "Bob",
                            "username": "bob",
                            "nickname": "Bob",
                            "remark": "",
                            "assistim_id": "bob",
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
                assert [item["id"] for item in contacts] == ["user-1"]
                assert [item["id"] for item in groups] == ["group-1"]

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
