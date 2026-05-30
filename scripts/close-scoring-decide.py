#!/usr/bin/env python3
# Description: Decide which close_success_* event /close should issue based on
#              close-report verdict + qa_ever_rejected history. Single executable
#              decision helper shared by:
#                - commands/close.md Step 3 (orchestrator-side gate)
#                - scripts/score-update.sh M3 precondition (script-side gate)
#              Tests MUST invoke this helper directly; tests MUST NOT
#              reimplement the decision logic in a parallel test harness
#              (codex iter-2 C1).
#
# Usage: close-scoring-decide.py --task-id <stem> --qa-ever-rejected <true|false>
#                                [--repo-root <path>]
#
# Inputs:
#   --task-id            Close-report stem (resolves to <repo>/docs/dev/close-report-<stem>.md)
#   --qa-ever-rejected   true|false — read by orchestrator from qa-report history
#   --repo-root          Optional repo-root override; default: git rev-parse + script parent-parent fallback
#
# Output: stdout JSON single line:
#   {"events": ["close_success_qa_pass" | "close_success_qa_fail_fixed"] OR [],
#    "skip_reason": "<string>" OR null}
#
# Decision matrix (per ticket-20260529-210616.md M4 / AC-4):
#   close-report missing     -> events=[],                              skip_reason contains "missing"
#   last-line "CLOSE: NO"    -> events=[],                              skip_reason non-null
#   last-line CLOSE: YES (FORCED) -> events=[],                         skip_reason contains "FORCED"
#   last-line "CLOSE: YES" + qa_ever_rejected=false -> events=["close_success_qa_pass"], skip_reason=null
#   last-line "CLOSE: YES" + qa_ever_rejected=true  -> events=["close_success_qa_fail_fixed"], skip_reason=null
#
# Exit codes:
#   0 = decision emitted (events may be empty if blocked by gate)
#   2 = missing/invalid --task-id or --qa-ever-rejected
#   3 = IO error reading close-report (distinct from gate-block which is exit 0 with empty events)
#
# Root cause addressed: task 20260529-081014 orchestrator issued
#   close_success_qa_fail_fixed scoring BEFORE QA finalized verdict. M4 routes
#   the scoring decision through this helper so the gate is the single
#   executable point of truth, not orchestrator inline reasoning.

from __future__ import annotations

import argparse
import json
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path


def _load_close_verdict_module(repo_root: Path):
    """Load hooks/lib/close-verdict.py via SourceFileLoader because the
    filename has a hyphen (Python module names cannot contain hyphens —
    codex iter-2 C6).
    """
    path = repo_root / "hooks" / "lib" / "close-verdict.py"
    if not path.is_file():
        raise FileNotFoundError(f"close-verdict.py not found at {path}")
    return SourceFileLoader("close_verdict", str(path)).load_module()


def _resolve_repo_root(override: str | None) -> Path:
    if override:
        return Path(override).resolve()
    # Try git rev-parse first
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(Path(__file__).resolve().parent),
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    # Fallback: script's parent-parent (scripts/close-scoring-decide.py -> repo/scripts/.. = repo)
    return Path(__file__).resolve().parent.parent


def decide(close_report_path: Path, qa_ever_rejected: bool, repo_root: Path) -> tuple[dict, int]:
    """Pure decision function. Returns (result_dict, exit_code).

    Exit code 0 always when result is a valid decision (even empty events).
    Exit code 3 ONLY when an IO error other than missing-file occurs.
    """
    # Missing file is a valid gate-block, not an error
    if not close_report_path.exists():
        return (
            {"events": [], "skip_reason": f"close-report missing at {close_report_path}"},
            0,
        )

    try:
        text = close_report_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        # Real IO error (permission denied, etc.) — distinct from missing
        sys.stderr.write(f"close-scoring-decide.py: IO error reading {close_report_path}: {e}\n")
        return ({"events": [], "skip_reason": f"IO error: {e}"}, 3)

    cv = _load_close_verdict_module(repo_root)
    last_line = cv.last_nonempty(text)
    verdict = cv.classify_line(last_line)

    # FORCED check FIRST (excluded per codex F9 — even though classify_line
    # returns "yes" for "CLOSE: YES (FORCED)"). Use case-insensitive.
    if "FORCED" in last_line.upper():
        return (
            {"events": [], "skip_reason": f"verdict is CLOSE: YES (FORCED) — scoring excluded"},
            0,
        )

    if verdict != "yes":
        return (
            {"events": [], "skip_reason": f"verdict last-line classifies as '{verdict}' (need 'yes'); last_line={last_line!r}"},
            0,
        )

    # Legal CLOSE: YES — pick event based on qa_ever_rejected
    event = "close_success_qa_fail_fixed" if qa_ever_rejected else "close_success_qa_pass"
    return ({"events": [event], "skip_reason": None}, 0)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="close-scoring-decide.py",
        description="Decide close_success_* event from close-report verdict + QA history",
    )
    parser.add_argument("--task-id", required=True, help="close-report stem")
    parser.add_argument(
        "--qa-ever-rejected",
        required=True,
        choices=["true", "false"],
        help="whether QA rejected at least once this cycle",
    )
    parser.add_argument("--repo-root", default=None, help="repo-root override")

    # argparse exits 2 on missing/invalid args by default — matches AC-4
    try:
        args = parser.parse_args(argv[1:])
    except SystemExit as e:
        # argparse already wrote stderr; preserve its exit code (2 for missing required)
        raise

    qa_ever_rejected = (args.qa_ever_rejected == "true")
    repo_root = _resolve_repo_root(args.repo_root)
    close_report_path = repo_root / "docs" / "dev" / f"close-report-{args.task_id}.md"

    try:
        result, exit_code = decide(close_report_path, qa_ever_rejected, repo_root)
    except FileNotFoundError as e:
        sys.stderr.write(f"close-scoring-decide.py: {e}\n")
        return 3

    # Single-line JSON to stdout
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
