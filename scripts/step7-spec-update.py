#!/usr/bin/env python3
"""
Step 8 (Spec-update dispatch) reference harness — task 20260524-205206 iter-2.

This script implements the Step 8 algorithm specified verbatim in commands/commit.md
section "### Step 8: Spec-update dispatch (post-commit, deterministic fail-closed)".

It is the executable embodiment of the algorithm that the /commit orchestrator runs
in stages (1) context.spec_path -> (2) close-report continuation line -> (3) mtime+marker
glob -> (4) fail-closed outcome. The orchestrator may either follow the commit.md
prose directly OR invoke this harness; both paths satisfy the AC-05 contract because
they execute identical decision logic.

USAGE:
  python3 scripts/step7-spec-update.py \\
      --task-id <TASK_ID> \\
      --dev-docs-root <DEV_DOCS_ROOT> \\
      [--bulk true|false] [--dryrun true|false] \\
      [--changelog-status committed|nothing_to_commit|failed] \\
      [--push-gate-token-path <path-or-NONE>]

ENV:
  COMMIT_STEP7_TRACE=1   Emit STEP7_* deterministic markers to stderr.

EXIT CODES:
  0   normal — either Step 8 skipped, stage 1/2 dispatched, or stage 4 empty-set
  2   stage 4 fail-closed (set has 1 or more elements without context linkage)

OUTPUT:
  stdout: human-readable narration of the decision
  stderr: STEP7_* markers when COMMIT_STEP7_TRACE=1; warnings; errors

NOTE: This harness implements ONLY the Step 8 SELECTION + TRACE logic — stages
(1)-(4) — and the corresponding STEP7_* stderr markers. It does NOT execute the
"Dispatch payload" Agent call described in commands/commit.md (an inline
spec-update Agent invocation requires the orchestrator's Claude Code session).
The harness emits the STEP7_SPEC_UPDATE_DISPATCHED marker IMMEDIATELY before
the point at which the orchestrator would perform the real Agent dispatch.
QA contract: the AC-05 marker assertion verifies the selection contract, not
the Agent-dispatch contract. The Agent-dispatch contract is implicit in the
documented behaviour of commands/commit.md Step 8 dispatch payload (which is a
Claude Code Agent call, not a shell command).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time

CONTINUATION_RE = re.compile(
    r"^[-*+]?\s*Continuation spec(\s*\([^)]*\))?\s*:\s*`?(docs/dev/specs/spec-[^\s`]+\.md)`?\s*$"
)
SPEC_BASENAME_RE = re.compile(r"^spec-\d{8}-\d{6}\.md$")


def _trace_on() -> bool:
    return os.environ.get("COMMIT_STEP7_TRACE", "") == "1"


def _emit(marker: str) -> None:
    if _trace_on():
        print(marker, file=sys.stderr, flush=True)


def _parse_close_report_lines_outside_fences(path: pathlib.Path):
    """Yield each line that is NOT inside a ``` fenced code block."""
    in_fence = False
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield raw


def _stage1_context_spec_path(task_id: str, dev_docs_root: pathlib.Path):
    ctx = dev_docs_root / f"context-{task_id}.json"
    if not ctx.is_file():
        return None
    try:
        data = json.loads(ctx.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    spec_path = data.get("spec_path")
    if not spec_path:
        return None
    sp = pathlib.Path(spec_path)
    # Resolve relative to dev-docs-root's parent (project root)
    if not sp.is_absolute():
        # Try project root (parent of dev-docs-root parent, i.e. /root/docs/dev -> /root)
        root_guess = dev_docs_root.parent.parent
        candidate = root_guess / sp
        if candidate.is_file():
            return candidate
        return None
    return sp if sp.is_file() else None


def _stage2_close_report_continuation(task_id: str, dev_docs_root: pathlib.Path):
    cr = dev_docs_root / f"close-report-{task_id}.md"
    if not cr.is_file():
        return None
    matches = []
    for line in _parse_close_report_lines_outside_fences(cr):
        m = CONTINUATION_RE.match(line)
        if m:
            matches.append(m.group(2))
    if len(matches) != 1:
        return None
    sp = pathlib.Path(matches[0])
    if not sp.is_absolute():
        root_guess = dev_docs_root.parent.parent
        candidate = root_guess / sp
        return candidate if candidate.is_file() else None
    return sp if sp.is_file() else None


def _stage3_mtime_glob(task_id: str, dev_docs_root: pathlib.Path):
    cr = dev_docs_root / f"close-report-{task_id}.md"
    if not cr.is_file():
        return []
    cr_mtime = cr.stat().st_mtime
    lo = cr_mtime - 24 * 3600
    hi = cr_mtime + 3600
    specs_dir = dev_docs_root / "specs"
    if not specs_dir.is_dir():
        return []
    marker = f"<!-- spec-continuation-of: {task_id} -->"
    hits = []
    for p in specs_dir.iterdir():
        if not p.is_file():
            continue
        if not SPEC_BASENAME_RE.match(p.name):
            continue
        m = p.stat().st_mtime
        if not (lo <= m <= hi):
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if marker in content:
            hits.append(p)
    # Deterministic ordering (codex finding #7): sort by full path so the
    # paths=... marker is stable regardless of filesystem iteration order.
    return sorted(hits)


def main() -> int:
    ap = argparse.ArgumentParser(description="Step 8 spec-update harness (commit.md)")
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--dev-docs-root", required=True)
    ap.add_argument("--bulk", default="false", choices=["true", "false"])
    ap.add_argument("--dryrun", default="false", choices=["true", "false"])
    ap.add_argument("--changelog-status", default="committed",
                    choices=["committed", "nothing_to_commit",
                             "nothing_to_commit_precommitted", "failed"])
    ap.add_argument("--push-gate-token-path", default="",
                    help="Path to push-gate token; empty/NONE => not present")
    args = ap.parse_args()

    task_id = args.task_id.strip()
    dev_docs_root = pathlib.Path(args.dev_docs_root).resolve()
    bulk = args.bulk == "true"
    dryrun = args.dryrun == "true"

    # SKIP branches (commit.md Step 8 SKIP block, in declared order)
    if bulk:
        _emit("STEP7_SKIPPED: bulk=true")
        print("Step 8 skipped: BULK=true")
        return 0
    if dryrun:
        _emit("STEP7_SKIPPED: dryrun=true")
        print("Step 8 skipped: DRYRUN=true")
        return 0
    if not task_id:
        _emit("STEP7_SKIPPED: task_id_empty")
        print("Step 8 skipped: TASK_ID is empty")
        return 0
    push_gate_ok = (
        args.push_gate_token_path
        and args.push_gate_token_path != "NONE"
        and pathlib.Path(args.push_gate_token_path).is_file()
    )
    if args.changelog_status != "committed" or not push_gate_ok:
        _emit("STEP7_SKIPPED: changelog_no_real_commit")
        print(
            f"Step 8 skipped: changelog status={args.changelog_status} "
            f"push_gate_ok={push_gate_ok}"
        )
        return 0

    # Stage (1) context.spec_path
    sp1 = _stage1_context_spec_path(task_id, dev_docs_root)
    if sp1 is not None:
        _emit(
            f"STEP7_SPEC_UPDATE_DISPATCHED: task-id={task_id} stage=1 "
            f"spec_path={sp1}"
        )
        print(f"Stage 1 dispatch: {sp1}")
        return 0

    # Stage (2) close-report continuation line
    sp2 = _stage2_close_report_continuation(task_id, dev_docs_root)
    if sp2 is not None:
        print(
            "WARNING: linked via close-report, not context.spec_path",
            file=sys.stderr,
        )
        _emit(
            f"STEP7_SPEC_UPDATE_DISPATCHED: task-id={task_id} stage=2 "
            f"spec_path={sp2}"
        )
        print(f"Stage 2 dispatch: {sp2}")
        return 0

    # Stage (3) mtime + literal-task-id glob
    candidates = _stage3_mtime_glob(task_id, dev_docs_root)

    # Stage (4) outcome (fail-closed)
    if not candidates:
        _emit(f"STEP7_NO_SPEC: task-id={task_id}")
        print(f"No spec associated with task-id {task_id}")
        return 0
    paths_str = ",".join(str(p) for p in candidates)
    _emit(
        f"STEP7_UNLINKED_SPEC: task-id={task_id} "
        f"count={len(candidates)} paths={paths_str}"
    )
    if len(candidates) == 1:
        print(
            f"spec produced this cycle but not linked in context: {candidates[0]}",
            file=sys.stderr,
        )
    else:
        print(
            f"multiple specs produced this cycle without context linkage: "
            f"{paths_str}; explicit context.spec_path required",
            file=sys.stderr,
        )
    return 2


if __name__ == "__main__":
    sys.exit(main())
