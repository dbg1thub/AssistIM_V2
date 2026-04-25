"""Offline evaluator for model-driven AI action router samples.

The router is only a classifier. It must not emit executable plans, tools, or
action steps. Runtime execution still belongs to the planner, normalizer, and
executor pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from tools.ai_action_prompt_benchmark import PromptBenchmarkCase, parse_plan_json


ROUTE_CHAT = "chat"
ROUTE_ACTION_CANDIDATE = "action_candidate"
ROUTE_UNKNOWN = "unknown"

ALLOWED_ROUTES = frozenset({ROUTE_CHAT, ROUTE_ACTION_CANDIDATE, ROUTE_UNKNOWN})
ALLOWED_TOP_LEVEL_FIELDS = frozenset({"route", "confidence", "reason"})
FORBIDDEN_ROUTER_FIELDS = frozenset(
    {
        "action",
        "actions",
        "args",
        "contact.resolve",
        "depends_on",
        "execute",
        "execution",
        "final",
        "memory.search",
        "memory.summarize",
        "message.draft",
        "message.send",
        "plan",
        "step",
        "steps",
        "tool",
        "tools",
        "user.confirm",
    }
)
DEFAULT_MIN_CONFIDENCE = 0.6


@dataclass(frozen=True, slots=True)
class RouterSampleResult:
    raw_output: str
    parsed_output: dict[str, Any] | None
    valid_json: bool
    accepted_schema: bool
    route: str
    effective_route: str
    confidence: float
    reason: str
    unsafe_output: bool
    messages: list[str]
    route_matches: bool | None = None


@dataclass(frozen=True, slots=True)
class RouterCaseResult:
    case: PromptBenchmarkCase
    expected_route: str
    samples: list[RouterSampleResult]


def parse_router_output(raw_output: str, *, min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> RouterSampleResult:
    """Parse and validate one saved model router output."""
    raw_text = str(raw_output or "")
    parsed, valid_json = parse_plan_json(raw_text)
    if not valid_json or parsed is None:
        return RouterSampleResult(
            raw_output=raw_text,
            parsed_output=None,
            valid_json=False,
            accepted_schema=False,
            route=ROUTE_UNKNOWN,
            effective_route=ROUTE_UNKNOWN,
            confidence=0.0,
            reason="",
            unsafe_output=False,
            messages=["invalid json"],
        )

    messages: list[str] = []
    forbidden_fields = _forbidden_fields(parsed)
    for field in forbidden_fields:
        _append_once(messages, f"forbidden router field: {field}")

    unexpected_fields = [
        str(key)
        for key in parsed
        if str(key) not in ALLOWED_TOP_LEVEL_FIELDS and str(key) not in forbidden_fields
    ]
    for field in unexpected_fields:
        _append_once(messages, f"unexpected router field: {field}")

    route = _normalize_route(parsed.get("route"))
    raw_route = str(parsed.get("route") or "").strip()
    if not raw_route:
        _append_once(messages, "missing route")
    elif route == ROUTE_UNKNOWN and raw_route.lower() not in ALLOWED_ROUTES:
        _append_once(messages, "invalid route")

    confidence, confidence_ok = _coerce_confidence(parsed.get("confidence"))
    if not confidence_ok:
        _append_once(messages, "invalid confidence")

    reason = str(parsed.get("reason") or "").strip()
    if not reason:
        _append_once(messages, "missing reason")

    unsafe_output = bool(forbidden_fields)
    accepted_schema = (
        valid_json
        and not unsafe_output
        and not unexpected_fields
        and raw_route.lower() in ALLOWED_ROUTES
        and confidence_ok
        and bool(reason)
    )
    effective_route = route if accepted_schema else ROUTE_UNKNOWN
    if accepted_schema and confidence < float(min_confidence):
        effective_route = ROUTE_UNKNOWN
        _append_once(messages, "confidence below threshold")

    return RouterSampleResult(
        raw_output=raw_text,
        parsed_output=parsed,
        valid_json=True,
        accepted_schema=accepted_schema,
        route=route,
        effective_route=effective_route,
        confidence=confidence,
        reason=reason,
        unsafe_output=unsafe_output,
        messages=messages,
    )


def expected_route_for_case(case: PromptBenchmarkCase) -> str:
    """Derive router ground truth from the golden corpus expectation."""
    is_action = case.expectation.is_action
    if is_action is True:
        return ROUTE_ACTION_CANDIDATE
    if is_action is False:
        return ROUTE_CHAT
    return ROUTE_UNKNOWN


def evaluate_router_samples(
    cases: Sequence[PromptBenchmarkCase],
    outputs_by_case: Mapping[str, Sequence[str]],
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> list[RouterCaseResult]:
    """Evaluate saved router outputs against golden corpus cases."""
    results: list[RouterCaseResult] = []
    for case in cases:
        expected_route = expected_route_for_case(case)
        samples: list[RouterSampleResult] = []
        for raw_output in list(outputs_by_case.get(case.name, ())):
            sample = parse_router_output(raw_output, min_confidence=min_confidence)
            route_matches = sample.effective_route == expected_route
            messages = list(sample.messages)
            if not route_matches:
                _append_once(messages, "route mismatch")
            samples.append(replace(sample, route_matches=route_matches, messages=messages))
        results.append(RouterCaseResult(case=case, expected_route=expected_route, samples=samples))
    return results


def summarize_router_results(results: Sequence[RouterCaseResult]) -> dict[str, Any]:
    samples = [sample for result in results for sample in list(result.samples or [])]
    return {
        "case_count": len(results),
        "sample_count": len(samples),
        "valid_json_rate": _rate(sum(1 for sample in samples if sample.valid_json), len(samples)),
        "accepted_schema_rate": _rate(sum(1 for sample in samples if sample.accepted_schema), len(samples)),
        "route_accuracy": _rate(sum(1 for sample in samples if sample.route_matches is True), len(samples)),
        "fallback_rate": _rate(sum(1 for sample in samples if sample.effective_route == ROUTE_UNKNOWN), len(samples)),
        "unsafe_output_count": sum(1 for sample in samples if sample.unsafe_output),
        "failed_cases": _failed_cases(results),
        "cases": [_summarize_case(result) for result in results],
    }


def _normalize_route(value: Any) -> str:
    route = str(value or "").strip().lower()
    return route if route in ALLOWED_ROUTES else ROUTE_UNKNOWN


def _coerce_confidence(value: Any) -> tuple[float, bool]:
    if isinstance(value, bool):
        return 0.0, False
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0, False
    if confidence < 0.0 or confidence > 1.0:
        return confidence, False
    return round(confidence, 4), True


def _forbidden_fields(value: Any) -> list[str]:
    fields: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                text = str(key)
                if text in FORBIDDEN_ROUTER_FIELDS and text not in fields:
                    fields.append(text)
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return fields


def _summarize_case(result: RouterCaseResult) -> dict[str, Any]:
    samples = list(result.samples or [])
    return {
        "name": result.case.name,
        "expected_route": result.expected_route,
        "sample_count": len(samples),
        "accepted_schema_rate": _rate(sum(1 for sample in samples if sample.accepted_schema), len(samples)),
        "route_accuracy": _rate(sum(1 for sample in samples if sample.route_matches is True), len(samples)),
        "fallback_rate": _rate(sum(1 for sample in samples if sample.effective_route == ROUTE_UNKNOWN), len(samples)),
        "unsafe_output_count": sum(1 for sample in samples if sample.unsafe_output),
    }


def _failed_cases(results: Sequence[RouterCaseResult]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    for result in results:
        failed_samples = [
            sample
            for sample in list(result.samples or [])
            if sample.route_matches is False or not sample.accepted_schema
        ]
        if not failed_samples:
            continue
        messages: list[str] = []
        for sample in failed_samples:
            for message in list(sample.messages or []):
                _append_once(messages, str(message or "").strip())
        failed.append(
            {
                "name": result.case.name,
                "failed_sample_count": len(failed_samples),
                "messages": messages,
            }
        )
    return failed


def _append_once(items: list[str], text: str) -> None:
    if text and text not in items:
        items.append(text)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)
