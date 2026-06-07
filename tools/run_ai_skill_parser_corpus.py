from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client.managers.ai_skill_parser import AISkillParser
from client.managers.ai_task_manager import AITaskManager
from client.services.ai_bootstrap import configure_default_ai_provider


DEFAULT_CORPUS_PATH = Path(__file__).with_name("ai_skill_golden_corpus.json")
DEFAULT_REPLAY_PATH = Path(__file__).with_name("ai_skill_parser_replay.jsonl")


@dataclass(frozen=True, slots=True)
class SkillParserCase:
    name: str
    user_input: str
    expectation: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SkillParserReplayRecord:
    case_name: str
    user_input: str
    expected: dict[str, Any]
    raw_output: str
    parsed: dict[str, Any] | None
    expectation_passed: bool
    check_messages: list[str]
    elapsed_ms: int
    provider: str = ""
    model: str = ""
    error_code: str = ""
    error_message: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run offline AI skill parser replay against the golden corpus.")
    parser.add_argument("--corpus-path", default=str(DEFAULT_CORPUS_PATH), help="Skill golden corpus JSON path.")
    parser.add_argument("--output-path", default=str(DEFAULT_REPLAY_PATH), help="JSONL replay output path.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum cases to run. 0 means all cases.")
    parser.add_argument("--model-path", default="", help="Optional GGUF model path or directory for this run.")
    parser.add_argument("--max-tokens", type=int, default=512, help="Maximum output tokens per parser request.")
    parser.add_argument("--strict", action="store_true", default=True, help="Use JSON response schema.")
    parser.add_argument("--no-strict", dest="strict", action="store_false", help="Disable JSON response schema.")
    return parser.parse_args()


async def run_skill_parser_corpus(
    cases: Sequence[SkillParserCase],
    *,
    parser: AISkillParser,
    task_manager: Any,
    output_path: str | Path | None = None,
    limit: int = 0,
    max_tokens: int = 512,
    strict: bool = True,
) -> list[SkillParserReplayRecord]:
    selected_cases = list(cases)
    if int(limit or 0) > 0:
        selected_cases = selected_cases[: int(limit)]

    records: list[SkillParserReplayRecord] = []
    for case in selected_cases:
        request = parser.build_request(case.user_input, max_tokens=max_tokens, strict=strict)
        started = time.perf_counter()
        try:
            snapshot = await task_manager.run_once(request)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            raw_output = str(getattr(snapshot, "content", "") or "")
            intent = parser.parse(raw_output)
            parsed = asdict(intent) if intent is not None else None
            passed, messages = evaluate_expectation(parsed, case.expectation)
            records.append(
                SkillParserReplayRecord(
                    case_name=case.name,
                    user_input=case.user_input,
                    expected=dict(case.expectation or {}),
                    raw_output=raw_output,
                    parsed=parsed,
                    expectation_passed=passed,
                    check_messages=messages,
                    elapsed_ms=elapsed_ms,
                    provider=str(getattr(snapshot, "provider", "") or ""),
                    model=str(getattr(snapshot, "model", "") or ""),
                    error_code=_error_code_value(getattr(snapshot, "error_code", "")),
                    error_message=str(getattr(snapshot, "error_message", "") or ""),
                )
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            records.append(
                SkillParserReplayRecord(
                    case_name=case.name,
                    user_input=case.user_input,
                    expected=dict(case.expectation or {}),
                    raw_output="",
                    parsed=None,
                    expectation_passed=False,
                    check_messages=[f"{type(exc).__name__}: {exc}"],
                    elapsed_ms=elapsed_ms,
                    error_code=type(exc).__name__,
                    error_message=str(exc),
                )
            )

    if output_path is not None:
        write_replay_records(output_path, records)
    return records


def load_skill_corpus(path: str | Path | None = None) -> list[SkillParserCase]:
    corpus_path = Path(path) if path is not None else DEFAULT_CORPUS_PATH
    payload = json.loads(corpus_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("skill corpus version must be 1")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("skill corpus cases must be a non-empty array")
    cases: list[SkillParserCase] = []
    seen_names: set[str] = set()
    for index, item in enumerate(raw_cases, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"skill corpus case #{index} must be an object")
        name = str(item.get("name") or "").strip()
        user_input = str(item.get("user_input") or "").strip()
        if not name or not user_input:
            raise ValueError(f"skill corpus case #{index} requires name and user_input")
        if name in seen_names:
            raise ValueError(f"duplicate case name: {name}")
        seen_names.add(name)
        expectation = item.get("expectation")
        cases.append(
            SkillParserCase(
                name=name,
                user_input=user_input,
                expectation=dict(expectation or {}) if isinstance(expectation, dict) else {},
            )
        )
    return cases


def evaluate_expectation(parsed: dict[str, Any] | None, expectation: dict[str, Any]) -> tuple[bool, list[str]]:
    messages: list[str] = []
    if not isinstance(parsed, dict):
        return False, ["parsed intent is empty"]
    expected_type = str(expectation.get("type") or "").strip()
    if expected_type and str(parsed.get("type") or "") != expected_type:
        messages.append(f"type mismatch: expected {expected_type}, got {parsed.get('type')}")
    expected_skill = str(expectation.get("skill") or "").strip()
    if expected_skill and str(parsed.get("skill") or "") != expected_skill:
        messages.append(f"skill mismatch: expected {expected_skill}, got {parsed.get('skill')}")
    expected_slots = expectation.get("slots") if isinstance(expectation.get("slots"), dict) else {}
    slots = parsed.get("slots") if isinstance(parsed.get("slots"), dict) else {}
    for key, expected_value in dict(expected_slots or {}).items():
        actual_value = slots.get(key)
        if actual_value != expected_value:
            messages.append(f"slot {key} mismatch: expected {expected_value!r}, got {actual_value!r}")
    return not messages, messages


def write_replay_records(path: str | Path, records: Sequence[SkillParserReplayRecord]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as writer:
        for record in records:
            writer.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True, default=str) + "\n")


def summarize_records(records: Sequence[SkillParserReplayRecord]) -> dict[str, Any]:
    total = len(records)
    passed = sum(1 for record in records if record.expectation_passed)
    by_type: dict[str, int] = {}
    for record in records:
        parsed_type = str((record.parsed or {}).get("type") or "")
        by_type[parsed_type] = by_type.get(parsed_type, 0) + 1
    return {
        "record_count": total,
        "expectation_passed_count": passed,
        "expectation_passed_rate": round(passed / total, 4) if total else 0,
        "parsed_types": by_type,
    }


async def main() -> None:
    args = parse_args()
    model_path = _clean_path(args.model_path)
    if model_path:
        os.environ["ASSISTIM_AI_PROVIDER"] = "local_gguf"
        os.environ["ASSISTIM_AI_MODEL_PATH"] = str(_resolve_model_path(model_path))
    configure_default_ai_provider()
    task_manager = AITaskManager()
    try:
        parser = AISkillParser()
        cases = load_skill_corpus(args.corpus_path)
        records = await run_skill_parser_corpus(
            cases,
            parser=parser,
            task_manager=task_manager,
            output_path=args.output_path,
            limit=max(0, int(args.limit or 0)),
            max_tokens=max(1, int(args.max_tokens or 512)),
            strict=bool(args.strict),
        )
        summary = summarize_records(records)
        summary["output_path"] = str(args.output_path)
        summary["corpus_path"] = str(args.corpus_path)
        summary["model_path"] = os.environ.get("ASSISTIM_AI_MODEL_PATH", "")
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    finally:
        await task_manager.close()


def _resolve_model_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_file():
        return path.resolve()
    if path.is_dir():
        candidates = sorted(path.glob("*.gguf")) or sorted(path.rglob("*.gguf"))
        if candidates:
            return candidates[0].resolve()
    raise FileNotFoundError(f"GGUF model not found from --model-path: {raw_path}")


def _clean_path(value: object) -> str:
    text = str(value or "").strip().strip('"').strip("'")
    for marker in ("\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\ufeff"):
        text = text.replace(marker, "")
    return text.strip()


def _error_code_value(value: Any) -> str:
    if value is None:
        return ""
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return str(enum_value)
    return str(value or "").strip()


if __name__ == "__main__":
    asyncio.run(main())
