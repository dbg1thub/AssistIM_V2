"""Utilities for evaluating AI action planner prompt samples.

This module is intentionally model-agnostic. It parses saved model output,
normalizes action-plan structure, and checks expectations without executing
application actions.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


DEFAULT_GOLDEN_CORPUS_PATH = Path(__file__).with_name("ai_action_golden_corpus.json")
LEGACY_PLAN_TOP_LEVEL_FIELDS = (
    "action",
    "slots",
    "missing_slots",
    "requires_app_data",
    "requires_side_effect",
)


@dataclass(frozen=True, slots=True)
class PromptStepArgExpectation:
    action: str
    path: str
    equals: str | None = None
    starts_with: str | None = None
    ref_action: str | None = None


@dataclass(frozen=True, slots=True)
class PromptCaseExpectation:
    required_actions: tuple[str, ...] = ()
    required_action_sequence: tuple[str, ...] = ()
    risk: str = ""
    contact_queries: tuple[str, ...] = ()
    requires_confirmation: bool | None = None
    expected_content: str = ""
    require_all_history: bool = False
    required_step_args: tuple[PromptStepArgExpectation, ...] = ()
    is_action: bool | None = None
    forbidden_actions: tuple[str, ...] = ()
    allow_extra_actions: bool = False
    forbidden_top_level_fields: tuple[str, ...] = field(default_factory=lambda: LEGACY_PLAN_TOP_LEVEL_FIELDS)


@dataclass(frozen=True, slots=True)
class PromptBenchmarkCase:
    name: str
    user_input: str
    expectation: PromptCaseExpectation = field(default_factory=PromptCaseExpectation)
    tags: tuple[str, ...] = ()
    router_expected_route: str = ""


@dataclass(frozen=True, slots=True)
class SampleResult:
    iteration: int
    elapsed_ms: int
    duration_ms: int
    queue_wait_ms: int
    prompt_chars: int
    raw_output: str
    parsed_plan: dict[str, Any] | None
    valid_json: bool
    expectation_passed: bool
    checks: dict[str, bool]
    check_messages: list[str]
    structural_signature: str
    raw_signature: str
    error_code: str = ""
    error_message: str = ""
    runtime_validation_result: str = ""
    runtime_expectation_passed: bool | None = None
    runtime_safe: bool | None = None
    runtime_check_messages: list[str] = field(default_factory=list)
    runtime_structural_signature: str = ""
    workflow_repair_result: str = ""
    workflow_repair_expectation_passed: bool | None = None
    workflow_repair_safe: bool | None = None
    workflow_repair_attempted: bool | None = None
    workflow_repair_check_messages: list[str] = field(default_factory=list)
    workflow_repair_structural_signature: str = ""


@dataclass(frozen=True, slots=True)
class CaseBenchmarkResult:
    case: PromptBenchmarkCase
    samples: list[SampleResult]


def parse_plan_json(raw_output: str) -> tuple[dict[str, Any] | None, bool]:
    """Parse one JSON object from raw model output."""
    text = str(raw_output or "").strip()
    if not text:
        return None, False
    candidates = _json_candidates(text)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed, True
    return None, False


def load_golden_corpus(path: str | Path | None = None) -> list[PromptBenchmarkCase]:
    """Load saved AI action golden cases without running a model."""
    corpus_path = Path(path) if path is not None else DEFAULT_GOLDEN_CORPUS_PATH
    try:
        payload = json.loads(corpus_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"golden corpus not found: {corpus_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"golden corpus is not valid JSON: {corpus_path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("golden corpus root must be an object")
    version = payload.get("version")
    if version != 1:
        raise ValueError("golden corpus version must be 1")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("golden corpus cases must be a non-empty array")

    cases: list[PromptBenchmarkCase] = []
    seen_names: set[str] = set()
    for index, raw_case in enumerate(raw_cases, start=1):
        if not isinstance(raw_case, dict):
            raise ValueError(f"golden corpus case #{index} must be an object")
        case = _load_golden_case(raw_case, index=index)
        if case.name in seen_names:
            raise ValueError(f"duplicate case name: {case.name}")
        seen_names.add(case.name)
        cases.append(case)
    return cases


def canonical_structural_signature(plan: dict[str, Any] | None) -> str:
    """Return a stable plan signature ignoring wording-only fields and step ids."""
    if not isinstance(plan, dict):
        return "{}"
    step_id_map: dict[str, str] = {}
    steps: list[dict[str, Any]] = []
    for index, raw_step in enumerate(list(plan.get("steps") or []), start=1):
        if not isinstance(raw_step, dict):
            continue
        step_id = str(raw_step.get("id") or f"step_{index}").strip()
        canonical_id = f"s{len(step_id_map) + 1}"
        step_id_map[step_id] = canonical_id
    for index, raw_step in enumerate(list(plan.get("steps") or []), start=1):
        if not isinstance(raw_step, dict):
            continue
        canonical_id = step_id_map.get(str(raw_step.get("id") or f"step_{index}").strip(), f"s{index}")
        steps.append(
            {
                "id": canonical_id,
                "action": str(raw_step.get("action") or "").strip(),
                "depends_on": [
                    step_id_map.get(str(dep or "").strip(), str(dep or "").strip())
                    for dep in list(raw_step.get("depends_on") or [])
                    if str(dep or "").strip()
                ],
                "args": _replace_refs(_canonical_value(raw_step.get("args") if isinstance(raw_step.get("args"), dict) else {}), step_id_map),
            }
        )
    payload = {
        "risk": str(plan.get("risk") or "").strip().lower(),
        "steps": steps,
        "final": _replace_refs(_canonical_value(plan.get("final") if isinstance(plan.get("final"), dict) else {}), step_id_map),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def evaluate_case(plan: dict[str, Any] | None, expectation: PromptCaseExpectation) -> tuple[dict[str, bool], list[str]]:
    payload = dict(plan or {}) if isinstance(plan, dict) else {}
    steps = [dict(item) for item in list(payload.get("steps") or []) if isinstance(item, dict)]
    actions = [str(step.get("action") or "").strip() for step in steps]
    checks: dict[str, bool] = {"valid_plan": bool(payload)}
    messages: list[str] = []

    if expectation.forbidden_top_level_fields:
        present_fields = sorted(field for field in expectation.forbidden_top_level_fields if field in payload)
        checks["forbidden_top_level_fields"] = not present_fields
        if present_fields:
            messages.append(f"forbidden top-level fields present: {', '.join(present_fields)}")
    if expectation.is_action is not None:
        inferred_is_action = bool(payload.get("is_action", True if steps else False))
        checks["is_action"] = inferred_is_action is bool(expectation.is_action)
        if not checks["is_action"]:
            messages.append("is_action mismatch")
        if expectation.is_action is False:
            checks["no_steps_for_non_action"] = not steps
            if not checks["no_steps_for_non_action"]:
                messages.append("non-action plan contains steps")
    if expectation.required_actions:
        checks["required_actions"] = all(action in actions for action in expectation.required_actions)
        if not checks["required_actions"]:
            messages.append("missing required actions")
        if not expectation.allow_extra_actions:
            checks["unexpected_actions"] = not _extra_actions(actions, expectation.required_actions)
            if not checks["unexpected_actions"]:
                messages.append("unexpected actions present")
    if expectation.required_action_sequence:
        checks["required_action_sequence"] = _actions_contain_sequence(actions, expectation.required_action_sequence)
        if not checks["required_action_sequence"]:
            messages.append("required action sequence mismatch")
    if steps:
        checks["step_references"] = _has_valid_step_references(steps, payload.get("final") if isinstance(payload.get("final"), dict) else {})
        if not checks["step_references"]:
            messages.append("unresolved step reference")
    if expectation.forbidden_actions:
        forbidden = set(expectation.forbidden_actions)
        checks["forbidden_actions"] = not any(action in forbidden for action in actions)
        if not checks["forbidden_actions"]:
            messages.append("forbidden action present")
    if expectation.risk:
        checks["risk"] = str(payload.get("risk") or "").strip().lower() == expectation.risk.strip().lower()
        if not checks["risk"]:
            messages.append("risk mismatch")
    if expectation.contact_queries:
        actual_queries = _contact_queries(steps)
        checks["contact_queries"] = all(
            any(expected == actual for actual in actual_queries)
            for expected in expectation.contact_queries
        )
        if not checks["contact_queries"]:
            messages.append("missing contact query")
    if expectation.requires_confirmation is not None:
        has_confirmation = any(str(step.get("action") or "").strip() == "user.confirm" for step in steps)
        checks["requires_confirmation"] = has_confirmation == expectation.requires_confirmation
        if not checks["requires_confirmation"]:
            messages.append("confirmation expectation mismatch")
    if expectation.expected_content:
        checks["expected_content"] = expectation.expected_content in json.dumps(payload, ensure_ascii=False)
        if not checks["expected_content"]:
            messages.append("missing expected content")
    if expectation.require_all_history:
        checks["all_history"] = _has_all_history_memory_search(steps)
        if not checks["all_history"]:
            messages.append("missing all_history memory search")
    if expectation.required_step_args:
        checks["required_step_args"] = all(_step_arg_matches(steps, item) for item in expectation.required_step_args)
        if not checks["required_step_args"]:
            messages.append("required step args mismatch")
    return checks, messages


def summarize_results(results: list[CaseBenchmarkResult]) -> dict[str, Any]:
    samples = [sample for result in results for sample in list(result.samples or [])]
    summary = {
        "case_count": len(results),
        "sample_count": len(samples),
        "valid_json_rate": _rate(sum(1 for sample in samples if sample.valid_json), len(samples)),
        "expectation_pass_rate": _rate(sum(1 for sample in samples if sample.expectation_passed), len(samples)),
        "raw_expectation_pass_rate": _rate(sum(1 for sample in samples if sample.expectation_passed), len(samples)),
        "error_codes": _error_counts(samples),
        "failed_cases": _failed_cases(results),
        "cases": [_summarize_case(result) for result in results],
        "failure_analysis": _failure_analysis(results),
    }
    runtime_samples = [sample for sample in samples if sample.runtime_validation_result]
    if runtime_samples:
        summary["runtime_expectation_pass_rate"] = _rate(
            sum(1 for sample in runtime_samples if sample.runtime_expectation_passed is True),
            len(runtime_samples),
        )
        summary["runtime_safe_rate"] = _rate(
            sum(1 for sample in runtime_samples if sample.runtime_safe is True),
            len(runtime_samples),
        )
        summary["runtime_blocked_cases"] = _runtime_blocked_cases(results)
        summary["runtime_failed_cases"] = _runtime_failed_cases(results)
    workflow_samples = [sample for sample in samples if sample.workflow_repair_result]
    if workflow_samples:
        summary["workflow_repair_expectation_pass_rate"] = _rate(
            sum(1 for sample in workflow_samples if sample.workflow_repair_expectation_passed is True),
            len(workflow_samples),
        )
        summary["workflow_repair_safe_rate"] = _rate(
            sum(1 for sample in workflow_samples if sample.workflow_repair_safe is True),
            len(workflow_samples),
        )
        summary["workflow_repair_attempt_rate"] = _rate(
            sum(1 for sample in workflow_samples if sample.workflow_repair_attempted is True),
            len(workflow_samples),
        )
        summary["workflow_repair_blocked_cases"] = _workflow_repair_blocked_cases(results)
        summary["workflow_repair_failed_cases"] = _workflow_repair_failed_cases(results)
    return summary


def _load_golden_case(raw_case: dict[str, Any], *, index: int) -> PromptBenchmarkCase:
    name = str(raw_case.get("name") or "").strip()
    user_input = str(raw_case.get("user_input") or "").strip()
    if not name:
        raise ValueError(f"golden corpus case #{index} is missing name")
    if not user_input:
        raise ValueError(f"golden corpus case {name} is missing user_input")
    expectation = raw_case.get("expectation")
    if not isinstance(expectation, dict):
        raise ValueError(f"golden corpus case {name} is missing expectation")
    return PromptBenchmarkCase(
        name=name,
        user_input=user_input,
        expectation=_load_expectation(expectation, case_name=name),
        tags=tuple(_string_list(raw_case.get("tags"))),
        router_expected_route=str(raw_case.get("router_expected_route") or "").strip(),
    )


def _load_expectation(payload: dict[str, Any], *, case_name: str) -> PromptCaseExpectation:
    raw_is_action = payload.get("is_action")
    if raw_is_action is not None and not isinstance(raw_is_action, bool):
        raise ValueError(f"golden corpus case {case_name} expectation.is_action must be boolean")
    raw_requires_confirmation = payload.get("requires_confirmation")
    if raw_requires_confirmation is not None and not isinstance(raw_requires_confirmation, bool):
        raise ValueError(f"golden corpus case {case_name} expectation.requires_confirmation must be boolean")
    raw_required_step_args = payload.get("required_step_args") or []
    if not isinstance(raw_required_step_args, list):
        raise ValueError(f"golden corpus case {case_name} required_step_args must be an array")
    required_step_args = tuple(
        _load_step_arg_expectation(item, case_name=case_name)
        for item in raw_required_step_args
        if isinstance(item, dict)
    )
    if len(required_step_args) != len(raw_required_step_args):
        raise ValueError(f"golden corpus case {case_name} required_step_args must contain objects")
    return PromptCaseExpectation(
        is_action=raw_is_action,
        required_actions=tuple(_string_list(payload.get("required_actions"))),
        required_action_sequence=tuple(_string_list(payload.get("required_action_sequence"))),
        forbidden_actions=tuple(_string_list(payload.get("forbidden_actions"))),
        allow_extra_actions=bool(payload.get("allow_extra_actions")),
        forbidden_top_level_fields=(
            tuple(_string_list(payload.get("forbidden_top_level_fields")))
            if "forbidden_top_level_fields" in payload
            else LEGACY_PLAN_TOP_LEVEL_FIELDS
        ),
        risk=str(payload.get("risk") or "").strip(),
        contact_queries=tuple(_string_list(payload.get("contact_queries"))),
        requires_confirmation=raw_requires_confirmation,
        expected_content=str(payload.get("expected_content") or "").strip(),
        require_all_history=bool(payload.get("require_all_history")),
        required_step_args=required_step_args,
    )


def _load_step_arg_expectation(payload: dict[str, Any], *, case_name: str) -> PromptStepArgExpectation:
    action = str(payload.get("action") or "").strip()
    path = str(payload.get("path") or "").strip()
    if not action or not path:
        raise ValueError(f"golden corpus case {case_name} step arg expectation requires action and path")
    return PromptStepArgExpectation(
        action=action,
        path=path,
        equals=str(payload.get("equals")) if payload.get("equals") is not None else None,
        starts_with=str(payload.get("starts_with")) if payload.get("starts_with") is not None else None,
        ref_action=str(payload.get("ref_action")) if payload.get("ref_action") is not None else None,
    )


def _json_candidates(text: str) -> list[str]:
    fenced = [
        match.group("body").strip()
        for match in re.finditer(r"```(?:json)?\s*(?P<body>.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
        if match.group("body").strip()
    ]
    if fenced:
        return fenced
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        return [text[start : end + 1], text]
    return [text]


def _string_list(value: Any) -> list[str]:
    raw_items = value if isinstance(value, list) else ([] if value is None else [value])
    items: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text)
    return items


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in {"display_text", "explanation"}
        }
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, tuple):
        return [_canonical_value(item) for item in value]
    return value


def _replace_refs(value: Any, step_id_map: dict[str, str]) -> Any:
    if isinstance(value, str):
        return _replace_ref_string(value, step_id_map)
    if isinstance(value, list):
        return [_replace_refs(item, step_id_map) for item in value]
    if isinstance(value, dict):
        return {key: _replace_refs(item, step_id_map) for key, item in value.items()}
    return value


def _replace_ref_string(value: str, step_id_map: dict[str, str]) -> str:
    if not value.startswith("$"):
        return value
    body = value[1:]
    stops = [index for index in (body.find("."), body.find("[")) if index >= 0]
    split_at = min(stops) if stops else len(body)
    step_id = body[:split_at]
    return f"${step_id_map.get(step_id, step_id)}{body[split_at:]}"


def _contact_queries(steps: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for step in steps:
        if str(step.get("action") or "").strip() != "contact.resolve":
            continue
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        for query in list(args.get("queries") or []):
            text = str(query or "").strip()
            if text and text not in values:
                values.append(text)
    return values


def _has_all_history_memory_search(steps: list[dict[str, Any]]) -> bool:
    for step in steps:
        if str(step.get("action") or "").strip() != "memory.search":
            continue
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        time_scope = args.get("time_scope") if isinstance(args.get("time_scope"), dict) else {}
        scope_type = str(time_scope.get("type") or "").strip().lower()
        if scope_type in {"all", "all_history", "history"}:
            return True
    return False


def _actions_contain_sequence(actions: list[str], expected_sequence: tuple[str, ...]) -> bool:
    expected = [str(action or "").strip() for action in expected_sequence if str(action or "").strip()]
    if not expected:
        return True
    cursor = 0
    for action in actions:
        if action == expected[cursor]:
            cursor += 1
            if cursor == len(expected):
                return True
    return False


def _extra_actions(actions: list[str], expected_actions: tuple[str, ...]) -> list[str]:
    actual_counts = Counter(action for action in actions if action)
    expected_counts = Counter(action for action in expected_actions if action)
    extras: list[str] = []
    for action, count in actual_counts.items():
        excess = count - expected_counts.get(action, 0)
        if excess > 0:
            extras.extend([action] * excess)
    return extras


def _has_valid_step_references(steps: list[dict[str, Any]], final: dict[str, Any]) -> bool:
    seen_ids: set[str] = set()
    for index, step in enumerate(steps, start=1):
        step_id = str(step.get("id") or f"step_{index}").strip()
        if not step_id or step_id in seen_ids:
            return False
        depends_on = [str(dep or "").strip() for dep in list(step.get("depends_on") or []) if str(dep or "").strip()]
        if any(dep not in seen_ids for dep in depends_on):
            return False
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        if not _refs_are_available(args, available=seen_ids):
            return False
        seen_ids.add(step_id)
    return _refs_are_available(final, available=seen_ids)


def _refs_are_available(value: Any, *, available: set[str]) -> bool:
    return all(ref in available for ref in _ref_roots(value))


def _ref_roots(value: Any) -> set[str]:
    if isinstance(value, str):
        if not value.startswith("$"):
            return set()
        body = value[1:]
        stops = [index for index in (body.find("."), body.find("[")) if index >= 0]
        split_at = min(stops) if stops else len(body)
        root = body[:split_at]
        return {root} if root else {""}
    if isinstance(value, list):
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


def _step_arg_matches(steps: list[dict[str, Any]], expectation: PromptStepArgExpectation) -> bool:
    steps_by_id = {
        str(step.get("id") or f"step_{index}").strip(): step
        for index, step in enumerate(steps, start=1)
    }
    for step in steps:
        if str(step.get("action") or "").strip() != expectation.action:
            continue
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        value = _get_path(args, expectation.path)
        if expectation.equals is not None and str(value) != expectation.equals:
            continue
        if expectation.starts_with is not None and not str(value).startswith(expectation.starts_with):
            continue
        if expectation.ref_action is not None and not _ref_points_to_action(
            value,
            steps_by_id=steps_by_id,
            action=expectation.ref_action,
        ):
            continue
        return True
    return False


def _ref_points_to_action(value: Any, *, steps_by_id: dict[str, dict[str, Any]], action: str) -> bool:
    expected_action = str(action or "").strip()
    if not expected_action or not isinstance(value, str) or not value.startswith("$"):
        return False
    roots = _ref_roots(value)
    if len(roots) != 1:
        return False
    root = next(iter(roots))
    step = steps_by_id.get(root)
    return str((step or {}).get("action") or "").strip() == expected_action


def _get_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in [item for item in str(path or "").split(".") if item]:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _summarize_case(result: CaseBenchmarkResult) -> dict[str, Any]:
    samples = list(result.samples or [])
    signatures: dict[str, int] = {}
    for sample in samples:
        signatures[sample.structural_signature] = signatures.get(sample.structural_signature, 0) + 1
    dominant_count = max(signatures.values(), default=0)
    payload = {
        "name": result.case.name,
        "sample_count": len(samples),
        "valid_json_rate": _rate(sum(1 for sample in samples if sample.valid_json), len(samples)),
        "expectation_pass_rate": _rate(sum(1 for sample in samples if sample.expectation_passed), len(samples)),
        "raw_expectation_pass_rate": _rate(sum(1 for sample in samples if sample.expectation_passed), len(samples)),
        "structural_stability": _rate(dominant_count, len(samples)),
        "error_codes": _error_counts(samples),
    }
    runtime_samples = [sample for sample in samples if sample.runtime_validation_result]
    if runtime_samples:
        runtime_signatures: dict[str, int] = {}
        for sample in runtime_samples:
            runtime_signatures[sample.runtime_structural_signature] = runtime_signatures.get(sample.runtime_structural_signature, 0) + 1
        runtime_dominant_count = max(runtime_signatures.values(), default=0)
        payload["runtime_expectation_pass_rate"] = _rate(
            sum(1 for sample in runtime_samples if sample.runtime_expectation_passed is True),
            len(runtime_samples),
        )
        payload["runtime_safe_rate"] = _rate(
            sum(1 for sample in runtime_samples if sample.runtime_safe is True),
            len(runtime_samples),
        )
        payload["runtime_structural_stability"] = _rate(runtime_dominant_count, len(runtime_samples))
    workflow_samples = [sample for sample in samples if sample.workflow_repair_result]
    if workflow_samples:
        workflow_signatures: dict[str, int] = {}
        for sample in workflow_samples:
            workflow_signatures[sample.workflow_repair_structural_signature] = (
                workflow_signatures.get(sample.workflow_repair_structural_signature, 0) + 1
            )
        workflow_dominant_count = max(workflow_signatures.values(), default=0)
        payload["workflow_repair_expectation_pass_rate"] = _rate(
            sum(1 for sample in workflow_samples if sample.workflow_repair_expectation_passed is True),
            len(workflow_samples),
        )
        payload["workflow_repair_safe_rate"] = _rate(
            sum(1 for sample in workflow_samples if sample.workflow_repair_safe is True),
            len(workflow_samples),
        )
        payload["workflow_repair_attempt_rate"] = _rate(
            sum(1 for sample in workflow_samples if sample.workflow_repair_attempted is True),
            len(workflow_samples),
        )
        payload["workflow_repair_structural_stability"] = _rate(workflow_dominant_count, len(workflow_samples))
    return payload


def _failed_cases(results: list[CaseBenchmarkResult]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    for result in results:
        failed_samples = [sample for sample in list(result.samples or []) if not sample.expectation_passed]
        if not failed_samples:
            continue
        messages: list[str] = []
        for sample in failed_samples:
            for message in list(sample.check_messages or []):
                text = str(message or "").strip()
                if text and text not in messages:
                    messages.append(text)
        failed.append(
            {
                "name": result.case.name,
                "failed_sample_count": len(failed_samples),
                "messages": messages,
            }
        )
    return failed


def _runtime_blocked_cases(results: list[CaseBenchmarkResult]) -> list[dict[str, Any]]:
    blocked: list[dict[str, Any]] = []
    for result in results:
        blocked_samples = [
            sample
            for sample in list(result.samples or [])
            if sample.runtime_validation_result == "blocked"
        ]
        if not blocked_samples:
            continue
        messages: list[str] = []
        for sample in blocked_samples:
            for message in list(sample.runtime_check_messages or []):
                text = str(message or "").strip()
                if text.startswith("runtime blocked:") and text not in messages:
                    messages.append(text)
        blocked.append(
            {
                "name": result.case.name,
                "blocked_sample_count": len(blocked_samples),
                "messages": messages,
            }
        )
    return blocked


def _runtime_failed_cases(results: list[CaseBenchmarkResult]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    for result in results:
        failed_samples = [
            sample
            for sample in list(result.samples or [])
            if sample.runtime_validation_result
            and sample.runtime_validation_result != "blocked"
            and sample.runtime_expectation_passed is not True
        ]
        if not failed_samples:
            continue
        messages: list[str] = []
        for sample in failed_samples:
            for message in list(sample.runtime_check_messages or []):
                text = str(message or "").strip()
                if text and text not in messages:
                    messages.append(text)
        failed.append(
            {
                "name": result.case.name,
                "failed_sample_count": len(failed_samples),
                "messages": messages,
            }
        )
    return failed


def _workflow_repair_blocked_cases(results: list[CaseBenchmarkResult]) -> list[dict[str, Any]]:
    blocked: list[dict[str, Any]] = []
    for result in results:
        blocked_samples = [
            sample
            for sample in list(result.samples or [])
            if sample.workflow_repair_result in {"blocked", "blocked_after_repair"}
        ]
        if not blocked_samples:
            continue
        messages: list[str] = []
        for sample in blocked_samples:
            for message in list(sample.workflow_repair_check_messages or []):
                text = str(message or "").strip()
                if text.startswith("workflow repair blocked:") and text not in messages:
                    messages.append(text)
        blocked.append(
            {
                "name": result.case.name,
                "blocked_sample_count": len(blocked_samples),
                "messages": messages,
            }
        )
    return blocked


def _workflow_repair_failed_cases(results: list[CaseBenchmarkResult]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    for result in results:
        failed_samples = [
            sample
            for sample in list(result.samples or [])
            if sample.workflow_repair_result
            and sample.workflow_repair_result not in {"blocked", "blocked_after_repair"}
            and sample.workflow_repair_expectation_passed is not True
        ]
        if not failed_samples:
            continue
        messages: list[str] = []
        for sample in failed_samples:
            for message in list(sample.workflow_repair_check_messages or []):
                text = str(message or "").strip()
                if text and text not in messages:
                    messages.append(text)
        failed.append(
            {
                "name": result.case.name,
                "failed_sample_count": len(failed_samples),
                "messages": messages,
            }
        )
    return failed


def _failure_analysis(results: list[CaseBenchmarkResult]) -> dict[str, Any]:
    return {
        "raw": _raw_failure_analysis(results),
        "runtime": _runtime_failure_analysis(results),
        "workflow_repair": _workflow_repair_failure_analysis(results),
    }


def _raw_failure_analysis(results: list[CaseBenchmarkResult]) -> dict[str, Any]:
    return _layer_failure_analysis(
        results,
        sample_selector=lambda sample: True,
        failed_selector=lambda sample: not sample.expectation_passed,
        categories_for_sample=_raw_failure_categories,
        messages_for_sample=lambda sample: list(sample.check_messages or []),
    )


def _runtime_failure_analysis(results: list[CaseBenchmarkResult]) -> dict[str, Any]:
    return _layer_failure_analysis(
        results,
        sample_selector=lambda sample: bool(sample.runtime_validation_result),
        failed_selector=lambda sample: bool(sample.runtime_validation_result)
        and (
            sample.runtime_validation_result == "blocked"
            or sample.runtime_safe is False
            or sample.runtime_expectation_passed is not True
        ),
        categories_for_sample=_runtime_failure_categories,
        messages_for_sample=lambda sample: list(sample.runtime_check_messages or []),
    )


def _workflow_repair_failure_analysis(results: list[CaseBenchmarkResult]) -> dict[str, Any]:
    return _layer_failure_analysis(
        results,
        sample_selector=lambda sample: bool(sample.workflow_repair_result),
        failed_selector=lambda sample: bool(sample.workflow_repair_result)
        and (
            sample.workflow_repair_result in {"blocked", "blocked_after_repair"}
            or sample.workflow_repair_safe is False
            or sample.workflow_repair_expectation_passed is not True
        ),
        categories_for_sample=_workflow_repair_failure_categories,
        messages_for_sample=lambda sample: list(sample.workflow_repair_check_messages or []),
    )


def _layer_failure_analysis(
    results: list[CaseBenchmarkResult],
    *,
    sample_selector: Callable[[SampleResult], bool],
    failed_selector: Callable[[SampleResult], bool],
    categories_for_sample: Callable[[SampleResult], list[str]],
    messages_for_sample: Callable[[SampleResult], list[str]],
) -> dict[str, Any]:
    selected_samples = [
        sample
        for result in results
        for sample in list(result.samples or [])
        if sample_selector(sample)
    ]
    failed_samples = [
        sample
        for sample in selected_samples
        if failed_selector(sample)
    ]
    category_counts: Counter[str] = Counter()
    for sample in failed_samples:
        category_counts.update(categories_for_sample(sample))

    cases: list[dict[str, Any]] = []
    for result in results:
        case_failed_samples = [
            sample
            for sample in list(result.samples or [])
            if sample_selector(sample) and failed_selector(sample)
        ]
        if not case_failed_samples:
            continue
        case_category_counts: Counter[str] = Counter()
        messages: list[str] = []
        for sample in case_failed_samples:
            case_category_counts.update(categories_for_sample(sample))
            for message in messages_for_sample(sample):
                text = str(message or "").strip()
                if text and text not in messages:
                    messages.append(text)
        cases.append(
            {
                "name": result.case.name,
                "failed_sample_count": len(case_failed_samples),
                "category_counts": _counter_payload(case_category_counts),
                "messages": messages,
            }
        )

    return {
        "sample_count": len(selected_samples),
        "failed_sample_count": len(failed_samples),
        "category_counts": _counter_payload(category_counts),
        "cases": cases,
    }


def _raw_failure_categories(sample: SampleResult) -> list[str]:
    if not sample.valid_json:
        return ["invalid_json"]

    categories: list[str] = []
    checks = dict(sample.checks or {})
    if checks.get("is_action") is False or checks.get("no_steps_for_non_action") is False:
        categories.append("wrong_is_action")
    if checks.get("required_actions") is False:
        categories.append("missing_action")
    if checks.get("unexpected_actions") is False or checks.get("forbidden_actions") is False:
        categories.append("extra_action")
    if checks.get("required_action_sequence") is False or checks.get("step_references") is False:
        categories.append("wrong_dependency")
    if any(
        checks.get(key) is False
        for key in (
            "all_history",
            "contact_queries",
            "expected_content",
            "forbidden_top_level_fields",
            "requires_confirmation",
            "required_step_args",
            "risk",
            "valid_plan",
        )
    ):
        categories.append("wrong_args")
    return _dedupe_categories(categories or ["unknown"])


def _runtime_failure_categories(sample: SampleResult) -> list[str]:
    messages = [str(message or "").strip() for message in list(sample.runtime_check_messages or [])]
    if sample.runtime_validation_result == "blocked" or any(message.startswith("runtime blocked:") for message in messages):
        return ["unsafe_or_blocked"]
    categories = _message_failure_categories(messages)
    if sample.runtime_safe is False:
        categories.append("unsafe_or_blocked")
    return _dedupe_categories(categories or ["unknown"])


def _workflow_repair_failure_categories(sample: SampleResult) -> list[str]:
    messages = [str(message or "").strip() for message in list(sample.workflow_repair_check_messages or [])]
    if sample.workflow_repair_result in {"blocked", "blocked_after_repair"} or any(
        message.startswith("workflow repair blocked:") for message in messages
    ):
        return ["unsafe_or_blocked"]
    categories = _message_failure_categories(messages)
    if sample.workflow_repair_safe is False:
        categories.append("unsafe_or_blocked")
    return _dedupe_categories(categories or ["unknown"])


def _message_failure_categories(messages: list[str]) -> list[str]:
    categories: list[str] = []
    for message in messages:
        if message == "invalid json":
            categories.append("invalid_json")
        elif message in {"is_action mismatch", "non-action plan contains steps"}:
            categories.append("wrong_is_action")
        elif message == "missing required actions":
            categories.append("missing_action")
        elif message in {"unexpected actions present", "forbidden action present"}:
            categories.append("extra_action")
        elif message in {"required action sequence mismatch", "unresolved step reference"}:
            categories.append("wrong_dependency")
        elif message.startswith("runtime blocked:") or message.startswith("workflow repair blocked:"):
            categories.append("unsafe_or_blocked")
        elif message:
            categories.append("wrong_args")
    return _dedupe_categories(categories)


def _dedupe_categories(categories: list[str]) -> list[str]:
    output: list[str] = []
    for category in categories:
        text = str(category or "").strip()
        if text and text not in output:
            output.append(text)
    return output


def _counter_payload(counter: Counter[str]) -> dict[str, int]:
    return {
        key: int(counter[key])
        for key in sorted(counter)
        if int(counter[key]) > 0
    }


def _error_counts(samples: list[SampleResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sample in samples:
        code = str(sample.error_code or "").strip()
        if code:
            counts[code] = counts.get(code, 0) + 1
    return counts


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)
