"""Offline replay helpers for AI action planner corpus runs.

This module preserves raw model output and evaluates it without executing any
application action.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from client.managers.ai_action_normalizer import AIPlanNormalizer
from client.managers.ai_action_optimizer import AIPlanOptimizer
from client.managers.ai_action_registry import AtomicActionRegistry, build_default_action_names
from client.managers.ai_action_types import AIActionPlan
from client.managers.ai_action_validator import AIPlanValidationResult, AIPlanValidator
from client.managers.ai_action_workflow import AIActionPlanner
from tools.ai_action_prompt_benchmark import (
    CaseBenchmarkResult,
    PromptBenchmarkCase,
    SampleResult,
    canonical_structural_signature,
    evaluate_case,
    parse_plan_json,
)


DEFAULT_PLANNER_SCHEMA_VERSION = AIActionPlanner.PLANNER_SCHEMA_VERSION
DEFAULT_PLANNER_PROMPT_VERSION = AIActionPlanner.PLANNER_PROMPT_VERSION
DEFAULT_PLAN_OUTPUT_VERSION = AIActionPlanner.PLAN_OUTPUT_VERSION
DEFAULT_PLANNER_REPLAY_PATH = Path(__file__).with_name("ai_action_planner_replay.jsonl")


@dataclass(frozen=True, slots=True)
class PlannerReplayRecord:
    case_name: str
    user_input: str
    raw_output: str
    elapsed_ms: int = 0
    provider: str = ""
    model: str = ""
    error_code: str = ""
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    planner_prompt_version: str = DEFAULT_PLANNER_PROMPT_VERSION
    planner_schema_version: str = DEFAULT_PLANNER_SCHEMA_VERSION
    plan_version: int = DEFAULT_PLAN_OUTPUT_VERSION
    actions: tuple[str, ...] = ()
    validation_result: str = ""
    diff_from_expected: tuple[str, ...] = ()
    runtime_actions: tuple[str, ...] = ()
    runtime_validation_result: str = ""
    runtime_safe: bool | None = None
    runtime_diff_from_expected: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimeReplayEvaluation:
    actions: tuple[str, ...] = ()
    validation_result: str = ""
    expectation_passed: bool = False
    safe: bool = False
    messages: tuple[str, ...] = ()
    structural_signature: str = "{}"


def build_planner_request(case: PromptBenchmarkCase):
    """Build one local AI request that matches the normal new-action planner prompt."""
    from client.services.ai_service import AIPrivacyScope, AIRequest, AITaskType

    prompt_kind = AIActionPlanner.PROMPT_NEW_ACTION
    registered_action_names = build_default_action_names()
    system_prompt = AIActionPlanner._system_prompt(prompt_kind)
    user_prompt = AIActionPlanner._user_prompt(case.user_input, prompt_kind=prompt_kind)
    return AIRequest(
        task_type=AITaskType.CHAT,
        privacy_scope=AIPrivacyScope.GENERAL,
        must_be_local=True,
        stream=False,
        temperature=0.0,
        max_tokens=1024,
        response_format={
            "type": "json_object",
            "schema": AIActionPlanner.build_schema_for_prompt_kind(
                prompt_kind,
                registered_action_names=registered_action_names,
            ),
        },
        priority=4,
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        metadata={
            "source": "ai_action_planner_corpus",
            "strict_json": True,
            "planner_schema_version": DEFAULT_PLANNER_SCHEMA_VERSION,
            "planner_prompt_version": DEFAULT_PLANNER_PROMPT_VERSION,
            "planner_prompt_kind": prompt_kind,
            "planner_case_name": case.name,
            "prompt_chars": len(system_prompt) + len(user_prompt),
        },
    )


def evaluate_planner_replay_file(cases: Sequence[PromptBenchmarkCase], path: str | Path) -> list[CaseBenchmarkResult]:
    records = load_planner_replay_records(path)
    return evaluate_planner_replay_records(cases, records)


def evaluate_planner_replay_records(
    cases: Sequence[PromptBenchmarkCase],
    records: Sequence[PlannerReplayRecord],
) -> list[CaseBenchmarkResult]:
    records_by_case = _records_by_case(records)
    results: list[CaseBenchmarkResult] = []
    for case in cases:
        samples = [
            _sample_from_record(case, record, iteration=index)
            for index, record in enumerate(records_by_case.get(case.name, ()), start=1)
        ]
        results.append(CaseBenchmarkResult(case=case, samples=samples))
    return results


def annotate_planner_replay_records(
    cases: Sequence[PromptBenchmarkCase],
    records: Sequence[PlannerReplayRecord],
) -> list[PlannerReplayRecord]:
    """Attach plan-shape and expectation-diff metadata before writing replay JSONL."""
    cases_by_name = {case.name: case for case in cases}
    return [_annotate_record(cases_by_name.get(record.case_name), record) for record in records]


def write_planner_replay_records(
    path: str | Path,
    records: Sequence[PlannerReplayRecord],
    *,
    cases: Sequence[PromptBenchmarkCase] | None = None,
) -> None:
    replay_path = Path(path)
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    output_records = annotate_planner_replay_records(cases, records) if cases is not None else list(records)
    with replay_path.open("w", encoding="utf-8", newline="\n") as file:
        for record in output_records:
            file.write(json.dumps(_record_to_payload(record), ensure_ascii=False, sort_keys=True) + "\n")


def load_planner_replay_records(path: str | Path) -> list[PlannerReplayRecord]:
    replay_path = Path(path)
    records: list[PlannerReplayRecord] = []
    try:
        lines = replay_path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError as exc:
        raise ValueError(f"planner replay file not found: {replay_path}") from exc
    for line_no, line in enumerate(lines, start=1):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"planner replay line {line_no} is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"planner replay line {line_no} must be an object")
        records.append(_record_from_payload(payload, line_no=line_no))
    return records


def _sample_from_record(
    case: PromptBenchmarkCase,
    record: PlannerReplayRecord,
    *,
    iteration: int,
) -> SampleResult:
    parsed, valid_json = parse_plan_json(record.raw_output)
    checks: dict[str, bool] = {"valid_json": valid_json}
    messages: list[str] = []
    if valid_json:
        expectation_checks, expectation_messages = evaluate_case(parsed, case.expectation)
        checks.update(expectation_checks)
        messages.extend(expectation_messages)
    else:
        checks["valid_plan"] = False
        messages.append("invalid json")
    expectation_passed = valid_json and all(checks.values())
    runtime = _evaluate_runtime_replay(
        case=case,
        parsed=parsed,
        valid_json=valid_json,
        user_text=record.user_input,
    )
    return SampleResult(
        iteration=iteration,
        elapsed_ms=max(0, int(record.elapsed_ms or 0)),
        duration_ms=max(0, int(record.elapsed_ms or 0)),
        queue_wait_ms=max(0, _metadata_int(record.metadata, "queue_wait_ms")),
        prompt_chars=max(len(record.user_input), _metadata_int(record.metadata, "prompt_chars")),
        raw_output=record.raw_output,
        parsed_plan=parsed if valid_json else None,
        valid_json=valid_json,
        expectation_passed=expectation_passed,
        checks=checks,
        check_messages=messages,
        structural_signature=canonical_structural_signature(parsed),
        raw_signature=_raw_signature(parsed),
        error_code=record.error_code,
        error_message=record.error_message,
        runtime_validation_result=runtime.validation_result,
        runtime_expectation_passed=runtime.expectation_passed,
        runtime_safe=runtime.safe,
        runtime_check_messages=list(runtime.messages),
        runtime_structural_signature=runtime.structural_signature,
    )


def _annotate_record(case: PromptBenchmarkCase | None, record: PlannerReplayRecord) -> PlannerReplayRecord:
    parsed, valid_json = parse_plan_json(record.raw_output)
    actions = _actions_from_plan(parsed)
    validation_result = "not_evaluated"
    diff_from_expected: tuple[str, ...] = ()
    runtime = RuntimeReplayEvaluation()
    if case is None:
        if not valid_json:
            validation_result = "invalid_json"
            diff_from_expected = ("invalid json",)
    elif not valid_json:
        validation_result = "invalid_json"
        diff_from_expected = ("invalid json",)
        runtime = _evaluate_runtime_replay(
            case=case,
            parsed=parsed,
            valid_json=valid_json,
            user_text=record.user_input,
        )
    else:
        checks, messages = evaluate_case(parsed, case.expectation)
        validation_result = "passed" if checks and all(checks.values()) else "failed"
        diff_from_expected = tuple(messages)
        runtime = _evaluate_runtime_replay(
            case=case,
            parsed=parsed,
            valid_json=valid_json,
            user_text=record.user_input,
        )
    return replace(
        record,
        planner_prompt_version=_planner_prompt_version(record),
        planner_schema_version=_planner_schema_version(record),
        plan_version=_plan_version(record),
        actions=actions,
        validation_result=validation_result,
        diff_from_expected=diff_from_expected,
        runtime_actions=runtime.actions,
        runtime_validation_result=runtime.validation_result,
        runtime_safe=runtime.safe,
        runtime_diff_from_expected=runtime.messages,
    )


def _evaluate_runtime_replay(
    *,
    case: PromptBenchmarkCase,
    parsed: Mapping[str, Any] | None,
    valid_json: bool,
    user_text: str,
) -> RuntimeReplayEvaluation:
    if not valid_json or not isinstance(parsed, Mapping):
        return RuntimeReplayEvaluation(
            validation_result="invalid_json",
            expectation_passed=False,
            safe=False,
            messages=("invalid json",),
        )

    registry = _runtime_registry()
    normalizer = AIPlanNormalizer()
    optimizer = AIPlanOptimizer()
    validator = AIPlanValidator(registry=registry)
    normalized = normalizer.normalize(AIActionPlan.from_dict(dict(parsed)), user_text=user_text)

    if not normalized.is_action:
        return _runtime_expectation_result(normalized.to_dict(), case)

    validation = validator.validate(normalized)
    if not validation.allowed:
        return _runtime_invalid_result(normalized, validation, registry=registry)

    optimized, _reason = optimizer.optimize(normalized)
    optimized_validation = validator.validate(optimized)
    if not optimized_validation.allowed:
        return _runtime_invalid_result(optimized, optimized_validation, registry=registry)
    return _runtime_expectation_result(optimized.to_dict(), case)


def _runtime_expectation_result(plan_payload: dict[str, Any], case: PromptBenchmarkCase) -> RuntimeReplayEvaluation:
    checks, messages = evaluate_case(plan_payload, case.expectation)
    passed = bool(checks) and all(checks.values())
    return RuntimeReplayEvaluation(
        actions=_actions_from_plan(plan_payload),
        validation_result="passed" if passed else "failed",
        expectation_passed=passed,
        safe=passed,
        messages=tuple(messages),
        structural_signature=canonical_structural_signature(plan_payload),
    )


def _runtime_invalid_result(
    plan: AIActionPlan,
    validation: AIPlanValidationResult,
    *,
    registry: AtomicActionRegistry,
) -> RuntimeReplayEvaluation:
    skip_reason = _runtime_repair_skip_reason(plan, validation, registry=registry)
    if skip_reason:
        return RuntimeReplayEvaluation(
            actions=tuple(step.action for step in tuple(plan.steps or ()) if step.action),
            validation_result="blocked",
            expectation_passed=False,
            safe=True,
            messages=(
                f"runtime blocked: {skip_reason}",
                *validation.repair_messages(),
            ),
            structural_signature=canonical_structural_signature(plan.to_dict()),
        )
    return RuntimeReplayEvaluation(
        actions=tuple(step.action for step in tuple(plan.steps or ()) if step.action),
        validation_result="repairable_invalid",
        expectation_passed=False,
        safe=False,
        messages=validation.repair_messages(),
        structural_signature=canonical_structural_signature(plan.to_dict()),
    )


_RUNTIME_REGISTRY: AtomicActionRegistry | None = None


def _runtime_registry() -> AtomicActionRegistry:
    global _RUNTIME_REGISTRY
    if _RUNTIME_REGISTRY is None:
        _RUNTIME_REGISTRY = AtomicActionRegistry(contact_resolver=None)
    return _RUNTIME_REGISTRY


def _runtime_repair_skip_reason(
    plan: AIActionPlan,
    validation: AIPlanValidationResult,
    *,
    registry: AtomicActionRegistry,
) -> str:
    if any(error.code == "ACTION_NOT_FOUND" for error in validation.errors):
        return "unknown_action"
    if _runtime_plan_has_side_effect(plan, registry=registry):
        return "side_effect_plan"
    return ""


def _runtime_plan_has_side_effect(plan: AIActionPlan, *, registry: AtomicActionRegistry) -> bool:
    for step in tuple(plan.steps or ()):
        spec = registry.get(step.action)
        if spec is not None and (spec.kind == "write" or spec.allow_side_effect):
            return True
    return False


def _actions_from_plan(plan: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(plan, Mapping):
        return ()
    actions: list[str] = []
    for step in list(plan.get("steps") or []):
        if not isinstance(step, Mapping):
            continue
        action = str(step.get("action") or "").strip()
        if action:
            actions.append(action)
    return tuple(actions)


def _planner_prompt_version(record: PlannerReplayRecord) -> str:
    value = str(record.planner_prompt_version or "").strip()
    if value:
        return value
    return str(record.metadata.get("planner_prompt_version") or DEFAULT_PLANNER_PROMPT_VERSION).strip()


def _planner_schema_version(record: PlannerReplayRecord) -> str:
    value = str(record.planner_schema_version or "").strip()
    if value:
        return value
    return str(record.metadata.get("planner_schema_version") or DEFAULT_PLANNER_SCHEMA_VERSION).strip()


def _plan_version(record: PlannerReplayRecord) -> int:
    try:
        value = int(record.plan_version or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else DEFAULT_PLAN_OUTPUT_VERSION


def _records_by_case(records: Sequence[PlannerReplayRecord]) -> dict[str, list[PlannerReplayRecord]]:
    grouped: dict[str, list[PlannerReplayRecord]] = {}
    for record in records:
        grouped.setdefault(record.case_name, []).append(record)
    return grouped


def _record_to_payload(record: PlannerReplayRecord) -> dict[str, Any]:
    return {
        "case_name": record.case_name,
        "user_input": record.user_input,
        "raw_output": record.raw_output,
        "elapsed_ms": int(record.elapsed_ms or 0),
        "provider": record.provider,
        "model": record.model,
        "error_code": record.error_code,
        "error_message": record.error_message,
        "metadata": dict(record.metadata or {}),
        "planner_prompt_version": _planner_prompt_version(record),
        "planner_schema_version": _planner_schema_version(record),
        "plan_version": _plan_version(record),
        "actions": list(record.actions or ()),
        "validation_result": str(record.validation_result or "").strip(),
        "diff_from_expected": list(record.diff_from_expected or ()),
        "runtime_actions": list(record.runtime_actions or ()),
        "runtime_validation_result": str(record.runtime_validation_result or "").strip(),
        "runtime_safe": record.runtime_safe,
        "runtime_diff_from_expected": list(record.runtime_diff_from_expected or ()),
    }


def _record_from_payload(payload: dict[str, Any], *, line_no: int) -> PlannerReplayRecord:
    case_name = str(payload.get("case_name") or "").strip()
    user_input = str(payload.get("user_input") or "").strip()
    if not case_name:
        raise ValueError(f"planner replay line {line_no} is missing case_name")
    if not user_input:
        raise ValueError(f"planner replay line {line_no} is missing user_input")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return PlannerReplayRecord(
        case_name=case_name,
        user_input=user_input,
        raw_output=str(payload.get("raw_output") or ""),
        elapsed_ms=max(0, int(payload.get("elapsed_ms") or 0)),
        provider=str(payload.get("provider") or "").strip(),
        model=str(payload.get("model") or "").strip(),
        error_code=str(payload.get("error_code") or "").strip(),
        error_message=str(payload.get("error_message") or "").strip(),
        metadata=dict(metadata),
        planner_prompt_version=str(payload.get("planner_prompt_version") or metadata.get("planner_prompt_version") or DEFAULT_PLANNER_PROMPT_VERSION).strip(),
        planner_schema_version=str(payload.get("planner_schema_version") or metadata.get("planner_schema_version") or DEFAULT_PLANNER_SCHEMA_VERSION).strip(),
        plan_version=max(1, int(payload.get("plan_version") or DEFAULT_PLAN_OUTPUT_VERSION)),
        actions=tuple(str(item or "").strip() for item in list(payload.get("actions") or []) if str(item or "").strip()),
        validation_result=str(payload.get("validation_result") or "").strip(),
        diff_from_expected=tuple(str(item or "").strip() for item in list(payload.get("diff_from_expected") or []) if str(item or "").strip()),
        runtime_actions=tuple(str(item or "").strip() for item in list(payload.get("runtime_actions") or []) if str(item or "").strip()),
        runtime_validation_result=str(payload.get("runtime_validation_result") or "").strip(),
        runtime_safe=payload.get("runtime_safe") if isinstance(payload.get("runtime_safe"), bool) else None,
        runtime_diff_from_expected=tuple(
            str(item or "").strip()
            for item in list(payload.get("runtime_diff_from_expected") or [])
            if str(item or "").strip()
        ),
    )


def _raw_signature(parsed: Mapping[str, Any] | None) -> str:
    if not isinstance(parsed, Mapping):
        return "{}"
    return json.dumps(dict(parsed), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _metadata_int(metadata: Mapping[str, Any], key: str) -> int:
    try:
        return int(metadata.get(key) or 0)
    except (TypeError, ValueError):
        return 0
