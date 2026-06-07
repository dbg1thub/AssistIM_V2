"""Shared types for the AI skill layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel

from client.managers.ai_action_types import AIActionPlan, RiskLevel


SkillIntentType = Literal["skill", "unsupported", "clarification"]
SkillCompileResultType = Literal["plan", "unsupported", "clarification"]
SkillConfidence = Literal["low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class SkillIntent:
    """Model-facing skill intent before deterministic action-plan compilation."""

    type: SkillIntentType
    skill: str = ""
    goal: str = ""
    slots: dict[str, Any] = field(default_factory=dict)
    confidence: SkillConfidence = "medium"
    reason: str = ""
    control: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SkillSpec:
    """One stable semantic skill exposed to the model-facing skill parser."""

    id: str
    description: str
    input_model: type[BaseModel]
    risk_level: RiskLevel
    requires_confirmation: bool
    compiler: Callable[[SkillIntent, BaseModel], AIActionPlan]
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class SkillCompileResult:
    """Output from compiling a skill intent into an existing AIActionPlan."""

    type: SkillCompileResultType
    plan: AIActionPlan | None = None
    skill: str = ""
    reason: str = ""
    missing_slots: tuple[str, ...] = ()
    question: str = ""

    @classmethod
    def plan_result(cls, skill: str, plan: AIActionPlan) -> "SkillCompileResult":
        return cls(type="plan", skill=str(skill or "").strip(), plan=plan)

    @classmethod
    def unsupported(cls, skill: str, reason: str) -> "SkillCompileResult":
        return cls(type="unsupported", skill=str(skill or "").strip(), reason=str(reason or "").strip())

    @classmethod
    def clarification(
        cls,
        skill: str,
        *,
        missing_slots: tuple[str, ...],
        question: str = "",
        reason: str = "",
    ) -> "SkillCompileResult":
        return cls(
            type="clarification",
            skill=str(skill or "").strip(),
            missing_slots=tuple(str(item or "").strip() for item in missing_slots if str(item or "").strip()),
            question=str(question or "").strip(),
            reason=str(reason or "").strip(),
        )
