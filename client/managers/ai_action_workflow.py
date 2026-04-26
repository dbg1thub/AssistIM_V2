"""AI assistant action workflow based on atomic executable plans."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Sequence

from client.core import logging
from client.managers.ai_action_executor import AIActionExecutor
from client.managers.ai_action_normalizer import AIPlanNormalizer
from client.managers.ai_action_optimizer import AIPlanOptimizer
from client.managers.ai_action_permission_policy import AIPermissionPolicy, AIPermissionScope
from client.managers.ai_action_registry import AtomicActionRegistry
from client.managers.ai_action_resource_manager import AIResourceManager
from client.managers.ai_action_types import (
    AIActionPlan,
    AIActionStep,
    AIActionTurnResult,
    ActionExecutionResult,
    confirmation_preview_fingerprint,
    mark_step_output_current,
)
from client.managers.ai_action_validator import AIPlanValidationResult, AIPlanValidator
from client.managers.ai_task_manager import get_ai_task_manager
from client.storage.ai_action_plan_store import AIActionPlanRecord, AIActionPlanStore
from client.storage.ai_action_store import AIActionStore, get_ai_action_store
from client.storage.database import Database, get_database


logger = logging.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ContactAliasCandidate:
    """One local contact identity candidate for an ambiguous user-facing alias."""

    contact_id: str
    display_name: str = ""
    username: str = ""
    nickname: str = ""
    remark: str = ""
    assistim_id: str = ""


@dataclass(frozen=True, slots=True)
class ContactAliasResolution:
    """Expanded query terms, or an ambiguity that must be clarified before lookup."""

    expanded_terms: tuple[str, ...] = ()
    ambiguous_query: str = ""
    candidates: tuple[ContactAliasCandidate, ...] = ()

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.ambiguous_query and self.candidates)


@dataclass(frozen=True, slots=True)
class PendingPlannerState:
    """Structured pending state given back to the planner for resume decisions."""

    id: str
    thread_id: str
    ai_thread_id: str
    state: str
    waiting_payload: dict[str, Any]


class ContactAliasResolver:
    """Resolve user-facing contact aliases to stable local identity terms."""

    SEARCH_LIMIT = 20

    def __init__(self, db: Database | None = None) -> None:
        self._db = db or get_database()

    async def get_contact_index_version(self) -> str:
        get_version = getattr(self._db, "get_contacts_cache_index_version", None)
        if not callable(get_version):
            return ""
        try:
            return str(await get_version() or "").strip()
        except Exception:
            logger.debug("Contact cache index version lookup failed", exc_info=True)
            return ""

    async def expand_terms(self, participants: Sequence[str]) -> ContactAliasResolution:
        expanded_terms: list[str] = []

        def add(raw_value: object) -> None:
            value = _normalize_text(str(raw_value or "")).strip(" ，,。")
            if value and value not in expanded_terms:
                expanded_terms.append(value)

        for participant in _clean_list(list(participants or [])):
            add(participant)
            exact_matches = await self._exact_matches(participant)
            if len(exact_matches) > 1:
                return ContactAliasResolution(
                    expanded_terms=tuple(expanded_terms),
                    ambiguous_query=participant,
                    candidates=tuple(exact_matches[:5]),
                )
            if len(exact_matches) == 1:
                for term in _candidate_terms(exact_matches[0]):
                    add(term)

        return ContactAliasResolution(expanded_terms=tuple(expanded_terms))

    async def _exact_matches(self, alias: str) -> list[ContactAliasCandidate]:
        normalized_alias = _alias_key(alias)
        if not normalized_alias:
            return []

        contacts: list[dict[str, Any]] = []
        resolve_alias = getattr(self._db, "resolve_contacts_cache_alias", None)
        if resolve_alias is not None:
            try:
                contacts = list(await resolve_alias(alias, limit=self.SEARCH_LIMIT))
            except Exception:
                logger.debug("Contact exact alias lookup failed for %s", alias, exc_info=True)

        if not contacts:
            search = getattr(self._db, "search_contacts", None)
            if search is not None:
                try:
                    contacts = list(await search(alias, limit=self.SEARCH_LIMIT))
                except Exception:
                    logger.debug("Contact alias lookup failed for %s", alias, exc_info=True)
                    contacts = []

        matches: list[ContactAliasCandidate] = []
        seen_ids: set[str] = set()
        for contact in list(contacts or []):
            candidate = _contact_candidate_from_payload(contact)
            if candidate is None or not candidate.contact_id or candidate.contact_id in seen_ids:
                continue
            if normalized_alias not in {_alias_key(term) for term in _candidate_terms(candidate)}:
                continue
            seen_ids.add(candidate.contact_id)
            matches.append(candidate)

        direct_id_candidate = await self._contact_by_id(alias)
        if direct_id_candidate is not None and direct_id_candidate.contact_id not in seen_ids:
            matches.append(direct_id_candidate)
        return matches

    async def _contact_by_id(self, alias: str) -> ContactAliasCandidate | None:
        list_by_ids = getattr(self._db, "list_contacts_cache_by_ids", None)
        if list_by_ids is None:
            return None
        normalized_alias = _normalize_text(alias)
        if not normalized_alias:
            return None
        try:
            contacts_by_id = await list_by_ids([normalized_alias])
        except Exception:
            logger.debug("Contact id lookup failed for %s", alias, exc_info=True)
            return None
        contact = dict((contacts_by_id or {}).get(normalized_alias) or {})
        return _contact_candidate_from_payload(contact)


class AIActionPlanner:
    """Optional model-backed planner that returns atomic JSON action plans."""

    PLANNER_SCHEMA_VERSION = "atomic_steps_v1"
    PLANNER_PROMPT_VERSION = "atomic_steps_prompt_v1"
    PLAN_OUTPUT_VERSION = 1

    PROMPT_NEW_ACTION = "new_action"
    PROMPT_PENDING_CONFIRMATION = "pending_confirmation"
    PROMPT_PENDING_CONTACT_SELECTION = "pending_contact_selection"
    PROMPT_PENDING_CLARIFICATION = "pending_clarification"

    ACTION_STEP_SCHEMA: dict[str, Any] = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "action": {"type": "string"},
            "depends_on": {"type": "array", "items": {"type": "string"}},
            "args": {"type": "object"},
            "display_text": {"type": "string"},
            "explanation": {"type": "string"},
        },
        "required": ["id", "action", "depends_on", "args"],
        "additionalProperties": False,
    }
    NEW_ACTION_SCHEMA: dict[str, Any] = {
        "type": "object",
        "properties": {
            "is_action": {"type": "boolean"},
            "goal": {"type": "string"},
            "risk": {"type": "string", "enum": ["low", "medium", "high"]},
            "steps": {
                "type": "array",
                "items": ACTION_STEP_SCHEMA,
            },
            "final": {"type": "object"},
        },
        "required": ["is_action", "goal", "risk", "steps", "final"],
        "additionalProperties": False,
    }
    PENDING_CONTROL_SCHEMA: dict[str, Any] = {
        "type": "object",
        "properties": {
            "is_action": {"type": "boolean"},
            "goal": {"type": "string"},
            "risk": {"type": "string", "enum": ["low", "medium", "high"]},
            "control": {"type": "object"},
            "steps": {"type": "array", "items": ACTION_STEP_SCHEMA},
            "final": {"type": "object"},
        },
        "required": ["is_action", "goal", "risk", "steps", "final"],
        "additionalProperties": False,
    }
    PENDING_CLARIFICATION_SCHEMA: dict[str, Any] = PENDING_CONTROL_SCHEMA

    def __init__(self, task_manager: Any | None = None) -> None:
        self._task_manager = task_manager

    async def plan(
        self,
        user_text: str,
        *,
        pending_state: Any | None = None,
        strict: bool = False,
    ) -> AIActionPlan | None:
        if self._task_manager is None:
            return None
        try:
            from client.services.ai_service import AIPrivacyScope, AIRequest, AITaskType
        except Exception:
            logger.debug("AI action planner request contracts are unavailable", exc_info=True)
            return None

        prompt_kind = self._prompt_kind(pending_state)
        schema = self._schema_for_prompt_kind(prompt_kind)
        request = AIRequest(
            task_id=f"ai-action-plan-{int(time.time() * 1000)}",
            session_id=str(getattr(pending_state, "ai_thread_id", "") or getattr(pending_state, "thread_id", "") or ""),
            task_type=AITaskType.CHAT,
            privacy_scope=AIPrivacyScope.GENERAL,
            must_be_local=True,
            stream=False,
            temperature=0.0,
            max_tokens=1024,
            response_format={"type": "json_object", "schema": schema} if strict else None,
            priority=4,
            system_prompt=self._system_prompt(prompt_kind),
            messages=[{"role": "user", "content": self._user_prompt(user_text, pending_state=pending_state, prompt_kind=prompt_kind)}],
            metadata={
                "source": "ai_action_planner",
                "strict_json": strict,
                "planner_schema_version": self.PLANNER_SCHEMA_VERSION,
                "planner_prompt_version": self.PLANNER_PROMPT_VERSION,
                "planner_prompt_kind": prompt_kind,
            },
        )
        try:
            snapshot = await self._task_manager.run_once(request)
        except Exception:
            logger.exception("AI action planner failed")
            return None
        return _parse_planner_json(str(getattr(snapshot, "content", "") or ""))

    async def repair_plan(
        self,
        user_text: str,
        *,
        invalid_plan: AIActionPlan,
        validation_errors: Sequence[str],
        pending_state: Any | None = None,
        strict: bool = True,
    ) -> AIActionPlan | None:
        if self._task_manager is None:
            return None
        try:
            from client.services.ai_service import AIPrivacyScope, AIRequest, AITaskType
        except Exception:
            logger.debug("AI action planner repair request contracts are unavailable", exc_info=True)
            return None

        prompt_kind = self._prompt_kind(pending_state)
        schema = self._schema_for_prompt_kind(prompt_kind)
        invalid_json = json.dumps(invalid_plan.to_dict(), ensure_ascii=False, sort_keys=True)
        errors_text = "\n".join(str(item or "").strip() for item in validation_errors if str(item or "").strip())
        repair_prompt = (
            self._user_prompt(user_text, pending_state=pending_state, prompt_kind=prompt_kind)
            + "\n\n上一次 plan 未通过结构校验。请只修正结构错误，保持用户目标不变，仍然只输出 JSON。\n"
            "校验错误：\n"
            f"{errors_text or 'PLAN_SCHEMA_INVALID'}\n"
            "无效 plan：\n"
            f"{invalid_json}"
        )
        request = AIRequest(
            task_id=f"ai-action-plan-repair-{int(time.time() * 1000)}",
            session_id=str(getattr(pending_state, "ai_thread_id", "") or getattr(pending_state, "thread_id", "") or ""),
            task_type=AITaskType.CHAT,
            privacy_scope=AIPrivacyScope.GENERAL,
            must_be_local=True,
            stream=False,
            temperature=0.0,
            max_tokens=1024,
            response_format={"type": "json_object", "schema": schema} if strict else None,
            priority=4,
            system_prompt=(
                self._system_prompt(prompt_kind)
                + "\n你现在处于 plan 修正模式：不要重新解释用户意图，只修正 step id、depends_on、$ 引用、action 名称和 args 字段。"
            ),
            messages=[{"role": "user", "content": repair_prompt}],
            metadata={
                "source": "ai_action_planner_repair",
                "strict_json": strict,
                "planner_schema_version": self.PLANNER_SCHEMA_VERSION,
                "planner_prompt_version": self.PLANNER_PROMPT_VERSION,
                "planner_prompt_kind": prompt_kind,
                "validation_error_count": len(tuple(validation_errors or ())),
            },
        )
        try:
            snapshot = await self._task_manager.run_once(request)
        except Exception:
            logger.exception("AI action planner repair failed")
            return None
        return _parse_planner_json(str(getattr(snapshot, "content", "") or ""))

    @staticmethod
    def _prompt_kind(pending_state: Any | None) -> str:
        if pending_state is None:
            return AIActionPlanner.PROMPT_NEW_ACTION
        state = str(getattr(pending_state, "state", "") or "").strip()
        waiting = dict(getattr(pending_state, "waiting_payload", {}) or {})
        waiting_type = str(waiting.get("type") or "").strip()
        if state in {"waiting_confirmation", "need_confirmation"}:
            return AIActionPlanner.PROMPT_PENDING_CONFIRMATION
        if state in {"waiting_clarification", "need_clarification"} and waiting_type in {"contact_ambiguity", "target_too_many"}:
            return AIActionPlanner.PROMPT_PENDING_CONTACT_SELECTION
        if state in {"waiting_clarification", "need_clarification"}:
            return AIActionPlanner.PROMPT_PENDING_CLARIFICATION
        return AIActionPlanner.PROMPT_PENDING_CLARIFICATION

    @staticmethod
    def _schema_for_prompt_kind(prompt_kind: str) -> dict[str, Any]:
        if prompt_kind in {
            AIActionPlanner.PROMPT_PENDING_CONFIRMATION,
            AIActionPlanner.PROMPT_PENDING_CONTACT_SELECTION,
        }:
            return AIActionPlanner.PENDING_CONTROL_SCHEMA
        if prompt_kind == AIActionPlanner.PROMPT_PENDING_CLARIFICATION:
            return AIActionPlanner.PENDING_CLARIFICATION_SCHEMA
        return AIActionPlanner.NEW_ACTION_SCHEMA

    @staticmethod
    def _system_prompt(prompt_kind: str = PROMPT_NEW_ACTION) -> str:
        common = (
            "你是 AssistIM 的动作规划器，只输出 JSON，不要解释，不要使用代码块。\n"
            "不要在本地自然语言短语上做假设；语义理解由你完成，系统只执行结构化 plan。\n"
        )
        if prompt_kind == AIActionPlanner.PROMPT_PENDING_CONFIRMATION:
            return (
                common
                + "当前只处理一个 pending 确认。由你结合 pending preview 判断用户是在确认、取消、修改还是无关输入；本地不会用词表判断。"
            )
        if prompt_kind == AIActionPlanner.PROMPT_PENDING_CONTACT_SELECTION:
            return (
                common
                + "当前只处理联系人候选选择。由你结合 waiting_payload.candidates 判断用户选择了哪个候选；本地不会用词表判断。"
            )
        if prompt_kind == AIActionPlanner.PROMPT_PENDING_CLARIFICATION:
            return (
                common
                + "当前只处理 pending 补充信息。由你结合 waiting_payload 判断用户是否补齐所需结构。"
            )
        return (
            common
            + "你的职责是判断用户是否需要 AssistIM 应用数据或本地应用能力，若是则拆成原子 steps。\n"
            "已注册 action：contact.resolve, memory.search, memory.summarize, message.draft, user.confirm, message.send。\n"
            "读取类任务不需要确认；产生外部副作用的任务必须包含 user.confirm，message.send 当前仍需要确认。\n"
            "只有用户明确要求发送、添加、发布、删除或修改时，才允许输出 user.confirm 或 message.send。\n"
            "聊天记录查询使用 contact.resolve -> memory.search -> memory.summarize。\n"
            "询问历史、回顾、总结、检索内容时使用 memory.search 和 memory.summarize；不要为读取类任务生成 user.confirm。\n"
            "多个对象默认表示多对象操作，不是歧义；只有单个名称对应多个本地实体时才由系统澄清。\n"
            "如果用户只是普通问答、写作、翻译或代码分析，输出 is_action=false 且 steps=[]。\n"
            "只有需要执行、确认、取消或补充高风险应用操作时，才输出 action plan。\n"
            "原子 action 参数契约必须严格遵守，字段名错误会导致计划不可执行：\n"
            "聊天历史查询必须使用固定 step id：resolve_contacts, search_memory, summarize_memory；"
            "发送消息必须使用固定 step id：resolve_target, draft_message, confirm_send, send_message。\n"
            "所有 $ 引用的根名称必须等于已存在 step.id；不要生成 %step_0 这类临时 id。\n"
            'participant_match 只能是 "any", "all", "direct_only", "group_only"；默认使用 "any"。\n'
            'contact.resolve.args = {"queries": ["张三"], "allow_multiple": false}；queries 必须是数组；'
            "不要使用 contact.resolve.args.target。\n"
            'memory.search.args = {"participants": "$resolve_contacts.contacts", "participant_match": "any", '
            '"time_scope": {"type": "all_history"}, "keywords": [], "question": "用户原始问题"}；'
            "question 必须是用户原始问题，不要使用 memory.search.args.query。\n"
            '历史/之前/聊过什么/回顾 -> time_scope.type="all_history"。\n'
            'memory.summarize.args = {"source": "$search_memory", "question": "用户原始问题"}；'
            "source 必须引用 memory.search step。\n"
            'message.draft.args = {"target": "$resolve_target.contacts[0]", "content": "明确消息内容"}。\n'
            'user.confirm.args = {"risk": "high", "preview": {"operation": "发送消息", '
            '"target": "$draft_message.target", "content": "$draft_message.content"}}。\n'
            'message.send.args = {"target": "$draft_message.target_entity", '
            '"content": "$draft_message.content", "preview": "$draft_message.preview", '
            '"idempotency_key": "$draft_message.idempotency_key"}。\n'
            '示例：普通聊天 -> {"is_action": false, "goal": "普通聊天", "risk": "low", "steps": [], "final": {}}。\n'
            "示例：聊天历史查询 -> resolve_contacts: contact.resolve(queries) -> "
            'search_memory: memory.search(participants="$resolve_contacts.contacts", '
            'participant_match="any", time_scope.type="all_history", question="用户原始问题") -> '
            'summarize_memory: memory.summarize(source="$search_memory")。\n'
            "示例：发送消息 -> resolve_target: contact.resolve(queries, allow_multiple=false) -> "
            'draft_message: message.draft(target="$resolve_target.contacts[0]") -> '
            'confirm_send: user.confirm(preview.target="$draft_message.target") -> '
            'send_message: message.send(target="$draft_message.target_entity")。'
        )

    @staticmethod
    def _user_prompt(user_text: str, *, pending_state: Any | None = None, prompt_kind: str | None = None) -> str:
        prompt_kind = prompt_kind or AIActionPlanner._prompt_kind(pending_state)
        now = datetime.now()
        fields = "is_action, goal, risk, control, steps, final" if pending_state is not None else "is_action, goal, risk, steps, final"
        header = f"请输出 JSON：{fields}。\n当前本地时间：{now.strftime('%Y-%m-%d %H:%M:%S')}。\n"
        pending = _pending_prompt_block(pending_state)
        if prompt_kind == AIActionPlanner.PROMPT_PENDING_CONFIRMATION:
            return (
                header
                + "当前任务：判断用户对 pending 确认的回复。\n"
                '用户确认当前 preview：输出 "control": {"type": "confirm"}，steps=[]，final={}。\n'
                '用户取消当前 pending：输出 "control": {"type": "cancel"}，steps=[]，final={}。\n'
                "用户修改目标、内容或条件：不要确认原 plan，可输出新的结构化动作；无法判断则 is_action=false 且 steps=[]。\n"
                f"用户输入：{str(user_text or '').strip()}"
                f"{pending}"
            )
        if prompt_kind == AIActionPlanner.PROMPT_PENDING_CONTACT_SELECTION:
            return (
                header
                + "当前任务：从 pending 候选联系人中判断用户选择了哪一个。\n"
                '能确定候选：输出 "control": {"type": "select_contact_alias", "selection_index": 1}，也可使用 contact_id 或 alias_text，steps=[]，final={}。\n'
                '用户取消 pending：输出 "control": {"type": "cancel"}，steps=[]，final={}。\n'
                "无法确定候选或输入无关：输出 is_action=false 且 steps=[]。\n"
                f"用户输入：{str(user_text or '').strip()}"
                f"{pending}"
            )
        if prompt_kind == AIActionPlanner.PROMPT_PENDING_CLARIFICATION:
            return (
                header
                + "当前任务：判断用户是否补齐 pending 缺失信息。\n"
                '如果补齐信息后能继续，输出修正后的结构化 plan；如果用户取消，输出 "control": {"type": "cancel"} 且 steps=[]。\n'
                "如果仍无法补齐或输入无关，输出 is_action=false 且 steps=[]。\n"
                "需要生成发送 plan 时使用 contact.resolve -> message.draft -> user.confirm -> message.send。\n"
                f"用户输入：{str(user_text or '').strip()}"
                f"{pending}"
            )
        return (
            header
            + "step 字段：id, action, depends_on, args, display_text, explanation。\n"
            "引用上游输出使用 $step_id.field 或 $step_id.field[0]。\n"
            "发送消息的组合是 contact.resolve -> message.draft -> user.confirm -> message.send。\n"
            "聊天记录查询的组合是 contact.resolve -> memory.search -> memory.summarize。\n"
            "发送组合必须同时有明确目标和明确消息内容。\n"
            "只有明确要求发送/发布/添加/删除/修改时才使用发送组合；询问历史、回顾、总结、检索内容时使用 memory.search 和 memory.summarize。\n"
            f"用户输入：{str(user_text or '').strip()}"
        )


def _pending_prompt_block(pending_state: Any | None) -> str:
    if pending_state is None:
        return ""
    return "\n\n当前 pending plan：" + json.dumps(
                {
                    "state": getattr(pending_state, "state", ""),
                    "waiting_payload": getattr(pending_state, "waiting_payload", {}),
                },
                ensure_ascii=False,
            )


class AIActionWorkflow:
    """Plan, validate, execute, pause, and resume assistant actions."""

    def __init__(
        self,
        *,
        action_store: AIActionStore | AIActionPlanStore | None = None,
        planner: AIActionPlanner | None = None,
        task_manager: Any | None = None,
        contact_alias_resolver: ContactAliasResolver | None = None,
        memory_manager: Any | None = None,
        message_sender: Any | None = None,
        permission_scope_provider: Callable[[], AIPermissionScope | None] | None = None,
    ) -> None:
        self._store = action_store or get_ai_action_store()
        self._planner = planner or AIActionPlanner(task_manager=task_manager or get_ai_task_manager())
        self._contact_alias_resolver = contact_alias_resolver or ContactAliasResolver()
        self._message_sender = message_sender
        self._permission_scope_provider = permission_scope_provider
        self._normalizer = AIPlanNormalizer()
        self._optimizer = AIPlanOptimizer()
        self._resource_manager = AIResourceManager()
        self._registry = AtomicActionRegistry(
            contact_resolver=self._contact_alias_resolver,
            memory_manager=memory_manager,
            message_sender=self._message_sender,
        )
        self._validator = AIPlanValidator(registry=self._registry)
        self._executor = AIActionExecutor(registry=self._registry, store=self._store)

    async def handle_user_turn(
        self,
        *,
        thread_id: str,
        text: str,
        has_attachments: bool = False,
    ) -> AIActionTurnResult:
        total_started = time.perf_counter()
        planner_ms = 0
        normalizer_ms = 0
        optimizer_ms = 0
        resource_check_ms = 0
        executor_ms = 0

        def log_perf(result_state: str, *, handled: bool, plan: AIActionPlan | None = None) -> None:
            logger.info(
                "[ai-perf] ai_action_workflow_finished thread_id=%s handled=%s state=%s pending=%s "
                "planner_ms=%s normalizer_ms=%s optimizer_ms=%s resource_check_ms=%s executor_ms=%s "
                "total_ms=%s step_count=%s action=%s",
                thread_id,
                handled,
                result_state,
                pending is not None,
                planner_ms,
                normalizer_ms,
                optimizer_ms,
                resource_check_ms,
                executor_ms,
                _elapsed_ms(total_started),
                len(plan.steps) if plan is not None else 0,
                _plan_action_label(plan) if plan is not None else "",
            )

        normalized_text = _normalize_text(text)
        if not normalized_text:
            logger.info(
                "[ai-diag] ai_action_workflow_skipped thread_id=%s reason=empty_text has_attachments=%s text_chars=%s",
                thread_id,
                has_attachments,
                len(str(text or "")),
            )
            return AIActionTurnResult(handled=False)
        if has_attachments:
            logger.info(
                "[ai-diag] ai_action_workflow_skipped thread_id=%s reason=attachments has_attachments=%s text_chars=%s",
                thread_id,
                has_attachments,
                len(normalized_text),
            )
            return AIActionTurnResult(handled=False)

        pending = await self._store.latest_pending_plan(thread_id)
        pending_state = self._pending_for_planner(pending)
        logger.info(
            "[ai-diag] ai_action_workflow_planner_start thread_id=%s pending=%s text_chars=%s",
            thread_id,
            bool(pending),
            len(normalized_text),
        )
        planner_started = time.perf_counter()
        raw_plan = await self._build_plan(normalized_text, pending_state=pending_state)
        planner_ms = _elapsed_ms(planner_started)
        logger.info(
            "[ai-diag] ai_action_workflow_planner_result thread_id=%s is_action=%s steps=%s control=%s",
            thread_id,
            raw_plan.is_action,
            len(raw_plan.steps),
            str((raw_plan.control or {}).get("type") or ""),
        )
        logger.info(
            "[ai-diag] ai_action_workflow_raw_plan thread_id=%s plan=%s",
            thread_id,
            json.dumps(raw_plan.to_dict(), ensure_ascii=False, sort_keys=True, default=str),
        )
        if pending is not None:
            control = await self._handle_planner_control(pending, raw_plan)
            if control is not None:
                log_perf(str(control.message_extra.get("ai_action", {}).get("state") or "pending_control"), handled=True, plan=raw_plan)
                return control

        if not raw_plan.is_action:
            log_perf("not_action", handled=False, plan=raw_plan)
            return AIActionTurnResult(handled=False)

        normalizer_started = time.perf_counter()
        normalized_plan = self._normalizer.normalize(raw_plan, user_text=normalized_text)
        normalizer_ms = _elapsed_ms(normalizer_started)
        if not normalized_plan.is_action:
            logger.info(
                "[ai-diag] ai_action_workflow_normalizer_rejected thread_id=%s reason=%s raw_plan=%s",
                thread_id,
                self._normalizer.last_rejection_reason,
                json.dumps(raw_plan.to_dict(), ensure_ascii=False, sort_keys=True, default=str),
            )
            log_perf("normalized_not_action", handled=False, plan=normalized_plan)
            return AIActionTurnResult(handled=False)
        if not normalized_plan.steps:
            log_perf("done", handled=True, plan=normalized_plan)
            return AIActionTurnResult(handled=False)

        validation = self._validator.validate(normalized_plan)
        if not validation.allowed:
            repaired_raw_plan = await self._repair_invalid_plan(
                normalized_text,
                pending_state=pending_state,
                invalid_plan=normalized_plan,
                validation=validation,
            )
            if repaired_raw_plan is None:
                log_perf("plan_invalid", handled=True, plan=normalized_plan)
                return self._invalid_plan_turn(validation)
            normalizer_started = time.perf_counter()
            normalized_plan = self._normalizer.normalize(repaired_raw_plan, user_text=normalized_text)
            normalizer_ms += _elapsed_ms(normalizer_started)
            if not normalized_plan.is_action:
                log_perf("repair_not_action", handled=False, plan=normalized_plan)
                return AIActionTurnResult(handled=False)
            if not normalized_plan.steps:
                log_perf("done", handled=True, plan=normalized_plan)
                return AIActionTurnResult(handled=False)
            validation = self._validator.validate(normalized_plan)
            if not validation.allowed:
                log_perf("plan_invalid_after_repair", handled=True, plan=normalized_plan)
                return self._invalid_plan_turn(validation)

        optimizer_started = time.perf_counter()
        optimized_plan, optimize_reason = self._optimizer.optimize(normalized_plan)
        optimizer_ms = _elapsed_ms(optimizer_started)
        optimized_validation = self._validator.validate(optimized_plan)
        if not optimized_validation.allowed:
            log_perf("optimized_plan_invalid", handled=True, plan=optimized_plan)
            return self._invalid_plan_turn(optimized_validation)
        resource_started = time.perf_counter()
        resource = self._resource_manager.check_plan(optimized_plan)
        resource_check_ms = _elapsed_ms(resource_started)
        if not resource.allowed:
            log_perf("waiting_clarification", handled=True, plan=optimized_plan)
            return await self._create_resource_clarification(
                thread_id,
                optimized_plan,
                resource.response_text,
                resource_reason=resource.reason,
            )

        plan_json = optimized_plan.to_dict()
        record = await self._store.create_plan(
            thread_id=thread_id,
            goal=optimized_plan.goal,
            plan_json=plan_json,
            state="running",
            reason="initial_normalized",
        )
        if optimize_reason:
            record = await self._store.update_plan(
                record.id,
                plan_json=plan_json,
                reason=optimize_reason,
            ) or record
        executor_started = time.perf_counter()
        turn = await self._execute_to_turn(record)
        executor_ms = _elapsed_ms(executor_started)
        log_perf(str(turn.message_extra.get("ai_action", {}).get("state") or "done"), handled=turn.handled, plan=optimized_plan)
        return turn

    async def handle_pending_control(
        self,
        *,
        thread_id: str,
        control_type: str,
    ) -> AIActionTurnResult:
        normalized_thread_id = str(thread_id or "").strip()
        normalized_control = str(control_type or "").strip().lower()
        if not normalized_thread_id or normalized_control not in {"confirm", "cancel"}:
            logger.info(
                "[ai-diag] ai_action_pending_control_skipped thread_id=%s control=%s reason=invalid_input",
                normalized_thread_id,
                normalized_control,
            )
            return AIActionTurnResult(handled=False)
        pending = await self._store.latest_pending_plan(normalized_thread_id)
        if pending is None:
            logger.info(
                "[ai-diag] ai_action_pending_control_skipped thread_id=%s control=%s reason=no_pending",
                normalized_thread_id,
                normalized_control,
            )
            return AIActionTurnResult(handled=False)
        logger.info(
            "[ai-diag] ai_action_pending_control thread_id=%s plan_id=%s state=%s control=%s",
            normalized_thread_id,
            pending.id,
            pending.state,
            normalized_control,
        )
        if normalized_control == "cancel":
            return await self._cancel_pending(pending)
        if pending.state == "waiting_confirmation":
            return await self._confirm_pending(pending)
        return AIActionTurnResult(
            handled=True,
            response_text=str(pending.waiting_payload.get("response_text") or "这个操作还在等待补充信息。"),
            message_extra={"ai_action": self._extra(pending)},
        )

    async def finish_streamed_action(self, extra: dict[str, Any] | None, *, content: str, status: str) -> None:
        data = dict((extra or {}).get("ai_action") or {})
        plan_id = str(data.get("plan_id") or data.get("id") or "").strip()
        if not plan_id:
            return
        normalized_status = str(status or "").strip().lower()
        result_status = "done" if normalized_status == "done" else normalized_status or "failed"
        state = "done" if result_status == "done" else "failed"
        record = await self._store.get_plan(plan_id)
        if record is None:
            return
        outputs = dict(record.step_outputs or {})
        final = dict(outputs.get("final") or {})
        final["text"] = _clip(_normalize_text(content), 1000)
        outputs["final"] = final
        await self._store.update_plan(
            plan_id,
            state=state,
            step_outputs=outputs,
            error_text="" if state == "done" else result_status,
            completed_at=time.time(),
        )

    async def _build_plan(self, user_text: str, *, pending_state: Any | None) -> AIActionPlan:
        strict_plan = await self._planner.plan(user_text, pending_state=pending_state, strict=True)
        if strict_plan is not None:
            return strict_plan
        plan = await self._planner.plan(user_text, pending_state=pending_state, strict=False)
        return plan or AIActionPlan(is_action=False)

    async def _repair_invalid_plan(
        self,
        user_text: str,
        *,
        pending_state: Any | None,
        invalid_plan: AIActionPlan,
        validation: AIPlanValidationResult,
    ) -> AIActionPlan | None:
        repair = getattr(self._planner, "repair_plan", None)
        if not callable(repair):
            logger.info(
                "[ai-diag] ai_action_plan_validation_repair_unavailable errors=%s",
                len(validation.errors),
            )
            return None
        logger.info(
            "[ai-diag] ai_action_plan_validation_repair_start errors=%s first_error=%s",
            len(validation.errors),
            validation.errors[0].code if validation.errors else "",
        )
        try:
            repaired = await repair(
                user_text,
                invalid_plan=invalid_plan,
                validation_errors=validation.repair_messages(),
                pending_state=pending_state,
                strict=True,
            )
        except Exception:
            logger.exception("AI action planner repair call failed")
            return None
        if repaired is None:
            logger.info("[ai-diag] ai_action_plan_validation_repair_empty errors=%s", len(validation.errors))
        return repaired

    @staticmethod
    def _invalid_plan_turn(validation: AIPlanValidationResult) -> AIActionTurnResult:
        first = validation.errors[0] if validation.errors else None
        return AIActionTurnResult(
            handled=True,
            response_text="这个操作计划结构有问题，请重新描述一下。",
            message_extra={
                "ai_action": {
                    "state": "failed",
                    "error_code": first.code if first is not None else "PLAN_SCHEMA_INVALID",
                    "validation_errors": validation.repair_messages()[:5],
                }
            },
        )

    def _pending_for_planner(self, pending: AIActionPlanRecord | None) -> PendingPlannerState | None:
        if pending is None:
            return None
        waiting = dict(pending.waiting_payload or {})
        return PendingPlannerState(
            id=pending.id,
            thread_id=pending.thread_id,
            ai_thread_id=pending.thread_id,
            state=pending.state,
            waiting_payload=waiting,
        )

    async def _handle_planner_control(self, pending: AIActionPlanRecord, plan: AIActionPlan) -> AIActionTurnResult | None:
        control = dict(plan.control or {})
        control_type = str(control.get("type") or "").strip()
        if control_type == "cancel":
            return await self._cancel_pending(pending)
        if control_type == "confirm" and pending.state == "waiting_confirmation":
            return await self._confirm_pending(pending)
        if control_type == "select_contact_alias" and pending.state == "waiting_clarification":
            selection = str(control.get("selection_index") or control.get("contact_id") or control.get("alias_text") or "")
            if selection:
                return await self._select_pending_contact(pending, selection)
        return None

    async def _cancel_pending(self, pending: AIActionPlanRecord) -> AIActionTurnResult:
        await self._store.update_plan(pending.id, state="cancelled", completed_at=time.time())
        return AIActionTurnResult(
            handled=True,
            response_text="已取消这个操作。",
            message_extra={"ai_action": self._extra(pending, state="cancelled")},
        )

    async def _confirm_pending(self, pending: AIActionPlanRecord) -> AIActionTurnResult:
        waiting = dict(pending.waiting_payload or {})
        if self._pending_confirmation_is_stale(pending, waiting):
            return AIActionTurnResult(
                handled=True,
                response_text="操作内容已变化，请重新发起这个操作。",
                message_extra={"ai_action": self._extra(pending)},
            )
        outputs = dict(pending.step_outputs or {})
        outputs[pending.current_step_id] = {
            "confirmed": True,
            "risk": waiting.get("risk"),
            "preview": waiting.get("preview"),
            "confirmed_at": time.time(),
        }
        mark_step_output_current(outputs, step_id=pending.current_step_id, plan_version=pending.plan_version)
        updated = await self._store.update_plan(
            pending.id,
            state="running",
            step_outputs=outputs,
            waiting_payload={},
        )
        return await self._execute_to_turn(updated or pending)

    @staticmethod
    def _pending_confirmation_is_stale(pending: AIActionPlanRecord, waiting: dict[str, Any]) -> bool:
        if str(waiting.get("type") or "").strip() != "confirmation":
            return True
        waiting_step_id = str(waiting.get("step_id") or "").strip()
        if not waiting_step_id or waiting_step_id != str(pending.current_step_id or "").strip():
            return True
        try:
            waiting_plan_version = int(waiting.get("plan_version") or 0)
        except (TypeError, ValueError):
            waiting_plan_version = 0
        if waiting_plan_version <= 0 or waiting_plan_version != int(pending.plan_version or 0):
            return True
        risk = str(waiting.get("risk") or "high").strip() or "high"
        waiting_preview = waiting.get("preview") if isinstance(waiting.get("preview"), dict) else {}
        waiting_fingerprint = str(waiting.get("preview_fingerprint") or "").strip()
        if not waiting_fingerprint:
            return True
        if waiting_fingerprint != confirmation_preview_fingerprint(waiting_preview, risk=risk):
            return True
        current_preview = _current_confirmation_preview(pending)
        if current_preview is None:
            return True
        return waiting_fingerprint != confirmation_preview_fingerprint(current_preview, risk=risk)

    async def _select_pending_contact(self, pending: AIActionPlanRecord, selection: str) -> AIActionTurnResult:
        waiting = dict(pending.waiting_payload or {})
        if str(waiting.get("type") or "") not in {"contact_ambiguity", "target_too_many"}:
            return AIActionTurnResult(
                handled=True,
                response_text=str(waiting.get("response_text") or "这个操作还在等待补充信息。"),
                message_extra={"ai_action": self._extra(pending)},
            )
        selected = _select_contact_from_waiting(selection, waiting)
        if selected is None:
            return AIActionTurnResult(
                handled=True,
                response_text=str(waiting.get("response_text") or "请回复要选择的候选。"),
                message_extra={"ai_action": self._extra(pending)},
            )
        outputs = dict(pending.step_outputs or {})
        contacts = [item for item in list(waiting.get("partial_contacts") or []) if isinstance(item, dict)]
        contacts.append(selected)
        outputs[pending.current_step_id] = {
            "contacts": contacts,
            "groups": [],
            "ambiguous": [],
            "unresolved": list(waiting.get("unresolved") or []),
        }
        mark_step_output_current(outputs, step_id=pending.current_step_id, plan_version=pending.plan_version)
        updated = await self._store.update_plan(
            pending.id,
            state="running",
            step_outputs=outputs,
            waiting_payload={},
        )
        return await self._execute_to_turn(updated or pending)

    async def _execute_to_turn(self, record: AIActionPlanRecord) -> AIActionTurnResult:
        result = await self._executor_for_current_scope().execute(record)
        latest = await self._store.get_plan(record.id) or record
        return self._result_to_turn(latest, result)

    def _executor_for_current_scope(self) -> AIActionExecutor:
        if self._permission_scope_provider is None:
            return self._executor
        scope = self._permission_scope_provider() or AIPermissionScope()
        return AIActionExecutor(
            registry=self._registry,
            store=self._store,
            permission_policy=AIPermissionPolicy(scope=scope),
        )

    def _result_to_turn(self, record: AIActionPlanRecord, result: ActionExecutionResult) -> AIActionTurnResult:
        if result.state == "failed":
            return AIActionTurnResult(
                handled=True,
                response_text=result.response_text or "这个操作执行失败，请稍后再试。",
                message_extra={"ai_action": self._extra(record, state="failed")},
            )
        return AIActionTurnResult(
            handled=True,
            response_text=result.response_text,
            memory_context_lines=result.memory_context_lines,
            message_extra={"ai_action": self._extra(record, state=record.state)},
        )

    async def _create_resource_clarification(
        self,
        thread_id: str,
        plan: AIActionPlan,
        response_text: str,
        *,
        resource_reason: str,
    ) -> AIActionTurnResult:
        plan_json = plan.to_dict()
        record = await self._store.create_plan(
            thread_id=thread_id,
            goal=plan.goal,
            plan_json=plan_json,
            state="waiting_clarification",
            reason="resource_limit",
        )
        await self._store.update_plan(
            record.id,
            waiting_payload={
                "type": "clarification",
                "reason": "resource_limit",
                "resource_reason": str(resource_reason or "").strip(),
                "response_text": response_text,
            },
        )
        latest = await self._store.get_plan(record.id) or record
        return AIActionTurnResult(handled=True, response_text=response_text, message_extra={"ai_action": self._extra(latest)})

    @staticmethod
    def _extra(record: AIActionPlanRecord, *, state: str | None = None) -> dict[str, Any]:
        plan_json = dict(record.plan_json or {})
        events = _safe_action_events(plan_json)
        step_states = _project_action_step_states(plan_json, events, record)
        steps = [
            {
                "id": str(step.get("id") or ""),
                "action": str(step.get("action") or ""),
                "state": step_states.get(str(step.get("id") or ""), "pending"),
                "display_text": str(step.get("display_text") or ""),
                "explanation": str(step.get("explanation") or ""),
            }
            for step in list(plan_json.get("steps") or [])
            if isinstance(step, dict)
        ]
        return {
            "id": record.id,
            "plan_id": record.id,
            "action": _plan_json_action_label(plan_json),
            "state": state or record.state,
            "kind": "write" if _plan_has_action(plan_json, "message.send") else "read",
            "risk_level": str(plan_json.get("risk") or "low"),
            "plan_version": record.plan_version,
            "current_step_id": record.current_step_id,
            "steps": steps,
            "events": events,
            "waiting": dict(record.waiting_payload or {}),
        }


def _current_confirmation_preview(pending: AIActionPlanRecord) -> dict[str, Any] | None:
    step = _current_plan_step(pending)
    if step is None:
        return None
    args = step.get("args") if isinstance(step.get("args"), dict) else {}
    if "preview" not in args:
        return None
    try:
        preview = _resolve_action_arg_refs(args.get("preview"), dict(pending.step_outputs or {}))
    except ValueError:
        return None
    return dict(preview) if isinstance(preview, dict) else None


def _current_plan_step(pending: AIActionPlanRecord) -> dict[str, Any] | None:
    current_step_id = str(pending.current_step_id or "").strip()
    if not current_step_id:
        return None
    for step in list(dict(pending.plan_json or {}).get("steps") or []):
        if isinstance(step, dict) and str(step.get("id") or "").strip() == current_step_id:
            return dict(step)
    return None


def _resolve_action_arg_refs(value: Any, outputs: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return _resolve_action_ref(value, outputs)
    if isinstance(value, list):
        return [_resolve_action_arg_refs(item, outputs) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_action_arg_refs(item, outputs) for key, item in value.items()}
    return value


def _resolve_action_ref(ref: str, outputs: dict[str, Any]) -> Any:
    text = str(ref or "").strip()
    if not text.startswith("$"):
        return text
    parts = text[1:].split(".")
    if not parts or not parts[0] or parts[0] not in outputs:
        raise ValueError("ARG_REFERENCE_INVALID")
    current: Any = outputs[parts[0]]
    for raw_part in parts[1:]:
        name, indexes = _parse_action_ref_path_part(raw_part)
        if name:
            if not isinstance(current, dict) or name not in current:
                raise ValueError("ARG_REFERENCE_INVALID")
            current = current[name]
        for index in indexes:
            if not isinstance(current, list) or index < 0 or index >= len(current):
                raise ValueError("ARG_REFERENCE_INVALID")
            current = current[index]
    return current


def _parse_action_ref_path_part(part: str) -> tuple[str, list[int]]:
    text = str(part or "").strip()
    match = re.match(r"^(?P<name>[^\[]*)(?P<indexes>(?:\[\d+\])*)$", text)
    if not match:
        raise ValueError("ARG_REFERENCE_INVALID")
    name = match.group("name")
    indexes = [int(item) for item in re.findall(r"\[(\d+)\]", match.group("indexes") or "")]
    return name, indexes


def _safe_action_events(plan_json: dict[str, Any]) -> list[dict[str, Any]]:
    events = plan_json.get("events")
    return [dict(item) for item in list(events or []) if isinstance(item, dict)]


def _project_action_step_states(
    plan_json: dict[str, Any],
    events: list[dict[str, Any]],
    record: AIActionPlanRecord,
) -> dict[str, str]:
    states: dict[str, str] = {}
    for step in list(plan_json.get("steps") or []):
        if isinstance(step, dict):
            step_id = str(step.get("id") or "")
            if step_id:
                states[step_id] = "pending"

    for step_id in set(record.step_outputs or {}):
        if step_id in states:
            states[step_id] = "done"

    for event in events:
        step_id = str(event.get("step_id") or "")
        if step_id not in states:
            continue
        event_type = str(event.get("type") or "")
        event_state = str(event.get("state") or "")
        if event_type == "step_completed" or event_state == "completed":
            states[step_id] = "done"
        elif event_type == "step_failed" or event_state == "failed":
            states[step_id] = "failed"
        elif event_type.startswith("step_waiting") or event_state.startswith("waiting_"):
            states[step_id] = event_state or "waiting"
        elif event_type == "step_started" or event_state == "started":
            states[step_id] = "running"

    current_step_id = str(record.current_step_id or "")
    if record.state == "running" and current_step_id in states and states[current_step_id] == "pending":
        states[current_step_id] = "running"
    return states


def _parse_planner_json(raw: str) -> AIActionPlan | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        text = match.group(0)
    try:
        data = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("steps"), list):
        return AIActionPlan.from_dict(data)
    return None


def _plan_action_label(plan: AIActionPlan) -> str:
    actions = [step.action for step in plan.steps]
    if "message.send" in actions:
        return "send_message"
    if "memory.search" in actions:
        return "memory.search"
    if actions:
        return actions[-1].replace(".", "_")
    return ""


def _plan_json_action_label(plan_json: dict[str, Any]) -> str:
    return _plan_action_label(AIActionPlan.from_dict(plan_json))


def _plan_has_action(plan_json: dict[str, Any], action: str) -> bool:
    return any(isinstance(step, dict) and str(step.get("action") or "") == action for step in list(plan_json.get("steps") or []))


def _select_contact_from_waiting(text: str, waiting: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [candidate for candidate in list(waiting.get("candidates") or []) if isinstance(candidate, dict)]
    if not candidates:
        return None
    normalized = _normalize_text(text)
    selected_index: int | None = None
    if normalized.isdigit():
        selected_index = int(normalized) - 1
    elif isinstance(waiting.get("selection_index"), int):
        selected_index = int(waiting["selection_index"]) - 1
    if selected_index is not None and 0 <= selected_index < len(candidates):
        return candidates[selected_index]
    normalized_key = _alias_key(normalized)
    for candidate in candidates:
        aliases = list(candidate.get("aliases") or [])
        values = [
            candidate.get("contact_id"),
            candidate.get("display_name"),
            candidate.get("username"),
            candidate.get("nickname"),
            candidate.get("remark"),
            candidate.get("assistim_id"),
            *aliases,
        ]
        if normalized_key in {_alias_key(value) for value in values}:
            return candidate
    return None

def _clean_list(value: object) -> list[str]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    cleaned: list[str] = []
    for item in list(raw_items):
        text = _normalize_text(str(item or "")).strip(" ，,。？！?;；:：")
        if not text:
            continue
        if text not in cleaned:
            cleaned.append(text)
    return cleaned[:8]


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _alias_key(value: object) -> str:
    return _normalize_text(str(value or "")).casefold()


def _candidate_terms(candidate: ContactAliasCandidate | dict[str, Any]) -> list[str]:
    if isinstance(candidate, ContactAliasCandidate):
        raw_terms = [
            candidate.remark,
            candidate.display_name,
            candidate.nickname,
            candidate.username,
            candidate.assistim_id,
            candidate.contact_id,
        ]
    else:
        raw_terms = [
            candidate.get("remark"),
            candidate.get("display_name"),
            candidate.get("nickname"),
            candidate.get("username"),
            candidate.get("assistim_id"),
            candidate.get("contact_id") or candidate.get("id"),
        ]
    terms: list[str] = []
    for raw_term in raw_terms:
        term = _normalize_text(str(raw_term or "")).strip(" ，,。")
        if term and term not in terms:
            terms.append(term)
    return terms


def _contact_candidate_from_payload(contact: object) -> ContactAliasCandidate | None:
    if not isinstance(contact, dict):
        return None
    candidate = ContactAliasCandidate(
        contact_id=str(contact.get("id") or contact.get("contact_id") or "").strip(),
        display_name=str(contact.get("display_name") or contact.get("name") or "").strip(),
        username=str(contact.get("username") or "").strip(),
        nickname=str(contact.get("nickname") or "").strip(),
        remark=str(contact.get("remark") or "").strip(),
        assistim_id=str(contact.get("assistim_id") or "").strip(),
    )
    return candidate if candidate.contact_id else None


def _clip(value: str, max_chars: int) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))
