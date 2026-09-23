#!/usr/bin/env python3
"""Resolve a closed task's owned paths into an admitted repository plan.

The normal ``/commit`` workflow uses this helper before it writes any commit
grant.  A dev/do report is the ownership authority, but it is not repository
admission authority: every resolved owner must also be one of the explicitly
supported repositories supplied by the command orchestrator.

The emitted JSON binds each admitted repository to its current branch and HEAD
so the changelog analyst can apply the same CAS boundary before staging and
again before committing.  This helper never changes a repository or its index.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from sibling_loader import load_sibling_module  # noqa: E402


SCHEMA_VERSION = 1


class PlanError(RuntimeError):
    """A fail-closed repository-plan admission error."""


def _load_late_repair_controller() -> ModuleType:
    """Load late-repair-controller.py (R4 tri-state guard).

    Delegates to the single canonical implementation in
    scripts/lib/sibling_loader.py.
    """
    return load_sibling_module("late-repair-controller.py", __file__)


def _git_capture(repo_or_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_or_path), *args],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git command failed").strip()
        raise PlanError(f"git -C {repo_or_path} {' '.join(args)}: {detail}")
    return result.stdout.strip()


def _repo_root(path: Path) -> Path:
    anchor = path if path.is_dir() else path.parent
    return Path(_git_capture(anchor, "rev-parse", "--show-toplevel")).resolve()


def _existing_ancestor(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise PlanError(f"owned path has no existing ancestor: {path}")
        candidate = parent
    return candidate


def _canonical_owned_path(raw: str, control_root: Path) -> Path:
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        raise PlanError("owned paths must be non-empty NUL-free strings")
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        candidate = control_root / candidate

    # resolve(strict=False) normalizes '..' and resolves every existing symlink
    # prefix while still supporting a not-yet-created files_created entry.
    resolved = candidate.resolve(strict=False)
    _existing_ancestor(resolved)
    return resolved


def _canonicalized_ledger_identities(owned_edits: Any, control_root: Path) -> set[tuple[Path, str]]:
    """Canonicalize an owned_edits ledger's keys to (owner, relative) identities.

    Applies the identical _canonical_owned_path / _repo_root / .relative_to()
    pipeline already used for files_modified/files_created so both sides of
    the ownership-gate comparison share one canonicalization path (no second
    convention is invented). A key that cannot be canonicalized (malformed,
    non-string, NUL, or no existing ancestor) is dropped rather than raised --
    it fails closed by covering nothing, never masking a real gap.
    """
    identities: set[tuple[Path, str]] = set()
    if not isinstance(owned_edits, dict):
        return identities
    for key in owned_edits:
        if not isinstance(key, str):
            continue
        try:
            absolute = _canonical_owned_path(key, control_root)
            owner = _repo_root(_existing_ancestor(absolute))
            relative = absolute.relative_to(owner).as_posix()
        except (PlanError, ValueError, OSError):
            continue
        identities.add((owner, relative))
    return identities


_PORCELAIN_C_ESCAPES = {
    "\\": "\\",
    '"': '"',
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
}


def _unquote_porcelain_path(token: str) -> str:
    """Undo git's C-style double-quoting for one porcelain path token.

    Empirically confirmed this session (real ``git status --porcelain``
    subprocess fixture, git 2.54.0 -- not taken from documentation alone,
    per this ticket's tier_3_unverified flag on this exact behavior): git
    wraps a path in ``"..."`` and backslash/octal-escapes it whenever the
    raw bytes would otherwise be ambiguous for a machine parser splitting on
    the fixed ``"XY "`` single-space prefix -- a plain space in the path is
    already sufficient to trigger quoting. A token that is not quoted is
    returned unchanged.
    """
    if len(token) < 2 or token[0] != '"' or token[-1] != '"':
        return token
    body = token[1:-1]
    raw = bytearray()
    i, n = 0, len(body)
    while i < n:
        ch = body[i]
        if ch != "\\" or i + 1 >= n:
            raw.extend(ch.encode("utf-8", "surrogateescape"))
            i += 1
            continue
        octal = body[i + 1 : i + 4]
        if len(octal) == 3 and all(digit in "01234567" for digit in octal):
            raw.append(int(octal, 8))
            i += 4
            continue
        nxt = body[i + 1]
        raw.extend(_PORCELAIN_C_ESCAPES.get(nxt, nxt).encode("utf-8", "surrogateescape"))
        i += 2
    return raw.decode("utf-8", "surrogateescape")


def _split_porcelain_rename(rest: str) -> tuple[str, str] | None:
    """Split a rename/copy porcelain data field into (old, new) tokens.

    Only called for 'R'/'C' status lines, where the ' -> ' arrow is git's
    own emitted syntax (never ambiguous with an unrelated entry that happens
    to contain the literal substring). The old-side token may itself be
    independently quoted (git quotes each path based on whether THAT path
    needs it), so this walks past a leading quoted token instead of blindly
    splitting on the first ' -> ' substring.
    """
    if rest.startswith('"'):
        end, n = 1, len(rest)
        while end < n and rest[end] != '"':
            end += 2 if rest[end] == "\\" else 1
        if end >= n:
            return None
        remainder = rest[end + 1 :]
        if not remainder.startswith(" -> "):
            return None
        return rest[: end + 1], remainder[4:]
    if " -> " in rest:
        old, new = rest.split(" -> ", 1)
        return old, new
    return None


def _parse_porcelain_snapshot_paths(snapshot: str) -> list[str]:
    """Split ``git status --porcelain`` text into raw (unquoted) path strings.

    Mirrors the line-splitting shape of scripts/resolve-dev-report.py's
    parse_changed_paths() (``"XY path"`` / ``"XY orig -> dest"``) but keeps
    BOTH rename endpoints (AC-5: files_modified's git-diff-name-only capture
    may reference either endpoint depending on rename-detection settings at
    capture time, so under-covering either would reproduce this ticket's
    false-positive-rejection bug for the rename case specifically) and
    unquotes each token (AC-6) instead of leaving quote/escape artifacts.
    """
    paths: list[str] = []
    for line in snapshot.splitlines():
        if len(line) < 3 or line[2] != " ":
            continue
        status, rest = line[:2], line[3:]
        if status[0] in ("R", "C"):
            split = _split_porcelain_rename(rest)
            if split is not None:
                old, new = split
                paths.append(_unquote_porcelain_path(old))
                paths.append(_unquote_porcelain_path(new))
                continue
        paths.append(_unquote_porcelain_path(rest))
    return paths


def _canonicalized_baseline_dirty_identities(
    baseline_dirty_snapshot: Any, control_root: Path
) -> set[tuple[Path, str]]:
    """Canonicalize baseline_dirty_snapshot's porcelain paths to (owner, relative) identities.

    ``baseline_dirty_snapshot`` is the ``git status --porcelain`` text
    captured before dev dispatch (agents/dev.md:807, agents/dev.md:533): a
    files_modified-derived identity that is a pre-existing dirty tracked
    file from another session -- not this cycle's own edit, and therefore
    absent from owned_edits -- is exempt from the ownership gate exactly as
    an owned_edits match would be (agents/dev.md:521/533: presence in
    baseline_dirty_snapshot is "a reason to keep it in files_modified, never
    a reason to drop it"). Parses through the SAME
    _canonical_owned_path / _repo_root / .relative_to() pipeline already
    used by _canonicalized_ledger_identities so both exemption sources share
    one canonicalization convention -- no second scheme is invented. Fails
    closed per-entry: an unparseable path is dropped, never masking a real
    gap. A missing, non-string, or empty snapshot yields an empty set,
    degrading to the pre-fix strict behavior (AC-3): the subtraction then
    exempts nothing.
    """
    identities: set[tuple[Path, str]] = set()
    if not isinstance(baseline_dirty_snapshot, str) or not baseline_dirty_snapshot:
        return identities
    for raw in _parse_porcelain_snapshot_paths(baseline_dirty_snapshot):
        try:
            absolute = _canonical_owned_path(raw, control_root)
            owner = _repo_root(_existing_ancestor(absolute))
            relative = absolute.relative_to(owner).as_posix()
        except (PlanError, ValueError, OSError):
            continue
        identities.add((owner, relative))
    return identities


def _contains(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _load_report(path: Path, task_id: str, control_root: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanError(f"cannot read report {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PlanError(f"report is not a JSON object: {path}")
    identities = [
        payload.get(field)
        for field in ("task_id", "request_id")
        if payload.get(field) is not None
    ]
    if not identities or any(identity != task_id for identity in identities):
        raise PlanError(f"report task id does not match {task_id}: {path}")

    if path.name == f"dev-report-{task_id}.json":
        section_name = "dev"
    elif path.name == f"do-report-{task_id}.json" and payload.get("source") == "do":
        section_name = "do"
    elif path.name == f"dev-report-{task_id}.effective.json":
        # R4 tri-state guard (Architect (f) v2, QA round-2 objection 3): a
        # provenance-refresh artifact is accepted ONLY when this function
        # independently re-derives corroboration itself -- never trusted
        # from the caller's filename alone. State A (no run record at all)
        # never reaches this branch. State C (present but uncorroborated,
        # e.g. drift/corruption discovered after finalize) MUST fail closed
        # here, never silently fall back to the canonical dev-report.
        controller = _load_late_repair_controller()
        state, resolved_path = controller.resolve_effective_report_state(control_root, task_id)
        if state != "verified" or resolved_path is None or resolved_path.resolve() != path.resolve():
            raise PlanError(
                f"effective report present but not independently corroborated: {path}"
            )
        section_name = "dev"
    else:
        raise PlanError(f"report is neither a canonical dev report nor a source=do report: {path}")
    section = payload.get(section_name)
    if not isinstance(section, dict):
        raise PlanError(f"report is missing object field {section_name}: {path}")
    return payload, section_name


def _resolve_report(control_root: Path, task_id: str, explicit: str | None) -> Path:
    if explicit:
        report = Path(explicit).expanduser().resolve()
        if not report.is_file():
            raise PlanError(f"explicit report does not exist: {report}")
        return report
    docs = control_root / "docs" / "dev"
    # R4 tri-state guard: prefer a corroborated effective report ONLY when
    # verify-disclosure independently admits it for this task-id (State B).
    # No run record at all (State A) or an uncorroborated one (State C) both
    # fall through to the unchanged canonical/do-report glob below.
    controller = _load_late_repair_controller()
    state, effective_path = controller.resolve_effective_report_state(control_root, task_id)
    if state == "verified" and effective_path is not None and effective_path.is_file():
        return effective_path.resolve()
    for name in (f"dev-report-{task_id}.json", f"do-report-{task_id}.json"):
        candidate = docs / name
        if candidate.is_file():
            return candidate.resolve()
    raise PlanError(f"no dev/do report found for task {task_id} under {docs}")


def build_plan(
    *,
    task_id: str,
    control_root_arg: str,
    supported_repo_args: list[str],
    report_arg: str | None = None,
    verify_ownership: bool = True,
) -> dict[str, Any]:
    """Resolve a task's owned paths into an admitted repository plan.

    ``verify_ownership`` (default True) gates a fail-closed cross-check, for
    ``section_name == "dev"`` reports only: every canonical identity declared
    via ``files_modified`` must also be EITHER a canonicalized key of the
    report's ``owned_edits`` ledger OR a canonicalized path parsed from the
    report's ``baseline_dirty_snapshot`` (a pre-existing dirty tracked file
    from another session, exempt per agents/dev.md:521/533) -- both read
    from the TOP-LEVEL report payload (``payload["owned_edits"]`` /
    ``payload["baseline_dirty_snapshot"]``), never from ``section[...]``,
    which is never populated (see agents/dev.md, agents/changelog-analyst.md).
    ``files_created``-only paths are exempt; a path dual-listed in both
    ``files_modified`` and ``files_created`` is not. Pass ``verify_ownership=
    False`` only for read-only historical-status reuse (scripts/dev-
    lifecycle.py's commit_detection()) that predates the ledger and must not
    misreport already-landed tasks as blocked.
    """
    if not task_id.strip():
        raise PlanError("task id must be non-empty")
    control_root = _repo_root(Path(control_root_arg).expanduser().resolve())
    report_path = _resolve_report(control_root, task_id, report_arg)
    if not _contains(control_root, report_path):
        raise PlanError(f"report must resolve under the control repository: {report_path}")
    payload, section_name = _load_report(report_path, task_id, control_root)
    section = payload[section_name]

    supported: list[Path] = []
    for raw in [str(control_root), *supported_repo_args]:
        repo = _repo_root(Path(raw).expanduser().resolve())
        if repo not in supported:
            supported.append(repo)

    owned_raw: list[str] = []
    raw_fields: dict[str, set[str]] = {}
    for field in ("files_modified", "files_created"):
        values = section.get(field, [])
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise PlanError(f"{section_name}.{field} must be an array of strings")
        owned_raw.extend(values)
        for raw in values:
            raw_fields.setdefault(raw, set()).add(field)

    by_repo: dict[Path, list[str]] = {control_root: []}
    identity_fields: dict[tuple[Path, str], set[str]] = {}
    identity_display: dict[tuple[Path, str], str] = {}
    for raw in owned_raw:
        absolute = _canonical_owned_path(raw, control_root)
        actual_owner = _repo_root(_existing_ancestor(absolute))
        if actual_owner not in supported:
            raise PlanError(f"owned path is outside the supported repository set: {raw}")
        # Git, not pathname containment alone, determines ownership. This rejects
        # an unadmitted nested checkout instead of laundering it through an
        # admitted outer repository.
        owner = actual_owner
        relative = absolute.relative_to(owner).as_posix()
        if relative == "." or relative.startswith("../"):
            raise PlanError(f"owned path cannot name a repository root: {raw}")
        by_repo.setdefault(owner, [])
        if relative not in by_repo[owner]:
            by_repo[owner].append(relative)
        identity = (owner, relative)
        identity_fields.setdefault(identity, set()).update(raw_fields.get(raw, set()))
        identity_display.setdefault(identity, raw)

    # Ownership gate (backlog #110, extended -- task 20260923-024043):
    # files_modified is never blindly trusted -- it must be backed by this
    # cycle's own owned_edits ledger OR by baseline_dirty_snapshot (a
    # pre-existing dirty tracked file from another session in a shared
    # worktree, per agents/dev.md:521/533), or the plan would silently admit
    # a foreign seat's uncommitted work. files_created-only identities are
    # exempt (a brand-new file's ledger entry is legitimately absent -- see
    # agents/dev.md/schemas/owned-edits-ledger.v1.json's minLength:1 on
    # `old`); a dual-listed identity is not. Missing/empty owned_edits AND
    # missing/empty baseline_dirty_snapshot both fall out of the same
    # set-difference with no special branch: an absent/empty input
    # canonicalizes to an empty identity-set, so a files_modified path
    # backed by neither always yields a reject (agents/dev.md requires the
    # ledger be non-empty whenever edits were made, and requires
    # baseline_dirty_snapshot itself be a mandatory top-level field).
    if verify_ownership and section_name == "dev":
        ledger_identities = _canonicalized_ledger_identities(payload.get("owned_edits"), control_root)
        baseline_identities = _canonicalized_baseline_dirty_identities(
            payload.get("baseline_dirty_snapshot"), control_root
        )
        missing = sorted(
            identity_display[identity]
            for identity, fields in identity_fields.items()
            if "files_modified" in fields
            and identity not in ledger_identities
            and identity not in baseline_identities
        )
        if missing:
            raise PlanError(
                "files_modified declares path(s) with no matching owned_edits "
                "ledger entry and absent from baseline_dirty_snapshot (foreign "
                f"or unaccounted-for edit): {', '.join(missing)}"
            )

    targets: list[dict[str, Any]] = []
    ordered_roots = [control_root] + sorted(
        (root for root in by_repo if root != control_root), key=lambda item: str(item)
    )
    for order, root in enumerate(ordered_roots):
        branch = _git_capture(root, "branch", "--show-current")
        head = _git_capture(root, "rev-parse", "HEAD")
        if not branch or not head:
            raise PlanError(f"repository must have an attached branch and HEAD: {root}")
        targets.append(
            {
                "order": order,
                "repo_root": str(root),
                "branch": branch,
                "expected_head": head,
                "owned_paths": sorted(by_repo.get(root, [])),
                "cycle_artifact_repo": root == control_root,
            }
        )

    report_bytes = report_path.read_bytes()
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "report_path": str(report_path),
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "control_root": str(control_root),
        "repository_count": len(targets),
        "repositories": targets,
        "transaction_semantics": "ordered_non_atomic_with_partial_failure_reporting",
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--control-root", required=True)
    parser.add_argument("--supported-repo", action="append", default=[])
    parser.add_argument("--report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        plan = build_plan(
            task_id=args.task_id,
            control_root_arg=args.control_root,
            supported_repo_args=args.supported_repo,
            report_arg=args.report,
        )
    except PlanError as exc:
        print(f"resolve-commit-repos: BLOCKED: {exc}", file=sys.stderr)
        return 2
    json.dump(plan, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
