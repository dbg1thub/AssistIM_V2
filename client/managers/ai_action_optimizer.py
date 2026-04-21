"""Safe optimizer for AI action plans."""

from __future__ import annotations

import json
from typing import Any

from client.managers.ai_action_types import AIActionPlan, AIActionStep


MERGEABLE_ACTIONS = {"contact.resolve"}
ROOT_ACTIONS = {"message.send", "friend.add", "moment.publish", "user.confirm"}


class AIPlanOptimizer:
    """Apply small deterministic optimizations that do not change intent."""

    def optimize(self, plan: AIActionPlan) -> tuple[AIActionPlan, str]:
        if not plan.is_action or not plan.steps:
            return plan, ""
        steps = list(plan.steps)
        final = dict(plan.final or {})
        reasons: list[str] = []

        steps, final, merged_reason = self._merge_duplicate_read_steps(steps, final)
        if merged_reason:
            reasons.append(merged_reason)

        steps, normalized_depends = self._normalize_depends(steps)
        if normalized_depends:
            reasons.append("optimizer_normalize_depends")

        steps, removed_unreachable = self._remove_unreachable_read_steps(steps, final)
        if removed_unreachable:
            reasons.append("optimizer_remove_unreachable_read_steps")

        if tuple(steps) == plan.steps and final == dict(plan.final or {}):
            return plan, ""
        return (
            AIActionPlan(
                is_action=plan.is_action,
                goal=plan.goal,
                risk=plan.risk,
                steps=tuple(steps),
                final=final,
                action=plan.action,
                requires_app_data=plan.requires_app_data,
                requires_side_effect=plan.requires_side_effect,
                slots=dict(plan.slots or {}),
                missing_slots=plan.missing_slots,
            ),
            "+".join(dict.fromkeys(reasons)) or "optimizer_safe",
        )

    @staticmethod
    def _merge_duplicate_read_steps(steps: list[AIActionStep], final: dict[str, Any]) -> tuple[list[AIActionStep], dict[str, Any], str]:
        seen: dict[tuple[str, str, tuple[str, ...]], str] = {}
        replacements: dict[str, str] = {}
        output: list[AIActionStep] = []
        merged_actions: set[str] = set()
        for step in steps:
            current = _replace_step_refs(step, replacements)
            if current.action not in MERGEABLE_ACTIONS:
                output.append(current)
                continue
            key = (current.action, _stable_json(current.args), _dedupe_depends(current.depends_on, current.id))
            if key in seen:
                replacements[current.id] = seen[key]
                merged_actions.add(current.action)
                continue
            seen[key] = current.id
            output.append(current)
        if not replacements:
            return steps, final, ""
        output = [_replace_step_refs(step, replacements) for step in output]
        final = _replace_value_refs(final, replacements)
        reasons = []
        if "contact.resolve" in merged_actions:
            reasons.append("optimizer_merge_duplicate_contact_resolve")
        return output, final, "+".join(reasons)

    @staticmethod
    def _normalize_depends(steps: list[AIActionStep]) -> tuple[list[AIActionStep], bool]:
        changed = False
        output: list[AIActionStep] = []
        for step in steps:
            depends = _dedupe_depends(step.depends_on, step.id)
            if depends != step.depends_on:
                changed = True
            output.append(
                AIActionStep(
                    id=step.id,
                    action=step.action,
                    depends_on=depends,
                    args=dict(step.args or {}),
                    display_text=step.display_text,
                    explanation=step.explanation,
                    fallback=step.fallback,
                )
            )
        return output, changed

    @staticmethod
    def _remove_unreachable_read_steps(steps: list[AIActionStep], final: dict[str, Any]) -> tuple[list[AIActionStep], bool]:
        root_ids = _refs_in_value(final)
        root_ids.update(step.id for step in steps if step.action in ROOT_ACTIONS)
        if not root_ids:
            return steps, False

        by_id = {step.id: step for step in steps}
        needed: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in needed:
                return
            step = by_id.get(step_id)
            if step is None:
                return
            needed.add(step_id)
            for dep in step.depends_on:
                visit(dep)
            for ref in _refs_in_value(step.args):
                visit(ref)

        for root_id in root_ids:
            visit(root_id)

        if not needed:
            return steps, False
        output = [step for step in steps if step.id in needed or step.action in ROOT_ACTIONS]
        return output, len(output) != len(steps)


def _replace_step_refs(step: AIActionStep, replacements: dict[str, str]) -> AIActionStep:
    if not replacements:
        return step
    depends = tuple(dict.fromkeys(replacements.get(item, item) for item in step.depends_on))
    return AIActionStep(
        id=step.id,
        action=step.action,
        depends_on=depends,
        args=_replace_value_refs(dict(step.args or {}), replacements),
        display_text=step.display_text,
        explanation=step.explanation,
        fallback=_replace_value_refs(step.fallback, replacements) if step.fallback else None,
    )


def _replace_value_refs(value: Any, replacements: dict[str, str]) -> Any:
    if not replacements:
        return value
    if isinstance(value, str):
        return _replace_ref_string(value, replacements)
    if isinstance(value, list):
        return [_replace_value_refs(item, replacements) for item in value]
    if isinstance(value, tuple):
        return tuple(_replace_value_refs(item, replacements) for item in value)
    if isinstance(value, dict):
        return {key: _replace_value_refs(item, replacements) for key, item in value.items()}
    return value


def _replace_ref_string(value: str, replacements: dict[str, str]) -> str:
    if not value.startswith("$"):
        return value
    step_id, suffix = _split_ref(value)
    replacement = replacements.get(step_id)
    if not replacement:
        return value
    return f"${replacement}{suffix}"


def _refs_in_value(value: Any) -> set[str]:
    if isinstance(value, str):
        if not value.startswith("$"):
            return set()
        step_id, _suffix = _split_ref(value)
        return {step_id} if step_id else set()
    if isinstance(value, list | tuple):
        refs: set[str] = set()
        for item in value:
            refs.update(_refs_in_value(item))
        return refs
    if isinstance(value, dict):
        refs: set[str] = set()
        for item in value.values():
            refs.update(_refs_in_value(item))
        return refs
    return set()


def _split_ref(value: str) -> tuple[str, str]:
    body = str(value or "")[1:]
    indexes = [index for index in (body.find("."), body.find("[")) if index >= 0]
    split_at = min(indexes) if indexes else len(body)
    return body[:split_at], body[split_at:]


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _dedupe_depends(depends: tuple[str, ...], step_id: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            dep
            for dep in (str(item or "").strip() for item in depends)
            if dep and dep != step_id
        )
    )
