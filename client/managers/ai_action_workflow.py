"""AI assistant action workflow based on atomic executable plans."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from client.core import logging
from client.managers.ai_action_executor import AIActionExecutor
from client.managers.ai_action_normalizer import AIPlanNormalizer
from client.managers.ai_action_optimizer import AIPlanOptimizer
from client.managers.ai_action_registry import AtomicActionRegistry
from client.managers.ai_action_resource_manager import AIResourceManager
from client.managers.ai_action_types import AIActionPlan, AIActionStep, AIActionTurnResult, ActionExecutionResult
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
    action: str
    state: str
    slots: dict[str, Any]
    missing_slots: tuple[str, ...]
    waiting_payload: dict[str, Any]


class ContactAliasResolver:
    """Resolve user-facing contact aliases to stable local identity terms."""

    SEARCH_LIMIT = 20

    def __init__(self, db: Database | None = None) -> None:
        self._db = db or get_database()

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
            "action": {"type": "string"},
            "slots": {"type": "object"},
            "missing_slots": {"type": "array", "items": {"type": "string"}},
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
            "action": {"type": "string"},
            "slots": {"type": "object"},
            "missing_slots": {"type": "array", "items": {"type": "string"}},
            "steps": {"type": "array", "items": ACTION_STEP_SCHEMA},
            "final": {"type": "object"},
        },
        "required": ["is_action", "goal", "risk", "action", "slots", "steps", "final"],
        "additionalProperties": False,
    }
    PENDING_CLARIFICATION_SCHEMA: dict[str, Any] = NEW_ACTION_SCHEMA

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
                "planner_schema": "atomic_steps_v1",
                "planner_prompt_kind": prompt_kind,
            },
        )
        try:
            snapshot = await self._task_manager.run_once(request)
        except Exception:
            logger.exception("AI action planner failed")
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
                + "当前只处理 pending 补充信息。由你结合 missing_slots 和 waiting_payload 判断用户是否补齐所需结构。"
            )
        return (
            common
            + "你的职责是判断用户是否需要 AssistIM 应用数据或本地应用能力，若是则拆成原子 steps。\n"
            "已注册 action：contact.resolve, message.draft, user.confirm, message.send。\n"
            "读取类任务不需要确认；产生外部副作用的任务必须包含 user.confirm，message.send 当前仍需要确认。\n"
            "只有用户明确要求发送、添加、发布、删除或修改时，才允许输出 user.confirm 或 message.send。\n"
            "查询、总结、回顾、分析、检索、读取历史或询问“聊过什么”都不属于 action workflow，统一输出 is_action=false 且 steps=[]。\n"
            "多个对象默认表示多对象操作，不是歧义；只有单个名称对应多个本地实体时才由系统澄清。\n"
            "如果用户只是普通问答、写作、翻译或代码分析，输出 is_action=false 且 steps=[]。\n"
            "只有需要执行、确认、取消或补充高风险应用操作时，才输出 action plan。"
        )

    @staticmethod
    def _user_prompt(user_text: str, *, pending_state: Any | None = None, prompt_kind: str | None = None) -> str:
        prompt_kind = prompt_kind or AIActionPlanner._prompt_kind(pending_state)
        now = datetime.now()
        header = (
            "请输出 JSON：is_action, goal, risk, action, slots, steps, final。\n"
            f"当前本地时间：{now.strftime('%Y-%m-%d %H:%M:%S')}。\n"
        )
        pending = _pending_prompt_block(pending_state)
        if prompt_kind == AIActionPlanner.PROMPT_PENDING_CONFIRMATION:
            return (
                header
                + "当前任务：判断用户对 pending 确认的回复。\n"
                "用户确认当前 preview：输出 action=\"confirm_action\"，slots={}，steps=[]，final={}。\n"
                "用户取消当前 pending：输出 action=\"cancel_action\"，slots={}，steps=[]，final={}。\n"
                "用户修改目标、内容或条件：不要确认原 plan，可输出新的结构化动作；无法判断则 is_action=false 且 steps=[]。\n"
                f"用户输入：{str(user_text or '').strip()}"
                f"{pending}"
            )
        if prompt_kind == AIActionPlanner.PROMPT_PENDING_CONTACT_SELECTION:
            return (
                header
                + "当前任务：从 pending 候选联系人中判断用户选择了哪一个。\n"
                "能确定候选：输出 action=\"select_contact_alias\"，slots 使用 selection_index、contact_id 或 alias_text，steps=[]，final={}。\n"
                "用户取消 pending：输出 action=\"cancel_action\"，slots={}，steps=[]，final={}。\n"
                "无法确定候选或输入无关：输出 is_action=false 且 steps=[]。\n"
                f"用户输入：{str(user_text or '').strip()}"
                f"{pending}"
            )
        if prompt_kind == AIActionPlanner.PROMPT_PENDING_CLARIFICATION:
            return (
                header
                + "当前任务：判断用户是否补齐 pending 缺失信息。\n"
                "如果补齐信息后能继续，输出修正后的结构化 plan；如果用户取消，输出 action=\"cancel_action\" 且 steps=[]。\n"
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
            "发送组合必须同时有明确目标和明确消息内容。\n"
            "只有明确要求发送/发布/添加/删除/修改时才使用发送组合；询问历史、回顾、总结、检索内容时输出 is_action=false 且不要生成 steps。\n"
            f"用户输入：{str(user_text or '').strip()}"
        )


def _pending_prompt_block(pending_state: Any | None) -> str:
    if pending_state is None:
        return ""
    return "\n\n当前 pending plan/action：" + json.dumps(
                {
                    "action": getattr(pending_state, "action", ""),
                    "state": getattr(pending_state, "state", ""),
                    "slots": getattr(pending_state, "slots", {}),
                    "missing_slots": getattr(pending_state, "missing_slots", []),
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
        contact_alias_resolver: ContactAliasResolver | None = None,
    ) -> None:
        self._store = action_store or get_ai_action_store()
        self._planner = planner or AIActionPlanner()
        self._contact_alias_resolver = contact_alias_resolver or ContactAliasResolver()
        self._normalizer = AIPlanNormalizer()
        self._optimizer = AIPlanOptimizer()
        self._resource_manager = AIResourceManager()
        self._registry = AtomicActionRegistry(
            contact_resolver=self._contact_alias_resolver,
        )
        self._executor = AIActionExecutor(registry=self._registry, store=self._store)

    async def handle_user_turn(
        self,
        *,
        thread_id: str,
        text: str,
        has_attachments: bool = False,
    ) -> AIActionTurnResult:
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
        raw_plan = await self._build_plan(normalized_text, pending_state=pending_state)
        logger.info(
            "[ai-diag] ai_action_workflow_planner_result thread_id=%s is_action=%s steps=%s missing_slots=%s action=%s",
            thread_id,
            raw_plan.is_action,
            len(raw_plan.steps),
            len(raw_plan.missing_slots),
            raw_plan.action,
        )
        if pending is not None:
            control = await self._handle_planner_control(pending, raw_plan)
            if control is not None:
                return control

        if not raw_plan.is_action:
            return AIActionTurnResult(handled=False)

        normalized_plan = self._normalizer.normalize(raw_plan, user_text=normalized_text)
        if not normalized_plan.is_action:
            return AIActionTurnResult(handled=False)
        if normalized_plan.missing_slots:
            return await self._create_clarification(thread_id, normalized_plan)
        if not normalized_plan.steps:
            return await self._disabled_legacy_action(thread_id, normalized_plan)

        optimized_plan, optimize_reason = self._optimizer.optimize(normalized_plan)
        resource = self._resource_manager.check_plan(optimized_plan)
        if not resource.allowed:
            return await self._create_resource_clarification(thread_id, optimized_plan, resource.response_text)

        plan_json = optimized_plan.to_dict()
        plan_json["compat_action"] = _compat_action(optimized_plan)
        plan_json["compat_slots"] = dict(optimized_plan.slots or {})
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
        return await self._execute_to_turn(record)

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

    def _pending_for_planner(self, pending: AIActionPlanRecord | None) -> PendingPlannerState | None:
        if pending is None:
            return None
        plan_json = dict(pending.plan_json or {})
        waiting = dict(pending.waiting_payload or {})
        slots = dict(plan_json.get("compat_slots") or {})
        missing_slots: list[str] = []
        waiting_type = str(waiting.get("type") or "")
        if waiting_type == "contact_ambiguity":
            slots["alias_ambiguity"] = waiting
            missing_slots.append("participant_identity")
        elif waiting_type == "clarification":
            missing_slots.extend(
                str(item or "").strip()
                for item in list(waiting.get("missing") or [])
                if str(item or "").strip()
            )
        return PendingPlannerState(
            id=pending.id,
            thread_id=pending.thread_id,
            ai_thread_id=pending.thread_id,
            action=str(plan_json.get("compat_action") or _compat_action(AIActionPlan.from_dict(plan_json)) or ""),
            state=pending.state,
            slots=slots,
            missing_slots=tuple(missing_slots),
            waiting_payload=waiting,
        )

    async def _handle_planner_control(self, pending: AIActionPlanRecord, plan: AIActionPlan) -> AIActionTurnResult | None:
        action = str(plan.action or "").strip()
        if action == "cancel_action":
            return await self._cancel_pending(pending)
        if action == "confirm_action" and pending.state == "waiting_confirmation":
            return await self._confirm_pending(pending)
        if action == "select_contact_alias" and pending.state == "waiting_clarification":
            slots = dict(plan.slots or {})
            selection = str(slots.get("selection_index") or slots.get("contact_id") or slots.get("alias_text") or "")
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
        outputs = dict(pending.step_outputs or {})
        outputs[pending.current_step_id] = {
            "confirmed": True,
            "risk": waiting.get("risk"),
            "preview": waiting.get("preview"),
            "confirmed_at": time.time(),
        }
        updated = await self._store.update_plan(
            pending.id,
            state="running",
            step_outputs=outputs,
            waiting_payload={},
        )
        return await self._execute_to_turn(updated or pending)

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
        plan_json = dict(pending.plan_json or {})
        compat = dict(plan_json.get("compat_slots") or {})
        compat["resolved_contacts"] = contacts
        plan_json["compat_slots"] = compat
        updated = await self._store.update_plan(
            pending.id,
            state="running",
            plan_json=plan_json,
            bump_version=False,
            step_outputs=outputs,
            waiting_payload={},
        )
        return await self._execute_to_turn(updated or pending)

    async def _execute_to_turn(self, record: AIActionPlanRecord) -> AIActionTurnResult:
        result = await self._executor.execute(record)
        latest = await self._store.get_plan(record.id) or record
        return self._result_to_turn(latest, result)

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

    async def _create_clarification(self, thread_id: str, plan: AIActionPlan) -> AIActionTurnResult:
        response_text = _clarification_question(plan)
        plan_json = plan.to_dict()
        plan_json["compat_action"] = _compat_action(plan)
        plan_json["compat_slots"] = dict(plan.slots or {})
        record = await self._store.create_plan(
            thread_id=thread_id,
            goal=plan.goal,
            plan_json=plan_json,
            state="waiting_clarification",
            reason="normalizer_missing_slots",
        )
        await self._store.update_plan(
            record.id,
            waiting_payload={
                "type": "clarification",
                "missing": list(plan.missing_slots or []),
                "slots": dict(plan.slots or {}),
                "response_text": response_text,
            },
        )
        latest = await self._store.get_plan(record.id) or record
        return AIActionTurnResult(handled=True, response_text=response_text, message_extra={"ai_action": self._extra(latest)})

    async def _create_resource_clarification(self, thread_id: str, plan: AIActionPlan, response_text: str) -> AIActionTurnResult:
        plan_json = plan.to_dict()
        plan_json["compat_action"] = _compat_action(plan)
        plan_json["compat_slots"] = dict(plan.slots or {})
        record = await self._store.create_plan(
            thread_id=thread_id,
            goal=plan.goal,
            plan_json=plan_json,
            state="waiting_clarification",
            reason="resource_limit",
        )
        await self._store.update_plan(
            record.id,
            waiting_payload={"type": "clarification", "reason": "resource_limit", "response_text": response_text},
        )
        latest = await self._store.get_plan(record.id) or record
        return AIActionTurnResult(handled=True, response_text=response_text, message_extra={"ai_action": self._extra(latest)})

    async def _disabled_legacy_action(self, thread_id: str, plan: AIActionPlan) -> AIActionTurnResult:
        text = _disabled_legacy_text(plan.action, plan.slots)
        plan_json = plan.to_dict()
        plan_json["compat_action"] = _compat_action(plan)
        plan_json["compat_slots"] = dict(plan.slots or {})
        record = await self._store.create_plan(
            thread_id=thread_id,
            goal=plan.goal,
            plan_json=plan_json,
            state="done",
            reason="disabled_legacy_action",
        )
        await self._store.update_plan(
            record.id,
            state="done",
            step_outputs={"final": {"text": text, "status": "disabled"}},
            completed_at=time.time(),
        )
        latest = await self._store.get_plan(record.id) or record
        return AIActionTurnResult(handled=True, response_text=text, message_extra={"ai_action": self._extra(latest)})

    @staticmethod
    def _extra(record: AIActionPlanRecord, *, state: str | None = None) -> dict[str, Any]:
        plan_json = dict(record.plan_json or {})
        steps = [
            {
                "id": str(step.get("id") or ""),
                "action": str(step.get("action") or ""),
                "state": "done" if str(step.get("id") or "") in set(record.step_outputs or {}) else "pending",
                "display_text": str(step.get("display_text") or ""),
                "explanation": str(step.get("explanation") or ""),
            }
            for step in list(plan_json.get("steps") or [])
            if isinstance(step, dict)
        ]
        return {
            "id": record.id,
            "plan_id": record.id,
            "action": str(plan_json.get("compat_action") or _compat_action(AIActionPlan.from_dict(plan_json)) or ""),
            "state": state or record.state,
            "kind": "write" if _plan_has_action(plan_json, "message.send") else "read",
            "risk_level": str(plan_json.get("risk") or "low"),
            "plan_version": record.plan_version,
            "current_step_id": record.current_step_id,
            "steps": steps,
            "waiting": dict(record.waiting_payload or {}),
        }


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
    return AIActionPlan(
        is_action=bool(data.get("is_action")),
        action=str(data.get("action") or "").strip(),
        requires_app_data=bool(data.get("requires_app_data")),
        requires_side_effect=bool(data.get("requires_side_effect")),
        slots=dict(data.get("slots") or {}) if isinstance(data.get("slots"), dict) else {},
        missing_slots=tuple(_clean_list(data.get("missing_slots"))),
    )


def _clarification_question(plan: AIActionPlan) -> str:
    missing = set(plan.missing_slots)
    slots = dict(plan.slots or {})
    if "target_user" in missing:
        return "你想把这句话发给谁？"
    if "message_text" in missing:
        return "你想发送的具体内容是什么？"
    return "这个操作还缺少信息，请继续补充。"


def _disabled_legacy_text(action: str, slots: dict[str, Any]) -> str:
    if action == "add_friend":
        return f"我识别到你想添加{slots.get('target_user') or '某人'}为好友。当前版本还没有接入真实添加好友能力。"
    if action == "post_moment":
        return "我识别到你想发朋友圈。当前版本还没有接入真实发布能力，所以不会实际发布。"
    return "这个操作当前还没有接入真实执行。"


def _compat_action(plan: AIActionPlan) -> str:
    if plan.action:
        return plan.action
    actions = [step.action for step in plan.steps]
    if "message.send" in actions:
        return "send_message"
    if actions:
        return actions[-1].replace(".", "_")
    return ""


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
