#!/usr/bin/env python3
"""Repair engine for close/commit findings (ticket-20260930-132644-l8 Part B).

Consumes schemas/repair-map.v1.json; given a findings list, looks up each
finding's bucket-derived action, dispatches/reruns/stalls, rechecks, retries
(<=2 attempts total per finding), and returns {continue, disclosures} --
never touching an artifact file itself (only Agent-dispatch and
rerun/recheck-command calls, both injectable so production code and tests
share the exact same control flow).

CLI contract (Technical Hints SSB1): stdin JSON {findings: [{code, path,
detail}]}; stdout JSON {continue: bool, disclosures: [{code, path, detail,
producer_role, action}]} (+ "output": "OPERATION_STALLED" on a physical/
instrument-class stall, R6).

ticket-20261001-161041-r20 (M1/AC-R20-01), additive: stdout JSON also
includes "required_actions": [{code, path, detail, producer_role, action,
bucket}] -- present (key included) only when non-empty -- one entry per
finding whose action is dispatch_producer_fix, rerun_tool, or restart_lane
(never land_with_disclosure/retry_then_stall, i.e. never bucket A/X/G/S) AND
whose CLI-level attempt here did not verify success (denied or exhausted).
This field never branches on producer_role nullness for either
dispatch_producer_fix or rerun_tool -- that branching happens entirely at the
orchestrator consumption layer (commands/close.md / commands/commit.md),
never in this engine, because only the orchestrator session holds the Agent
tool needed to act on it. required_actions is additive, never a replacement
for disclosures -- every finding that populates it also has a paired
disclosures[] entry with the same code/path, for the case the orchestrator's
own bounded redispatch loop still exhausts and falls back to disclosure.

retry_then_stall is reserved EXCLUSIVELY for genuinely physical/instrument-
class failures (S-bucket only, per schemas/repair-map.v1.json's own
bucket->action table) -- it is the ONLY finding-type that can set
`continue: false`. Every other outcome -- including retry exhaustion for a
dispatch/rerun action -- degrades to `land_with_disclosure` and leaves
`continue: true`. Any internal engine exception during a single finding's
processing degrades THAT finding to a disclosure; it never propagates.

restart_lane is a caller-supplied SENTINEL input (code == "lane_incomplete"),
not a table lookup -- the repair-map table never produces this action
(Technical Hints SSA3).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TABLE_PATH = REPO_ROOT / "schemas" / "repair-map.v1.json"

MAX_ATTEMPTS = 2  # "retry <=2" (R2/R6): first attempt + at most one retry.
STALL_OUTPUT = "OPERATION_STALLED"
RESTART_LANE_SENTINEL_CODE = "lane_incomplete"

DispatchFn = Callable[[str | None, str | None, str | None], dict]
RerunFn = Callable[[str | None, str | None], bool]
InstrumentProbeFn = Callable[[dict], bool]
RestartLaneFn = Callable[[str | None, str | None], bool]


def load_table(path: Path = DEFAULT_TABLE_PATH) -> dict[str, dict]:
    """Load schemas/repair-map.v1.json once, indexed by `code`."""
    document = json.loads(path.read_text(encoding="utf-8"))
    return {entry["code"]: entry for entry in document.get("entries", [])}


def _build_disclosure(
    finding: dict,
    *,
    producer_role: str | None = None,
    action: str | None = None,
    detail_override: str | None = None,
) -> dict:
    return {
        "code": finding.get("code"),
        "path": finding.get("path"),
        "detail": detail_override if detail_override is not None else finding.get("detail"),
        "producer_role": producer_role,
        "action": action,
    }


def _build_required_action(
    finding: dict,
    *,
    action: str,
    producer_role: str | None,
    bucket: str | None,
) -> dict:
    """ticket-20261001-161041-r20 M1/AC-R20-01: additive signal (never a
    replacement for the paired disclosure) naming a finding whose CLI-level
    attempt could not verify success -- the orchestrator (the only holder of
    the Agent tool) consumes this to perform a real dispatch-and-recheck loop
    before ever accepting the disclosure as final. Emitted only for
    dispatch_producer_fix/rerun_tool/restart_lane findings that did not
    succeed; never branches on producer_role nullness (symmetry is the point
    -- role selection for a null producer_role happens at the orchestrator
    consumption layer, not here)."""
    return {
        "code": finding.get("code"),
        "path": finding.get("path"),
        "detail": finding.get("detail"),
        "producer_role": producer_role,
        "action": action,
        "bucket": bucket,
    }


def _attempt_dispatch_or_rerun(
    finding: dict, entry: dict, dispatch_fn: DispatchFn, rerun_fn: RerunFn,
) -> tuple[str, str | None]:
    """Returns (outcome, detail) where outcome in {"success","denied","exhausted"}.

    A whitelist DENIAL (AC16) is a terminal signal on the FIRST attempt it is
    observed -- it is never retried as a transient failure, unlike a plain
    "error" status (the honest shape for a transient dispatch/rerun hiccup),
    which consumes one of the MAX_ATTEMPTS retries.
    """
    action = entry["action"]
    for _attempt in range(1, MAX_ATTEMPTS + 1):
        if action == "dispatch_producer_fix":
            result = dispatch_fn(entry.get("producer_role"), finding.get("path"), finding.get("detail"))
            status = result.get("status") if isinstance(result, dict) else None
            if status == "denied":
                return "denied", result.get("detail", "")
            if status == "success":
                return "success", None
            continue  # transient ("error" or any other shape) -- retry.
        # action == "rerun_tool"
        try:
            ok = rerun_fn(finding.get("code"), finding.get("path"))
        except Exception:
            ok = False
        if ok:
            return "success", None
    return "exhausted", None


def _attempt_retry_then_stall(finding: dict, instrument_probe_fn: InstrumentProbeFn) -> bool:
    for _attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            if instrument_probe_fn(finding):
                return True
        except Exception:
            continue
    return False


def _attempt_restart_lane(finding: dict, restart_lane_fn: RestartLaneFn) -> bool:
    for _attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            if restart_lane_fn(finding.get("path"), finding.get("detail")):
                return True
        except Exception:
            continue
    return False


def _process_one_finding(
    finding: dict,
    table: dict[str, dict],
    dispatch_fn: DispatchFn,
    rerun_fn: RerunFn,
    instrument_probe_fn: InstrumentProbeFn,
    restart_lane_fn: RestartLaneFn,
    disclosures: list[dict],
    required_actions: list[dict],
) -> tuple[bool, str | None]:
    """Process a single finding. Returns (stalled, stall_output)."""
    if not isinstance(finding, dict):
        raise ValueError(f"finding is not a dict: {finding!r}")

    code = finding.get("code")
    if code == RESTART_LANE_SENTINEL_CODE:
        if not _attempt_restart_lane(finding, restart_lane_fn):
            lane = finding.get("path") or finding.get("detail") or "<unknown lane>"
            disclosures.append(_build_disclosure(
                finding, action="restart_lane",
                detail_override=f"lane {lane} 未完成 (restart_lane exhausted {MAX_ATTEMPTS} attempts)",
            ))
            # M1/AC-R20-01: restart_lane has no producer_role/bucket (it
            # bypasses the table lookup entirely) -- both are None.
            required_actions.append(_build_required_action(
                finding, action="restart_lane", producer_role=None, bucket=None,
            ))
        return False, None

    entry = table.get(code)
    if entry is None:
        disclosures.append(_build_disclosure(
            finding, detail_override=f"code {code!r} not found in repair-map table",
        ))
        return False, None

    action = entry["action"]
    if action == "land_with_disclosure":
        disclosures.append(_build_disclosure(
            finding, producer_role=entry.get("producer_role"), action=action,
        ))
        return False, None

    if action == "retry_then_stall":
        if _attempt_retry_then_stall(finding, instrument_probe_fn):
            return False, None
        return True, STALL_OUTPUT

    # dispatch_producer_fix / rerun_tool -- required_actions populates
    # regardless of producer_role nullness (M1 round 3 symmetry; AC-R20-01).
    outcome, detail = _attempt_dispatch_or_rerun(finding, entry, dispatch_fn, rerun_fn)
    if outcome == "success":
        return False, None
    if outcome == "denied":
        disclosures.append(_build_disclosure(
            finding, producer_role=entry.get("producer_role"), action=action, detail_override=detail,
        ))
        required_actions.append(_build_required_action(
            finding, action=action, producer_role=entry.get("producer_role"), bucket=entry.get("bucket"),
        ))
        return False, None
    # exhausted
    disclosures.append(_build_disclosure(
        finding, producer_role=entry.get("producer_role"), action=action,
    ))
    required_actions.append(_build_required_action(
        finding, action=action, producer_role=entry.get("producer_role"), bucket=entry.get("bucket"),
    ))
    return False, None


def run_engine(
    findings: list[dict],
    table: dict[str, dict],
    *,
    dispatch_fn: DispatchFn,
    rerun_fn: RerunFn,
    instrument_probe_fn: InstrumentProbeFn,
    restart_lane_fn: RestartLaneFn,
) -> dict:
    """Process every finding; never raise, never write a file.

    Any unexpected internal exception while processing ONE finding degrades
    that finding to a land_with_disclosure entry (AC8) -- it never aborts
    the whole run. A genuine physical/instrument-class stall (S-bucket
    retry_then_stall only) is the ONLY outcome that sets `continue: false`;
    on reaching it, remaining findings are not processed (the instrument is
    presumed broken, so further rechecks against it are not attempted).
    """
    disclosures: list[dict] = []
    required_actions: list[dict] = []
    for finding in findings:
        try:
            stalled, stall_output = _process_one_finding(
                finding, table, dispatch_fn, rerun_fn, instrument_probe_fn, restart_lane_fn,
                disclosures, required_actions,
            )
        except Exception as exc:
            disclosures.append(_build_disclosure(
                finding if isinstance(finding, dict) else {},
                detail_override=f"internal engine error degraded to disclosure: {exc}",
            ))
            continue
        if stalled:
            result = {"continue": False, "disclosures": disclosures, "output": stall_output}
            if required_actions:
                result["required_actions"] = required_actions
            return result
    result = {"continue": True, "disclosures": disclosures}
    if required_actions:
        # M1/AC-R20-01 (additive -- Technical Hints: "required_actions is an
        # additive field, not a replacement for disclosures"): present only
        # when non-empty so every pre-existing exact-dict-equality test in
        # tests/test_repair_orchestrate.py (L8's frozen contract, success
        # paths) keeps passing unmodified.
        result["required_actions"] = required_actions
    return result


# ---------------------------------------------------------------------------
# Production default side-effecting functions (CLI only -- every test
# supplies its own stubs so AC5-AC8/AC14-AC16 never depend on these).
# ---------------------------------------------------------------------------

def _default_dispatch_fn(producer_role: str | None, path: str | None, detail: str | None) -> dict:
    """This script cannot itself invoke the Agent tool (only the
    orchestrator holds that capability) -- report an honest, retryable
    "error" so the normal retry ceiling applies, degrading to a
    land_with_disclosure that names exactly what the orchestrator still
    needs to dispatch."""
    return {
        "status": "error",
        "detail": (
            f"no production dispatch channel wired in this CLI invocation; "
            f"orchestrator must dispatch producer_role={producer_role!r} for "
            f"path={path!r}: {detail!r}"
        ),
    }


_TASK_ID_TOKEN_RE = re.compile(r"\d{8}-\d{6}[A-Za-z0-9._-]*")


def _default_rerun_fn(code: str | None, path: str | None) -> bool:
    """Best-effort production rerun: the only rerun_tool target this table
    currently produces is the aggregator itself (SSA3); when the finding's
    own path names a task-id, rerun it and report its own exit code."""
    m = _TASK_ID_TOKEN_RE.search(path or "")
    if not m:
        return False
    aggregator = Path(__file__).resolve().with_name("aggregate-dev-report.py")
    proc = subprocess.run(
        [sys.executable, str(aggregator), "--task-id", m.group(0)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return proc.returncode == 0


def _default_instrument_probe_fn(_finding: dict) -> bool:
    """Physical/instrument-class failures are not recoverable by a bare
    retry from this process -- the honest default is "still failing"."""
    return False


def _default_restart_lane_fn(_path: str | None, _detail: str | None) -> bool:
    """No production lane-restart channel is wired in this CLI invocation
    (restarting a lane means dispatching a subagent -- the orchestrator's
    own capability) -- the honest default is "did not restart"."""
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE_PATH)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    raw_stdin = sys.stdin.read()
    try:
        payload: Any = json.loads(raw_stdin) if raw_stdin.strip() else {}
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"close-commit-repair-orchestrate: malformed stdin JSON: {exc}\n")
        print(json.dumps({"continue": True, "disclosures": []}))
        return 0

    findings = payload.get("findings") if isinstance(payload, dict) else None
    if not isinstance(findings, list):
        findings = []

    table = load_table(args.table)
    result = run_engine(
        findings, table,
        dispatch_fn=_default_dispatch_fn,
        rerun_fn=_default_rerun_fn,
        instrument_probe_fn=_default_instrument_probe_fn,
        restart_lane_fn=_default_restart_lane_fn,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
