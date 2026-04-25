"""Offline evaluator for model-driven AI action router samples.

The router is only a classifier. It must not emit executable plans, tools, or
action steps. Runtime execution still belongs to the planner, normalizer, and
executor pipeline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
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
ROUTER_SCHEMA_VERSION = "route_v1"
ROUTER_MAX_OUTPUT_CHARS = 512
ROUTER_MAX_TOKENS = 96

ROUTER_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "route": {"type": "string", "enum": [ROUTE_CHAT, ROUTE_ACTION_CANDIDATE, ROUTE_UNKNOWN]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reason": {"type": "string"},
    },
    "required": ["route", "confidence", "reason"],
    "additionalProperties": False,
}


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


@dataclass(frozen=True, slots=True)
class RouterReplayRecord:
    case_name: str
    user_input: str
    expected_route: str
    raw_output: str
    elapsed_ms: int = 0
    provider: str = ""
    model: str = ""
    error_code: str = ""
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def build_router_request(case: PromptBenchmarkCase):
    """Build one local AI request for offline router replay."""
    from client.services.ai_service import AIPrivacyScope, AIRequest, AITaskType

    return AIRequest(
        task_type=AITaskType.CHAT,
        privacy_scope=AIPrivacyScope.GENERAL,
        must_be_local=True,
        stream=False,
        temperature=0.0,
        max_tokens=ROUTER_MAX_TOKENS,
        max_output_chars=ROUTER_MAX_OUTPUT_CHARS,
        response_format={"type": "json_object", "schema": ROUTER_OUTPUT_SCHEMA},
        system_prompt=build_router_system_prompt(),
        messages=[{"role": "user", "content": build_router_user_prompt(case.user_input)}],
        metadata={
            "source": "ai_action_router_corpus",
            "router_schema": ROUTER_SCHEMA_VERSION,
            "router_case_name": case.name,
        },
    )


def build_router_system_prompt() -> str:
    """Return the model-only router prompt used for offline corpus replay."""
    return (
        "你是 AssistIM 的 AI action Router，只负责判断用户输入是否需要进入 action planner。\n"
        "只输出一个 JSON 对象，不要输出 Markdown、解释段落或多余文本。\n"
        f'route 只能是 "{ROUTE_CHAT}"、"{ROUTE_ACTION_CANDIDATE}"、"{ROUTE_UNKNOWN}" 之一。\n'
        f'"{ROUTE_CHAT}" 表示普通聊天、问答、解释概念或闲聊，不需要执行工具。\n'
        f'"{ROUTE_ACTION_CANDIDATE}" 表示可能需要查询聊天记忆、总结历史、处理附件信息或准备发送消息，应交给 planner。\n'
        f'"{ROUTE_UNKNOWN}" 表示意图不明确或置信度不足。\n'
        '输出字段固定为 {"route": string, "confidence": number, "reason": string}。\n'
        "confidence 必须是 0 到 1 的数字，reason 不超过 30 个中文字符。\n"
        "不要输出 steps、action、actions、args、plan、tool、tools、final、depends_on。\n"
        "不要输出 message.send、message.draft、contact.resolve、memory.search、memory.summarize、user.confirm。\n"
        "不要解析联系人，不要生成执行计划，不要决定具体业务动作。"
    )


def build_router_user_prompt(user_input: str) -> str:
    return f"用户输入：{str(user_input or '').strip()}"


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
    """Return router ground truth, with a fallback for older corpus cases."""
    configured_route = str(getattr(case, "router_expected_route", "") or "").strip().lower()
    if configured_route:
        route = _normalize_route(configured_route)
        if route == ROUTE_UNKNOWN and configured_route != ROUTE_UNKNOWN:
            raise ValueError(f"invalid router_expected_route for case {case.name}: {configured_route}")
        return route
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


def evaluate_router_replay_file(
    cases: Sequence[PromptBenchmarkCase],
    path: str | Path,
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> list[RouterCaseResult]:
    records = load_router_replay_records(path)
    return evaluate_router_samples(cases, _outputs_by_case(records), min_confidence=min_confidence)


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


def write_router_replay_records(path: str | Path, records: Sequence[RouterReplayRecord]) -> None:
    replay_path = Path(path)
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    with replay_path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(_record_to_payload(record), ensure_ascii=False, sort_keys=True) + "\n")


def load_router_replay_records(path: str | Path) -> list[RouterReplayRecord]:
    replay_path = Path(path)
    records: list[RouterReplayRecord] = []
    try:
        lines = replay_path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError as exc:
        raise ValueError(f"router replay file not found: {replay_path}") from exc
    for line_no, line in enumerate(lines, start=1):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"router replay line {line_no} is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"router replay line {line_no} must be an object")
        records.append(_record_from_payload(payload, line_no=line_no))
    return records


def _normalize_route(value: Any) -> str:
    route = str(value or "").strip().lower()
    return route if route in ALLOWED_ROUTES else ROUTE_UNKNOWN


def _outputs_by_case(records: Sequence[RouterReplayRecord]) -> dict[str, list[str]]:
    outputs: dict[str, list[str]] = {}
    for record in records:
        outputs.setdefault(record.case_name, []).append(record.raw_output)
    return outputs


def _record_to_payload(record: RouterReplayRecord) -> dict[str, Any]:
    return {
        "case_name": record.case_name,
        "user_input": record.user_input,
        "expected_route": record.expected_route,
        "raw_output": record.raw_output,
        "elapsed_ms": int(record.elapsed_ms or 0),
        "provider": record.provider,
        "model": record.model,
        "error_code": record.error_code,
        "error_message": record.error_message,
        "metadata": dict(record.metadata or {}),
    }


def _record_from_payload(payload: dict[str, Any], *, line_no: int) -> RouterReplayRecord:
    case_name = str(payload.get("case_name") or "").strip()
    user_input = str(payload.get("user_input") or "").strip()
    expected_route = _normalize_route(payload.get("expected_route"))
    if not case_name:
        raise ValueError(f"router replay line {line_no} is missing case_name")
    if not user_input:
        raise ValueError(f"router replay line {line_no} is missing user_input")
    if expected_route == ROUTE_UNKNOWN and str(payload.get("expected_route") or "").strip().lower() != ROUTE_UNKNOWN:
        raise ValueError(f"router replay line {line_no} has invalid expected_route")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return RouterReplayRecord(
        case_name=case_name,
        user_input=user_input,
        expected_route=expected_route,
        raw_output=str(payload.get("raw_output") or ""),
        elapsed_ms=max(0, int(payload.get("elapsed_ms") or 0)),
        provider=str(payload.get("provider") or "").strip(),
        model=str(payload.get("model") or "").strip(),
        error_code=str(payload.get("error_code") or "").strip(),
        error_message=str(payload.get("error_message") or "").strip(),
        metadata=dict(metadata),
    )


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
