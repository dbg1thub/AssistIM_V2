import asyncio

from client.models.ai_assistant import AIMessageRole, AIMessageStatus
from client.storage.database import Database
import client.storage.ai_assistant_store as store_module


def test_ai_assistant_store_thread_message_lifecycle(tmp_path, monkeypatch):
    async def run():
        db = Database(str(tmp_path / "assistant.db"))
        monkeypatch.setattr(store_module, "get_database", lambda: db)
        store = store_module.AIAssistantStore(owner_user_id="user-a")
        try:
            thread = await store.create_thread(title="New Chat", model="gemma")
            assert thread.thread_id

            user = await store.create_message(
                thread_id=thread.thread_id,
                role=AIMessageRole.USER,
                content="你好",
            )
            assistant = await store.create_message(
                thread_id=thread.thread_id,
                role=AIMessageRole.ASSISTANT,
                content="你好，有什么可以帮你？",
                status=AIMessageStatus.DONE,
            )

            messages = await store.list_messages(thread.thread_id)
            assert [message.message_id for message in messages] == [user.message_id, assistant.message_id]

            await store.update_message(assistant, content="已更新", status=AIMessageStatus.CANCELLED)
            updated_messages = await store.list_messages(thread.thread_id)
            assert updated_messages[-1].content == "已更新"
            assert updated_messages[-1].status == AIMessageStatus.CANCELLED

            await store.maybe_title_from_first_user_message(thread.thread_id, "这是一个很长的问题标题")
            updated_thread = await store.get_thread(thread.thread_id)
            assert updated_thread is not None
            assert updated_thread.title.startswith("这是一个")

            await store.clear_thread_messages(thread.thread_id)
            assert await store.list_messages(thread.thread_id) == []

            await store.delete_thread(thread.thread_id)
            assert await store.get_thread(thread.thread_id) is None
        finally:
            await db.close()

    asyncio.run(run())


def test_ai_assistant_store_preview_and_restart_recovery(tmp_path, monkeypatch):
    async def run():
        db = Database(str(tmp_path / "assistant.db"))
        monkeypatch.setattr(store_module, "get_database", lambda: db)
        store = store_module.AIAssistantStore(owner_user_id="user-a")
        try:
            thread = await store.create_thread(title="New Chat", model="gemma")
            await store.create_message(
                thread_id=thread.thread_id,
                role=AIMessageRole.ASSISTANT,
                content="",
                status=AIMessageStatus.STREAMING,
            )

            streaming_thread = await store.get_thread(thread.thread_id)
            assert streaming_thread is not None
            assert streaming_thread.last_message == store_module.tr(
                "ai_assistant.preview.generating",
                "正在生成...",
            )

            recovered_store = store_module.AIAssistantStore(owner_user_id="user-a")
            await recovered_store.initialize()
            recovered_messages = await recovered_store.list_messages(thread.thread_id)
            assert len(recovered_messages) == 1
            assert recovered_messages[0].status == AIMessageStatus.CANCELLED
            assert recovered_messages[0].content == store_module.tr(
                "ai_assistant.message.cancelled",
                "已停止生成。",
            )

            recovered_thread = await recovered_store.get_thread(thread.thread_id)
            assert recovered_thread is not None
            assert recovered_thread.last_message == store_module.tr(
                "ai_assistant.preview.cancelled",
                "已停止生成",
            )
        finally:
            await db.close()

    asyncio.run(run())


def test_ai_assistant_store_manual_title_blocks_auto_title(tmp_path, monkeypatch):
    async def run():
        db = Database(str(tmp_path / "assistant.db"))
        monkeypatch.setattr(store_module, "get_database", lambda: db)
        store = store_module.AIAssistantStore(owner_user_id="user-a")
        try:
            thread = await store.create_thread(title="New Chat", model="gemma")
            renamed = await store.update_thread_title(thread.thread_id, "手动标题")
            assert renamed is not None
            assert renamed.title == "手动标题"

            unchanged = await store.maybe_title_from_first_user_message(thread.thread_id, "这是一段新的首条消息标题")
            assert unchanged is not None
            assert unchanged.title == "手动标题"
        finally:
            await db.close()

    asyncio.run(run())


def test_ai_assistant_store_empty_thread_detection_uses_messages_not_title(tmp_path, monkeypatch):
    async def run():
        db = Database(str(tmp_path / "assistant.db"))
        monkeypatch.setattr(store_module, "get_database", lambda: db)
        store = store_module.AIAssistantStore(owner_user_id="user-a")
        try:
            thread = await store.create_thread(title="新聊天", model="gemma")
            assert await store.thread_has_messages(thread.thread_id) is False
            empty_thread = await store.find_empty_thread()
            assert empty_thread is not None
            assert empty_thread.thread_id == thread.thread_id

            await store.create_message(
                thread_id=thread.thread_id,
                role=AIMessageRole.USER,
                content="新聊天",
            )
            assert await store.thread_has_messages(thread.thread_id) is True
            assert await store.find_empty_thread() is None

            renamed_empty = await store.create_thread(title="手动标题", model="gemma")
            empty_thread = await store.find_empty_thread()
            assert empty_thread is not None
            assert empty_thread.thread_id == renamed_empty.thread_id
        finally:
            await db.close()

    asyncio.run(run())


def test_ai_assistant_store_is_scoped_by_owner_user_id(tmp_path, monkeypatch):
    async def run():
        db = Database(str(tmp_path / "assistant.db"))
        monkeypatch.setattr(store_module, "get_database", lambda: db)
        owner_a_store = store_module.AIAssistantStore(owner_user_id="user-a")
        owner_b_store = store_module.AIAssistantStore(owner_user_id="user-b")
        try:
            owner_a_thread = await owner_a_store.create_thread(title="A thread", model="gemma")
            owner_a_message = await owner_a_store.create_message(
                thread_id=owner_a_thread.thread_id,
                role=AIMessageRole.USER,
                content="A private prompt",
            )

            owner_b_thread = await owner_b_store.create_thread(title="B thread", model="gemma")
            await owner_b_store.create_message(
                thread_id=owner_b_thread.thread_id,
                role=AIMessageRole.USER,
                content="B private prompt",
            )

            assert [thread.thread_id for thread in await owner_a_store.list_threads()] == [owner_a_thread.thread_id]
            assert [thread.thread_id for thread in await owner_b_store.list_threads()] == [owner_b_thread.thread_id]
            assert await owner_b_store.get_thread(owner_a_thread.thread_id) is None
            assert await owner_b_store.list_messages(owner_a_thread.thread_id) == []

            await owner_b_store.delete_message(owner_a_message.message_id)
            assert [message.message_id for message in await owner_a_store.list_messages(owner_a_thread.thread_id)] == [
                owner_a_message.message_id
            ]

            await owner_b_store.delete_thread(owner_a_thread.thread_id)
            assert await owner_a_store.get_thread(owner_a_thread.thread_id) is not None
        finally:
            await db.close()

    asyncio.run(run())


def test_ai_assistant_store_hides_legacy_unowned_threads(tmp_path, monkeypatch):
    async def run():
        db = Database(str(tmp_path / "assistant.db"))
        monkeypatch.setattr(store_module, "get_database", lambda: db)
        store = store_module.AIAssistantStore(owner_user_id="user-a")
        try:
            await store.initialize()
            connection = store._connection()
            await connection.execute(
                """
                INSERT INTO ai_threads
                (thread_id, owner_user_id, title, model, last_message, last_message_time, status, extra, created_at, updated_at)
                VALUES ('legacy-thread', '', 'Legacy', '', '', 1, 'active', '{}', 1, 1)
                """
            )
            await connection.execute(
                """
                INSERT INTO ai_messages
                (message_id, thread_id, owner_user_id, role, content, status, task_id, model, extra, created_at, updated_at)
                VALUES ('legacy-message', 'legacy-thread', '', 'user', 'legacy prompt', 'done', '', '', '{}', 1, 1)
                """
            )
            await connection.commit()

            assert await store.list_threads() == []
            assert await store.get_thread("legacy-thread") is None
            assert await store.list_messages("legacy-thread") == []
        finally:
            await db.close()

    asyncio.run(run())


def test_ai_assistant_store_migrates_existing_unowned_schema(tmp_path, monkeypatch):
    async def run():
        db = Database(str(tmp_path / "assistant.db"))
        monkeypatch.setattr(store_module, "get_database", lambda: db)
        try:
            await db.connect()
            connection = getattr(db, "_db")
            await connection.executescript(
                """
                CREATE TABLE ai_threads (
                    thread_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    last_message TEXT NOT NULL DEFAULT '',
                    last_message_time INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    extra TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE ai_messages (
                    message_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'done',
                    task_id TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    extra TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                """
            )
            await connection.commit()

            store = store_module.AIAssistantStore(owner_user_id="user-a")
            await store.initialize()

            thread_columns = {str(row["name"]) for row in await (await connection.execute("PRAGMA table_info(ai_threads)")).fetchall()}
            message_columns = {str(row["name"]) for row in await (await connection.execute("PRAGMA table_info(ai_messages)")).fetchall()}
            assert "owner_user_id" in thread_columns
            assert "owner_user_id" in message_columns

            thread = await store.create_thread(title="Migrated", model="gemma")
            assert await store.get_thread(thread.thread_id) is not None
        finally:
            await db.close()

    asyncio.run(run())
