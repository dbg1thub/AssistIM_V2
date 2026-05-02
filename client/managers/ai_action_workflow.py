"""AI assistant action workflow based on atomic executable plans."""

from __future__ import annotations

import copy
import json
import inspect
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Sequence

from client.core import logging
from client.managers.ai_action_executor import AIActionExecutor
from client.managers.ai_action_memory_summarizer import AIActionMemorySummarizer
from client.managers.ai_action_normalizer import AIPlanNormalizer
from client.managers.ai_action_optimizer import AIPlanOptimizer
from client.managers.ai_action_permission_policy import AIPermissionPolicy, AIPermissionScope
from client.managers.ai_action_registry import (
    AtomicActionRegistry,
    build_default_action_names,
    build_default_action_prompt_closure,
    build_default_action_prompt_contract,
    build_default_candidate_action_names,
    build_default_candidate_action_prompt_contract,
    build_default_required_action_closure,
)
from client.managers.ai_action_resource_manager import AIResourceManager
from client.managers.ai_action_types import (
    AIActionEvent,
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

AIActionTurnProgressCallback = Callable[[AIActionTurnResult], Any]


def _normalize_registered_action_names(action_names: Sequence[str] | None) -> tuple[str, ...]:
    names: list[str] = []
    for raw_name in tuple(action_names or ()):
        name = str(raw_name or "").strip()
        if name and name not in names:
            names.append(name)
    return tuple(names)


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


@dataclass(frozen=True, slots=True)
class AIActionCandidateSelection:
    """First-stage model output listing candidate target actions for planning."""

    is_action: bool
    goal: str = ""
    candidate_actions: tuple[str, ...] = ()
    reason: str = ""


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

    PLANNER_SCHEMA_VERSION = "atomic_steps_v2"
    PLANNER_PROMPT_VERSION = "atomic_steps_prompt_v18"
    CANDIDATE_SCHEMA_VERSION = "action_candidates_v1"
    CANDIDATE_PROMPT_VERSION = "action_candidates_prompt_v1"
    PLAN_OUTPUT_VERSION = 1
    PLAN_MAX_TOKENS = 2048
    PLAN_REPAIR_MAX_TOKENS = 2048
    CANDIDATE_MAX_TOKENS = 384

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
    FINAL_SCHEMA: dict[str, Any] = {
        "type": "object",
        "properties": {
            "type": {},
            "source": {},
            "sources": {},
            "status": {},
            "text": {},
            "result": {},
            "summary": {},
            "reason": {},
            "error": {},
            "message": {},
            "details": {},
        },
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
            "final": FINAL_SCHEMA,
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
            "final": FINAL_SCHEMA,
        },
        "required": ["is_action", "goal", "risk", "steps", "final"],
        "additionalProperties": False,
    }
    PENDING_CLARIFICATION_SCHEMA: dict[str, Any] = PENDING_CONTROL_SCHEMA
    CANDIDATE_SCHEMA: dict[str, Any] = {
        "type": "object",
        "properties": {
            "is_action": {"type": "boolean"},
            "goal": {"type": "string"},
            "candidate_actions": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
        },
        "required": ["is_action", "goal", "candidate_actions"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        task_manager: Any | None = None,
        *,
        action_registry: AtomicActionRegistry | None = None,
        action_contract_prompt: str | None = None,
        registered_action_names: Sequence[str] | None = None,
    ) -> None:
        self._task_manager = task_manager
        self._action_registry = action_registry
        self._action_contract_prompt = str(action_contract_prompt or "").strip()
        self._registered_action_names = _normalize_registered_action_names(
            registered_action_names if registered_action_names is not None else build_default_action_names()
        )
        self._candidate_action_names = (
            action_registry.candidate_action_names()
            if action_registry is not None
            else build_default_candidate_action_names()
        )

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
        action_contract_prompt = self._action_contract_prompt_for(prompt_kind)
        registered_action_names = self._registered_action_names
        candidate_selection: AIActionCandidateSelection | None = None
        candidate_action_closure: tuple[str, ...] = ()
        required_action_closure: tuple[str, ...] = ()
        if prompt_kind == self.PROMPT_NEW_ACTION:
            candidate_selection = await self._select_candidate_actions(user_text, strict=strict)
            if candidate_selection is None:
                return None
            if not candidate_selection.is_action:
                return AIActionPlan(
                    is_action=False,
                    goal=candidate_selection.goal,
                    risk="low",
                    steps=(),
                    final={},
                )
            candidate_action_closure = self._candidate_action_closure(candidate_selection.candidate_actions)
            if not candidate_action_closure:
                logger.info(
                    "[ai-diag] ai_action_candidate_selector_empty_closure candidates=%s",
                    list(candidate_selection.candidate_actions),
                )
                return AIActionPlan(
                    is_action=False,
                    goal=candidate_selection.goal,
                    risk="low",
                    steps=(),
                    final={"reason": "candidate_actions_empty"},
                )
            action_contract_prompt = self._action_contract_prompt_for(
                prompt_kind,
                action_names=candidate_action_closure,
            )
            registered_action_names = candidate_action_closure
            required_action_closure = self._candidate_required_action_closure(candidate_selection.candidate_actions)
        schema = self._schema_for_prompt_kind(prompt_kind, registered_action_names=registered_action_names)
        user_prompt = self._user_prompt(
            user_text,
            pending_state=pending_state,
            prompt_kind=prompt_kind,
            required_action_names=required_action_closure,
        )
        request = AIRequest(
            task_id=f"ai-action-plan-{int(time.time() * 1000)}",
            session_id=str(getattr(pending_state, "ai_thread_id", "") or getattr(pending_state, "thread_id", "") or ""),
            task_type=AITaskType.CHAT,
            privacy_scope=AIPrivacyScope.GENERAL,
            must_be_local=True,
            stream=False,
            temperature=0.0,
            max_tokens=self.PLAN_MAX_TOKENS,
            response_format={"type": "json_object", "schema": schema} if strict else None,
            priority=4,
            system_prompt=self._system_prompt(prompt_kind, action_contract=action_contract_prompt),
            messages=[{"role": "user", "content": user_prompt}],
            metadata={
                "source": "ai_action_planner",
                "strict_json": strict,
                "planner_schema_version": self.PLANNER_SCHEMA_VERSION,
                "planner_prompt_version": self.PLANNER_PROMPT_VERSION,
                "planner_prompt_kind": prompt_kind,
                "candidate_actions": list(candidate_selection.candidate_actions) if candidate_selection is not None else [],
                "candidate_action_closure": list(candidate_action_closure),
                "required_action_closure": list(required_action_closure),
            },
        )
        try:
            snapshot = await self._task_manager.run_once(request)
        except Exception:
            logger.exception("AI action planner failed")
            return None
        return _parse_planner_json(str(getattr(snapshot, "content", "") or ""))

    async def _select_candidate_actions(self, user_text: str, *, strict: bool) -> AIActionCandidateSelection | None:
        if self._task_manager is None:
            return None
        try:
            from client.services.ai_service import AIPrivacyScope, AIRequest, AITaskType
        except Exception:
            logger.debug("AI action candidate selector request contracts are unavailable", exc_info=True)
            return None

        request = AIRequest(
            task_id=f"ai-action-candidates-{int(time.time() * 1000)}",
            task_type=AITaskType.CHAT,
            privacy_scope=AIPrivacyScope.GENERAL,
            must_be_local=True,
            stream=False,
            temperature=0.0,
            max_tokens=self.CANDIDATE_MAX_TOKENS,
            response_format={
                "type": "json_object",
                "schema": self.build_candidate_schema(registered_action_names=self._candidate_action_names),
            }
            if strict
            else None,
            priority=4,
            system_prompt=self._candidate_system_prompt(action_catalog=self._candidate_action_catalog_prompt()),
            messages=[{"role": "user", "content": self._candidate_user_prompt(user_text)}],
            metadata={
                "source": "ai_action_candidate_selector",
                "strict_json": strict,
                "candidate_schema_version": self.CANDIDATE_SCHEMA_VERSION,
                "candidate_prompt_version": self.CANDIDATE_PROMPT_VERSION,
            },
        )
        try:
            snapshot = await self._task_manager.run_once(request)
        except Exception:
            logger.exception("AI action candidate selector failed")
            return None
        selection = parse_candidate_selection_json(
            str(getattr(snapshot, "content", "") or ""),
            registered_action_names=self._candidate_action_names,
        )
        if selection is None:
            logger.info("[ai-diag] ai_action_candidate_selector_invalid")
            return None
        logger.info(
            "[ai-diag] ai_action_candidate_selector_result is_action=%s candidates=%s reason=%s",
            selection.is_action,
            list(selection.candidate_actions),
            selection.reason,
        )
        return selection

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
        invalid_action_names = tuple(step.action for step in tuple(invalid_plan.steps or ()))
        repair_action_closure = self._candidate_action_closure(invalid_action_names)
        action_contract_prompt = self._action_contract_prompt_for(
            prompt_kind,
            action_names=repair_action_closure or None,
        )
        registered_action_names = repair_action_closure or self._registered_action_names
        schema = self._schema_for_prompt_kind(prompt_kind, registered_action_names=registered_action_names)
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
            max_tokens=self.PLAN_REPAIR_MAX_TOKENS,
            response_format={"type": "json_object", "schema": schema} if strict else None,
            priority=4,
            system_prompt=(
                self._system_prompt(prompt_kind, action_contract=action_contract_prompt)
                + "\n你现在处于 plan 修正模式：不要重新解释用户意图，只修正结构错误。"
                "可以修正 step id、depends_on、$ 引用、action 名称、args 字段和 final 引用。"
                "如果 final 中包含 action、args 或 depends_on，表示可执行动作放错位置：把该 action 移到 steps，final 改为引用对应 step 输出。"
            ),
            messages=[{"role": "user", "content": repair_prompt}],
            metadata={
                "source": "ai_action_planner_repair",
                "strict_json": strict,
                "planner_schema_version": self.PLANNER_SCHEMA_VERSION,
                "planner_prompt_version": self.PLANNER_PROMPT_VERSION,
                "planner_prompt_kind": prompt_kind,
                "validation_error_count": len(tuple(validation_errors or ())),
                "candidate_action_closure": list(repair_action_closure),
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

    def _schema_for_prompt_kind(
        self,
        prompt_kind: str,
        *,
        registered_action_names: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        return self.build_schema_for_prompt_kind(
            prompt_kind,
            registered_action_names=registered_action_names or self._registered_action_names,
        )

    @classmethod
    def build_schema_for_prompt_kind(
        cls,
        prompt_kind: str,
        *,
        registered_action_names: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        if prompt_kind in {
            AIActionPlanner.PROMPT_PENDING_CONFIRMATION,
            AIActionPlanner.PROMPT_PENDING_CONTACT_SELECTION,
        }:
            return cls._schema_with_action_enum(
                cls.PENDING_CONTROL_SCHEMA,
                registered_action_names=registered_action_names,
            )
        if prompt_kind == AIActionPlanner.PROMPT_PENDING_CLARIFICATION:
            return cls._schema_with_action_enum(
                cls.PENDING_CLARIFICATION_SCHEMA,
                registered_action_names=registered_action_names,
            )
        return cls._schema_with_action_enum(
            cls.NEW_ACTION_SCHEMA,
            registered_action_names=registered_action_names,
        )

    @classmethod
    def build_candidate_schema(
        cls,
        *,
        registered_action_names: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        schema_copy = copy.deepcopy(cls.CANDIDATE_SCHEMA)
        names = _normalize_registered_action_names(registered_action_names)
        if names:
            actions = schema_copy.get("properties", {}).get("candidate_actions")
            if isinstance(actions, dict):
                items = actions.get("items")
                if isinstance(items, dict):
                    items["enum"] = list(names)
        return schema_copy

    @classmethod
    def _schema_with_action_enum(
        cls,
        schema: dict[str, Any],
        *,
        registered_action_names: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        schema_copy = copy.deepcopy(schema)
        names = _normalize_registered_action_names(registered_action_names)
        if not names:
            return schema_copy
        steps = schema_copy.get("properties", {}).get("steps")
        if not isinstance(steps, dict):
            return schema_copy
        items = steps.get("items")
        if not isinstance(items, dict):
            return schema_copy
        action_schema = items.get("properties", {}).get("action")
        if isinstance(action_schema, dict):
            action_schema["enum"] = list(names)
        return schema_copy

    def _candidate_action_catalog_prompt(self) -> str:
        if self._action_registry is not None:
            return self._action_registry.candidate_prompt_contract()
        return build_default_candidate_action_prompt_contract()

    def _action_contract_prompt_for(
        self,
        prompt_kind: str,
        *,
        action_names: Sequence[str] | None = None,
    ) -> str:
        if prompt_kind != self.PROMPT_NEW_ACTION:
            return self._action_contract_prompt
        if self._action_registry is not None:
            return self._action_registry.prompt_contract(action_names=action_names)
        if action_names is not None:
            return build_default_action_prompt_contract(action_names=action_names)
        return self._action_contract_prompt or build_default_action_prompt_contract()

    def _candidate_action_closure(self, action_names: Sequence[str] | None) -> tuple[str, ...]:
        if self._action_registry is not None:
            return self._action_registry.prompt_action_closure(action_names)
        return build_default_action_prompt_closure(action_names)

    def _candidate_required_action_closure(self, action_names: Sequence[str] | None) -> tuple[str, ...]:
        if self._action_registry is not None:
            return self._action_registry.required_action_closure(action_names)
        return build_default_required_action_closure(action_names)

    @staticmethod
    def _system_prompt(prompt_kind: str = PROMPT_NEW_ACTION, *, action_contract: str | None = None) -> str:
        common = (
            "你是 AssistIM 的动作规划器，只输出 JSON，不要解释，不要使用代码块。\n"
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
        contract = str(action_contract or "").strip() or build_default_action_prompt_contract()
        return (
            common
            + "需 AssistIM 数据/本地能力时拆原子 steps。\n"
            "普通问答等输出 is_action=false。\n"
            "只有读取或操作 AssistIM 本地数据、调用已注册能力、处理 pending 时才输出 action plan。\n"
            "规划规则：\n"
            "- 每个 step.id 必须唯一，使用简短稳定名称即可，不要求固定命名。\n"
            "step.id 只能使用字母、数字和下划线，不能包含点号，避免和 $ 引用路径混淆。\n"
            "所有 $ 引用的根名称必须等于已存在 step.id；不要生成 %step_0 这类临时 id。\n"
            "- 契约中 deps=a,b 表示 depends_on 包含对应上游 step；refs=x<-a.y 表示 args.x 写成 $step_id.y；"
            "no_literal 禁止普通字符串；obj=p(a,b) 表示 args.p 是对象且含字段。\n"
            "- 契约里的 action 名称只说明输出来源，不能用 action 名称当 $ 引用根。\n"
            "- final 是顶层结果描述，不是 step；展示、返回或最终结果只写在顶层 final，final 只引用最后一个 step 输出，不要编造或展开服务端返回字段；不要生成 id=final 的 step，也不能为返回结果重复执行同一个 action。\n"
            "- 用户已经给出稳定 ID（如 user-*、session-*、group-*、moment-*、req-*）时，直接填入对应 ID 字段，不要再额外规划 contact.resolve 或搜索动作。\n"
            "- 输入契约没有字段的 action，args 必须是 {}，不要补 null 字段或猜测字段。\n"
            "- 读取类任务不需要确认；写操作必须先生成 preview 并经过 user.confirm，确认后才能执行写 action。\n"
            "- plan 包含 write action 时 risk=high。\n"
            "- 对任何写 action，idempotency_key 必须是写 action 的顶层 args 字段，不要放进 preview 对象；preview.content 必须非空并描述本次操作内容。\n"
            "- 明确要求发送/添加/发布/删除/修改应用数据时，必须规划写 action。\n"
            "- 多个对象默认表示多对象读取或操作，不是歧义；只有单个名称对应多个本地实体时才由系统澄清。\n"
            "- 涉及联系人、群名或会话对象的读取任务，必须先解析对象，并把解析结果传给后续读取 action 的 participants；不要把名称字符串直接放到 participants，也不要只把名称留在 question 或 keywords。\n"
            "- 历史聊天、语音转写、文件内容总结和已存在内容回顾属于本地记忆读取，优先使用 memory.search；如果用户问题里出现联系人或会话对象，memory.search 前必须有 contact.resolve，participants 不能为空。\n"
            "- 用户要求搜索用户、查看好友、群组、会话、未读、文件列表或朋友圈列表等当前账号服务端数据时，使用对应服务端只读 action；输入中已有关键词时不要要求用户再次提供。\n"
            "- 需要向用户回答检索到的内容时，先检索再总结；final 不直接指向 memory.search，除非用户明确只要原始列表或原始记录。\n"
            "- 严格使用已注册 action、输入字段和输出字段；不要发明 action、字段或不存在的上游输出。\n"
            "- 可由已注册 read action 解析或搜索到的目标仍视为可完成，不要因为当前没有 ID 就输出 false。\n"
            "- 需要先调用某个已注册 action 不是失败理由；把它规划成 step，再让后续 step 引用它的输出。\n"
            "- 如果用户请求的应用能力不能完全用已注册 action 完成，输出 is_action=false 且 steps=[]；不要发明 action，也不要用相近 action 代替。\n"
            "- 根据 action 用途和输入/输出契约自行组合 plan，不要按固定示例补齐计划。\n"
            "- 只输出完成用户目标的最小必要 steps；不要加入可选、辅助、预热或候选步骤。\n"
            "- 如果某个 step 的输出不会被后续 step 或 final 使用，说明它不在当前目标的执行链路中，不要输出。\n"
            "- 写操作完成后 final 指向写 action 的输出；除非用户明确要求继续查询，否则不要在写 action 后追加只读 action。\n"
            f"{contract}"
        )

    @staticmethod
    def _candidate_system_prompt(*, action_catalog: str | None = None) -> str:
        catalog = str(action_catalog or "").strip() or build_default_candidate_action_prompt_contract()
        return (
            "你是 AssistIM 的候选 action 选择器，只输出 JSON，不要解释，不要使用代码块。\n"
            "当前只判断用户目标需要哪些已注册目标 action，不能输出 steps、args、final 或执行计划。\n"
            "candidate_actions 只能从目录选择，放用户最终需要的目标 action；系统会按 registry 自动补齐闭包里的前置/支撑 action。\n"
            "候选阶段只选择能力，不要判断参数是否已经完整；不要因为目标、内容或 ID 尚未结构化就输出 false。\n"
            "不要为了确认、草稿或解析对象选择内部支撑 action；普通问答、写作、翻译、代码分析输出 is_action=false 且 candidate_actions=[]。\n"
            "如果用户明确要求读取或操作 AssistIM 本地数据、聊天记忆、当前账号服务端数据，输出 is_action=true 并选择最小目标 action 集合。\n"
            f"{catalog}"
        )

    @staticmethod
    def _candidate_user_prompt(user_text: str) -> str:
        return (
            "请输出 JSON：is_action, goal, candidate_actions, reason。\n"
            f"用户输入：{str(user_text or '').strip()}"
        )

    @staticmethod
    def _user_prompt(
        user_text: str,
        *,
        pending_state: Any | None = None,
        prompt_kind: str | None = None,
        required_action_names: Sequence[str] | None = None,
    ) -> str:
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
                "补齐后的写操作仍必须经过 user.confirm，并继续遵守已注册 action 契约。\n"
                f"用户输入：{str(user_text or '').strip()}"
                f"{pending}"
            )
        required_chain = _required_action_chain_prompt(required_action_names)
        return (
            header
            + "step 字段：id, action, depends_on, args, display_text, explanation。\n"
            "引用上游输出使用 $step_id.field 或 $step_id.field[0]。\n"
            "写操作必须有明确目标和内容，并经过确认。\n"
            "查询、回顾、总结或检索已存在内容是读取，不要确认。\n"
            "按已注册 action 的用途、输入字段和输出字段组合 steps，不要按固定示例补齐计划。\n"
            f"{required_chain}"
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


def _required_action_chain_prompt(action_names: Sequence[str] | None) -> str:
    names = _normalize_registered_action_names(action_names)
    if not names:
        return ""
    return (
        f"候选阶段已判定这是 action。必需执行链路：{' -> '.join(names)}。\n"
        "这些 action 必须出现在 steps；如果某一步需要上游结果，先规划上游 step，不能输出 is_action=false。\n"
    )


class AIActionWorkflow:
    """Plan, validate, execute, pause, and resume assistant actions."""

    PENDING_CONFIRMATION_TTL_SECONDS = 120

    def __init__(
        self,
        *,
        action_store: AIActionStore | AIActionPlanStore | None = None,
        planner: AIActionPlanner | None = None,
        task_manager: Any | None = None,
        contact_alias_resolver: ContactAliasResolver | None = None,
        memory_manager: Any | None = None,
        memory_summarizer: Any | None = None,
        message_sender: Any | None = None,
        server_reader: Any | None = None,
        server_writer: Any | None = None,
        permission_scope_provider: Callable[[], AIPermissionScope | None] | None = None,
    ) -> None:
        self._store = action_store or get_ai_action_store()
        resolved_task_manager = task_manager
        if resolved_task_manager is None and (planner is None or memory_summarizer is None):
            resolved_task_manager = get_ai_task_manager()
        self._contact_alias_resolver = contact_alias_resolver or ContactAliasResolver()
        self._message_sender = message_sender
        self._permission_scope_provider = permission_scope_provider
        self._optimizer = AIPlanOptimizer()
        self._registry = AtomicActionRegistry(
            contact_resolver=self._contact_alias_resolver,
            memory_manager=memory_manager,
            memory_summarizer=memory_summarizer or AIActionMemorySummarizer(task_manager=resolved_task_manager),
            message_sender=self._message_sender,
            server_reader=server_reader,
            server_writer=server_writer,
        )
        self._normalizer = AIPlanNormalizer(
            write_action_names=(
                name
                for name in self._registry.names()
                if (spec := self._registry.get(name)) is not None and spec.kind == "write"
            ),
            action_specs=(
                spec
                for name in self._registry.names()
                if (spec := self._registry.get(name)) is not None
            ),
        )
        self._planner = planner or AIActionPlanner(
            task_manager=resolved_task_manager,
            action_registry=self._registry,
            registered_action_names=self._registry.names(),
        )
        self._resource_manager = AIResourceManager(registry=self._registry)
        self._validator = AIPlanValidator(registry=self._registry)
        self._executor = AIActionExecutor(registry=self._registry, store=self._store)

    async def handle_user_turn(
        self,
        *,
        thread_id: str,
        text: str,
        has_attachments: bool = False,
        progress_callback: AIActionTurnProgressCallback | None = None,
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
        pending = await self._expire_pending_confirmation_if_needed(pending)
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
            control = await self._handle_planner_control(
                pending,
                raw_plan,
                progress_callback=progress_callback,
            )
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
                return self._invalid_plan_turn(validation, plan=normalized_plan)
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
                return self._invalid_plan_turn(validation, plan=normalized_plan)

        optimizer_started = time.perf_counter()
        optimized_plan, optimize_reason = self._optimizer.optimize(normalized_plan)
        optimizer_ms = _elapsed_ms(optimizer_started)
        optimized_validation = self._validator.validate(optimized_plan)
        if not optimized_validation.allowed:
            log_perf("optimized_plan_invalid", handled=True, plan=optimized_plan)
            return self._invalid_plan_turn(optimized_validation, plan=optimized_plan)
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
                resource_estimate=resource.estimate,
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
        await self._emit_progress_turn(progress_callback, record)
        executor_started = time.perf_counter()
        turn = await self._execute_to_turn(record, progress_callback=progress_callback)
        executor_ms = _elapsed_ms(executor_started)
        log_perf(str(turn.message_extra.get("ai_action", {}).get("state") or "done"), handled=turn.handled, plan=optimized_plan)
        return turn

    async def handle_pending_control(
        self,
        *,
        thread_id: str,
        control_type: str,
        progress_callback: AIActionTurnProgressCallback | None = None,
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
        expired = await self._expire_pending_confirmation_if_needed(pending)
        if expired is None:
            return AIActionTurnResult(
                handled=True,
                response_text="这个确认已过期，请重新发起操作。",
                message_extra={"ai_action": self._extra(pending, state="cancelled")},
            )
        pending = expired
        logger.info(
            "[ai-diag] ai_action_pending_control thread_id=%s plan_id=%s state=%s control=%s",
            normalized_thread_id,
            pending.id,
            pending.state,
            normalized_control,
        )
        if normalized_control == "cancel":
            return await self._cancel_pending(pending, progress_callback=progress_callback)
        if pending.state == "waiting_confirmation":
            return await self._confirm_pending(pending, progress_callback=progress_callback)
        return AIActionTurnResult(
            handled=True,
            response_text=str(pending.waiting_payload.get("response_text") or "这个操作还在等待补充信息。"),
            message_extra={"ai_action": self._extra(pending)},
        )

    async def cancel_plan(
        self,
        plan_id: str,
        *,
        progress_callback: AIActionTurnProgressCallback | None = None,
    ) -> AIActionTurnResult:
        normalized_plan_id = str(plan_id or "").strip()
        if not normalized_plan_id:
            return AIActionTurnResult(handled=False)
        record = await self._store.get_plan(normalized_plan_id)
        if record is None:
            logger.info("[ai-diag] ai_action_cancel_skipped plan_id=%s reason=not_found", normalized_plan_id)
            return AIActionTurnResult(handled=False)
        if record.state == "cancelled":
            updated = await self._mark_plan_cancelled(record, progress_callback=progress_callback)
            return AIActionTurnResult(
                handled=True,
                response_text="已取消这个操作。",
                message_extra={"ai_action": self._extra(updated, state="cancelled")},
            )
        if record.state in {"done", "failed"}:
            return AIActionTurnResult(
                handled=True,
                response_text="这个操作已经结束。",
                message_extra={"ai_action": self._extra(record)},
            )
        updated = await self._mark_plan_cancelled(record, progress_callback=progress_callback)
        logger.info(
            "[ai-diag] ai_action_plan_cancelled thread_id=%s plan_id=%s previous_state=%s",
            record.thread_id,
            record.id,
            record.state,
        )
        return AIActionTurnResult(
            handled=True,
            response_text="已取消这个操作。",
            message_extra={"ai_action": self._extra(updated, state="cancelled")},
        )

    async def recover_interrupted_plans(self) -> list[AIActionPlanRecord]:
        recovered = await self._store.recover_interrupted_plans()
        if recovered:
            logger.info("[ai-diag] ai_action_startup_recovered interrupted_count=%s", len(recovered))
        return recovered

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
        repair_skip_reason = self._plan_repair_skip_reason(invalid_plan, validation)
        if repair_skip_reason:
            logger.info(
                "[ai-diag] ai_action_plan_validation_repair_skipped reason=%s errors=%s first_error=%s",
                repair_skip_reason,
                len(validation.errors),
                validation.errors[0].code if validation.errors else "",
            )
            return None
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

    def _plan_repair_skip_reason(self, plan: AIActionPlan, validation: AIPlanValidationResult) -> str:
        if any(error.code == "ACTION_NOT_FOUND" for error in validation.errors):
            return "unknown_action"
        if self._plan_has_side_effect(plan) and not self._validation_is_planner_contract_only(validation):
            return "side_effect_plan"
        return ""

    @staticmethod
    def _validation_is_planner_contract_only(validation: AIPlanValidationResult) -> bool:
        return bool(validation.errors) and all(error.code == "PLANNER_CONTRACT_INVALID" for error in validation.errors)

    def _plan_has_side_effect(self, plan: AIActionPlan) -> bool:
        for step in tuple(plan.steps or ()):
            spec = self._registry.get(step.action)
            if spec is not None and (spec.kind == "write" or spec.allow_side_effect):
                return True
        return False

    def _invalid_plan_turn(self, validation: AIPlanValidationResult, *, plan: AIActionPlan | None = None) -> AIActionTurnResult:
        first = validation.errors[0] if validation.errors else None
        response_text = "这个操作计划结构有问题，请重新描述一下。"
        if any(error.code == "ACTION_NOT_FOUND" for error in validation.errors):
            response_text = "这个操作超出当前支持的能力，请重新描述一下。"
        elif plan is not None and self._plan_has_side_effect(plan):
            response_text = "这个高风险操作计划结构不安全，请重新描述一下。"
        return AIActionTurnResult(
            handled=True,
            response_text=response_text,
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

    async def _expire_pending_confirmation_if_needed(
        self, pending: AIActionPlanRecord | None
    ) -> AIActionPlanRecord | None:
        if pending is None or pending.state != "waiting_confirmation":
            return pending
        if not self._pending_confirmation_expired(pending):
            return pending
        age_seconds = max(0.0, time.time() - float(pending.updated_at or pending.created_at or 0.0))
        await self._store.update_plan(
            pending.id,
            state="cancelled",
            error_text="expired_confirmation",
            completed_at=time.time(),
        )
        logger.info(
            "[ai-diag] ai_action_pending_confirmation_expired thread_id=%s plan_id=%s age_ms=%s ttl_ms=%s",
            pending.thread_id,
            pending.id,
            int(age_seconds * 1000),
            int(self.PENDING_CONFIRMATION_TTL_SECONDS * 1000),
        )
        return None

    def _pending_confirmation_expired(self, pending: AIActionPlanRecord) -> bool:
        started = float(pending.updated_at or pending.created_at or 0.0)
        if started <= 0:
            return False
        return (time.time() - started) > self.PENDING_CONFIRMATION_TTL_SECONDS

    async def _handle_planner_control(
        self,
        pending: AIActionPlanRecord,
        plan: AIActionPlan,
        *,
        progress_callback: AIActionTurnProgressCallback | None = None,
    ) -> AIActionTurnResult | None:
        control = dict(plan.control or {})
        control_type = str(control.get("type") or "").strip()
        if control_type == "cancel":
            return await self._cancel_pending(pending, progress_callback=progress_callback)
        if control_type == "confirm" and pending.state == "waiting_confirmation":
            return await self._confirm_pending(pending, progress_callback=progress_callback)
        if control_type == "select_contact_alias" and pending.state == "waiting_clarification":
            selection = str(control.get("selection_index") or control.get("contact_id") or control.get("alias_text") or "")
            if selection:
                return await self._select_pending_contact(
                    pending,
                    selection,
                    progress_callback=progress_callback,
                )
        return None

    async def _cancel_pending(
        self,
        pending: AIActionPlanRecord,
        *,
        progress_callback: AIActionTurnProgressCallback | None = None,
    ) -> AIActionTurnResult:
        updated = await self._mark_plan_cancelled(pending, progress_callback=progress_callback)
        return AIActionTurnResult(
            handled=True,
            response_text="已取消这个操作。",
            message_extra={"ai_action": self._extra(updated, state="cancelled")},
        )

    async def _mark_plan_cancelled(
        self,
        record: AIActionPlanRecord,
        *,
        progress_callback: AIActionTurnProgressCallback | None = None,
    ) -> AIActionPlanRecord:
        plan_json = _plan_json_with_cancelled_event(record.plan_json, plan_id=record.id)
        updated = await self._store.update_plan(
            record.id,
            plan_json=plan_json,
            reason="plan_cancelled",
            bump_version=False,
            state="cancelled",
            current_step_id="",
            waiting_payload={},
            completed_at=time.time(),
        ) or record
        await self._emit_progress_turn(progress_callback, updated)
        return updated

    async def _confirm_pending(
        self,
        pending: AIActionPlanRecord,
        *,
        progress_callback: AIActionTurnProgressCallback | None = None,
    ) -> AIActionTurnResult:
        waiting = dict(pending.waiting_payload or {})
        if self._pending_confirmation_is_stale(pending, waiting):
            return AIActionTurnResult(
                handled=True,
                response_text="操作内容已变化，请重新发起这个操作。",
                message_extra={"ai_action": self._extra(pending)},
            )
        outputs = dict(pending.step_outputs or {})
        risk = waiting.get("risk")
        preview = waiting.get("preview")
        outputs[pending.current_step_id] = {
            "confirmed": True,
            "risk": risk,
            "preview": preview,
            "preview_fingerprint": confirmation_preview_fingerprint(preview, risk=risk),
            "confirmed_at": time.time(),
        }
        mark_step_output_current(outputs, step_id=pending.current_step_id, plan_version=pending.plan_version)
        updated = await self._store.update_plan(
            pending.id,
            state="running",
            step_outputs=outputs,
            waiting_payload={},
        )
        await self._emit_progress_turn(progress_callback, updated or pending)
        return await self._execute_to_turn(updated or pending, progress_callback=progress_callback)

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

    async def _select_pending_contact(
        self,
        pending: AIActionPlanRecord,
        selection: str,
        *,
        progress_callback: AIActionTurnProgressCallback | None = None,
    ) -> AIActionTurnResult:
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
        await self._emit_progress_turn(progress_callback, updated or pending)
        return await self._execute_to_turn(updated or pending, progress_callback=progress_callback)

    async def _execute_to_turn(
        self,
        record: AIActionPlanRecord,
        *,
        progress_callback: AIActionTurnProgressCallback | None = None,
    ) -> AIActionTurnResult:
        async def on_executor_progress(updated_record: AIActionPlanRecord) -> None:
            await self._emit_progress_turn(progress_callback, updated_record)

        result = await self._executor_for_current_scope().execute(
            record,
            progress_callback=on_executor_progress if progress_callback is not None else None,
        )
        latest = await self._store.get_plan(record.id) or record
        return self._result_to_turn(latest, result)

    async def _emit_progress_turn(
        self,
        progress_callback: AIActionTurnProgressCallback | None,
        record: AIActionPlanRecord,
    ) -> None:
        if progress_callback is None:
            return
        waiting_payload = dict(record.waiting_payload or {})
        turn = AIActionTurnResult(
            handled=True,
            response_text=str(waiting_payload.get("response_text") or ""),
            message_extra={"ai_action": self._extra(record)},
        )
        try:
            result = progress_callback(turn)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception("AI action turn progress callback failed")

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
        resource_estimate: dict[str, int] | None = None,
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
                "resource_estimate": dict(resource_estimate or {}),
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


def _plan_json_with_cancelled_event(plan_json: dict[str, Any], *, plan_id: str) -> dict[str, Any]:
    payload = dict(plan_json or {})
    events = _safe_action_events(payload)
    if not any(str(event.get("type") or "") == "plan_cancelled" for event in events):
        events.append(
            AIActionEvent(
                step_id="",
                action="plan",
                state="cancelled",
                event_type="plan_cancelled",
                plan_id=plan_id,
            ).to_dict()
        )
    payload["events"] = events[-20:]
    return payload


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


def parse_candidate_selection_json(
    raw: str,
    *,
    registered_action_names: Sequence[str] | None = None,
) -> AIActionCandidateSelection | None:
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
    allowed = set(_normalize_registered_action_names(registered_action_names))
    candidates: list[str] = []
    for raw_name in list(data.get("candidate_actions") or []):
        name = str(raw_name or "").strip()
        if not name or name in candidates:
            continue
        if allowed and name not in allowed:
            continue
        candidates.append(name)
    is_action = bool(data.get("is_action"))
    if is_action and not candidates:
        return None
    return AIActionCandidateSelection(
        is_action=is_action,
        goal=str(data.get("goal") or ""),
        candidate_actions=tuple(candidates) if is_action else (),
        reason=str(data.get("reason") or ""),
    )


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
