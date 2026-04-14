from __future__ import annotations

import asyncio
import importlib
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

from client.storage import database as database_module
from client.storage.database import Database
from client.core.secure_storage import SecureStorage
from client.models.message import ChatMessage, MessageStatus, MessageType, Session


def _read_db_crypto_metadata(path: Path) -> dict[str, object]:
    metadata_path = Path(f"{path}.crypto.json")
    if not metadata_path.exists():
        return {}
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def _expected_runtime_module_for_requested_sqlcipher() -> str:
    core_module = getattr(database_module.aiosqlite, "core", None)
    if core_module is None or getattr(core_module, "sqlite3", None) is None:
        return "sqlite3"
    for module_name in database_module.Database.DB_ENCRYPTION_PROVIDER_SQLCIPHER_MODULES:
        try:
            importlib.import_module(module_name)
            return module_name
        except ImportError:
            continue
    return "sqlite3"


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
                await database.set_app_state("auth.user_id", "alice")
                await database.replace_contacts_cache(
                    [
                        {
                            "id": "shared-user",
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
                    ],
                    owner_user_id="alice",
                )
                await database.replace_groups_cache(
                    [
                        {
                            "id": "shared-group",
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
                    ],
                    owner_user_id="alice",
                )
                await database.replace_contacts_cache(
                    [
                        {
                            "id": "shared-user",
                            "display_name": "Bob Core",
                            "username": "bob-core",
                            "nickname": "Bobby",
                            "remark": "Core operator",
                            "assistim_id": "bobcore",
                            "region": "Busan",
                            "signature": "Run core ops",
                        }
                    ],
                    owner_user_id="bob",
                )
                await database.replace_groups_cache(
                    [
                        {
                            "id": "shared-group",
                            "name": "Core Ops",
                            "session_id": "session-group-3",
                            "member_count": 4,
                            "member_search_text": "Bobby Busan Dana",
                        }
                    ],
                    owner_user_id="bob",
                )

                contacts = await database.search_contacts("core", limit=10)
                groups = await database.search_groups("core", limit=10)
                region_contacts = await database.search_contacts("shenzhen", limit=10)
                member_groups = await database.search_groups("busan", limit=10)
                assert [item["id"] for item in contacts] == ["shared-user"]
                assert [item["display_name"] for item in contacts] == ["Alice Core"]
                assert [item["id"] for item in groups] == ["shared-group"]
                assert [item["name"] for item in groups] == ["Core Team"]
                assert [item["id"] for item in region_contacts] == ["shared-user"]
                assert [item["id"] for item in member_groups] == ["shared-group"]
                assert await database.list_contacts_cache_by_ids(["shared-user"]) == {
                    "shared-user": contacts[0]
                }

                await database.set_app_state("auth.user_id", "bob")
                bob_contacts = await database.search_contacts("core", limit=10)
                bob_groups = await database.search_groups("core", limit=10)
                assert [item["id"] for item in bob_contacts] == ["shared-user"]
                assert [item["display_name"] for item in bob_contacts] == ["Bob Core"]
                assert [item["id"] for item in bob_groups] == ["shared-group"]
                assert [item["name"] for item in bob_groups] == ["Core Ops"]

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



def test_database_replace_sessions_prunes_messages_and_read_cursors_outside_snapshot() -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-replace-sessions-prune.db"
    try:
        db_path.unlink(missing_ok=True)

        async def scenario() -> None:
            database = Database(str(db_path))
            await database.connect()
            try:
                session_1 = Session(
                    session_id="session-1",
                    name="One",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                session_2 = Session(
                    session_id="session-2",
                    name="Two",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                await database.save_sessions_batch([session_1, session_2])
                await database.save_message(
                    ChatMessage(
                        message_id="message-1",
                        session_id="session-1",
                        sender_id="alice",
                        content="kept",
                        message_type=MessageType.TEXT,
                        status=MessageStatus.SENT,
                        timestamp=datetime.now(),
                        updated_at=datetime.now(),
                        extra={"session_seq": 1},
                    )
                )
                await database.save_message(
                    ChatMessage(
                        message_id="message-2",
                        session_id="session-2",
                        sender_id="alice",
                        content="pruned",
                        message_type=MessageType.TEXT,
                        status=MessageStatus.SENT,
                        timestamp=datetime.now(),
                        updated_at=datetime.now(),
                        extra={"session_seq": 1},
                    )
                )
                await database.apply_read_receipt("session-2", "bob", "message-2", 1)

                await database.replace_sessions([session_1])
            finally:
                await database.close()

        asyncio.run(scenario())

        with sqlite3.connect(str(db_path)) as connection:
            message_rows = connection.execute("SELECT session_id FROM messages ORDER BY session_id").fetchall()
            cursor_rows = connection.execute("SELECT session_id FROM session_read_cursors").fetchall()
            session_rows = connection.execute("SELECT session_id FROM sessions ORDER BY session_id").fetchall()

        assert message_rows == [("session-1",)]
        assert cursor_rows == []
        assert session_rows == [("session-1",)]
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
                contact_rows = await cursor.fetchall()
                contact_columns = {row["name"] for row in contact_rows}
                cursor = await database._db.execute("PRAGMA table_info(groups_cache)")
                group_rows = await cursor.fetchall()
                group_columns = {row["name"] for row in group_rows}
                cursor = await database._db.execute("PRAGMA table_info(messages)")
                message_columns = {row["name"] for row in await cursor.fetchall()}
                contact_primary_key = {
                    row["name"]: int(row["pk"] or 0)
                    for row in contact_rows
                    if int(row["pk"] or 0) > 0
                }
                group_primary_key = {
                    row["name"]: int(row["pk"] or 0)
                    for row in group_rows
                    if int(row["pk"] or 0) > 0
                }
                assert "owner_user_id" in contact_columns
                assert "region" in contact_columns
                assert contact_primary_key == {"owner_user_id": 1, "contact_id": 2}
                assert "owner_user_id" in group_columns
                assert "member_search_text" in group_columns
                assert group_primary_key == {"owner_user_id": 1, "group_id": 2}
                assert "is_encrypted" in message_columns
                assert "encryption_scheme" in message_columns
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


def test_database_directory_cache_replace_is_atomic_per_owner() -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-directory-cache-atomic.db"
    try:
        db_path.unlink(missing_ok=True)

        async def scenario() -> None:
            database = Database(db_path=str(db_path))
            await database.connect()
            try:
                await database.set_app_state("auth.user_id", "alice")
                await database.replace_contacts_cache(
                    [
                        {
                            "id": "legacy-contact",
                            "display_name": "Legacy Contact",
                            "nickname": "Legacy",
                            "assistim_id": "legacy-contact",
                            "region": "Seoul",
                        }
                    ],
                    owner_user_id="alice",
                )
                await database.replace_groups_cache(
                    [
                        {
                            "id": "legacy-group",
                            "name": "Legacy Group",
                            "session_id": "session-legacy",
                            "member_search_text": "Legacy Seoul",
                        }
                    ],
                    owner_user_id="alice",
                )

                original_execute = database._db.execute
                contact_insert_calls = 0

                async def flaky_contact_execute(sql: str, params=()):
                    nonlocal contact_insert_calls
                    normalized_sql = " ".join(str(sql).split())
                    if "INSERT OR REPLACE INTO contacts_cache" in normalized_sql:
                        contact_insert_calls += 1
                        if contact_insert_calls == 2:
                            raise RuntimeError("inject contact replace failure")
                    return await original_execute(sql, params)

                database._db.execute = flaky_contact_execute
                try:
                    try:
                        await database.replace_contacts_cache(
                            [
                                {"id": "new-contact-1", "display_name": "New Contact 1"},
                                {"id": "new-contact-2", "display_name": "New Contact 2"},
                            ],
                            owner_user_id="alice",
                        )
                        raise AssertionError("replace_contacts_cache should have failed")
                    except RuntimeError as exc:
                        assert str(exc) == "inject contact replace failure"
                finally:
                    database._db.execute = original_execute

                assert [item["id"] for item in await database.search_contacts("legacy", limit=10)] == ["legacy-contact"]

                group_insert_calls = 0

                async def flaky_group_execute(sql: str, params=()):
                    nonlocal group_insert_calls
                    normalized_sql = " ".join(str(sql).split())
                    if "INSERT OR REPLACE INTO groups_cache" in normalized_sql:
                        group_insert_calls += 1
                        if group_insert_calls == 2:
                            raise RuntimeError("inject group replace failure")
                    return await original_execute(sql, params)

                database._db.execute = flaky_group_execute
                try:
                    try:
                        await database.replace_groups_cache(
                            [
                                {"id": "new-group-1", "name": "New Group 1"},
                                {"id": "new-group-2", "name": "New Group 2"},
                            ],
                            owner_user_id="alice",
                        )
                        raise AssertionError("replace_groups_cache should have failed")
                    except RuntimeError as exc:
                        assert str(exc) == "inject group replace failure"
                finally:
                    database._db.execute = original_execute

                assert [item["id"] for item in await database.search_groups("legacy", limit=10)] == ["legacy-group"]
            finally:
                await database.close()

        asyncio.run(scenario())
    finally:
        try:
            db_path.unlink(missing_ok=True)
        except PermissionError:
            pass
        shutil.rmtree(temp_root, ignore_errors=True)


def test_database_connect_records_plain_db_encryption_state(monkeypatch) -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-encryption-plain.db"
    try:
        db_path.unlink(missing_ok=True)

        fake_config = types.SimpleNamespace(
            storage=types.SimpleNamespace(
                db_path=str(db_path),
                db_encryption_mode="plain",
            )
        )
        monkeypatch.setattr(database_module, "get_config", lambda: fake_config)

        async def scenario() -> None:
            database = database_module.Database()
            await database.connect()
            try:
                status = database.get_db_encryption_status()
                self_check = database.get_db_encryption_self_check()
                assert status["requested_mode"] == "plain"
                assert status["requested_provider"] == "auto"
                assert status["effective_mode"] == "plain"
                assert status["runtime_provider"] == "sqlite-default"
                assert status["runtime_module"] == "sqlite3"
                assert status["provider_match"] is True
                assert status["driver_available"] is False
                assert status["driver_version"] == ""
                assert status["has_key_material"] is False
                assert status["key_id"] == ""
                assert status["ready_for_sqlcipher"] is False
                assert status["migration_required"] is False
                assert status["supported_sqlcipher_modules"] == list(
                    database_module.Database.DB_ENCRYPTION_PROVIDER_SQLCIPHER_MODULES
                )
                assert status["install_hint"] == ""
                if status["fts_available"]:
                    assert status["fts_tokenizer"] in {"trigram", "unicode61"}
                else:
                    assert status["fts_tokenizer"] == ""
                assert self_check["state"] == "plain"
                assert self_check["severity"] == "info"
                assert self_check["can_start"] is True
                assert self_check["action_required"] is False
                if status["fts_available"]:
                    assert self_check["search_mode"] == f"fts5_{status['fts_tokenizer']}"
                    assert "FTS5" in self_check["search_message"]
                else:
                    assert self_check["search_mode"] == "like_fallback"
                    assert "LIKE" in self_check["search_message"]
                assert await database.get_app_state(database.APP_STATE_DB_ENCRYPTION_MODE) == "plain"
                assert await database.get_app_state(database.APP_STATE_DB_ENCRYPTION_KEY) is None
                assert await database.get_app_state(database.APP_STATE_DB_ENCRYPTION_KEY_ID) is None
                assert _read_db_crypto_metadata(db_path) == {}
            finally:
                await database.close()

        asyncio.run(scenario())
    finally:
        try:
            db_path.unlink(missing_ok=True)
        except PermissionError:
            pass
        shutil.rmtree(temp_root, ignore_errors=True)


def test_database_connect_prepares_sqlcipher_key_material(monkeypatch) -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-encryption-sqlcipher.db"
    try:
        db_path.unlink(missing_ok=True)

        fake_config = types.SimpleNamespace(
            storage=types.SimpleNamespace(
                db_path=str(db_path),
                db_encryption_mode="sqlcipher",
                db_encryption_provider="auto",
            )
        )
        monkeypatch.setattr(database_module, "get_config", lambda: fake_config)

        async def scenario() -> None:
            first_database = database_module.Database()
            await first_database.connect()
            try:
                first_status = first_database.get_db_encryption_status()
                first_self_check = first_database.get_db_encryption_self_check()
                stored_mode = await first_database.get_app_state(first_database.APP_STATE_DB_ENCRYPTION_MODE)
                stored_metadata = _read_db_crypto_metadata(db_path)
                stored_key_cipher = str(stored_metadata["db_encryption_key"])
                stored_key_id = str(stored_metadata["db_encryption_key_id"])
                decrypted_key = SecureStorage.decrypt_text(str(stored_key_cipher or ""))

                assert first_status["requested_mode"] == "sqlcipher"
                assert first_status["requested_provider"] == "auto"
                assert first_status["effective_mode"] == "sqlcipher_pending"
                assert first_status["runtime_provider"] == "sqlite-default"
                assert first_status["runtime_module"] == _expected_runtime_module_for_requested_sqlcipher()
                assert first_status["provider_match"] is True
                assert first_status["driver_available"] is False
                assert first_status["driver_version"] == ""
                assert first_status["has_key_material"] is True
                assert first_status["ready_for_sqlcipher"] is True
                assert first_status["migration_required"] is True
                assert first_status["key_id"] == stored_key_id
                assert first_status["supported_sqlcipher_modules"] == list(
                    database_module.Database.DB_ENCRYPTION_PROVIDER_SQLCIPHER_MODULES
                )
                assert "sqlcipher3" in first_status["install_hint"]
                assert first_self_check["state"] == "runtime_missing"
                assert first_self_check["severity"] == "warning"
                assert first_self_check["can_start"] is True
                assert first_self_check["action_required"] is True
                assert "sqlcipher3" in str(first_self_check.get("recommended_action") or "")
                assert stored_mode == "sqlcipher_pending"
                assert stored_metadata["db_encryption_mode"] == "sqlcipher_pending"
                assert await first_database.get_app_state(first_database.APP_STATE_DB_ENCRYPTION_KEY) is None
                assert await first_database.get_app_state(first_database.APP_STATE_DB_ENCRYPTION_KEY_ID) is None
                assert len(decrypted_key) > 10
            finally:
                await first_database.close()

            second_database = database_module.Database()
            await second_database.connect()
            try:
                second_status = second_database.get_db_encryption_status()
                assert second_status["key_id"] == stored_key_id
                assert await second_database.get_app_state(second_database.APP_STATE_DB_ENCRYPTION_MODE) == "sqlcipher_pending"
                assert await second_database.get_app_state(second_database.APP_STATE_DB_ENCRYPTION_KEY_ID) is None
                assert _read_db_crypto_metadata(db_path)["db_encryption_key_id"] == stored_key_id
            finally:
                await second_database.close()

        asyncio.run(scenario())
    finally:
        try:
            db_path.unlink(missing_ok=True)
        except PermissionError:
            pass
        shutil.rmtree(temp_root, ignore_errors=True)


def test_database_detects_sqlcipher_runtime_when_cipher_version_is_available(monkeypatch) -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-encryption-sqlcipher-driver.db"
    try:
        db_path.unlink(missing_ok=True)

        fake_config = types.SimpleNamespace(
            storage=types.SimpleNamespace(
                db_path=str(db_path),
                db_encryption_mode="sqlcipher",
                db_encryption_provider="auto",
            )
        )
        monkeypatch.setattr(database_module, "get_config", lambda: fake_config)

        original_detect = database_module.Database._detect_sqlcipher_runtime

        async def fake_detect(self) -> tuple[bool, str, str]:
            return True, "4.5.6", "sqlcipher-compatible"

        monkeypatch.setattr(database_module.Database, "_detect_sqlcipher_runtime", fake_detect)

        async def fake_detect_on_connection(self, connection) -> tuple[bool, str, str]:
            return True, "4.5.6", "sqlcipher-compatible"

        monkeypatch.setattr(database_module.Database, "_detect_sqlcipher_runtime_on_connection", fake_detect_on_connection)

        async def disable_auto_migrate(self) -> bool:
            return False

        monkeypatch.setattr(database_module.Database, "_auto_migrate_sqlcipher_if_needed", disable_auto_migrate)

        async def scenario() -> None:
            database = database_module.Database()
            await database.connect()
            try:
                status = database.get_db_encryption_status()
                self_check = database.get_db_encryption_self_check()
                assert status["requested_mode"] == "sqlcipher"
                assert status["requested_provider"] == "auto"
                assert status["effective_mode"] == "sqlcipher_pending"
                assert status["runtime_provider"] == "sqlcipher-compatible"
                assert status["runtime_module"] == _expected_runtime_module_for_requested_sqlcipher()
                assert status["provider_match"] is True
                assert status["driver_available"] is True
                assert status["driver_version"] == "4.5.6"
                assert status["has_key_material"] is True
                assert status["ready_for_sqlcipher"] is True
                assert status["migration_required"] is True
                assert status["install_hint"] == ""
                assert self_check["state"] == "migration_pending"
                assert self_check["severity"] == "warning"
                assert self_check["can_start"] is True
                assert self_check["action_required"] is True
            finally:
                await database.close()

        asyncio.run(scenario())
        monkeypatch.setattr(database_module.Database, "_detect_sqlcipher_runtime", original_detect)
    finally:
        try:
            db_path.unlink(missing_ok=True)
        except PermissionError:
            pass
        shutil.rmtree(temp_root, ignore_errors=True)


def test_database_migrates_legacy_db_key_material_out_of_app_state(monkeypatch) -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-encryption-legacy-key.db"
    try:
        db_path.unlink(missing_ok=True)

        fake_config = types.SimpleNamespace(
            storage=types.SimpleNamespace(
                db_path=str(db_path),
                db_encryption_mode="sqlcipher",
                db_encryption_provider="auto",
            )
        )
        monkeypatch.setattr(database_module, "get_config", lambda: fake_config)

        legacy_raw_key = "legacy-db-key-material"
        legacy_key_cipher = SecureStorage.encrypt_text(legacy_raw_key)
        legacy_key_id = database_module.Database._derive_db_key_id(legacy_raw_key)

        with sqlite3.connect(str(db_path)) as connection:
            connection.executescript(
                """
                CREATE TABLE app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT INTO app_state(key, value) VALUES (?, ?)",
                (database_module.Database.APP_STATE_DB_ENCRYPTION_MODE, "sqlcipher_pending"),
            )
            connection.execute(
                "INSERT INTO app_state(key, value) VALUES (?, ?)",
                (database_module.Database.APP_STATE_DB_ENCRYPTION_KEY, legacy_key_cipher),
            )
            connection.execute(
                "INSERT INTO app_state(key, value) VALUES (?, ?)",
                (database_module.Database.APP_STATE_DB_ENCRYPTION_KEY_ID, legacy_key_id),
            )
            connection.commit()

        async def scenario() -> None:
            database = database_module.Database()
            await database.connect()
            try:
                metadata = _read_db_crypto_metadata(db_path)
                status = database.get_db_encryption_status()
                assert metadata["db_encryption_key"] == legacy_key_cipher
                assert metadata["db_encryption_key_id"] == legacy_key_id
                assert metadata["db_encryption_mode"] == "sqlcipher_pending"
                assert status["key_id"] == legacy_key_id
                assert await database.get_app_state(database.APP_STATE_DB_ENCRYPTION_KEY) is None
                assert await database.get_app_state(database.APP_STATE_DB_ENCRYPTION_KEY_ID) is None
            finally:
                await database.close()

        asyncio.run(scenario())
    finally:
        try:
            db_path.unlink(missing_ok=True)
        except PermissionError:
            pass
        metadata_path = Path(f"{db_path}.crypto.json")
        try:
            metadata_path.unlink(missing_ok=True)
        except PermissionError:
            pass
        shutil.rmtree(temp_root, ignore_errors=True)


def test_database_migrate_to_sqlcipher_updates_metadata_and_reopens(monkeypatch) -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-migrate-sqlcipher.db"
    backup_path = Path(f"{db_path}.pre-sqlcipher.bak")
    temp_export_path = Path(f"{db_path}.sqlcipher.tmp")
    metadata_path = Path(f"{db_path}.crypto.json")
    try:
        db_path.unlink(missing_ok=True)
        backup_path.unlink(missing_ok=True)
        temp_export_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)

        fake_config = types.SimpleNamespace(
            storage=types.SimpleNamespace(
                db_path=str(db_path),
                db_encryption_mode="sqlcipher",
                db_encryption_provider="auto",
            )
        )
        monkeypatch.setattr(database_module, "get_config", lambda: fake_config)

        async def fake_detect(self) -> tuple[bool, str, str]:
            return True, "4.5.6", "sqlcipher-compatible"

        monkeypatch.setattr(database_module.Database, "_detect_sqlcipher_runtime", fake_detect)

        async def fake_detect_on_connection(self, connection) -> tuple[bool, str, str]:
            return True, "4.5.6", "sqlcipher-compatible"

        monkeypatch.setattr(database_module.Database, "_detect_sqlcipher_runtime_on_connection", fake_detect_on_connection)

        async def disable_auto_migrate(self) -> bool:
            return False

        monkeypatch.setattr(database_module.Database, "_auto_migrate_sqlcipher_if_needed", disable_auto_migrate)

        class _DummyCursor:
            def __init__(self, row=None):
                self._row = row
                self.rowcount = 1

            async def fetchone(self):
                return self._row

            async def fetchall(self):
                return [] if self._row is None else [self._row]

        async def scenario() -> None:
            database = database_module.Database()
            await database.connect()
            try:
                await database.save_session(
                    Session(
                        session_id="session-1",
                        name="Bob",
                        session_type="direct",
                        participant_ids=["alice", "bob"],
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    )
                )
                await database.save_message(
                    ChatMessage(
                        message_id="m-1",
                        session_id="session-1",
                        sender_id="alice",
                        content="ciphertext",
                        message_type=MessageType.TEXT,
                        status=MessageStatus.SENT,
                        timestamp=datetime.now(),
                        updated_at=datetime.now(),
                        is_self=False,
                        extra={},
                    )
                )

                original_execute = database._db.execute

                async def intercepted_execute(sql: str, params=()):
                    normalized_sql = " ".join(str(sql).split()).upper()
                    if normalized_sql.startswith("ATTACH DATABASE"):
                        shutil.copyfile(str(db_path), str(temp_export_path))
                        return _DummyCursor()
                    if "SQLCIPHER_EXPORT" in normalized_sql:
                        return _DummyCursor()
                    if normalized_sql.startswith("DETACH DATABASE"):
                        return _DummyCursor()
                    return await original_execute(sql, params)

                monkeypatch.setattr(database._db, "execute", intercepted_execute)

                result = await database.migrate_to_sqlcipher()

                assert result["migrated"] is True
                assert result["effective_mode"] == "sqlcipher"
                assert Path(result["backup_path"]) == backup_path
                assert backup_path.exists()
                assert not temp_export_path.exists()
                assert metadata_path.exists()
                metadata = _read_db_crypto_metadata(db_path)
                assert metadata["db_encryption_mode"] == "sqlcipher"
                status = database.get_db_encryption_status()
                assert status["effective_mode"] == "sqlcipher"
                assert status["requested_provider"] == "auto"
                assert status["runtime_provider"] == "sqlcipher-compatible"
                assert status["runtime_module"] == _expected_runtime_module_for_requested_sqlcipher()
                assert status["provider_match"] is True
                assert status["driver_available"] is True
                assert status["driver_version"] == "4.5.6"
                assert status["migration_required"] is False
                assert await database.get_app_state(database.APP_STATE_DB_ENCRYPTION_MODE) == "sqlcipher"
            finally:
                await database.close()

        asyncio.run(scenario())
    finally:
        for path in (db_path, backup_path, temp_export_path, metadata_path):
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                pass
        shutil.rmtree(temp_root, ignore_errors=True)


def test_database_connect_auto_migrates_to_sqlcipher_when_driver_is_available(monkeypatch) -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-auto-migrate-sqlcipher.db"
    backup_path = Path(f"{db_path}.pre-sqlcipher.bak")
    metadata_path = Path(f"{db_path}.crypto.json")
    try:
        db_path.unlink(missing_ok=True)
        backup_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)

        fake_config = types.SimpleNamespace(
            storage=types.SimpleNamespace(
                db_path=str(db_path),
                db_encryption_mode="sqlcipher",
                db_encryption_provider="auto",
            )
        )
        monkeypatch.setattr(database_module, "get_config", lambda: fake_config)

        async def fake_detect(self) -> tuple[bool, str, str]:
            return True, "4.5.6", "sqlcipher-compatible"

        monkeypatch.setattr(database_module.Database, "_detect_sqlcipher_runtime", fake_detect)

        migration_calls: list[str] = []
        original_migrate = database_module.Database._migrate_current_connection_to_sqlcipher

        async def fake_migrate(self) -> None:
            migration_calls.append(self._db_path)
            metadata = self._load_db_crypto_metadata()
            metadata["db_encryption_mode"] = self.DB_ENCRYPTION_MODE_SQLCIPHER
            self._save_db_crypto_metadata(metadata)
            Path(backup_path).write_text("backup", encoding="utf-8")

        monkeypatch.setattr(database_module.Database, "_migrate_current_connection_to_sqlcipher", fake_migrate)

        async def scenario() -> None:
            database = database_module.Database()
            await database.connect()
            try:
                status = database.get_db_encryption_status()
                metadata = _read_db_crypto_metadata(db_path)
                assert migration_calls == [str(db_path)]
                assert status["requested_mode"] == "sqlcipher"
                assert status["requested_provider"] == "auto"
                assert status["effective_mode"] == "sqlcipher"
                assert status["runtime_provider"] == "sqlcipher-compatible"
                assert status["runtime_module"] == _expected_runtime_module_for_requested_sqlcipher()
                assert status["provider_match"] is True
                assert status["driver_available"] is True
                assert status["driver_version"] == "4.5.6"
                assert status["has_key_material"] is True
                assert status["ready_for_sqlcipher"] is False
                assert status["migration_required"] is False
                assert await database.get_app_state(database.APP_STATE_DB_ENCRYPTION_MODE) == "sqlcipher"
                assert metadata["db_encryption_mode"] == "sqlcipher"
                assert backup_path.exists()
            finally:
                await database.close()

        asyncio.run(scenario())
        monkeypatch.setattr(database_module.Database, "_migrate_current_connection_to_sqlcipher", original_migrate)
    finally:
        for path in (db_path, backup_path, metadata_path):
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                pass
        shutil.rmtree(temp_root, ignore_errors=True)


def test_database_connect_rejects_sqlcipher_db_without_runtime_support(monkeypatch) -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-open-sqlcipher-without-driver.db"
    metadata_path = Path(f"{db_path}.crypto.json")
    try:
        db_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)

        fake_config = types.SimpleNamespace(
            storage=types.SimpleNamespace(
                db_path=str(db_path),
                db_encryption_mode="sqlcipher",
                db_encryption_provider="auto",
            )
        )
        monkeypatch.setattr(database_module, "get_config", lambda: fake_config)

        metadata_path.write_text(
            json.dumps(
                {
                    "db_encryption_mode": "sqlcipher",
                    "db_encryption_key": SecureStorage.encrypt_text("runtime-check-key"),
                    "db_encryption_key_id": database_module.Database._derive_db_key_id("runtime-check-key"),
                },
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )

        async def fake_detect(self, connection) -> tuple[bool, str, str]:
            return False, "", "sqlite-default"

        monkeypatch.setattr(database_module.Database, "_detect_sqlcipher_runtime_on_connection", fake_detect)

        async def scenario() -> None:
            database = database_module.Database()
            try:
                await database.connect()
                raise AssertionError("connect() should have failed without SQLCipher runtime support")
            except RuntimeError as exc:
                assert "requires SQLCipher runtime support" in str(exc)
            finally:
                await database.close()

        asyncio.run(scenario())
    finally:
        for path in (db_path, metadata_path):
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                pass
        shutil.rmtree(temp_root, ignore_errors=True)


def test_database_connect_rejects_sqlcipher_db_when_key_verification_fails(monkeypatch) -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-open-sqlcipher-invalid-key.db"
    metadata_path = Path(f"{db_path}.crypto.json")
    try:
        db_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)

        with sqlite3.connect(str(db_path)) as connection:
            connection.execute("CREATE TABLE sample (id TEXT PRIMARY KEY)")
            connection.commit()

        fake_config = types.SimpleNamespace(
            storage=types.SimpleNamespace(
                db_path=str(db_path),
                db_encryption_mode="sqlcipher",
                db_encryption_provider="auto",
            )
        )
        monkeypatch.setattr(database_module, "get_config", lambda: fake_config)

        metadata_path.write_text(
            json.dumps(
                {
                    "db_encryption_mode": "sqlcipher",
                    "db_encryption_key": SecureStorage.encrypt_text("verification-key"),
                    "db_encryption_key_id": database_module.Database._derive_db_key_id("verification-key"),
                },
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )

        async def fake_detect(self, connection) -> tuple[bool, str, str]:
            return True, "4.5.6", "sqlcipher-compatible"

        async def fake_verify(self, connection) -> None:
            raise RuntimeError("Failed to open SQLCipher database with the configured key")

        monkeypatch.setattr(database_module.Database, "_detect_sqlcipher_runtime_on_connection", fake_detect)
        monkeypatch.setattr(database_module.Database, "_verify_sqlcipher_connection", fake_verify)

        async def scenario() -> None:
            database = database_module.Database()
            try:
                await database.connect()
                raise AssertionError("connect() should have failed for one invalid SQLCipher key")
            except RuntimeError as exc:
                assert "configured key" in str(exc)
            finally:
                await database.close()

        asyncio.run(scenario())
    finally:
        for path in (db_path, metadata_path):
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                pass
        shutil.rmtree(temp_root, ignore_errors=True)


def test_database_connect_records_requested_sqlcipher_provider_mismatch(monkeypatch) -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-provider-mismatch.db"
    try:
        db_path.unlink(missing_ok=True)

        fake_config = types.SimpleNamespace(
            storage=types.SimpleNamespace(
                db_path=str(db_path),
                db_encryption_mode="sqlcipher",
                db_encryption_provider="sqlcipher-compatible",
            )
        )
        monkeypatch.setattr(database_module, "get_config", lambda: fake_config)

        async def fake_detect(self) -> tuple[bool, str, str]:
            return False, "", "sqlite-default"

        monkeypatch.setattr(database_module.Database, "_detect_sqlcipher_runtime", fake_detect)

        async def disable_auto_migrate(self) -> bool:
            return False

        monkeypatch.setattr(database_module.Database, "_auto_migrate_sqlcipher_if_needed", disable_auto_migrate)

        async def scenario() -> None:
            database = database_module.Database()
            try:
                await database.connect()
                raise AssertionError("connect() should have failed for one unavailable provider")
            except RuntimeError as exc:
                assert "Configured DB encryption provider" in str(exc)
                assert "sqlite-default" in str(exc)
            finally:
                await database.close()

        asyncio.run(scenario())
    finally:
        try:
            db_path.unlink(missing_ok=True)
        except PermissionError:
            pass
        shutil.rmtree(temp_root, ignore_errors=True)


def test_database_connect_uses_sqlcipher_provider_module_when_available(monkeypatch) -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-provider-module.db"
    try:
        db_path.unlink(missing_ok=True)

        fake_config = types.SimpleNamespace(
            storage=types.SimpleNamespace(
                db_path=str(db_path),
                db_encryption_mode="sqlcipher",
                db_encryption_provider="sqlcipher-compatible",
            )
        )
        monkeypatch.setattr(database_module, "get_config", lambda: fake_config)

        fake_sqlcipher_module = types.SimpleNamespace(
            __name__="sqlcipher3",
            connect=lambda path: sqlite3.connect(path),
        )

        def fake_import_module(name: str):
            if name == "sqlcipher3":
                return fake_sqlcipher_module
            raise ImportError(name)

        monkeypatch.setattr(database_module.importlib, "import_module", fake_import_module)

        async def fake_detect(self) -> tuple[bool, str, str]:
            return True, "4.5.6", "sqlcipher-compatible"

        async def fake_detect_on_connection(self, connection) -> tuple[bool, str, str]:
            return True, "4.5.6", "sqlcipher-compatible"

        monkeypatch.setattr(database_module.Database, "_detect_sqlcipher_runtime", fake_detect)
        monkeypatch.setattr(database_module.Database, "_detect_sqlcipher_runtime_on_connection", fake_detect_on_connection)

        async def disable_auto_migrate(self) -> bool:
            return False

        monkeypatch.setattr(database_module.Database, "_auto_migrate_sqlcipher_if_needed", disable_auto_migrate)

        async def scenario() -> None:
            database = database_module.Database()
            await database.connect()
            try:
                status = database.get_db_encryption_status()
                assert status["requested_provider"] == "sqlcipher-compatible"
                assert status["runtime_provider"] == "sqlcipher-compatible"
                assert status["runtime_module"] == _expected_runtime_module_for_requested_sqlcipher()
                assert status["driver_available"] is True
                assert status["install_hint"] == ""
            finally:
                await database.close()

        asyncio.run(scenario())
    finally:
        metadata_path = Path(f"{db_path}.crypto.json")
        for path in (db_path, metadata_path):
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                pass
        shutil.rmtree(temp_root, ignore_errors=True)


def test_database_self_check_reports_sqlcipher_active(monkeypatch) -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-self-check-active.db"
    try:
        db_path.unlink(missing_ok=True)

        fake_config = types.SimpleNamespace(
            storage=types.SimpleNamespace(
                db_path=str(db_path),
                db_encryption_mode="sqlcipher",
                db_encryption_provider="auto",
            )
        )
        monkeypatch.setattr(database_module, "get_config", lambda: fake_config)

        async def fake_detect(self) -> tuple[bool, str, str]:
            return True, "4.5.6", "sqlcipher-compatible"

        monkeypatch.setattr(database_module.Database, "_detect_sqlcipher_runtime", fake_detect)

        async def fake_migrate(self) -> None:
            metadata = self._load_db_crypto_metadata()
            metadata["db_encryption_mode"] = self.DB_ENCRYPTION_MODE_SQLCIPHER
            self._save_db_crypto_metadata(metadata)

        monkeypatch.setattr(database_module.Database, "_migrate_current_connection_to_sqlcipher", fake_migrate)

        async def scenario() -> None:
            database = database_module.Database()
            await database.connect()
            try:
                self_check = database.get_db_encryption_self_check()
                assert self_check["state"] == "sqlcipher_active"
                assert self_check["severity"] == "ok"
                assert self_check["can_start"] is True
                assert self_check["action_required"] is False
                if database.get_db_encryption_status()["fts_available"]:
                    assert self_check["search_mode"].startswith("fts5_")
                    assert "FTS5" in self_check["search_message"]
                else:
                    assert self_check["search_mode"] == "like_fallback"
                    assert "LIKE" in self_check["search_message"]
            finally:
                await database.close()

        asyncio.run(scenario())
    finally:
        metadata_path = Path(f"{db_path}.crypto.json")
        for path in (db_path, metadata_path):
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                pass
        shutil.rmtree(temp_root, ignore_errors=True)


def test_database_persists_encrypted_message_ciphertext_and_searches_versioned_local_plaintext() -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-encrypted-message.db"
    try:
        db_path.unlink(missing_ok=True)

        async def scenario() -> None:
            database = Database(str(db_path))
            await database.connect()
            try:
                await database.save_session(
                    Session(
                        session_id="session-direct-1",
                        name="Bob",
                        session_type="direct",
                        participant_ids=["alice", "bob"],
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    )
                )

                plaintext = "classified roadmap"
                ciphertext = "Y2lwaGVydGV4dC0x"
                message = ChatMessage(
                    message_id="m-e2ee-1",
                    session_id="session-direct-1",
                    sender_id="alice",
                    content=plaintext,
                    message_type=MessageType.TEXT,
                    status=MessageStatus.SENT,
                    timestamp=datetime.now(),
                    updated_at=datetime.now(),
                    is_self=True,
                    extra={
                        "session_type": "direct",
                        "encryption": {
                            "enabled": True,
                            "scheme": "x25519-aesgcm-v1",
                            "content_ciphertext": ciphertext,
                            "local_plaintext": SecureStorage.encrypt_text(plaintext),
                            "local_plaintext_version": "dpapi-text-v1",
                        },
                    },
                )
                await database.save_message(message)

                loaded = await database.get_message("m-e2ee-1")
                search_results = await database.search_messages("classified", session_id="session-direct-1", limit=10)
                search_count = await database.count_search_message_sessions("classified", session_id="session-direct-1")

                assert loaded is not None
                assert loaded.content == plaintext
                assert [item.message_id for item in search_results] == ["m-e2ee-1"]
                assert search_count == 1
            finally:
                await database.close()

        asyncio.run(scenario())

        with sqlite3.connect(str(db_path)) as connection:
            stored_row = connection.execute(
                "SELECT content, is_encrypted, encryption_scheme FROM messages WHERE message_id = ?",
                ("m-e2ee-1",),
            ).fetchone()

        assert stored_row[0] == "Y2lwaGVydGV4dC0x"
        assert stored_row[1] == 1
        assert stored_row[2] == "x25519-aesgcm-v1"
    finally:
        try:
            db_path.unlink(missing_ok=True)
        except PermissionError:
            pass
        shutil.rmtree(temp_root, ignore_errors=True)


def test_database_marks_encrypted_attachments_and_searches_versioned_local_metadata() -> None:
    temp_root = (Path.cwd() / "client/tests/.pytest_tmp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "database-encrypted-attachment.db"
    try:
        db_path.unlink(missing_ok=True)

        async def scenario() -> None:
            database = Database(str(db_path))
            await database.connect()
            try:
                await database.save_session(
                    Session(
                        session_id="session-group-1",
                        name="Core Team",
                        session_type="group",
                        participant_ids=["alice", "bob", "charlie"],
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    )
                )

                message = ChatMessage(
                    message_id="m-e2ee-file-1",
                    session_id="session-group-1",
                    sender_id="alice",
                    content="https://cdn.example/files/group-secret.bin",
                    message_type=MessageType.FILE,
                    status=MessageStatus.SENT,
                    timestamp=datetime.now(),
                    updated_at=datetime.now(),
                    is_self=True,
                    extra={
                        "session_type": "group",
                        "attachment_encryption": {
                            "enabled": True,
                            "scheme": "aesgcm-file+group-sender-key-v1",
                            "sender_device_id": "device-alice",
                            "sender_key_id": "group-key-1",
                            "encrypted_size_bytes": 2048,
                            "local_metadata": SecureStorage.encrypt_text('{"name":"secret.pdf"}'),
                            "local_plaintext_version": "dpapi-text-v1",
                        },
                    },
                )
                await database.save_message(message)

                url_results = await database.search_messages("cdn.example", session_id="session-group-1", limit=10)
                metadata_results = await database.search_messages("secret.pdf", session_id="session-group-1", limit=10)
                metadata_count = await database.count_search_message_sessions("secret.pdf", session_id="session-group-1")
                assert url_results == []
                assert [item.message_id for item in metadata_results] == ["m-e2ee-file-1"]
                assert metadata_count == 1
            finally:
                await database.close()

        asyncio.run(scenario())

        with sqlite3.connect(str(db_path)) as connection:
            stored_row = connection.execute(
                "SELECT content, is_encrypted, encryption_scheme FROM messages WHERE message_id = ?",
                ("m-e2ee-file-1",),
            ).fetchone()

        assert stored_row[0] == "https://cdn.example/files/group-secret.bin"
        assert stored_row[1] == 1
        assert stored_row[2] == "aesgcm-file+group-sender-key-v1"
    finally:
        try:
            db_path.unlink(missing_ok=True)
        except PermissionError:
            pass
        shutil.rmtree(temp_root, ignore_errors=True)
