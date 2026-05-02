"""Safe optimizer for AI action plans."""

from __future__ import annotations

import json
from typing import Any

from client.managers.ai_action_registry import SERVER_READ_ACTION_ROUTES, SERVER_WRITE_ACTION_ROUTES
from client.managers.ai_action_types import AIActionPlan, AIActionStep


MERGEABLE_ACTIONS = {"contact.resolve", "memory.search", "memory.summarize", *SERVER_READ_ACTION_ROUTES.keys()}
ROOT_ACTIONS = {"message.send", "friend.add", "moment.publish", "user.confirm", *SERVER_WRITE_ACTION_ROUTES.keys()}


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
                control=dict(plan.control or {}),
            ),
            "+".join(dict.fromkeys(reasons)) or "optimizer_safe",
        )

    @staticmethod
    def _merge_duplicate_read_steps(steps: list[AIActionStep], final: dict[str, Any]) -> tuple[list[AIActionStep], dict[str, Any], str]:
        seen: dict[tuple[str, str, tuple[str, ...]], str] = {}
        seen_by_args: dict[tuple[str, str], str] = {}
        output_by_id: dict[str, AIActionStep] = {}
        replacements: dict[str, str] = {}
        output: list[AIActionStep] = []
        merged_actions: set[str] = set()
        for step in steps:
            current = _replace_step_refs(step, replacements)
            if current.action not in MERGEABLE_ACTIONS:
                output.append(current)
                output_by_id[current.id] = current
                continue
            key = (current.action, _stable_json(current.args), _dedupe_depends(current.depends_on, current.id))
            args_key = (current.action, _stable_json(current.args))
            replacement_id = seen.get(key)
            if replacement_id is None:
                candidate_id = seen_by_args.get(args_key)
                if (
                    current.action in SERVER_READ_ACTION_ROUTES
                    and candidate_id
                    and _depends_only_on_duplicate_chain(current.depends_on, candidate_id, output_by_id)
                ):
                    replacement_id = candidate_id
            if replacement_id:
                replacements[current.id] = replacement_id
                merged_actions.add(current.action)
                continue
            seen[key] = current.id
            seen_by_args.setdefault(args_key, current.id)
            output.append(current)
            output_by_id[current.id] = current
        if not replacements:
            return steps, final, ""
        output = [_replace_step_refs(step, replacements) for step in output]
        final = _replace_value_refs(final, replacements)
        reasons = [
            f"optimizer_merge_duplicate_{action.replace('.', '_')}"
            for action in sorted(merged_actions)
        ]
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


def _depends_only_on_duplicate_chain(
    depends_on: tuple[str, ...],
    duplicate_id: str,
    output_by_id: dict[str, AIActionStep],
) -> bool:
    depends = set(_dedupe_depends(depends_on, ""))
    if not depends:
        return False
    duplicate = output_by_id.get(duplicate_id)
    if duplicate is None:
        return False
    allowed = {duplicate_id, *duplicate.depends_on}
    return depends.issubset(allowed)


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
