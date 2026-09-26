#!/usr/bin/env python3
"""SubagentStop Hook: producer-side artifact schema gate for dev/qa reports.

Ports the /close "Artifact schema gate" (commands/close.md §"Artifact schema gate" — the
contract_runtime.validate_report_artifact() Draft7 check that rejects a
versioned-but-schema-invalid dev/qa report at close time) to the PRODUCER's
stop boundary: the qa/dev subagent that just wrote the report is blocked
from stopping while it still has full context to repair it, instead of the
identical violation surfacing later as a /close schema-gate rejection after the
producer's context is gone.

Scope discipline (deliberately the SAME blocking surface as /close):
  - BLOCKS only validate_report_artifact() status == "fail": the report
    DECLARES report_version but VIOLATES its versioned schema. Same engine,
    same semantics ("this is the only blocking outcome" — close.md).
  - Unversioned legacy reports, unparseable JSON, unregistered kinds, and
    validator-infra problems all return 'skip' from the shared engine and
    pass through. Measured baseline 2026-09-26: 674 real reports in
    docs/dev/ -> 9 pass / 0 fail / 665 skip, so this gate rejects zero
    existing compliant reports.
  - A MISSING report is NOT blocked here: qa-report existence is already
    enforced (exit 2) by subagentstop-e2e-enforce.py, and dev-report
    existence by /close's Step-0 artifact-chain resolver. Duplicating
    existence enforcement would create a drift-prone mirrored pair; a
    missing report is only recorded to the advisory JSONL for observability.

Activation chain (every step fails open to exit 0):
  1. stdin carries agent_id (subagent stop, not a main-session stop).
  2. resolve_dev_registry_entry() resolves the agent. LOW-10 contract
     (hooks/lib/agent_resolver.py): callers MUST NOT hard-block on None —
     a skipped FIRST ACTION registration fails open here, as in every
     sibling SubagentStop hook.
  3. The entry carries dev_session_id (legacy flat entries skip).
  4. .claude/dev-registry/<sid>/artifact-contract-enforce.json exists with
     enabled == true (written by scripts/write-enforce-flag.sh
     --flag artifact-contract from /dev-family init and /close Step 2).
  5. agent_type is listed in the flag's enforced_agent_types — this hook
     actually compares that declared list at runtime.
  6. Not a forced close (/tmp/claude-close-force-<sid>.flag — forced closes
     dispatch no QA by design; parity with subagentstop-e2e-enforce.py) and,
     for qa, not a ba_validation-mode dispatch (no report obligation).

Report correlation adapts the two dimensions established by
subagentstop-e2e-enforce.py (session_ts filename/content match + the
orchestrator-anchored exact task_id from the agent's own registry sentinel),
generalized over the report filename prefix so it serves both qa-report-* and
dev-report-* — but as a UNION of all correlated candidates, each validated,
rather than a single pick: under fan-out several lane reports share the
session timestamp, and picking one file would let an invalid lane report be
shadowed by a valid sibling (codex audit finding, HIGH, fixed in this cycle).
The algorithm is intentionally NOT imported from the sibling hook: a runtime
import would let an unrelated refactor of that file silently disable this
gate via the fail-open wrapper, whereas a local copy degrades observably
(missing_report advisory records) if correlation drifts.

Mode: ARTIFACT_CONTRACT_ENFORCE_MODE environment variable.
  "block" (default) — schema-fail writes an advisory record AND exits 2
                      with an ARTIFACT_CONTRACT_BLOCKED message.
  "advisory"        — schema-fail only appends to
                      ~/.claude/logs/artifact-contract-advisory.jsonl.
  Default is block — unlike cp-enforce's advisory-first default — because
  the validator is not new judgment: the identical engine already blocks
  these exact reports at /close today; this hook only moves WHERE the
  rejection lands (user ruling 2026-09-26). The env var is the kill-switch.

Exit codes:
  0: Allow stop (pass-through).
  2: Block stop (ARTIFACT_CONTRACT_BLOCKED — repair the report first).

Spec alignment (2026-09-26, do-20260926-073930): this hook is a PROPER SUBSET
of docs/dev/specs/spec-20260914-052140.md §5.1 (contract-driven SubagentStop
source-blocking of MISSING artifacts, still pending, never checked out) — it
implements only the schema-wellformedness half of that spec's
_artifact_valid_for_entry() end state, for the two roles whose reports already
carry versioned schemas, via the existing enforce-flag channel instead of
cycle-contract required_calls[]. It does NOT implement and does NOT supersede
§5.1: missing-artifact blocking, contract-driven role coverage, the role-enum
extension, prerequisite (f) (hooks reading the contract), and the advisory-log
cleanup precondition (c) all remain that spec's scope. When §5.1 lands, its
mechanism subsumes this hook's check (existence + schema in one entry lookup):
retire this hook or fold it into the contract-driven gate at that point rather
than running both. Rollout style follows spec-20260916-031427 §8.1
(no over-engineering: reuse existing plumbing, no new mechanism); the
default-block-instead-of-advisory-first deviation from that spec's §5.2 is
deliberate and evidence-backed — the blocking predicate is not new judgment
(the identical engine already blocks the identical reports at /close's
Artifact schema gate;
measured 674-report corpus: 0 fail) and the user ordered immediate blocking
on 2026-09-26; ARTIFACT_CONTRACT_ENFORCE_MODE=advisory is the rollback lever.
"""

import glob
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.agent_resolver import resolve_dev_registry_entry
from lib import contract_runtime

# Producer agent types and the report family each is obligated to write.
REPORT_PREFIX_BY_AGENT_TYPE = {
    "qa": "qa-report-",
    "dev": "dev-report-",
}

ADVISORY_LOG = os.path.join("~", ".claude", "logs", "artifact-contract-advisory.jsonl")

# Same identifier-safety shape write-qa-mode.sh enforces for --session-id /
# --task-id: an unsafe or path-shaped anchor degrades silently to "no anchor".
_TASK_ID_ANCHOR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _load_stdin() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _emit_advisory(record: dict) -> None:
    """Best-effort append to the advisory log. Never affects exit."""
    try:
        log_path = os.path.expanduser(ADVISORY_LOG)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **record,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _find_correlated_reports(
    project_dir: str,
    prefix: str,
    dev_session_id: str,
    task_id: str | None,
) -> list[Path]:
    """Return EVERY report correlated with this session, as a sorted union.

    Correlation dimensions (adapted from subagentstop-e2e-enforce.py, but
    UNION-ALL instead of pick-one): the schema predicate below is per-file and
    one-directional, so there is no need to select "the" report — and picking
    a single lexicographic winner is wrong under fan-out, where several lane
    reports share the session timestamp and a schema-invalid lane report would
    be shadowed by a lexicographically-later valid sibling (codex audit
    finding, do-20260926-073930, HIGH). The dev-registry also carries no
    per-lane agent→report binding (all dev lanes share one dev.json sentinel),
    so per-author attribution is structurally unavailable; the enforced
    invariant is session-scoped, matching the enforce flag's session scope:
    no dev/qa agent of this session stops while ANY correlated report of its
    role class is versioned-and-invalid.

    Candidates are the union of:
      1. session_ts (from dev_session_id) as a filename substring — all
         matches, not the lexicographically last one;
      2. session_ts inside the self-declared task_id/request_id of the 5
         most recent reports (content match for renamed/foreign-named files);
      3. the orchestrator-anchored exact task_id from the agent's registry
         sentinel, matched by exact path prefix + exact self-declared-identity
         equality (the cross-session /close path, close.md Step 2).
    An empty union means "no correlation found" — never fall back to
    unrelated/most-recent reports.
    """
    pattern = os.path.join(project_dir, "docs", "dev", prefix + "*.json")
    matches = sorted(glob.glob(pattern))
    candidates: dict[str, Path] = {}

    ts_match = re.search(r"\d{8}-\d{6}", dev_session_id or "")
    if ts_match:
        session_ts = ts_match.group()
        for p in matches:
            if session_ts in os.path.basename(p):
                candidates[p] = Path(p)
        for p in matches[-5:]:
            if p in candidates:
                continue
            data = _read_json(Path(p))
            report_id = data.get("task_id") or data.get("request_id") or ""
            if report_id and session_ts in report_id:
                candidates[p] = Path(p)

    if task_id and _TASK_ID_ANCHOR_RE.match(task_id):
        anchor_pattern = os.path.join(
            project_dir, "docs", "dev", f"{prefix}{task_id}*.json"
        )
        for p in sorted(glob.glob(anchor_pattern)):
            if p in candidates:
                continue
            data = _read_json(Path(p))
            report_id = data.get("task_id") or data.get("request_id") or ""
            if report_id == task_id:
                candidates[p] = Path(p)

    return [candidates[k] for k in sorted(candidates)]


def main() -> None:
    data = _load_stdin()
    if not data:
        sys.exit(0)

    agent_id = data.get("agent_id")
    if not agent_id:
        sys.exit(0)

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())

    entry = resolve_dev_registry_entry(agent_id, project_dir)
    if entry is None:
        # LOW-10: never hard-block on an unresolved agent.
        sys.exit(0)

    dev_session_id = entry.get("dev_session_id")
    if not dev_session_id:
        sys.exit(0)

    agent_type = entry.get("agent_type", "")
    prefix = REPORT_PREFIX_BY_AGENT_TYPE.get(agent_type)
    if prefix is None:
        sys.exit(0)

    registry_dir = Path(project_dir) / ".claude" / "dev-registry" / dev_session_id

    flag = _read_json(registry_dir / "artifact-contract-enforce.json")
    if not flag.get("enabled"):
        sys.exit(0)
    enforced_types = flag.get("enforced_agent_types")
    if isinstance(enforced_types, list) and agent_type not in enforced_types:
        sys.exit(0)

    # Forced closes dispatch zero QA subagents by design; parity with the
    # e2e hook's defense-in-depth sentinel check.
    if glob.glob(f"/tmp/claude-close-force-{dev_session_id}.flag"):
        sys.exit(0)

    sentinel = _read_json(registry_dir / f"{agent_type}.json")
    if agent_type == "qa" and sentinel.get("qa_mode") == "ba_validation":
        # BA-validation QA has no qa-report obligation.
        sys.exit(0)

    report_paths = _find_correlated_reports(
        project_dir, prefix, dev_session_id, sentinel.get("task_id")
    )
    if not report_paths:
        # Existence enforcement belongs to subagentstop-e2e-enforce.py (qa)
        # and /close's chain resolver (dev). Observe, never block, here.
        _emit_advisory(
            {
                "kind": "missing_report",
                "agent_id": agent_id,
                "agent_type": agent_type,
                "dev_session_id": dev_session_id,
                "prefix": prefix,
                "project_dir": project_dir,
            }
        )
        sys.exit(0)

    failures = []
    for report_path in report_paths:
        result = contract_runtime.validate_report_artifact(str(report_path))
        if result.get("status") == "fail":
            failures.append((report_path, result))
    if not failures:
        sys.exit(0)

    mode = os.environ.get("ARTIFACT_CONTRACT_ENFORCE_MODE", "block").strip().lower()
    _emit_advisory(
        {
            "kind": "schema_fail",
            "mode": mode,
            "agent_id": agent_id,
            "agent_type": agent_type,
            "dev_session_id": dev_session_id,
            "failures": [
                {
                    "report_path": str(p),
                    "schema": r.get("schema"),
                    "errors": r.get("errors", [])[:10],
                }
                for p, r in failures[:10]
            ],
        }
    )
    if mode == "advisory":
        sys.exit(0)

    detail_lines = ""
    for p, r in failures[:5]:
        detail_lines += f"  report {p} violates schema {r.get('schema')!r}:\n"
        detail_lines += "".join(f"    - {e}\n" for e in r.get("errors", [])[:10])
    sys.stderr.write(
        f"ARTIFACT_CONTRACT_BLOCKED: agent {agent_id} (type={agent_type}) in "
        f"session {dev_session_id}: {len(failures)} correlated report(s) "
        f"declare report_version but violate their schema.\n"
        f"{detail_lines}"
        f"This is the same check /close's Artifact schema gate applies — /close would "
        f"reject these reports identically. Repair the named report(s) so they "
        f"satisfy their declared schema before stopping. If a named report was "
        f"written by a sibling lane agent, report the blockage instead of "
        f"editing a peer's artifact.\n"
    )
    sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # A hook bug must never trap a subagent exit.
        sys.exit(0)
