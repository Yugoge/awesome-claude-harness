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
import os
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


def _resolve_project_dir() -> Path:
    """Resolve the PROJECT root that owns docs/dev/close-report-*.md.

    This is DISTINCT from _resolve_repo_root (which finds the .claude code root
    where hooks/lib/close-verdict.py lives). The close-report lives in the user's
    project, not in the .claude repo. Resolution order:
      1. CLAUDE_PROJECT_DIR env (authoritative when set)
      2. git toplevel from the ACTUAL cwd (NOT the script's dir)
      3. cwd
    Never derive this from __file__ — the script is symlinked into .claude and
    its own location is the .claude repo, not the project (the historical bug).
    """
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )  # cwd defaults to the actual working directory, not the script dir
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.cwd()


def _resolve_close_report_path(repo_root: Path, task_id: str) -> Path:
    """Resolve docs/dev/close-report-<task_id>.md via the canonical bash resolver.

    Calls scripts/resolve-close-report.sh (absolute path under repo_root), reading
    its stdout regardless of exit code (it prints the resolved path on exit 0 and a
    sensible fallback path on exit 1). Inherits the current cwd + environment so the
    resolver's git-toplevel-of-cwd / CLAUDE_PROJECT_DIR / CONTROL_ROOT probes behave
    identically to a direct invocation. Falls back to the prior 2-candidate logic
    (project_dir, repo_root) if the script is missing or the subprocess fails, so
    the gate never crashes on a missing-report condition.
    """
    import subprocess

    # 1. CLAUDE_PROJECT_DIR / git-toplevel-of-cwd project root is authoritative when
    #    the report actually exists there. Check it directly (deterministic) BEFORE
    #    delegating to the bash resolver, whose subprocess-cwd dependence has
    #    mis-resolved the report into the nested .claude repo / ${CONTROL_ROOT:-/root}
    #    in nested-.claude layouts (the historical mis-resolution bug).
    project_dir = _resolve_project_dir()
    project_candidate = project_dir / "docs" / "dev" / f"close-report-{task_id}.md"
    if project_candidate.exists():
        return project_candidate

    # 2. Canonical bash resolver probe chain (inherits cwd + env). Only trust its
    #    output when the path it prints actually EXISTS — resolve-close-report.sh
    #    prints a ${CONTROL_ROOT:-/root} fallback path to stdout even on exit 1
    #    (no candidate found), and returning that blindly reports a missing-report
    #    at the wrong location.
    resolver = repo_root / "scripts" / "resolve-close-report.sh"
    if resolver.is_file():
        try:
            result = subprocess.run(
                ["bash", str(resolver), task_id],
                capture_output=True,
                text=True,
                timeout=5,
            )
            out = result.stdout.strip()
            if out and Path(out).exists():
                return Path(out)
        except (OSError, subprocess.SubprocessError):
            pass

    # 3. Fallback: project_dir (for the missing-file error message) then code repo_root.
    _candidates = [
        project_candidate,
        repo_root / "docs" / "dev" / f"close-report-{task_id}.md",
    ]
    return next((p for p in _candidates if p.exists()), _candidates[0])


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
    repo_root = _resolve_repo_root(args.repo_root)  # CODE root: hooks/lib/close-verdict.py
    # Resolve the close-report path through the canonical resolve-close-report.sh
    # probe chain (CLAUDE_PROJECT_DIR -> git-toplevel-of-cwd -> /root/.claude ->
    # ${CONTROL_ROOT:-/root}), which finds /root/docs/dev/ even when /close runs
    # with cwd = the nested .claude repo (the historical B1 bug: the python's own
    # narrower 2-candidate resolution missed /root). The resolver prints a path on
    # both exit 0 (found) and exit 1 (missing fallback), so use its stdout
    # regardless of exit code. Fall back to the prior 2-candidate logic if the
    # resolver script is absent or unusable — the gate must never crash on a
    # missing-report condition.
    close_report_path = _resolve_close_report_path(repo_root, args.task_id)

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
