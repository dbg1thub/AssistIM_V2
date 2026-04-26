"""Shared types for AI assistant action planning and execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Literal


CONFIRMATION_PREVIEW_FINGERPRINT_VERSION = "confirmation_preview:v1"


def confirmation_preview_fingerprint(preview: Any, *, risk: Any) -> str:
    normalized_preview = dict(preview or {}) if isinstance(preview, dict) else {}
    payload = {
        "version": CONFIRMATION_PREVIEW_FINGERPRINT_VERSION,
        "risk": str(risk or "").strip() or "high",
        "preview": normalized_preview,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
        return payload
