from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client.managers.ai_task_manager import AITaskManager
from client.services.ai_bootstrap import configure_default_ai_provider
from tools.ai_action_planner_replay import (
    DEFAULT_PLANNER_REPLAY_PATH,
    PlannerReplayRecord,
    annotate_planner_replay_records_with_workflow_repair,
    annotate_planner_replay_records,
    build_candidate_selector_request,
    build_planner_request,
    evaluate_planner_replay_file,
    parse_candidate_selection_json,
    write_planner_replay_records,
)
from tools.ai_action_prompt_benchmark import DEFAULT_GOLDEN_CORPUS_PATH, PromptBenchmarkCase, load_golden_corpus, summarize_results


QUALITY_GATE_THRESHOLDS: tuple[tuple[str, float], ...] = (
    ("runtime_expectation_pass_rate", 1.0),
    ("runtime_safe_rate", 1.0),
    ("workflow_repair_expectation_pass_rate", 1.0),
    ("workflow_repair_safe_rate", 1.0),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run offline AI action planner replay against the golden corpus.")
    parser.add_argument("--corpus-path", default=str(DEFAULT_GOLDEN_CORPUS_PATH), help="Golden corpus JSON path.")
    parser.add_argument("--output-path", default=str(DEFAULT_PLANNER_REPLAY_PATH), help="JSONL replay output path.")
    parser.add_argument(
        "--summary-path",
        default="",
        help="Optional JSON summary report path. When omitted, only prints the summary.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Maximum cases to run. 0 means all cases.")
    parser.add_argument("--repeat", type=int, default=1, help="Number of samples to run per selected case.")
    parser.add_argument(
        "--case",
        dest="case_names",
        action="append",
        default=[],
        help="Run only a named golden case. Can be passed multiple times.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate an existing JSONL replay file without running a local model.",
    )
    parser.add_argument(
        "--workflow-repair",
        action="store_true",
        help="During model runs, also evaluate repairable invalid plans through the workflow repair prompt.",
    )
    parser.add_argument(
        "--quality-gate",
        action="store_true",
        help="Fail unless runtime and workflow repair quality metrics meet the strict baseline.",
    )
    return parser.parse_args()


async def run_planner_corpus(
    cases: Sequence[PromptBenchmarkCase],
    *,
    task_manager: Any,
    output_path: str | Path | None = None,
    limit: int = 0,
    case_names: Sequence[str] = (),
    repeat: int = 1,
    workflow_repair: bool = False,
) -> list[PlannerReplayRecord]:
    selected_cases = _select_cases(cases, case_names=case_names)
    if int(limit or 0) > 0:
        selected_cases = selected_cases[: int(limit)]
    sample_count = max(1, int(repeat or 1))

    records: list[PlannerReplayRecord] = []
    for case in selected_cases:
        for iteration in range(1, sample_count + 1):
            selector_request = build_candidate_selector_request(case)
            selector_request.metadata["planner_case_iteration"] = iteration
            selector_request.metadata["planner_case_repeat"] = sample_count
            started = time.perf_counter()
            try:
                selector_snapshot = await task_manager.run_once(selector_request)
                selector_elapsed_ms = int((time.perf_counter() - started) * 1000)
                selector_raw = str(getattr(selector_snapshot, "content", "") or "")
                selection = parse_candidate_selection_json(
                    selector_raw,
                    registered_action_names=selector_request.response_format["schema"]["properties"]["candidate_actions"]["items"].get("enum", ()),
                )
                candidate_action_names = selection.candidate_actions if selection is not None and selection.is_action else ()
                candidate_selector_fallback = selection is None or not candidate_action_names
                request = build_planner_request(case, candidate_action_names=candidate_action_names)
                request.metadata["planner_case_iteration"] = iteration
                request.metadata["planner_case_repeat"] = sample_count
                snapshot = await task_manager.run_once(request)
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                metadata = _record_metadata(request)
                metadata["candidate_raw_output"] = selector_raw
                metadata["candidate_elapsed_ms"] = selector_elapsed_ms
                metadata["candidate_selector_fallback"] = candidate_selector_fallback
                metadata["candidate_selector_invalid"] = selection is None
                metadata["candidate_selector_is_action"] = selection.is_action if selection is not None else None
                records.append(
                    PlannerReplayRecord(
                        case_name=case.name,
                        user_input=case.user_input,
                        raw_output=str(getattr(snapshot, "content", "") or ""),
                        elapsed_ms=elapsed_ms,
                        provider=str(getattr(snapshot, "provider", "") or ""),
                        model=str(getattr(snapshot, "model", "") or ""),
                        error_code=_error_code_value(getattr(snapshot, "error_code", "")),
                        error_message=str(getattr(snapshot, "error_message", "") or ""),
                        metadata=metadata,
                        planner_schema_version=str(request.metadata.get("planner_schema_version") or ""),
                        planner_prompt_version=str(request.metadata.get("planner_prompt_version") or ""),
                    )
                )
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                records.append(
                    PlannerReplayRecord(
                        case_name=case.name,
                        user_input=case.user_input,
                        raw_output="",
                        elapsed_ms=elapsed_ms,
                        error_code=type(exc).__name__,
                        error_message=str(exc),
                        metadata=_record_metadata(selector_request),
                        planner_schema_version=str(selector_request.metadata.get("candidate_schema_version") or ""),
                        planner_prompt_version=str(selector_request.metadata.get("candidate_prompt_version") or ""),
                    )
                )

    records = annotate_planner_replay_records(selected_cases, records)
    if workflow_repair:
        records = await annotate_planner_replay_records_with_workflow_repair(
            selected_cases,
            records,
            task_manager=task_manager,
        )
    if output_path is not None:
        write_planner_replay_records(output_path, records)
    return records


async def main() -> None:
    args = parse_args()
    corpus_path = Path(args.corpus_path)
    output_path = Path(args.output_path)
    cases = load_golden_corpus(corpus_path)
    evaluation_cases = _select_cases(cases, case_names=tuple(args.case_names or ()))
    if args.validate_only:
        summary = validate_planner_replay(
            evaluation_cases,
            output_path,
            summary_path=args.summary_path or None,
            quality_gate=bool(args.quality_gate),
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        if quality_gate_exit_code(summary):
            raise SystemExit(1)
        return
    configure_default_ai_provider()
    task_manager = AITaskManager()
    try:
        records = await run_planner_corpus(
            cases,
            task_manager=task_manager,
            output_path=output_path,
            limit=max(0, int(args.limit or 0)),
            case_names=tuple(args.case_names or ()),
            repeat=max(1, int(args.repeat or 1)),
            workflow_repair=bool(args.workflow_repair),
        )
        results = evaluate_planner_replay_file(evaluation_cases, output_path)
        summary = summarize_results(results)
        summary["output_path"] = str(output_path)
        summary["replay_record_count"] = len(records)
        if args.quality_gate:
            summary["quality_gate"] = evaluate_quality_gate(summary)
        if args.summary_path:
            write_planner_replay_summary(args.summary_path, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        if quality_gate_exit_code(summary):
            raise SystemExit(1)
    finally:
        await task_manager.close()


def validate_planner_replay(
    cases: Sequence[PromptBenchmarkCase],
    output_path: str | Path,
    *,
    summary_path: str | Path | None = None,
    quality_gate: bool = False,
) -> dict[str, Any]:
    """Evaluate a saved planner replay JSONL without invoking the AI runtime."""
    results = evaluate_planner_replay_file(cases, output_path)
    summary = summarize_results(results)
    summary["output_path"] = str(output_path)
    summary["replay_record_count"] = sum(len(result.samples) for result in results)
    summary["mode"] = "validate_only"
    if quality_gate:
        summary["quality_gate"] = evaluate_quality_gate(summary)
    if summary_path is not None:
        write_planner_replay_summary(summary_path, summary)
    return summary


def evaluate_quality_gate(
    summary: Mapping[str, Any],
    *,
    thresholds: Sequence[tuple[str, float]] = QUALITY_GATE_THRESHOLDS,
) -> dict[str, Any]:
    """Evaluate strict planner replay quality thresholds against a summary."""
    checked_metrics: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    missing_case_samples = _missing_case_samples(summary)
    for metric, expected_min in thresholds:
        expected_value = float(expected_min)
        raw_actual = summary.get(metric)
        if raw_actual is None:
            failure = {
                "metric": metric,
                "actual": None,
                "expected_min": expected_value,
                "reason": "missing_metric",
            }
            checked_metrics.append(dict(failure))
            failures.append(failure)
            continue
        try:
            actual = float(raw_actual)
        except (TypeError, ValueError):
            actual = None
        if actual is None:
            failure = {
                "metric": metric,
                "actual": None,
                "expected_min": expected_value,
                "reason": "invalid_metric",
            }
            checked_metrics.append(dict(failure))
            failures.append(failure)
            continue
        passed = actual >= expected_value
        item = {
            "metric": metric,
            "actual": round(actual, 4),
            "expected_min": expected_value,
            "passed": passed,
        }
        checked_metrics.append(item)
        if not passed:
            failures.append(
                {
                    "metric": metric,
                    "actual": round(actual, 4),
                    "expected_min": expected_value,
                    "reason": "below_threshold",
                }
            )
    return {
        "enabled": True,
        "passed": not failures and not missing_case_samples,
        "thresholds": {metric: float(value) for metric, value in thresholds},
        "checked_metrics": checked_metrics,
        "missing_case_samples": missing_case_samples,
        "failures": failures,
    }


def quality_gate_exit_code(summary: Mapping[str, Any]) -> int:
    gate = summary.get("quality_gate") if isinstance(summary, Mapping) else None
    if not isinstance(gate, Mapping):
        return 0
    if gate.get("enabled") is True and gate.get("passed") is not True:
        return 1
    return 0


def _missing_case_samples(summary: Mapping[str, Any]) -> list[str]:
    raw_cases = summary.get("cases")
    if not isinstance(raw_cases, list):
        return []
    missing: list[str] = []
    for item in raw_cases:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        try:
            sample_count = int(item.get("sample_count") or 0)
        except (TypeError, ValueError):
            sample_count = 0
        if name and sample_count <= 0:
            missing.append(name)
    return missing


def write_planner_replay_summary(path: str | Path, summary: Mapping[str, Any]) -> None:
    """Write a deterministic JSON summary beside replay JSONL output."""
    summary_path = Path(path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(dict(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _select_cases(
    cases: Sequence[PromptBenchmarkCase],
    *,
    case_names: Sequence[str],
) -> list[PromptBenchmarkCase]:
    selected_names: list[str] = []
    for raw_name in case_names or ():
        name = str(raw_name or "").strip()
        if name and name not in selected_names:
            selected_names.append(name)
    if not selected_names:
        return list(cases)
    cases_by_name = {case.name: case for case in cases}
    missing = [name for name in selected_names if name not in cases_by_name]
    if missing:
        raise ValueError(f"unknown golden case name: {', '.join(missing)}")
    return [cases_by_name[name] for name in selected_names]


def _record_metadata(request: Any) -> dict[str, Any]:
    metadata = dict(getattr(request, "metadata", {}) or {})
    return {
        "planner_schema_version": str(metadata.get("planner_schema_version") or ""),
        "planner_prompt_version": str(metadata.get("planner_prompt_version") or ""),
        "planner_prompt_kind": str(metadata.get("planner_prompt_kind") or ""),
        "candidate_schema_version": str(metadata.get("candidate_schema_version") or ""),
        "candidate_prompt_version": str(metadata.get("candidate_prompt_version") or ""),
        "candidate_actions": list(metadata.get("candidate_actions") or []),
        "candidate_action_closure": list(metadata.get("candidate_action_closure") or []),
        "prompt_chars": int(metadata.get("prompt_chars") or 0),
        "planner_case_iteration": int(metadata.get("planner_case_iteration") or 1),
        "planner_case_repeat": int(metadata.get("planner_case_repeat") or 1),
    }


def _not_action_plan_json(selection: Any) -> str:
    return json.dumps(
        {
            "is_action": False,
            "goal": str(getattr(selection, "goal", "") or ""),
            "risk": "low",
            "steps": [],
            "final": {"reason": str(getattr(selection, "reason", "") or "")},
        },
        ensure_ascii=False,
    )


def _error_code_value(value: Any) -> str:
    if value is None:
        return ""
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return str(enum_value)
    return str(value or "").strip()


if __name__ == "__main__":
    asyncio.run(main())
