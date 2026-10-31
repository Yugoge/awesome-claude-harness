#!/usr/bin/env python3
"""R4 late-repair route controller (spec-20260907-115508-lawful-commit-channel.md).

Owns the run-record lifecycle for the deliberately-invoked ``/close
--late-repair`` route as four independently CLI-invocable phases:

  init              Eligibility check (reads late_repair_eligible from
                     resolve-dev-artifact-chain.py -- the single source of
                     truth, never recomputed here) + run-record creation.
                     Refuses immediately, creating no record, when the chain
                     is not late-repair eligible.  Refuses --force outright.
  record-stage      Appends one of BA/Dev/QA's genuine completions to the
                     run record, enforcing stage order (ba -> dev -> qa),
                     taking the report path's role from the dispatch that
                     declared it (obligation.declaring_dispatch), and independently
                     recomputing its hash from the on-disk bytes -- never a
                     caller-supplied hash.  It writes nothing into the
                     report: each report has one producer, its stage's role.
  finalize          Runs the drift-detection + per-file routing phase
                     (scripts/check-late-repair-provenance.py) and decides
                     finalized_pending_verification / honest_refuse /
                     fail_closed.  On routed drift it writes the effective
                     report afresh, on every run, and checks the file it
                     wrote before it records the outcome and the path.  This
                     outcome is PROVISIONAL: it is not itself sufficient for
                     commit eligibility.
  verify-disclosure The same independent-recomputation corroboration
                     /close's own gate invokes, using ONLY task_id +
                     project_dir -- never a caller-supplied claim; each
                     refusal names the artifact's path.  Only a subsequent,
                     separate 'admitted' from this phase makes a late-repair
                     chain commit-eligible.

R4 does not grandfather work completed before R4 existed: a chain's only
lawful path via this route requires a run record created while the resolver
actually reported the eligible shape, never a label added afterward.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from sibling_loader import load_sibling_module, sha256_bytes  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hooks.lib.obligation import command_templates, declaring_dispatch  # noqa: E402  (who owes a report)

ROUTE = "R4-late-repair"
# The route runs the /dev cycle's dispatches that produce the chain's reports again.
CYCLE_COMMAND = "dev"


def stage_order(root: Path, task_id: str) -> tuple[str, ...]:
    """The route's stages, in order: the role of each dispatch template of the
    /dev cycle (commands/dev.md, in text order) that declares one of the
    chain's reports for this task (the resolver's parent paths), each role
    once. The templates are the declaration of who produces which report and
    in which order the cycle runs them; no list of roles is kept here."""
    resolver = load_sibling_module("resolve-dev-artifact-chain.py", __file__)
    reports = {resolver._rel(path, root)
               for path in resolver._parent_paths(root / "docs" / "dev", task_id).values()}
    order: list[str] = []
    for template in command_templates(CYCLE_COMMAND):
        role = template.get("role")
        for artifact in template.get("artifacts") or []:
            path = artifact.get("path") if isinstance(artifact, dict) else None
            if (isinstance(role, str) and isinstance(path, str) and role not in order
                    and re.sub(r"<[^<>/]+>", task_id, path) in reports):
                order.append(role)
    return tuple(order)


def _load_sibling_module(name: str) -> ModuleType:
    """Back-compat name: tests/test_late_repair_route.py calls this directly
    on the loaded controller module. Delegates to the single canonical
    implementation in scripts/lib/sibling_loader.py."""
    return load_sibling_module(name, __file__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _run_record_path(root: Path, task_id: str) -> Path:
    return root / "docs" / "dev" / f"late-repair-run-{task_id}.json"


def _write_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _effective_report_fault(path: Path, disclosure: dict[str, str]) -> str | None:
    """finalize's own check of the effective report it just wrote.

    finalize is that file's only producer and a script no gate sees, so the
    rule on it (the file exists, parses and carries the block finalize
    embedded) is decided here, before the outcome and path are recorded;
    every later reader takes the file from that record.
    """
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "effective report missing right after finalize wrote it"
    except (OSError, ValueError) as exc:
        return f"effective report unreadable right after finalize wrote it ({exc.__class__.__name__})"
    if not isinstance(doc, dict) or doc.get("retrospective_disclosure") != disclosure:
        return "effective report does not carry the retrospective_disclosure block finalize embedded"
    return None


def _derive_original_cycle_at(root: Path, task_id: str) -> tuple[str | None, str]:
    dev_report_path = root / "docs" / "dev" / f"dev-report-{task_id}.json"
    if dev_report_path.is_file():
        try:
            doc = json.loads(dev_report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {}
        ts = doc.get("timestamp") if isinstance(doc, dict) else None
        if isinstance(ts, str) and ts.strip():
            return ts, "dev_report_timestamp"
    # No dev-report (or no usable timestamp): fall back to independently
    # corroborable evidence -- the earliest git commit touching the files
    # this task's context declares, if a context exists.
    context_path = root / "docs" / "dev" / f"context-{task_id}.json"
    if context_path.is_file():
        try:
            context = json.loads(context_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            context = {}
        where = (
            context.get("requirement", {}).get("where")
            if isinstance(context.get("requirement"), dict)
            else None
        )
        if isinstance(where, list) and where:
            paths = [str(p) for p in where if isinstance(p, str)]
            if paths:
                proc = subprocess.run(
                    ["git", "-C", str(root), "log", "--follow", "--format=%aI", "--"] + paths,
                    capture_output=True, text=True,
                )
                dates = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
                if dates:
                    return sorted(dates)[0], "earliest_git_commit"
    return None, "none"


def _refuse(reason: str, exit_code: int, path: str | None = None) -> int:
    payload = {"outcome": "refuse", "reason": reason}
    if path is not None:
        payload["path"] = path
    _emit(payload)
    return exit_code


def _fail_closed_no_evidence(run_record_path: Path, record: dict[str, Any], stage: str) -> int:
    """AC-13(b): refuse BEFORE any report is touched when original_cycle_at is None.

    Persists outcome=='fail_closed' on the run record itself so a later
    finalize/verify-disclosure call sees the same terminal outcome rather
    than a stale None. Runs before the report is hashed or recorded, so no
    fabricated report enters the run record.
    """
    record["outcome"] = "fail_closed"
    _write_json(run_record_path, record)
    _emit({
        "outcome": "fail_closed",
        "reason": f"no independently corroborable original_cycle_at; refusing before stage {stage!r} is recorded",
    })
    return 6


def _dev_report_missing_at_init(root: Path, task_id: str, record: dict[str, Any]) -> bool:
    """AC-13(b) scope guard: true only for the exact 'no dev-report at all' shape.

    Combined with original_cycle_at is None (see cmd_record_stage), this
    gates EVERY stage (ba/dev/qa) per QA's "more conservative" reading --
    once a chain has no dev-report at all AND no independently corroborable
    evidence, the whole late-repair route refuses at the first stage rather
    than letting 'ba'/'qa' succeed pointlessly before 'dev' is blocked.

    True only when the canonical dev-report was itself absent (a recorded
    stage gap) at route-init time -- matching AC-13(b)'s literal "given: no
    dev-report at all". An ordinary beyond_qa chain whose dev-report already
    existed before the route started (e.g. missing only ticket/context,
    AC-8/AC-9's fixtures) is a DIFFERENT, already-eligible shape this guard
    must not newly block: its dev-report predates the route and is not a
    stage gap, so it is absent from live_snapshot.stage_gaps -- this is what
    makes the all-stage generalization safe without regressing those tests.
    """
    dev_report_rel = (root / "docs" / "dev" / f"dev-report-{task_id}.json").relative_to(root).as_posix()
    return dev_report_rel in record.get("live_snapshot", {}).get("stage_gaps", [])


def init_run(root: Path, task_id: str) -> tuple[int, dict[str, Any], dict[str, Any]]:
    """init's decision: (exit code, payload, the chain result it decided on).

    The chain result is /close --late-repair's one call of the chain
    function; close-route-select.py hands it on verbatim when init declines,
    so the ordinary route never resolves the chain a second time.
    """
    resolver = load_sibling_module("resolve-dev-artifact-chain.py", __file__)
    result = resolver.resolve_chain(root, task_id)
    if not resolver.late_repair_eligible(result):
        return 1, {"outcome": "refuse", "reason": "not a beyond-QA gap; use R1's route"}, result

    run_record_path = _run_record_path(root, task_id)
    if run_record_path.is_file():
        existing = json.loads(run_record_path.read_text(encoding="utf-8"))
        return 0, {"outcome": "already_initialized", "repair_run_id": existing["repair_run_id"]}, result

    parents = resolver._parent_paths(root / "docs" / "dev", task_id)
    pre_route_hashes: dict[str, str | None] = {}
    for key, path in parents.items():
        rel = resolver._rel(path, root)
        pre_route_hashes[rel] = _sha256_file(path) if path.is_file() else None

    original_cycle_at, source = _derive_original_cycle_at(root, task_id)
    repair_run_id = uuid.uuid4().hex
    record = {
        "schema_version": 1,
        "task_id": task_id,
        "repair_run_id": repair_run_id,
        "route": ROUTE,
        "live_snapshot": {
            "gap_classification": result["gap_classification"],
            "late_repair_eligible": result["late_repair_eligible"],
            "stage_gaps": result["stage_gaps"],
            "non_gap_errors": result["non_gap_errors"],
        },
        "pre_route_file_hashes": pre_route_hashes,
        "original_cycle_at": original_cycle_at,
        "original_cycle_at_source": source,
        "repair_started_at": _now_iso(),
        "stages": {},
        "outcome": None,
        "effective_report": None,
    }
    _write_json(run_record_path, record)
    return 0, {"outcome": "initialized", "repair_run_id": repair_run_id}, result


def cmd_init(ns: argparse.Namespace) -> int:
    if ns.force:
        return _refuse("--late-repair combined with --force is not permitted", 2)
    rc, payload, _chain = init_run(Path(ns.project_dir).resolve(), ns.task_id)
    _emit(payload)
    return rc


def _load_active_record(root: Path, task_id: str) -> dict[str, Any] | None:
    path = _run_record_path(root, task_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cmd_record_stage(ns: argparse.Namespace) -> int:
    root = Path(ns.project_dir).resolve()
    record = _load_active_record(root, ns.task_id)
    if record is None:
        return _refuse("no active late-repair run record for this task", 3)
    if record.get("repair_run_id") != ns.repair_run_id:
        return _refuse("repair-run-id does not match the active run record", 3)
    stages = stage_order(root, ns.task_id)
    if ns.stage not in stages:
        return _refuse(f"unknown stage: {ns.stage!r} (stages: {', '.join(stages) or 'none declared'})", 2)
    if (
        record.get("original_cycle_at") is None
        and _dev_report_missing_at_init(root, ns.task_id, record)
    ):
        return _fail_closed_no_evidence(_run_record_path(root, ns.task_id), record, ns.stage)
    if ns.stage in record["stages"]:
        return _refuse(f"stage {ns.stage!r} already recorded for this repair_run_id", 3)
    index = stages.index(ns.stage)
    for earlier in stages[:index]:
        if earlier not in record["stages"]:
            return _refuse(f"stage {ns.stage!r} recorded before {earlier!r}", 4)

    report_path = Path(ns.report_path)
    if not report_path.is_absolute():
        report_path = root / report_path
    if not report_path.is_file():
        return _refuse(f"--report-path does not exist: {ns.report_path}", 3)
    # A stage's report is one its own dispatch declared: the stage names the
    # role, and the declaring dispatch's obligation names the report's owner.
    owner = declaring_dispatch(ns.task_id, report_path, root)
    owner_role = owner.get("role") if owner and owner.get("source") == "dispatch" else None
    if owner_role != ns.stage:
        return _refuse(
            f"--report-path {_rel(report_path, root)} is not valid for stage {ns.stage!r}: "
            f"no {ns.stage} dispatch of this task declares it (declared by: {owner_role!r})",
            3,
        )

    sha256 = _sha256_file(report_path)
    root_rel = report_path.relative_to(root).as_posix()
    record["stages"][ns.stage] = {
        "report_path": root_rel,
        "sha256": sha256,
        "recorded_at": _now_iso(),
    }
    _write_json(_run_record_path(root, ns.task_id), record)
    _emit({"outcome": "recorded", "stage": ns.stage, "sha256": sha256})
    return 0


def cmd_finalize(ns: argparse.Namespace) -> int:
    root = Path(ns.project_dir).resolve()
    record = _load_active_record(root, ns.task_id)
    if record is None:
        return _refuse("no active late-repair run record for this task", 3)
    if record.get("repair_run_id") != ns.repair_run_id:
        return _refuse("repair-run-id does not match the active run record", 3)
    stages = stage_order(root, ns.task_id)
    if not stages:
        return _refuse("no stage declared: no /dev dispatch template declares a report of the chain", 3)
    for stage in stages:
        if stage not in record["stages"]:
            return _refuse(f"stage {stage!r} not yet recorded", 3)

    run_record_path = _run_record_path(root, ns.task_id)
    dev_report_path = root / "docs" / "dev" / f"dev-report-{ns.task_id}.json"
    if not dev_report_path.is_file():
        if record.get("original_cycle_at") is None:
            record["outcome"] = "fail_closed"
            _write_json(run_record_path, record)
            _emit({
                "outcome": "fail_closed",
                "reason": "no dev-report and no independently corroborable original_cycle_at",
            })
            return 6
        dev_rel = _rel(dev_report_path, root)
        return _refuse(f"dev report missing at finalize time despite a recorded dev stage: {dev_rel}", 3, dev_rel)

    checker = load_sibling_module("check-late-repair-provenance.py", __file__)
    provenance = checker.check(str(root), ns.task_id, dev_report_path)
    if provenance["status"] != "ok":
        return _refuse(provenance.get("reason", "provenance check failed"), 3)

    if not provenance["drift_detected"]:
        record["outcome"] = "finalized_pending_verification"
        record["drift_detected"] = {}
        record["effective_report"] = None
        _write_json(run_record_path, record)
        _emit({"outcome": "finalized_pending_verification", "drift_detected": {}})
        return 0

    if not provenance["reconcilable"]:
        record["outcome"] = "honest_refuse"
        _write_json(run_record_path, record)
        _emit({
            "outcome": "honest_refuse",
            "drift_detected": provenance["drift_detected"],
            "unroutable_files": provenance["unroutable_files"],
        })
        return 5

    # Written afresh from the task's dev report on every run, never refused
    # as a second run: running finalize again is how a file removed or broken
    # after an earlier run is repaired.
    effective_path = root / "docs" / "dev" / f"dev-report-{ns.task_id}.effective.json"
    effective_rel = _rel(effective_path, root)
    doc = json.loads(dev_report_path.read_text(encoding="utf-8"))
    final_hashes = dict(doc.get("final_source_hashes") or {})
    for rel in provenance["routing"]:
        final_hashes[rel] = _sha256_file(root / rel)
    doc["final_source_hashes"] = final_hashes
    doc["provenance_refresh"] = {
        "refreshed_at": _now_iso(),
        "drift_detected": provenance["drift_detected"],
        "routing": provenance["routing"],
    }
    doc["retrospective_disclosure"] = {
        "route": ROUTE,
        "repair_run_id": record["repair_run_id"],
        "original_cycle_at": str(record.get("original_cycle_at")),
        "produced_at": _now_iso(),
        "artifact": effective_path.name,
    }
    _write_json(effective_path, doc)
    fault = _effective_report_fault(effective_path, doc["retrospective_disclosure"])
    if fault is not None:
        return _refuse(f"{fault}: {effective_rel}", 3, effective_rel)

    record["outcome"] = "finalized_pending_verification"
    record["drift_detected"] = provenance["drift_detected"]
    record["effective_report"] = effective_rel
    _write_json(run_record_path, record)
    _emit({
        "outcome": "finalized_pending_verification",
        "drift_detected": provenance["drift_detected"],
        "effective_report": record["effective_report"],
    })
    return 0


def _refuse_verify(root: Path, path: Path, detail: str) -> int:
    # The refusal names the artifact's path, so /close and /commit route the
    # fault to that artifact's producer.
    rel = _rel(path, root)
    _emit({"outcome": "refused", "path": rel, "reason": f"not independently corroborated: {detail}: {rel}"})
    return 3


def cmd_verify_disclosure(ns: argparse.Namespace) -> int:
    root = Path(ns.project_dir).resolve()
    record = _load_active_record(root, ns.task_id)
    if record is None:
        return _refuse_verify(root, _run_record_path(root, ns.task_id), "no matching run record")
    expected_run_id = record["repair_run_id"]

    # finalize's effective report is no target here: finalize checked the
    # file when it wrote it, and the report is taken only from the outcome
    # and path it recorded (resolve_effective_report_state).
    targets: list[tuple[Path, str | None]] = []
    for stage in stage_order(root, ns.task_id):
        info = record.get("stages", {}).get(stage)
        if info:
            targets.append((root / info["report_path"], info.get("sha256")))

    if not targets:
        return _refuse_verify(
            root, _run_record_path(root, ns.task_id), "run record has no recorded artifacts to corroborate"
        )

    for path, expected_sha in targets:
        if not path.is_file():
            return _refuse_verify(root, path, "recorded stage report missing")
        if expected_sha is not None and _sha256_file(path) != expected_sha:
            return _refuse_verify(root, path, "hash mismatch against the run record")

    _emit({"outcome": "admitted", "repair_run_id": expected_run_id})
    return 0


def resolve_effective_report_state(project_dir: Path, task_id: str) -> tuple[str, Path | None]:
    """Tri-state answer shared by /commit's dev-report resolution points.

    Every caller takes the state and path verbatim; none re-checks the file.

    Returns ("none", None) when there is nothing for a caller to prefer over
    the canonical dev-report: either no late-repair state exists for task_id
    at all (byte-identical to pre-R4 behavior), or a corroborated run that
    finalize carried all the way to its drift-free outcome.  Returns
    ("verified", effective_path) when verify-disclosure admits the run and
    finalize recorded its routed-drift outcome with the effective report's
    path: the path finalize recorded, which finalize checked when it wrote
    the file; a file removed or broken since is a gap its first use names
    (the repository plan), repaired by running finalize again.  Returns
    ("invalid", path) otherwise (State C -- callers MUST fail closed here,
    never fall back to stale canonical provenance): path is the artifact
    verify-disclosure's refusal names, or the run record when its outcome is
    not one of finalize's two above.

    A null effective_report does NOT by itself mean "no drift": finalize
    leaves it null in every terminal state it can reach except the
    routed-drift one, and init writes that same null before finalize has run
    at all.  honest_refuse (drift found but unroutable) reports its drift
    only in the emitted payload and never records it; fail_closed and a
    not-yet-finalized record likewise leave drift_detected absent.  Only the
    drift-free branch records drift_detected == {} with outcome
    'finalized_pending_verification', in one record write.
    """
    root = Path(project_dir).resolve()
    run_record_path = _run_record_path(root, task_id)
    if not run_record_path.is_file():
        return "none", None
    ns = argparse.Namespace(task_id=task_id, project_dir=str(root))
    import io
    import contextlib

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rc = cmd_verify_disclosure(ns)
    try:
        payload = json.loads(buffer.getvalue().strip().splitlines()[-1])
    except (ValueError, IndexError):
        return "invalid", run_record_path
    if rc != 0 or payload.get("outcome") != "admitted":
        refused = payload.get("path")
        return "invalid", (root / refused) if refused else run_record_path
    record = _load_active_record(root, task_id)
    if record is not None and record.get("outcome") == "finalized_pending_verification":
        if record.get("effective_report"):
            return "verified", root / record["effective_report"]
        if record.get("drift_detected") == {}:
            return "none", None
    return "invalid", run_record_path


def cmd_resolve_effective_report(ns: argparse.Namespace) -> int:
    """Thin CLI wrapper around resolve_effective_report_state.

    Lets callers (e.g. commands/commit.md) invoke a stable, testable
    subcommand instead of dynamically loading this module inline, mirroring
    how scripts/dev-lifecycle.py exposes list-actionable.  The printed path
    is the function's, verbatim: the effective report for "verified", the
    path to route a finding on for "invalid".
    """
    state, path = resolve_effective_report_state(Path(ns.project_dir), ns.task_id)
    _emit({"state": state, "path": str(path) if path else None})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("--task-id", required=True)
    p_init.add_argument("--project-dir", required=True)
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_stage = sub.add_parser("record-stage")
    p_stage.add_argument("--task-id", required=True)
    p_stage.add_argument("--project-dir", required=True)
    p_stage.add_argument("--stage", required=True, help="the stage's role (see stage_order)")
    p_stage.add_argument("--report-path", required=True)
    p_stage.add_argument("--repair-run-id", required=True)
    p_stage.set_defaults(func=cmd_record_stage)

    p_finalize = sub.add_parser("finalize")
    p_finalize.add_argument("--task-id", required=True)
    p_finalize.add_argument("--project-dir", required=True)
    p_finalize.add_argument("--repair-run-id", required=True)
    p_finalize.set_defaults(func=cmd_finalize)

    p_verify = sub.add_parser("verify-disclosure")
    p_verify.add_argument("--task-id", required=True)
    p_verify.add_argument("--project-dir", required=True)
    p_verify.set_defaults(func=cmd_verify_disclosure)

    p_resolve = sub.add_parser("resolve-effective-report")
    p_resolve.add_argument("--task-id", required=True)
    p_resolve.add_argument("--project-dir", required=True)
    p_resolve.set_defaults(func=cmd_resolve_effective_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    return ns.func(ns)


if __name__ == "__main__":
    sys.exit(main())
