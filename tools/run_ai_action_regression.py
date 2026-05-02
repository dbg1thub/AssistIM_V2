from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.ai_action_regression_baseline import (  # noqa: E402
    AI_ACTION_REGRESSION_CASES,
    build_run_command,
    build_validate_command,
    command_to_powershell,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the fixed AI action planner regression baseline.")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate the retained replay file without running the local model.",
    )
    validate_parser.add_argument("--dry-run", action="store_true", help="Print the command without executing it.")

    run_parser = subparsers.add_parser(
        "run",
        help="Regenerate the retained A-action replay with workflow repair and the quality gate.",
    )
    run_parser.add_argument("--repeat", type=int, default=1, help="Samples per case. Defaults to 1.")
    run_parser.add_argument(
        "--case",
        dest="case_names",
        action="append",
        default=[],
        help="Limit the run to one retained case. Can be passed multiple times.",
    )
    run_parser.add_argument("--dry-run", action="store_true", help="Print the command without executing it.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mode == "validate":
        command = build_validate_command()
    else:
        selected_cases = tuple(args.case_names or ()) or AI_ACTION_REGRESSION_CASES
        command = build_run_command(repeat=max(1, int(args.repeat or 1)), cases=selected_cases)

    display_command = command_to_powershell(command, python_executable=Path(sys.executable).as_posix())
    print(display_command, flush=True)
    if bool(getattr(args, "dry_run", False)):
        return 0
    completed = subprocess.run([sys.executable, *command.args], cwd=ROOT)
    return int(completed.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
