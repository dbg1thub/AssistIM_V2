"""Resource limits for AI action plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from client.managers.ai_action_types import AIActionPlan


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    max_steps_per_plan: int = 20
    max_contacts_per_plan: int = 5
    max_write_actions_per_plan: int = 1
    max_total_model_calls: int = 3
    max_memory_results: int = 80
    max_total_input_tokens: int = 8192
    max_total_output_tokens: int = 4096


@dataclass(frozen=True, slots=True)
class ResourceCheckResult:
    allowed: bool
    reason: str = ""
    response_text: str = ""
    estimate: dict[str, int] = field(default_factory=dict)


class AIResourceManager:
    """Apply plan-level resource limits before execution."""

    DEFAULT_BUDGET = ResourceBudget()

    def __init__(self, *, registry: Any | None = None, budget: ResourceBudget | None = None) -> None:
        self._registry = registry
        self._budget = budget or self.DEFAULT_BUDGET

    def check_plan(self, plan: AIActionPlan) -> ResourceCheckResult:
        steps = list(plan.steps or [])
        estimate = self.estimate_plan(plan)
        if estimate["steps"] > self._budget.max_steps_per_plan:
            return ResourceCheckResult(
                allowed=False,
                reason="too_many_steps",
                response_text="这个操作步骤太多，请缩小范围后分批执行。",
                estimate=estimate,
            )
        if estimate["contacts"] > self._budget.max_contacts_per_plan:
            return ResourceCheckResult(
                allowed=False,
                reason="too_many_contacts",
                response_text="一次最多处理 5 个联系人或对象，请缩小范围后再试。",
                estimate=estimate,
            )
        if estimate["write_actions"] > self._budget.max_write_actions_per_plan:
            return ResourceCheckResult(
                allowed=False,
                reason="too_many_write_actions",
                response_text="一次只能确认一个会产生外部影响的操作，请分开执行。",
                estimate=estimate,
            )
        if estimate["model_calls"] > self._budget.max_total_model_calls:
            return ResourceCheckResult(
                allowed=False,
                reason="too_many_model_calls",
                response_text="这个操作预计模型调用次数过多，请缩小问题范围后再试。",
                estimate=estimate,
            )
        if estimate["memory_results"] > self._budget.max_memory_results:
            return ResourceCheckResult(
                allowed=False,
                reason="too_many_memory_results",
                response_text="这个操作预计会读取过多检索结果，请缩小联系人、时间范围或关键词后再试。",
                estimate=estimate,
            )
        if estimate["input_tokens"] > self._budget.max_total_input_tokens:
            return ResourceCheckResult(
                allowed=False,
                reason="too_many_input_tokens",
                response_text="这个操作预计需要读取过多上下文，请缩小联系人、时间范围或关键词后再试。",
                estimate=estimate,
            )
        if estimate["output_tokens"] > self._budget.max_total_output_tokens:
            return ResourceCheckResult(
                allowed=False,
                reason="too_many_output_tokens",
                response_text="这个操作预计会生成过长结果，请缩小问题范围或要求更简短。",
                estimate=estimate,
            )
        return ResourceCheckResult(allowed=True, estimate=estimate)

    def estimate_plan(self, plan: AIActionPlan) -> dict[str, int]:
        steps = list(plan.steps or [])
        estimate = {
            "steps": len(steps),
            "contacts": 0,
            "write_actions": 0,
            "model_calls": 0,
            "memory_results": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
        for step in plan.steps:
            spec = self._spec_for(step.action)
            if spec is None:
                continue
            if str(getattr(spec, "kind", "") or "").strip() == "write" or bool(getattr(spec, "allow_side_effect", False)):
                estimate["write_actions"] += 1
            estimate["contacts"] += self._target_count_for_step(step.args, spec)
            estimate["model_calls"] += max(0, int(getattr(spec, "model_call_cost", 0) or 0))
            estimate["input_tokens"] += max(0, int(getattr(spec, "estimated_input_tokens", 0) or 0))
            estimate["output_tokens"] += max(0, int(getattr(spec, "estimated_output_tokens", 0) or 0))
            if str(getattr(spec, "result_budget_kind", "") or "").strip() == "memory":
                estimate["memory_results"] += self._result_limit_for_step(step.args, spec)
        return estimate

    def _spec_for(self, action: str) -> Any | None:
        get = getattr(self._registry, "get", None)
        if not callable(get):
            return None
        return get(str(action or "").strip())

    @staticmethod
    def _target_count_for_step(args: dict[str, Any], spec: Any) -> int:
        total = 0
        for key in tuple(getattr(spec, "target_arg_names", ()) or ()):
            value = args.get(str(key or ""))
            if isinstance(value, list):
                total += len([item for item in value if str(item or "").strip()])
            elif isinstance(value, tuple):
                total += len([item for item in value if str(item or "").strip()])
            elif str(value or "").strip():
                total += 1
        return total

    @staticmethod
    def _result_limit_for_step(args: dict[str, Any], spec: Any) -> int:
        requested = 0
        for key in tuple(getattr(spec, "result_limit_arg_names", ()) or ()):
            try:
                requested = int(args.get(str(key or "")) or 0)
            except (TypeError, ValueError):
                requested = 0
            if requested > 0:
                break
        if requested <= 0:
            requested = int(getattr(spec, "default_result_limit", 0) or 0)
        max_items = getattr(spec, "max_result_items", None)
        if max_items is not None:
            try:
                requested = min(requested, int(max_items))
            except (TypeError, ValueError):
                pass
        return max(0, requested)
