"""Resource limits for AI action plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from client.managers.ai_action_types import AIActionPlan


@dataclass(frozen=True, slots=True)
class ResourceCheckResult:
    allowed: bool
    reason: str = ""
    response_text: str = ""


class AIResourceManager:
    """Apply plan-level resource limits before execution."""

    MAX_STEPS_PER_PLAN = 20
    MAX_CONTACTS_PER_PLAN = 5
    MAX_WRITE_ACTIONS_PER_PLAN = 1

    def check_plan(self, plan: AIActionPlan) -> ResourceCheckResult:
        steps = list(plan.steps or [])
        if len(steps) > self.MAX_STEPS_PER_PLAN:
            return ResourceCheckResult(
                allowed=False,
                reason="too_many_steps",
                response_text="这个操作步骤太多，请缩小范围后分批执行。",
            )
        contact_count = self._count_contact_queries(plan)
        if contact_count > self.MAX_CONTACTS_PER_PLAN:
            return ResourceCheckResult(
                allowed=False,
                reason="too_many_contacts",
                response_text="一次最多处理 5 个联系人或对象，请缩小范围后再试。",
            )
        write_count = sum(1 for step in steps if str(step.action or "").strip() in {"message.send", "friend.add", "moment.publish"})
        if write_count > self.MAX_WRITE_ACTIONS_PER_PLAN:
            return ResourceCheckResult(
                allowed=False,
                reason="too_many_write_actions",
                response_text="一次只能确认一个会产生外部影响的操作，请分开执行。",
            )
        return ResourceCheckResult(allowed=True)

    @staticmethod
    def _count_contact_queries(plan: AIActionPlan) -> int:
        total = 0
        for step in plan.steps:
            if step.action != "contact.resolve":
                continue
            queries = step.args.get("queries")
            if isinstance(queries, list):
                total += len([item for item in queries if str(item or "").strip()])
        return total
