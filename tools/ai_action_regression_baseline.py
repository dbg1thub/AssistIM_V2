from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


PLANNER_CORPUS_SCRIPT = Path("tools") / "run_ai_action_planner_corpus.py"
DEFAULT_VALIDATE_OUTPUT_PATH = Path("tools") / "ai_action_planner_replay_retained_actions_targeted.jsonl"
DEFAULT_VALIDATE_SUMMARY_PATH = Path("data") / "ai_action_diagnostics" / "retained_quality_summary.json"
DEFAULT_RUN_OUTPUT_PATH = Path("data") / "ai_action_diagnostics" / "ai_action_regression_replay.jsonl"
DEFAULT_RUN_SUMMARY_PATH = Path("data") / "ai_action_diagnostics" / "ai_action_regression_summary.json"


AI_ACTION_REGRESSION_CASES: tuple[str, ...] = (
    "server_user_get",
    "server_friend_list",
    "server_friend_request_list",
    "server_session_list",
    "server_session_get",
    "server_group_list",
    "server_group_get",
    "server_moment_list",
    "server_moment_get",
    "friend_request_accept",
)


@dataclass(frozen=True, slots=True)
class RegressionCommand:
    mode: str
    args: tuple[str, ...]
    output_path: Path
    summary_path: Path
    requires_model: bool


def build_validate_command(
    *,
    output_path: str | Path = DEFAULT_VALIDATE_OUTPUT_PATH,
    summary_path: str | Path = DEFAULT_VALIDATE_SUMMARY_PATH,
) -> RegressionCommand:
    replay_path = Path(output_path)
    report_path = Path(summary_path)
    return RegressionCommand(
        mode="validate",
        args=(
            _path_arg(PLANNER_CORPUS_SCRIPT),
            "--validate-only",
            "--quality-gate",
            "--output-path",
            _path_arg(replay_path),
            "--summary-path",
            _path_arg(report_path),
        ),
        output_path=replay_path,
        summary_path=report_path,
        requires_model=False,
    )


def build_run_command(
    *,
    output_path: str | Path = DEFAULT_RUN_OUTPUT_PATH,
    summary_path: str | Path = DEFAULT_RUN_SUMMARY_PATH,
    repeat: int = 1,
    cases: Sequence[str] = AI_ACTION_REGRESSION_CASES,
) -> RegressionCommand:
    replay_path = Path(output_path)
    report_path = Path(summary_path)
    args: list[str] = [
        _path_arg(PLANNER_CORPUS_SCRIPT),
        "--workflow-repair",
        "--quality-gate",
        "--output-path",
        _path_arg(replay_path),
        "--summary-path",
        _path_arg(report_path),
        "--repeat",
        str(max(1, int(repeat or 1))),
    ]
    for case_name in _case_names(cases):
        args.extend(["--case", case_name])
    return RegressionCommand(
        mode="run",
        args=tuple(args),
        output_path=replay_path,
        summary_path=report_path,
        requires_model=True,
    )


def command_to_powershell(command: RegressionCommand, *, python_executable: str = "python") -> str:
    return " ".join([_quote_arg(python_executable), *(_quote_arg(arg) for arg in command.args)])


def _case_names(cases: Sequence[str]) -> tuple[str, ...]:
    names: list[str] = []
    for raw_name in cases:
        name = str(raw_name or "").strip()
        if name and name not in names:
            names.append(name)
    return tuple(names)


def _path_arg(path: Path) -> str:
    return path.as_posix()


def _quote_arg(value: str) -> str:
    text = str(value)
    if not text or any(char.isspace() for char in text):
        return '"' + text.replace('"', '\\"') + '"'
    return text
