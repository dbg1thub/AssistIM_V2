from __future__ import annotations

from pathlib import Path

from tools.ai_action_regression_baseline import (
    AI_ACTION_REGRESSION_CASES,
    DEFAULT_RUN_OUTPUT_PATH,
    DEFAULT_RUN_SUMMARY_PATH,
    DEFAULT_VALIDATE_OUTPUT_PATH,
    DEFAULT_VALIDATE_SUMMARY_PATH,
    build_run_command,
    build_validate_command,
    command_to_powershell,
)


def test_ai_action_regression_validate_command_uses_existing_replay_and_quality_gate() -> None:
    command = build_validate_command()

    assert command.mode == "validate"
    assert command.requires_model is False
    assert command.output_path == DEFAULT_VALIDATE_OUTPUT_PATH
    assert command.summary_path == DEFAULT_VALIDATE_SUMMARY_PATH
    assert command.args[:2] == ("tools/run_ai_action_planner_corpus.py", "--validate-only")
    assert "--quality-gate" in command.args
    assert command.args[command.args.index("--output-path") + 1] == DEFAULT_VALIDATE_OUTPUT_PATH.as_posix()
    assert command.args[command.args.index("--summary-path") + 1] == DEFAULT_VALIDATE_SUMMARY_PATH.as_posix()
    assert "--workflow-repair" not in command.args


def test_ai_action_regression_run_command_uses_workflow_repair_quality_gate_and_a_cases() -> None:
    command = build_run_command(repeat=2)

    assert command.mode == "run"
    assert command.requires_model is True
    assert command.output_path == DEFAULT_RUN_OUTPUT_PATH
    assert command.summary_path == DEFAULT_RUN_SUMMARY_PATH
    assert "--workflow-repair" in command.args
    assert "--quality-gate" in command.args
    assert command.args[command.args.index("--repeat") + 1] == "2"
    case_values = [
        command.args[index + 1]
        for index, value in enumerate(command.args)
        if value == "--case"
    ]
    assert tuple(case_values) == AI_ACTION_REGRESSION_CASES


def test_ai_action_regression_command_paths_stay_in_ignored_local_outputs() -> None:
    run_command = build_run_command()

    assert run_command.output_path.parts[:2] == ("data", "ai_action_diagnostics")
    assert run_command.summary_path.parts[:2] == ("data", "ai_action_diagnostics")
    assert run_command.output_path.name.endswith(".jsonl")
    assert run_command.summary_path.name.endswith(".json")


def test_ai_action_regression_powershell_command_is_copyable() -> None:
    command = build_validate_command()

    text = command_to_powershell(command, python_executable="python")

    assert text.startswith("python tools/run_ai_action_planner_corpus.py")
    assert "--validate-only" in text
    assert "--quality-gate" in text
    assert DEFAULT_VALIDATE_OUTPUT_PATH.as_posix() in text


def test_ai_action_regression_doc_lists_fixed_commands() -> None:
    doc = Path("AI_ACTION_REGRESSION.md").read_text(encoding="utf-8")

    assert "tools/run_ai_action_regression.py validate" in doc
    assert "tools/run_ai_action_regression.py run" in doc
    assert "--workflow-repair" in doc
    assert "--quality-gate" in doc
    assert DEFAULT_RUN_OUTPUT_PATH.as_posix() in doc
