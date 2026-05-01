from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client.managers.ai_task_manager import AITaskManager
from client.services.ai_bootstrap import configure_default_ai_provider
from tools.ai_action_planner_replay import (
    DEFAULT_PLANNER_REPLAY_PATH,
    PlannerReplayRecord,
    annotate_planner_replay_records,
    build_planner_request,
    evaluate_planner_replay_file,
    write_planner_replay_records,
)
from tools.ai_action_prompt_benchmark import DEFAULT_GOLDEN_CORPUS_PATH, PromptBenchmarkCase, load_golden_corpus, summarize_results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run offline AI action planner replay against the golden corpus.")
    parser.add_argument("--corpus-path", default=str(DEFAULT_GOLDEN_CORPUS_PATH), help="Golden corpus JSON path.")
    parser.add_argument("--output-path", default=str(DEFAULT_PLANNER_REPLAY_PATH), help="JSONL replay output path.")
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
    return parser.parse_args()


async def run_planner_corpus(
    cases: Sequence[PromptBenchmarkCase],
    *,
    task_manager: Any,
    output_path: str | Path | None = None,
    limit: int = 0,
    case_names: Sequence[str] = (),
    repeat: int = 1,
) -> list[PlannerReplayRecord]:
    selected_cases = _select_cases(cases, case_names=case_names)
    if int(limit or 0) > 0:
        selected_cases = selected_cases[: int(limit)]
    sample_count = max(1, int(repeat or 1))

    records: list[PlannerReplayRecord] = []
    for case in selected_cases:
        for iteration in range(1, sample_count + 1):
            request = build_planner_request(case)
            request.metadata["planner_case_iteration"] = iteration
            request.metadata["planner_case_repeat"] = sample_count
            started = time.perf_counter()
            try:
                snapshot = await task_manager.run_once(request)
                elapsed_ms = int((time.perf_counter() - started) * 1000)
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
                        metadata=_record_metadata(request),
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
                        metadata=_record_metadata(request),
                        planner_schema_version=str(request.metadata.get("planner_schema_version") or ""),
                        planner_prompt_version=str(request.metadata.get("planner_prompt_version") or ""),
                    )
                )

    records = annotate_planner_replay_records(selected_cases, records)
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
        summary = validate_planner_replay(evaluation_cases, output_path)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
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
        )
        results = evaluate_planner_replay_file(evaluation_cases, output_path)
        summary = summarize_results(results)
        summary["output_path"] = str(output_path)
        summary["replay_record_count"] = len(records)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    finally:
        await task_manager.close()


def validate_planner_replay(cases: Sequence[PromptBenchmarkCase], output_path: str | Path) -> dict[str, Any]:
    """Evaluate a saved planner replay JSONL without invoking the AI runtime."""
    results = evaluate_planner_replay_file(cases, output_path)
    summary = summarize_results(results)
    summary["output_path"] = str(output_path)
    summary["replay_record_count"] = sum(len(result.samples) for result in results)
    summary["mode"] = "validate_only"
    return summary


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
        "prompt_chars": int(metadata.get("prompt_chars") or 0),
        "planner_case_iteration": int(metadata.get("planner_case_iteration") or 1),
        "planner_case_repeat": int(metadata.get("planner_case_repeat") or 1),
    }


def _error_code_value(value: Any) -> str:
    if value is None:
        return ""
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return str(enum_value)
    return str(value or "").strip()


if __name__ == "__main__":
    asyncio.run(main())
