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
  6. Not a forced close (claude-close-force-<sid>.flag under the harness state
     dir, the process temp dir, or the legacy fixed location — forced closes
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
import hashlib
import importlib.util
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.agent_resolver import resolve_dev_registry_entry
from lib import contract_runtime
from lib import obligation
from lib.harness_state_dir import harness_state_dir

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


def _last_nonempty_line(text: str) -> str:
    """Return the last non-blank line of ``text`` (or '' when none)."""
    non_empty = [ln for ln in (text or "").splitlines() if ln.strip()]
    return non_empty[-1] if non_empty else ""


def _classify_verdict_line(line: str) -> str:
    """Classify a CLOSE: terminal line via the canonical close-verdict
    classifier (hooks/lib/close-verdict.py), loaded with SourceFileLoader
    (hyphenated filename -- same technique as scripts/close-report-
    append.py:205-211) so the AC5 consistency check can never silently
    drift from the authoritative classifier's own rules. Fail-open: any
    load/classify problem returns 'unknown', which never trips the
    verdict_class inconsistency check below (both sides must classify to
    'yes'/'no')."""
    try:
        from importlib.machinery import SourceFileLoader

        cv_path = Path(__file__).parent / "lib" / "close-verdict.py"
        module = SourceFileLoader("close_verdict", str(cv_path)).load_module()
        return module.classify_line(line)
    except Exception:
        return "unknown"


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


# ---------------------------------------------------------------------------
# Producer stop gate (lane L2): terminal state, downstream wires, bounded
# blocking with a nonce hand-off. Nothing here releases a producer by itself:
# the only exit-0 paths are (a) nothing failed, (b) the producer acknowledged a
# recorded escalation (see _ack_line), (c) advisory mode.
#
# Acknowledgement line: when the gate escalates (no progress, infrastructure
# fault, or gate exception) it writes a record to
#   .claude/dev-registry/<cycle_id>/escalations/<record_id>.json
# and quotes its nonce. The producer's NEXT final message must carry a whole
# line equal to  ESCALATION_ACK <nonce>  (last_assistant_message only). The
# gate admits that stop iff the nonce is the latest not-yet-admitted record of
# the same agent/task/reason. Records are never edited by this hook; they are
# resolved only by the orchestrator-side arbitration rule (docs/dev/
# arbitration-<cycle_id>.json), so admission is a recorded hand-off, not a
# verdict.
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
LEGACY_FLAG_DIR = "/tmp"  # historical forced-close flag location (read-only)
WIRE_FILE_TIMEOUT_S = 30
WIRE_TOTAL_BUDGET_S = 120
ACK_PREFIX = "ESCALATION_ACK"
_SHA_REF_RE = re.compile(r"^[0-9a-f]{7,40}$")


class _WireTimeout(BaseException):
    """Raised by the alarm handler; BaseException so no broad except eats it."""


def _fault(code: str, detail: str, path: str = "") -> dict:
    return {"code": code, "detail": detail, "path": path}


def _record_safe(value) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", str(value))


def _ack_line(nonce: str) -> str:
    return f"{ACK_PREFIX} {nonce}"


def _ack_present(message, nonce: str) -> bool:
    if not isinstance(message, str):
        return False
    want = _ack_line(nonce)
    return any(line.strip() == want for line in message.splitlines())


def _cycle_id(ob: dict):
    """C1: the dev-registry directory name of the cycle, or None when the
    obligation cannot be attributed to one."""
    task_id = ob.get("task_id")
    lane = ob.get("lane")
    if not isinstance(task_id, str) or not _TASK_ID_ANCHOR_RE.match(task_id):
        return None
    if lane is None:
        return task_id
    if not isinstance(lane, str) or not lane:
        return None
    suffix = "-" + lane
    if task_id.endswith(suffix) and len(task_id) > len(suffix):
        return task_id[: -len(suffix)]
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _atomic_write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".gate-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, str(path))


def _load_progress_helper():
    """Runtime import of the shared R15 helper; failure is a gate fault."""
    from lib import progress_measure  # noqa: WPS433 (deliberately late)

    return progress_measure


def _finding_key(pm, code: str, path: str, project_dir: str) -> str:
    if pm is not None:
        return pm.finding_id(code, path, project_dir)
    # Helper unavailable (fault path only): same code|relpath shape.
    return f"{code}|{os.path.normpath(str(path)).replace(os.sep, '/')}"


def _forced_close_flag_present(dev_session_id: str) -> bool:
    """Forced-close sentinel lookup through ONE helper: the harness state root,
    the process temp dir (honours TMPDIR) and the legacy fixed location."""
    name = f"claude-close-force-{dev_session_id}.flag"
    roots = []
    for root in (harness_state_dir(), tempfile.gettempdir(), LEGACY_FLAG_DIR):
        if root and root not in roots:
            roots.append(root)
    return any(os.path.exists(os.path.join(root, name)) for root in roots)


def _load_script_module(script_name: str):
    loader_path = SCRIPTS_DIR / "lib" / "sibling_loader.py"
    spec = importlib.util.spec_from_file_location("l2_sibling_loader", loader_path)
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    return loader.load_sibling_module(script_name, str(SCRIPTS_DIR / "placeholder.py"))


def _nested_claude_repo() -> list:
    """Same supported-repository admission /commit Step 5 passes: the real
    ~/.claude checkout (omitted when it is not a git checkout)."""
    try:
        real = os.path.realpath(os.path.expanduser("~/.claude"))
        proc = subprocess.run(
            ["git", "-C", real, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
        top = proc.stdout.strip()
        return [top] if proc.returncode == 0 and top else []
    except Exception:
        return []


def _with_alarm(seconds: float, fn):
    def _handler(signum, frame):
        raise _WireTimeout()

    try:
        previous = signal.signal(signal.SIGALRM, _handler)
    except (ValueError, AttributeError):
        return fn()
    signal.setitimer(signal.ITIMER_REAL, max(seconds, 0.05))
    try:
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _tail(text: str, limit: int = 6) -> list:
    lines = [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()]
    return [ln[:300] for ln in lines[-limit:]]


def _wire_ledger(report_full: Path, report_rel: str, project_dir: str, no_discover: bool,
                 timeout: float):
    argv = [sys.executable, str(SCRIPTS_DIR / "check-owned-edits-ledger.py"),
            str(report_full), "--git-root", project_dir, "--json"]
    if no_discover:
        argv.append("--no-discover")
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return [], [_fault("gate_infrastructure_fault", "owned-edits ledger checker timed out", report_rel)]
    except OSError as exc:
        return [], [_fault("gate_infrastructure_fault", f"owned-edits ledger checker not runnable: {exc!r}", report_rel)]
    if proc.returncode == 0:
        return [], []
    if proc.returncode == 1:
        return [{
            "path": report_rel, "reason": "owned_edits_ledger_violation",
            "errors": ["rejected by check-owned-edits-ledger.py (consumer: owned-edits ledger checker)"]
                      + _tail(proc.stdout or proc.stderr),
        }], []
    return [], [_fault(
        "gate_infrastructure_fault",
        f"check-owned-edits-ledger.py exit {proc.returncode}: " + " | ".join(_tail(proc.stderr or proc.stdout, 3)),
        report_rel,
    )]


def _wire_trial_plan(report_full: Path, report_rel: str, project_dir: str, task_id: str):
    """Returns (findings, faults, plan_or_None). PlanError of any code (or none)
    is a finding against the producer's report."""
    try:
        mod = _load_script_module("resolve-commit-repos.py")
    except Exception as exc:
        return [], [_fault("gate_infrastructure_fault", f"cannot load resolve-commit-repos.py: {exc!r}", report_rel)], None
    try:
        plan = _with_alarm(
            WIRE_FILE_TIMEOUT_S,
            lambda: mod.build_plan(
                task_id=task_id, control_root_arg=project_dir,
                supported_repo_args=_nested_claude_repo(), report_arg=str(report_full),
            ),
        )
    except _WireTimeout:
        return [], [_fault("gate_infrastructure_fault", "trial repository plan timed out", report_rel)], None
    except mod.PlanError as exc:
        code = getattr(exc, "code", None) or "uncoded"
        return [{
            "path": report_rel, "reason": "repository_plan_error",
            "errors": [f"/commit would reject this report (consumer: resolve-commit-repos.py build_plan), code={code}: {exc}"],
        }], [], None
    return [], [], plan


def _materialize_snapshot(value, git_root: str) -> bytes:
    if isinstance(value, str) and _SHA_REF_RE.match(value):
        try:
            probe = subprocess.run(["git", "-C", git_root, "cat-file", "-e", value],
                                   capture_output=True, timeout=10)
            if probe.returncode == 0:
                blob = subprocess.run(["git", "-C", git_root, "cat-file", "blob", value],
                                      capture_output=True, timeout=10)
                if blob.returncode == 0:
                    return blob.stdout
        except (OSError, subprocess.TimeoutExpired):
            pass
    return (value if isinstance(value, str) else json.dumps(value)).encode("utf-8")


def _repo_for_key(plan: dict, project_dir: str, key: str):
    """(repo_root, repo-relative path) the trial plan assigns ``key`` to."""
    absolute = os.path.normpath(os.path.join(project_dir, key))
    for repo in plan.get("repositories", []):
        root = repo.get("repo_root")
        if not isinstance(root, str):
            continue
        try:
            rel = os.path.relpath(os.path.realpath(absolute), os.path.realpath(root))
        except ValueError:
            continue
        if rel in repo.get("owned_paths", []):
            return root, rel
    return os.path.realpath(project_dir), key


def _wire_stager_replay(report: dict, report_rel: str, project_dir: str, plan: dict, deadline: float):
    owned = report.get("owned_edits")
    snapshots = report.get("pre_edit_snapshots")
    findings, faults = [], []
    if not isinstance(owned, dict) or not isinstance(snapshots, dict):
        return findings, faults
    with tempfile.TemporaryDirectory(prefix="l2-replay-") as scratch:
        for index, key in enumerate(sorted(owned)):
            if key not in snapshots or not isinstance(owned[key], list):
                continue  # shape/ledger defects are the ledger checker's finding
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                faults.append(_fault("gate_infrastructure_fault", "stager replay budget exhausted", key))
                break
            root, rel = _repo_for_key(plan, project_dir, key)
            ledger_path = Path(scratch) / f"ledger-{index}.json"
            snap_path = Path(scratch) / f"snapshot-{index}"
            ledger_path.write_text(json.dumps(owned[key], ensure_ascii=False), encoding="utf-8")
            snap_path.write_bytes(_materialize_snapshot(snapshots[key], root))
            argv = [sys.executable, str(SCRIPTS_DIR / "stage-owned-hunks.py"), "--git-root", root,
                    "--file", rel, "--ledger", str(ledger_path), "--snapshot", str(snap_path), "--dry-run"]
            try:
                proc = subprocess.run(argv, capture_output=True, text=True,
                                      timeout=min(WIRE_FILE_TIMEOUT_S, remaining))
            except subprocess.TimeoutExpired:
                faults.append(_fault("gate_infrastructure_fault", f"stager replay timed out for {key}", key))
                continue
            except OSError as exc:
                faults.append(_fault("gate_infrastructure_fault", f"stager not runnable: {exc!r}", key))
                continue
            if proc.returncode != 0:
                findings.append({
                    "path": key, "reason": "stager_replay_exclude",
                    "errors": [f"hunk stager (consumer: stage-owned-hunks.py --dry-run) would EXCLUDE this file, exit {proc.returncode}"]
                              + _tail(proc.stderr or proc.stdout, 3),
                })
    return findings, faults


def _load_lib_module(name: str):
    """Load scripts/lib/<name>.py by path (scripts/lib, not scripts/ -- see
    _load_script_module for the sibling-script loader this complements)."""
    path = SCRIPTS_DIR / "lib" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_journal_view_sidecar(project_dir: str, task_id: str) -> None:
    """Best-effort, non-blocking real caller for scripts/lib/attribution_
    aggregate_view.py (attribution-journal consumer cutover; see
    _wire_ledger_judgment's docstring) -- it otherwise has zero callers.
    Never raises: a failure here is simply no sidecar, never a finding."""
    try:
        view = _load_lib_module("attribution_aggregate_view")
        events, _ = view.aj.read_all_journals(None)
        doc = view.build_view(events, {"task_id": task_id}, root=project_dir)
        out = Path(project_dir) / "docs" / "dev" / f"journal-view-{task_id}.json"
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        pass


def _wire_ledger_judgment(report: dict, report_rel: str, project_dir: str, task_id: str,
                          deadline: float):
    """Attribution-journal consumer cutover (docs/reference/attribution-
    journal-cutover-flip-plan-20261003.md, superseded by the zero-blocking
    constraint of the follow-up consumer-cutover task): replaces this hook's
    two self-reported-ledger replay checks -- check-owned-edits-ledger.py's
    structural+replay validation and stage-owned-hunks.py --dry-run's hunk-
    replay exclusion. Both scripts still exist (this cycle switches callers,
    it does not delete code) but neither is invoked from this blocking path
    any more.

    Every path this cycle claims (dev.files_modified + dev.files_created) is
    asked the SAME lane-agnostic question scripts/resolve-commit-repos.py's
    ownership gate now asks (scripts/lib/attribution_adjudicator.py
    ledger_structural_verdict()): does the write-time hash-chain journal
    measure a structural conflict (ENTANGLED) for this path? Only that
    blocks here. No journal evidence at all, or evidence that does not
    reach back to the current HEAD blob, is deferred to the commit
    analyst's own judgment (agents/changelog-analyst.md's "Attribution and
    staging decision" is the actual staging authority, not this gate) --
    never a finding. A journal/adjudicator read failure is an infrastructure
    fault, never a verdict.
    """
    dev = report.get("dev") if isinstance(report.get("dev"), dict) else {}
    modified = dev.get("files_modified") if isinstance(dev.get("files_modified"), list) else []
    created = dev.get("files_created") if isinstance(dev.get("files_created"), list) else []
    paths = sorted({p for p in (modified + created) if isinstance(p, str) and p})
    findings, faults = [], []
    if not paths:
        return findings, faults
    try:
        ledger = _load_lib_module("attribution_adjudicator")
    except Exception as exc:
        return [], [_fault("gate_infrastructure_fault",
                           f"cannot load attribution_adjudicator.py: {exc!r}", report_rel)]
    for rel in paths:
        if time.monotonic() > deadline:
            faults.append(_fault("gate_infrastructure_fault", "ledger judgment budget exhausted", report_rel))
            break
        absolute = str(Path(project_dir) / rel)
        try:
            verdict = ledger.ledger_structural_verdict(absolute, root=project_dir, task_id=task_id)
        except Exception as exc:
            faults.append(_fault("gate_infrastructure_fault", f"ledger judgment failed for {rel}: {exc!r}", rel))
            continue
        if verdict.get("verdict") == ledger.ENTANGLED:
            findings.append({
                "path": rel, "reason": "ledger_entangled_conflict",
                "errors": [("write-time attribution journal (consumer: attribution_adjudicator.py) measures "
                           f"an unresolved structural conflict for this file: {verdict.get('detail', '')}")[:400]],
            })
    _write_journal_view_sidecar(project_dir, task_id)
    return findings, faults


def _wire_qa_chain(ob: dict, project_dir: str, qa_owned: set, timeout: float):
    """Returns (findings, faults, upstream_errors)."""
    argv = [sys.executable, str(SCRIPTS_DIR / "resolve-dev-artifact-chain.py"),
            "--task-id", str(ob.get("task_id")), "--project-dir", project_dir]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return [], [_fault("gate_infrastructure_fault", "artifact chain resolver timed out")], []
    except OSError as exc:
        return [], [_fault("gate_infrastructure_fault", f"artifact chain resolver not runnable: {exc!r}")], []
    if proc.returncode == 0:
        return [], [], []
    try:
        errors = json.loads(proc.stdout).get("errors")
    except Exception:
        errors = None
    if not isinstance(errors, list) or not errors:
        return [], [_fault("gate_infrastructure_fault",
                           f"resolve-dev-artifact-chain.py exit {proc.returncode} without attributable errors")], []
    findings, faults, upstream = [], [], []
    for err in errors:
        code = err.get("code") if isinstance(err, dict) else None
        path = err.get("path") if isinstance(err, dict) else None
        if not isinstance(code, str) or not code or not isinstance(path, str) or not path:
            faults.append(_fault("gate_infrastructure_fault", f"unattributable chain error: {err!r}"[:300]))
            continue
        norm = os.path.normpath(os.path.relpath(path, project_dir) if os.path.isabs(path) else path)
        if norm in qa_owned:
            findings.append({
                "path": norm, "reason": code,
                "errors": [f"artifact chain resolver (consumer: resolve-dev-artifact-chain.py) rejects your artifact: "
                           f"{str(err.get('detail', ''))[:300]}"],
            })
        else:
            upstream.append({"code": code, "path": norm, "detail": str(err.get("detail", ""))[:300]})
    return findings, faults, upstream


def _run_downstream_wires(project_dir: str, ob: dict, json_artifacts: list, qa_owned: set):
    """Wires a/b/c (dev-report) and d (qa chain). Returns
    (findings, faults, upstream_errors, deferrals)."""
    findings, faults, upstream, deferrals = [], [], [], []
    deadline = time.monotonic() + WIRE_TOTAL_BUDGET_S
    role = ob.get("role")
    lane_set = ob.get("lane_set")
    shard = isinstance(lane_set, list) and len(lane_set) > 1
    if role == "dev":
        for art in json_artifacts:
            # Only the v2 report carries the nested dev section, owned_edits
            # ledger and pre_edit_snapshots the downstream consumers read; the
            # flat v1 shape is unplannable by /commit itself and is shape-gated
            # only (schema + identity + terminal state).
            if not str(art.get("schema", "")).startswith("dev-report.v2"):
                continue
            report_rel = art["path"]
            report_full = Path(project_dir) / report_rel
            report = _read_json(report_full)
            f, x = _wire_ledger_judgment(report, report_rel, project_dir, str(ob.get("task_id")),
                                         deadline)
            findings += f
            faults += x
            if shard:
                deferrals.append({"checks": ["trial_plan"], "path": report_rel})
                continue
            f, x, _plan = _wire_trial_plan(report_full, report_rel, project_dir, str(ob.get("task_id")))
            findings += f
            faults += x
    elif role == "qa" and any(str(a.get("schema", "")).startswith("qa-report") for a in json_artifacts):
        f, x, up = _wire_qa_chain(ob, project_dir, qa_owned, max(deadline - time.monotonic(), 1))
        findings += f
        faults += x
        upstream += up
    return findings, faults, upstream, deferrals


def _cycle_dir(project_dir: str, cycle_id: str) -> Path:
    return Path(project_dir) / ".claude" / "dev-registry" / cycle_id


def _artifact_digests(project_dir: str, paths: list) -> dict:
    digests = {}
    for rel in paths:
        try:
            digests[rel] = hashlib.sha256((Path(project_dir) / rel).read_bytes()).hexdigest()
        except OSError:
            digests[rel] = "ABSENT"
    return digests


def _mint_record(project_dir: str, ob: dict, cycle_id: str, agent_id: str, agent_type: str,
                 kind: str, reason, finding_keys: list, paths: list) -> dict:
    """C1/C2 record, atomic. Raises on any failure (caller treats as no hand-off)."""
    record_id = "esc" + secrets.token_hex(10)
    record = {
        "record_id": record_id,
        "nonce": secrets.token_hex(16),
        "agent_id": agent_id,
        "task_id": ob.get("task_id"),
        "finding_keys": list(finding_keys),
        "created_at": _now_iso(),
        "kind": kind,
        "role": agent_type or ob.get("role"),
        "artifact_digests": _artifact_digests(project_dir, paths),
    }
    if reason is not None:
        record["reason"] = reason
    path = _cycle_dir(project_dir, cycle_id) / "escalations" / f"{record_id}.json"
    _atomic_write_json(path, record)
    record["_path"] = str(path)
    return record


def _latest_unadmitted(project_dir: str, cycle_id: str, agent_id: str, task_id, reason):
    esc = _cycle_dir(project_dir, cycle_id) / "escalations"
    adm = _cycle_dir(project_dir, cycle_id) / "escalation-admissions"
    best = None
    try:
        candidates = sorted(esc.glob("*.json"))
    except OSError:
        return None
    for p in candidates:
        rec = _read_json(p)
        if (rec.get("kind") != "producer_stop_escalation" or rec.get("agent_id") != agent_id
                or rec.get("task_id") != task_id or rec.get("reason") != reason
                or not isinstance(rec.get("nonce"), str) or not isinstance(rec.get("record_id"), str)):
            continue
        if (adm / f"{rec['record_id']}.json").exists():
            continue
        order = (str(rec.get("created_at", "")), p.name)
        if best is None or order > best[0]:
            best = (order, rec)
    return best[1] if best else None


def _write_side_records(project_dir: str, ob: dict, agent_id: str, agent_type: str, upstream: list,
                        deferrals: list, paths: list) -> list:
    """Upstream-defect notices (qa, admitted without a nonce) and shard deferrals.
    Returns faults (empty when everything was recorded)."""
    faults = []
    cycle_id = _cycle_id(ob)
    if (upstream or deferrals) and cycle_id is None:
        return [_fault("gate_infrastructure_fault", "obligation cannot be attributed to a cycle directory")]
    try:
        pm = _load_progress_helper() if upstream else None
        if upstream:
            keys = sorted({_finding_key(pm, e["code"], e["path"], project_dir) for e in upstream})
            esc = _cycle_dir(project_dir, cycle_id) / "escalations"
            duplicate = False
            if esc.is_dir():
                for p in esc.glob("*.json"):
                    rec = _read_json(p)
                    if (rec.get("kind") == "upstream_defect_notice" and rec.get("agent_id") == agent_id
                            and rec.get("task_id") == ob.get("task_id")
                            and sorted(rec.get("finding_keys", [])) == keys):
                        duplicate = True
                        break
            if not duplicate:
                rec = _mint_record(project_dir, ob, cycle_id, agent_id, agent_type,
                                   "upstream_defect_notice", None, keys, paths)
                rec["upstream_errors"] = upstream
                _atomic_write_json(Path(rec.pop("_path")), rec)
            _emit_advisory({"kind": "obligation_upstream_defect_notice", "agent_id": agent_id,
                            "task_id": ob.get("task_id"), "finding_keys": keys})
        if deferrals:
            checks = sorted({c for d in deferrals for c in d["checks"]})
            _atomic_write_json(
                _cycle_dir(project_dir, cycle_id) / "deferred-checks" / f"{_record_safe(agent_id)}.json",
                {"kind": "not_evaluable_at_lane_granularity", "task_id": ob.get("task_id"),
                 "agent_id": agent_id, "lane": ob.get("lane"), "checks": checks,
                 "created_at": _now_iso()},
            )
            _emit_advisory({"kind": "obligation_check_deferred", "agent_id": agent_id,
                            "task_id": ob.get("task_id"), "lane": ob.get("lane"),
                            "reason": "not_evaluable_at_lane_granularity", "checks": checks})
    except Exception as exc:
        faults.append(_fault("gate_exception", f"cannot write side record: {exc!r}"))
    return faults


def _clear_progress(project_dir: str, ob: dict, agent_id: str) -> None:
    """The producer's own trigger became false: drop its progress state."""
    try:
        cycle_id = _cycle_id(ob)
        if cycle_id is None:
            return
        pm = _load_progress_helper()
        pm.clear_state(_cycle_dir(project_dir, cycle_id) / "progress"
                       / f"producer-stop-{_record_safe(agent_id)}.json")
    except Exception:
        pass


def _gate_decide(project_dir: str, ob: dict, agent_id: str, agent_type: str, failures: list,
                 faults: list, paths: list, message, block_text: str) -> int:
    """Block-mode decision for a failing stop: exit code (stderr already written).
    Never returns 0 unless the producer acknowledged a recorded escalation."""
    cycle_id = _cycle_id(ob)
    task_id = ob.get("task_id")
    faults = list(faults)
    pm = None
    outcome = None
    if cycle_id is not None:
        try:
            pm = _load_progress_helper()
        except Exception as exc:
            faults.append(_fault("gate_infrastructure_fault", f"progress helper unavailable: {exc!r}"))
        if pm is not None:
            try:
                keys = [_finding_key(pm, f["reason"], f["path"], project_dir) for f in failures]
                keys += [_finding_key(pm, x["code"], x.get("path") or str(task_id), project_dir) for x in faults]
                rnd = pm.record_round(
                    _cycle_dir(project_dir, cycle_id) / "progress" / f"producer-stop-{_record_safe(agent_id)}.json",
                    f"producer-stop|{task_id}|{agent_id}",
                    pm.world_fingerprint(project_dir, paths),
                    keys,
                )
                outcome = rnd.get("outcome")
                if outcome == "unwritable":
                    faults.append(_fault("gate_infrastructure_fault", f"progress state unwritable: {rnd.get('reason')}"))
                elif outcome not in ("first", "progress", "no_progress"):
                    faults.append(_fault("gate_infrastructure_fault", f"unknown progress outcome {outcome!r}"))
            except Exception as exc:
                faults.append(_fault("gate_exception", f"progress measure failed: {exc!r}"))
    reason = None
    if faults:
        reason = faults[0]["code"]
    elif outcome == "no_progress":
        reason = "no_progress"
    if cycle_id is None:
        sys.stderr.write(
            block_text
            + "GATE_FAULT: this obligation cannot be attributed to a cycle directory (task_id/lane mismatch), "
              "so no escalation can be recorded; the stop stays blocked.\n"
        )
        return 2
    if reason is None:
        sys.stderr.write(block_text)
        return 2
    # Escalation: admit only on the acknowledgement of the latest unadmitted record.
    try:
        prior = _latest_unadmitted(project_dir, cycle_id, agent_id, task_id, reason)
        if prior is not None and _ack_present(message, prior["nonce"]):
            _atomic_write_json(
                _cycle_dir(project_dir, cycle_id) / "escalation-admissions" / f"{prior['record_id']}.json",
                {"record_id": prior["record_id"], "nonce": prior["nonce"], "agent_id": agent_id,
                 "admitted_at": _now_iso()},
            )
            _emit_advisory({"kind": "obligation_escalation_admitted", "agent_id": agent_id,
                            "task_id": task_id, "reason": reason, "record_id": prior["record_id"]})
            return 0
    except Exception as exc:
        faults.append(_fault("gate_exception", f"admission check failed: {exc!r}"))
        reason = reason or "gate_exception"
    try:
        keys = [_finding_key(pm, f["reason"], f["path"], project_dir) for f in failures]
        keys += [_finding_key(pm, x["code"], x.get("path") or str(task_id), project_dir) for x in faults]
        rec = _mint_record(project_dir, ob, cycle_id, agent_id, agent_type, "producer_stop_escalation",
                           reason, sorted(set(keys)), paths)
    except Exception as exc:
        sys.stderr.write(
            block_text
            + f"GATE_FAULT: escalation record could not be written ({exc!r}); a hand-off that cannot be "
              "recorded is not a hand-off, so the stop stays blocked.\n"
        )
        return 2
    detail = "".join(f"  - {x['code']}: {x['detail']}\n" for x in faults)
    sys.stderr.write(
        block_text
        + f"ESCALATION: reason={reason}. A hand-off record was written for the orchestrator "
          f"(record_id={rec['record_id']}, unresolved until arbitrated).\n{detail}"
          f"If you cannot repair the artifact(s) above, report that in your final message and make one whole "
          f"line of it exactly:\n{_ack_line(rec['nonce'])}\n"
          f"Your next stop is then admitted as a recorded hand-off, not as a pass.\n"
    )
    return 2


def main() -> None:
    data = _load_stdin()
    if not data:
        sys.exit(0)

    agent_id = data.get("agent_id")
    if not agent_id:
        sys.exit(0)

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())

    # Resolved unconditionally (no early-exit here): the obligation-mode
    # block below does not depend on agent-index.json / resolve_dev_registry_entry
    # at all (hooks/lib/obligation.py has zero references to either). The
    # LOW-10 "never hard-block on an unresolved agent" early-exits are
    # deferred to immediately before the LEGACY correlation path's first
    # actual use of dev_session_id, below -- relocated so a skipped FIRST
    # ACTION registry Read no longer silently discards obligation-mode
    # enforcement of the agent's own dev-report/context.json obligation too.
    entry = resolve_dev_registry_entry(agent_id, project_dir)
    agent_type = entry.get("agent_type", "") if entry else ""

    # Obligation mode (rollout S4): verify the artifacts THIS agent's own
    # dispatch obligation names, ahead of the session-wide correlation guess
    # below. CLAUDE_OBLIGATION_STOPGATE is a DIFFERENT switch from
    # ARTIFACT_CONTRACT_ENFORCE_MODE, which continues to govern only the
    # untouched legacy path.
    stopgate_mode = os.environ.get("CLAUDE_OBLIGATION_STOPGATE", "advisory").strip().lower()
    if stopgate_mode not in {"advisory", "block", "off"}:
        stopgate_mode = "advisory"
    if stopgate_mode != "off":
        try:
            session_id = data.get("session_id") or data.get("sessionId")
            transcript_hint = data.get("agent_transcript_path")
            last_assistant_message = data.get("last_assistant_message")
            resolution = obligation.resolve_own_obligation(
                session_id=session_id,
                agent_id=agent_id,
                project_dir=project_dir,
                payload_agent_transcript_path=transcript_hint,
                expected_role=agent_type if agent_type in obligation.ROLES else None,
            )
            if isinstance(resolution, obligation.Resolved):
                artifacts = resolution.obligation.get("artifacts", [])
                json_artifacts = [a for a in artifacts if a.get("kind") == "json"]
                markdown_artifacts = [a for a in artifacts if a.get("kind") == "markdown"]
                response_line_artifacts = [a for a in artifacts if a.get("kind") == "response_line"]
                response_block_artifacts = [a for a in artifacts if a.get("kind") == "response_block"]
                verified_artifacts = (
                    json_artifacts + markdown_artifacts + response_line_artifacts
                    + response_block_artifacts
                )
                for art in artifacts:
                    if art.get("kind") not in ("json", "markdown", "response_line", "response_block"):
                        # W1/M4: any other unknown kind belongs to a
                        # different G5 bullet; informationally skipped
                        # here, never blocked or crashed on.
                        _emit_advisory(
                            {
                                "kind": "obligation_artifact_kind_unsupported",
                                "artifact_kind": art.get("kind"),
                                "agent_id": agent_id,
                            }
                        )
                failures = []
                for art in json_artifacts:
                    full_path = Path(project_dir) / art["path"]
                    result = contract_runtime.validate_artifact_for_obligation(
                        str(full_path), art["schema"]
                    )
                    if result.get("status") == "skip":
                        # Infra unavailable (unregistered schema id, registry
                        # error): fail-safe, never a verification failure.
                        _emit_advisory(
                            {
                                "kind": "obligation_artifact_skip",
                                "path": art["path"],
                                "reason": result.get("reason"),
                            }
                        )
                        continue
                    if result.get("status") == "fail":
                        failures.append(
                            {
                                "path": art["path"],
                                "reason": result.get("reason"),
                                "errors": result.get("errors", [])[:10],
                            }
                        )
                        continue
                    # "pass": identity comparison is this lane's own
                    # responsibility (validate_artifact_for_obligation does
                    # not check it).
                    record = _read_json(full_path)
                    for key, value in art.get("identity", {}).items():
                        if record.get(key) != value:
                            failures.append(
                                {
                                    "path": art["path"],
                                    "reason": "identity_mismatch",
                                    "errors": [
                                        f"identity.{key}: obligation declares "
                                        f"{value!r}, file has {record.get(key)!r}"
                                    ],
                                }
                            )
                    # M1: terminal state (L1 required_values). Unevaluable is a
                    # blocking finding, never a silent skip.
                    if "required_values" in art:
                        try:
                            terminal = obligation.evaluate_required_values(
                                record, art["required_values"]
                            )
                        except Exception as exc:
                            failures.append(
                                {
                                    "path": art["path"],
                                    "reason": "terminal_constraint_unevaluable",
                                    "errors": [f"required_values could not be evaluated: {exc!r}"],
                                }
                            )
                        else:
                            if terminal:
                                failures.append(
                                    {
                                        "path": art["path"],
                                        "reason": "terminal_value_violation",
                                        "errors": [
                                            (
                                                f"{v.get('path')}: missing, admissible values {v.get('allowed')}"
                                                if v.get("reason") == "missing_terminal_path"
                                                else f"{v.get('path')}: actual {v.get('actual')!r}, "
                                                f"admissible values {v.get('allowed')}"
                                            )
                                            for v in terminal
                                        ],
                                    }
                                )
                markdown_waived_paths: set[str] = set()
                for art in markdown_artifacts:
                    # M3: markdown-kind entries get the same producer-side
                    # Stop verification json-kind entries already have,
                    # reusing the shared contract_runtime function (ticket
                    # 20261001-161041-r01) -- folded into the SAME
                    # failures/advisory/block control flow, no new branch.
                    #
                    # waived_by_response (ticket 20261001-161041-r12, AC4):
                    # an append-sentinel response means
                    # scripts/close-report-append.py itself already refused
                    # to touch the file -- its on-disk terminal line
                    # reflects a PRIOR, unrelated attempt, so the file
                    # check is SKIPPED (not failed) and excluded from the
                    # consistency check below.
                    waiver = art.get("waived_by_response")
                    if (
                        isinstance(waiver, str) and waiver
                        and isinstance(last_assistant_message, str)
                        and re.search(waiver, last_assistant_message)
                    ):
                        markdown_waived_paths.add(art["path"])
                        _emit_advisory(
                            {
                                "kind": "obligation_markdown_waived",
                                "path": art["path"],
                                "agent_id": agent_id,
                            }
                        )
                        continue
                    full_path = Path(project_dir) / art["path"]
                    result = contract_runtime.validate_markdown_artifact_for_obligation(
                        str(full_path), art.get("identity_anchor"), art.get("terminal_line_regex")
                    )
                    if result.get("status") == "fail":
                        failures.append(
                            {
                                "path": art["path"],
                                "reason": result.get("reason"),
                                "errors": result.get("errors", [])[:10],
                            }
                        )
                for art in response_line_artifacts:
                    # response_line-kind entries (ticket 20261001-161041-r12,
                    # AC3): validated against this agent's OWN final
                    # response text, independent of the markdown file
                    # channel above -- a failure here never suppresses, and
                    # is never suppressed by, a markdown-channel result.
                    result = contract_runtime.validate_response_line_for_obligation(
                        last_assistant_message, art.get("terminal_line_regex")
                    )
                    if result.get("status") == "fail":
                        failures.append(
                            {
                                "path": "<response_line>",
                                "reason": result.get("reason"),
                                "errors": result.get("errors", [])[:10],
                            }
                        )
                for art in response_block_artifacts:
                    # response_block-kind entries (ticket 20261001-161041-r21,
                    # M2): validated against this agent's OWN final response
                    # text via the sentinel-delimited JSON block it declares
                    # (e.g. changelog-analyst's changelog-status.v1), reusing
                    # the SAME last_assistant_message field response_line
                    # already keys off -- no transcript scan, no second
                    # jsonschema call path (see
                    # contract_runtime.validate_response_block_for_obligation).
                    result = contract_runtime.validate_response_block_for_obligation(
                        last_assistant_message, art.get("begin"), art.get("end"), art["schema"]
                    )
                    if result.get("status") == "skip":
                        _emit_advisory(
                            {
                                "kind": "obligation_artifact_skip",
                                "path": "<response_block>",
                                "reason": result.get("reason"),
                            }
                        )
                        continue
                    if result.get("status") == "fail":
                        failures.append(
                            {
                                "path": "<response_block>",
                                "reason": result.get("reason"),
                                "errors": result.get("errors", [])[:10],
                            }
                        )
                # Cross-channel consistency (ticket 20261001-161041-r12,
                # AC5): the markdown artifact's file terminal line and the
                # response_line artifact's response terminal line must
                # classify to the same CLOSE: verdict. Skipped when the
                # obligation does not declare consistency:"verdict_class",
                # either channel is absent, the markdown channel was
                # waived (no file verdict to compare), or either channel's
                # own check already failed above (that failure is already
                # reported; a derived inconsistency would be redundant).
                if (
                    resolution.obligation.get("consistency") == "verdict_class"
                    and markdown_artifacts and response_line_artifacts
                    and not markdown_waived_paths
                    and not failures
                ):
                    try:
                        md_path = Path(project_dir) / markdown_artifacts[0]["path"]
                        md_class = _classify_verdict_line(
                            _last_nonempty_line(md_path.read_text(encoding="utf-8"))
                        )
                        resp_text = (
                            last_assistant_message
                            if isinstance(last_assistant_message, str) else ""
                        )
                        resp_class = _classify_verdict_line(_last_nonempty_line(resp_text))
                        if (
                            md_class in ("yes", "no") and resp_class in ("yes", "no")
                            and md_class != resp_class
                        ):
                            failures.append(
                                {
                                    "path": markdown_artifacts[0]["path"],
                                    "reason": "verdict_class_inconsistent",
                                    "errors": [
                                        f"file classifies '{md_class}', response classifies '{resp_class}'"
                                    ],
                                }
                            )
                    except Exception:
                        pass  # fail-open: never block on consistency-check infra errors
                # Downstream wires (L2): only once the artifacts themselves are
                # shape- and terminal-valid, so the checkers see a usable report.
                gate_faults: list = []
                upstream_defects: list = []
                shard_deferrals: list = []
                fingerprint_paths = [a["path"] for a in json_artifacts + markdown_artifacts]
                qa_owned = {
                    os.path.normpath(a["path"]) for a in artifacts
                    if isinstance(a.get("path"), str)
                }
                if not failures:
                    try:
                        wire_findings, wire_faults, upstream_defects, shard_deferrals = (
                            _run_downstream_wires(
                                project_dir, resolution.obligation, json_artifacts, qa_owned
                            )
                        )
                        failures.extend(wire_findings)
                        gate_faults.extend(wire_faults)
                    except Exception as exc:
                        gate_faults.append(_fault("gate_exception", f"downstream wire crashed: {exc!r}"))
                if stopgate_mode == "block":
                    gate_faults.extend(
                        _write_side_records(
                            project_dir, resolution.obligation, agent_id, agent_type,
                            upstream_defects, shard_deferrals, fingerprint_paths,
                        )
                    )
                elif upstream_defects or shard_deferrals:
                    _emit_advisory(
                        {
                            "kind": "obligation_wire_notice",
                            "agent_id": agent_id,
                            "upstream_defects": upstream_defects[:10],
                            "deferred": shard_deferrals[:10],
                        }
                    )
                if not failures and not gate_faults:
                    # M3: all pass -- bypass the legacy correlation path
                    # entirely for this stop.
                    if stopgate_mode == "block":
                        _clear_progress(project_dir, resolution.obligation, agent_id)
                    sys.exit(0)
                task_id = resolution.obligation.get("task_id")
                _emit_advisory(
                    {
                        "kind": "obligation_verify_fail",
                        "mode": stopgate_mode,
                        "agent_id": agent_id,
                        "agent_type": agent_type,
                        "task_id": task_id,
                        "failures": failures[:10],
                        "faults": gate_faults[:10],
                    }
                )
                if stopgate_mode == "block":
                    detail_lines = ""
                    for f in failures[:10]:
                        detail_lines += f"  - {f['path']}: {f['reason']}\n"
                        for err in f.get("errors", [])[:10]:
                            detail_lines += f"    {err}\n"
                    block_text = (
                        f"OBLIGATION_STOPGATE_BLOCKED: agent {agent_id} "
                        f"(role={agent_type}, task_id={task_id}) declared "
                        f"{len(verified_artifacts)} obligated artifact(s); "
                        f"{len(failures)} failed verification:\n"
                        f"{detail_lines}"
                        f"Fix your OWN artifact(s) listed above, then stop "
                        f"again. Do NOT edit any other agent's artifact.\n"
                    )
                    try:
                        decision = _gate_decide(
                            project_dir, resolution.obligation, agent_id, agent_type,
                            failures, gate_faults, fingerprint_paths,
                            last_assistant_message, block_text,
                        )
                    except Exception as exc:
                        # Never fail open: an unrecordable decision stays blocked.
                        sys.stderr.write(block_text + f"GATE_FAULT: gate decision crashed ({exc!r}); stop stays blocked.\n")
                        decision = 2
                    sys.exit(decision)
                # advisory mode: never blocks (AC4/AC5).
                sys.exit(0)
            elif isinstance(resolution, obligation.Unresolvable):
                # S1: lightweight advisory record for rollout observability.
                _emit_advisory(
                    {
                        "kind": "obligation_unresolvable",
                        "agent_id": agent_id,
                        "reason": resolution.reason,
                        "detail": resolution.detail,
                    }
                )
            # else: NoObligationInPrompt -- the expected, extremely common
            # case for every non-obligated dispatch; no advisory record
            # (would spam the log for zero informational value).
        except Exception as exc:
            # M4: an obligation-mode-only failure must degrade to "run
            # legacy path", never "allow" and never escape from inside
            # this except block.
            _emit_advisory(
                {
                    "kind": "obligation_gate_error",
                    "agent_id": agent_id,
                    "error": repr(exc),
                }
            )

    prefix = REPORT_PREFIX_BY_AGENT_TYPE.get(agent_type)
    if prefix is None:
        sys.exit(0)

    # LOW-10: never hard-block the legacy correlation path on an
    # unresolved agent. Deferred here (was previously gating the
    # obligation-mode block above too) because only this legacy path
    # actually needs dev_session_id.
    if entry is None:
        sys.exit(0)
    dev_session_id = entry.get("dev_session_id")
    if not dev_session_id:
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
    if _forced_close_flag_present(dev_session_id):
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
