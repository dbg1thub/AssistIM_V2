"""Utilities for evaluating AI action planner prompt samples.

This module is intentionally model-agnostic. It parses saved model output,
normalizes action-plan structure, and checks expectations without executing
application actions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


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


@dataclass(frozen=True, slots=True)
class PromptBenchmarkCase:
    name: str
    user_input: str
    expectation: PromptCaseExpectation = field(default_factory=PromptCaseExpectation)


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

    if expectation.required_actions:
        actions = [str(step.get("action") or "").strip() for step in steps]
        checks["required_actions"] = all(action in actions for action in expectation.required_actions)
        if not checks["required_actions"]:
            messages.append("missing required actions")
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
        "cases": [_summarize_case(result) for result in results],
    }


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
