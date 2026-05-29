#!/usr/bin/env python3
"""qa-manifest-guard.py — canonical executable invariant for QA Phase 5 manifest_verification.

Dual-mode tool per BA spec docs/dev/ticket-20260529-081014.md M4:

  MANIFEST MODE (default, pure):
    - No CLI flags
    - Reads candidate manifest_verification JSON object on stdin
    - Pure stdin/stdout/exit-code: no filesystem reads, no subprocess
    - Importable as evaluate(manifest_dict) -> (verdict_str, reason_str)
    - Exit codes:
        0  verdict:"ok"                       (non-vacuous valid manifest)
        0  verdict:"ok_vacuous_acknowledged"  (explicit-vacuous: active==0
                                               AND pytest_collected_ok in {null,absent}
                                               AND vacuous_due_to_empty_active_set==true
                                               AND vacuous_reason non-empty)
        2  verdict:"vacuous_rejected"         (any vacuous shape, including
                                               active==0 + pytest_collected_ok==true)

  CYCLE-DIFF MODE (opt-in, read-only):
    - Activated when BOTH --cycle-diff-files <comma-paths>
                       AND --collect-only-cmd '<cmd>' are passed
    - For each .py path, runs collect-only command against THAT single file
    - Counts file as collectable iff pytest exits 0 with >=1 collected test
    - pytest exit 5 ("no tests collected") => non-collectable
    - Other unexpected exit codes => fail-closed
    - Exit codes:
        0  verdict:"ok"                       (active_tests_count > 0)
        0  verdict:"ok_vacuous_acknowledged"  (active_tests_count == 0 with
                                               vacuous_reason
                                               "no pytest-collectable files in cycle diff")
        3  verdict:"guard_blocked"            (one flag missing,
                                               command-not-found,
                                               any non-{0,5} pytest exit)

NEVER falls back to file-name heuristics (e.g. test_*.py) on environment failure —
fail-closed only, per codex iter-2 BLOCKER #2.

Usage:
  # Manifest mode (pure)
  echo '{"active_tests_count":0,"pytest_collected_ok":true,"pytest_failures":[]}' \\
    | python3 scripts/qa-manifest-guard.py
  # exits 2; stderr JSON: {"verdict":"vacuous_rejected","reason":"..."}

  # Cycle-diff mode (opt-in)
  python3 scripts/qa-manifest-guard.py \\
    --cycle-diff-files 'tests/x/test_foo.py,scripts/bar.py' \\
    --collect-only-cmd 'pytest --collect-only'
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Manifest mode — pure (importable)
# ---------------------------------------------------------------------------

VERDICT_OK = "ok"
VERDICT_OK_VACUOUS = "ok_vacuous_acknowledged"
VERDICT_VACUOUS_REJECTED = "vacuous_rejected"
VERDICT_GUARD_BLOCKED = "guard_blocked"


def evaluate(manifest: Dict[str, Any]) -> Tuple[str, str]:
    """Evaluate vacuity invariant on a manifest_verification dict.

    Returns (verdict, reason). Verdict is one of:
      - "ok"                       — valid, non-vacuous
      - "ok_vacuous_acknowledged"  — explicit-vacuous (declared truthfully)
      - "vacuous_rejected"         — any vacuous shape, declared or undeclared
    """
    if not isinstance(manifest, dict):
        return (
            VERDICT_VACUOUS_REJECTED,
            "manifest_verification payload is not a JSON object",
        )

    active = manifest.get("active_tests_count")
    pytest_ok = manifest.get("pytest_collected_ok", "__ABSENT__")
    vacuous_declared = manifest.get("vacuous_due_to_empty_active_set", False) is True
    vacuous_reason = manifest.get("vacuous_reason")

    # Non-vacuous path: active_tests_count > 0.
    # IMPORTANT: bool is a subclass of int in Python; `True > 0` evaluates True.
    # Use `type(active) is int` to reject bools that would otherwise mascarade as integer counts
    # (codex finding #6).
    if type(active) is int and active > 0:
        return (VERDICT_OK, f"active_tests_count={active} (>0); invariant not triggered")

    # active_tests_count == 0 path: vacuity invariant applies.
    # Same strict-int check: only literal int 0 counts as zero (not False).
    if type(active) is int and active == 0:
        # Invariant: pytest_collected_ok MUST NOT be true when active==0.
        if pytest_ok is True:
            return (
                VERDICT_VACUOUS_REJECTED,
                "vacuity invariant violated: active_tests_count==0 AND "
                "pytest_collected_ok==true (forbidden by agents/qa.md Phase 5 — "
                "an empty active set cannot evidence a green pytest run)",
            )

        # pytest_collected_ok is null or absent: require explicit-vacuous declaration.
        if pytest_ok in (None, "__ABSENT__"):
            if vacuous_declared and isinstance(vacuous_reason, str) and vacuous_reason.strip():
                return (
                    VERDICT_OK_VACUOUS,
                    f"vacuous_due_to_empty_active_set declared with reason: {vacuous_reason}",
                )
            return (
                VERDICT_VACUOUS_REJECTED,
                "active_tests_count==0 with pytest_collected_ok null/absent but "
                "vacuous_due_to_empty_active_set not true OR vacuous_reason missing/empty — "
                "vacuity must be declared explicitly",
            )

        # Any other shape with active==0 (e.g. pytest_collected_ok==false): rejected.
        return (
            VERDICT_VACUOUS_REJECTED,
            f"active_tests_count==0 with unexpected pytest_collected_ok={pytest_ok!r}; "
            "explicit-vacuous shape required",
        )

    # active_tests_count missing or non-int and non-zero: vacuous.
    return (
        VERDICT_VACUOUS_REJECTED,
        f"active_tests_count missing or invalid ({active!r}); cannot evaluate invariant",
    )


def _emit_manifest_result(verdict: str, reason: str) -> int:
    """Emit manifest-mode JSON result to the appropriate stream and return exit code."""
    payload = {"verdict": verdict, "reason": reason}
    if verdict == VERDICT_VACUOUS_REJECTED:
        # Diagnostic on stderr; exit 2.
        sys.stderr.write(json.dumps(payload) + "\n")
        sys.stderr.flush()
        return 2
    # ok / ok_vacuous_acknowledged: stdout, exit 0.
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()
    return 0


def _run_manifest_mode() -> int:
    """Read JSON on stdin, evaluate vacuity invariant, emit result."""
    raw = sys.stdin.read()
    try:
        manifest = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        sys.stderr.write(
            json.dumps(
                {
                    "verdict": VERDICT_VACUOUS_REJECTED,
                    "reason": f"stdin JSON parse failed: {e}",
                }
            )
            + "\n"
        )
        return 2
    verdict, reason = evaluate(manifest)
    return _emit_manifest_result(verdict, reason)


# ---------------------------------------------------------------------------
# Cycle-diff mode — opt-in, read-only (may run pytest --collect-only)
# ---------------------------------------------------------------------------

PYTEST_EXIT_OK = 0
PYTEST_EXIT_NO_TESTS_COLLECTED = 5


def _emit_cycle_diff_result(
    verdict: str,
    reason: str,
    extra: Dict[str, Any] | None = None,
) -> int:
    """Emit cycle-diff mode JSON result; pick stream + exit code by verdict."""
    payload: Dict[str, Any] = {"verdict": verdict}
    if verdict == VERDICT_GUARD_BLOCKED:
        payload["guard_reason"] = reason
        sys.stderr.write(json.dumps(payload) + "\n")
        sys.stderr.flush()
        return 3
    if verdict == VERDICT_OK_VACUOUS:
        payload["vacuous_reason"] = reason
    else:
        payload["reason"] = reason
    if extra:
        payload.update(extra)
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()
    return 0


def _is_py_file(path: str) -> bool:
    return path.endswith(".py")


def _collect_one_file(collect_cmd_argv: List[str], path: str) -> Tuple[bool, str]:
    """Run collect-only command against a single file. Returns (collectable, diagnostic).

    collectable=True iff exit 0 AND stdout indicates >=1 test collected.
    pytest exit 5 ("no tests collected") => collectable=False (non-collectable, NOT blocked).
    Other unexpected exits => raises EnvironmentError (caller maps to guard_blocked).
    """
    cmd = collect_cmd_argv + [path]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError as e:
        raise EnvironmentError(
            f"collect-only command not found: {cmd[0]!r} (errno {e.errno}: {e.strerror})"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise EnvironmentError(
            f"collect-only command timed out after {e.timeout}s on {path!r}"
        ) from e
    except OSError as e:
        raise EnvironmentError(
            f"collect-only command failed to execute: {e}"
        ) from e

    if proc.returncode == PYTEST_EXIT_NO_TESTS_COLLECTED:
        return (False, f"pytest exit 5 (no tests collected) for {path}")

    if proc.returncode != PYTEST_EXIT_OK:
        # Unexpected exit: not {0, 5} — fail-closed.
        raise EnvironmentError(
            f"collect-only command returned unexpected exit {proc.returncode} "
            f"for {path}; stderr: {proc.stderr.strip()[:400]}"
        )

    # Exit 0: parse stdout for "collected N items" or similar.
    out = proc.stdout
    # pytest --collect-only emits lines like "collected 3 items" or "1 test collected"
    # Conservative: any "collected N" with N > 0 OR explicit "<Module ...>" lines.
    collected = False
    for line in out.splitlines():
        line_s = line.strip()
        if line_s.startswith("collected "):
            parts = line_s.split()
            # "collected 3 items" or "collected 1 item"
            if len(parts) >= 2:
                try:
                    n = int(parts[1])
                    if n > 0:
                        collected = True
                        break
                except ValueError:
                    pass
        # Also accept "<Module ...>" entries with test items beneath them.
        if line_s.startswith("<Function ") or line_s.startswith("<TestCaseFunction "):
            collected = True
            break
    return (collected, f"pytest exit 0 collected={collected} for {path}")


def _run_cycle_diff_mode(cycle_diff_files: str, collect_only_cmd: str) -> int:
    """Cycle-diff mode: count pytest-collectable files in the cycle diff."""
    # Split paths; empty string -> empty list.
    paths = [p.strip() for p in cycle_diff_files.split(",") if p.strip()]

    # Tokenize and validate the collect-only command BEFORE any vacuous-acknowledged early
    # return — otherwise a no-.py diff + bogus command exits 0, violating the fail-closed
    # contract (codex finding #1).
    try:
        collect_cmd_argv = shlex.split(collect_only_cmd)
    except ValueError as e:
        return _emit_cycle_diff_result(
            VERDICT_GUARD_BLOCKED,
            f"--collect-only-cmd failed to tokenize: {e}",
        )
    if not collect_cmd_argv:
        return _emit_cycle_diff_result(
            VERDICT_GUARD_BLOCKED,
            "--collect-only-cmd is empty",
        )
    # Verify the command's executable is on PATH (or is an absolute path that exists).
    cmd0 = collect_cmd_argv[0]
    import shutil
    if not (os.path.isabs(cmd0) and os.access(cmd0, os.X_OK)) and shutil.which(cmd0) is None:
        return _emit_cycle_diff_result(
            VERDICT_GUARD_BLOCKED,
            f"collect-only command not found on PATH: {cmd0!r} (errno 2: No such file or directory)",
        )

    # Filter to .py files; non-.py are not pytest-collectable.
    py_paths = [p for p in paths if _is_py_file(p)]

    # If no .py paths at all, emit ok_vacuous_acknowledged with the canonical reason.
    # Per codex finding #2: emit the full explicit-vacuous shape so QA can copy these
    # fields verbatim into manifest_verification without racy semantics.
    if not py_paths:
        return _emit_cycle_diff_result(
            VERDICT_OK_VACUOUS,
            "no pytest-collectable files in cycle diff",
            extra={
                "active_tests_count": 0,
                "pytest_collected_ok": None,
                "vacuous_due_to_empty_active_set": True,
            },
        )

    active_tests_count = 0
    per_file_diagnostics: List[str] = []
    for p in py_paths:
        # Skip files that do not exist on disk (cycle-diff may surface a deletion).
        if not os.path.exists(p):
            per_file_diagnostics.append(f"{p}: missing on disk; treated as non-collectable")
            continue
        try:
            collectable, diag = _collect_one_file(collect_cmd_argv, p)
        except EnvironmentError as e:
            return _emit_cycle_diff_result(VERDICT_GUARD_BLOCKED, str(e))
        per_file_diagnostics.append(diag)
        if collectable:
            active_tests_count += 1

    if active_tests_count == 0:
        # Per codex finding #2: emit the full explicit-vacuous shape so QA can copy fields
        # verbatim into manifest_verification without racy semantics.
        return _emit_cycle_diff_result(
            VERDICT_OK_VACUOUS,
            "no pytest-collectable files in cycle diff",
            extra={
                "active_tests_count": 0,
                "pytest_collected_ok": None,
                "vacuous_due_to_empty_active_set": True,
                "per_file": per_file_diagnostics,
            },
        )
    return _emit_cycle_diff_result(
        VERDICT_OK,
        f"{active_tests_count} pytest-collectable file(s) in cycle diff",
        extra={"active_tests_count": active_tests_count, "per_file": per_file_diagnostics},
    )


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qa-manifest-guard.py",
        description="Canonical QA Phase 5 manifest_verification vacuity guard.",
        add_help=True,
    )
    parser.add_argument(
        "--cycle-diff-files",
        default=None,
        help="Comma-separated cycle-diff file paths (opt-in; requires --collect-only-cmd).",
    )
    parser.add_argument(
        "--collect-only-cmd",
        default=None,
        help="Collect-only command, e.g. 'pytest --collect-only' (opt-in; requires --cycle-diff-files).",
    )
    args = parser.parse_args(argv)

    cycle_flag_set = args.cycle_diff_files is not None
    collect_flag_set = args.collect_only_cmd is not None

    # Mode selection: cycle-diff mode requires BOTH flags. One-without-the-other is guard_blocked.
    if cycle_flag_set and collect_flag_set:
        return _run_cycle_diff_mode(args.cycle_diff_files, args.collect_only_cmd)
    if cycle_flag_set or collect_flag_set:
        missing = "--collect-only-cmd" if cycle_flag_set else "--cycle-diff-files"
        return _emit_cycle_diff_result(
            VERDICT_GUARD_BLOCKED,
            f"cycle-diff mode requires both --cycle-diff-files and --collect-only-cmd; "
            f"missing {missing} (no partial-mode degradation; codex iter-2 BLOCKER #2)",
        )

    # No flags: manifest mode (pure, stdin-only).
    return _run_manifest_mode()


if __name__ == "__main__":
    sys.exit(main())
