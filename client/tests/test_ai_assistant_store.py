import asyncio

from client.models.ai_assistant import AIMessageRole, AIMessageStatus
from client.storage.database import Database
import client.storage.ai_assistant_store as store_module


def test_ai_assistant_store_thread_message_lifecycle(tmp_path, monkeypatch):
    async def run():
        db = Database(str(tmp_path / "assistant.db"))
        monkeypatch.setattr(store_module, "get_database", lambda: db)
        store = store_module.AIAssistantStore()
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
        store = store_module.AIAssistantStore()
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

            recovered_store = store_module.AIAssistantStore()
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
        store = store_module.AIAssistantStore()
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
