import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from client.managers.conversation_memory_manager import ConversationMemoryManager
from client.managers.conversation_vector_index import DenseVector
from client.models.ai_assistant import AIMessage, AIMessageRole
from client.services.local_ai_memory_store import AIMemoryItem, AIMemorySearchResult
from client.storage.database import Database


class _FakeMemoryDatabase:
    def __init__(
        self,
        items: list[dict],
        *,
        sessions: list[object] | None = None,
        messages_by_session: dict[str, list[object]] | None = None,
        search_results: dict[str, list[object]] | None = None,
    ) -> None:
        self.items = list(items)
        self.calls: list[dict] = []
        self.ann_calls: list[dict] = []
        self.sessions = list(sessions or [])
        self.messages_by_session = dict(messages_by_session or {})
        self.search_results = dict(search_results or {})
        self.app_state = {Database.AUTH_USER_ID_STATE_KEY: "test1"}

    async def list_conversation_memory_items(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self._normalized_items()[: int(kwargs.get("limit") or 12)]

    async def list_conversation_memory_ann_candidates(self, **kwargs):
        self.ann_calls.append(dict(kwargs))
        return self._normalized_items()[: int(kwargs.get("limit") or 12)]

    def _normalized_items(self) -> list[dict]:
        items = []
        for raw_item in list(self.items):
            item = dict(raw_item)
            if not item.get("embedding_vector"):
                tokens = _FakeVectorIndex._tokens(
                    [
                        str(item.get("title") or ""),
                        str(item.get("text") or ""),
                        *[str(value or "") for value in list(item.get("keywords") or [])],
                        *[str(value or "") for value in list(item.get("participants") or [])],
                    ]
                )
                item["embedding_vector"] = _FakeVectorIndex._vector(tokens)
                item["embedding_dim"] = len(item["embedding_vector"])
                item["embedding_model"] = "fake-embedding-model"
                item["embedding_id"] = item.get("embedding_id") or f"{item.get('session_id','')}|{item.get('source_id','')}"
                item["embedding_content_hash"] = item.get("embedding_content_hash") or "|".join(sorted(tokens))
            items.append(item)
        return items

    async def get_all_sessions(self):
        return list(self.sessions)

    async def get_messages(self, session_id: str, limit: int = 50, before_timestamp=None):
        del before_timestamp
        return list(self.messages_by_session.get(session_id, []))[:limit]

    async def search_messages(self, keyword: str, session_id=None, limit: int = 100):
        del session_id
        return list(self.search_results.get(keyword, []))[:limit]

    async def resolve_contacts_cache_alias(self, alias: str, limit: int = 20, **kwargs):
        del kwargs
        matches: list[dict] = []
        normalized = str(alias or "").strip().casefold()
        for item in list(self.search_results.get("__contacts__", [])):
            values = {
                str(item.get("id") or "").strip().casefold(),
                str(item.get("username") or "").strip().casefold(),
                str(item.get("nickname") or "").strip().casefold(),
                str(item.get("remark") or "").strip().casefold(),
                str(item.get("display_name") or "").strip().casefold(),
                str(item.get("assistim_id") or "").strip().casefold(),
            }
            if normalized and normalized in values:
                matches.append(dict(item))
        return matches[:limit]

    async def get_app_state(self, key: str):
        return self.app_state.get(str(key or ""))


class _FakeVectorIndex:
    model_id = "fake-embedding-model"

    async def encode_query(self, *, query: str, terms=(), contact_aliases=()):
        tokens = self._tokens([query, *list(terms or []), *list(contact_aliases or [])])
        return DenseVector(values=tuple(self._vector(tokens)))

    @staticmethod
    def _tokens(values: list[str]) -> set[str]:
        joined = " ".join(str(value or "").casefold() for value in values if str(value or "").strip())
        replacements = {
            "咖啡馆": "咖啡店",
            "店铺": "店",
        }
        for source, target in replacements.items():
            joined = joined.replace(source, target)
        return {token for token in joined.replace("，", " ").replace("。", " ").replace("：", " ").split() if token}

    @staticmethod
    def _vector(tokens: set[str], dim: int = 16) -> list[float]:
        vector = [0.0] * dim
        for token in tokens:
            vector[sum(ord(ch) for ch in token) % dim] += 1.0
        return vector


class _FakeSemanticPlanner:
    def __init__(self, result):
        self.result = result
        self.calls: list[dict] = []

    async def plan(self, query_text: str, *, previous_messages=None):
        self.calls.append(
            {
                "query_text": query_text,
                "previous_messages": list(previous_messages or []),
            }
        )
        return self.result

    async def search_contacts(self, keyword: str, limit: int = 50, **kwargs):
        del kwargs
        matches: list[dict] = []
        normalized = str(keyword or "").strip().casefold()
        for item in list(self.search_results.get("__contacts__", [])):
            blob = " ".join(
                str(item.get(key) or "").strip().casefold()
                for key in ("id", "username", "nickname", "remark", "display_name", "assistim_id")
            )
            if normalized and normalized in blob:
                matches.append(dict(item))
        return matches[:limit]


class _FakeAIMemoryStore:
    def __init__(self, items: list[AIMemoryItem] | None = None) -> None:
        self.items = list(items or [])
        self.search_calls: list[dict] = []

    @classmethod
    def from_db(cls, db: _FakeMemoryDatabase) -> "_FakeAIMemoryStore":
        return cls([_ai_memory_item_from_summary(item) for item in db._normalized_items()])

    async def search(
        self,
        *,
        query_vector,
        owner_scope: str,
        embedding_model_id: str,
        source_types=(),
        limit: int = 8,
        min_score: float = 0.0,
    ):
        call = {
            "owner_scope": owner_scope,
            "embedding_model_id": embedding_model_id,
            "source_types": tuple(source_types or ()),
            "limit": limit,
            "min_score": min_score,
        }
        self.search_calls.append(call)
        query = DenseVector(values=tuple(float(value) for value in tuple(query_vector or ())))
        normalized_types = {str(value or "").strip() for value in list(source_types or ()) if str(value or "").strip()}
        results: list[AIMemorySearchResult] = []
        for item in self.items:
            if item.owner_scope != owner_scope:
                continue
            if embedding_model_id and item.embedding_model_id != embedding_model_id:
                continue
            if normalized_types and item.source_type not in normalized_types:
                continue
            score = query.cosine(DenseVector(values=item.vector)) if query.values else 0.0
            if score < float(min_score):
                continue
            results.append(AIMemorySearchResult(item=item, score=score))
        results.sort(key=lambda result: (result.score, int(result.item.metadata.get("bucket_end_ts") or 0)), reverse=True)
        return results[: int(limit or 8)]


def _ai_memory_item_from_summary(item: dict) -> AIMemoryItem:
    session_id = str(item.get("session_id") or "")
    source_id = str(item.get("source_id") or "")
    return AIMemoryItem(
        owner_scope="account:test1",
        source_type="conversation_summary",
        source_id=f"conversation:{session_id}:{source_id}",
        title=str(item.get("title") or ""),
        text=str(item.get("text") or ""),
        vector=tuple(float(value) for value in list(item.get("embedding_vector") or [])),
        embedding_model_id=str(item.get("embedding_model") or "fake-embedding-model"),
        metadata={
            "session_id": session_id,
            "legacy_source_type": "summary",
            "legacy_source_id": source_id,
            "source_version": int(item.get("source_version") or 1),
            "bucket_start_ts": int(item.get("start_ts") or 0),
            "bucket_end_ts": int(item.get("end_ts") or 0),
            "keywords": list(item.get("keywords") or []),
            "participants": list(item.get("participants") or []),
        },
    )


def _make_memory_manager(
    db: _FakeMemoryDatabase,
    planner: _FakeSemanticPlanner,
    *,
    ai_memory_store: _FakeAIMemoryStore | None = None,
) -> ConversationMemoryManager:
    store = ai_memory_store or _FakeAIMemoryStore.from_db(db)
    db.ai_memory_store = store
    return ConversationMemoryManager(
        db=db,
        semantic_planner=planner,
        vector_index=_FakeVectorIndex(),
        ai_memory_store=store,
    )


@dataclass
class _FakeSession:
    session_id: str
    name: str
    session_type: str = "direct"
    participant_ids: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    last_message_time: datetime | None = None

    def display_name(self) -> str:
        return self.name


@dataclass
class _FakeMessage:
    content: str
    timestamp: datetime
    sender_id: str
    is_self: bool = False
    extra: dict = field(default_factory=dict)


def _ts(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp())


def _rag_plan(
    query: str,
    *,
    participants: list[str] | None = None,
    relation: str = "separate",
    start_ts: int | None = None,
    end_ts: int | None = None,
) -> dict:
    return {
        "needs_memory": True,
        "user_goal": query,
        "memory_query": query,
        "participants": [
            {"mention": mention, "role": "contact"}
            for mention in list(participants or [])
        ],
        "participant_relation": relation,
        "time_range": {
            "type": "absolute" if start_ts is not None or end_ts is not None else "all_history",
            "start_ts": start_ts,
            "end_ts": end_ts,
            "label": "全部历史" if start_ts is None and end_ts is None else "指定时间",
        },
        "answer_style": "summary",
        "query_kind": "rag",
    }


def _contact(
    contact_id: str,
    display_name: str,
    *,
    username: str = "",
    remark: str = "",
) -> dict:
    return {
        "id": contact_id,
        "username": username,
        "nickname": display_name,
        "remark": remark,
        "display_name": display_name,
        "assistim_id": username or contact_id,
    }


def test_conversation_memory_manager_skips_regular_chat() -> None:
    async def scenario() -> None:
        db = _FakeMemoryDatabase([])
        planner = _FakeSemanticPlanner({"use_rag": False})
        manager = _make_memory_manager(db, planner)

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
        planner = _FakeSemanticPlanner({"use_rag": False})
        manager = _make_memory_manager(db, planner)

        context = await manager.build_ai_chat_memory_context("我和张三聊了什么？")

        assert context.has_context is True
        assert len(context.lines) == 1
        assert "张三" in context.lines[0]
        assert "咖啡店" in context.lines[0]
        assert db.calls == []
        assert db.ai_memory_store.search_calls[0]["source_types"] == ("conversation_summary",)
        assert db.ai_memory_store.search_calls[0]["owner_scope"] == "account:test1"

    asyncio.run(scenario())


def test_conversation_memory_manager_requires_confirmation_for_ambiguous_history_request() -> None:
    async def scenario() -> None:
        db = _FakeMemoryDatabase([])
        planner = _FakeSemanticPlanner({"use_rag": False})
        manager = _make_memory_manager(db, planner)

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
        planner = _FakeSemanticPlanner({"use_rag": False})
        manager = _make_memory_manager(db, planner)
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
        assert db.calls == []
        assert db.ai_memory_store.search_calls[0]["source_types"] == ("conversation_summary",)

    asyncio.run(scenario())


def test_conversation_memory_manager_builds_rag_context_for_general_ai_chat() -> None:
    async def scenario() -> None:
        db = _FakeMemoryDatabase(
            [
                {
                    "session_id": "s1",
                    "source_type": "summary",
                    "source_id": "summary:1",
                    "start_ts": _ts("2026-04-18T10:00:00"),
                    "end_ts": _ts("2026-04-18T10:05:00"),
                    "title": "张三 2026-04-18 10:00-10:05",
                    "text": "张三提到周末可以去南山咖啡店，下午人少一些。",
                    "keywords": ["周末", "南山咖啡店"],
                    "participants": ["张三", "我"],
                },
                {
                    "session_id": "s2",
                    "source_type": "summary",
                    "source_id": "summary:2",
                    "start_ts": _ts("2026-04-17T09:00:00"),
                    "end_ts": _ts("2026-04-17T09:05:00"),
                    "title": "李四 2026-04-17 09:00-09:05",
                    "text": "讨论了项目排期。",
                    "keywords": ["项目"],
                    "participants": ["李四"],
                },
            ],
            search_results={"__contacts__": [_contact("user-zhangsan", "张三")]},
        )
        planner = _FakeSemanticPlanner(_rag_plan("张三上次提到的咖啡店是哪家", participants=["张三"]))
        manager = _make_memory_manager(db, planner)

        context = await manager.build_rag_context_for_ai_chat("张三上次提到的咖啡店是哪家？")

        assert context.has_context is True
        assert len(context.lines) == 1
        assert "张三" in context.lines[0]
        assert "咖啡店" in context.lines[0]
        assert db.ann_calls == []
        assert db.ai_memory_store.search_calls[0]["source_types"] == ("conversation_summary",)
        assert db.ai_memory_store.search_calls[0]["embedding_model_id"] == "fake-embedding-model"

    asyncio.run(scenario())


def test_conversation_memory_manager_builds_reply_suggestion_rag_context_for_current_session() -> None:
    async def scenario() -> None:
        db = _FakeMemoryDatabase(
            [
                {
                    "session_id": "s1",
                    "source_type": "summary",
                    "source_id": "summary:old",
                    "start_ts": _ts("2026-04-12T18:30:00"),
                    "end_ts": _ts("2026-04-12T18:35:00"),
                    "title": "Alice 2026-04-12 18:30-18:35",
                    "text": "之前确认那家店周日人会少一点。",
                    "keywords": ["周日", "那家店"],
                    "participants": ["Alice", "我"],
                    "ann_match_count": 4,
                },
                {
                    "session_id": "s1",
                    "source_type": "summary",
                    "source_id": "summary:recent",
                    "start_ts": _ts("2026-04-15T18:55:00"),
                    "end_ts": _ts("2026-04-15T19:00:00"),
                    "title": "Alice 2026-04-15 18:55-19:00",
                    "text": "当前窗口内已经直接出现的内容。",
                    "keywords": ["周日", "那家店"],
                    "participants": ["Alice", "我"],
                    "ann_match_count": 4,
                },
                {
                    "session_id": "s2",
                    "source_type": "summary",
                    "source_id": "summary:other",
                    "start_ts": _ts("2026-04-12T18:30:00"),
                    "end_ts": _ts("2026-04-12T18:35:00"),
                    "title": "Bob 2026-04-12 18:30-18:35",
                    "text": "另一个会话也提到了周日和那家店。",
                    "keywords": ["周日", "那家店"],
                    "participants": ["Bob"],
                    "ann_match_count": 4,
                },
            ]
        )
        planner = _FakeSemanticPlanner({"use_rag": False})
        manager = _make_memory_manager(db, planner)

        context = await manager.build_reply_suggestion_rag_context(
            "s1",
            "对方问周日去那家店吗",
            max_end_ts=_ts("2026-04-15T18:00:00"),
            result_limit=2,
        )

        assert context.has_context is True
        assert len(context.lines) == 1
        assert "之前确认那家店周日人会少一点" in context.lines[0]
        assert "当前窗口内" not in context.lines[0]
        assert "另一个会话" not in context.lines[0]
        assert db.ann_calls == []
        assert db.ai_memory_store.search_calls[0]["source_types"] == ("conversation_summary",)
        assert db.ai_memory_store.search_calls[0]["owner_scope"] == "account:test1"

    asyncio.run(scenario())


def test_conversation_memory_manager_inspects_ann_retrieval_for_ai_chat() -> None:
    async def scenario() -> None:
        db = _FakeMemoryDatabase(
            [
                {
                    "session_id": "s1",
                    "source_type": "summary",
                    "source_id": "summary:1",
                    "start_ts": _ts("2026-04-18T10:00:00"),
                    "end_ts": _ts("2026-04-18T10:05:00"),
                    "title": "张三 2026-04-18 10:00-10:05",
                    "text": "张三提到周末可以去南山咖啡店，下午人少一些。",
                    "keywords": ["周末", "南山咖啡店"],
                    "participants": ["张三", "我"],
                    "ann_match_count": 3,
                },
            ],
            search_results={"__contacts__": [_contact("user-zhangsan", "张三")]},
        )
        planner = _FakeSemanticPlanner(_rag_plan("张三上次提到的咖啡店是哪家", participants=["张三"]))
        manager = _make_memory_manager(db, planner)

        debug = await manager.inspect_rag_retrieval_for_ai_chat("张三上次提到的咖啡店是哪家？")

        assert debug["use_rag"] is True
        assert debug["ann_namespace"] == ""
        assert debug["query_buckets"] == []
        assert debug["ann_candidate_count"] == 0
        assert debug["vector_store_candidate_count"] == 1
        assert debug["top_candidates"][0]["source_id"] == "summary:1"
        assert "咖啡店" in debug["context_lines"][0]

    asyncio.run(scenario())


def test_conversation_memory_manager_skips_rag_context_when_no_relevant_summary() -> None:
    async def scenario() -> None:
        db = _FakeMemoryDatabase(
            [
                {
                    "session_id": "s1",
                    "source_type": "summary",
                    "source_id": "summary:1",
                    "start_ts": _ts("2026-04-18T10:00:00"),
                    "end_ts": _ts("2026-04-18T10:05:00"),
                    "title": "张三 2026-04-18 10:00-10:05",
                    "text": "确认了周末去咖啡店见面。",
                    "keywords": ["周末", "咖啡店"],
                    "participants": ["张三", "我"],
                },
            ]
        )
        planner = _FakeSemanticPlanner({"use_rag": False})
        manager = _make_memory_manager(db, planner)

        context = await manager.build_rag_context_for_ai_chat("帮我写一段产品介绍")

        assert context.lines == ()
        assert db.calls == []

    asyncio.run(scenario())


def test_conversation_memory_manager_rag_reports_no_summary_without_raw_message_dump() -> None:
    async def scenario() -> None:
        session = _FakeSession(
            session_id="s1",
            name="张三",
            session_type="direct",
            participant_ids=["user-zhangsan"],
            extra={"counterpart_name": "张三", "counterpart_username": "test3"},
            last_message_time=datetime.fromisoformat("2026-04-18T10:06:00"),
        )
        message = _FakeMessage(
            content="周末可以去南山咖啡店，下午人会少一点。",
            timestamp=datetime.fromisoformat("2026-04-18T10:05:00"),
            sender_id="user-zhangsan",
            extra={"sender_name": "张三"},
        )
        db = _FakeMemoryDatabase(
            [],
            sessions=[session],
            messages_by_session={"s1": [message]},
        )
        planner = _FakeSemanticPlanner(_rag_plan("张三上次提到的咖啡店是哪家", participants=[]))
        manager = _make_memory_manager(db, planner)

        context = await manager.build_rag_context_for_ai_chat("张三上次提到的咖啡店是哪家？")

        assert context.has_context is True
        assert len(context.lines) == 1
        assert "未检索到匹配的聊天记忆" in context.lines[0]
        assert "南山咖啡店" not in context.lines[0]

    asyncio.run(scenario())


def test_conversation_memory_manager_expands_contact_alias_terms_for_rag() -> None:
    async def scenario() -> None:
        db = _FakeMemoryDatabase(
            [
                {
                    "session_id": "s1",
                    "source_type": "summary",
                    "source_id": "summary:1",
                    "start_ts": _ts("2026-04-18T10:00:00"),
                    "end_ts": _ts("2026-04-18T10:05:00"),
                    "title": "test3 2026-04-18 10:00-10:05",
                    "text": "test3提到周末可以去南山咖啡店。",
                    "keywords": ["周末", "南山咖啡店"],
                    "participants": ["test3", "我"],
                },
            ],
            search_results={
                "__contacts__": [
                    {
                        "id": "user-test3",
                        "username": "test3",
                        "nickname": "",
                        "remark": "小王",
                        "display_name": "test3",
                        "assistim_id": "test3",
                    }
                ]
            },
        )
        planner = _FakeSemanticPlanner(_rag_plan("小王上次提到的咖啡店是哪家", participants=["小王"]))
        manager = _make_memory_manager(db, planner)

        context = await manager.build_rag_context_for_ai_chat("小王上次提到的咖啡店是哪家？")

        assert context.has_context is True
        assert "咖啡店" in context.lines[0]
        assert "test3" in context.lines[0]

    asyncio.run(scenario())


def test_conversation_memory_manager_rag_handles_multiple_contacts_separately() -> None:
    async def scenario() -> None:
        db = _FakeMemoryDatabase(
            [
                {
                    "session_id": "s-test1",
                    "source_type": "summary",
                    "source_id": "summary:test1",
                    "start_ts": _ts("2026-04-18T10:00:00"),
                    "end_ts": _ts("2026-04-18T10:05:00"),
                    "title": "test1 2026-04-18 10:00-10:05",
                    "text": "test1 讨论了接口联调和明天继续排查。",
                    "keywords": ["接口联调"],
                    "participants": ["test1", "我"],
                },
                {
                    "session_id": "s-test3",
                    "source_type": "summary",
                    "source_id": "summary:test3",
                    "start_ts": _ts("2026-04-18T11:00:00"),
                    "end_ts": _ts("2026-04-18T11:05:00"),
                    "title": "test3 2026-04-18 11:00-11:05",
                    "text": "test3 讨论了周末去南山咖啡店。",
                    "keywords": ["南山咖啡店"],
                    "participants": ["test3", "我"],
                },
            ],
            search_results={
                "__contacts__": [
                    _contact("user-test1", "test1", username="test1"),
                    _contact("user-test3", "test3", username="test3"),
                ]
            },
        )
        planner = _FakeSemanticPlanner(
            _rag_plan("我和 test1、test3 聊过什么", participants=["test1", "test3"], relation="separate")
        )
        manager = _make_memory_manager(db, planner)

        context = await manager.build_rag_context_for_ai_chat("我和 test1、test3 聊过什么？")

        assert context.requires_confirmation is False
        assert len(context.lines) == 2
        assert any("联系人：test1" in line and "接口联调" in line for line in context.lines)
        assert any("联系人：test3" in line and "南山咖啡店" in line for line in context.lines)

    asyncio.run(scenario())


def test_conversation_memory_manager_rag_handles_together_relation() -> None:
    async def scenario() -> None:
        db = _FakeMemoryDatabase(
            [
                {
                    "session_id": "s-group",
                    "source_type": "summary",
                    "source_id": "summary:group",
                    "start_ts": _ts("2026-04-18T10:00:00"),
                    "end_ts": _ts("2026-04-18T10:05:00"),
                    "title": "项目群 2026-04-18 10:00-10:05",
                    "text": "test1 和 test3 一起讨论了项目验收。",
                    "keywords": ["项目验收"],
                    "participants": ["test1", "test3", "我"],
                },
                {
                    "session_id": "s-test1",
                    "source_type": "summary",
                    "source_id": "summary:test1",
                    "start_ts": _ts("2026-04-18T11:00:00"),
                    "end_ts": _ts("2026-04-18T11:05:00"),
                    "title": "test1 2026-04-18 11:00-11:05",
                    "text": "test1 单独讨论了接口联调。",
                    "keywords": ["接口联调"],
                    "participants": ["test1", "我"],
                },
            ],
            search_results={
                "__contacts__": [
                    _contact("user-test1", "test1", username="test1"),
                    _contact("user-test3", "test3", username="test3"),
                ]
            },
        )
        planner = _FakeSemanticPlanner(
            _rag_plan("我和 test1、test3 一起聊过什么", participants=["test1", "test3"], relation="together")
        )
        manager = _make_memory_manager(db, planner)

        context = await manager.build_rag_context_for_ai_chat("我和 test1、test3 一起聊过什么？")

        assert len(context.lines) == 1
        assert "项目验收" in context.lines[0]
        assert "接口联调" not in context.lines[0]

    asyncio.run(scenario())


def test_conversation_memory_manager_rag_asks_when_participant_relation_unknown() -> None:
    async def scenario() -> None:
        db = _FakeMemoryDatabase([])
        planner = _FakeSemanticPlanner(
            _rag_plan("我和 test1、test3 聊过什么", participants=["test1", "test3"], relation="unknown")
        )
        manager = _make_memory_manager(db, planner)

        context = await manager.build_rag_context_for_ai_chat("我和 test1、test3 聊过什么？")

        assert context.requires_confirmation is True
        assert "分别查询" in context.confirmation_prompt
        assert "共同参与" in context.confirmation_prompt

    asyncio.run(scenario())


def test_conversation_memory_manager_rag_asks_when_contact_alias_is_ambiguous() -> None:
    async def scenario() -> None:
        db = _FakeMemoryDatabase(
            [],
            search_results={
                "__contacts__": [
                    _contact("user-a", "test1", username="test1", remark="小王"),
                    _contact("user-b", "test3", username="test3", remark="小王"),
                ]
            },
        )
        planner = _FakeSemanticPlanner(_rag_plan("我和小王聊过什么", participants=["小王"]))
        manager = _make_memory_manager(db, planner)

        context = await manager.build_rag_context_for_ai_chat("我和小王聊过什么？")

        assert context.requires_confirmation is True
        assert "匹配到多个联系人" in context.confirmation_prompt
        assert "test1" in context.confirmation_prompt
        assert "test3" in context.confirmation_prompt

    asyncio.run(scenario())


def test_conversation_memory_manager_merges_followup_user_query_for_rag() -> None:
    async def scenario() -> None:
        db = _FakeMemoryDatabase(
            [
                {
                    "session_id": "s1",
                    "source_type": "summary",
                    "source_id": "summary:1",
                    "start_ts": _ts("2026-04-18T10:00:00"),
                    "end_ts": _ts("2026-04-18T10:05:00"),
                    "title": "张三 2026-04-18 10:00-10:05",
                    "text": "张三提到周末可以去南山咖啡店，下午人少一些。",
                    "keywords": ["周末", "南山咖啡店"],
                    "participants": ["张三", "我"],
                },
            ],
            search_results={"__contacts__": [_contact("user-zhangsan", "张三")]},
        )
        planner = _FakeSemanticPlanner(_rag_plan("张三上次推荐的那家店在哪", participants=["张三"]))
        manager = _make_memory_manager(db, planner)
        previous_messages = [
            AIMessage("u1", "thread-1", AIMessageRole.USER, "张三上次推荐的那家店是什么？"),
            AIMessage("a1", "thread-1", AIMessageRole.ASSISTANT, "我先帮你想想。"),
        ]

        context = await manager.build_rag_context_for_ai_chat(
            "那家店在哪？",
            previous_messages=previous_messages,
        )

        assert context.has_context is True
        assert "南山咖啡店" in context.lines[0]
        assert planner.calls[0]["query_text"] == "那家店在哪？"
        assert len(planner.calls[0]["previous_messages"]) == 2

    asyncio.run(scenario())


def test_conversation_memory_manager_vector_layer_matches_similar_terms() -> None:
    async def scenario() -> None:
        db = _FakeMemoryDatabase(
            [
                {
                    "session_id": "s1",
                    "source_type": "summary",
                    "source_id": "summary:1",
                    "start_ts": _ts("2026-04-18T10:00:00"),
                    "end_ts": _ts("2026-04-18T10:05:00"),
                    "title": "张三 2026-04-18 10:00-10:05",
                    "text": "张三提到周末可以去南山咖啡店，下午人少一些。",
                    "keywords": ["周末", "南山咖啡店"],
                    "participants": ["张三", "我"],
                },
            ],
            search_results={"__contacts__": [_contact("user-zhangsan", "张三")]},
        )
        planner = _FakeSemanticPlanner(_rag_plan("张三上次提到的咖啡馆是哪家", participants=["张三"]))
        manager = _make_memory_manager(db, planner)

        context = await manager.build_rag_context_for_ai_chat("张三上次提到的咖啡馆是哪家？")

        assert context.has_context is True
        assert "南山咖啡店" in context.lines[0]

    asyncio.run(scenario())
