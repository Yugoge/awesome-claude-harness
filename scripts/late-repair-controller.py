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
                     validating the report path's role, embedding a
                     retrospective_disclosure block into the artifact, and
                     independently recomputing its hash from the resulting
                     on-disk bytes -- never a caller-supplied hash.
  finalize          Runs the drift-detection + per-file routing phase
                     (scripts/check-late-repair-provenance.py) and decides
                     finalized_pending_verification / honest_refuse /
                     fail_closed.  This outcome is PROVISIONAL: it is not
                     itself sufficient for commit eligibility.
  verify-disclosure The same independent-recomputation corroboration
                     /close's own gate invokes, using ONLY task_id +
                     project_dir -- never a caller-supplied claim.  Only a
                     subsequent, separate 'admitted' from this phase makes a
                     late-repair chain commit-eligible.

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

ROUTE = "R4-late-repair"
STAGE_ORDER = ("ba", "dev", "qa")
DISCLOSURE_FIELDS = ("route", "repair_run_id", "original_cycle_at", "produced_at", "artifact")


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


def _stage_accepted_basenames(stage: str, task_id: str) -> set[str]:
    return {
        "ba": {f"ticket-{task_id}.md", f"context-{task_id}.json"},
        "dev": {f"dev-report-{task_id}.json"},
        "qa": {f"qa-report-{task_id}.json"},
    }[stage]


def _embed_disclosure(path: Path, disclosure: dict[str, str]) -> None:
    if path.suffix == ".json":
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["retrospective_disclosure"] = disclosure
        path.write_text(
            json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"\n*<!--\s*retrospective_disclosure.*?-->\n*", "\n", text, flags=re.DOTALL)
    lines = ["<!-- retrospective_disclosure"]
    for key in DISCLOSURE_FIELDS:
        lines.append(f"{key}: {disclosure[key]}")
    lines.append("-->")
    path.write_text(text.rstrip("\n") + "\n\n" + "\n".join(lines) + "\n", encoding="utf-8")


def _read_disclosure(path: Path) -> dict[str, str] | None:
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        try:
            doc = json.loads(raw)
        except ValueError:
            return None
        value = doc.get("retrospective_disclosure") if isinstance(doc, dict) else None
        return value if isinstance(value, dict) else None
    match = re.search(r"<!--\s*retrospective_disclosure\s*(.*?)-->", raw, re.DOTALL)
    if not match:
        return None
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        result[key.strip()] = value.strip()
    return result or None


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


def _refuse(reason: str, exit_code: int) -> int:
    _emit({"outcome": "refuse", "reason": reason})
    return exit_code


def _fail_closed_no_evidence(run_record_path: Path, record: dict[str, Any], stage: str) -> int:
    """AC-13(b): refuse BEFORE any report is touched when original_cycle_at is None.

    Persists outcome=='fail_closed' on the run record itself so a later
    finalize/verify-disclosure call sees the same terminal outcome rather
    than a stale None. Runs before _embed_disclosure/_sha256_file are ever
    reached, so no dev-report is written or mutated as a side effect of
    this refusal.
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


def cmd_init(ns: argparse.Namespace) -> int:
    if ns.force:
        return _refuse("--late-repair combined with --force is not permitted", 2)

    root = Path(ns.project_dir).resolve()
    resolver = load_sibling_module("resolve-dev-artifact-chain.py", __file__)
    result = resolver.resolve_chain(root, ns.task_id)
    if result.get("mode") != "singular" or result.get("late_repair_eligible") is not True:
        return _refuse("not a beyond-QA gap; use R1's route", 1)

    run_record_path = _run_record_path(root, ns.task_id)
    if run_record_path.is_file():
        existing = json.loads(run_record_path.read_text(encoding="utf-8"))
        _emit({"outcome": "already_initialized", "repair_run_id": existing["repair_run_id"]})
        return 0

    parents = resolver._parent_paths(root / "docs" / "dev", ns.task_id)
    pre_route_hashes: dict[str, str | None] = {}
    for key, path in parents.items():
        rel = resolver._rel(path, root)
        pre_route_hashes[rel] = _sha256_file(path) if path.is_file() else None

    original_cycle_at, source = _derive_original_cycle_at(root, ns.task_id)
    repair_run_id = uuid.uuid4().hex
    record = {
        "schema_version": 1,
        "task_id": ns.task_id,
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
    _emit({"outcome": "initialized", "repair_run_id": repair_run_id})
    return 0


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
    if ns.stage not in STAGE_ORDER:
        return _refuse(f"unknown stage: {ns.stage!r}", 2)
    if (
        record.get("original_cycle_at") is None
        and _dev_report_missing_at_init(root, ns.task_id, record)
    ):
        return _fail_closed_no_evidence(_run_record_path(root, ns.task_id), record, ns.stage)
    if ns.stage in record["stages"]:
        return _refuse(f"stage {ns.stage!r} already recorded for this repair_run_id", 3)
    index = STAGE_ORDER.index(ns.stage)
    for earlier in STAGE_ORDER[:index]:
        if earlier not in record["stages"]:
            return _refuse(f"stage {ns.stage!r} recorded before {earlier!r}", 4)

    report_path = Path(ns.report_path)
    if not report_path.is_absolute():
        report_path = root / report_path
    if not report_path.is_file():
        return _refuse(f"--report-path does not exist: {ns.report_path}", 3)
    accepted = _stage_accepted_basenames(ns.stage, ns.task_id)
    if report_path.name not in accepted:
        return _refuse(
            f"--report-path basename {report_path.name!r} is not valid for stage "
            f"{ns.stage!r} (expected one of {sorted(accepted)!r})",
            3,
        )

    disclosure = {
        "route": ROUTE,
        "repair_run_id": record["repair_run_id"],
        "original_cycle_at": str(record.get("original_cycle_at")),
        "produced_at": _now_iso(),
        "artifact": report_path.name,
    }
    _embed_disclosure(report_path, disclosure)
    sha256 = _sha256_file(report_path)
    root_rel = report_path.relative_to(root).as_posix()
    record["stages"][ns.stage] = {
        "report_path": root_rel,
        "sha256": sha256,
        "recorded_at": disclosure["produced_at"],
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
    for stage in STAGE_ORDER:
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
        return _refuse("dev report missing at finalize time despite a recorded dev stage", 3)

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

    effective_path = root / "docs" / "dev" / f"dev-report-{ns.task_id}.effective.json"
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
    _write_json(effective_path, doc)
    disclosure = {
        "route": ROUTE,
        "repair_run_id": record["repair_run_id"],
        "original_cycle_at": str(record.get("original_cycle_at")),
        "produced_at": _now_iso(),
        "artifact": effective_path.name,
    }
    _embed_disclosure(effective_path, disclosure)

    record["outcome"] = "finalized_pending_verification"
    record["drift_detected"] = provenance["drift_detected"]
    record["effective_report"] = effective_path.relative_to(root).as_posix()
    record["effective_report_disclosure_sha256"] = _sha256_file(effective_path)
    _write_json(run_record_path, record)
    _emit({
        "outcome": "finalized_pending_verification",
        "drift_detected": provenance["drift_detected"],
        "effective_report": record["effective_report"],
    })
    return 0


def _refuse_verify(detail: str, missing: bool = False) -> int:
    if missing:
        message = f"CLOSE: NO -- retrospective disclosure missing on an expected artifact: {detail}"
    else:
        message = f"CLOSE: NO -- retrospective disclosure present but not independently corroborated: {detail}"
    _emit({"outcome": "refused", "reason": message})
    return 3


def cmd_verify_disclosure(ns: argparse.Namespace) -> int:
    root = Path(ns.project_dir).resolve()
    record = _load_active_record(root, ns.task_id)
    if record is None:
        return _refuse_verify("no matching run record")
    expected_run_id = record["repair_run_id"]

    targets: list[tuple[str, Path, str | None]] = []
    for stage in STAGE_ORDER:
        info = record.get("stages", {}).get(stage)
        if info:
            targets.append((stage, root / info["report_path"], info.get("sha256")))
    if record.get("effective_report"):
        targets.append((
            "effective_report",
            root / record["effective_report"],
            record.get("effective_report_disclosure_sha256"),
        ))

    if not targets:
        return _refuse_verify("run record has no recorded artifacts to corroborate")

    for label, path, expected_sha in targets:
        if not path.is_file():
            return _refuse_verify(label, missing=True)
        disclosure = _read_disclosure(path)
        if disclosure is None:
            return _refuse_verify(label, missing=True)
        missing_fields = [field for field in DISCLOSURE_FIELDS if not disclosure.get(field)]
        if missing_fields:
            return _refuse_verify(f"missing field(s) {missing_fields} on {label}")
        if disclosure.get("route") != ROUTE:
            return _refuse_verify(f"route mismatch on {label}: {disclosure.get('route')!r}")
        if disclosure.get("repair_run_id") != expected_run_id:
            return _refuse_verify(f"no matching run record for disclosed repair_run_id on {label}")
        if disclosure.get("artifact") != path.name:
            return _refuse_verify(f"artifact identity mismatch on {label}")
        actual_sha = _sha256_file(path)
        if expected_sha is not None and actual_sha != expected_sha:
            return _refuse_verify(f"hash mismatch on {label}")

    _emit({"outcome": "admitted", "repair_run_id": expected_run_id})
    return 0


def resolve_effective_report_state(project_dir: Path, task_id: str) -> tuple[str, Path | None]:
    """Tri-state guard shared by /commit's dev-report resolution points.

    Returns ("none", None) when no late-repair state exists for task_id at
    all (State A -- byte-identical to pre-R4 behavior).  Returns
    ("verified", effective_path) only when verify-disclosure independently
    corroborates the active run record (State B).  Returns ("invalid", None)
    when a run record/effective report exists but corroboration fails or is
    absent (State C -- callers MUST fail closed here, never fall back to
    stale canonical provenance).
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
    if rc != 0:
        return "invalid", None
    try:
        payload = json.loads(buffer.getvalue().strip().splitlines()[-1])
    except (ValueError, IndexError):
        return "invalid", None
    if payload.get("outcome") != "admitted":
        return "invalid", None
    record = _load_active_record(root, task_id)
    effective_rel = record.get("effective_report") if record else None
    if not effective_rel:
        return "invalid", None
    effective_path = root / effective_rel
    if not effective_path.is_file():
        return "invalid", None
    return "verified", effective_path


def cmd_resolve_effective_report(ns: argparse.Namespace) -> int:
    """Thin CLI wrapper around resolve_effective_report_state.

    Lets callers (e.g. commands/commit.md) invoke a stable, testable
    subcommand instead of dynamically loading this module inline, mirroring
    how scripts/dev-lifecycle.py exposes list-actionable.
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
    p_stage.add_argument("--stage", required=True, choices=STAGE_ORDER)
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
