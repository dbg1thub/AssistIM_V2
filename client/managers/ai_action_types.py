"""Shared types for AI assistant action planning and execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Literal


CONFIRMATION_PREVIEW_FINGERPRINT_VERSION = "confirmation_preview:v1"
STEP_OUTPUTS_META_KEY = "_meta"


def confirmation_preview_fingerprint(preview: Any, *, risk: Any) -> str:
    normalized_preview = dict(preview or {}) if isinstance(preview, dict) else {}
    payload = {
        "version": CONFIRMATION_PREVIEW_FINGERPRINT_VERSION,
        "risk": str(risk or "").strip() or "high",
        "preview": normalized_preview,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def current_plan_step_outputs(
    outputs: dict[str, Any],
    *,
    step_ids: set[str],
    plan_version: Any,
) -> dict[str, Any]:
    version = _coerce_plan_version(plan_version)
    raw_versions = _step_output_versions(outputs)
    current: dict[str, Any] = {}
    current_versions: dict[str, int] = {}
    for step_id in step_ids:
        if step_id not in outputs:
            continue
        if _coerce_plan_version(raw_versions.get(step_id)) != version:
            continue
        current[step_id] = outputs[step_id]
        current_versions[step_id] = version
    if current_versions:
        current[STEP_OUTPUTS_META_KEY] = {
            "plan_version": version,
            "step_versions": current_versions,
        }
    return current


def mark_step_output_current(outputs: dict[str, Any], *, step_id: str, plan_version: Any) -> None:
    normalized_step_id = str(step_id or "").strip()
    if not normalized_step_id:
        return
    version = _coerce_plan_version(plan_version)
    meta = dict(outputs.get(STEP_OUTPUTS_META_KEY) or {}) if isinstance(outputs.get(STEP_OUTPUTS_META_KEY), dict) else {}
    versions = dict(meta.get("step_versions") or {}) if isinstance(meta.get("step_versions"), dict) else {}
    versions[normalized_step_id] = version
    meta["plan_version"] = version
    meta["step_versions"] = versions
    outputs[STEP_OUTPUTS_META_KEY] = meta


def _step_output_versions(outputs: dict[str, Any]) -> dict[str, Any]:
    meta = outputs.get(STEP_OUTPUTS_META_KEY) if isinstance(outputs, dict) else None
    if not isinstance(meta, dict):
        return {}
    versions = meta.get("step_versions")
    return dict(versions or {}) if isinstance(versions, dict) else {}


def _coerce_plan_version(value: Any) -> int:
    try:
        return max(1, int(value or 1))
    except (TypeError, ValueError):
        return 1


PlanState = Literal[
    "running",
    "waiting_clarification",
    "waiting_confirmation",
    "done",
    "failed",
    "cancelled",
]
ActionKind = Literal["read", "write"]
RiskLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class AIActionStep:
    """One atomic step in a model-generated action plan."""

    id: str
    action: str
    depends_on: tuple[str, ...] = ()
    args: dict[str, Any] = field(default_factory=dict)
    display_text: str = ""
    explanation: str = ""
    fallback: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "action": self.action,
            "depends_on": list(self.depends_on),
            "args": dict(self.args or {}),
        }
        if self.display_text:
            payload["display_text"] = self.display_text
        if self.explanation:
            payload["explanation"] = self.explanation
        if self.fallback:
            payload["fallback"] = dict(self.fallback)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AIActionStep":
        return cls(
            id=str(payload.get("id") or "").strip(),
            action=str(payload.get("action") or "").strip(),
            depends_on=tuple(
                str(item or "").strip()
                for item in list(payload.get("depends_on") or [])
                if str(item or "").strip()
            ),
            args=dict(payload.get("args") or {}) if isinstance(payload.get("args"), dict) else {},
            display_text=str(payload.get("display_text") or ""),
            explanation=str(payload.get("explanation") or ""),
            fallback=dict(payload.get("fallback") or {}) if isinstance(payload.get("fallback"), dict) else None,
        )


@dataclass(frozen=True, slots=True)
class AIActionPlan:
    """Planner output based on atomic steps or an explicit pending control."""

    is_action: bool
    goal: str = ""
    risk: RiskLevel = "low"
    steps: tuple[AIActionStep, ...] = ()
    final: dict[str, Any] = field(default_factory=dict)
    control: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "is_action": bool(self.is_action),
            "goal": self.goal,
            "risk": self.risk,
            "steps": [step.to_dict() for step in self.steps],
            "final": dict(self.final or {}),
        }
        if self.control:
            payload["control"] = dict(self.control)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AIActionPlan":
        raw_steps = payload.get("steps")
        steps = tuple(
            AIActionStep.from_dict(dict(item))
            for item in list(raw_steps or [])
            if isinstance(item, dict)
        )
        risk = str(payload.get("risk") or "low").strip().lower()
        if risk not in {"low", "medium", "high"}:
            risk = "low"
        return cls(
            is_action=bool(payload.get("is_action", True if steps else False)),
            goal=str(payload.get("goal") or ""),
            risk=risk,  # type: ignore[arg-type]
            steps=steps,
            final=dict(payload.get("final") or {}) if isinstance(payload.get("final"), dict) else {},
            control=dict(payload.get("control") or {}) if isinstance(payload.get("control"), dict) else {},
        )


@dataclass(frozen=True, slots=True)
class AIActionTurnResult:
    """Decision for one user turn in the AI assistant."""

    handled: bool
    response_text: str = ""
    memory_context_lines: tuple[str, ...] = ()
    message_extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AtomicActionSpec:
    """Registered atomic action capability and platform guardrails."""

    name: str
    kind: ActionKind
    risk_level: RiskLevel
    handler: Callable[..., Any] | None = None
    input_model: type[Any] | None = None
    output_model: type[Any] | None = None
    enabled: bool = True
    requires_confirmation: bool = False
    max_input_bytes: int = 32768
    max_output_json_bytes: int = 65536
    timeout_ms: int = 15000
    max_retries: int = 0
    max_targets: int | None = None
    allow_batch: bool = False
    require_resolved_target: bool = False
    allow_all_history: bool = True
    allow_cross_session: bool = False
    allow_side_effect: bool = False
    allow_raw_content_return: bool = False
    max_content_chars: int | None = None
    idempotency_required: bool = False
    require_preview: bool = False
    allow_auto_resume_after_confirm: bool = True
    supports_compensation: bool = False
    compensate_action: str | None = None
    model_call_cost: int = 0
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    target_arg_names: tuple[str, ...] = ()
    result_budget_kind: str = ""
    result_limit_arg_names: tuple[str, ...] = ()
    default_result_limit: int = 0
    max_result_items: int | None = None
    prompt_purpose: str = ""
    prompt_notes: tuple[str, ...] = ()
    planner_required_predecessors: tuple[str, ...] = ()
    planner_required_arg_refs: dict[str, tuple[str, ...]] = field(default_factory=dict)
    planner_required_object_args: dict[str, tuple[str, ...]] = field(default_factory=dict)
    planner_required_object_arg_refs: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)
    planner_required_object_arg_contains: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)
    planner_forbidden_literal_args: tuple[str, ...] = ()
    planner_prompt_support_actions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ActionPause:
    """Action execution paused and needs user input."""

    state: PlanState
    payload: dict[str, Any]
    response_text: str


@dataclass(frozen=True, slots=True)
class ActionExecutionResult:
    """Executor result projected to the assistant UI contract."""

    state: PlanState
    response_text: str = ""
    memory_context_lines: tuple[str, ...] = ()
    final_output: dict[str, Any] = field(default_factory=dict)
    error_text: str = ""


class ActionHandlerError(RuntimeError):
    """Stable action error that should be surfaced by the executor unchanged."""

    def __init__(self, error_text: str) -> None:
        self.error_text = str(error_text or "ACTION_FAILED").strip() or "ACTION_FAILED"
        super().__init__(self.error_text)


@dataclass(frozen=True, slots=True)
class AIActionEvent:
    """Small, UI-safe execution event."""

    step_id: str
    action: str
    state: str
    event_type: str = ""
    plan_id: str = ""
    message: str = ""
    result_count: int = 0
    error_code: str = ""
    duration_ms: int = 0
    resource_usage: dict[str, Any] = field(default_factory=dict)
    attempt: int = 0
    max_attempts: int = 0
    retryable: bool | None = None
    resource_limit: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "type": self.event_type or self.state,
            "step_id": self.step_id,
            "action": self.action,
            "state": self.state,
            "message": self.message,
        }
        if self.plan_id:
            payload["plan_id"] = self.plan_id
        if self.result_count:
            payload["result_count"] = self.result_count
        if self.error_code:
            payload["error_code"] = self.error_code
        if self.duration_ms:
            payload["duration_ms"] = self.duration_ms
        usage = _safe_resource_usage(self.resource_usage)
        if usage:
            payload["resource_usage"] = usage
        if self.attempt:
            payload["attempt"] = max(0, int(self.attempt))
        if self.max_attempts:
            payload["max_attempts"] = max(0, int(self.max_attempts))
        if self.retryable is not None:
            payload["retryable"] = bool(self.retryable)
        if self.resource_limit:
            payload["resource_limit"] = str(self.resource_limit)
        return payload


def _safe_resource_usage(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    if not value:
        return {}
    output: dict[str, Any] = {}
    for key in (
        "duration_ms",
        "result_count",
        "output_bytes",
        "model_call_cost",
        "model_tokens",
        "temp_result_bytes",
    ):
        try:
            output[key] = max(0, int(value.get(key) or 0))
        except (TypeError, ValueError):
            output[key] = 0
    output["result_ref"] = bool(value.get("result_ref"))
    return output
