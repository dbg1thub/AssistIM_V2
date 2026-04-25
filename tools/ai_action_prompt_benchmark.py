"""Utilities for evaluating AI action planner prompt samples.

This module is intentionally model-agnostic. It parses saved model output,
normalizes action-plan structure, and checks expectations without executing
application actions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_GOLDEN_CORPUS_PATH = Path(__file__).with_name("ai_action_golden_corpus.json")


@dataclass(frozen=True, slots=True)
class PromptStepArgExpectation:
    action: str
    path: str
    equals: str | None = None
    starts_with: str | None = None


@dataclass(frozen=True, slots=True)
class PromptCaseExpectation:
    required_actions: tuple[str, ...] = ()
    risk: str = ""
    contact_queries: tuple[str, ...] = ()
    requires_confirmation: bool | None = None
    expected_content: str = ""
    require_all_history: bool = False
    required_step_args: tuple[PromptStepArgExpectation, ...] = ()
    is_action: bool | None = None
    forbidden_actions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PromptBenchmarkCase:
    name: str
    user_input: str
    expectation: PromptCaseExpectation = field(default_factory=PromptCaseExpectation)
    tags: tuple[str, ...] = ()


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
    checks: dict[str, bool] = {"valid_plan": bool(payload)}
    messages: list[str] = []

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
        actions = [str(step.get("action") or "").strip() for step in steps]
        checks["required_actions"] = all(action in actions for action in expectation.required_actions)
        if not checks["required_actions"]:
            messages.append("missing required actions")
    if expectation.forbidden_actions:
        actions = [str(step.get("action") or "").strip() for step in steps]
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
    return {
        "case_count": len(results),
        "sample_count": len(samples),
        "valid_json_rate": _rate(sum(1 for sample in samples if sample.valid_json), len(samples)),
        "expectation_pass_rate": _rate(sum(1 for sample in samples if sample.expectation_passed), len(samples)),
        "error_codes": _error_counts(samples),
        "failed_cases": _failed_cases(results),
        "cases": [_summarize_case(result) for result in results],
    }


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
        forbidden_actions=tuple(_string_list(payload.get("forbidden_actions"))),
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


def _step_arg_matches(steps: list[dict[str, Any]], expectation: PromptStepArgExpectation) -> bool:
    for step in steps:
        if str(step.get("action") or "").strip() != expectation.action:
            continue
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        value = _get_path(args, expectation.path)
        if expectation.equals is not None and str(value) != expectation.equals:
            continue
        if expectation.starts_with is not None and not str(value).startswith(expectation.starts_with):
            continue
        return True
    return False


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
    return {
        "name": result.case.name,
        "sample_count": len(samples),
        "valid_json_rate": _rate(sum(1 for sample in samples if sample.valid_json), len(samples)),
        "expectation_pass_rate": _rate(sum(1 for sample in samples if sample.expectation_passed), len(samples)),
        "structural_stability": _rate(dominant_count, len(samples)),
        "error_codes": _error_counts(samples),
    }


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
