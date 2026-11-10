#!/usr/bin/env python3
"""Steps 1-4 of /test: folder setup, edge-case analysis, test/ migration, tests/ cleanup.

    test-prepare.py init [--full] [--project-root DIR]
    test-prepare.py edge-cases   [--project-root DIR]
    test-prepare.py migrate      [--project-root DIR]
    test-prepare.py cleanup      [--project-root DIR]

The project root defaults to the current directory. Facts go to stdout as key=value lines, one per
line; the output of the helper scripts it runs goes to stderr. Every state below is a fact, never a
failure: the exit status is 0 unless the arguments are wrong (2).

init        request_id, timestamp (ISO-8601, UTC), project_root, tests_dir=created|existing,
            created=<comma list|none>, templates_copied=<n>.
            Creates tests/reports/. When tests/ did not exist, or with --full, creates the whole
            structure tests/{scripts,instructions,data/fixtures,data/mocks,reports} and, into an
            instructions/ folder it creates, copies the harness's tests/instructions/*.md
            (never README.md or INDEX.md); an instructions/ folder that exists is left as it is.
edge-cases  edge_case_analysis=docs/test/edge-case-analysis.json|failed, edge_cases=<n>
            (failed adds analyzer_exit and analyzer_error). Runs scripts/analyze-git-edge-cases.sh
            over the last 90 days.
migrate     migration=migrated|failed|both_exist|none (failed adds migration_exit). Runs
            scripts/migrate-test-to-tests.sh when test/ exists and tests/ is absent or older than
            test/; both_exist: both exist and tests/ is not older. test/ is never removed.
cleanup     cleanup=done|skipped|failed (skipped adds cleanup_reason, failed adds cleanup_exit).
            Runs scripts/cleanup-tests-folder.sh against the analysis when it and tests/ exist.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = "docs/test/edge-case-analysis.json"
SUBDIRS = ("scripts", "instructions", "data/fixtures", "data/mocks", "reports")
NOT_TEMPLATES = ("README.md", "INDEX.md")


def emit(**facts: object) -> None:
    for key, value in facts.items():
        print(f"{key}={str(value).replace(chr(10), ' ')}")


def run_helper(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a helper script; everything it prints is shown on stderr so stdout stays facts only."""
    proc = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, errors="replace")
    sys.stderr.write(proc.stdout)
    return proc


def last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def cmd_init(root: Path, full: bool) -> None:
    tests = root / "tests"
    existed = tests.is_dir()
    now = datetime.now(timezone.utc).astimezone()
    wanted = SUBDIRS if full or not existed else ("reports",)
    new_instructions = "instructions" in wanted and not (tests / "instructions").is_dir()
    created: list[str] = []
    for sub in wanted:
        if not (tests / sub).is_dir():
            (tests / sub).mkdir(parents=True)
            created.append(f"tests/{sub}")
    copied = 0
    if new_instructions:
        for template in sorted((HARNESS_ROOT / "tests" / "instructions").glob("*.md")):
            target = tests / "instructions" / template.name
            if template.name not in NOT_TEMPLATES:
                target.write_bytes(template.read_bytes())
                copied += 1
    emit(request_id="test-" + now.strftime("%Y%m%d-%H%M%S"),
         timestamp=now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         project_root=root, tests_dir="existing" if existed else "created",
         created=",".join(created) or "none", templates_copied=copied)


def cmd_edge_cases(root: Path) -> None:
    proc = run_helper(["bash", str(HARNESS_ROOT / "scripts" / "analyze-git-edge-cases.sh"),
                       "--project-root", str(root), "--since-date", "90.days.ago", "--output", ANALYSIS], root)
    if proc.returncode != 0:
        emit(edge_case_analysis="failed", edge_cases=0, analyzer_exit=proc.returncode,
             analyzer_error=last_line(proc.stdout))
        return
    try:
        count = json.loads((root / ANALYSIS).read_text(encoding="utf-8"))["summary"]["total_edge_cases"]
    except (OSError, ValueError, KeyError, TypeError):
        count = "unknown"
    emit(edge_case_analysis=ANALYSIS, edge_cases=count)


def cmd_migrate(root: Path) -> None:
    old, new = root / "test", root / "tests"
    if old.is_dir() and (not new.is_dir() or old.stat().st_mtime_ns > new.stat().st_mtime_ns):
        proc = run_helper(["bash", str(HARNESS_ROOT / "scripts" / "migrate-test-to-tests.sh"),
                           "--project-root", str(root)], root)
        if proc.returncode == 0:
            emit(migration="migrated")
        else:
            emit(migration="failed", migration_exit=proc.returncode)
    elif old.is_dir() and new.is_dir():
        emit(migration="both_exist")
    else:
        emit(migration="none")


def cmd_cleanup(root: Path) -> None:
    if not (root / ANALYSIS).is_file():
        emit(cleanup="skipped", cleanup_reason="no edge case analysis")
    elif not (root / "tests").is_dir():
        emit(cleanup="skipped", cleanup_reason="no tests folder")
    else:
        proc = run_helper(["bash", str(HARNESS_ROOT / "scripts" / "cleanup-tests-folder.sh"),
                           "--project-root", str(root), "--edge-case-analysis", ANALYSIS], root)
        if proc.returncode == 0:
            emit(cleanup="done")
        else:
            emit(cleanup="failed", cleanup_exit=proc.returncode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("step", choices=("init", "edge-cases", "migrate", "cleanup"))
    parser.add_argument("--full", action="store_true", help="init: create the whole structure even when tests/ exists")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.project_root).resolve()
    if args.step == "init":
        cmd_init(root, args.full)
    elif args.step == "edge-cases":
        cmd_edge_cases(root)
    elif args.step == "migrate":
        cmd_migrate(root)
    else:
        cmd_cleanup(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
