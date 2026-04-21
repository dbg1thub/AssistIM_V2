import asyncio
from dataclasses import replace

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


class _FakeMemoryDatabase:
    async def list_conversation_memory_items(self, **kwargs):
        del kwargs
        return []


class _FakeContactDatabase:
    def __init__(self, contacts: list[dict]) -> None:
        self.contacts = list(contacts)
        self.calls: list[dict] = []
        self.resolve_calls: list[dict] = []

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
                    id="search_memory",
                    action="memory.search",
                    args={
                        "participants": ["test3"],
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


def test_ai_action_planner_prompt_routes_history_queries_out_of_workflow() -> None:
    system_prompt = AIActionPlanner._system_prompt(AIActionPlanner.PROMPT_NEW_ACTION)
    user_prompt = AIActionPlanner._user_prompt("我和test3昨天聊了什么？")

    assert "contact.resolve, message.draft, user.confirm, message.send" in system_prompt
    assert "不属于 action workflow" in system_prompt
    assert "memory.search" not in system_prompt
    assert "memory.summarize" not in system_prompt
    assert "询问历史、回顾、总结、检索内容时输出 is_action=false" in user_prompt
    assert "发送消息的组合是 contact.resolve -> message.draft -> user.confirm -> message.send" in user_prompt
    assert "memory.search" not in user_prompt
    assert "memory.summarize" not in user_prompt


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


def test_ai_action_registry_only_exposes_execution_actions() -> None:
    registry = AtomicActionRegistry(
        contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
    )

    assert registry.names() == (
        "contact.resolve",
        "message.draft",
        "message.send",
        "user.confirm",
    )
    assert registry.get("memory.search") is None
    assert registry.get("memory.summarize") is None


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


def test_ai_action_workflow_ignores_atomic_read_plan(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_AtomicReadPlanner(),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="我和test3聊过什么？")
            assert result.handled is False
            assert await store.latest_pending_plan("thread-1") is None
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
