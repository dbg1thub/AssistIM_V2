import asyncio
from dataclasses import replace

from client.managers import ai_action_registry as registry_module
from client.managers.ai_action_cache import AIActionCache
from client.managers.ai_action_executor import AIActionExecutor
from client.managers.ai_action_optimizer import AIPlanOptimizer
from client.managers.ai_action_registry import AtomicActionRegistry
from client.managers.ai_action_types import AIActionPlan, AIActionStep
from client.managers.ai_action_workflow import (
    AIActionPlanner,
    AIActionWorkflow,
    ContactAliasResolver,
    PendingPlannerState,
)
from client.storage.ai_action_store import AIActionStore
from client.storage.database import Database
import client.storage.ai_action_store as action_store_module


class _FakeActionMemoryManager:
    def __init__(
        self,
        *,
        context_lines: list[str] | None = None,
        result_count: int | None = None,
        extra_output: dict | None = None,
    ) -> None:
        self.context_lines = list(context_lines or [])
        self.result_count = len(self.context_lines) if result_count is None else int(result_count)
        self.extra_output = dict(extra_output or {})
        self.calls: list[dict] = []

    async def search_for_action(
        self,
        *,
        question: str,
        participants=None,
        participant_match: str = "any",
        time_scope=None,
        keywords=None,
        limit: int = 8,
    ) -> dict:
        self.calls.append(
            {
                "question": question,
                "participants": list(participants or []),
                "participant_match": participant_match,
                "time_scope": dict(time_scope or {}),
                "keywords": list(keywords or []),
                "limit": limit,
            }
        )
        results = [
            {
                "source_type": "conversation_summary",
                "source_id": f"summary:{index}",
                "title": f"记忆 {index}",
                "text": line,
                "text_preview": line,
            }
            for index, line in enumerate(self.context_lines, start=1)
        ]
        output = {
            "results": results,
            "preview": results[:3],
            "context_lines": list(self.context_lines),
            "result_count": self.result_count,
            "truncated": self.result_count > len(results),
        }
        output.update(self.extra_output)
        return output


class _FakeMemoryDatabase:
    async def list_conversation_memory_items(self, **kwargs):
        del kwargs
        return []


class _FakeContactDatabase:
    def __init__(self, contacts: list[dict], *, contact_index_version: str = "contacts-v1") -> None:
        self.contacts = list(contacts)
        self.contact_index_version = contact_index_version
        self.contact_index_version_calls = 0
        self.calls: list[dict] = []
        self.resolve_calls: list[dict] = []

    async def get_contacts_cache_index_version(self, **kwargs):
        del kwargs
        self.contact_index_version_calls += 1
        return self.contact_index_version

    async def search_contacts(self, keyword: str, limit: int = 50, **kwargs):
        self.calls.append({"keyword": keyword, "limit": limit, **kwargs})
        normalized = str(keyword or "").casefold()
        hits = []
        for contact in self.contacts:
            values = [
                contact.get("display_name"),
                contact.get("name"),
                contact.get("username"),
                contact.get("nickname"),
                contact.get("remark"),
                contact.get("assistim_id"),
            ]
            if any(normalized and normalized in str(value or "").casefold() for value in values):
                hits.append(dict(contact))
        return hits[: int(limit or 50)]

    async def list_contacts_cache_by_ids(self, contact_ids: list[str], **kwargs):
        del kwargs
        normalized_ids = {str(contact_id or "").strip() for contact_id in list(contact_ids or [])}
        return {str(contact.get("id") or ""): dict(contact) for contact in self.contacts if str(contact.get("id") or "") in normalized_ids}

    async def resolve_contacts_cache_alias(self, alias: str, limit: int = 20, **kwargs):
        del kwargs
        self.resolve_calls.append({"alias": alias, "limit": limit})
        normalized = str(alias or "").casefold()
        hits = []
        for contact in self.contacts:
            values = [
                contact.get("display_name"),
                contact.get("name"),
                contact.get("username"),
                contact.get("nickname"),
                contact.get("remark"),
                contact.get("assistim_id"),
                contact.get("id"),
            ]
            if any(normalized and normalized == str(value or "").casefold() for value in values):
                hits.append(dict(contact))
        return hits[: int(limit or 20)]


class _WorkflowPlanner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    async def plan(self, *args, **kwargs):
        user_text = str(args[0] if args else "").strip()
        pending_state = kwargs.get("pending_state")
        self.calls.append((user_text, pending_state is not None))

        if pending_state is not None and user_text == "取消":
            return AIActionPlan(is_action=True, action="cancel_action")
        if pending_state is not None and user_text == "确认":
            return AIActionPlan(is_action=True, action="confirm_action")
        if user_text == "帮我给张三发我晚点到":
            return AIActionPlan(
                is_action=True,
                action="send_message",
                requires_side_effect=True,
                slots={"target_user": "张三", "message_text": "我晚点到"},
            )
        if "聊了什么" in user_text or "聊过什么" in user_text:
            return AIActionPlan(
                is_action=True,
                action="memory_query",
                requires_app_data=True,
                slots={"participants": ["test3"]},
            )
        return AIActionPlan(is_action=False)


class _PendingNonControlPlanner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    async def plan(self, *args, **kwargs):
        user_text = str(args[0] if args else "").strip()
        pending_state = kwargs.get("pending_state")
        self.calls.append((user_text, pending_state is not None))
        if pending_state is not None:
            return AIActionPlan(is_action=False)
        if user_text == "帮我给张三发我晚点到":
            return AIActionPlan(
                is_action=True,
                action="send_message",
                requires_side_effect=True,
                slots={"target_user": "张三", "message_text": "我晚点到"},
            )
        return AIActionPlan(is_action=False)


class _InvalidConfirmationPlanner:
    async def plan(self, *args, **kwargs):
        del args, kwargs
        return AIActionPlan(
            is_action=True,
            goal="误判为发送确认",
            risk="high",
            steps=(
                AIActionStep(
                    id="confirm_send",
                    action="user.confirm",
                    args={"risk": "high", "preview": {"operation": "发送消息"}},
                    display_text="等待你确认发送...",
                ),
            ),
            final={"type": "answer", "source": "$confirm_send"},
        )


class _InvalidAtomicSendPlanner:
    async def plan(self, *args, **kwargs):
        del args, kwargs
        return AIActionPlan(
            is_action=True,
            goal="误判为发送链路",
            risk="high",
            steps=(
                AIActionStep(
                    id="resolve_target",
                    action="contact.resolve",
                    args={"queries": ["张三"], "allow_multiple": False},
                ),
                AIActionStep(
                    id="draft_message",
                    action="message.draft",
                    depends_on=("resolve_target",),
                    args={"target": "$resolve_target.contacts[0]", "content": ""},
                ),
                AIActionStep(
                    id="confirm_send",
                    action="user.confirm",
                    depends_on=("draft_message",),
                    args={
                        "risk": "high",
                        "preview": {
                            "operation": "发送消息",
                            "target": "$draft_message.target",
                            "content": "$draft_message.content",
                        },
                    },
                ),
                AIActionStep(
                    id="send_message",
                    action="message.send",
                    depends_on=("confirm_send", "draft_message"),
                    args={
                        "target": "$draft_message.target_entity",
                        "content": "$draft_message.content",
                        "idempotency_key": "$draft_message.idempotency_key",
                    },
                ),
            ),
            final={"type": "answer", "source": "$send_message.text"},
        )


class _AtomicReadPlanner:
    async def plan(self, *args, **kwargs):
        user_text = str(args[0] if args else "").strip()
        del kwargs
        return AIActionPlan(
            is_action=True,
            goal=user_text,
            risk="low",
            steps=(
                AIActionStep(
                    id="resolve_contacts",
                    action="contact.resolve",
                    args={"queries": ["test3"], "allow_multiple": True},
                ),
                AIActionStep(
                    id="search_memory",
                    action="memory.search",
                    depends_on=("resolve_contacts",),
                    args={
                        "participants": "$resolve_contacts.contacts",
                        "participant_match": "any",
                        "time_scope": {"type": "all_history"},
                        "keywords": [],
                        "question": user_text,
                    },
                ),
                AIActionStep(
                    id="summarize_memory",
                    action="memory.summarize",
                    depends_on=("search_memory",),
                    args={"source": "$search_memory", "question": user_text},
                ),
            ),
            final={"type": "answer", "source": "$summarize_memory"},
        )


class _DuplicateResolvePlanner:
    async def plan(self, *args, **kwargs):
        user_text = str(args[0] if args else "").strip()
        del kwargs
        resolve_steps = tuple(
            AIActionStep(
                id=f"resolve_{index}",
                action="contact.resolve",
                args={"queries": ["张三"], "allow_multiple": False},
            )
            for index in range(1, 7)
        )
        return AIActionPlan(
            is_action=True,
            goal=user_text,
            risk="high",
            steps=(
                *resolve_steps,
                AIActionStep(
                    id="draft_message",
                    action="message.draft",
                    depends_on=("resolve_6",),
                    args={"target": "$resolve_6.contacts[0]", "content": "我晚点到"},
                ),
                AIActionStep(
                    id="confirm_send",
                    action="user.confirm",
                    depends_on=("draft_message",),
                    args={
                        "risk": "high",
                        "preview": {
                            "operation": "发送消息",
                            "target": "$draft_message.target",
                            "content": "$draft_message.content",
                        },
                    },
                ),
                AIActionStep(
                    id="send_message",
                    action="message.send",
                    depends_on=("confirm_send", "draft_message"),
                    args={
                        "target": "$draft_message.target_entity",
                        "content": "$draft_message.content",
                        "preview": "$draft_message.preview",
                        "idempotency_key": "$draft_message.idempotency_key",
                    },
                ),
            ),
            final={"type": "answer", "source": "$send_message.text"},
        )


def test_ai_action_planner_prompt_routes_history_queries_to_memory_actions() -> None:
    system_prompt = AIActionPlanner._system_prompt(AIActionPlanner.PROMPT_NEW_ACTION)
    user_prompt = AIActionPlanner._user_prompt("我和test3昨天聊了什么？")

    assert "contact.resolve, memory.search, memory.summarize, message.draft, user.confirm, message.send" in system_prompt
    assert "聊天记录查询使用 contact.resolve -> memory.search -> memory.summarize" in system_prompt
    assert "memory.search" in system_prompt
    assert "memory.summarize" in system_prompt
    assert "询问历史、回顾、总结、检索内容时使用 memory.search 和 memory.summarize" in user_prompt
    assert "发送消息的组合是 contact.resolve -> message.draft -> user.confirm -> message.send" in user_prompt
    assert "memory.search" in user_prompt
    assert "memory.summarize" in user_prompt


def test_ai_action_planner_prompt_documents_atomic_action_arg_contracts() -> None:
    system_prompt = AIActionPlanner._system_prompt(AIActionPlanner.PROMPT_NEW_ACTION)

    assert 'contact.resolve.args = {"queries": ["张三"], "allow_multiple": false}' in system_prompt
    assert "不要使用 contact.resolve.args.target" in system_prompt
    assert (
        'memory.search.args = {"participants": "$resolve_contacts.contacts", '
        '"participant_match": "any", "time_scope": {"type": "all_history"}, '
        '"keywords": [], "question": "用户原始问题"}'
    ) in system_prompt
    assert '历史/之前/聊过什么/回顾 -> time_scope.type="all_history"' in system_prompt
    assert 'memory.summarize.args = {"source": "$search_memory", "question": "用户原始问题"}' in system_prompt
    assert 'message.draft.args = {"target": "$resolve_target.contacts[0]", "content": "明确消息内容"}' in system_prompt
    assert (
        'user.confirm.args = {"risk": "high", "preview": {"operation": "发送消息", '
        '"target": "$draft_message.target", "content": "$draft_message.content"}}'
    ) in system_prompt
    assert (
        'message.send.args = {"target": "$draft_message.target_entity", '
        '"content": "$draft_message.content", "preview": "$draft_message.preview", '
        '"idempotency_key": "$draft_message.idempotency_key"}'
    ) in system_prompt
    assert "示例：普通聊天" in system_prompt
    assert "示例：聊天历史查询" in system_prompt
    assert "示例：发送消息" in system_prompt
    assert "聊天历史查询必须使用固定 step id：resolve_contacts, search_memory, summarize_memory" in system_prompt
    assert "发送消息必须使用固定 step id：resolve_target, draft_message, confirm_send, send_message" in system_prompt
    assert "所有 $ 引用的根名称必须等于已存在 step.id" in system_prompt
    assert 'participant_match 只能是 "any", "all", "direct_only", "group_only"' in system_prompt


def test_ai_action_planner_uses_state_specific_prompt_templates() -> None:
    confirmation_state = PendingPlannerState(
        id="plan-1",
        thread_id="thread-1",
        ai_thread_id="thread-1",
        action="send_message",
        state="waiting_confirmation",
        slots={},
        missing_slots=(),
        waiting_payload={"type": "confirmation", "preview": {"operation": "发送消息", "target": "张三"}},
    )
    contact_state = PendingPlannerState(
        id="plan-2",
        thread_id="thread-1",
        ai_thread_id="thread-1",
        action="send_message",
        state="waiting_clarification",
        slots={},
        missing_slots=("target_user",),
        waiting_payload={"type": "contact_ambiguity", "candidates": [{"contact_id": "user-1"}]},
    )
    clarification_state = PendingPlannerState(
        id="plan-3",
        thread_id="thread-1",
        ai_thread_id="thread-1",
        action="send_message",
        state="waiting_clarification",
        slots={},
        missing_slots=("message_text",),
        waiting_payload={"type": "clarification", "missing": ["message_text"]},
    )

    assert AIActionPlanner._prompt_kind(None) == AIActionPlanner.PROMPT_NEW_ACTION
    assert AIActionPlanner._prompt_kind(confirmation_state) == AIActionPlanner.PROMPT_PENDING_CONFIRMATION
    assert AIActionPlanner._prompt_kind(contact_state) == AIActionPlanner.PROMPT_PENDING_CONTACT_SELECTION
    assert AIActionPlanner._prompt_kind(clarification_state) == AIActionPlanner.PROMPT_PENDING_CLARIFICATION


def test_ai_action_planner_pending_prompts_are_focused() -> None:
    confirmation_state = PendingPlannerState(
        id="plan-1",
        thread_id="thread-1",
        ai_thread_id="thread-1",
        action="send_message",
        state="waiting_confirmation",
        slots={},
        missing_slots=(),
        waiting_payload={"type": "confirmation", "preview": {"operation": "发送消息", "target": "张三"}},
    )
    contact_state = PendingPlannerState(
        id="plan-2",
        thread_id="thread-1",
        ai_thread_id="thread-1",
        action="send_message",
        state="waiting_clarification",
        slots={},
        missing_slots=("target_user",),
        waiting_payload={"type": "contact_ambiguity", "candidates": [{"contact_id": "user-1"}]},
    )
    clarification_state = PendingPlannerState(
        id="plan-3",
        thread_id="thread-1",
        ai_thread_id="thread-1",
        action="send_message",
        state="waiting_clarification",
        slots={},
        missing_slots=("message_text",),
        waiting_payload={"type": "clarification", "missing": ["message_text"]},
    )

    confirmation_prompt = AIActionPlanner._user_prompt("确认", pending_state=confirmation_state)
    contact_prompt = AIActionPlanner._user_prompt("2", pending_state=contact_state)
    clarification_prompt = AIActionPlanner._user_prompt("我晚点到", pending_state=clarification_state)

    assert 'action="confirm_action"' in confirmation_prompt
    assert 'action="select_contact_alias"' in contact_prompt
    assert 'action="cancel_action"' in clarification_prompt
    assert "memory.search" not in confirmation_prompt
    assert "memory.search" not in contact_prompt
    assert "memory.search" not in clarification_prompt
    assert "contact.resolve -> message.draft -> user.confirm -> message.send" in clarification_prompt


def test_ai_action_workflow_rejects_confirmation_without_write_step(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_InvalidConfirmationPlanner(),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="确认一下")
            assert result.handled is False
            assert await store.latest_pending_plan("thread-1") is None
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_rejects_incomplete_atomic_send_chain(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_InvalidAtomicSendPlanner(),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="帮我发一下")
            assert result.handled is False
            assert await store.latest_pending_plan("thread-1") is None
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_registry_exposes_memory_actions() -> None:
    registry = AtomicActionRegistry(
        contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        memory_manager=_FakeActionMemoryManager(),
    )

    assert registry.names() == (
        "contact.resolve",
        "memory.search",
        "memory.summarize",
        "message.draft",
        "message.send",
        "user.confirm",
    )
    assert registry.get("memory.search") is not None
    assert registry.get("memory.summarize") is not None


def test_ai_action_registry_clarifies_send_confirmation_without_preview() -> None:
    async def scenario() -> None:
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        spec = registry.get("user.confirm")
        assert spec is not None
        pause = await spec.handler(  # type: ignore[misc]
            {"risk": "high", "preview": {}},
            {"step_id": "confirm_send"},
        )

        assert pause.state == "waiting_confirmation"
        assert "确认" in pause.response_text
    asyncio.run(scenario())


def test_ai_action_registry_contact_resolve_uses_versioned_cache() -> None:
    async def scenario() -> None:
        contact_db = _FakeContactDatabase(
            [
                {
                    "id": "user-1",
                    "display_name": "张三",
                    "username": "zhangsan",
                    "nickname": "张三",
                    "remark": "张三",
                    "assistim_id": "zhangsan",
                }
            ],
            contact_index_version="contacts-v1",
        )
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=contact_db),
            action_cache=AIActionCache(),
        )
        spec = registry.get("contact.resolve")
        assert spec is not None

        first = await spec.handler(  # type: ignore[misc]
            {"queries": ["张三"], "allow_multiple": False},
            {"step_id": "resolve_a"},
        )
        second = await spec.handler(  # type: ignore[misc]
            {"queries": ["张三"], "allow_multiple": False},
            {"step_id": "resolve_b"},
        )
        second["contacts"].append({"contact_id": "polluted"})
        third = await spec.handler(  # type: ignore[misc]
            {"queries": ["张三"], "allow_multiple": False},
            {"step_id": "resolve_c"},
        )

        assert first["cache_hit"] is False
        assert second["cache_hit"] is True
        assert third["cache_hit"] is True
        assert third["contacts"] == first["contacts"]
        assert third["cache_namespace"] == "contact.resolve"
        assert third["cache_index_version"] == "contacts-v1"
        assert len(contact_db.resolve_calls) == 1

    asyncio.run(scenario())


def test_ai_action_registry_contact_resolve_cache_misses_when_index_version_changes() -> None:
    async def scenario() -> None:
        contact_db = _FakeContactDatabase(
            [
                {
                    "id": "user-1",
                    "display_name": "张三",
                    "username": "zhangsan",
                    "nickname": "张三",
                    "remark": "张三",
                    "assistim_id": "zhangsan",
                }
            ],
            contact_index_version="contacts-v1",
        )
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=contact_db),
            action_cache=AIActionCache(),
        )
        spec = registry.get("contact.resolve")
        assert spec is not None

        first = await spec.handler(  # type: ignore[misc]
            {"queries": ["张三"], "allow_multiple": False},
            {"step_id": "resolve_a"},
        )
        contact_db.contact_index_version = "contacts-v2"
        second = await spec.handler(  # type: ignore[misc]
            {"queries": ["张三"], "allow_multiple": False},
            {"step_id": "resolve_b"},
        )

        assert first["cache_hit"] is False
        assert second["cache_hit"] is False
        assert second["cache_index_version"] == "contacts-v2"
        assert len(contact_db.resolve_calls) == 2

    asyncio.run(scenario())


def test_ai_action_registry_contact_resolve_does_not_cache_without_index_version() -> None:
    async def scenario() -> None:
        contact_db = _FakeContactDatabase(
            [
                {
                    "id": "user-1",
                    "display_name": "张三",
                    "username": "zhangsan",
                    "nickname": "张三",
                    "remark": "张三",
                    "assistim_id": "zhangsan",
                }
            ],
            contact_index_version="",
        )
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=contact_db),
            action_cache=AIActionCache(),
        )
        spec = registry.get("contact.resolve")
        assert spec is not None

        first = await spec.handler(  # type: ignore[misc]
            {"queries": ["张三"], "allow_multiple": False},
            {"step_id": "resolve_a"},
        )
        second = await spec.handler(  # type: ignore[misc]
            {"queries": ["张三"], "allow_multiple": False},
            {"step_id": "resolve_b"},
        )

        assert first["cache_hit"] is False
        assert second["cache_hit"] is False
        assert "cache_index_version" not in second
        assert len(contact_db.resolve_calls) == 2

    asyncio.run(scenario())


def test_ai_action_registry_contact_resolve_does_not_cache_ambiguity_pause() -> None:
    async def scenario() -> None:
        contact_db = _FakeContactDatabase(
            [
                {
                    "id": "user-1",
                    "display_name": "张三",
                    "username": "zhangsan-a",
                    "nickname": "张三",
                    "remark": "张三",
                    "assistim_id": "zhangsan-a",
                },
                {
                    "id": "user-2",
                    "display_name": "张三",
                    "username": "zhangsan-b",
                    "nickname": "张三",
                    "remark": "张三",
                    "assistim_id": "zhangsan-b",
                },
            ],
            contact_index_version="contacts-v1",
        )
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=contact_db),
            action_cache=AIActionCache(),
        )
        spec = registry.get("contact.resolve")
        assert spec is not None

        first = await spec.handler(  # type: ignore[misc]
            {"queries": ["张三"], "allow_multiple": False},
            {"step_id": "resolve_a"},
        )
        second = await spec.handler(  # type: ignore[misc]
            {"queries": ["张三"], "allow_multiple": False},
            {"step_id": "resolve_b"},
        )

        assert first.state == "waiting_clarification"
        assert second.state == "waiting_clarification"
        assert first.payload["step_id"] == "resolve_a"
        assert second.payload["step_id"] == "resolve_b"
        assert len(contact_db.resolve_calls) == 2

    asyncio.run(scenario())


def test_ai_action_executor_persists_contact_resolve_cache_hit_result(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        contact_db = _FakeContactDatabase(
            [
                {
                    "id": "user-1",
                    "display_name": "张三",
                    "username": "zhangsan",
                    "nickname": "张三",
                    "remark": "张三",
                    "assistim_id": "zhangsan",
                }
            ],
            contact_index_version="contacts-v1",
        )
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=contact_db),
            action_cache=AIActionCache(),
        )
        executor = AIActionExecutor(registry=registry, store=store)
        plan = AIActionPlan(
            is_action=True,
            goal="解析联系人",
            steps=(
                AIActionStep(
                    id="resolve_contact",
                    action="contact.resolve",
                    args={"queries": ["张三"], "allow_multiple": False},
                ),
            ),
            final={"type": "answer", "source": "$resolve_contact"},
        )
        try:
            first_record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_contact_cache_miss",
            )
            await executor.execute(first_record)
            second_record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_contact_cache_hit",
            )
            await executor.execute(second_record)
            updated = await store.get_plan(second_record.id)

            assert updated is not None
            assert updated.step_outputs["resolve_contact"]["cache_hit"] is True
            assert updated.step_outputs["resolve_contact"]["cache_namespace"] == "contact.resolve"
            assert updated.step_outputs["resolve_contact"]["cache_index_version"] == "contacts-v1"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_optimizer_merges_duplicate_contact_resolve_and_updates_refs() -> None:
    optimizer = AIPlanOptimizer()
    plan = AIActionPlan(
        is_action=True,
        goal="send",
        risk="high",
        steps=(
            AIActionStep(id="resolve_a", action="contact.resolve", args={"queries": ["张三"], "allow_multiple": False}),
            AIActionStep(id="resolve_b", action="contact.resolve", args={"queries": ["张三"], "allow_multiple": False}),
            AIActionStep(
                id="draft",
                action="message.draft",
                depends_on=("resolve_b",),
                args={"target": "$resolve_b.contacts[0]", "content": "我晚点到"},
            ),
            AIActionStep(
                id="confirm_send",
                action="user.confirm",
                depends_on=("draft",),
                args={
                    "risk": "high",
                    "preview": {"operation": "发送消息", "target": "$draft.target", "content": "$draft.content"},
                },
            ),
            AIActionStep(
                id="send_message",
                action="message.send",
                depends_on=("confirm_send", "draft"),
                args={
                    "target": "$draft.target_entity",
                    "content": "$draft.content",
                    "preview": "$draft.preview",
                    "idempotency_key": "$draft.idempotency_key",
                },
            ),
        ),
        final={"type": "answer", "source": "$send_message.text"},
    )

    optimized, reason = optimizer.optimize(plan)

    assert reason == "optimizer_merge_duplicate_contact_resolve"
    assert [step.id for step in optimized.steps] == ["resolve_a", "draft", "confirm_send", "send_message"]
    draft = next(step for step in optimized.steps if step.id == "draft")
    assert draft.depends_on == ("resolve_a",)
    assert draft.args["target"] == "$resolve_a.contacts[0]"


def test_ai_action_optimizer_merges_duplicate_memory_search_and_updates_refs() -> None:
    optimizer = AIPlanOptimizer()
    search_args = {
        "participants": "$resolve_contacts.contacts",
        "participant_match": "any",
        "time_scope": {"type": "all_history"},
        "keywords": [],
        "question": "我和 test3 聊过什么？",
        "limit": 8,
    }
    plan = AIActionPlan(
        is_action=True,
        goal="history",
        risk="low",
        steps=(
            AIActionStep(
                id="resolve_contacts",
                action="contact.resolve",
                args={"queries": ["test3"], "allow_multiple": True},
            ),
            AIActionStep(
                id="search_a",
                action="memory.search",
                depends_on=("resolve_contacts",),
                args=dict(search_args),
            ),
            AIActionStep(
                id="search_b",
                action="memory.search",
                depends_on=("resolve_contacts",),
                args=dict(search_args),
            ),
            AIActionStep(
                id="summarize",
                action="memory.summarize",
                depends_on=("search_b",),
                args={"source": "$search_b", "question": "我和 test3 聊过什么？"},
            ),
        ),
        final={"type": "answer", "source": "$summarize"},
    )

    optimized, reason = optimizer.optimize(plan)

    assert reason == "optimizer_merge_duplicate_memory_search"
    assert [step.id for step in optimized.steps] == ["resolve_contacts", "search_a", "summarize"]
    summarize = next(step for step in optimized.steps if step.id == "summarize")
    assert summarize.depends_on == ("search_a",)
    assert summarize.args["source"] == "$search_a"


def test_ai_action_optimizer_keeps_distinct_memory_search_steps() -> None:
    optimizer = AIPlanOptimizer()
    base_args = {
        "participants": "$resolve_contacts.contacts",
        "participant_match": "any",
        "time_scope": {"type": "all_history"},
        "keywords": [],
        "question": "我和 test3 聊过什么？",
    }
    plan = AIActionPlan(
        is_action=True,
        goal="history",
        risk="low",
        steps=(
            AIActionStep(
                id="resolve_contacts",
                action="contact.resolve",
                args={"queries": ["test3"], "allow_multiple": True},
            ),
            AIActionStep(
                id="search_a",
                action="memory.search",
                depends_on=("resolve_contacts",),
                args={**base_args, "limit": 5},
            ),
            AIActionStep(
                id="summarize_a",
                action="memory.summarize",
                depends_on=("search_a",),
                args={"source": "$search_a", "question": "我和 test3 聊过什么？"},
            ),
            AIActionStep(
                id="search_b",
                action="memory.search",
                depends_on=("resolve_contacts",),
                args={**base_args, "limit": 8},
            ),
            AIActionStep(
                id="summarize_b",
                action="memory.summarize",
                depends_on=("search_b",),
                args={"source": "$search_b", "question": "我和 test3 聊过什么？"},
            ),
        ),
        final={"type": "answer", "sources": ["$summarize_a", "$summarize_b"]},
    )

    optimized, reason = optimizer.optimize(plan)

    assert reason == ""
    assert [step.id for step in optimized.steps] == [
        "resolve_contacts",
        "search_a",
        "summarize_a",
        "search_b",
        "summarize_b",
    ]


def test_ai_action_optimizer_removes_unreachable_read_steps_without_touching_confirm() -> None:
    optimizer = AIPlanOptimizer()
    plan = AIActionPlan(
        is_action=True,
        goal="send",
        risk="high",
        steps=(
            AIActionStep(id="unused_resolve", action="contact.resolve", args={"queries": ["李四"], "allow_multiple": False}),
            AIActionStep(id="resolve_target", action="contact.resolve", args={"queries": ["张三"], "allow_multiple": False}),
            AIActionStep(
                id="draft",
                action="message.draft",
                depends_on=("resolve_target",),
                args={"target": "$resolve_target.contacts[0]", "content": "我晚点到"},
            ),
            AIActionStep(
                id="confirm_send",
                action="user.confirm",
                depends_on=("draft",),
                args={
                    "risk": "high",
                    "preview": {"operation": "发送消息", "target": "$draft.target", "content": "$draft.content"},
                },
            ),
            AIActionStep(
                id="send_message",
                action="message.send",
                depends_on=("confirm_send", "draft"),
                args={
                    "target": "$draft.target_entity",
                    "content": "$draft.content",
                    "preview": "$draft.preview",
                    "idempotency_key": "$draft.idempotency_key",
                },
            ),
        ),
        final={"type": "answer", "source": "$send_message.text"},
    )

    optimized, reason = optimizer.optimize(plan)

    assert "optimizer_remove_unreachable_read_steps" in reason
    assert [step.id for step in optimized.steps] == ["resolve_target", "draft", "confirm_send", "send_message"]


def test_ai_action_workflow_checks_resources_after_safe_optimizer(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        contact_db = _FakeContactDatabase(
            [
                {
                    "id": "user-1",
                    "display_name": "张三",
                    "username": "zhangsan",
                    "nickname": "张三",
                    "remark": "张三",
                    "assistim_id": "zhangsan",
                }
            ]
        )
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_DuplicateResolvePlanner(),
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="帮我给张三发我晚点到")
            assert result.handled is True
            assert result.message_extra["ai_action"]["state"] == "waiting_confirmation"
            plan = await store.get_plan(result.message_extra["ai_action"]["plan_id"])
            assert plan is not None
            assert plan.plan_version == 2
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_ignores_regular_chat(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_WorkflowPlanner(),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="帮我写一段介绍")
            assert result.handled is False
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_ignores_legacy_history_query(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_WorkflowPlanner(),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="我和test3聊过什么？")
            assert result.handled is False
            assert await store.latest_pending_plan("thread-1") is None
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_executes_atomic_memory_plan(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        contact_db = _FakeContactDatabase(
            [
                {
                    "id": "user-3",
                    "display_name": "test3",
                    "username": "test3",
                    "nickname": "test3",
                    "remark": "",
                    "assistim_id": "test3",
                }
            ]
        )
        memory_manager = _FakeActionMemoryManager(context_lines=["[2026-04-21 10:00-10:05] test3；摘要：讨论了项目排期。"])
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_AtomicReadPlanner(),
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
            memory_manager=memory_manager,
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="我和test3聊过什么？")
            assert result.handled is True
            assert result.response_text == ""
            assert result.memory_context_lines == ("[2026-04-21 10:00-10:05] test3；摘要：讨论了项目排期。",)
            assert result.message_extra["ai_action"]["action"] == "memory.search"
            assert result.message_extra["ai_action"]["state"] == "running"
            assert memory_manager.calls[0]["participant_match"] == "any"
            assert memory_manager.calls[0]["time_scope"] == {"type": "all_history"}
            assert memory_manager.calls[0]["participants"][0]["contact_id"] == "user-3"
            plan = await store.get_plan(result.message_extra["ai_action"]["plan_id"])
            assert plan is not None
            assert plan.step_outputs["search_memory"]["result_count"] == 1
            assert plan.step_outputs["summarize_memory"]["requires_responder"] is True
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_memory_summarize_reports_empty_result(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        contact_db = _FakeContactDatabase(
            [
                {
                    "id": "user-3",
                    "display_name": "test3",
                    "username": "test3",
                    "nickname": "test3",
                    "assistim_id": "test3",
                }
            ]
        )
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_AtomicReadPlanner(),
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
            memory_manager=_FakeActionMemoryManager(context_lines=[]),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="我和test3聊过什么？")

            assert result.handled is True
            assert "没有找到相关记录" in result.response_text
            assert result.memory_context_lines == ()
            assert result.message_extra["ai_action"]["state"] == "done"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_memory_search_preserves_cache_metadata(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        contact_db = _FakeContactDatabase(
            [
                {
                    "id": "user-3",
                    "display_name": "test3",
                    "username": "test3",
                    "nickname": "test3",
                    "assistim_id": "test3",
                }
            ]
        )
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_AtomicReadPlanner(),
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
            memory_manager=_FakeActionMemoryManager(
                context_lines=["[2026-04-21 10:00] test3；摘要：讨论了项目排期。"],
                extra_output={
                    "cache_hit": True,
                    "cache_namespace": "memory.search",
                    "cache_index_version": "index-v1",
                    "cache_search_version": "action_memory_search:v1",
                },
            ),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="我和test3聊过什么？")
            plan = await store.get_plan(result.message_extra["ai_action"]["plan_id"])

            assert plan is not None
            assert plan.step_outputs["search_memory"]["cache_hit"] is True
            assert plan.step_outputs["search_memory"]["cache_namespace"] == "memory.search"
            assert plan.step_outputs["search_memory"]["cache_index_version"] == "index-v1"
            assert plan.step_outputs["search_memory"]["cache_search_version"] == "action_memory_search:v1"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_registry_memory_summarize_keeps_small_context_unmodified() -> None:
    async def scenario() -> None:
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            memory_manager=_FakeActionMemoryManager(),
        )
        spec = registry.get("memory.summarize")
        assert spec is not None

        output = await spec.handler(  # type: ignore[misc]
            {
                "source": {
                    "context_lines": [
                        "[2026-04-21 10:00] 摘要：讨论了项目排期。",
                        "[2026-04-21 10:05] 摘要：确认了交付时间。",
                    ],
                    "result_count": 2,
                },
                "question": "我和 test3 聊过什么？",
            },
            {"store": None},
        )

        assert output["requires_responder"] is True
        assert output["context_lines"] == [
            "[2026-04-21 10:00] 摘要：讨论了项目排期。",
            "[2026-04-21 10:05] 摘要：确认了交付时间。",
        ]
        assert output["chunked"] is False
        assert output["chunk_count"] == 0
        assert output["input_result_count"] == 2
        assert output["context_chars"] > 0

    asyncio.run(scenario())


def test_ai_action_registry_memory_summarize_chunks_large_context() -> None:
    async def scenario() -> None:
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            memory_manager=_FakeActionMemoryManager(),
        )
        spec = registry.get("memory.summarize")
        assert spec is not None
        context_lines = [
            f"[2026-04-21 10:{index:02d}] 摘要：第 {index} 条记录，包含项目排期、风险和下一步安排。"
            for index in range(10)
        ]

        output = await spec.handler(  # type: ignore[misc]
            {
                "source": {
                    "context_lines": context_lines,
                    "result_count": 10,
                },
                "question": "总结历史",
            },
            {"store": None},
        )

        assert output["requires_responder"] is True
        assert output["chunked"] is True
        assert output["chunk_count"] == 3
        assert output["input_result_count"] == 10
        assert len(output["context_lines"]) == 3
        assert output["context_lines"][0].startswith("检索结果 1-4：")
        assert output["context_lines"][1].startswith("检索结果 5-8：")
        assert output["context_lines"][2].startswith("检索结果 9-10：")
        assert output["context_chars"] < sum(len(line) for line in context_lines)

    asyncio.run(scenario())


def test_ai_action_registry_memory_summarize_uses_versioned_cache(monkeypatch) -> None:
    async def scenario() -> None:
        calls = []
        original = registry_module._summarize_memory_context_lines

        def wrapped(context_lines, *, input_result_count):
            calls.append(list(context_lines))
            return original(context_lines, input_result_count=input_result_count)

        monkeypatch.setattr(registry_module, "_summarize_memory_context_lines", wrapped)
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            memory_manager=_FakeActionMemoryManager(),
            action_cache=AIActionCache(),
        )
        spec = registry.get("memory.summarize")
        assert spec is not None
        source = {
            "context_lines": [
                "[2026-04-21 10:00] 摘要：讨论了项目排期。",
                "[2026-04-21 10:05] 摘要：确认了交付时间。",
            ],
            "result_count": 2,
        }

        first = await spec.handler(  # type: ignore[misc]
            {"source": source, "question": "我和 test3 聊过什么？"},
            {"store": None},
        )
        first["context_lines"].append("外部修改不应污染缓存")
        second = await spec.handler(  # type: ignore[misc]
            {"source": source, "question": "我和 test3 聊过什么？"},
            {"store": None},
        )

        assert first["cache_hit"] is False
        assert second["cache_hit"] is True
        assert second["cache_namespace"] == "memory.summarize"
        assert second["context_lines"] == source["context_lines"]
        assert calls == [source["context_lines"]]

    asyncio.run(scenario())


def test_ai_action_registry_memory_summarize_cache_key_changes_with_question(monkeypatch) -> None:
    async def scenario() -> None:
        calls = []
        original = registry_module._summarize_memory_context_lines

        def wrapped(context_lines, *, input_result_count):
            calls.append(list(context_lines))
            return original(context_lines, input_result_count=input_result_count)

        monkeypatch.setattr(registry_module, "_summarize_memory_context_lines", wrapped)
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            memory_manager=_FakeActionMemoryManager(),
            action_cache=AIActionCache(),
        )
        spec = registry.get("memory.summarize")
        assert spec is not None
        source = {
            "context_lines": ["[2026-04-21 10:00] 摘要：讨论了项目排期。"],
            "result_count": 1,
        }

        first = await spec.handler(  # type: ignore[misc]
            {"source": source, "question": "聊过什么？"},
            {"store": None},
        )
        second = await spec.handler(  # type: ignore[misc]
            {"source": source, "question": "有没有风险？"},
            {"store": None},
        )

        assert first["cache_hit"] is False
        assert second["cache_hit"] is False
        assert len(calls) == 2

    asyncio.run(scenario())


def test_ai_action_registry_memory_summarize_cache_key_changes_with_source_checksum(monkeypatch) -> None:
    async def scenario() -> None:
        calls = []
        original = registry_module._summarize_memory_context_lines

        def wrapped(context_lines, *, input_result_count):
            calls.append(list(context_lines))
            return original(context_lines, input_result_count=input_result_count)

        monkeypatch.setattr(registry_module, "_summarize_memory_context_lines", wrapped)
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            memory_manager=_FakeActionMemoryManager(),
            action_cache=AIActionCache(),
        )
        spec = registry.get("memory.summarize")
        assert spec is not None

        first = await spec.handler(  # type: ignore[misc]
            {
                "source": {
                    "context_lines": ["[2026-04-21 10:00] 摘要：讨论了项目排期。"],
                    "result_count": 1,
                },
                "question": "聊过什么？",
            },
            {"store": None},
        )
        second = await spec.handler(  # type: ignore[misc]
            {
                "source": {
                    "context_lines": ["[2026-04-21 10:00] 摘要：讨论了质量风险。"],
                    "result_count": 1,
                },
                "question": "聊过什么？",
            },
            {"store": None},
        )

        assert first["cache_hit"] is False
        assert second["cache_hit"] is False
        assert len(calls) == 2

    asyncio.run(scenario())


def test_ai_action_registry_memory_summarize_cache_key_requires_versions() -> None:
    source = {
        "context_lines": ["[2026-04-21 10:00] 摘要：讨论了项目排期。"],
        "result_count": 1,
    }

    assert (
        registry_module._memory_summarize_cache_key(
            source=source,
            question="聊过什么？",
            prompt_version="",
            model_id=registry_module.MEMORY_SUMMARIZE_MODEL_ID,
        )
        is None
    )
    assert (
        registry_module._memory_summarize_cache_key(
            source=source,
            question="聊过什么？",
            prompt_version=registry_module.MEMORY_SUMMARIZE_PROMPT_VERSION,
            model_id="",
        )
        is None
    )


def test_ai_action_executor_persists_memory_summarize_cache_hit_result(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            memory_manager=_FakeActionMemoryManager(),
            action_cache=AIActionCache(),
        )
        executor = AIActionExecutor(registry=registry, store=store)
        source = {
            "context_lines": [
                "[2026-04-21 10:00] 摘要：讨论了项目排期。",
                "[2026-04-21 10:05] 摘要：确认了交付时间。",
            ],
            "result_count": 2,
        }
        plan = AIActionPlan(
            is_action=True,
            goal="查询历史",
            steps=(
                AIActionStep(
                    id="summarize_memory",
                    action="memory.summarize",
                    args={"source": source, "question": "聊过什么？"},
                ),
            ),
            final={"type": "answer", "source": "$summarize_memory"},
        )
        try:
            first_record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_cache_miss",
            )
            await executor.execute(first_record)

            second_record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_cache_hit",
            )
            await executor.execute(second_record)
            updated = await store.get_plan(second_record.id)

            assert updated is not None
            assert updated.step_outputs["summarize_memory"]["cache_hit"] is True
            assert updated.step_outputs["summarize_memory"]["cache_namespace"] == "memory.summarize"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_does_not_execute_confirm_without_pending(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_WorkflowPlanner(),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="确认")
            assert result.handled is False
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_write_action_is_disabled(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        contact_db = _FakeContactDatabase(
            [
                {
                    "id": "user-1",
                    "display_name": "张三",
                    "username": "zhangsan",
                    "nickname": "张三",
                    "remark": "张三",
                    "assistim_id": "zhangsan",
                }
            ]
        )
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_WorkflowPlanner(),
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="帮我给张三发我晚点到")

            assert result.handled is True
            assert "确认要发送消息给张三" in result.response_text
            assert result.message_extra["ai_action"]["action"] == "send_message"
            assert result.message_extra["ai_action"]["state"] == "waiting_confirmation"

            confirmed = await workflow.handle_user_turn(thread_id="thread-1", text="确认")
            assert confirmed.handled is True
            assert "还没有接入真实发送能力" in confirmed.response_text
            assert confirmed.message_extra["ai_action"]["state"] == "done"
            assert len(contact_db.resolve_calls) == 1
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_waits_for_planner_control_before_confirming_pending_write(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        contact_db = _FakeContactDatabase(
            [
                {
                    "id": "user-1",
                    "display_name": "张三",
                    "username": "zhangsan",
                    "nickname": "张三",
                    "remark": "张三",
                    "assistim_id": "zhangsan",
                }
            ]
        )
        planner = _PendingNonControlPlanner()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=planner,
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
        )
        try:
            first = await workflow.handle_user_turn(thread_id="thread-1", text="帮我给张三发我晚点到")
            assert first.handled is True
            plan_id = first.message_extra["ai_action"]["plan_id"]
            assert first.message_extra["ai_action"]["state"] == "waiting_confirmation"

            second = await workflow.handle_user_turn(thread_id="thread-1", text="确认")
            assert second.handled is False
            record = await store.get_plan(plan_id)
            assert record is not None
            assert record.state == "waiting_confirmation"
            assert "confirm_send" not in record.step_outputs
            assert planner.calls[-1] == ("确认", True)
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_uses_temp_result_for_large_step_output(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        draft_spec = registry.get("message.draft")
        assert draft_spec is not None
        registry._actions["message.draft"] = replace(draft_spec, max_output_json_bytes=64)
        executor = AIActionExecutor(registry=registry, store=store)
        plan = AIActionPlan(
            is_action=True,
            goal="草稿太长",
            steps=(
                AIActionStep(
                    id="draft_message",
                    action="message.draft",
                    args={
                        "target": {"contact_id": "user-1", "display_name": "张三"},
                        "content": "很长的内容" * 80,
                    },
                ),
            ),
            final={"type": "answer", "source": "$draft_message"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_large_payload",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)

            assert updated is not None
            assert "result_ref" in updated.step_outputs["draft_message"]
            assert result.state == "done"
            result_ref = updated.step_outputs["draft_message"]["result_ref"]
            assert await store.get_temp_result(result_ref["id"]) is not None
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_passes_large_memory_search_by_result_ref(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        memory_manager = _FakeActionMemoryManager(
            context_lines=[f"[2026-04-21 10:{index:02d}] 摘要：第 {index} 条记录。" for index in range(20)]
        )
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            memory_manager=memory_manager,
        )
        search_spec = registry.get("memory.search")
        assert search_spec is not None
        registry._actions["memory.search"] = replace(search_spec, max_output_json_bytes=256)
        executor = AIActionExecutor(registry=registry, store=store)
        plan = AIActionPlan(
            is_action=True,
            goal="查询历史",
            steps=(
                AIActionStep(
                    id="search_memory",
                    action="memory.search",
                    args={
                        "participants": [],
                        "participant_match": "any",
                        "time_scope": {"type": "all_history"},
                        "question": "查历史",
                    },
                ),
                AIActionStep(
                    id="summarize_memory",
                    action="memory.summarize",
                    depends_on=("search_memory",),
                    args={"source": "$search_memory", "question": "查历史"},
                ),
            ),
            final={"type": "answer", "source": "$summarize_memory"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_large_memory_payload",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)

            assert updated is not None
            assert "result_ref" in updated.step_outputs["search_memory"]
            result_ref = updated.step_outputs["search_memory"]["result_ref"]
            assert await store.get_temp_result(result_ref["id"]) is not None
            assert result.state == "running"
            assert result.memory_context_lines[0].startswith("检索结果 1-4：")
            assert updated.step_outputs["summarize_memory"]["chunked"] is True
            assert updated.step_outputs["summarize_memory"]["input_result_count"] == 20
        finally:
            await db.close()

    asyncio.run(scenario())
