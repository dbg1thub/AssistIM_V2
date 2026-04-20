import asyncio
from datetime import datetime

from client.managers.conversation_memory_manager import ConversationMemoryManager
from client.models.ai_assistant import AIMessage, AIMessageRole


class _FakeMemoryDatabase:
    def __init__(self, items: list[dict]) -> None:
        self.items = list(items)
        self.calls: list[dict] = []

    async def list_conversation_memory_items(self, **kwargs):
        self.calls.append(dict(kwargs))
        items = list(self.items)
        return items[: int(kwargs.get("limit") or 12)]


def _ts(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp())


def test_conversation_memory_manager_skips_regular_chat() -> None:
    async def scenario() -> None:
        db = _FakeMemoryDatabase([])
        manager = ConversationMemoryManager(db=db)

        context = await manager.build_ai_chat_memory_context("帮我写一段介绍")
        dated_context = await manager.build_ai_chat_memory_context("今天帮我写一段介绍")

        assert context.lines == ()
        assert dated_context.lines == ()
        assert db.calls == []

    asyncio.run(scenario())


def test_conversation_memory_manager_formats_history_context() -> None:
    async def scenario() -> None:
        db = _FakeMemoryDatabase(
            [
                {
                    "session_id": "s1",
                    "source_type": "summary",
                    "source_id": "summary:1",
                    "start_ts": _ts("2026-04-21T10:00:00"),
                    "end_ts": _ts("2026-04-21T10:05:00"),
                    "title": "张三 2026-04-21 10:00-10:05",
                    "text": "确认了周末去咖啡店见面，语气轻松。",
                    "keywords": ["周末", "咖啡店"],
                    "participants": ["张三", "我"],
                },
                {
                    "session_id": "s2",
                    "source_type": "summary",
                    "source_id": "summary:2",
                    "start_ts": _ts("2026-04-21T11:00:00"),
                    "end_ts": _ts("2026-04-21T11:05:00"),
                    "title": "李四 2026-04-21 11:00-11:05",
                    "text": "讨论了文件整理。",
                    "keywords": ["文件"],
                    "participants": ["李四"],
                },
            ]
        )
        manager = ConversationMemoryManager(db=db)

        context = await manager.build_ai_chat_memory_context("今天我和张三聊了什么？")

        assert context.has_context is True
        assert len(context.lines) == 1
        assert "张三" in context.lines[0]
        assert "咖啡店" in context.lines[0]
        assert db.calls[0]["source_type"] == "summary"
        assert db.calls[0]["start_ts"] is not None
        assert db.calls[0]["end_ts"] is not None

    asyncio.run(scenario())


def test_conversation_memory_manager_requires_confirmation_for_ambiguous_history_request() -> None:
    async def scenario() -> None:
        db = _FakeMemoryDatabase([])
        manager = ConversationMemoryManager(db=db)

        context = await manager.build_ai_chat_memory_context("帮我看看聊天记录")

        assert context.requires_confirmation is True
        assert context.lines == ()
        assert "确认" in context.confirmation_prompt
        assert context.pending_query_text == "帮我看看聊天记录"
        assert db.calls == []

    asyncio.run(scenario())


def test_conversation_memory_manager_searches_after_explicit_confirmation() -> None:
    async def scenario() -> None:
        db = _FakeMemoryDatabase(
            [
                {
                    "session_id": "s1",
                    "source_type": "summary",
                    "source_id": "summary:1",
                    "start_ts": _ts("2026-04-21T10:00:00"),
                    "end_ts": _ts("2026-04-21T10:05:00"),
                    "title": "张三 2026-04-21 10:00-10:05",
                    "text": "确认了周末去咖啡店见面，语气轻松。",
                    "keywords": ["周末", "咖啡店"],
                    "participants": ["张三", "我"],
                },
            ]
        )
        manager = ConversationMemoryManager(db=db)
        previous_messages = [
            AIMessage(
                "a1",
                "thread-1",
                AIMessageRole.ASSISTANT,
                "你是想让我查询本机聊天记录来回答这个问题吗？",
                extra={"memory_confirmation": {"query": "帮我看看聊天记录"}},
            )
        ]

        context = await manager.build_ai_chat_memory_context("确认", previous_messages=previous_messages)

        assert context.requires_confirmation is False
        assert context.has_context is True
        assert "咖啡店" in context.lines[0]
        assert db.calls[0]["source_type"] == "summary"

    asyncio.run(scenario())
