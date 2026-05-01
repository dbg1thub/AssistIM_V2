import asyncio
import time
from dataclasses import replace
from types import SimpleNamespace

from client.managers import ai_action_registry as registry_module
from client.managers import ai_action_executor as executor_module
from client.managers.ai_action_cache import AIActionCache
from client.managers.ai_action_executor import AIActionExecutor, ActionRuntimeBudget
from client.managers.ai_action_memory_summarizer import AIActionMemorySummarizer
from client.managers.ai_action_normalizer import AIPlanNormalizer
from client.managers.ai_action_optimizer import AIPlanOptimizer
from client.managers.ai_action_permission_policy import AIPermissionPolicy, AIPermissionScope, PermissionDecision
from client.managers.ai_action_resource_manager import AIResourceManager, ResourceBudget
from client.managers.ai_action_registry import AIActionMessageSender, AtomicActionRegistry
from client.managers.ai_action_types import AIActionPlan, AIActionStep, AtomicActionSpec
from client.managers.ai_action_validator import AIPlanValidator
from client.managers.ai_action_workflow import (
    AIActionPlanner,
    AIActionWorkflow,
    ContactAliasResolver,
    PendingPlannerState,
)
from client.models.message import MessageStatus, Session
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


class _FakeActionMessageSender:
    def __init__(self, *, result: dict | None = None) -> None:
        self.result = dict(result or {})
        self.calls: list[dict] = []

    async def send_text_to_contact(
        self,
        *,
        target: dict,
        content: str,
        idempotency_key: str,
        plan_id: str,
    ) -> dict:
        self.calls.append(
            {
                "target": dict(target or {}),
                "content": content,
                "idempotency_key": idempotency_key,
                "plan_id": plan_id,
            }
        )
        if self.result:
            return dict(self.result)
        return {
            "status": "sent",
            "text": f"已发送给{target.get('display_name') or target.get('contact_id')}。",
            "target": dict(target or {}),
            "content_chars": len(content),
            "session_id": "session-direct-1",
            "message_id": "message-ai-1",
        }


class _FakeDirectMessageManager:
    def __init__(self, *, status=MessageStatus.SENDING) -> None:
        self.status = status
        self.calls: list[dict] = []

    async def send_message(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(status=self.status, message_id="message-ai-1")


class _FakePlannerTaskManager:
    def __init__(self, raw_output: str) -> None:
        self.raw_output = raw_output
        self.requests: list = []

    async def run_once(self, request):
        self.requests.append(request)
        return SimpleNamespace(
            content=self.raw_output,
            provider="fake",
            model="planner-test",
            error_code=None,
            error_message="",
        )


class _FakeMemorySummarizer:
    def __init__(self, text: str = "根据检索结果，主要讨论了项目排期。", *, model_tokens: int = 0) -> None:
        self.text = text
        self.model_tokens = int(model_tokens or 0)
        self.calls: list[dict] = []

    async def summarize(self, **kwargs):
        self.calls.append(dict(kwargs))
        output = {
            "text": self.text,
            "summary_model_id": "fake-memory-summarizer",
        }
        if self.model_tokens:
            output["model_tokens"] = self.model_tokens
            output["usage"] = {"total_tokens": self.model_tokens}
        return output


class _FailingMemorySummarizer:
    def __init__(self, error_text: str = "MEMORY_SUMMARIZE_FAILED") -> None:
        self.error_text = error_text
        self.calls: list[dict] = []

    async def summarize(self, **kwargs):
        self.calls.append(dict(kwargs))
        raise RuntimeError(self.error_text)


class _FakeSummaryTaskManager:
    def __init__(self) -> None:
        self.requests: list = []

    async def run_once(self, request):
        self.requests.append(request)
        stage = str(request.metadata.get("summary_stage") or "")
        content = "最终总结：README.md 主要介绍 AssistIM。" if stage == "final" else f"分块总结 {len(self.requests)}"
        return SimpleNamespace(
            content=content,
            provider="fake",
            model="summary-test",
            error_code=None,
            error_message="",
        )


class _UsageSummaryTaskManager:
    def __init__(self, usage: dict[str, int]) -> None:
        self.usage = dict(usage)
        self.requests: list = []

    async def run_once(self, request):
        self.requests.append(request)
        return SimpleNamespace(
            content="最终总结：README.md 主要介绍 AssistIM。",
            provider="fake",
            model="summary-test",
            error_code=None,
            error_message="",
            metadata={"usage": dict(self.usage)},
        )


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
            return AIActionPlan(is_action=True, control={"type": "cancel"})
        if pending_state is not None and user_text == "确认":
            return AIActionPlan(is_action=True, control={"type": "confirm"})
        if user_text == "帮我给张三发我晚点到":
            return _atomic_send_plan(user_text=user_text)
        if "聊了什么" in user_text or "聊过什么" in user_text:
            return await _AtomicReadPlanner().plan(user_text)
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
            return _atomic_send_plan(user_text=user_text)
        return AIActionPlan(is_action=False)


class _LegacyBusinessActionPlanner:
    async def plan(self, *args, **kwargs):
        user_text = str(args[0] if args else "").strip()
        del kwargs
        if user_text == "帮我给张三发我晚点到":
            return AIActionPlan.from_dict(
                {
                    "is_action": True,
                    "goal": user_text,
                    "risk": "high",
                    "action": "send_message",
                    "requires_side_effect": True,
                    "slots": {"target_user": "张三", "message_text": "我晚点到"},
                    "steps": [],
                    "final": {},
                }
            )
        if "聊了什么" in user_text or "聊过什么" in user_text:
            return AIActionPlan.from_dict(
                {
                    "is_action": True,
                    "goal": user_text,
                    "risk": "low",
                    "action": "memory_query",
                    "requires_app_data": True,
                    "slots": {"participants": ["test3"]},
                    "steps": [],
                    "final": {},
                }
            )
        return AIActionPlan(is_action=False)


def _atomic_send_plan(*, user_text: str = "帮我给张三发我晚点到") -> AIActionPlan:
    return AIActionPlan(
        is_action=True,
        goal=user_text,
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
                args={"target": "$resolve_target.contacts[0]", "content": "我晚点到"},
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


class _NonCanonicalAtomicSendPlanner:
    async def plan(self, *args, **kwargs):
        user_text = str(args[0] if args else "").strip()
        del kwargs
        return AIActionPlan(
            is_action=True,
            goal=user_text,
            risk="high",
            steps=(
                AIActionStep(
                    id="resolve_target",
                    action="contact.resolve",
                    args={"queries": ["test3"], "allow_multiple": False},
                ),
                AIActionStep(
                    id="resolve_target_again",
                    action="contact.resolve",
                    args={"queries": ["test3"], "allow_multiple": False},
                ),
                AIActionStep(
                    id="draft_message",
                    action="message.draft",
                    depends_on=("resolve_target",),
                    args={"target": "$resolve_target.contacts[0]", "content": "我晚点联系他"},
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
                    depends_on=("confirm_send",),
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


class _TooManyStepsPlanner:
    async def plan(self, *args, **kwargs):
        user_text = str(args[0] if args else "").strip()
        del kwargs
        steps = []
        for index in range(1, 22):
            step_id = f"search_{index}"
            steps.append(
                AIActionStep(
                    id=step_id,
                    action="memory.search",
                    depends_on=(f"search_{index - 1}",) if index > 1 else (),
                    args={
                        "participant_match": "any",
                        "time_scope": {"type": "all_history"},
                        "keywords": [],
                        "question": user_text,
                    },
                )
            )
        return AIActionPlan(
            is_action=True,
            goal=user_text,
            risk="low",
            steps=tuple(steps),
            final={"type": "answer", "source": "$search_21.context_lines"},
        )


class _TooManyContactsPlanner:
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
                    args={"queries": [f"用户{index}" for index in range(1, 7)], "allow_multiple": True},
                ),
            ),
            final={"type": "answer", "source": "$resolve_contacts.contacts"},
        )


class _TooManyWriteActionsPlanner:
    async def plan(self, *args, **kwargs):
        user_text = str(args[0] if args else "").strip()
        del kwargs
        return AIActionPlan(
            is_action=True,
            goal=user_text,
            risk="high",
            steps=(
                AIActionStep(
                    id="resolve_target",
                    action="contact.resolve",
                    args={"queries": ["张三"], "allow_multiple": False},
                ),
                AIActionStep(
                    id="draft_first",
                    action="message.draft",
                    depends_on=("resolve_target",),
                    args={"target": "$resolve_target.contacts[0]", "content": "第一条"},
                ),
                AIActionStep(
                    id="confirm_first",
                    action="user.confirm",
                    depends_on=("draft_first",),
                    args={
                        "risk": "high",
                        "preview": {
                            "operation": "发送消息",
                            "target": "$draft_first.target",
                            "content": "$draft_first.content",
                        },
                    },
                ),
                AIActionStep(
                    id="send_first",
                    action="message.send",
                    depends_on=("confirm_first", "draft_first"),
                    args={
                        "target": "$draft_first.target_entity",
                        "content": "$draft_first.content",
                        "preview": "$draft_first.preview",
                        "idempotency_key": "$draft_first.idempotency_key",
                    },
                ),
                AIActionStep(
                    id="draft_second",
                    action="message.draft",
                    depends_on=("resolve_target",),
                    args={"target": "$resolve_target.contacts[0]", "content": "第二条"},
                ),
                AIActionStep(
                    id="confirm_second",
                    action="user.confirm",
                    depends_on=("draft_second",),
                    args={
                        "risk": "high",
                        "preview": {
                            "operation": "发送消息",
                            "target": "$draft_second.target",
                            "content": "$draft_second.content",
                        },
                    },
                ),
                AIActionStep(
                    id="send_second",
                    action="message.send",
                    depends_on=("confirm_second", "draft_second"),
                    args={
                        "target": "$draft_second.target_entity",
                        "content": "$draft_second.content",
                        "preview": "$draft_second.preview",
                        "idempotency_key": "$draft_second.idempotency_key",
                    },
                ),
            ),
            final={"type": "answer", "source": "$send_second.text"},
        )


class _TooManyModelCallsPlanner:
    async def plan(self, *args, **kwargs):
        user_text = str(args[0] if args else "").strip()
        del kwargs
        summarize_steps = []
        for index in range(1, 5):
            summarize_steps.append(
                AIActionStep(
                    id=f"summarize_{index}",
                    action="memory.summarize",
                    depends_on=(f"summarize_{index - 1}",) if index > 1 else ("search_memory",),
                    args={"source": "$search_memory", "question": user_text},
                )
            )
        return AIActionPlan(
            is_action=True,
            goal=user_text,
            risk="low",
            steps=(
                AIActionStep(
                    id="search_memory",
                    action="memory.search",
                    args={
                        "participant_match": "any",
                        "time_scope": {"type": "all_history"},
                        "keywords": [],
                        "question": user_text,
                    },
                ),
                *summarize_steps,
            ),
            final={"type": "answer", "source": "$summarize_4"},
        )


class _TooManyMemoryResultsPlanner:
    async def plan(self, *args, **kwargs):
        user_text = str(args[0] if args else "").strip()
        del kwargs
        return AIActionPlan(
            is_action=True,
            goal=user_text,
            risk="low",
            steps=(
                AIActionStep(
                    id="search_first",
                    action="memory.search",
                    args={
                        "participant_match": "any",
                        "time_scope": {"type": "all_history"},
                        "keywords": ["第一批"],
                        "question": f"{user_text} 第一批",
                        "limit": 50,
                    },
                ),
                AIActionStep(
                    id="search_second",
                    action="memory.search",
                    args={
                        "participant_match": "any",
                        "time_scope": {"type": "all_history"},
                        "keywords": ["第二批"],
                        "question": f"{user_text} 第二批",
                        "limit": 50,
                    },
                ),
                AIActionStep(
                    id="summarize_memory",
                    action="memory.summarize",
                    depends_on=("search_first", "search_second"),
                    args={
                        "source": {"first": "$search_first", "second": "$search_second"},
                        "question": user_text,
                    },
                ),
            ),
            final={"type": "answer", "source": "$summarize_memory"},
        )


class _TokenBudgetPlanner:
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


class _InvalidReferenceThenFixedPlanner:
    def __init__(self) -> None:
        self.plan_calls = 0
        self.repair_calls: list[dict] = []

    async def plan(self, *args, **kwargs):
        self.plan_calls += 1
        user_text = str(args[0] if args else "").strip()
        del kwargs
        return AIActionPlan(
            is_action=True,
            goal=user_text,
            risk="low",
            steps=(
                AIActionStep(
                    id="%step_0",
                    action="contact.resolve",
                    args={"queries": ["test3"], "allow_multiple": True},
                ),
                AIActionStep(
                    id="%step_1",
                    action="memory.search",
                    depends_on=("%step_0",),
                    args={
                        "participants": "$resolve_contacts.contacts",
                        "participant_match": "test3",
                        "time_scope": {"type": "all_history"},
                        "keywords": [],
                        "question": user_text,
                    },
                ),
                AIActionStep(
                    id="%step_2",
                    action="memory.summarize",
                    depends_on=("%step_1",),
                    args={"source": "$search_memory", "question": user_text},
                ),
            ),
            final={"type": "answer", "source": "$summarize_memory"},
        )

    async def repair_plan(self, user_text: str, *, invalid_plan, validation_errors, pending_state=None, strict: bool = True):
        self.repair_calls.append(
            {
                "user_text": user_text,
                "pending": pending_state is not None,
                "strict": strict,
                "errors": list(validation_errors),
                "invalid_plan": invalid_plan,
            }
        )
        return await _AtomicReadPlanner().plan(user_text)


class _AlwaysInvalidReferencePlanner(_InvalidReferenceThenFixedPlanner):
    async def repair_plan(self, user_text: str, *, invalid_plan, validation_errors, pending_state=None, strict: bool = True):
        self.repair_calls.append(
            {
                "user_text": user_text,
                "pending": pending_state is not None,
                "strict": strict,
                "errors": list(validation_errors),
                "invalid_plan": invalid_plan,
            }
        )
        return await self.plan(user_text)


class _InvalidWriteUnknownActionRepairWouldSendPlanner:
    def __init__(self) -> None:
        self.plan_calls = 0
        self.repair_calls: list[dict] = []

    async def plan(self, *args, **kwargs):
        self.plan_calls += 1
        user_text = str(args[0] if args else "").strip()
        del kwargs
        return AIActionPlan(
            is_action=True,
            goal=user_text,
            risk="high",
            steps=(
                AIActionStep(
                    id="resolve_target",
                    action="contact.resolve",
                    args={"queries": ["服务器数据库"], "allow_multiple": False},
                ),
                AIActionStep(
                    id="draft_message",
                    action="message.draft",
                    depends_on=("resolve_target",),
                    args={"target": "$resolve_target.contacts[0]", "content": "请确认删除服务器数据库。"},
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
                    depends_on=("confirm_send",),
                    args={
                        "target": "$draft_message.target_entity",
                        "content": "$draft_message.content",
                        "preview": "$draft_message.preview",
                        "idempotency_key": "$draft_message.idempotency_key",
                    },
                ),
                AIActionStep(
                    id="delete_db",
                    action="system_action",
                    depends_on=("send_message",),
                    args={"database_name": "服务器数据库"},
                ),
            ),
            final={},
        )

    async def repair_plan(self, user_text: str, *, invalid_plan, validation_errors, pending_state=None, strict: bool = True):
        self.repair_calls.append(
            {
                "user_text": user_text,
                "pending": pending_state is not None,
                "strict": strict,
                "errors": list(validation_errors),
                "invalid_plan": invalid_plan,
            }
        )
        return _atomic_send_plan(user_text=user_text)


class _InvalidWriteBadReadTailRepairWouldSendPlanner(_InvalidWriteUnknownActionRepairWouldSendPlanner):
    async def plan(self, *args, **kwargs):
        self.plan_calls += 1
        user_text = str(args[0] if args else "").strip()
        del kwargs
        return AIActionPlan(
            is_action=True,
            goal=user_text,
            risk="low",
            steps=(
                AIActionStep(
                    id="resolve_target",
                    action="contact.resolve",
                    args={"queries": ["这个群里"], "allow_multiple": False},
                ),
                AIActionStep(
                    id="draft_message",
                    action="message.draft",
                    depends_on=("resolve_target",),
                    args={"target": "$resolve_target.contacts[0]", "content": "生成推荐回复"},
                ),
                AIActionStep(
                    id="confirm_send",
                    action="user.confirm",
                    depends_on=("draft_message",),
                    args={
                        "risk": "low",
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
                    depends_on=("confirm_send",),
                    args={
                        "target": "$draft_message.target_entity",
                        "content": "$draft_message.content",
                        "preview": "$draft_message.preview",
                        "idempotency_key": "$draft_message.idempotency_key",
                    },
                ),
                AIActionStep(
                    id="summarize_memory",
                    action="memory.summarize",
                    args={"source": None, "question": user_text},
                ),
            ),
            final={},
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


def test_ai_action_planner_schema_uses_atomic_steps_or_control_not_legacy_slots() -> None:
    new_schema = AIActionPlanner.NEW_ACTION_SCHEMA
    control_schema = AIActionPlanner.PENDING_CONTROL_SCHEMA

    assert "control" in control_schema["properties"]
    assert "action" not in new_schema["properties"]
    assert "slots" not in new_schema["properties"]
    assert "missing_slots" not in new_schema["properties"]
    assert "action" not in control_schema["properties"]
    assert "slots" not in control_schema["properties"]
    assert "missing_slots" not in control_schema["properties"]


def test_ai_action_planner_uses_state_specific_prompt_templates() -> None:
    confirmation_state = PendingPlannerState(
        id="plan-1",
        thread_id="thread-1",
        ai_thread_id="thread-1",
        state="waiting_confirmation",
        waiting_payload={"type": "confirmation", "preview": {"operation": "发送消息", "target": "张三"}},
    )
    contact_state = PendingPlannerState(
        id="plan-2",
        thread_id="thread-1",
        ai_thread_id="thread-1",
        state="waiting_clarification",
        waiting_payload={"type": "contact_ambiguity", "candidates": [{"contact_id": "user-1"}]},
    )
    clarification_state = PendingPlannerState(
        id="plan-3",
        thread_id="thread-1",
        ai_thread_id="thread-1",
        state="waiting_clarification",
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
        state="waiting_confirmation",
        waiting_payload={"type": "confirmation", "preview": {"operation": "发送消息", "target": "张三"}},
    )
    contact_state = PendingPlannerState(
        id="plan-2",
        thread_id="thread-1",
        ai_thread_id="thread-1",
        state="waiting_clarification",
        waiting_payload={"type": "contact_ambiguity", "candidates": [{"contact_id": "user-1"}]},
    )
    clarification_state = PendingPlannerState(
        id="plan-3",
        thread_id="thread-1",
        ai_thread_id="thread-1",
        state="waiting_clarification",
        waiting_payload={"type": "clarification", "missing": ["message_text"]},
    )

    confirmation_prompt = AIActionPlanner._user_prompt("确认", pending_state=confirmation_state)
    contact_prompt = AIActionPlanner._user_prompt("2", pending_state=contact_state)
    clarification_prompt = AIActionPlanner._user_prompt("我晚点到", pending_state=clarification_state)

    assert '"control": {"type": "confirm"}' in confirmation_prompt
    assert '"control": {"type": "select_contact_alias"' in contact_prompt
    assert '"control": {"type": "cancel"}' in clarification_prompt
    assert "memory.search" not in confirmation_prompt
    assert "memory.search" not in contact_prompt
    assert "memory.search" not in clarification_prompt
    assert "contact.resolve -> message.draft -> user.confirm -> message.send" in clarification_prompt


def test_ai_plan_normalizer_rejects_legacy_single_business_actions() -> None:
    normalizer = AIPlanNormalizer()
    for payload in (
        {
            "is_action": True,
            "goal": "旧发送",
            "risk": "high",
            "action": "send_message",
            "slots": {"target_user": "张三", "message_text": "我晚点到"},
            "steps": [],
            "final": {},
        },
        {
            "is_action": True,
            "goal": "旧查询",
            "risk": "low",
            "action": "memory_query",
            "slots": {"participants": ["test3"]},
            "steps": [],
            "final": {},
        },
        {
            "is_action": True,
            "goal": "旧加好友",
            "risk": "high",
            "action": "add_friend",
            "slots": {"target_user": "张三"},
            "steps": [],
            "final": {},
        },
        {
            "is_action": True,
            "goal": "旧发朋友圈",
            "risk": "high",
            "action": "post_moment",
            "slots": {"content": "今天很开心"},
            "steps": [],
            "final": {},
        },
    ):
        normalized = normalizer.normalize(AIActionPlan.from_dict(payload), user_text=str(payload["goal"]))

        assert normalized.is_action is False
        assert normalized.steps == ()
        assert normalized.control == {}


def test_ai_plan_normalizer_adds_dependencies_for_existing_arg_refs() -> None:
    normalizer = AIPlanNormalizer()
    plan = AIActionPlan(
        is_action=True,
        goal="查询历史",
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
                args={
                    "participants": "$resolve_contacts.contacts",
                    "participant_match": "any",
                    "time_scope": {"type": "all_history"},
                    "keywords": [],
                    "question": "我和 test3 聊过什么？",
                },
            ),
            AIActionStep(
                id="summarize_memory",
                action="memory.summarize",
                args={"source": "$search_memory", "question": "我和 test3 聊过什么？"},
            ),
        ),
        final={"type": "answer", "source": "$summarize_memory"},
    )

    normalized = normalizer.normalize(plan, user_text="我和 test3 聊过什么？")

    assert normalized.is_action is True
    search = next(step for step in normalized.steps if step.id == "search_memory")
    summarize = next(step for step in normalized.steps if step.id == "summarize_memory")
    assert search.depends_on == ("resolve_contacts",)
    assert summarize.depends_on == ("search_memory",)


def test_ai_plan_validator_rejects_unresolved_step_reference() -> None:
    registry = AtomicActionRegistry(
        contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        memory_manager=_FakeActionMemoryManager(),
    )
    validator = AIPlanValidator(registry=registry)
    plan = AIActionPlan(
        is_action=True,
        goal="查询历史",
        risk="low",
        steps=(
            AIActionStep(
                id="%step_0",
                action="contact.resolve",
                args={"queries": ["test3"], "allow_multiple": True},
            ),
            AIActionStep(
                id="%step_1",
                action="memory.search",
                depends_on=("%step_0",),
                args={
                    "participants": "$resolve_contacts.contacts",
                    "participant_match": "any",
                    "time_scope": {"type": "all_history"},
                    "keywords": [],
                    "question": "我和 test3 聊过什么？",
                },
            ),
        ),
        final={"type": "answer", "source": "$search_memory"},
    )

    result = validator.validate(plan)

    assert result.allowed is False
    assert any(error.code == "ARG_REFERENCE_INVALID" for error in result.errors)
    assert "ARG_REFERENCE_INVALID" in result.repair_instructions()


def test_ai_plan_validator_rejects_duplicate_step_id_unknown_action_and_bad_participant_match() -> None:
    registry = AtomicActionRegistry(
        contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        memory_manager=_FakeActionMemoryManager(),
    )
    validator = AIPlanValidator(registry=registry)
    plan = AIActionPlan(
        is_action=True,
        goal="查询历史",
        risk="low",
        steps=(
            AIActionStep(
                id="search_memory",
                action="memory.search",
                args={
                    "participant_match": "test3",
                    "time_scope": {"type": "all_history"},
                    "keywords": [],
                    "question": "我和 test3 聊过什么？",
                },
            ),
            AIActionStep(
                id="search_memory",
                action="memory.lookup",
                args={},
            ),
        ),
        final={"type": "answer", "source": "$search_memory"},
    )

    result = validator.validate(plan)
    codes = [error.code for error in result.errors]

    assert result.allowed is False
    assert "PLAN_SCHEMA_INVALID" in codes
    assert "ACTION_NOT_FOUND" in codes
    assert "ARG_SCHEMA_INVALID" in codes


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


def test_ai_action_registry_default_specs_declare_platform_boundaries() -> None:
    registry = AtomicActionRegistry(
        contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        memory_manager=_FakeActionMemoryManager(),
    )

    for action_name in registry.names():
        spec = registry.get(action_name)
        assert spec is not None
        assert spec.name == action_name
        assert spec.kind in {"read", "write"}
        assert spec.risk_level in {"low", "medium", "high"}
        assert spec.max_input_bytes > 0
        assert spec.max_output_json_bytes > 0
        assert spec.timeout_ms > 0
        assert spec.estimated_input_tokens >= 0
        assert spec.estimated_output_tokens >= 0
        if spec.kind == "read":
            assert spec.allow_side_effect is False

    summarize = registry.get("memory.summarize")
    assert summarize is not None
    assert summarize.model_call_cost == 1
    assert summarize.estimated_input_tokens > 0
    assert summarize.estimated_output_tokens > 0

    send = registry.get("message.send")
    assert send is not None
    assert send.kind == "write"
    assert send.risk_level == "high"
    assert send.allow_side_effect is True
    assert send.requires_confirmation is True
    assert send.max_targets == 1
    assert send.allow_batch is False
    assert send.require_resolved_target is True
    assert send.require_preview is True
    assert send.idempotency_required is True
    assert send.allow_auto_resume_after_confirm is False


def test_ai_action_registry_rejects_invalid_platform_boundaries() -> None:
    invalid_specs = [
        AtomicActionSpec(name="test.bad_read", kind="read", risk_level="low", allow_side_effect=True),
        AtomicActionSpec(name="test.bad_input_tokens", kind="read", risk_level="low", estimated_input_tokens=-1),
        AtomicActionSpec(name="test.bad_output_tokens", kind="read", risk_level="low", estimated_output_tokens=-1),
        AtomicActionSpec(name="test.bad_write_risk", kind="write", risk_level="medium", allow_side_effect=True),
        AtomicActionSpec(name="test.bad_write_effect", kind="write", risk_level="high", allow_side_effect=False),
        AtomicActionSpec(
            name="test.bad_write_confirmation",
            kind="write",
            risk_level="high",
            allow_side_effect=True,
            requires_confirmation=False,
        ),
        AtomicActionSpec(
            name="test.bad_write_preview",
            kind="write",
            risk_level="high",
            allow_side_effect=True,
            requires_confirmation=True,
            require_preview=False,
            idempotency_required=True,
            max_targets=1,
        ),
        AtomicActionSpec(
            name="test.bad_write_idempotency",
            kind="write",
            risk_level="high",
            allow_side_effect=True,
            requires_confirmation=True,
            require_preview=True,
            idempotency_required=False,
            max_targets=1,
        ),
        AtomicActionSpec(
            name="test.bad_write_targets",
            kind="write",
            risk_level="high",
            allow_side_effect=True,
            requires_confirmation=True,
            require_preview=True,
            idempotency_required=True,
            max_targets=2,
        ),
        AtomicActionSpec(
            name="test.bad_write_resume",
            kind="write",
            risk_level="high",
            allow_side_effect=True,
            requires_confirmation=True,
            require_preview=True,
            idempotency_required=True,
            max_targets=1,
            allow_auto_resume_after_confirm=True,
        ),
    ]

    for spec in invalid_specs:
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            memory_manager=_FakeActionMemoryManager(),
        )
        try:
            registry._register(spec)
        except ValueError as exc:
            assert "ACTION_SPEC_INVALID" in str(exc)
            assert spec.name in str(exc)
        else:
            raise AssertionError(f"invalid action spec should be rejected: {spec.name}")


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


def test_ai_action_optimizer_merges_duplicate_memory_summarize_and_updates_refs() -> None:
    optimizer = AIPlanOptimizer()
    summarize_args = {
        "source": "$search_memory",
        "question": "我和 test3 聊过什么？",
        "style": "summary",
    }
    plan = AIActionPlan(
        is_action=True,
        goal="history",
        risk="low",
        steps=(
            AIActionStep(
                id="search_memory",
                action="memory.search",
                args={
                    "participants": "$resolve_contacts.contacts",
                    "participant_match": "any",
                    "time_scope": {"type": "all_history"},
                    "question": "我和 test3 聊过什么？",
                },
            ),
            AIActionStep(
                id="summarize_a",
                action="memory.summarize",
                depends_on=("search_memory",),
                args=dict(summarize_args),
            ),
            AIActionStep(
                id="summarize_b",
                action="memory.summarize",
                depends_on=("search_memory",),
                args=dict(summarize_args),
            ),
        ),
        final={"type": "answer", "source": "$summarize_b.text", "details": ["$summarize_b.context_lines"]},
    )

    optimized, reason = optimizer.optimize(plan)

    assert reason == "optimizer_merge_duplicate_memory_summarize"
    assert [step.id for step in optimized.steps] == ["search_memory", "summarize_a"]
    assert optimized.final == {
        "type": "answer",
        "source": "$summarize_a.text",
        "details": ["$summarize_a.context_lines"],
    }


def test_ai_action_optimizer_keeps_distinct_memory_summarize_steps() -> None:
    optimizer = AIPlanOptimizer()
    plan = AIActionPlan(
        is_action=True,
        goal="history",
        risk="low",
        steps=(
            AIActionStep(
                id="search_memory",
                action="memory.search",
                args={
                    "participants": "$resolve_contacts.contacts",
                    "participant_match": "any",
                    "time_scope": {"type": "all_history"},
                    "question": "我和 test3 聊过什么？",
                },
            ),
            AIActionStep(
                id="summarize_brief",
                action="memory.summarize",
                depends_on=("search_memory",),
                args={"source": "$search_memory", "question": "我和 test3 聊过什么？", "style": "brief"},
            ),
            AIActionStep(
                id="summarize_detail",
                action="memory.summarize",
                depends_on=("search_memory",),
                args={"source": "$search_memory", "question": "我和 test3 聊过什么？", "style": "detail"},
            ),
        ),
        final={"type": "answer", "sources": ["$summarize_brief", "$summarize_detail"]},
    )

    optimized, reason = optimizer.optimize(plan)

    assert reason == ""
    assert [step.id for step in optimized.steps] == ["search_memory", "summarize_brief", "summarize_detail"]


def test_ai_action_optimizer_does_not_merge_per_contact_summaries() -> None:
    optimizer = AIPlanOptimizer()
    plan = AIActionPlan(
        is_action=True,
        goal="history",
        risk="low",
        steps=(
            AIActionStep(
                id="search_test1",
                action="memory.search",
                args={
                    "participants": [{"display_name": "test1"}],
                    "participant_match": "any",
                    "time_scope": {"type": "all_history"},
                    "question": "我和 test1 聊过什么？",
                },
            ),
            AIActionStep(
                id="summarize_test1",
                action="memory.summarize",
                depends_on=("search_test1",),
                args={"source": "$search_test1", "question": "我和 test1 聊过什么？"},
            ),
            AIActionStep(
                id="search_test3",
                action="memory.search",
                args={
                    "participants": [{"display_name": "test3"}],
                    "participant_match": "any",
                    "time_scope": {"type": "all_history"},
                    "question": "我和 test3 聊过什么？",
                },
            ),
            AIActionStep(
                id="summarize_test3",
                action="memory.summarize",
                depends_on=("search_test3",),
                args={"source": "$search_test3", "question": "我和 test3 聊过什么？"},
            ),
        ),
        final={"type": "answer", "sources": ["$summarize_test1", "$summarize_test3"]},
    )

    optimized, reason = optimizer.optimize(plan)

    assert reason == ""
    assert [step.id for step in optimized.steps] == [
        "search_test1",
        "summarize_test1",
        "search_test3",
        "summarize_test3",
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


def test_ai_action_workflow_canonicalizes_noncanonical_send_confirmation(tmp_path, monkeypatch) -> None:
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
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_NonCanonicalAtomicSendPlanner(),
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
            message_sender=_FakeActionMessageSender(),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="给test3说我晚点联系他")

            assert result.handled is True
            assert result.message_extra["ai_action"]["state"] == "waiting_confirmation"
            assert result.message_extra["ai_action"]["action"] == "send_message"
            assert "确认要发送消息给test3" in result.response_text
            assert "我晚点联系他" in result.response_text
            record = await store.latest_pending_plan("thread-1")
            assert record is not None
            send = next(step for step in record.plan_json["steps"] if step["action"] == "message.send")
            assert "confirm_send" in send["depends_on"]
            assert "draft_message" in send["depends_on"]
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_emits_action_progress_updates(tmp_path, monkeypatch) -> None:
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
        progress_updates = []

        async def on_progress(turn) -> None:
            progress_updates.append(turn)

        try:
            result = await workflow.handle_user_turn(
                thread_id="thread-1",
                text="帮我给张三发我晚点到",
                progress_callback=on_progress,
            )

            assert result.handled is True
            assert progress_updates
            progress_extras = [item.message_extra["ai_action"] for item in progress_updates]
            assert progress_extras[-1]["state"] == result.message_extra["ai_action"]["state"]
            assert progress_extras[-1]["current_step_id"] == result.message_extra["ai_action"]["current_step_id"]
            assert any(extra["state"] == "running" for extra in progress_extras)
            assert any(extra["current_step_id"] == "resolve_target" for extra in progress_extras)
            assert any(
                step["id"] == "resolve_target" and step["state"] == "done"
                for extra in progress_extras
                for step in extra["steps"]
            )
            assert result.message_extra["ai_action"]["state"] == "waiting_confirmation"
            assert result.message_extra["ai_action"]["current_step_id"] == "confirm_send"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_records_too_many_steps_resource_reason(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        memory_manager = _FakeActionMemoryManager()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_TooManyStepsPlanner(),
            memory_manager=memory_manager,
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="帮我查很多内容")
            assert result.handled is True
            action_extra = result.message_extra["ai_action"]
            assert action_extra["state"] == "waiting_clarification"
            assert "步骤太多" in result.response_text
            assert action_extra["waiting"]["reason"] == "resource_limit"
            assert action_extra["waiting"]["resource_reason"] == "too_many_steps"

            plan = await store.get_plan(action_extra["plan_id"])
            assert plan is not None
            assert plan.state == "waiting_clarification"
            assert plan.waiting_payload["resource_reason"] == "too_many_steps"
            assert plan.current_step_id == ""
            assert plan.step_outputs == {}
            assert memory_manager.calls == []
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_records_too_many_contacts_resource_reason(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        contact_db = _FakeContactDatabase([])
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_TooManyContactsPlanner(),
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="帮我找很多联系人")
            assert result.handled is True
            action_extra = result.message_extra["ai_action"]
            assert action_extra["state"] == "waiting_clarification"
            assert "最多处理 5 个" in result.response_text
            assert action_extra["waiting"]["reason"] == "resource_limit"
            assert action_extra["waiting"]["resource_reason"] == "too_many_contacts"

            plan = await store.get_plan(action_extra["plan_id"])
            assert plan is not None
            assert plan.state == "waiting_clarification"
            assert plan.waiting_payload["resource_reason"] == "too_many_contacts"
            assert plan.current_step_id == ""
            assert plan.step_outputs == {}
            assert contact_db.resolve_calls == []
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_records_too_many_write_actions_resource_reason(tmp_path, monkeypatch) -> None:
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
            planner=_TooManyWriteActionsPlanner(),
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="帮我连续发两条消息")
            assert result.handled is True
            action_extra = result.message_extra["ai_action"]
            assert action_extra["state"] == "waiting_clarification"
            assert "一次只能确认一个" in result.response_text
            assert action_extra["waiting"]["reason"] == "resource_limit"
            assert action_extra["waiting"]["resource_reason"] == "too_many_write_actions"

            plan = await store.get_plan(action_extra["plan_id"])
            assert plan is not None
            assert plan.state == "waiting_clarification"
            assert plan.waiting_payload["resource_reason"] == "too_many_write_actions"
            assert plan.current_step_id == ""
            assert plan.step_outputs == {}
            assert contact_db.resolve_calls == []
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_resource_manager_counts_write_actions_from_registry_specs() -> None:
    registry = AtomicActionRegistry(contact_resolver=SimpleNamespace())
    registry._actions["test.write"] = AtomicActionSpec(name="test.write", kind="write", risk_level="high")
    manager = AIResourceManager(registry=registry)
    plan = AIActionPlan(
        is_action=True,
        goal="执行两个写操作",
        risk="high",
        steps=(
            AIActionStep(id="write_first", action="test.write", args={}),
            AIActionStep(id="write_second", action="test.write", args={}),
        ),
        final={"type": "answer", "source": "$write_second"},
    )

    result = manager.check_plan(plan)

    assert result.allowed is False
    assert result.reason == "too_many_write_actions"
    assert result.estimate["write_actions"] == 2


def test_ai_action_workflow_records_too_many_model_calls_resource_reason(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        memory_manager = _FakeActionMemoryManager(context_lines=["项目排期"])
        memory_summarizer = _FakeMemorySummarizer()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_TooManyModelCallsPlanner(),
            memory_manager=memory_manager,
            memory_summarizer=memory_summarizer,
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="帮我总结很多轮记录")
            assert result.handled is True
            action_extra = result.message_extra["ai_action"]
            assert action_extra["state"] == "waiting_clarification"
            assert "模型调用次数" in result.response_text
            assert action_extra["waiting"]["reason"] == "resource_limit"
            assert action_extra["waiting"]["resource_reason"] == "too_many_model_calls"
            assert action_extra["waiting"]["resource_estimate"]["model_calls"] == 4

            plan = await store.get_plan(action_extra["plan_id"])
            assert plan is not None
            assert plan.state == "waiting_clarification"
            assert plan.waiting_payload["resource_reason"] == "too_many_model_calls"
            assert plan.waiting_payload["resource_estimate"]["model_calls"] == 4
            assert plan.current_step_id == ""
            assert plan.step_outputs == {}
            assert memory_manager.calls == []
            assert memory_summarizer.calls == []
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_records_too_many_memory_results_resource_reason(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        memory_manager = _FakeActionMemoryManager(context_lines=["项目排期"])
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_TooManyMemoryResultsPlanner(),
            memory_manager=memory_manager,
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="帮我查很多聊天记录")
            assert result.handled is True
            action_extra = result.message_extra["ai_action"]
            assert action_extra["state"] == "waiting_clarification"
            assert "检索结果" in result.response_text
            assert action_extra["waiting"]["reason"] == "resource_limit"
            assert action_extra["waiting"]["resource_reason"] == "too_many_memory_results"
            assert action_extra["waiting"]["resource_estimate"]["memory_results"] == 100

            plan = await store.get_plan(action_extra["plan_id"])
            assert plan is not None
            assert plan.state == "waiting_clarification"
            assert plan.waiting_payload["resource_reason"] == "too_many_memory_results"
            assert plan.waiting_payload["resource_estimate"]["memory_results"] == 100
            assert plan.current_step_id == ""
            assert plan.step_outputs == {}
            assert memory_manager.calls == []
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_records_too_many_input_tokens_resource_reason(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        memory_manager = _FakeActionMemoryManager(context_lines=["项目排期"])
        memory_summarizer = _FakeMemorySummarizer()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_TokenBudgetPlanner(),
            memory_manager=memory_manager,
            memory_summarizer=memory_summarizer,
        )
        workflow._resource_manager = AIResourceManager(
            registry=workflow._registry,
            budget=ResourceBudget(max_total_input_tokens=1, max_total_output_tokens=999999),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="帮我总结聊天记录")
            assert result.handled is True
            action_extra = result.message_extra["ai_action"]
            assert action_extra["state"] == "waiting_clarification"
            assert "上下文" in result.response_text
            assert action_extra["waiting"]["reason"] == "resource_limit"
            assert action_extra["waiting"]["resource_reason"] == "too_many_input_tokens"
            assert action_extra["waiting"]["resource_estimate"]["input_tokens"] > 1

            plan = await store.get_plan(action_extra["plan_id"])
            assert plan is not None
            assert plan.state == "waiting_clarification"
            assert plan.waiting_payload["resource_reason"] == "too_many_input_tokens"
            assert plan.waiting_payload["resource_estimate"]["input_tokens"] > 1
            assert plan.current_step_id == ""
            assert plan.step_outputs == {}
            assert memory_manager.calls == []
            assert memory_summarizer.calls == []
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_records_too_many_output_tokens_resource_reason(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        memory_manager = _FakeActionMemoryManager(context_lines=["项目排期"])
        memory_summarizer = _FakeMemorySummarizer()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_TokenBudgetPlanner(),
            memory_manager=memory_manager,
            memory_summarizer=memory_summarizer,
        )
        workflow._resource_manager = AIResourceManager(
            registry=workflow._registry,
            budget=ResourceBudget(max_total_input_tokens=999999, max_total_output_tokens=1),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="帮我总结聊天记录")
            assert result.handled is True
            action_extra = result.message_extra["ai_action"]
            assert action_extra["state"] == "waiting_clarification"
            assert "过长" in result.response_text
            assert action_extra["waiting"]["reason"] == "resource_limit"
            assert action_extra["waiting"]["resource_reason"] == "too_many_output_tokens"
            assert action_extra["waiting"]["resource_estimate"]["output_tokens"] > 1

            plan = await store.get_plan(action_extra["plan_id"])
            assert plan is not None
            assert plan.state == "waiting_clarification"
            assert plan.waiting_payload["resource_reason"] == "too_many_output_tokens"
            assert plan.waiting_payload["resource_estimate"]["output_tokens"] > 1
            assert plan.current_step_id == ""
            assert plan.step_outputs == {}
            assert memory_manager.calls == []
            assert memory_summarizer.calls == []
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_resource_manager_does_not_apply_token_budget_to_plain_read_action() -> None:
    registry = AtomicActionRegistry(contact_resolver=SimpleNamespace())
    manager = AIResourceManager(
        registry=registry,
        budget=ResourceBudget(max_total_input_tokens=0, max_total_output_tokens=0),
    )
    plan = AIActionPlan(
        is_action=True,
        goal="解析联系人",
        risk="low",
        steps=(
            AIActionStep(
                id="resolve_contacts",
                action="contact.resolve",
                args={"queries": ["test3"], "allow_multiple": True},
            ),
        ),
        final={"type": "answer", "source": "$resolve_contacts"},
    )

    result = manager.check_plan(plan)

    assert result.allowed is True
    assert result.estimate["input_tokens"] == 0
    assert result.estimate["output_tokens"] == 0


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


def test_ai_action_workflow_rejects_legacy_single_business_actions(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_LegacyBusinessActionPlanner(),
        )
        try:
            send_result = await workflow.handle_user_turn(thread_id="thread-1", text="帮我给张三发我晚点到")
            history_result = await workflow.handle_user_turn(thread_id="thread-1", text="我和test3聊过什么？")

            assert send_result.handled is False
            assert history_result.handled is False
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
        memory_summarizer = _FakeMemorySummarizer("你和 test3 主要讨论了项目排期。")
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_AtomicReadPlanner(),
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
            memory_manager=memory_manager,
            memory_summarizer=memory_summarizer,
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="我和test3聊过什么？")
            assert result.handled is True
            assert result.response_text == "你和 test3 主要讨论了项目排期。"
            assert result.memory_context_lines == ()
            assert result.message_extra["ai_action"]["action"] == "memory.search"
            assert result.message_extra["ai_action"]["state"] == "done"
            assert memory_manager.calls[0]["participant_match"] == "any"
            assert memory_manager.calls[0]["time_scope"] == {"type": "all_history"}
            assert memory_manager.calls[0]["participants"][0]["contact_id"] == "user-3"
            assert memory_summarizer.calls[0]["question"] == "我和test3聊过什么？"
            plan = await store.get_plan(result.message_extra["ai_action"]["plan_id"])
            assert plan is not None
            assert plan.step_outputs["search_memory"]["result_count"] == 1
            assert plan.step_outputs["summarize_memory"]["requires_responder"] is False
            assert plan.step_outputs["summarize_memory"]["text"] == "你和 test3 主要讨论了项目排期。"
            events = result.message_extra["ai_action"]["events"]
            event_types = [event["type"] for event in events]
            assert event_types == [
                "step_started",
                "step_completed",
                "step_started",
                "step_completed",
                "step_started",
                "step_completed",
                "plan_completed",
            ]
            assert "讨论了项目排期" not in str(events)
            assert [step["state"] for step in result.message_extra["ai_action"]["steps"]] == ["done", "done", "done"]
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_uses_fresh_permission_scope_for_each_execution(tmp_path, monkeypatch) -> None:
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
        memory_manager = _FakeActionMemoryManager(context_lines=["[2026-04-21 10:00] test3；摘要：讨论了项目排期。"])
        memory_summarizer = _FakeMemorySummarizer("已总结 test3 的项目排期记录。")
        scopes = [
            AIPermissionScope(allowed_contacts=("user-3",)),
            AIPermissionScope(allowed_contacts=("user-9",)),
        ]
        provider_calls: list[int] = []

        def permission_scope_provider() -> AIPermissionScope:
            provider_calls.append(1)
            index = min(len(provider_calls) - 1, len(scopes) - 1)
            return scopes[index]

        workflow = AIActionWorkflow(
            action_store=store,
            planner=_AtomicReadPlanner(),
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
            memory_manager=memory_manager,
            memory_summarizer=memory_summarizer,
            permission_scope_provider=permission_scope_provider,
        )
        try:
            allowed = await workflow.handle_user_turn(thread_id="thread-allowed", text="我和test3聊过什么？")
            denied = await workflow.handle_user_turn(thread_id="thread-denied", text="我和test3聊过什么？")
            denied_plan = await store.get_plan(denied.message_extra["ai_action"]["plan_id"])

            assert allowed.handled is True
            assert allowed.response_text == "已总结 test3 的项目排期记录。"
            assert allowed.memory_context_lines == ()
            assert denied.handled is True
            assert denied.response_text == "这个操作执行失败，请稍后再试。"
            assert denied.message_extra["ai_action"]["state"] == "failed"
            assert denied_plan is not None
            assert denied_plan.error_text == "PERMISSION_DENIED"
            assert len(provider_calls) == 2
            assert len(memory_manager.calls) == 1
            assert len(memory_summarizer.calls) == 1
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_allows_e2ee_memory_search_when_local_plaintext_granted(tmp_path, monkeypatch) -> None:
    class _E2EEMemoryPlanner:
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
                            "participants": [
                                {
                                    "contact_id": "user-3",
                                    "display_name": "test3",
                                    "e2ee": True,
                                }
                            ],
                            "participant_match": "any",
                            "time_scope": {"type": "all_history"},
                            "keywords": ["README.md"],
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

    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        memory_manager = _FakeActionMemoryManager(
            context_lines=["[2026-04-24 15:20] README.md；摘要：AssistIM 文档总览。"]
        )
        memory_summarizer = _FakeMemorySummarizer("README.md 主要是 AssistIM 文档总览。")
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_E2EEMemoryPlanner(),
            contact_alias_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            memory_manager=memory_manager,
            memory_summarizer=memory_summarizer,
            permission_scope_provider=lambda: AIPermissionScope(allow_e2ee_plaintext=True),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="我给test3发的README.md文件内容有什么？")
            plan = await store.get_plan(result.message_extra["ai_action"]["plan_id"])

            assert result.handled is True
            assert result.response_text == "README.md 主要是 AssistIM 文档总览。"
            assert result.memory_context_lines == ()
            assert len(memory_manager.calls) == 1
            assert len(memory_summarizer.calls) == 1
            assert memory_manager.calls[0]["participants"][0]["e2ee"] is True
            assert plan is not None
            assert plan.error_text == ""
            assert "search_memory" in plan.step_outputs
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_rejects_sensitive_tagged_memory_search_before_handler(tmp_path, monkeypatch) -> None:
    class _SensitiveTaggedMemoryPlanner:
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
                            "participants": [
                                {
                                    "contact_id": "user-secret",
                                    "display_name": "Sensitive Friend",
                                    "tags": ["private"],
                                }
                            ],
                            "participant_match": "any",
                            "time_scope": {"type": "all_history"},
                            "keywords": ["private"],
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

    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        memory_manager = _FakeActionMemoryManager(context_lines=["不应读取"])
        memory_summarizer = _FakeMemorySummarizer("不应总结")
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_SensitiveTaggedMemoryPlanner(),
            memory_manager=memory_manager,
            memory_summarizer=memory_summarizer,
            permission_scope_provider=lambda: AIPermissionScope(sensitive_tags=("private",)),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="总结敏感联系人记录")
            plan = await store.get_plan(result.message_extra["ai_action"]["plan_id"])

            assert result.handled is True
            assert result.response_text == "这个操作执行失败，请稍后再试。"
            assert result.message_extra["ai_action"]["state"] == "failed"
            assert result.message_extra["ai_action"]["current_step_id"] == "search_memory"
            assert result.message_extra["ai_action"]["events"] == [
                {
                    "type": "step_failed",
                    "step_id": "search_memory",
                    "action": "memory.search",
                    "state": "failed",
                    "message": "",
                    "plan_id": plan.id if plan is not None else result.message_extra["ai_action"]["plan_id"],
                    "error_code": "PERMISSION_DENIED",
                }
            ]
            assert "user-secret" not in result.response_text
            assert "Sensitive Friend" not in result.response_text
            assert "private" not in result.response_text
            assert "user-secret" not in str(result.message_extra["ai_action"]["events"])
            assert "Sensitive Friend" not in str(result.message_extra["ai_action"]["events"])
            assert "private" not in str(result.message_extra["ai_action"]["events"])
            assert plan is not None
            assert plan.error_text == "PERMISSION_DENIED"
            assert plan.step_outputs == {}
            assert memory_manager.calls == []
            assert memory_summarizer.calls == []
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_rejects_e2ee_memory_search_without_plaintext_grant(tmp_path, monkeypatch) -> None:
    class _E2EEMemoryPlanner:
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
                            "participants": [
                                {
                                    "contact_id": "user-e2ee",
                                    "display_name": "Encrypted Friend",
                                    "e2ee": True,
                                }
                            ],
                            "participant_match": "any",
                            "time_scope": {"type": "all_history"},
                            "keywords": ["README.md"],
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

    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        memory_manager = _FakeActionMemoryManager(context_lines=["不应读取"])
        memory_summarizer = _FakeMemorySummarizer("不应总结")
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_E2EEMemoryPlanner(),
            memory_manager=memory_manager,
            memory_summarizer=memory_summarizer,
            permission_scope_provider=lambda: AIPermissionScope(allow_e2ee_plaintext=False),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="总结加密会话记录")
            plan = await store.get_plan(result.message_extra["ai_action"]["plan_id"])

            assert result.handled is True
            assert result.response_text == "这个操作执行失败，请稍后再试。"
            assert result.message_extra["ai_action"]["state"] == "failed"
            assert result.message_extra["ai_action"]["events"][0]["error_code"] == "PERMISSION_DENIED"
            assert "user-e2ee" not in result.response_text
            assert "Encrypted Friend" not in result.response_text
            assert "user-e2ee" not in str(result.message_extra["ai_action"]["events"])
            assert "Encrypted Friend" not in str(result.message_extra["ai_action"]["events"])
            assert plan is not None
            assert plan.error_text == "PERMISSION_DENIED"
            assert plan.step_outputs == {}
            assert memory_manager.calls == []
            assert memory_summarizer.calls == []
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_rejects_raw_content_memory_search_before_handler(tmp_path, monkeypatch) -> None:
    class _RawContentMemoryPlanner:
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
                            "participant_match": "any",
                            "time_scope": {"type": "all_history"},
                            "keywords": ["README.md"],
                            "question": user_text,
                            "return_raw_content": True,
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

    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        memory_manager = _FakeActionMemoryManager(context_lines=["不应读取原文"])
        memory_summarizer = _FakeMemorySummarizer("不应总结")
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_RawContentMemoryPlanner(),
            memory_manager=memory_manager,
            memory_summarizer=memory_summarizer,
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="把 README.md 原文找出来")
            plan = await store.get_plan(result.message_extra["ai_action"]["plan_id"])

            assert result.handled is True
            assert result.response_text == "这个操作执行失败，请稍后再试。"
            assert result.message_extra["ai_action"]["state"] == "failed"
            assert result.message_extra["ai_action"]["events"][0]["error_code"] == "PERMISSION_DENIED"
            assert plan is not None
            assert plan.error_text == "PERMISSION_DENIED"
            assert plan.step_outputs == {}
            assert memory_manager.calls == []
            assert memory_summarizer.calls == []
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
        memory_summarizer = _FakeMemorySummarizer("不应被调用")
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_AtomicReadPlanner(),
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
            memory_manager=_FakeActionMemoryManager(context_lines=[]),
            memory_summarizer=memory_summarizer,
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="我和test3聊过什么？")

            assert result.handled is True
            assert "没有找到相关记录" in result.response_text
            assert result.memory_context_lines == ()
            assert result.message_extra["ai_action"]["state"] == "done"
            assert memory_summarizer.calls == []
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
            memory_summarizer=_FakeMemorySummarizer("已总结缓存命中的搜索结果。"),
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


def test_ai_action_workflow_repairs_invalid_plan_before_execution(tmp_path, monkeypatch) -> None:
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
        memory_manager = _FakeActionMemoryManager(context_lines=["[2026-04-21 10:00] test3；摘要：讨论了项目排期。"])
        planner = _InvalidReferenceThenFixedPlanner()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=planner,
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
            memory_manager=memory_manager,
            memory_summarizer=_FakeMemorySummarizer("修复计划后总结了项目排期。"),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="我和test3聊过什么？")
            plan = await store.get_plan(result.message_extra["ai_action"]["plan_id"])

            assert result.handled is True
            assert result.response_text == "修复计划后总结了项目排期。"
            assert result.memory_context_lines == ()
            assert planner.plan_calls == 1
            assert len(planner.repair_calls) == 1
            assert any("ARG_REFERENCE_INVALID" in error for error in planner.repair_calls[0]["errors"])
            assert memory_manager.calls[0]["participant_match"] == "any"
            assert plan is not None
            assert [step["id"] for step in plan.plan_json["steps"]] == [
                "resolve_contacts",
                "search_memory",
                "summarize_memory",
            ]
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_rejects_plan_after_failed_repair_without_persisting(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        memory_manager = _FakeActionMemoryManager(context_lines=["不应执行"])
        planner = _AlwaysInvalidReferencePlanner()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=planner,
            contact_alias_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            memory_manager=memory_manager,
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="我和test3聊过什么？")

            assert result.handled is True
            assert "计划结构有问题" in result.response_text
            assert planner.plan_calls == 2
            assert len(planner.repair_calls) == 1
            assert memory_manager.calls == []
            assert await store.latest_pending_plan("thread-1") is None
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_does_not_repair_unknown_write_action(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        planner = _InvalidWriteUnknownActionRepairWouldSendPlanner()
        message_sender = _FakeActionMessageSender()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=planner,
            contact_alias_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            message_sender=message_sender,
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="帮我删除服务器数据库")

            assert result.handled is True
            assert result.message_extra["ai_action"]["state"] == "failed"
            assert "超出当前支持" in result.response_text
            assert planner.plan_calls == 1
            assert planner.repair_calls == []
            assert message_sender.calls == []
            assert await store.latest_pending_plan("thread-1") is None
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_does_not_repair_invalid_side_effect_plan(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        planner = _InvalidWriteBadReadTailRepairWouldSendPlanner()
        message_sender = _FakeActionMessageSender()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=planner,
            contact_alias_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            message_sender=message_sender,
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="帮我在这个群里生成推荐回复")

            assert result.handled is True
            assert result.message_extra["ai_action"]["state"] == "failed"
            assert "结构不安全" in result.response_text
            assert planner.plan_calls == 1
            assert planner.repair_calls == []
            assert message_sender.calls == []
            assert await store.latest_pending_plan("thread-1") is None
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_registry_memory_summarize_keeps_small_context_unmodified() -> None:
    async def scenario() -> None:
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            memory_manager=_FakeActionMemoryManager(),
            memory_summarizer=_FakeMemorySummarizer("总结：讨论了项目排期，并确认了交付时间。"),
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

        assert output["requires_responder"] is False
        assert output["text"] == "总结：讨论了项目排期，并确认了交付时间。"
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
            memory_summarizer=_FakeMemorySummarizer("总结：历史记录包含项目排期、风险和下一步安排。"),
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

        assert output["requires_responder"] is False
        assert output["text"] == "总结：历史记录包含项目排期、风险和下一步安排。"
        assert output["chunked"] is True
        assert output["chunk_count"] == 3
        assert output["input_result_count"] == 10
        assert len(output["context_lines"]) == 3
        assert output["context_lines"][0].startswith("检索结果 1-4：")
        assert output["context_lines"][1].startswith("检索结果 5-8：")
        assert output["context_lines"][2].startswith("检索结果 9-10：")
        assert output["context_chars"] < sum(len(line) for line in context_lines)

    asyncio.run(scenario())


def test_ai_action_registry_memory_summarize_keeps_file_result_content_when_chunked() -> None:
    async def scenario() -> None:
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            memory_manager=_FakeActionMemoryManager(),
            memory_summarizer=_FakeMemorySummarizer("README.md 主要介绍 AssistIM。"),
        )
        spec = registry.get("memory.summarize")
        assert spec is not None
        context_lines = [
            (
                "[2026-04-24 15:20-15:20]；README.md #1；参与者：test1、test3；"
                "摘要：文件内容片段：# AssistIM 文档总览 本文档集用于约束 AssistIM 的产品边界、"
                "系统架构、实时协议、UI 设计系统与工程实践。"
            ),
            (
                "[2026-04-24 15:20-15:20]；README.md；参与者：test1、test3；"
                "摘要：文件总结：AssistIM 是一个 AI 增强即时通讯桌面应用，目标是将即时通讯和 AI 助手能力整合。"
            ),
            (
                "[2026-04-24 15:20-15:20]；README.md #2；参与者：test1、test3；"
                "摘要：文件内容片段：系统由桌面客户端、后端 API/WebSocket 网关、外部 AI 提供商和文件存储组成。"
            ),
            (
                "[2026-04-24 15:20-15:20]；README.md #3；参与者：test1、test3；"
                "摘要：文件内容片段：核心能力包括私聊群聊、消息处理、AI 会话流式输出、本地缓存等。"
            ),
            (
                "[2026-04-24 15:20-15:20]；README.md #4；参与者：test1、test3；"
                "摘要：文件内容片段：文档集约束产品边界、架构、协议和 UI 设计，并规定文档职责划分。"
            ),
            (
                "[2026-04-24 15:20-15:20]；README.md #5；参与者：test1、test3；"
                "摘要：文件内容片段：架构、协议、UI 设计系统和工程规则变化时必须同步更新文档。"
            ),
            "[2026-04-24 15:19-15:19]；requirements.txt；摘要：GUI 依赖使用 PySide6。",
            "[2026-04-24 15:19-15:19]；requirements.txt #1；摘要：异步通信依赖包含 websockets。",
        ]

        output = await spec.handler(  # type: ignore[misc]
            {
                "source": {
                    "context_lines": context_lines,
                    "result_count": 13,
                    "truncated": True,
                },
                "question": "我给test3发的README.md文件主要是讲什么",
            },
            {"store": None},
        )

        joined = "\n".join(output["context_lines"])
        assert output["requires_responder"] is False
        assert output["text"] == "README.md 主要介绍 AssistIM。"
        assert output["chunked"] is True
        assert "README.md" in joined
        assert "AI 增强即时通讯桌面应用" in joined
        assert "桌面客户端、后端 API/WebSocket 网关" in joined
        assert "核心能力包括私聊群聊" in joined

    asyncio.run(scenario())


def test_ai_action_registry_memory_summarize_degrades_when_model_fails() -> None:
    async def scenario() -> None:
        memory_summarizer = _FailingMemorySummarizer("MEMORY_SUMMARIZE_FAILED")
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            memory_manager=_FakeActionMemoryManager(),
            memory_summarizer=memory_summarizer,
            action_cache=AIActionCache(),
        )
        spec = registry.get("memory.summarize")
        assert spec is not None
        source = {
            "context_lines": [
                "[2026-04-24 15:20] README.md；摘要：文件总结：AssistIM 是一个 AI 增强即时通讯桌面应用。",
                "[2026-04-24 15:21] README.md #1；摘要：文件内容片段：核心能力包括私聊群聊、AI 会话流式输出。",
            ],
            "result_count": 2,
        }

        first = await spec.handler(  # type: ignore[misc]
            {"source": source, "question": "README.md 主要讲什么？"},
            {"store": None},
        )
        second = await spec.handler(  # type: ignore[misc]
            {"source": source, "question": "README.md 主要讲什么？"},
            {"store": None},
        )

        assert first["requires_responder"] is False
        assert first["status"] == "degraded"
        assert first["fallback_used"] is True
        assert first["fallback_reason"] == "model_failed"
        assert first["cache_hit"] is False
        assert "模型总结暂不可用" in first["text"]
        assert "AssistIM 是一个 AI 增强即时通讯桌面应用" in first["text"]
        assert "核心能力包括私聊群聊" in first["text"]
        assert second["cache_hit"] is False
        assert len(memory_summarizer.calls) == 2

    asyncio.run(scenario())


def test_ai_action_registry_memory_summarize_degrades_when_model_returns_empty() -> None:
    async def scenario() -> None:
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            memory_manager=_FakeActionMemoryManager(),
            memory_summarizer=_FakeMemorySummarizer(""),
        )
        spec = registry.get("memory.summarize")
        assert spec is not None

        output = await spec.handler(  # type: ignore[misc]
            {
                "source": {
                    "context_lines": ["[2026-04-21 10:00] 摘要：讨论了项目排期。"],
                    "result_count": 1,
                },
                "question": "我和 test3 聊过什么？",
            },
            {"store": None},
        )

        assert output["status"] == "degraded"
        assert output["fallback_used"] is True
        assert output["fallback_reason"] == "model_empty"
        assert output["cache_hit"] is False
        assert "模型总结暂不可用" in output["text"]
        assert "讨论了项目排期" in output["text"]

    asyncio.run(scenario())


def test_ai_action_workflow_memory_summarize_degraded_result_finishes_plan(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_AtomicReadPlanner(),
            contact_alias_resolver=ContactAliasResolver(
                db=_FakeContactDatabase(
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
            ),
            memory_manager=_FakeActionMemoryManager(
                context_lines=[
                    "[2026-04-24 15:20] README.md；参与者：test1、test3；摘要：文件总结：AssistIM 文档总览。"
                ]
            ),
            memory_summarizer=_FailingMemorySummarizer("MEMORY_SUMMARIZE_FAILED"),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="我给test3发的README.md文件内容有什么？")
            plan = await store.get_plan(result.message_extra["ai_action"]["plan_id"])

            assert result.handled is True
            assert result.message_extra["ai_action"]["state"] == "done"
            assert "模型总结暂不可用" in result.response_text
            assert plan is not None
            assert plan.error_text == ""
            assert plan.step_outputs["summarize_memory"]["status"] == "degraded"
            assert plan.step_outputs["summarize_memory"]["fallback_reason"] == "model_failed"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_memory_summarizer_chunks_then_finalizes() -> None:
    async def scenario() -> None:
        task_manager = _FakeSummaryTaskManager()
        summarizer = AIActionMemorySummarizer(
            task_manager=task_manager,
            max_context_chars=120,
            chunk_context_chars=80,
        )
        context_lines = [
            f"[2026-04-24 15:{index:02d}] README.md；摘要：第 {index} 段内容介绍 AssistIM 的架构、协议和 AI 能力。"
            for index in range(6)
        ]

        result = await summarizer.summarize(
            question="README.md 主要讲什么？",
            context_lines=context_lines,
            style="summary",
            input_result_count=6,
        )

        assert result["text"] == "最终总结：README.md 主要介绍 AssistIM。"
        assert result["chunk_count"] > 1
        assert len(task_manager.requests) == result["chunk_count"] + 1
        assert task_manager.requests[-1].metadata["summary_stage"] == "final"
        assert all(request.stream is False for request in task_manager.requests)

    asyncio.run(scenario())


def test_ai_action_memory_summarizer_returns_model_token_usage() -> None:
    async def scenario() -> None:
        task_manager = _UsageSummaryTaskManager(
            {"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11}
        )
        summarizer = AIActionMemorySummarizer(task_manager=task_manager)

        result = await summarizer.summarize(
            question="README.md 主要讲什么？",
            context_lines=["[2026-04-24 15:20] README.md；摘要：AssistIM 文档总览。"],
            style="summary",
            input_result_count=1,
        )

        assert result["text"] == "最终总结：README.md 主要介绍 AssistIM。"
        assert result["usage"] == {"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11}
        assert result["model_tokens"] == 11

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
            memory_summarizer=_FakeMemorySummarizer("缓存测试总结。"),
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
        assert second["text"] == "缓存测试总结。"
        assert second["context_lines"] == source["context_lines"]
        assert calls == [source["context_lines"]]

    asyncio.run(scenario())


def test_ai_action_registry_memory_summarize_cache_skips_repeated_chunked_summary() -> None:
    async def scenario() -> None:
        memory_summarizer = _FakeMemorySummarizer("缓存后的大上下文总结。")
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            memory_manager=_FakeActionMemoryManager(),
            memory_summarizer=memory_summarizer,
            action_cache=AIActionCache(),
        )
        spec = registry.get("memory.summarize")
        assert spec is not None
        source = {
            "context_lines": [
                f"[2026-04-21 10:{index:02d}] 摘要：第 {index} 条记录，包含项目排期、风险和下一步安排。"
                for index in range(10)
            ],
            "result_count": 10,
        }

        first = await spec.handler(  # type: ignore[misc]
            {"source": source, "question": "总结历史"},
            {"store": None},
        )
        second = await spec.handler(  # type: ignore[misc]
            {"source": source, "question": "总结历史"},
            {"store": None},
        )

        assert first["cache_hit"] is False
        assert first["chunked"] is True
        assert first["chunk_count"] == 3
        assert second["cache_hit"] is True
        assert second["chunked"] is True
        assert second["chunk_count"] == 3
        assert second["text"] == "缓存后的大上下文总结。"
        assert len(memory_summarizer.calls) == 1

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
            memory_summarizer=_FakeMemorySummarizer("问题变化测试总结。"),
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
            memory_summarizer=_FakeMemorySummarizer("来源变化测试总结。"),
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
            memory_summarizer=_FakeMemorySummarizer("缓存命中后的总结。"),
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


def test_ai_action_executor_validates_input_model_before_handler(tmp_path, monkeypatch) -> None:
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
                    "assistim_id": "zhangsan",
                }
            ]
        )
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=contact_db),
        )
        executor = AIActionExecutor(registry=registry, store=store)
        plan = AIActionPlan(
            is_action=True,
            goal="输入类型错误",
            steps=(
                AIActionStep(
                    id="resolve_contacts",
                    action="contact.resolve",
                    args={"queries": "张三", "allow_multiple": True},
                ),
            ),
            final={"type": "answer", "source": "$resolve_contacts"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_invalid_input_model",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)

            assert result.state == "failed"
            assert result.error_text.startswith("ARG_SCHEMA_INVALID")
            assert updated is not None
            assert updated.error_text.startswith("ARG_SCHEMA_INVALID")
            assert updated.step_outputs == {}
            assert contact_db.resolve_calls == []
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_passes_permission_context_and_skips_denied_handler(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        class DenyPolicy(AIPermissionPolicy):
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def check_step(self, *, spec, args, plan_context=None):
                self.calls.append(
                    {
                        "spec_name": spec.name,
                        "args": dict(args or {}),
                        "plan_context": dict(plan_context or {}),
                    }
                )
                return PermissionDecision(False, "PERMISSION_DENIED", "blocked by test policy")

        async def denied_handler(args, context):
            raise AssertionError("permission-denied steps must not execute their handler")

        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        spec = registry.get("contact.resolve")
        assert spec is not None
        registry._actions["contact.resolve"] = replace(spec, handler=denied_handler)
        policy = DenyPolicy()
        executor = AIActionExecutor(registry=registry, store=store, permission_policy=policy)
        plan = AIActionPlan(
            is_action=True,
            goal="权限拒绝",
            steps=(
                AIActionStep(
                    id="resolve_contacts",
                    action="contact.resolve",
                    args={"queries": ["张三"], "allow_multiple": True},
                ),
            ),
            final={"type": "answer", "source": "$resolve_contacts"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_permission_denied",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)

            assert result.state == "failed"
            assert result.error_text == "PERMISSION_DENIED"
            assert policy.calls == [
                {
                    "spec_name": "contact.resolve",
                    "args": {"queries": ["张三"], "allow_multiple": True},
                    "plan_context": {
                        "thread_id": "thread-1",
                        "plan_id": record.id,
                        "plan_version": 1,
                        "step_id": "resolve_contacts",
                        "action": "contact.resolve",
                    },
                }
            ]
            assert updated is not None
            assert updated.state == "failed"
            assert updated.error_text == "PERMISSION_DENIED"
            assert updated.step_outputs == {}
            assert [event["type"] for event in updated.plan_json["events"]] == ["step_failed"]
            assert updated.plan_json["events"][0]["step_id"] == "resolve_contacts"
            assert updated.plan_json["events"][0]["action"] == "contact.resolve"
            assert updated.plan_json["events"][0]["error_code"] == "PERMISSION_DENIED"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_permission_policy_rejects_structured_raw_content_return_request() -> None:
    policy = AIPermissionPolicy()
    spec = AtomicActionSpec(name="read.local", kind="read", risk_level="low", allow_raw_content_return=False)

    decision = policy.check_step(spec=spec, args={"return_raw_content": True})

    assert decision.allowed is False
    assert decision.code == "PERMISSION_DENIED"


def test_ai_permission_policy_rejects_cross_session_read_when_spec_disallows() -> None:
    policy = AIPermissionPolicy()
    spec = AtomicActionSpec(name="read.local", kind="read", risk_level="low", allow_cross_session=False)

    decision = policy.check_step(spec=spec, args={"scope": "all_sessions"})

    assert decision.allowed is False
    assert decision.code == "PERMISSION_DENIED"


def test_ai_permission_policy_allows_default_local_read_scope() -> None:
    policy = AIPermissionPolicy()
    spec = AtomicActionSpec(name="read.local", kind="read", risk_level="low")

    decision = policy.check_step(spec=spec, args={"query": "test3"})

    assert decision.allowed is True
    assert decision.code == ""


def test_ai_permission_policy_rejects_excluded_contact_without_leaking_details() -> None:
    policy = AIPermissionPolicy(scope=AIPermissionScope(excluded_contacts=("user-1",)))
    spec = AtomicActionSpec(name="memory.search", kind="read", risk_level="low", allow_cross_session=True)

    decision = policy.check_step(
        spec=spec,
        args={
            "participants": [
                {
                    "contact_id": "user-1",
                    "display_name": "Sensitive Friend",
                    "tags": ["normal"],
                }
            ]
        },
    )

    assert decision.allowed is False
    assert decision.code == "PERMISSION_DENIED"
    assert "user-1" not in decision.message
    assert "Sensitive Friend" not in decision.message


def test_ai_permission_policy_rejects_target_outside_allowed_contacts() -> None:
    policy = AIPermissionPolicy(scope=AIPermissionScope(allowed_contacts=("user-2",)))
    spec = AtomicActionSpec(
        name="message.send",
        kind="write",
        risk_level="high",
        allow_side_effect=True,
    )

    decision = policy.check_step(
        spec=spec,
        args={
            "target": {"contact_id": "user-1", "display_name": "张三"},
            "content": "hello",
            "preview": {"operation": "发送消息"},
            "idempotency_key": "send-1",
        },
    )

    assert decision.allowed is False
    assert decision.code == "PERMISSION_DENIED"
    assert "user-1" not in decision.message
    assert "张三" not in decision.message


def test_ai_permission_policy_rejects_group_target_when_only_contact_scope_is_allowed() -> None:
    policy = AIPermissionPolicy(scope=AIPermissionScope(allowed_contacts=("user-2",)))
    spec = AtomicActionSpec(name="memory.search", kind="read", risk_level="low", allow_cross_session=True)

    decision = policy.check_step(
        spec=spec,
        args={"participants": [{"group_id": "group-1", "name": "Project Group"}]},
    )

    assert decision.allowed is False
    assert decision.code == "PERMISSION_DENIED"
    assert "group-1" not in decision.message
    assert "Project Group" not in decision.message


def test_ai_permission_policy_rejects_contact_target_when_only_group_scope_is_allowed() -> None:
    policy = AIPermissionPolicy(scope=AIPermissionScope(allowed_groups=("group-1",)))
    spec = AtomicActionSpec(name="memory.search", kind="read", risk_level="low", allow_cross_session=True)

    decision = policy.check_step(
        spec=spec,
        args={"participants": [{"contact_id": "user-3", "display_name": "test3"}]},
    )

    assert decision.allowed is False
    assert decision.code == "PERMISSION_DENIED"
    assert "user-3" not in decision.message
    assert "test3" not in decision.message


def test_ai_permission_policy_rejects_excluded_group_scope() -> None:
    policy = AIPermissionPolicy(scope=AIPermissionScope(excluded_groups=("group-1",)))
    spec = AtomicActionSpec(name="memory.search", kind="read", risk_level="low", allow_cross_session=True)

    decision = policy.check_step(
        spec=spec,
        args={"participants": [{"group_id": "group-1", "name": "Private Group"}]},
    )

    assert decision.allowed is False
    assert decision.code == "PERMISSION_DENIED"
    assert "group-1" not in decision.message
    assert "Private Group" not in decision.message


def test_ai_permission_policy_rejects_sensitive_tagged_entities() -> None:
    policy = AIPermissionPolicy(scope=AIPermissionScope(sensitive_tags=("private", "blocked")))
    spec = AtomicActionSpec(name="memory.search", kind="read", risk_level="low", allow_cross_session=True)

    decision = policy.check_step(
        spec=spec,
        args={"participants": [{"contact_id": "user-3", "tags": ["private"]}]},
    )

    assert decision.allowed is False
    assert decision.code == "PERMISSION_DENIED"
    assert "user-3" not in decision.message
    assert "private" not in decision.message


def test_ai_permission_policy_rejects_e2ee_plaintext_without_scope_grant() -> None:
    policy = AIPermissionPolicy(scope=AIPermissionScope(allow_e2ee_plaintext=False))
    spec = AtomicActionSpec(name="memory.search", kind="read", risk_level="low", allow_cross_session=True)

    denied = policy.check_step(
        spec=spec,
        args={"participants": [{"contact_id": "user-4", "e2ee": True}]},
    )
    allowed = AIPermissionPolicy(scope=AIPermissionScope(allow_e2ee_plaintext=True)).check_step(
        spec=spec,
        args={"participants": [{"contact_id": "user-4", "e2ee": True}]},
    )

    assert denied.allowed is False
    assert denied.code == "PERMISSION_DENIED"
    assert "user-4" not in denied.message
    assert allowed.allowed is True
    assert allowed.code == ""


def test_ai_action_executor_validates_output_model_after_handler(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        async def invalid_contact_output(args, context):
            del args, context
            return {
                "contacts": "not-a-list",
                "groups": [],
                "ambiguous": [],
                "unresolved": [],
            }

        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        spec = registry.get("contact.resolve")
        assert spec is not None
        registry._actions["contact.resolve"] = replace(spec, handler=invalid_contact_output)
        executor = AIActionExecutor(registry=registry, store=store)
        plan = AIActionPlan(
            is_action=True,
            goal="输出类型错误",
            steps=(
                AIActionStep(
                    id="resolve_contacts",
                    action="contact.resolve",
                    args={"queries": ["张三"], "allow_multiple": True},
                ),
            ),
            final={"type": "answer", "source": "$resolve_contacts"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_invalid_output_model",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)

            assert result.state == "failed"
            assert result.error_text.startswith("OUTPUT_SCHEMA_INVALID")
            assert updated is not None
            assert updated.error_text.startswith("OUTPUT_SCHEMA_INVALID")
            assert updated.step_outputs == {}
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_times_out_action_and_marks_plan_failed(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        async def slow_contact_output(args, context):
            del args, context
            await asyncio.sleep(0.05)
            return {
                "contacts": [],
                "groups": [],
                "ambiguous": [],
                "unresolved": [],
            }

        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        spec = registry.get("contact.resolve")
        assert spec is not None
        registry._actions["contact.resolve"] = replace(spec, handler=slow_contact_output, timeout_ms=1)
        executor = AIActionExecutor(registry=registry, store=store)
        plan = AIActionPlan(
            is_action=True,
            goal="超时",
            steps=(
                AIActionStep(
                    id="resolve_contacts",
                    action="contact.resolve",
                    args={"queries": ["张三"], "allow_multiple": True},
                ),
            ),
            final={"type": "answer", "source": "$resolve_contacts"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_timeout",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)

            assert result.state == "failed"
            assert result.error_text == "ACTION_TIMEOUT: contact.resolve"
            assert updated is not None
            assert updated.state == "failed"
            assert updated.error_text == "ACTION_TIMEOUT: contact.resolve"
            assert updated.step_outputs == {}
            assert [event["type"] for event in updated.plan_json["events"]] == ["step_started", "step_failed"]
            assert updated.plan_json["events"][-1]["error_code"] == "ACTION_TIMEOUT"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_retries_safe_read_action_once(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        calls = 0

        async def flaky_contact_output(args, context):
            nonlocal calls
            del args, context
            calls += 1
            if calls == 1:
                raise RuntimeError("transient read failure")
            return {
                "contacts": [{"contact_id": "user-1", "display_name": "张三"}],
                "groups": [],
                "ambiguous": [],
                "unresolved": [],
            }

        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        spec = registry.get("contact.resolve")
        assert spec is not None
        registry._actions["contact.resolve"] = replace(spec, handler=flaky_contact_output, max_retries=1)
        executor = AIActionExecutor(registry=registry, store=store)
        plan = AIActionPlan(
            is_action=True,
            goal="短重试",
            steps=(
                AIActionStep(
                    id="resolve_contacts",
                    action="contact.resolve",
                    args={"queries": ["张三"], "allow_multiple": True},
                ),
            ),
            final={"type": "answer", "source": "$resolve_contacts"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_safe_retry",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)

            assert result.state == "done"
            assert calls == 2
            assert updated is not None
            assert updated.state == "done"
            assert updated.step_outputs["resolve_contacts"]["contacts"][0]["contact_id"] == "user-1"
            assert [event["type"] for event in updated.plan_json["events"]] == [
                "step_started",
                "step_attempt_failed",
                "step_retrying",
                "step_completed",
                "plan_completed",
            ]
            failed_attempt = updated.plan_json["events"][1]
            retrying = updated.plan_json["events"][2]
            assert failed_attempt["step_id"] == "resolve_contacts"
            assert failed_attempt["attempt"] == 1
            assert failed_attempt["max_attempts"] == 2
            assert failed_attempt["retryable"] is True
            assert failed_attempt["error_code"] == "ACTION_FAILED"
            assert "transient read failure" not in str(failed_attempt)
            assert retrying["step_id"] == "resolve_contacts"
            assert retrying["attempt"] == 2
            assert retrying["max_attempts"] == 2
            assert retrying["retryable"] is True
            assert "transient read failure" not in str(retrying)
            assert updated.plan_json["events"][3]["result_count"] == 1
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_records_safe_step_resource_usage(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        async def contact_output(args, context):
            del args, context
            return {
                "contacts": [{"contact_id": "user-1", "display_name": "张三"}],
                "groups": [],
                "ambiguous": [],
                "unresolved": [],
            }

        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        spec = registry.get("contact.resolve")
        assert spec is not None
        registry._actions["contact.resolve"] = replace(spec, handler=contact_output)
        executor = AIActionExecutor(registry=registry, store=store)
        plan = AIActionPlan(
            is_action=True,
            goal="解析联系人",
            steps=(
                AIActionStep(
                    id="resolve_contacts",
                    action="contact.resolve",
                    args={"queries": ["张三"], "allow_multiple": True},
                ),
            ),
            final={"type": "answer", "source": "$resolve_contacts.contacts[0].contact_id"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_resource_usage",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)

            assert result.state == "done"
            assert updated is not None
            completed_event = next(event for event in updated.plan_json["events"] if event["type"] == "step_completed")
            usage = completed_event["resource_usage"]
            assert usage["duration_ms"] >= 0
            assert usage["result_count"] == 1
            assert usage["output_bytes"] > 0
            assert usage["result_ref"] is False
            assert usage["model_call_cost"] == 0
            assert "张三" not in str(usage)

            aggregate = updated.plan_json["resource_usage"]
            assert aggregate["total_duration_ms"] >= 0
            assert aggregate["total_result_count"] == 1
            assert aggregate["total_output_bytes"] == usage["output_bytes"]
            assert aggregate["total_model_call_cost"] == 0
            assert aggregate["result_ref_count"] == 0
            assert aggregate["step_event_count"] == 1
            assert "张三" not in str(aggregate)
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_stops_after_runtime_duration_budget_exceeded(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        calls: list[str] = []

        async def first_read(args, context):
            del args, context
            calls.append("first_read")
            return {"text": "first", "result_count": 1}

        async def second_read(args, context):
            del args, context
            calls.append("second_read")
            return {"text": "second", "result_count": 1}

        monkeypatch.setattr(executor_module, "_elapsed_ms", lambda _started: 50)
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        registry._actions["test.first_read"] = AtomicActionSpec(
            name="test.first_read",
            kind="read",
            risk_level="low",
            handler=first_read,
        )
        registry._actions["test.second_read"] = AtomicActionSpec(
            name="test.second_read",
            kind="read",
            risk_level="low",
            handler=second_read,
        )
        executor = AIActionExecutor(
            registry=registry,
            store=store,
            runtime_budget=ActionRuntimeBudget(max_total_duration_ms=25),
        )
        plan = AIActionPlan(
            is_action=True,
            goal="总时长硬限制",
            steps=(
                AIActionStep(id="first_read", action="test.first_read", args={}),
                AIActionStep(id="second_read", action="test.second_read", depends_on=("first_read",), args={}),
            ),
            final={"type": "answer", "source": "$second_read"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_runtime_duration_budget",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)

            assert result.state == "failed"
            assert result.error_text == "RESOURCE_LIMIT_EXCEEDED: total_duration_ms"
            assert calls == ["first_read"]
            assert updated is not None
            assert "second_read" not in updated.step_outputs
            assert updated.plan_json["events"][-1]["resource_limit"] == "total_duration_ms"
            assert updated.plan_json["resource_usage"]["total_duration_ms"] == 50
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_stops_after_runtime_model_token_budget_exceeded(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        calls: list[str] = []

        async def second_read(args, context):
            del args, context
            calls.append("second_read")
            return {"text": "should not run", "result_count": 1}

        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            memory_manager=_FakeActionMemoryManager(),
            memory_summarizer=_FakeMemorySummarizer("模型总结。", model_tokens=8),
            action_cache=AIActionCache(),
        )
        registry._actions["test.second_read"] = AtomicActionSpec(
            name="test.second_read",
            kind="read",
            risk_level="low",
            handler=second_read,
        )
        executor = AIActionExecutor(
            registry=registry,
            store=store,
            runtime_budget=ActionRuntimeBudget(max_total_model_tokens=5),
        )
        plan = AIActionPlan(
            is_action=True,
            goal="模型 token 硬限制",
            steps=(
                AIActionStep(
                    id="summarize_memory",
                    action="memory.summarize",
                    args={
                        "source": {
                            "context_lines": ["[2026-04-24 15:20] README.md；摘要：AssistIM 文档总览。"],
                            "result_count": 1,
                        },
                        "question": "README.md 主要讲什么？",
                    },
                ),
                AIActionStep(id="second_read", action="test.second_read", depends_on=("summarize_memory",), args={}),
            ),
            final={"type": "answer", "source": "$second_read"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_runtime_model_token_budget",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)

            assert result.state == "failed"
            assert result.error_text == "RESOURCE_LIMIT_EXCEEDED: total_model_tokens"
            assert calls == []
            assert updated is not None
            completed_event = next(
                event
                for event in updated.plan_json["events"]
                if event["type"] == "step_completed" and event["step_id"] == "summarize_memory"
            )
            assert completed_event["resource_usage"]["model_tokens"] == 8
            assert updated.plan_json["events"][-1]["resource_limit"] == "total_model_tokens"
            assert updated.plan_json["resource_usage"]["total_model_tokens"] == 8
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_rejects_oversized_temp_result_before_persisting(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        async def huge_result(args, context):
            del args, context
            return {"results": [{"text": "x" * 240}], "result_count": 1}

        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        registry._actions["test.huge_result"] = AtomicActionSpec(
            name="test.huge_result",
            kind="read",
            risk_level="low",
            handler=huge_result,
            max_output_json_bytes=64,
        )
        executor = AIActionExecutor(
            registry=registry,
            store=store,
            runtime_budget=ActionRuntimeBudget(max_temp_result_bytes=100),
        )
        plan = AIActionPlan(
            is_action=True,
            goal="临时结果体积硬限制",
            steps=(AIActionStep(id="huge_result", action="test.huge_result", args={}),),
            final={"type": "answer", "source": "$huge_result"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_temp_result_budget",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)
            assert db._db is not None
            cursor = await db._db.execute("SELECT COUNT(*) FROM ai_action_temp_results")
            row = await cursor.fetchone()

            assert result.state == "failed"
            assert result.error_text == "RESOURCE_LIMIT_EXCEEDED: temp_result_bytes"
            assert row[0] == 0
            assert updated is not None
            assert "huge_result" not in updated.step_outputs
            assert updated.plan_json["events"][-1]["error_code"] == "RESOURCE_LIMIT_EXCEEDED"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_stops_after_runtime_output_budget_exceeded(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        calls: list[str] = []

        async def large_read(args, context):
            del args, context
            calls.append("large_read")
            return {"text": "x" * 220, "result_count": 1}

        async def second_read(args, context):
            del args, context
            calls.append("second_read")
            return {"text": "should not run", "result_count": 1}

        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        registry._actions["test.large_read"] = AtomicActionSpec(
            name="test.large_read",
            kind="read",
            risk_level="low",
            handler=large_read,
        )
        registry._actions["test.second_read"] = AtomicActionSpec(
            name="test.second_read",
            kind="read",
            risk_level="low",
            handler=second_read,
        )
        executor = AIActionExecutor(
            registry=registry,
            store=store,
            runtime_budget=ActionRuntimeBudget(max_total_output_bytes=120),
        )
        plan = AIActionPlan(
            is_action=True,
            goal="运行时硬限制",
            steps=(
                AIActionStep(id="large_read", action="test.large_read", args={}),
                AIActionStep(id="second_read", action="test.second_read", depends_on=("large_read",), args={}),
            ),
            final={"type": "answer", "source": "$second_read"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_runtime_output_budget",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)

            assert result.state == "failed"
            assert result.error_text == "RESOURCE_LIMIT_EXCEEDED: total_output_bytes"
            assert calls == ["large_read"]
            assert updated is not None
            assert updated.state == "failed"
            assert updated.error_text == "RESOURCE_LIMIT_EXCEEDED: total_output_bytes"
            assert "large_read" in updated.step_outputs
            assert "second_read" not in updated.step_outputs
            assert [event["type"] for event in updated.plan_json["events"]] == [
                "step_started",
                "step_completed",
                "plan_resource_limit_exceeded",
            ]
            assert updated.plan_json["events"][-1]["error_code"] == "RESOURCE_LIMIT_EXCEEDED"
            assert updated.plan_json["events"][-1]["resource_limit"] == "total_output_bytes"
            assert updated.plan_json["events"][-1]["step_id"] == "large_read"
            assert updated.plan_json["resource_usage"]["total_output_bytes"] > 120
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_runtime_budget_blocks_following_write_action(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        send_calls: list[dict] = []

        async def large_read(args, context):
            del args, context
            return {"text": "x" * 220, "result_count": 1}

        async def send_message(args, context):
            del context
            send_calls.append(dict(args))
            return {"status": "sent", "text": "sent", "target": dict(args.get("target") or {}), "content_chars": 4}

        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        registry._actions["test.large_read"] = AtomicActionSpec(
            name="test.large_read",
            kind="read",
            risk_level="low",
            handler=large_read,
        )
        send_spec = registry.get("message.send")
        assert send_spec is not None
        registry._actions["message.send"] = replace(send_spec, handler=send_message, enabled=True)
        executor = AIActionExecutor(
            registry=registry,
            store=store,
            runtime_budget=ActionRuntimeBudget(max_total_output_bytes=120),
        )
        plan = AIActionPlan(
            is_action=True,
            goal="超限后不能发送",
            risk="high",
            steps=(
                AIActionStep(id="large_read", action="test.large_read", args={}),
                AIActionStep(
                    id="send_message",
                    action="message.send",
                    depends_on=("large_read",),
                    args={
                        "target": {"contact_id": "user-1", "display_name": "张三"},
                        "content": "测试",
                        "preview": {"operation": "发送消息", "target": "张三", "content": "测试"},
                        "idempotency_key": "idem-runtime-budget",
                    },
                ),
            ),
            final={"type": "answer", "source": "$send_message.text"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_runtime_budget_before_write",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)

            assert result.state == "failed"
            assert result.error_text == "RESOURCE_LIMIT_EXCEEDED: total_output_bytes"
            assert send_calls == []
            assert updated is not None
            assert updated.state == "failed"
            assert "send_message" not in updated.step_outputs
            assert updated.plan_json["events"][-1]["type"] == "plan_resource_limit_exceeded"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_stops_after_runtime_result_count_budget_exceeded(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        async def many_results(args, context):
            del args, context
            return {"results": [{"id": "1"}, {"id": "2"}], "result_count": 2}

        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        registry._actions["test.many_results"] = AtomicActionSpec(
            name="test.many_results",
            kind="read",
            risk_level="low",
            handler=many_results,
        )
        executor = AIActionExecutor(
            registry=registry,
            store=store,
            runtime_budget=ActionRuntimeBudget(max_total_result_count=1),
        )
        plan = AIActionPlan(
            is_action=True,
            goal="结果数硬限制",
            steps=(AIActionStep(id="many_results", action="test.many_results", args={}),),
            final={"type": "answer", "source": "$many_results"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_runtime_result_count_budget",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)

            assert result.state == "failed"
            assert result.error_text == "RESOURCE_LIMIT_EXCEEDED: total_result_count"
            assert updated is not None
            assert updated.plan_json["events"][-1]["resource_limit"] == "total_result_count"
            assert updated.plan_json["resource_usage"]["total_result_count"] == 2
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_stops_after_runtime_result_ref_budget_exceeded(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        async def large_result(args, context):
            del args, context
            return {"results": [{"text": "x" * 200}], "result_count": 1}

        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        registry._actions["test.large_result"] = AtomicActionSpec(
            name="test.large_result",
            kind="read",
            risk_level="low",
            handler=large_result,
            max_output_json_bytes=64,
        )
        executor = AIActionExecutor(
            registry=registry,
            store=store,
            runtime_budget=ActionRuntimeBudget(max_result_ref_count=0),
        )
        plan = AIActionPlan(
            is_action=True,
            goal="result ref 硬限制",
            steps=(AIActionStep(id="large_result", action="test.large_result", args={}),),
            final={"type": "answer", "source": "$large_result"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_runtime_result_ref_budget",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)

            assert result.state == "failed"
            assert result.error_text == "RESOURCE_LIMIT_EXCEEDED: result_ref_count"
            assert updated is not None
            assert "result_ref" in updated.step_outputs["large_result"]
            assert updated.plan_json["events"][-1]["resource_limit"] == "result_ref_count"
            assert updated.plan_json["resource_usage"]["result_ref_count"] == 1
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_does_not_reuse_step_output_after_plan_version_changes(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        calls: list[list[str]] = []

        async def contact_output(args, context):
            del context
            queries = list(args.get("queries") or [])
            calls.append([str(item) for item in queries])
            label = str(queries[0] if queries else "")
            contact_id = "user-2" if label == "李四" else "user-1"
            return {
                "contacts": [{"contact_id": contact_id, "display_name": label or "张三"}],
                "groups": [],
                "ambiguous": [],
                "unresolved": [],
            }

        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        spec = registry.get("contact.resolve")
        assert spec is not None
        registry._actions["contact.resolve"] = replace(spec, handler=contact_output)
        executor = AIActionExecutor(registry=registry, store=store)
        plan = AIActionPlan(
            is_action=True,
            goal="解析联系人",
            steps=(
                AIActionStep(
                    id="resolve_contacts",
                    action="contact.resolve",
                    args={"queries": ["张三"], "allow_multiple": True},
                ),
            ),
            final={"type": "answer", "source": "$resolve_contacts.contacts[0].contact_id"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_versioned_outputs_initial",
            )
            first = await executor.execute(record)
            stored_first = await store.get_plan(record.id)
            assert first.response_text == "user-1"
            assert calls == [["张三"]]
            assert stored_first is not None
            assert stored_first.plan_version == 1
            assert stored_first.step_outputs["resolve_contacts"]["contacts"][0]["contact_id"] == "user-1"
            assert stored_first.step_outputs["_meta"]["step_versions"]["resolve_contacts"] == 1

            changed_plan = AIActionPlan(
                is_action=True,
                goal="解析联系人",
                steps=(
                    AIActionStep(
                        id="resolve_contacts",
                        action="contact.resolve",
                        args={"queries": ["李四"], "allow_multiple": True},
                    ),
                ),
                final={"type": "answer", "source": "$resolve_contacts.contacts[0].contact_id"},
            )
            updated_plan = await store.update_plan(
                record.id,
                plan_json=changed_plan.to_dict(),
                reason="test_versioned_outputs_changed_plan",
                state="running",
                current_step_id="",
                completed_at=0,
            )
            assert updated_plan is not None
            assert updated_plan.plan_version == 2

            second = await executor.execute(updated_plan)
            stored_second = await store.get_plan(record.id)

            assert second.response_text == "user-2"
            assert calls == [["张三"], ["李四"]]
            assert stored_second is not None
            assert stored_second.step_outputs["resolve_contacts"]["contacts"][0]["contact_id"] == "user-2"
            assert stored_second.step_outputs["_meta"]["step_versions"]["resolve_contacts"] == 2
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_does_not_retry_side_effect_action(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        calls = 0

        async def failing_send(args, context):
            nonlocal calls
            del args, context
            calls += 1
            raise RuntimeError("send failed")

        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        spec = registry.get("message.send")
        assert spec is not None
        registry._actions["message.send"] = replace(spec, handler=failing_send, enabled=True, max_retries=3)
        executor = AIActionExecutor(registry=registry, store=store)
        plan = AIActionPlan(
            is_action=True,
            goal="发送失败不重试",
            steps=(
                AIActionStep(
                    id="send_message",
                    action="message.send",
                    args={
                        "target": {"contact_id": "user-1", "display_name": "张三"},
                        "content": "我晚点到",
                        "preview": {"operation": "发送消息", "target": "张三", "content": "我晚点到"},
                        "idempotency_key": "idem-1",
                    },
                ),
            ),
            final={"type": "answer", "source": "$send_message"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_no_write_retry",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)

            assert result.state == "failed"
            assert result.error_text == "ACTION_FAILED: message.send"
            assert calls == 1
            assert updated is not None
            assert updated.state == "failed"
            assert updated.step_outputs == {}
            assert [event["type"] for event in updated.plan_json["events"]] == ["step_started", "step_failed"]
            assert updated.plan_json["events"][-1]["error_code"] == "ACTION_FAILED"
            assert "step_retrying" not in [event["type"] for event in updated.plan_json["events"]]
            assert "step_attempt_failed" not in [event["type"] for event in updated.plan_json["events"]]
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_rejects_spec_guardrail_violations_before_handler(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        cases = [
            {
                "name": "contact_targets",
                "action": "contact.resolve",
                "args": {"queries": [f"用户{index}" for index in range(6)], "allow_multiple": True},
                "error": "PLAN_TOO_LARGE: too many targets",
            },
            {
                "name": "send_content_chars",
                "action": "message.send",
                "args": {
                    "target": {"contact_id": "user-1", "display_name": "张三"},
                    "content": "x" * 501,
                    "preview": {"operation": "发送消息", "target": "张三", "content": "x" * 501},
                    "idempotency_key": "idem-1",
                },
                "error": "PAYLOAD_TOO_LARGE: content",
            },
            {
                "name": "send_idempotency",
                "action": "message.send",
                "args": {
                    "target": {"contact_id": "user-1", "display_name": "张三"},
                    "content": "我晚点到",
                    "preview": {"operation": "发送消息", "target": "张三", "content": "我晚点到"},
                },
                "error": "IDEMPOTENCY_KEY_REQUIRED",
            },
            {
                "name": "send_unresolved_target",
                "action": "message.send",
                "args": {
                    "target": {"display_name": "张三"},
                    "content": "我晚点到",
                    "preview": {"operation": "发送消息", "target": "张三", "content": "我晚点到"},
                    "idempotency_key": "idem-1",
                },
                "error": "ARG_SCHEMA_INVALID: target",
            },
            {
                "name": "send_batch_target",
                "action": "message.send",
                "args": {
                    "target": [
                        {"contact_id": "user-1", "display_name": "张三"},
                        {"contact_id": "user-2", "display_name": "李四"},
                    ],
                    "content": "我晚点到",
                    "preview": {"operation": "发送消息", "target": "张三、李四", "content": "我晚点到"},
                    "idempotency_key": "idem-1",
                },
                "error": "BATCH_NOT_ALLOWED",
            },
        ]

        for index, case in enumerate(cases):
            calls = 0

            async def forbidden_handler(args, context):
                nonlocal calls
                del args, context
                calls += 1
                return {"status": "unexpected", "text": "不应执行"}

            db = Database(str(tmp_path / f"guardrail_{index}_{case['name']}.db"))
            monkeypatch.setattr(action_store_module, "get_database", lambda: db)
            store = AIActionStore()
            registry = AtomicActionRegistry(
                contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
            )
            spec = registry.get(str(case["action"]))
            assert spec is not None
            registry._actions[str(case["action"])] = replace(spec, handler=forbidden_handler, enabled=True)
            executor = AIActionExecutor(registry=registry, store=store)
            plan = AIActionPlan(
                is_action=True,
                goal=f"guardrail {case['name']}",
                risk="high" if case["action"] == "message.send" else "low",
                steps=(
                    AIActionStep(
                        id="guarded_step",
                        action=str(case["action"]),
                        args=dict(case["args"]),
                    ),
                ),
                final={"type": "answer", "source": "$guarded_step"},
            )
            try:
                record = await store.create_plan(
                    thread_id=f"thread-{index}",
                    goal=plan.goal,
                    plan_json=plan.to_dict(),
                    reason=f"test_guardrail_{case['name']}",
                )
                result = await executor.execute(record)
                updated = await store.get_plan(record.id)

                assert result.state == "failed", case["name"]
                assert result.error_text == case["error"], case["name"]
                assert calls == 0, case["name"]
                assert updated is not None
                assert updated.state == "failed", case["name"]
                assert updated.error_text == case["error"], case["name"]
                assert updated.step_outputs == {}, case["name"]
                assert [event["type"] for event in updated.plan_json["events"]] == ["step_failed"], case["name"]
                assert updated.plan_json["events"][0]["step_id"] == "guarded_step", case["name"]
                assert updated.plan_json["events"][0]["action"] == case["action"], case["name"]
                assert updated.plan_json["events"][0]["error_code"] == case["error"].split(":", 1)[0], case["name"]
            finally:
                await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_records_step_failed_event_for_missing_dependency(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        executor = AIActionExecutor(registry=registry, store=store)
        plan = AIActionPlan(
            is_action=True,
            goal="缺失依赖",
            steps=(
                AIActionStep(
                    id="search_memory",
                    action="memory.search",
                    depends_on=("missing_step",),
                    args={
                        "question": "聊过什么",
                        "participants": ["张三"],
                        "participant_match": "any",
                        "time_scope": {"type": "all_history"},
                    },
                ),
            ),
            final={"type": "answer", "source": "$search_memory"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_missing_dependency_event",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)

            assert result.state == "failed"
            assert result.error_text == "ARG_REFERENCE_INVALID: missing dependency missing_step"
            assert updated is not None
            assert updated.state == "failed"
            assert updated.error_text == "ARG_REFERENCE_INVALID: missing dependency missing_step"
            assert updated.step_outputs == {}
            assert [event["type"] for event in updated.plan_json["events"]] == ["step_failed"]
            assert updated.plan_json["events"][0]["step_id"] == "search_memory"
            assert updated.plan_json["events"][0]["action"] == "memory.search"
            assert updated.plan_json["events"][0]["error_code"] == "ARG_REFERENCE_INVALID"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_persists_waiting_confirmation_event(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        executor = AIActionExecutor(registry=registry, store=store)
        plan = AIActionPlan(
            is_action=True,
            goal="等待确认",
            risk="high",
            steps=(
                AIActionStep(
                    id="confirm_send",
                    action="user.confirm",
                    args={
                        "risk": "high",
                        "preview": {
                            "operation": "发送消息",
                            "target": "张三",
                            "content": "我晚点到",
                        },
                    },
                ),
            ),
            final={"type": "answer", "source": "$confirm_send"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_waiting_event",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)

            assert result.state == "waiting_confirmation"
            assert updated is not None
            assert updated.state == "waiting_confirmation"
            assert [event["type"] for event in updated.plan_json["events"]] == [
                "step_started",
                "step_waiting_confirmation",
            ]
            assert updated.plan_json["events"][-1]["step_id"] == "confirm_send"
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


def test_ai_action_workflow_default_planner_uses_task_manager(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        task_manager = _FakePlannerTaskManager(
            '{"is_action": false, "goal": "普通聊天", "risk": "low", "steps": [], "final": {}}'
        )
        workflow = AIActionWorkflow(
            action_store=store,
            task_manager=task_manager,
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="你好")

            assert result.handled is False
            assert len(task_manager.requests) == 1
            request = task_manager.requests[0]
            assert request.metadata["source"] == "ai_action_planner"
            assert request.metadata["planner_prompt_kind"] == AIActionPlanner.PROMPT_NEW_ACTION
            assert request.response_format["type"] == "json_object"
            assert "用户输入：你好" in request.messages[0]["content"]
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_default_planner_can_surface_send_confirmation_for_transfer_phrase(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        task_manager = _FakePlannerTaskManager(
            """
            {
              "is_action": true,
              "goal": "发送消息",
              "risk": "high",
              "steps": [
                {
                  "id": "resolve_target",
                  "action": "contact.resolve",
                  "depends_on": [],
                  "args": {"queries": ["test3"], "allow_multiple": false}
                },
                {
                  "id": "draft_message",
                  "action": "message.draft",
                  "depends_on": ["resolve_target"],
                  "args": {"target": "$resolve_target.contacts[0]", "content": "我晚点联系他"}
                },
                {
                  "id": "confirm_send",
                  "action": "user.confirm",
                  "depends_on": ["draft_message"],
                  "args": {
                    "risk": "high",
                    "preview": {
                      "operation": "发送消息",
                      "target": "$draft_message.target",
                      "content": "$draft_message.content"
                    }
                  }
                },
                {
                  "id": "send_message",
                  "action": "message.send",
                  "depends_on": ["confirm_send", "draft_message"],
                  "args": {
                    "target": "$draft_message.target_entity",
                    "content": "$draft_message.content",
                    "preview": "$draft_message.preview",
                    "idempotency_key": "$draft_message.idempotency_key"
                  }
                }
              ],
              "final": {"type": "answer", "source": "$send_message.text"}
            }
            """
        )
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
        workflow = AIActionWorkflow(
            action_store=store,
            task_manager=task_manager,
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
            message_sender=_FakeActionMessageSender(),
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="给test3说一声我晚点联系他")

            assert result.handled is True
            assert result.message_extra["ai_action"]["state"] == "waiting_confirmation"
            assert result.message_extra["ai_action"]["action"] == "send_message"
            assert "确认要发送消息给test3" in result.response_text
            assert "我晚点联系他" in result.response_text
            assert len(task_manager.requests) == 1
            assert contact_db.resolve_calls == [{"alias": "test3", "limit": 20}]
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_sends_message_after_confirmation(tmp_path, monkeypatch) -> None:
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
        message_sender = _FakeActionMessageSender()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_WorkflowPlanner(),
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
            message_sender=message_sender,
        )
        try:
            result = await workflow.handle_user_turn(thread_id="thread-1", text="帮我给张三发我晚点到")

            assert result.handled is True
            assert "确认要发送消息给张三" in result.response_text
            assert result.message_extra["ai_action"]["action"] == "send_message"
            assert result.message_extra["ai_action"]["state"] == "waiting_confirmation"
            assert message_sender.calls == []

            confirmed = await workflow.handle_user_turn(thread_id="thread-1", text="确认")
            assert confirmed.handled is True
            assert "已发送给张三" in confirmed.response_text
            assert confirmed.message_extra["ai_action"]["state"] == "done"
            assert len(message_sender.calls) == 1
            assert message_sender.calls[0]["target"]["contact_id"] == "user-1"
            assert message_sender.calls[0]["content"] == "我晚点到"
            assert message_sender.calls[0]["idempotency_key"]
            assert len(contact_db.resolve_calls) == 1
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_structured_confirm_bypasses_pending_planner(tmp_path, monkeypatch) -> None:
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
        message_sender = _FakeActionMessageSender()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=planner,
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
            message_sender=message_sender,
        )
        try:
            first = await workflow.handle_user_turn(thread_id="thread-1", text="帮我给张三发我晚点到")
            assert first.handled is True
            assert first.message_extra["ai_action"]["state"] == "waiting_confirmation"

            confirmed = await workflow.handle_pending_control(thread_id="thread-1", control_type="confirm")

            assert confirmed.handled is True
            assert "已发送给张三" in confirmed.response_text
            assert confirmed.message_extra["ai_action"]["state"] == "done"
            assert len(message_sender.calls) == 1
            assert planner.calls == [("帮我给张三发我晚点到", False)]
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_structured_cancel_bypasses_pending_planner(tmp_path, monkeypatch) -> None:
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
        message_sender = _FakeActionMessageSender()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=planner,
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
            message_sender=message_sender,
        )
        try:
            first = await workflow.handle_user_turn(thread_id="thread-1", text="帮我给张三发我晚点到")
            plan_id = first.message_extra["ai_action"]["plan_id"]

            cancelled = await workflow.handle_pending_control(thread_id="thread-1", control_type="cancel")
            record = await store.get_plan(plan_id)

            assert cancelled.handled is True
            assert cancelled.response_text == "已取消这个操作。"
            assert cancelled.message_extra["ai_action"]["state"] == "cancelled"
            assert record is not None
            assert record.state == "cancelled"
            assert message_sender.calls == []
            assert planner.calls == [("帮我给张三发我晚点到", False)]
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_cancel_plan_marks_active_plan_cancelled(tmp_path, monkeypatch) -> None:
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
        progress_updates = []

        async def on_progress(turn) -> None:
            progress_updates.append(turn)

        try:
            first = await workflow.handle_user_turn(thread_id="thread-1", text="帮我给张三发我晚点到")
            plan_id = first.message_extra["ai_action"]["plan_id"]

            cancelled = await workflow.cancel_plan(plan_id, progress_callback=on_progress)
            record = await store.get_plan(plan_id)

            assert cancelled.handled is True
            assert cancelled.response_text == "已取消这个操作。"
            assert cancelled.message_extra["ai_action"]["state"] == "cancelled"
            assert record is not None
            assert record.state == "cancelled"
            assert record.current_step_id == ""
            assert record.plan_json["events"][-1]["type"] == "plan_cancelled"
            assert progress_updates[-1].message_extra["ai_action"]["state"] == "cancelled"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_store_recovers_only_running_plans_on_startup(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        plan = _atomic_send_plan()
        try:
            running = await store.create_plan(
                thread_id="thread-1",
                goal="运行中计划",
                plan_json=plan.to_dict(),
                state="running",
                reason="test_running",
            )
            running = await store.update_plan(
                running.id,
                current_step_id="draft_message",
                waiting_payload={"response_text": "旧的执行中提示"},
                step_outputs={"resolve_target": {"contacts": [{"contact_id": "user-1"}]}},
                reason="test_running_state",
                bump_version=False,
            )
            waiting_confirmation = await store.create_plan(
                thread_id="thread-1",
                goal="等待确认计划",
                plan_json=plan.to_dict(),
                state="waiting_confirmation",
                reason="test_waiting_confirmation",
            )
            waiting_clarification = await store.create_plan(
                thread_id="thread-1",
                goal="等待补充计划",
                plan_json=plan.to_dict(),
                state="waiting_clarification",
                reason="test_waiting_clarification",
            )

            recovered = await store.recover_interrupted_plans()
            recovered_running = await store.get_plan(running.id)
            preserved_confirmation = await store.get_plan(waiting_confirmation.id)
            preserved_clarification = await store.get_plan(waiting_clarification.id)
            pending = await store.latest_pending_plan("thread-1")

            assert [item.id for item in recovered] == [running.id]
            assert recovered_running is not None
            assert recovered_running.state == "failed"
            assert recovered_running.error_text == "interrupted_recoverable"
            assert recovered_running.current_step_id == ""
            assert recovered_running.waiting_payload == {}
            assert recovered_running.completed_at > 0
            assert recovered_running.step_outputs == running.step_outputs
            assert recovered_running.plan_json["events"][-1]["type"] == "plan_interrupted"
            assert preserved_confirmation is not None
            assert preserved_confirmation.state == "waiting_confirmation"
            assert preserved_clarification is not None
            assert preserved_clarification.state == "waiting_clarification"
            assert pending is not None
            assert pending.id in {waiting_confirmation.id, waiting_clarification.id}
            assert pending.id != running.id
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_recovers_interrupted_plans(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        workflow = AIActionWorkflow(action_store=store, planner=_WorkflowPlanner())
        plan = _atomic_send_plan()
        try:
            running = await store.create_plan(
                thread_id="thread-1",
                goal="运行中计划",
                plan_json=plan.to_dict(),
                state="running",
                reason="test_workflow_recover",
            )

            recovered = await workflow.recover_interrupted_plans()
            latest = await store.get_plan(running.id)

            assert [item.id for item in recovered] == [running.id]
            assert latest is not None
            assert latest.state == "failed"
            assert latest.error_text == "interrupted_recoverable"
            assert latest.plan_json["events"][-1]["type"] == "plan_interrupted"
            assert await store.latest_pending_plan("thread-1") is None
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_expires_stale_confirmation_before_next_user_turn(tmp_path, monkeypatch) -> None:
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
                },
                {
                    "id": "user-3",
                    "display_name": "test3",
                    "username": "test3",
                    "nickname": "test3",
                    "remark": "",
                    "assistim_id": "test3",
                },
            ]
        )
        planner = _WorkflowPlanner()
        memory_manager = _FakeActionMemoryManager(context_lines=["test3 收到过 README.md 文件。"])
        message_sender = _FakeActionMessageSender()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=planner,
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
            memory_manager=memory_manager,
            message_sender=message_sender,
        )
        try:
            first = await workflow.handle_user_turn(thread_id="thread-1", text="帮我给张三发我晚点到")
            plan_id = first.message_extra["ai_action"]["plan_id"]
            assert first.message_extra["ai_action"]["state"] == "waiting_confirmation"

            old_ts = time.time() - AIActionWorkflow.PENDING_CONFIRMATION_TTL_SECONDS - 5
            await store._connection().execute(  # noqa: SLF001
                "UPDATE ai_action_plans SET updated_at = ? WHERE id = ?",
                (old_ts, plan_id),
            )
            await store._connection().commit()  # noqa: SLF001

            second = await workflow.handle_user_turn(thread_id="thread-1", text="我和test3聊过什么？")
            expired = await store.get_plan(plan_id)

            assert second.handled is True
            assert planner.calls[-1] == ("我和test3聊过什么？", False)
            assert memory_manager.calls
            assert message_sender.calls == []
            assert expired is not None
            assert expired.state == "cancelled"
            assert expired.error_text == "expired_confirmation"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_rejects_expired_structured_confirmation(tmp_path, monkeypatch) -> None:
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
        message_sender = _FakeActionMessageSender()
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_WorkflowPlanner(),
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
            message_sender=message_sender,
        )
        try:
            first = await workflow.handle_user_turn(thread_id="thread-1", text="帮我给张三发我晚点到")
            plan_id = first.message_extra["ai_action"]["plan_id"]
            assert first.message_extra["ai_action"]["state"] == "waiting_confirmation"

            old_ts = time.time() - AIActionWorkflow.PENDING_CONFIRMATION_TTL_SECONDS - 5
            await store._connection().execute(  # noqa: SLF001
                "UPDATE ai_action_plans SET updated_at = ? WHERE id = ?",
                (old_ts, plan_id),
            )
            await store._connection().commit()  # noqa: SLF001

            confirmed = await workflow.handle_pending_control(thread_id="thread-1", control_type="confirm")
            latest = await store.get_plan(plan_id)

            assert confirmed.handled is True
            assert "确认已过期" in confirmed.response_text
            assert confirmed.message_extra["ai_action"]["state"] == "cancelled"
            assert message_sender.calls == []
            assert latest is not None
            assert latest.state == "cancelled"
            assert latest.error_text == "expired_confirmation"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_reports_missing_send_session_after_confirmation(tmp_path, monkeypatch) -> None:
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
        message_sender = _FakeActionMessageSender(
            result={
                "status": "failed",
                "error_code": "SESSION_NOT_FOUND",
                "text": "没有找到可发送的会话，请先打开或创建与张三的私聊。",
                "target": {"contact_id": "user-1", "display_name": "张三"},
                "content_chars": 4,
            }
        )
        workflow = AIActionWorkflow(
            action_store=store,
            planner=_WorkflowPlanner(),
            contact_alias_resolver=ContactAliasResolver(db=contact_db),
            message_sender=message_sender,
        )
        try:
            first = await workflow.handle_user_turn(thread_id="thread-1", text="帮我给张三发我晚点到")
            confirmed = await workflow.handle_user_turn(thread_id="thread-1", text="确认")
            plan = await store.get_plan(first.message_extra["ai_action"]["plan_id"])

            assert confirmed.handled is True
            assert "没有找到可发送的会话" in confirmed.response_text
            assert confirmed.message_extra["ai_action"]["state"] == "done"
            assert len(message_sender.calls) == 1
            assert plan is not None
            assert plan.step_outputs["send_message"]["status"] == "failed"
            assert plan.step_outputs["send_message"]["error_code"] == "SESSION_NOT_FOUND"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_message_sender_uses_existing_direct_session() -> None:
    async def scenario() -> None:
        session = Session(
            session_id="session-direct-1",
            name="张三",
            session_type="direct",
            participant_ids=["me", "user-1"],
            extra={"counterpart_id": "user-1"},
        )
        message_manager = _FakeDirectMessageManager()
        sender = AIActionMessageSender(
            session_manager=SimpleNamespace(current_session=None, sessions=[session]),
            message_manager=message_manager,
        )

        result = await sender.send_text_to_contact(
            target={"contact_id": "user-1", "display_name": "张三"},
            content="我晚点到",
            idempotency_key="idem-1",
            plan_id="plan-1",
        )

        assert result["status"] == "sent"
        assert result["session_id"] == "session-direct-1"
        assert result["message_id"] == "message-ai-1"
        assert result["text"] == "已发送给张三。"
        assert len(message_manager.calls) == 1
        assert message_manager.calls[0]["session_id"] == "session-direct-1"
        assert message_manager.calls[0]["content"] == "我晚点到"
        assert message_manager.calls[0]["extra"]["ai_action_send"]["plan_id"] == "plan-1"

    asyncio.run(scenario())


def test_ai_action_message_sender_requires_existing_direct_session() -> None:
    async def scenario() -> None:
        message_manager = _FakeDirectMessageManager()
        sender = AIActionMessageSender(
            session_manager=SimpleNamespace(current_session=None, sessions=[]),
            message_manager=message_manager,
        )

        result = await sender.send_text_to_contact(
            target={"contact_id": "user-1", "display_name": "张三"},
            content="我晚点到",
            idempotency_key="idem-1",
            plan_id="plan-1",
        )

        assert result["status"] == "failed"
        assert result["error_code"] == "SESSION_NOT_FOUND"
        assert "没有找到可发送的会话" in result["text"]
        assert message_manager.calls == []

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


def test_ai_action_workflow_rejects_stale_pending_confirmation_after_plan_version_changes(tmp_path, monkeypatch) -> None:
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
            first = await workflow.handle_user_turn(thread_id="thread-1", text="帮我给张三发我晚点到")
            assert first.handled is True
            plan_id = first.message_extra["ai_action"]["plan_id"]
            assert first.message_extra["ai_action"]["state"] == "waiting_confirmation"

            record = await store.get_plan(plan_id)
            assert record is not None
            assert record.plan_version == 1
            assert record.waiting_payload["plan_version"] == 1
            assert "confirm_send" not in record.step_outputs

            mutated_plan_json = dict(record.plan_json)
            mutated_plan_json["goal"] = "测试中模拟确认期间计划内容变化"
            mutated = await store.update_plan(
                plan_id,
                plan_json=mutated_plan_json,
                reason="test_mutate_pending_confirmation",
            )
            assert mutated is not None
            assert mutated.plan_version == 2
            assert mutated.state == "waiting_confirmation"

            confirmed = await workflow.handle_user_turn(thread_id="thread-1", text="确认")
            latest = await store.get_plan(plan_id)

            assert confirmed.handled is True
            assert "操作内容已变化" in confirmed.response_text
            assert confirmed.message_extra["ai_action"]["state"] == "waiting_confirmation"
            assert latest is not None
            assert latest.state == "waiting_confirmation"
            assert "confirm_send" not in latest.step_outputs
            assert "send_message" not in latest.step_outputs
            assert latest.waiting_payload["plan_version"] == 1
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_workflow_rejects_stale_pending_confirmation_after_preview_changes(tmp_path, monkeypatch) -> None:
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
            first = await workflow.handle_user_turn(thread_id="thread-1", text="帮我给张三发我晚点到")
            assert first.handled is True
            plan_id = first.message_extra["ai_action"]["plan_id"]
            assert first.message_extra["ai_action"]["state"] == "waiting_confirmation"

            record = await store.get_plan(plan_id)
            assert record is not None
            assert record.plan_version == 1
            assert record.waiting_payload["plan_version"] == 1
            assert record.waiting_payload["preview"]["content"] == "我晚点到"
            assert record.step_outputs["draft_message"]["preview"]["content"] == "我晚点到"

            mutated_outputs = dict(record.step_outputs)
            mutated_draft = dict(mutated_outputs["draft_message"])
            mutated_preview = dict(mutated_draft["preview"])
            mutated_preview["content"] = "我改成明天到"
            mutated_draft["content"] = "我改成明天到"
            mutated_draft["preview"] = mutated_preview
            mutated_outputs["draft_message"] = mutated_draft
            mutated = await store.update_plan(
                plan_id,
                step_outputs=mutated_outputs,
                reason="test_mutate_pending_confirmation_preview",
            )
            assert mutated is not None
            assert mutated.plan_version == 1
            assert mutated.state == "waiting_confirmation"

            confirmed = await workflow.handle_user_turn(thread_id="thread-1", text="确认")
            latest = await store.get_plan(plan_id)

            assert confirmed.handled is True
            assert "操作内容已变化" in confirmed.response_text
            assert confirmed.message_extra["ai_action"]["state"] == "waiting_confirmation"
            assert latest is not None
            assert latest.state == "waiting_confirmation"
            assert "confirm_send" not in latest.step_outputs
            assert "send_message" not in latest.step_outputs
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


def test_ai_action_executor_stops_after_plan_is_cancelled_between_steps(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        calls: list[str] = []

        async def first_handler(args, context):
            del args, context
            calls.append("first")
            return {"text": "第一步完成"}

        async def second_handler(args, context):
            del args, context
            calls.append("second")
            return {"text": "第二步完成"}

        registry._actions["test.first"] = AtomicActionSpec(
            name="test.first",
            kind="read",
            risk_level="low",
            handler=first_handler,
        )
        registry._actions["test.second"] = AtomicActionSpec(
            name="test.second",
            kind="read",
            risk_level="low",
            handler=second_handler,
        )
        executor = AIActionExecutor(registry=registry, store=store)
        plan = AIActionPlan(
            is_action=True,
            goal="可取消计划",
            steps=(
                AIActionStep(id="first", action="test.first"),
                AIActionStep(id="second", action="test.second", depends_on=("first",)),
            ),
            final={"type": "answer", "source": "$second.text"},
        )
        cancelled_once = False

        async def on_progress(record) -> None:
            nonlocal cancelled_once
            if cancelled_once:
                return
            if "first" in dict(record.step_outputs or {}) and record.state == "running":
                cancelled_once = True
                await store.update_plan(record.id, state="cancelled")

        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_cancel_between_steps",
            )
            result = await executor.execute(record, progress_callback=on_progress)
            updated = await store.get_plan(record.id)

            assert result.state == "cancelled"
            assert result.response_text == "已取消这个操作。"
            assert calls == ["first"]
            assert updated is not None
            assert updated.state == "cancelled"
            assert "first" in updated.step_outputs
            assert "second" not in updated.step_outputs
            assert updated.current_step_id == ""
            assert updated.plan_json["events"][-1]["type"] == "plan_cancelled"
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
            memory_summarizer=_FakeMemorySummarizer("大结果已分块总结。"),
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
            search_event = next(
                event
                for event in updated.plan_json["events"]
                if event["type"] == "step_completed" and event["step_id"] == "search_memory"
            )
            assert search_event["resource_usage"]["result_ref"] is True
            assert search_event["resource_usage"]["result_count"] == 20
            assert search_event["resource_usage"]["output_bytes"] > 256
            summarize_event = next(
                event
                for event in updated.plan_json["events"]
                if event["type"] == "step_completed" and event["step_id"] == "summarize_memory"
            )
            assert summarize_event["resource_usage"]["model_call_cost"] == 1
            assert updated.plan_json["resource_usage"]["result_ref_count"] == 1
            assert updated.plan_json["resource_usage"]["total_model_call_cost"] == 1
            assert result.state == "done"
            assert result.response_text == "大结果已分块总结。"
            assert result.memory_context_lines == ()
            assert updated.step_outputs["summarize_memory"]["chunked"] is True
            assert updated.step_outputs["summarize_memory"]["input_result_count"] == 20
            assert updated.step_outputs["summarize_memory"]["text"] == "大结果已分块总结。"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_ai_action_executor_fails_memory_summarize_when_result_ref_expired(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        db = Database(str(tmp_path / "actions.db"))
        monkeypatch.setattr(action_store_module, "get_database", lambda: db)
        store = AIActionStore()
        temp = await store.create_temp_result(
            plan_id="expired-plan",
            step_id="search_memory",
            result_type="memory.search",
            payload={
                "context_lines": ["[2026-04-21 10:00] 摘要：旧临时结果。"],
                "result_count": 1,
            },
        )
        assert db._db is not None
        await db._db.execute("UPDATE ai_action_temp_results SET expires_at = 1 WHERE id = ?", (temp.id,))
        await db._db.commit()
        assert await store.get_temp_result(temp.id) is None

        registry = AtomicActionRegistry(
            contact_resolver=ContactAliasResolver(db=_FakeContactDatabase([])),
        )
        executor = AIActionExecutor(registry=registry, store=store)
        plan = AIActionPlan(
            is_action=True,
            goal="过期临时结果",
            steps=(
                AIActionStep(
                    id="summarize_memory",
                    action="memory.summarize",
                    args={
                        "source": {
                            "result_ref": {
                                "type": "memory.search",
                                "id": temp.id,
                                "result_count": 1,
                            }
                        },
                        "question": "查历史",
                    },
                ),
            ),
            final={"type": "answer", "source": "$summarize_memory"},
        )
        try:
            record = await store.create_plan(
                thread_id="thread-1",
                goal=plan.goal,
                plan_json=plan.to_dict(),
                reason="test_expired_temp_result",
            )
            result = await executor.execute(record)
            updated = await store.get_plan(record.id)

            assert result.state == "failed"
            assert result.error_text == "TEMP_RESULT_EXPIRED"
            assert updated is not None
            assert updated.state == "failed"
            assert updated.error_text == "TEMP_RESULT_EXPIRED"
            assert "summarize_memory" not in updated.step_outputs
            assert [event["type"] for event in updated.plan_json["events"]] == ["step_started", "step_failed"]
            assert updated.plan_json["events"][-1]["step_id"] == "summarize_memory"
            assert updated.plan_json["events"][-1]["action"] == "memory.summarize"
            assert updated.plan_json["events"][-1]["error_code"] == "TEMP_RESULT_EXPIRED"
        finally:
            await db.close()

    asyncio.run(scenario())
