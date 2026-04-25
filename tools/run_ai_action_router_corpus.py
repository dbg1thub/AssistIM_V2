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
from tools.ai_action_prompt_benchmark import DEFAULT_GOLDEN_CORPUS_PATH, PromptBenchmarkCase, load_golden_corpus
from tools.ai_action_router_evaluator import (
    RouterReplayRecord,
    build_router_request,
    evaluate_router_replay_file,
    expected_route_for_case,
    summarize_router_results,
    write_router_replay_records,
)


DEFAULT_ROUTER_REPLAY_PATH = Path(__file__).with_name("ai_action_router_replay.jsonl")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run offline AI action router replay against the golden corpus.")
    parser.add_argument("--corpus-path", default=str(DEFAULT_GOLDEN_CORPUS_PATH), help="Golden corpus JSON path.")
    parser.add_argument("--output-path", default=str(DEFAULT_ROUTER_REPLAY_PATH), help="JSONL replay output path.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum cases to run. 0 means all cases.")
    parser.add_argument("--min-confidence", type=float, default=0.6, help="Minimum confidence used by the summary evaluator.")
    return parser.parse_args()


async def run_router_corpus(
    cases: Sequence[PromptBenchmarkCase],
    *,
    task_manager: Any,
    output_path: str | Path | None = None,
    limit: int = 0,
) -> list[RouterReplayRecord]:
    selected_cases = list(cases)
    if int(limit or 0) > 0:
        selected_cases = selected_cases[: int(limit)]

    records: list[RouterReplayRecord] = []
    for case in selected_cases:
        request = build_router_request(case)
        started = time.perf_counter()
        try:
            snapshot = await task_manager.run_once(request)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            records.append(
                RouterReplayRecord(
                    case_name=case.name,
                    user_input=case.user_input,
                    expected_route=expected_route_for_case(case),
                    raw_output=str(getattr(snapshot, "content", "") or ""),
                    elapsed_ms=elapsed_ms,
                    provider=str(getattr(snapshot, "provider", "") or ""),
                    model=str(getattr(snapshot, "model", "") or ""),
                    error_code=_error_code_value(getattr(snapshot, "error_code", "")),
                    error_message=str(getattr(snapshot, "error_message", "") or ""),
                    metadata={"router_schema": str(request.metadata.get("router_schema") or "")},
                )
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            records.append(
                RouterReplayRecord(
                    case_name=case.name,
                    user_input=case.user_input,
                    expected_route=expected_route_for_case(case),
                    raw_output="",
                    elapsed_ms=elapsed_ms,
                    error_code=type(exc).__name__,
                    error_message=str(exc),
                    metadata={"router_schema": str(request.metadata.get("router_schema") or "")},
                )
            )

    if output_path is not None:
        write_router_replay_records(output_path, records)
    return records


async def main() -> None:
    args = parse_args()
    configure_default_ai_provider()
    task_manager = AITaskManager()
    try:
        corpus_path = Path(args.corpus_path)
        output_path = Path(args.output_path)
        cases = load_golden_corpus(corpus_path)
        records = await run_router_corpus(
            cases,
            task_manager=task_manager,
            output_path=output_path,
            limit=max(0, int(args.limit or 0)),
        )
        results = evaluate_router_replay_file(cases, output_path, min_confidence=float(args.min_confidence))
        summary = summarize_router_results(results)
        summary["output_path"] = str(output_path)
        summary["replay_record_count"] = len(records)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    finally:
        await task_manager.close()


def _error_code_value(value: Any) -> str:
    if value is None:
        return ""
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return str(enum_value)
    return str(value or "").strip()


if __name__ == "__main__":
    asyncio.run(main())
