"""Shared types for AI assistant action planning and execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal


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
    """Planner output.

    The legacy single-action fields are intentionally kept because older tests
    and callers can still construct this object directly. Normalization is the
    compatibility boundary that converts those fields into atomic steps.
    """

    is_action: bool
    goal: str = ""
    risk: RiskLevel = "low"
    steps: tuple[AIActionStep, ...] = ()
    final: dict[str, Any] = field(default_factory=dict)
    action: str = ""
    requires_app_data: bool = False
    requires_side_effect: bool = False
    slots: dict[str, Any] = field(default_factory=dict)
    missing_slots: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "is_action": bool(self.is_action),
            "goal": self.goal,
            "risk": self.risk,
            "steps": [step.to_dict() for step in self.steps],
            "final": dict(self.final or {}),
        }
        if self.action:
            payload["action"] = self.action
        if self.requires_app_data:
            payload["requires_app_data"] = True
        if self.requires_side_effect:
            payload["requires_side_effect"] = True
        if self.slots:
            payload["slots"] = dict(self.slots)
        if self.missing_slots:
            payload["missing_slots"] = list(self.missing_slots)
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
            action=str(payload.get("action") or "").strip(),
            requires_app_data=bool(payload.get("requires_app_data")),
            requires_side_effect=bool(payload.get("requires_side_effect")),
            slots=dict(payload.get("slots") or {}) if isinstance(payload.get("slots"), dict) else {},
            missing_slots=tuple(
                str(item or "").strip()
                for item in list(payload.get("missing_slots") or [])
                if str(item or "").strip()
            ),
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


@dataclass(frozen=True, slots=True)
class AIActionEvent:
    """Small, UI-safe execution event."""

    step_id: str
    action: str
    state: str
    message: str = ""
    result_count: int = 0
    error_code: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "step_id": self.step_id,
            "action": self.action,
            "state": self.state,
            "message": self.message,
        }
        if self.result_count:
            payload["result_count"] = self.result_count
        if self.error_code:
            payload["error_code"] = self.error_code
        return payload
