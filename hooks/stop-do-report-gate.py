#!/usr/bin/env python3
"""Stop hook: enforce the /do do-report completion contract at session stop.

A /do session mints a task-id sidecar (/tmp/claude-do-task-<sid>.json) and a
pending do-report skeleton (docs/dev/do-report-<task_id>.json) at consent time
(hooks/prompt-workflow.py::handle_do_consent). commands/do.md obliges the agent
to rewrite that skeleton to a terminal status BEFORE stopping. Historically the
obligation was instruction-only — nothing compared declared vs. actual at
runtime, so omissions surfaced only when /close later failed to find the report.
This gate is the runtime binder.

MODE (env DO_REPORT_GATE_MODE): "advisory" (default) | "block" | "off".
ADVISORY-FIRST: a buggy blocking Stop hook on the MAIN session traps every
session exit — worse blast radius than the SubagentStop analogue that taught
this lesson (subagentstop-cp-enforce.py). Default mode therefore only appends
would-block records to ~/.claude/logs/do-report-gate-advisory.jsonl; flipping to
"block" is a separate, deliberate decision made AFTER the advisory log shows
low false positives.

Compliance (all required to allow stop in block mode):
  1. docs/dev/do-report-<task_id>.json exists and parses as a JSON object.
  2. Top-level task_id equals the sidecar task_id, and source == "do".
  3. do.status is a TERMINAL status: "completed" or "blocked" ("blocked" is the
     honest terminal branch — a gate that only accepts "completed" would press
     the agent to misreport abandoned work; /close still accepts only
     "completed").
  4. do.summary is a non-empty string; do.files_modified and do.files_created
     are arrays.
  5. contract_runtime.validate_report_artifact() does not FAIL (schema-infra
     problems and unversioned records skip — never fail-closed).
The gate checks SHAPE only. It never derives or verifies files_modified against
git diff (forbidden by commands/do.md — git is session-unaware), and it never
writes the report itself.

DEADLOCK GUARD (block mode): per-session attempt counter
/tmp/claude-do-report-gate-<sid>.json; after MAX_BLOCKS blocks for the same
task_id the gate force-allows with a loud stderr warning (an unwritable
docs/dev or a confused agent must not trap the session forever).

FAIL-SAFE: any unexpected error -> exit 0 (allow). No network, no subprocess.

Exit codes: 0 = allow stop; 2 = block stop (block mode only, stderr tells the
agent exactly which fields are missing).
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
from pathlib import Path

MAX_BLOCKS = 2
ADVISORY_LOG = Path.home() / ".claude" / "logs" / "do-report-gate-advisory.jsonl"
TERMINAL_STATUSES = {"completed", "blocked"}

# Identifier-safety pattern reused from subagentstop-e2e-enforce.py: an unsafe/
# path-shaped sidecar task_id degrades silently to "no enforcement" rather than
# escaping docs/dev/ or raising.
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _log_event(record: dict) -> None:
    """Best-effort append to the advisory log. Never affects exit."""
    try:
        ADVISORY_LOG.parent.mkdir(parents=True, exist_ok=True)
        record["ts"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(ADVISORY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _compliance_problems(report_path: Path, task_id: str) -> list[str]:
    """Return [] when the do-report satisfies the stop contract, else the
    human-readable list of violations."""
    if not report_path.exists():
        return [f"do-report absent: {report_path}"]
    try:
        record = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return [f"do-report unreadable/unparseable: {e}"]
    if not isinstance(record, dict):
        return ["do-report is not a JSON object"]

    problems: list[str] = []
    if record.get("task_id") != task_id:
        problems.append(
            f"task_id mismatch: report has {record.get('task_id')!r}, sidecar minted {task_id!r}")
    if record.get("source") != "do":
        problems.append(f"source must be \"do\", got {record.get('source')!r}")
    do = record.get("do")
    if not isinstance(do, dict):
        problems.append("missing/invalid \"do\" object")
        return problems
    status = do.get("status")
    if status not in TERMINAL_STATUSES:
        problems.append(
            f"do.status is {status!r} — must be a terminal status "
            f"({'/'.join(sorted(TERMINAL_STATUSES))}); \"pending\" means the skeleton was never completed")
    summary = do.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        problems.append("do.summary must be a non-empty string")
    if not isinstance(do.get("files_modified"), list):
        problems.append("do.files_modified must be an array (empty is fine for read-only tasks)")
    if not isinstance(do.get("files_created"), list):
        problems.append("do.files_created must be an array")

    # Versioned-schema pass via the shared engine (single validation source —
    # never hand-roll a second shape check where a registered schema exists).
    # Infra failures and unversioned records skip: never fail-closed.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from lib import contract_runtime as cr
        gate = cr.validate_report_artifact(report_path)
        if gate.get("status") == "fail":
            problems.extend(f"schema {gate.get('schema')}: {e}" for e in gate.get("errors", []))
    except Exception:
        pass
    return problems


def _counter_path(sid: str) -> Path:
    return Path(f"/tmp/claude-do-report-gate-{sid}.json")


def _read_blocks(sid: str, task_id: str) -> int:
    try:
        data = json.loads(_counter_path(sid).read_text(encoding="utf-8"))
        if data.get("task_id") == task_id:
            return int(data.get("blocks", 0))
    except Exception:
        pass
    return 0


def _write_blocks(sid: str, task_id: str, blocks: int) -> None:
    try:
        _counter_path(sid).write_text(
            json.dumps({"task_id": task_id, "blocks": blocks}), encoding="utf-8")
    except Exception:
        pass


def main() -> int:
    mode = (os.environ.get("DO_REPORT_GATE_MODE", "advisory") or "advisory").strip().lower()
    if mode == "off":
        return 0

    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    sid = (payload.get("session_id")
           or os.environ.get("CLAUDE_CODE_SESSION_ID")
           or os.environ.get("CLAUDE_SESSION_ID") or "")
    if not sid or not _TASK_ID_RE.match(sid):
        return 0

    sidecar = Path(f"/tmp/claude-do-task-{sid}.json")
    if not sidecar.exists():
        return 0  # no /do consent this session — gate is out of scope
    try:
        task_id = json.loads(sidecar.read_text(encoding="utf-8")).get("task_id", "")
    except Exception:
        return 0
    if not isinstance(task_id, str) or not _TASK_ID_RE.match(task_id):
        return 0

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR")
                       or payload.get("cwd")
                       or os.getcwd())
    report_path = project_dir / "docs" / "dev" / f"do-report-{task_id}.json"

    problems = _compliance_problems(report_path, task_id)
    if not problems:
        try:
            _counter_path(sid).unlink()
        except OSError:
            pass
        return 0

    if mode != "block":
        _log_event({"event": "would_block", "mode": mode, "session_id": sid,
                    "task_id": task_id, "report": str(report_path), "problems": problems})
        return 0

    blocks = _read_blocks(sid, task_id)
    if blocks >= MAX_BLOCKS:
        _log_event({"event": "forced_allow", "mode": mode, "session_id": sid,
                    "task_id": task_id, "report": str(report_path),
                    "blocks": blocks, "problems": problems})
        sys.stderr.write(
            f"[do-report-gate] FORCED ALLOW after {blocks} blocks — do-report for task "
            f"{task_id} is STILL non-compliant ({'; '.join(problems)}). /close will reject "
            f"this task until the report is completed.\n")
        return 0

    _write_blocks(sid, task_id, blocks + 1)
    _log_event({"event": "block", "mode": mode, "session_id": sid,
                "task_id": task_id, "report": str(report_path),
                "blocks": blocks + 1, "problems": problems})
    sys.stderr.write(
        "DO_REPORT_GATE_BLOCKED — the /do contract (commands/do.md) requires a completed "
        f"do-report before this session may stop.\n"
        f"Report: {report_path}\n"
        f"Violations:\n" + "".join(f"  - {p}\n" for p in problems) +
        "Rewrite the report now: fill do.summary and do.files_modified/files_created from "
        "your OWN knowledge of what you changed (do NOT derive from git diff — it is "
        "session-unaware), and set do.status to \"completed\" (or \"blocked\" with an honest "
        "summary if the task could not be finished). Then stop again.\n")
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # FAIL-SAFE: a gate bug must never trap the session
        try:
            _log_event({"event": "gate_error", "error": repr(exc)})
        except Exception:
            pass
        sys.exit(0)
