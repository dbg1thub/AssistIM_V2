"""Normalize model action plans into executable atomic steps."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from client.managers.ai_action_types import AIActionPlan, AIActionStep, AtomicActionSpec


DEFAULT_WRITE_ACTION_NAMES = frozenset({"message.send"})


class AIPlanNormalizer:
    """Deterministic cleanup for atomic action plans."""

    def __init__(
        self,
        *,
        write_action_names: Iterable[str] | None = None,
        action_specs: Iterable[AtomicActionSpec] | None = None,
    ) -> None:
        specs = {
            str(spec.name or "").strip(): spec
            for spec in list(action_specs or ())
            if str(getattr(spec, "name", "") or "").strip()
        }
        derived_write_names = {
            name
            for name, spec in specs.items()
            if str(getattr(spec, "kind", "") or "").strip() == "write"
        }
        self._write_action_names = frozenset(
            name
            for name in (write_action_names or (derived_write_names or DEFAULT_WRITE_ACTION_NAMES))
            if str(name or "").strip()
        )
        self._action_specs = specs
        self._last_rejection_reason = ""

    @property
    def last_rejection_reason(self) -> str:
        return self._last_rejection_reason

    def normalize(self, plan: AIActionPlan, *, user_text: str) -> AIActionPlan:
        self._last_rejection_reason = ""
        if not plan.is_action:
            self._last_rejection_reason = "plan_not_action"
            return plan
        if plan.control and not plan.steps:
            return plan
        if plan.steps:
            return self._normalize_atomic_plan(plan, user_text=user_text)
        self._last_rejection_reason = "action_without_steps"
        return AIActionPlan(is_action=False)

    def _normalize_atomic_plan(self, plan: AIActionPlan, *, user_text: str) -> AIActionPlan:
        steps: list[AIActionStep] = []
        seen_ids: set[str] = set()
        for index, step in enumerate(plan.steps, start=1):
            step_id = step.id or _default_step_id(step.action, index)
            if step_id in seen_ids:
                step_id = f"{step_id}_{index}"
            seen_ids.add(step_id)
            steps.append(
                AIActionStep(
                    id=step_id,
                    action=step.action,
                    depends_on=tuple(item for item in step.depends_on if item in seen_ids),
                    args=dict(step.args or {}),
                    display_text=step.display_text or _display_text(step.action),
                    explanation=step.explanation or _explanation(step.action),
                    fallback=step.fallback,
                )
            )
        final = dict(plan.final or {"type": "answer"})
        steps, final = self._canonicalize_unique_action_name_refs(steps, final)
        steps = self._normalize_args_against_input_contracts(steps)
        steps = self._remove_non_executable_final_steps(steps)
        steps = self._ensure_reference_dependencies(steps)
        steps = self._canonicalize_send_chain_refs(steps)
        steps = self._canonicalize_planner_contract_refs(steps)
        steps = self._canonicalize_single_target_send_contact_resolve(steps)
        steps, final = self._ensure_memory_summarize_for_search_answer(steps, final=final, user_text=user_text)
        steps = self._ensure_reference_dependencies(steps)
        steps = self._remove_unreferenced_invalid_read_steps(steps, final=final)
        steps = self._ensure_reference_dependencies(steps)
        steps = self._ensure_write_confirmation(steps)
        if self._has_confirmation_without_write(steps):
            self._last_rejection_reason = "confirmation_without_write"
            return AIActionPlan(is_action=False)
        invalid_reasons = self._invalid_atomic_write_chain_reasons(steps)
        if invalid_reasons:
            self._last_rejection_reason = ",".join(invalid_reasons)
            return AIActionPlan(is_action=False)
        return AIActionPlan(
            is_action=True,
            goal=plan.goal or _clip(user_text, 80),
            risk=_plan_risk(steps, plan.risk, write_action_names=self._write_action_names),
            steps=tuple(steps),
            final=final,
            control=dict(plan.control or {}),
        )

    def _normalize_args_against_input_contracts(self, steps: list[AIActionStep]) -> list[AIActionStep]:
        if not self._action_specs:
            return steps
        output: list[AIActionStep] = []
        for step in steps:
            spec = self._action_specs.get(step.action)
            if spec is None:
                output.append(step)
                continue
            normalized_args = _normalize_args_against_input_model(dict(step.args or {}), spec=spec)
            if normalized_args == dict(step.args or {}):
                output.append(step)
                continue
            output.append(
                AIActionStep(
                    id=step.id,
                    action=step.action,
                    depends_on=step.depends_on,
                    args=normalized_args,
                    display_text=step.display_text,
                    explanation=step.explanation,
                    fallback=step.fallback,
                )
            )
        return output

    def _remove_non_executable_final_steps(self, steps: list[AIActionStep]) -> list[AIActionStep]:
        if len(steps) <= 1:
            return steps
        output = [
            step
            for step in steps
            if not (step.id == "final" and self._spec_kind(step.action) != "write")
        ]
        return output or steps

    def _canonicalize_planner_contract_refs(self, steps: list[AIActionStep]) -> list[AIActionStep]:
        if not self._action_specs:
            return steps
        seen_step_actions: dict[str, str] = {}
        output: list[AIActionStep] = []
        for step in steps:
            spec = self._action_specs.get(step.action)
            args = dict(step.args or {})
            if spec is not None:
                for field_name, expected_refs in spec.planner_required_arg_refs.items():
                    if _value_references_expected_action_field(
                        args.get(field_name),
                        expected_refs,
                        action_specs=self._action_specs,
                        seen_step_actions=seen_step_actions,
                    ):
                        continue
                    replacement = _first_available_expected_ref(
                        expected_refs,
                        action_specs=self._action_specs,
                        seen_step_actions=seen_step_actions,
                        preferred_step_ids=step.depends_on,
                    )
                    if replacement:
                        args[field_name] = replacement
            output.append(
                AIActionStep(
                    id=step.id,
                    action=step.action,
                    depends_on=step.depends_on,
                    args=args,
                    display_text=step.display_text,
                    explanation=step.explanation,
                    fallback=step.fallback,
                )
            )
            seen_step_actions[step.id] = step.action
        return output

    def _remove_unreferenced_invalid_read_steps(self, steps: list[AIActionStep], *, final: dict) -> list[AIActionStep]:
        if len(steps) <= 1 or not self._action_specs:
            return steps
        if any(self._spec_kind(step.action) == "write" for step in steps):
            return steps
        used_ids = set(_refs_in_value(final))
        for step in steps:
            used_ids.update(step.depends_on)
            used_ids.update(_refs_in_value(step.args))
        output: list[AIActionStep] = []
        for step in steps:
            spec = self._action_specs.get(step.action)
            if (
                step.id not in used_ids
                and spec is not None
                and str(spec.kind or "").strip() == "read"
                and _step_has_missing_required_input(step, spec=spec)
            ):
                continue
            output.append(step)
        return output or steps

    def _spec_kind(self, action: str) -> str:
        spec = self._action_specs.get(str(action or "").strip())
        return str(getattr(spec, "kind", "") or "").strip()

    @staticmethod
    def _canonicalize_unique_action_name_refs(
        steps: list[AIActionStep],
        final: dict,
    ) -> tuple[list[AIActionStep], dict]:
        action_step_ids: dict[str, str | None] = {}
        for step in steps:
            action = str(step.action or "").strip()
            if not action:
                continue
            if action in action_step_ids:
                action_step_ids[action] = None
            else:
                action_step_ids[action] = step.id
        replacements = {
            action: step_id
            for action, step_id in action_step_ids.items()
            if action and step_id
        }
        if not replacements:
            return steps, final
        return (
            [
                AIActionStep(
                    id=step.id,
                    action=step.action,
                    depends_on=step.depends_on,
                    args=_replace_unique_action_refs(dict(step.args or {}), replacements),
                    display_text=step.display_text,
                    explanation=step.explanation,
                    fallback=_replace_unique_action_refs(step.fallback, replacements) if step.fallback else None,
                )
                for step in steps
            ],
            _replace_unique_action_refs(final, replacements),
        )

    @staticmethod
    def _ensure_memory_summarize_for_search_answer(
        steps: list[AIActionStep],
        *,
        final: dict,
        user_text: str,
    ) -> tuple[list[AIActionStep], dict]:
        if any(step.action == "memory.summarize" for step in steps):
            return steps, final
        search_steps = [step for step in steps if step.action == "memory.search"]
        if not search_steps:
            return steps, final

        existing_ids = {step.id for step in steps}
        if len(search_steps) == 1:
            search_step = search_steps[0]
            summarize_id = _unique_step_id(f"summarize_{search_step.id}", existing_ids)
            depends_on = (search_step.id,)
            source: object = f"${search_step.id}"
            question = str(search_step.args.get("question") or user_text or "").strip()
        else:
            summarize_id = _unique_step_id("summarize_memory", existing_ids)
            depends_on = tuple(step.id for step in search_steps)
            source = {step.id: f"${step.id}" for step in search_steps}
            question = str(user_text or "").strip()

        summarize_step = AIActionStep(
            id=summarize_id,
            action="memory.summarize",
            depends_on=depends_on,
            args={
                "source": source,
                "question": question,
                "style": "summary",
            },
            display_text=_display_text("memory.summarize"),
            explanation="历史检索结果需要整理成自然语言回答。",
        )
        return [*steps, summarize_step], {"type": "answer", "source": f"${summarize_id}"}

    def _ensure_write_confirmation(self, steps: list[AIActionStep]) -> list[AIActionStep]:
        output: list[AIActionStep] = []
        for step in steps:
            if step.action != "message.send":
                output.append(step)
                continue
            has_confirmation = any(
                prior.action == "user.confirm" and prior.id in set(step.depends_on)
                for prior in output
            )
            if has_confirmation:
                output.append(step)
                continue
            existing_confirm = _latest_complete_send_confirmation(output, send_step=step)
            if existing_confirm is not None:
                output.append(
                    AIActionStep(
                        id=step.id,
                        action=step.action,
                        depends_on=tuple(dict.fromkeys([*step.depends_on, existing_confirm.id])),
                        args=dict(step.args or {}),
                        display_text=step.display_text,
                        explanation=step.explanation,
                        fallback=step.fallback,
                    )
                )
                continue
            confirm_id = f"confirm_{step.id}"
            output.append(
                AIActionStep(
                    id=confirm_id,
                    action="user.confirm",
                    depends_on=step.depends_on,
                    args={
                        "risk": "high",
                        "preview": {
                            "operation": "发送消息",
                            "target": step.args.get("target") or "",
                            "content": step.args.get("content") or "",
                        },
                    },
                    display_text="等待你确认发送...",
                    explanation="发送消息会产生外部影响，必须先确认。",
                )
            )
            output.append(
                AIActionStep(
                    id=step.id,
                    action=step.action,
                    depends_on=tuple(dict.fromkeys([*step.depends_on, confirm_id])),
                    args=dict(step.args or {}),
                    display_text=step.display_text,
                    explanation=step.explanation,
                    fallback=step.fallback,
                )
            )
        return output

    @staticmethod
    def _canonicalize_send_chain_refs(steps: list[AIActionStep]) -> list[AIActionStep]:
        chains = _send_chain_refs(steps)
        if not chains:
            return steps
        confirm_drafts = {
            confirm_id: draft_id
            for draft_id, confirm_id in chains.values()
            if confirm_id
        }
        output: list[AIActionStep] = []
        for step in steps:
            if step.action == "user.confirm" and step.id in confirm_drafts:
                output.append(_canonicalize_confirm_step(step, draft_id=confirm_drafts[step.id]))
                continue
            if step.action == "message.send" and step.id in chains:
                draft_id, confirm_id = chains[step.id]
                output.append(_canonicalize_send_step(step, draft_id=draft_id, confirm_id=confirm_id))
                continue
            output.append(step)
        return output

    @staticmethod
    def _canonicalize_single_target_send_contact_resolve(steps: list[AIActionStep]) -> list[AIActionStep]:
        contact_step_ids = _single_target_send_contact_resolve_ids(steps)
        if not contact_step_ids:
            return steps
        output: list[AIActionStep] = []
        for step in steps:
            if step.action == "contact.resolve" and step.id in contact_step_ids:
                args = dict(step.args or {})
                args["allow_multiple"] = False
                output.append(
                    AIActionStep(
                        id=step.id,
                        action=step.action,
                        depends_on=step.depends_on,
                        args=args,
                        display_text=step.display_text,
                        explanation=step.explanation,
                        fallback=step.fallback,
                    )
                )
                continue
            output.append(step)
        return output

    @staticmethod
    def _ensure_reference_dependencies(steps: list[AIActionStep]) -> list[AIActionStep]:
        output: list[AIActionStep] = []
        seen_ids: set[str] = set()
        for step in steps:
            refs = _refs_in_value(step.args)
            depends = tuple(
                dict.fromkeys(
                    [
                        *step.depends_on,
                        *(ref for ref in refs if ref in seen_ids and ref != step.id),
                    ]
                )
            )
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
            seen_ids.add(step.id)
        return output

    def _has_confirmation_without_write(self, steps: list[AIActionStep]) -> bool:
        write_step_ids = {
            step.id
            for step in steps
            if step.action in self._write_action_names
        }
        if not write_step_ids:
            return any(step.action == "user.confirm" for step in steps)
        for step in steps:
            if step.action != "user.confirm":
                continue
            if not any(step.id in set(candidate.depends_on) for candidate in steps if candidate.id in write_step_ids):
                return True
        return False

    @staticmethod
    def _has_invalid_atomic_write_chain(steps: list[AIActionStep]) -> bool:
        return bool(AIPlanNormalizer._invalid_atomic_write_chain_reasons(steps))

    @staticmethod
    def _invalid_atomic_write_chain_reasons(steps: list[AIActionStep]) -> list[str]:
        by_id = {step.id: step for step in steps}
        reasons: list[str] = []
        for step in steps:
            if step.action == "message.draft" and not _message_draft_is_complete(step):
                reasons.append(f"{step.id}:message_draft_incomplete")
            if step.action != "message.send":
                continue
            if not _message_send_is_complete(step):
                reasons.append(f"{step.id}:message_send_incomplete")
            confirm_steps = [by_id.get(dep) for dep in step.depends_on if by_id.get(dep) and by_id[dep].action == "user.confirm"]
            if not confirm_steps:
                reasons.append(f"{step.id}:missing_user_confirm_dependency")
            if not any(_confirm_send_is_complete(confirm) for confirm in confirm_steps if confirm is not None):
                reasons.append(f"{step.id}:incomplete_user_confirm_preview")
            if not _refs_are_available(step.args, available=set(step.depends_on)):
                reasons.append(f"{step.id}:message_send_unavailable_ref")
        return reasons


def _latest_complete_send_confirmation(steps: list[AIActionStep], *, send_step: AIActionStep) -> AIActionStep | None:
    send_refs = _refs_in_value(send_step.args)
    for step in reversed(steps):
        if step.action != "user.confirm" or not _confirm_send_is_complete(step):
            continue
        confirm_refs = _refs_in_value(step.args)
        confirm_depends = set(step.depends_on)
        if not send_refs or send_refs & confirm_refs or send_refs & confirm_depends:
            return step
    return None


def _send_chain_refs(steps: list[AIActionStep]) -> dict[str, tuple[str, str]]:
    by_id = {step.id: step for step in steps}
    chains: dict[str, tuple[str, str]] = {}
    for step in steps:
        if step.action != "message.send":
            continue
        confirm_ids = [
            dep
            for dep in step.depends_on
            if (by_id.get(dep) is not None and by_id[dep].action == "user.confirm")
        ]
        for root in _refs_in_value(step.args.get("preview")):
            candidate = by_id.get(root)
            if candidate is not None and candidate.action == "user.confirm" and root not in confirm_ids:
                confirm_ids.append(root)

        draft_ids = {
            root
            for root in _refs_in_value(step.args)
            if (by_id.get(root) is not None and by_id[root].action == "message.draft")
        }
        for confirm_id in confirm_ids:
            confirm = by_id.get(confirm_id)
            if confirm is None:
                continue
            draft_ids.update(
                dep
                for dep in confirm.depends_on
                if (by_id.get(dep) is not None and by_id[dep].action == "message.draft")
            )
            draft_ids.update(
                root
                for root in _refs_in_value(confirm.args)
                if (by_id.get(root) is not None and by_id[root].action == "message.draft")
            )
        if len(draft_ids) == 1:
            chains[step.id] = (next(iter(draft_ids)), confirm_ids[0] if len(confirm_ids) == 1 else "")
    return chains


def _single_target_send_contact_resolve_ids(steps: list[AIActionStep]) -> set[str]:
    by_id = {step.id: step for step in steps}
    contact_step_ids: set[str] = set()
    for draft_id, _confirm_id in _send_chain_refs(steps).values():
        draft = by_id.get(draft_id)
        if draft is None or draft.action != "message.draft":
            continue
        target_ref = _single_ref(draft.args.get("target"))
        if target_ref is None:
            continue
        root, field_path = target_ref
        source = by_id.get(root)
        if source is None or source.action != "contact.resolve":
            continue
        if _is_first_contact_ref_path(field_path):
            contact_step_ids.add(root)
    return contact_step_ids


def _canonicalize_confirm_step(step: AIActionStep, *, draft_id: str) -> AIActionStep:
    args = dict(step.args or {})
    preview = dict(args.get("preview") or {}) if isinstance(args.get("preview"), dict) else {}
    if preview:
        operation = str(preview.get("operation") or "").strip()
        if "发送" not in operation:
            preview["operation"] = "发送消息"
        preview["target"] = f"${draft_id}.target"
        preview["content"] = f"${draft_id}.content"
        args["preview"] = preview
    return AIActionStep(
        id=step.id,
        action=step.action,
        depends_on=step.depends_on,
        args=args,
        display_text=step.display_text,
        explanation=step.explanation,
        fallback=step.fallback,
    )


def _canonicalize_send_step(step: AIActionStep, *, draft_id: str, confirm_id: str) -> AIActionStep:
    args = dict(step.args or {})
    args["target"] = f"${draft_id}.target_entity"
    args["content"] = f"${draft_id}.content"
    args["idempotency_key"] = f"${draft_id}.idempotency_key"
    depends_on = step.depends_on
    if confirm_id:
        depends_on = tuple(dict.fromkeys([*depends_on, confirm_id]))
    return AIActionStep(
        id=step.id,
        action=step.action,
        depends_on=depends_on,
        args=args,
        display_text=step.display_text,
        explanation=step.explanation,
        fallback=step.fallback,
    )


def _single_ref(value: object) -> tuple[str, str] | None:
    if not isinstance(value, str) or not value.startswith("$"):
        return None
    body = value[1:]
    stops = [index for index in (body.find("."), body.find("[")) if index >= 0]
    split_at = min(stops) if stops else len(body)
    root = body[:split_at]
    if not root:
        return None
    field_path = body[split_at + 1 :] if split_at < len(body) and body[split_at] == "." else body[split_at:]
    return root, field_path


def _is_first_contact_ref_path(field_path: str) -> bool:
    return field_path == "contacts[0]" or field_path.startswith("contacts[0].")


def _message_draft_is_complete(step: AIActionStep) -> bool:
    args = dict(step.args or {})
    return (
        _has_value(args.get("target"))
        and _has_value(args.get("content"))
        and _refs_are_available(args, available=set(step.depends_on))
    )


def _message_send_is_complete(step: AIActionStep) -> bool:
    args = dict(step.args or {})
    return (
        _has_value(args.get("target"))
        and _has_value(args.get("content"))
        and _has_value(args.get("idempotency_key"))
    )


def _confirm_send_is_complete(step: AIActionStep) -> bool:
    args = dict(step.args or {})
    preview = args.get("preview") if isinstance(args.get("preview"), dict) else {}
    operation = str(preview.get("operation") or "").strip()
    return (
        "发送" in operation
        and _has_value(preview.get("target"))
        and _has_value(preview.get("content"))
        and _refs_are_available(preview, available=set(step.depends_on))
    )


def _normalize_args_against_input_model(args: dict[str, Any], *, spec: AtomicActionSpec) -> dict[str, Any]:
    fields = getattr(getattr(spec, "input_model", None), "model_fields", None)
    if fields is None:
        return args
    allowed_fields = set(fields.keys())
    if not allowed_fields:
        return {}
    return {
        key: value
        for key, value in args.items()
        if key in allowed_fields or value is not None
    }


def _step_has_missing_required_input(step: AIActionStep, *, spec: AtomicActionSpec) -> bool:
    fields = getattr(getattr(spec, "input_model", None), "model_fields", None)
    if not fields:
        return False
    args = dict(step.args or {})
    for field_name, field in fields.items():
        is_required = getattr(field, "is_required", None)
        if callable(is_required) and is_required() and not _has_value(args.get(field_name)):
            return True
    return False


def _value_references_expected_action_field(
    value: Any,
    expected_refs: Iterable[str],
    *,
    action_specs: dict[str, AtomicActionSpec],
    seen_step_actions: dict[str, str],
) -> bool:
    ref = _single_ref(value)
    if ref is None:
        return False
    root, field_path = ref
    actual_action = seen_step_actions.get(root, "")
    for expected_ref in expected_refs:
        expected = _split_expected_ref(expected_ref, action_specs=action_specs)
        if expected is None:
            continue
        expected_action, expected_field_path = expected
        if actual_action == expected_action and field_path == expected_field_path:
            return True
    return False


def _first_available_expected_ref(
    expected_refs: Iterable[str],
    *,
    action_specs: dict[str, AtomicActionSpec],
    seen_step_actions: dict[str, str],
    preferred_step_ids: Iterable[str],
) -> str:
    preferred = tuple(str(step_id or "").strip() for step_id in preferred_step_ids if str(step_id or "").strip())
    ordered_step_ids = tuple(dict.fromkeys([*preferred, *seen_step_actions.keys()]))
    for expected_ref in expected_refs:
        expected = _split_expected_ref(expected_ref, action_specs=action_specs)
        if expected is None:
            continue
        expected_action, expected_field_path = expected
        for step_id in ordered_step_ids:
            if seen_step_actions.get(step_id) != expected_action:
                continue
            return f"${step_id}.{expected_field_path}" if expected_field_path else f"${step_id}"
    return ""


def _split_expected_ref(
    expected_ref: str,
    *,
    action_specs: dict[str, AtomicActionSpec],
) -> tuple[str, str] | None:
    text = str(expected_ref or "").strip()
    if not text:
        return None
    for action_name in sorted(action_specs.keys(), key=len, reverse=True):
        if text == action_name:
            return action_name, ""
        prefix = f"{action_name}."
        if text.startswith(prefix):
            return action_name, text[len(prefix) :]
    return None


def _refs_are_available(value: object, *, available: set[str]) -> bool:
    for ref in _refs_in_value(value):
        if ref not in available:
            return False
    return True


def _replace_unique_action_refs(value: object, replacements: dict[str, str]) -> object:
    if isinstance(value, str):
        if not value.startswith("$"):
            return value
        body = value[1:]
        for action_name in sorted(replacements, key=len, reverse=True):
            if body == action_name or body.startswith(f"{action_name}.") or body.startswith(f"{action_name}["):
                return f"${replacements[action_name]}{body[len(action_name):]}"
        return value
    if isinstance(value, list):
        return [_replace_unique_action_refs(item, replacements) for item in value]
    if isinstance(value, tuple):
        return tuple(_replace_unique_action_refs(item, replacements) for item in value)
    if isinstance(value, dict):
        return {key: _replace_unique_action_refs(item, replacements) for key, item in value.items()}
    return value


def _refs_in_value(value: object) -> set[str]:
    if isinstance(value, str):
        if not value.startswith("$"):
            return set()
        ref = value[1:]
        stops = [index for index in (ref.find("."), ref.find("[")) if index >= 0]
        root = ref[: min(stops) if stops else len(ref)]
        return {root} if root else set()
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


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list | tuple | dict):
        return bool(value)
    return True

def _default_step_id(action: str, index: int) -> str:
    base = str(action or "step").replace(".", "_").replace("-", "_").strip("_") or "step"
    return f"{base}_{index}"


def _unique_step_id(base: str, existing_ids: set[str]) -> str:
    normalized = str(base or "step").strip() or "step"
    if normalized not in existing_ids:
        return normalized
    index = 2
    while f"{normalized}_{index}" in existing_ids:
        index += 1
    return f"{normalized}_{index}"


def _display_text(action: str) -> str:
    return {
        "contact.resolve": "正在解析对象...",
        "memory.search": "正在检索本地记忆...",
        "memory.summarize": "正在整理检索结果...",
        "message.draft": "正在生成草稿...",
        "user.confirm": "等待你确认...",
        "message.send": "准备执行发送...",
    }.get(str(action or ""), "正在执行步骤...")


def _explanation(action: str) -> str:
    return {
        "contact.resolve": "把用户表达的对象解析为本地稳定实体。",
        "memory.search": "从本地 AI 记忆库检索相关聊天、语音和文件内容。",
        "memory.summarize": "把检索结果整理成可供 AI 回复使用的上下文。",
        "message.draft": "生成发送前可预览的草稿。",
        "user.confirm": "高风险或外部副作用操作需要用户确认。",
        "message.send": "执行发送动作；当前真实发送能力可能被禁用。",
    }.get(str(action or ""), "执行模型计划中的原子动作。")


def _plan_risk(
    steps: list[AIActionStep],
    fallback: str,
    *,
    write_action_names: Iterable[str] | None = None,
) -> str:
    writes = frozenset(write_action_names or DEFAULT_WRITE_ACTION_NAMES)
    if any(step.action in writes for step in steps):
        return "high"
    normalized = str(fallback or "low").strip().lower()
    return normalized if normalized in {"low", "medium", "high"} else "low"


def _clip(value: str, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."
