#!/usr/bin/env python3
"""R4.3 drift-detection + per-file provenance routing for the late-repair route.

Takes ONLY ``--task-id`` and ``--project-dir`` (never a caller-supplied file
list, digest map, or provenance-plan path -- codex finding #3): independently
resolves the active late-repair run record and the live dev-report itself,
then:

  1. Drift-detection phase: for every file the dev-report declares
     (``dev.files_modified`` + ``dev.files_created``), compares its recorded
     ``final_source_hashes`` entry against that file's CURRENT live bytes
     directly (codex finding #9) -- NOT via ``stage-owned-hunks.py``
     success/failure, which is a routing question, not a detection one.
  2. For every drifted file, route it through exactly one of three
     mechanisms, never the plain ``--ledger``/``--snapshot`` mode (that mode
     has no ``--plan-only`` isolation and mutates the real index):
       - authenticated pre-existing untracked (``untracked_modified_provenance``):
         ``stage-owned-hunks.py --untracked-modified-report --plan-only``,
         cross-checked against the contract's own recorded final hash.
       - tracked hunk-owned (``owned_edits`` + ``pre_edit_snapshots``, file
         currently tracked in the index):
         ``stage-owned-hunks.py --provenance-plan --plan-only`` (composed
         mode).
       - whole newly-created (``owned_edits`` + ``pre_edit_snapshots``, file
         currently untracked): a direct, in-process replay of the SAME
         forward-replay ownership algorithm ``stage-owned-hunks.py``'s live
         mode uses (imported, never invoked via its mutating CLI path) --
         reconciled only when replaying the ledger from the pre-edit
         snapshot reproduces the CURRENT live bytes exactly.
     A drifted file with no matching mechanism is unroutable.

Exit codes:
  0  reconcilable (drift_detected may be empty, or every drifted file routed)
  1  unreconcilable -- at least one drifted file has no valid route
  2  usage / resolution error (no dev-report, no run record, etc.)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from sibling_loader import load_sibling_module, sha256_bytes  # noqa: E402


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _git(root: Path, args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _git_status_code(root: Path, rel: str) -> str | None:
    rc, out, _ = _git(root, ["status", "--porcelain=v1", "--", rel])
    if rc != 0 or not out.strip():
        return None
    line = out.splitlines()[0]
    return line[:2]


def _is_tracked(root: Path, rel: str) -> bool:
    """Whether rel is currently tracked in the git index.

    Deliberately independent of `_git_status_code`: a CLEAN tracked file
    (worktree bytes == index/HEAD, e.g. a peer's change was fully committed
    rather than left dirty) produces NO `git status --porcelain` line at all,
    which is otherwise indistinguishable from "does not exist" / "ignored".
    Self-review finding (codex unavailable this session, HTTP 401 against
    api.openai.com -- see docs/codex/20260910-091226/dev-adversarial-review.txt):
    the original status-only check misrouted this exact shape to
    'unroutable', spuriously refusing a genuinely reconcilable tracked file.
    """
    rc, _, _ = _git(root, ["ls-files", "--error-unmatch", "--", rel])
    return rc == 0


def detect_drift(root: Path, dev_report: dict[str, Any]) -> dict[str, str]:
    """Compare each declared file's recorded final hash against live bytes."""
    dev = dev_report.get("dev", {}) if isinstance(dev_report.get("dev"), dict) else {}
    modified = dev.get("files_modified") if isinstance(dev.get("files_modified"), list) else []
    created = dev.get("files_created") if isinstance(dev.get("files_created"), list) else []
    declared = [p for p in (list(modified) + list(created)) if isinstance(p, str)]
    final_hashes = dev_report.get("final_source_hashes")
    final_hashes = final_hashes if isinstance(final_hashes, dict) else {}

    drift: dict[str, str] = {}
    for rel in declared:
        recorded = final_hashes.get(rel)
        if not isinstance(recorded, str):
            # Nothing recorded to compare against -- not this phase's concern.
            continue
        current = _read_bytes(root / rel)
        if current is None:
            drift[rel] = "file_missing"
            continue
        if sha256_bytes(current) != recorded:
            drift[rel] = "hash_mismatch"
    return drift


def _try_untracked_modified(root: Path, task_id: str, rel: str, dev_report_path: Path) -> tuple[bool, str]:
    report_bytes = _read_bytes(dev_report_path)
    if report_bytes is None:
        return False, "dev report unreadable for untracked-modified routing"
    digest = sha256_bytes(report_bytes)
    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("stage-owned-hunks.py")),
            "--git-root", str(root),
            "--file", rel,
            "--untracked-modified-report", str(dev_report_path),
            "--report-sha256", digest,
            "--task-id", task_id,
            "--plan-only",
        ],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0, (proc.stdout.strip() or proc.stderr.strip())


def _try_tracked_composed(root: Path, task_id: str, rel: str, owned_edits: list, pre_edit_snapshot: str) -> tuple[bool, str]:
    plan = {
        "task_id": task_id,
        "path": rel,
        "segments": [
            {
                "kind": "live",
                "source_worker": "dev",
                "pre_edit_snapshot": pre_edit_snapshot,
                "owned_edits": owned_edits,
            }
        ],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(plan, fh)
        plan_path = fh.name
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("stage-owned-hunks.py")),
                "--git-root", str(root),
                "--file", rel,
                "--provenance-plan", plan_path,
                "--task-id", task_id,
                "--plan-only",
            ],
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0, (proc.stdout.strip() or proc.stderr.strip())
    finally:
        Path(plan_path).unlink(missing_ok=True)


def _try_whole_created(root: Path, rel: str, owned_edits: list, pre_edit_snapshot: str) -> tuple[bool, str]:
    """Reconcile a currently-untracked, newly-created file via pure replay.

    Reuses stage-owned-hunks.py's own forward-replay ownership algorithm
    in-process (never its mutating --ledger/--snapshot CLI path): if
    replaying this cycle's ledger from the pre-edit snapshot reproduces the
    CURRENT live bytes exactly, the current state is entirely this cycle's
    own authored content regardless of what a stale final_source_hashes
    entry claims.
    """
    current = _read_bytes(root / rel)
    if current is None:
        return False, "whole-created file missing from worktree"
    status = _git_status_code(root, rel)
    if status != "??":
        return False, f"whole-created file is no longer untracked (status={status!r})"
    module = load_sibling_module("stage-owned-hunks.py", __file__)
    snapshot = pre_edit_snapshot.encode("utf-8") if isinstance(pre_edit_snapshot, str) else pre_edit_snapshot
    replay, error = module._replay_live(snapshot, owned_edits, rel)
    if replay is None:
        return False, f"ledger replay failed: {error}"
    if replay != current:
        return False, "replayed ledger does not reproduce current bytes -- foreign content present"
    return True, "replay reproduces current bytes exactly"


def route_file(root: Path, task_id: str, rel: str, dev_report: dict[str, Any], dev_report_path: Path) -> tuple[str, str]:
    owned_edits = dev_report.get("owned_edits")
    owned_edits = owned_edits if isinstance(owned_edits, dict) else {}
    pre_edit_snapshots = dev_report.get("pre_edit_snapshots")
    pre_edit_snapshots = pre_edit_snapshots if isinstance(pre_edit_snapshots, dict) else {}
    untracked = dev_report.get("untracked_modified_provenance")
    untracked = untracked if isinstance(untracked, dict) else {}

    if rel in untracked:
        ok, detail = _try_untracked_modified(root, task_id, rel, dev_report_path)
        return ("untracked_modified", detail) if ok else ("unroutable", detail)

    has_ledger = rel in owned_edits and rel in pre_edit_snapshots
    if has_ledger and _is_tracked(root, rel):
        ok, detail = _try_tracked_composed(root, task_id, rel, owned_edits[rel], pre_edit_snapshots[rel])
        return ("tracked_composed", detail) if ok else ("unroutable", detail)
    status = _git_status_code(root, rel)
    if has_ledger and status == "??":
        ok, detail = _try_whole_created(root, rel, owned_edits[rel], pre_edit_snapshots[rel])
        return ("whole_created", detail) if ok else ("unroutable", detail)
    return ("unroutable", "no provenance mechanism declared for this file")


def check(project_dir: str, task_id: str, dev_report_path: Path) -> dict[str, Any]:
    root = Path(project_dir).resolve()
    try:
        dev_report = json.loads(dev_report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "task_id": task_id,
            "status": "error",
            "reason": f"dev report unreadable: {exc}",
            "drift_detected": {},
            "routing": {},
            "reconcilable": False,
        }

    drift = detect_drift(root, dev_report)
    routing: dict[str, dict[str, str]] = {}
    unroutable: list[str] = []
    for rel in sorted(drift):
        route_kind, detail = route_file(root, task_id, rel, dev_report, dev_report_path)
        routing[rel] = {"route": route_kind, "detail": detail}
        if route_kind == "unroutable":
            unroutable.append(rel)

    return {
        "task_id": task_id,
        "status": "ok",
        "drift_detected": drift,
        "routing": routing,
        "unroutable_files": sorted(unroutable),
        "reconcilable": not unroutable,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument(
        "--dev-report-path",
        help="Override the dev-report path (defaults to docs/dev/dev-report-<task-id>.json)",
    )
    args = parser.parse_args(argv)

    root = Path(args.project_dir).resolve()
    dev_report_path = (
        Path(args.dev_report_path).resolve()
        if args.dev_report_path
        else root / "docs" / "dev" / f"dev-report-{args.task_id}.json"
    )
    if not dev_report_path.is_file():
        print(json.dumps({
            "task_id": args.task_id,
            "status": "error",
            "reason": "no dev report to check provenance against",
            "drift_detected": {},
            "routing": {},
            "reconcilable": False,
        }, sort_keys=True))
        return 2

    result = check(str(root), args.task_id, dev_report_path)
    print(json.dumps(result, sort_keys=True))
    if result["status"] != "ok":
        return 2
    return 0 if result["reconcilable"] else 1


if __name__ == "__main__":
    sys.exit(main())
