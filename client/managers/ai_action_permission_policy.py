"""Permission policy boundary for AI action execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from client.managers.ai_action_types import AtomicActionSpec


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    code: str = ""
    message: str = ""


class AIPermissionPolicy:
    """Central permission hook for action execution.

    The first implementation is intentionally conservative but permissive for
    local read-only actions. The boundary exists so contact/group/E2EE scopes
    can be enforced without spreading permission checks into action handlers.
    """

    def check_step(
        self,
        *,
        spec: AtomicActionSpec,
        args: dict[str, Any],
        plan_context: dict[str, Any] | None = None,
    ) -> PermissionDecision:
        del args, plan_context
        if spec.kind == "write" and not spec.allow_side_effect and spec.name != "message.send":
            return PermissionDecision(False, "PERMISSION_DENIED", "这个操作当前不允许产生外部影响。")
        return PermissionDecision(True)
