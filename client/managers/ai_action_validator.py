"""Structural validation for AI assistant action plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from client.managers.ai_action_registry import AtomicActionRegistry
from client.managers.ai_action_types import AIActionPlan, AIActionStep


VALID_PARTICIPANT_MATCHES = {"any", "all", "direct_only", "group_only"}
VALID_RISKS = {"low", "medium", "high"}


@dataclass(frozen=True, slots=True)
class AIPlanValidationError:
    code: str
    message: str
    step_id: str = ""
    action: str = ""
    field: str = ""

    def to_repair_text(self) -> str:
        parts = [self.code]
        if self.step_id:
            parts.append(f"step={self.step_id}")
        if self.action:
            parts.append(f"action={self.action}")
        if self.field:
            parts.append(f"field={self.field}")
        parts.append(self.message)
        return ": ".join(parts)


@dataclass(frozen=True, slots=True)
class AIPlanValidationResult:
    errors: tuple[AIPlanValidationError, ...] = ()

    @property
    def allowed(self) -> bool:
        return not self.errors

    def repair_messages(self) -> tuple[str, ...]:
        return tuple(error.to_repair_text() for error in self.errors)

    def repair_instructions(self) -> str:
        return "\n".join(self.repair_messages())


class AIPlanValidator:
    """Validate executable plan structure before persistence or execution."""

    def __init__(self, *, registry: AtomicActionRegistry) -> None:
        self._registry = registry

    def validate(self, plan: AIActionPlan) -> AIPlanValidationResult:
        if not plan.is_action or not plan.steps:
            return AIPlanValidationResult()

        errors: list[AIPlanValidationError] = []
        if str(plan.risk or "low").strip().lower() not in VALID_RISKS:
            errors.append(_error("PLAN_SCHEMA_INVALID", "risk must be low, medium, or high", field="risk"))

        seen_ids: set[str] = set()
        for index, step in enumerate(plan.steps, start=1):
            step_id = str(step.id or "").strip()
            action = str(step.action or "").strip()
            if not step_id:
                errors.append(_error("PLAN_SCHEMA_INVALID", "step id is required", step=step, field="id"))
                step_id = f"step_{index}"
            if step_id in seen_ids:
                errors.append(_error("PLAN_SCHEMA_INVALID", "step id must be unique", step=step, field="id"))
            if not action or self._registry.get(action) is None:
                errors.append(_error("ACTION_NOT_FOUND", "action is not registered", step=step, field="action"))

            depends_on = tuple(str(dep or "").strip() for dep in step.depends_on if str(dep or "").strip())
            for dep in depends_on:
                if dep not in seen_ids:
                    errors.append(
                        _error(
                            "ARG_REFERENCE_INVALID",
                            f"depends_on references unavailable step {dep}",
                            step=step,
                            field="depends_on",
                        )
                    )
            for ref in _ref_roots(step.args):
                if ref not in seen_ids:
                    errors.append(
                        _error(
                            "ARG_REFERENCE_INVALID",
                            f"args reference unavailable step {ref}",
                            step=step,
                            field="args",
                        )
                    )
            errors.extend(_validate_step_args(step, self._registry))
            seen_ids.add(step_id)

        for ref in _ref_roots(plan.final):
            if ref not in seen_ids:
                errors.append(
                    AIPlanValidationError(
                        code="ARG_REFERENCE_INVALID",
                        message=f"final references unavailable step {ref}",
                        field="final",
                    )
                )
        return AIPlanValidationResult(errors=tuple(errors))


def _validate_step_args(step: AIActionStep, registry: AtomicActionRegistry) -> list[AIPlanValidationError]:
    action = str(step.action or "").strip()
    args = dict(step.args or {})
    errors: list[AIPlanValidationError] = []

    if action == "contact.resolve":
        queries = args.get("queries")
        if not isinstance(queries, list) or not any(str(item or "").strip() for item in queries):
            errors.append(_error("ARG_SCHEMA_INVALID", "contact.resolve requires non-empty queries list", step=step, field="queries"))
        if "allow_multiple" in args and not isinstance(args.get("allow_multiple"), bool):
            errors.append(_error("ARG_SCHEMA_INVALID", "allow_multiple must be boolean", step=step, field="allow_multiple"))

    elif action == "memory.search":
        participant_match = str(args.get("participant_match") or "any").strip().lower() or "any"
        if participant_match not in VALID_PARTICIPANT_MATCHES:
            errors.append(
                _error(
                    "ARG_SCHEMA_INVALID",
                    "participant_match must be one of any, all, direct_only, group_only",
                    step=step,
                    field="participant_match",
                )
            )
        if "time_scope" in args and not isinstance(args.get("time_scope"), dict):
            errors.append(_error("ARG_SCHEMA_INVALID", "time_scope must be an object", step=step, field="time_scope"))
        if "keywords" in args and not isinstance(args.get("keywords"), list):
            errors.append(_error("ARG_SCHEMA_INVALID", "keywords must be a list", step=step, field="keywords"))
        if "question" in args and not isinstance(args.get("question"), str):
            errors.append(_error("ARG_SCHEMA_INVALID", "question must be a string", step=step, field="question"))

    elif action == "memory.summarize":
        if not _has_value(args.get("source")):
            errors.append(_error("ARG_SCHEMA_INVALID", "memory.summarize requires source", step=step, field="source"))
        if "question" in args and not isinstance(args.get("question"), str):
            errors.append(_error("ARG_SCHEMA_INVALID", "question must be a string", step=step, field="question"))

    elif action == "message.draft":
        if not _has_value(args.get("target")):
            errors.append(_error("ARG_SCHEMA_INVALID", "message.draft requires target", step=step, field="target"))
        if not _has_value(args.get("content")):
            errors.append(_error("ARG_SCHEMA_INVALID", "message.draft requires content", step=step, field="content"))

    elif action == "user.confirm":
        preview = args.get("preview")
        if not isinstance(preview, dict):
            errors.append(_error("ARG_SCHEMA_INVALID", "user.confirm requires preview object", step=step, field="preview"))
        risk = str(args.get("risk") or "high").strip().lower() or "high"
        if risk not in VALID_RISKS:
            errors.append(_error("ARG_SCHEMA_INVALID", "risk must be low, medium, or high", step=step, field="risk"))

    elif action == "message.send":
        spec = registry.get(action)
        if not _has_value(args.get("target")):
            errors.append(_error("ARG_SCHEMA_INVALID", "message.send requires target", step=step, field="target"))
        if not _has_value(args.get("content")):
            errors.append(_error("ARG_SCHEMA_INVALID", "message.send requires content", step=step, field="content"))
        if not _has_value(args.get("idempotency_key")):
            errors.append(_error("ARG_SCHEMA_INVALID", "message.send requires idempotency_key", step=step, field="idempotency_key"))
        if spec is not None and spec.require_preview and not _has_value(args.get("preview")):
            errors.append(_error("ARG_SCHEMA_INVALID", "message.send requires preview", step=step, field="preview"))

    return errors


def _ref_roots(value: Any) -> set[str]:
    if isinstance(value, str):
        if not value.startswith("$"):
            return set()
        body = value[1:]
        stops = [index for index in (body.find("."), body.find("[")) if index >= 0]
        split_at = min(stops) if stops else len(body)
        root = body[:split_at]
        return {root} if root else {""}
    if isinstance(value, list | tuple):
        roots: set[str] = set()
        for item in value:
            roots.update(_ref_roots(item))
        return roots
    if isinstance(value, dict):
        roots: set[str] = set()
        for item in value.values():
            roots.update(_ref_roots(item))
        return roots
    return set()


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list | tuple | dict):
        return bool(value)
    return True


def _error(code: str, message: str, *, step: AIActionStep | None = None, field: str = "") -> AIPlanValidationError:
    return AIPlanValidationError(
        code=code,
        message=message,
        step_id=str(getattr(step, "id", "") or "").strip(),
        action=str(getattr(step, "action", "") or "").strip(),
        field=field,
    )
