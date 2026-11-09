#!/usr/bin/env python3
"""Read-only resolver for singular and fan-out /dev artifact chains.

The resolver never creates, refreshes, or rewrites artifacts.  It validates the
chain rooted at ``docs/dev/dev-report-<task-id>.json`` and emits one stable JSON
document suitable for /dev completion, /close, Close QA, and /commit.

Exit codes:
    0  the complete artifact chain is valid (status == "pass")
    2  invalid arguments, or a missing/stale/mismatched/ambiguous chain

``--disposition --stage dev|close|commit`` prints the task's disposition at
that stage instead (``disposition()``): exit 0 whenever it was computed, 1 on
an instrument failure (the reason on stderr, no DISPOSITION line).
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


SCHEMA_VERSION = 2
IDENTITY_RE = re.compile(
    r"^(?:[-*+]\s*)?(?:task[- ]id|request[- ]id)\s*:\s*(\S+)\s*$",
    re.IGNORECASE,
)
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
WORKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")

# A check that has no analogue on the code path taken.  Distinct from both
# booleans: `False` would claim the check ran and failed, `True` would claim it
# ran and passed.  Consumers must treat this as "unevaluated here", never as a
# pass.
NOT_APPLICABLE = "not_applicable"
SINGULAR_RELATIONAL_REASON = (
    "relational comparison requiring two or more independent shard artifacts; "
    "a singular chain has no second artifact to compare against, so this check "
    "has no singular analogue"
)

# R4 (spec-20260907-115508-lawful-commit-channel.md) gap classification.  A
# stage gap means an entire BA/Dev-stage artifact is absent or empty; every
# other non-qa-report error is a "non-gap" integrity problem that must NOT be
# treated as late-repair eligible even when a real stage gap is also present
# (codex finding #7 / QA round-2 objection 7).
STAGE_GAP_CODES = frozenset({"MISSING_ARTIFACT", "EMPTY_ARTIFACT"})


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _exec_script(name: str, module_name: str) -> ModuleType:
    """A sibling script exec'd into a bare module (never imported, so loading
    one another never cycles)."""
    path = Path(__file__).with_name(name)
    module = ModuleType(module_name)
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


def _load_aggregate_module() -> ModuleType:
    return _exec_script("aggregate-dev-report.py", "_dev_aggregate")


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


class ChainValidator:
    def __init__(self, project_root: Path, task_id: str) -> None:
        self.root = project_root
        self.dev_dir = project_root / "docs" / "dev"
        self.task_id = task_id
        self.errors: list[dict[str, str]] = []

    def error(self, code: str, path: str, detail: str) -> None:
        self.errors.append({"code": code, "path": path, "detail": detail})

    def read_json(self, path: Path, *, required: bool = True) -> dict[str, Any] | None:
        relative = _rel(path, self.root)
        if not path.is_file():
            if required:
                self.error("MISSING_ARTIFACT", relative, "required JSON artifact is absent")
            return None
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.error("UNREADABLE_ARTIFACT", relative, str(exc))
            return None
        if not raw.strip():
            self.error("EMPTY_ARTIFACT", relative, "JSON artifact is empty")
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.error(
                "MALFORMED_JSON",
                relative,
                f"line {exc.lineno}, column {exc.colno}: {exc.msg}",
            )
            return None
        if not isinstance(value, dict):
            self.error("INVALID_JSON_TYPE", relative, "top-level value must be an object")
            return None
        return value

    def read_text(self, path: Path, *, required: bool = True) -> str | None:
        relative = _rel(path, self.root)
        if not path.is_file():
            if required:
                self.error("MISSING_ARTIFACT", relative, "required Markdown artifact is absent")
            return None
        try:
            value = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.error("UNREADABLE_ARTIFACT", relative, str(exc))
            return None
        if not value.strip():
            self.error("EMPTY_ARTIFACT", relative, "Markdown artifact is empty")
            return None
        return value

    def validate_json_identity(
        self, value: dict[str, Any], expected: str, path: Path
    ) -> None:
        relative = _rel(path, self.root)
        for key in ("request_id", "task_id"):
            actual = value.get(key)
            if actual != expected:
                self.error(
                    "IDENTITY_MISMATCH",
                    relative,
                    f"{key} is {actual!r}; expected {expected!r}",
                )

    def validate_markdown_identity(self, text: str, expected: str, path: Path) -> None:
        values: list[str] = []
        for line in text.splitlines():
            cleaned = line.strip().replace("**", "").replace("`", "")
            match = IDENTITY_RE.fullmatch(cleaned)
            if match:
                values.append(match.group(1))
        relative = _rel(path, self.root)
        if not values:
            self.error(
                "MISSING_IDENTITY",
                relative,
                "no TASK-ID, Task ID, or Request ID metadata was found",
            )
            return
        for actual in values:
            if actual != expected:
                self.error(
                    "IDENTITY_MISMATCH",
                    relative,
                    f"metadata identity is {actual!r}; expected {expected!r}",
                )

    def validate_dev(self, value: dict[str, Any], expected: str, path: Path) -> None:
        self.validate_json_identity(value, expected, path)
        relative = _rel(path, self.root)
        dev = value.get("dev")
        if not isinstance(dev, dict):
            self.error("INVALID_DEV_STATUS", relative, "dev must be an object")
            return
        if dev.get("status") != "completed":
            self.error(
                "INVALID_DEV_STATUS",
                relative,
                f"dev.status is {dev.get('status')!r}; expected 'completed'",
            )
        for key in ("files_modified", "files_created"):
            paths = dev.get(key)
            if not isinstance(paths, list) or any(
                not isinstance(item, str) or not item or "\x00" in item for item in paths
            ):
                self.error(
                    "INVALID_FILE_LIST",
                    relative,
                    f"dev.{key} must be an array of non-empty path strings",
                )
        blockers = value.get("blocking_issues", [])
        if not isinstance(blockers, list):
            self.error(
                "INVALID_BLOCKING_ISSUES",
                relative,
                "blocking_issues must be an array when present",
            )
        elif blockers:
            self.error(
                "UNRESOLVED_BLOCKERS",
                relative,
                "blocking_issues is not empty",
            )

    def validate_qa(self, value: dict[str, Any], expected: str, path: Path) -> None:
        self.validate_json_identity(value, expected, path)
        relative = _rel(path, self.root)
        qa = value.get("qa")
        # Binary by design (`commands/dev.md`:1354, :1361). A 20260806 relaxation
        # widened this to accept `warning`; /close QA judged it improper and it
        # was reverted -- see the close report for task 20260806-115859.
        if not isinstance(qa, dict) or qa.get("status") != "pass":
            actual = qa.get("status") if isinstance(qa, dict) else None
            self.error(
                "INVALID_QA_STATUS",
                relative,
                f"qa.status is {actual!r}; expected 'pass'",
            )

    def validate_completion(
        self, text: str, expected: str, path: Path, references: list[str]
    ) -> None:
        self.validate_markdown_identity(text, expected, path)
        relative = _rel(path, self.root)
        for reference in references:
            reference_pattern = re.compile(
                rf"(?<![A-Za-z0-9._/-]){re.escape(reference)}(?![A-Za-z0-9._/-])"
            )
            if reference_pattern.search(text) is None:
                self.error(
                    "MISSING_COMPLETION_REFERENCE",
                    relative,
                    f"completion does not reference {reference}",
                )


def _compute_gap_fields(
    errors: list[dict[str, str]],
    qa_report_path: str,
) -> tuple[list[str], list[str], bool, str]:
    """Classify a singular chain's errors into stage gaps vs. integrity errors.

    THE SOLE PLACE stage_gaps/non_gap_errors/late_repair_eligible/
    gap_classification are computed (R4/AC-6).  Every consumer -- the
    late-repair controller, /close's own gate -- MUST read these fields from
    this resolver's output rather than recomputing them; there is exactly one
    source of truth.

    stage_gaps: the distinct non-qa-report paths whose only problem is that an
    entire BA/Dev/completion-stage artifact is absent or empty
    (MISSING_ARTIFACT / EMPTY_ARTIFACT).  non_gap_errors: every other
    non-qa-report error path -- a genuine integrity problem (malformed JSON,
    identity mismatch, invalid dev status, etc).  late_repair_eligible is true
    only when there is at least one stage gap AND zero non-gap errors: a chain
    with both a real gap and an unrelated integrity error is NOT late-repair
    eligible, even though the coarser gap_classification still reports
    'beyond_qa' for it (codex finding #7 / QA round-2 objection 7).
    """
    stage_gaps: set[str] = set()
    non_gap_errors: set[str] = set()
    qa_has_error = False
    for entry in errors:
        path = entry.get("path", "")
        if path == qa_report_path:
            qa_has_error = True
            continue
        if entry.get("code") in STAGE_GAP_CODES:
            stage_gaps.add(path)
        else:
            non_gap_errors.add(path)
    late_repair_eligible = bool(stage_gaps) and not non_gap_errors
    if stage_gaps or non_gap_errors:
        gap_classification = "beyond_qa"
    elif qa_has_error:
        gap_classification = "qa_only"
    else:
        gap_classification = "complete"
    return sorted(stage_gaps), sorted(non_gap_errors), late_repair_eligible, gap_classification


def _dev_report_has_sibling_shards(dev_dir: Path, task_id: str) -> bool:
    """Whether any dev-report-<task_id>-<label>.json sibling exists.

    Consulted only when the canonical dev-report itself cannot be read at
    all.  A genuinely singular chain missing its dev-report has no such
    sibling; any sibling means the shape may actually be a fan-out canonical
    that also happens to be missing/broken, which gap classification does not
    cover this cycle (singular-mode only) -- fail closed to NOT_APPLICABLE
    rather than guess.
    """
    try:
        return any(dev_dir.glob(f"dev-report-{task_id}-*.json"))
    except OSError:
        return False


def _safe_task_id(task_id: str) -> bool:
    return bool(task_id not in {".", ".."} and TASK_ID_RE.fullmatch(task_id))


def _lane_paths(dev_dir: Path, task_id: str, worker: str) -> dict[str, Path]:
    lane_id = f"{task_id}-{worker}"
    return {
        "ticket": dev_dir / f"ticket-{lane_id}.md",
        "context": dev_dir / f"context-{lane_id}.json",
        "dev_report": dev_dir / f"dev-report-{lane_id}.json",
        "qa_report": dev_dir / f"qa-report-{lane_id}.json",
    }


def _is_non_worker_label(label: str, aggregate: ModuleType | None) -> bool:
    """Whether the aggregate classifier treats a filename label as non-lane.

    draft/final/fix/continuation/wip and iterN/retryN/attemptN name a revision of
    one artifact, not a parallel lane.  Shared so every filename-derived label in
    this module is classified by the one predicate; an asymmetry here would let
    the same filename be a lane on one code path and not on another.  Without the
    aggregate module no label can be excluded, which is the fail-closed answer.
    """
    if aggregate is None:
        return False
    lowered = label.lower()
    return bool(
        lowered in aggregate.NON_WORKER_LABELS
        or aggregate.NON_WORKER_LABEL_RE.match(lowered)
    )


def _lane_shard_label(filename: str, task_id: str, aggregate: ModuleType) -> str | None:
    """Return the worker label when filename is a dev-report shard OF task_id.

    Shards are named ``dev-report-<task-id>-<worker>.json`` — the same naming
    ``_lane_paths`` constructs.  Labels the aggregate classifier treats as
    non-worker (draft/final/iterN/...) are not lanes.
    """
    prefix = f"dev-report-{task_id}-"
    suffix = ".json"
    if not filename.startswith(prefix) or not filename.endswith(suffix):
        return None
    label = filename[len(prefix) : -len(suffix)]
    if not WORKER_RE.fullmatch(label):
        return None
    if _is_non_worker_label(label, aggregate):
        return None
    return label


def _self_declared_identity(path: Path) -> str | None:
    """Return the task identity an artifact declares about ITSELF, or ``None``.

    ``None`` means "no usable self-declaration" and deliberately conflates every
    degenerate shape — unreadable, non-UTF-8, empty, malformed JSON, a non-object
    top level, an absent/blank/non-string identity key, or two keys that
    contradict each other.  They collapse to one answer so that damaging or
    omitting one's own identity can never buy a weaker verdict than declaring it
    honestly; the caller treats ``None`` as "not vouched for".

    Silent and read-only by design: the artifacts that belong to the chain are
    read and reported on by the validator's own readers, so raising here would
    duplicate their errors under a second code.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    declared: set[str] = set()
    if path.suffix == ".json":
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, RecursionError):
            return None
        if not isinstance(value, dict):
            return None
        for key in ("request_id", "task_id"):
            actual = value.get(key)
            if not isinstance(actual, str) or not actual.strip():
                return None
            declared.add(actual.strip())
    else:
        for line in raw.splitlines():
            cleaned = line.strip().replace("**", "").replace("`", "")
            match = IDENTITY_RE.fullmatch(cleaned)
            if match is not None:
                declared.add(match.group(1))
    if len(declared) != 1:
        return None
    return declared.pop()


def _self_declared_worker(path: Path, task_id: str) -> str | None:
    """Return the worker an artifact's own identity names, or ``None``.

    A lane identity is exactly ``<task-id>-<worker>``.  An identity naming some
    other task, or the parent task-id with no worker, is outside this task's lane
    namespace and cannot vouch for the file, so it too yields ``None``.
    """
    identity = _self_declared_identity(path)
    if identity is None:
        return None
    prefix = f"{task_id}-"
    if not identity.startswith(prefix):
        return None
    worker = identity[len(prefix) :]
    if not WORKER_RE.fullmatch(worker):
        return None
    return worker


def _parent_paths(dev_dir: Path, task_id: str) -> dict[str, Path]:
    return {
        "ticket": dev_dir / f"ticket-{task_id}.md",
        "context": dev_dir / f"context-{task_id}.json",
        "dev_report": dev_dir / f"dev-report-{task_id}.json",
        "qa_report": dev_dir / f"qa-report-{task_id}.json",
        "completion": dev_dir / f"completion-{task_id}.md",
    }


def _find_undeclared_lane_artifacts(
    validator: ChainValidator, workers: list[str], aggregate: ModuleType | None
) -> None:
    """Report artifacts belonging to a lane the canonical never declared.

    Which lane an artifact belongs to is settled by the artifact's own declared
    identity, not by its filename.  A filename suffix is only a label a writer
    chose: a round-two or round-one report of a declared lane carries a
    distinguishing suffix while still declaring — and being — that lane's
    artifact, and attributing it to a lane named after the whole suffix invents a
    worker that never ran.  The identity fields are the authoritative statement of
    what a file is, so they decide.

    The filename remains the fallback, never an escape.  When a file declares no
    usable identity (see ``_self_declared_identity``) it is not vouched for, and
    its filename suffix is attributed to it exactly as before — so an artifact
    cannot evade the check by dropping, blanking, or corrupting its own identity.
    The non-worker label filter applies to that fallback only: it is a heuristic
    about filenames, needed only where no authoritative evidence exists, and
    applying it to a self-declared worker would let a lane exempt itself by
    naming its files after a revision label.
    """
    declared = set(workers)
    families = (
        ("ticket-", ".md"),
        ("context-", ".json"),
        ("qa-report-", ".json"),
    )
    for prefix, suffix in families:
        start = f"{prefix}{validator.task_id}-"
        for path in sorted(validator.dev_dir.glob(f"{start}*{suffix}")):
            worker = _self_declared_worker(path, validator.task_id)
            source = "declared identity"
            if worker is None:
                worker = path.name[len(start) : -len(suffix)]
                source = "filename, no usable declared identity"
                if _is_non_worker_label(worker, aggregate):
                    continue
            if worker not in declared:
                validator.error(
                    "UNDECLARED_LANE_ARTIFACT",
                    _rel(path, validator.root),
                    f"worker {worker!r} (from {source}) is not in canonical "
                    "parallel_workers",
                )


def _declared_union(canonical: dict[str, Any]) -> list[str]:
    """Return the canonical dev-report's declared file union, order-preserving.

    Tolerates a malformed canonical: a non-dict ``dev``, a non-list file list,
    or a non-string entry contributes nothing rather than raising.  ``validate_dev``
    already reports those shapes under their own error codes.
    """
    dev = canonical.get("dev")
    if not isinstance(dev, dict):
        return []
    union: list[str] = []
    for key in ("files_modified", "files_created"):
        entries = dev.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str) and entry and entry not in union:
                union.append(entry)
    return union


def _check_declared_paths_exist(
    validator: ChainValidator, canonical: dict[str, Any], result: dict[str, Any]
) -> None:
    """Every path the canonical declares must exist on disk.

    Reached by both the singular and the fan-out branch: a report claiming files
    it did not produce must not be admitted, whichever way it was assembled.
    Existence is deliberately the weakest defensible predicate -- a directory or
    a symlink, including a broken one, counts as present, because the claim under
    test is "the report named a path that is not there", not "it named a regular
    file".  Read-only: the resolver never creates the paths it looks for.

    One error per absent path, so the report enumerates every miss rather than
    aggregating them into a single opaque failure.
    """
    missing: list[str] = []
    for declared in _declared_union(canonical):
        target = validator.root / declared
        try:
            present = target.exists() or target.is_symlink()
        except OSError:
            present = False
        if not present:
            missing.append(declared)
    result["checks"]["declared_paths_exist"] = not missing
    for declared in missing:
        validator.error(
            "ABSENT_DECLARED_PATH",
            result["canonical_dev_report"],
            f"dev-report declares {declared!r}, which does not exist on disk",
        )


def _workers_declaration_state(canonical: dict[str, Any]) -> str:
    """Classify how the canonical declares ``parallel_workers``.

    ``absent`` and ``empty`` are different facts about an aggregate and must not
    be conflated: a canonical that LOST the key is structurally indistinguishable
    from a genuine singular chain, and would otherwise degrade silently into the
    unchecked branch.
    """
    if "parallel_workers" not in canonical:
        return "absent"
    value = canonical.get("parallel_workers")
    if isinstance(value, list) and not value:
        return "empty"
    return "declared"


def _base_result(task_id: str, canonical: str, completion: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "fail",
        "mode": "unknown",
        "task_id": task_id,
        "canonical_dev_report": canonical,
        "completion": completion,
        "parallel_workers": [],
        "parallel_workers_declaration": "unknown",
        "lanes": [],
        "report_paths": [],
        "artifact_paths": [],
        "commit_whitelist_artifacts": [],
        "qa_inputs": [],
        "checks": {
            "canonical_fresh": False,
            "file_unions_exact": False,
            "declared_paths_exist": False,
        },
        "checks_not_applicable": {},
        "errors": [],
        # R4 additive fields (spec-20260907-115508-lawful-commit-channel.md).
        # NOT_APPLICABLE by default; overwritten only where determinable (see
        # _compute_gap_fields call sites in resolve_chain()).
        "stage_gaps": NOT_APPLICABLE,
        "non_gap_errors": NOT_APPLICABLE,
        "late_repair_eligible": NOT_APPLICABLE,
        "gap_classification": NOT_APPLICABLE,
        # Same-cycle-only gate rescope (task dev-20260927-135305,
        # spec-20260914-052140 S5.3): OWNERSHIP_COMPLETENESS_GAP errors below
        # are now computed with `same_cycle_only=True` -- they block only on
        # THIS cycle's own lanes/claimants failing to account for the bytes
        # they themselves claim, never on an unrelated, possibly still-active
        # session's undeclared bytes in a shared file. The full, cross-cycle-
        # aware computation (span accounting, the declared-boundary chain,
        # the anti-absorption rule) still runs, UNCHANGED, and its diagnostic
        # strings land here -- non-blocking forensic information, not an
        # error, not read by any gate. [] means nothing to report, not that
        # the check did not run.
        "ownership_completeness_informational": [],
    }


# --- Serialized-wave baseline route -----------------------------------------
#
# WHAT THE SHARED-BASELINE REQUIREMENT PROTECTS.  The aggregator projects ONE
# baseline_head_sha and ONE baseline_dirty_snapshot for the whole fan-out,
# taken from the first shard in scan order, and every downstream pre-edit /
# ownership cross-check resolves EVERY lane's files against that single scalar
# (`git cat-file -e <sha>:<rel>` / `git show <sha>:<rel>` in
# aggregate-dev-report.py::_resolve_baseline_snapshot).  Requiring all shards
# to agree is what makes "take the first shard's value" lossless: it detects a
# fan-out whose shards were measured against different repository states, where
# at least one lane's ownership evidence would otherwise be silently verified
# against a baseline that lane never observed.
#
# WHY A ROUTE IS NEEDED.  Equality also encodes an assumption the dispatcher is
# free not to make: that a fan-out is SIMULTANEOUS.  When lanes target the same
# file the orchestrator must serialize them, and then lanes see different dirty
# trees by construction, and a lane that ran after a peer session committed sees
# a different head.  That set is honest, and the gate blocked it -- so the route
# was missing, not the honesty.
#
# WHAT THIS ROUTE IS NOT.  It is not a waiver and not a widening of the default.
# A shard set that declares nothing is adjudicated by the untouched equality
# invariant, byte for byte.  A shard that DOES declare must satisfy strictly
# more than equality would have asked -- its predecessor must be a real shard in
# the set, the predecessor's head must be restated to match what that other
# shard independently recorded, the two heads must stand in a git-verified
# ancestor relation, the working tree may only grow along the chain, the growth
# must equal the figure recomputed from the two recorded snapshots, and the
# growth must be itemised against evidence written by somebody else (a
# predecessor's own files_created, or git's own commit range).  A declaration
# that fails any of these yields NEW errors under INVALID_BASELINE_WAVE; it
# never yields fewer.  Nothing is ever retired for a dimension the declaration
# did not name and verify.
BASELINE_WAVE_KEY = "baseline_wave"
SERIALIZED_WAVE_MODE = "serialized_wave"
WAVE_HEAD_DIMENSION = "baseline_head_sha"
WAVE_DIRTY_DIMENSION = "baseline_dirty_snapshot"
WAVE_DIMENSIONS = (WAVE_HEAD_DIMENSION, WAVE_DIRTY_DIMENSION)
# chain_files_created and commit_range are corroborated against evidence this
# shard did not write (a predecessor shard's own dev.files_created, and git's
# own diff between the two heads).  peer_session is the residual category for a
# shared working tree's concurrent independent sessions; it must still enumerate
# paths, and those paths must not double-count anything the chain itself claims.
WAVE_ATTRIBUTION_SOURCES = ("chain_files_created", "commit_range", "peer_session")


def _wave_snapshot_form(aggregate: ModuleType, snapshot: Any) -> str | None:
    """Classify a recorded baseline_dirty_snapshot's evidentiary form.

    "porcelain" is a verbatim `git status --porcelain` capture: every entry is a
    path, so growth can be itemised exhaustively and the route demands it.
    "count_summary" is the leading-integer narration some dispatch payloads
    carry; it names only examples, so exhaustive itemisation is impossible and
    the route permits a declared, bounded unitemised remainder instead.  None is
    neither, and corroborates nothing.
    """
    if not isinstance(snapshot, str):
        return None
    lines = [line for line in snapshot.splitlines() if line.strip()]
    if lines and all(aggregate.PORCELAIN_LINE_RE.match(line) for line in lines):
        return "porcelain"
    if aggregate.COUNT_SUMMARY_RE.match(snapshot) is not None:
        return "count_summary"
    return None


def _wave_chain_prefix(
    label: str, declared: dict[str, dict], by_label: dict[str, dict]
) -> list[str]:
    """Labels strictly preceding `label` along the declared chain, nearest first."""
    prefix: list[str] = []
    seen = {label}
    current = label
    while current in declared:
        nxt = str(declared[current].get("derived_from") or "").strip()
        if not nxt or nxt in seen or nxt not in by_label:
            break
        prefix.append(nxt)
        seen.add(nxt)
        current = nxt
    return prefix


def _wave_cyclic_labels(
    declared: dict[str, dict], by_label: dict[str, dict]
) -> set[str]:
    """Declared labels whose chain never roots at an undeclared shard."""
    cyclic: set[str] = set()
    for start in declared:
        seen: list[str] = []
        current = start
        while current in declared:
            if current in seen:
                cyclic.update(seen[seen.index(current):])
                break
            seen.append(current)
            current = str(declared[current].get("derived_from") or "").strip()
            if current not in by_label:
                break
    return cyclic


def _wave_reachability_problem(
    project_root: Path, aggregate: ModuleType, ancestor: str, descendant: str
) -> str | None:
    """None when `descendant` is reachable from `ancestor`, else why not.

    Fails closed: an unresolvable sha, or a repository git cannot read, is a
    rejection rather than a pass, because an unverifiable claim must never buy a
    weaker verdict than declaring nothing.
    """
    for sha, role in ((ancestor, "predecessor"), (descendant, "own")):
        rc, _, _ = aggregate._git(
            project_root, ["rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"]
        )
        if rc != 0:
            return (
                f"{role} baseline_head_sha {sha!r} does not resolve to a commit in this"
                " repository, so reachability cannot be verified"
            )
    if ancestor == descendant:
        return None
    rc, _, _ = aggregate._git(
        project_root, ["merge-base", "--is-ancestor", ancestor, descendant]
    )
    if rc == 0:
        return None
    return (
        f"baseline_head_sha {descendant!r} is not reachable from its declared"
        f" predecessor's {ancestor!r}; a serialized wave may only move forward along"
        " committed history, so an unrelated or divergent head is not a lawful successor"
    )


def _wave_growth_problems(
    project_root: Path,
    aggregate: ModuleType,
    wave: dict,
    growth: int,
    prefix: list[str],
    by_label: dict[str, dict],
    own_form: str | None,
    pred_head: str,
    own_head: str,
) -> list[str]:
    """Verify that a declared baseline growth is itemised against real evidence."""
    problems: list[str] = []
    if growth == 0:
        reason = wave.get("narration_divergence")
        if not (isinstance(reason, str) and reason.strip()):
            problems.append(
                "baseline_wave declares zero entry growth, so the two recorded snapshots"
                " describe equally sized trees; baseline_wave.narration_divergence must"
                " state why their text nevertheless differs"
            )
        return problems

    attribution = wave.get("dirty_attribution")
    if not isinstance(attribution, list) or not attribution:
        problems.append(
            f"baseline_wave declares {growth} entries of baseline growth but carries no"
            " dirty_attribution naming where they came from"
        )
        return problems

    prefix_created: set[str] = set()
    for label in prefix:
        dev = by_label.get(label, {}).get("dev")
        created = dev.get("files_created") if isinstance(dev, dict) else None
        if isinstance(created, list):
            prefix_created.update(str(path) for path in created)
    chain_created: set[str] = set()
    for data in by_label.values():
        dev = data.get("dev")
        created = dev.get("files_created") if isinstance(dev, dict) else None
        if isinstance(created, list):
            chain_created.update(str(path) for path in created)

    range_paths: set[str] | None = None
    named: set[str] = set()
    for index, entry in enumerate(attribution):
        if not isinstance(entry, dict):
            problems.append(
                f"baseline_wave.dirty_attribution[{index}] is not an object"
            )
            continue
        source = entry.get("source")
        if source not in WAVE_ATTRIBUTION_SOURCES:
            problems.append(
                f"baseline_wave.dirty_attribution[{index}].source {source!r} is not one"
                f" of {list(WAVE_ATTRIBUTION_SOURCES)}"
            )
            continue
        paths = entry.get("paths")
        if not isinstance(paths, list) or not paths:
            problems.append(
                f"baseline_wave.dirty_attribution[{index}] ({source}) must enumerate at"
                " least one path; a bare count is not an attribution"
            )
            continue
        entry_paths = {str(path) for path in paths}
        named.update(entry_paths)
        if source == "chain_files_created":
            unknown = sorted(entry_paths - prefix_created)
            if unknown:
                problems.append(
                    f"baseline_wave.dirty_attribution[{index}] attributes {unknown} to"
                    f" files created by chain predecessors {prefix!r}, but none of those"
                    " shards recorded creating them"
                )
        elif source == "commit_range":
            if range_paths is None:
                rc, out, _ = aggregate._git(
                    project_root, ["diff", "--name-only", pred_head, own_head]
                )
                range_paths = (
                    {line for line in out.decode("utf-8", "replace").splitlines() if line}
                    if rc == 0
                    else set()
                )
            unknown = sorted(entry_paths - range_paths)
            if unknown:
                problems.append(
                    f"baseline_wave.dirty_attribution[{index}] attributes {unknown} to the"
                    f" commit range {pred_head}..{own_head}, but git reports no such change"
                    " to them in that range"
                )
        else:
            overlap = sorted(entry_paths & chain_created)
            if overlap:
                problems.append(
                    f"baseline_wave.dirty_attribution[{index}] attributes {overlap} to a"
                    " concurrent peer session, but a shard of this very fan-out recorded"
                    " creating them; the same growth cannot be counted twice"
                )

    unitemised = wave.get("dirty_growth_unitemised", 0)
    if not isinstance(unitemised, int) or isinstance(unitemised, bool) or unitemised < 0:
        problems.append(
            "baseline_wave.dirty_growth_unitemised must be a non-negative integer when"
            " present"
        )
        return problems
    if unitemised and own_form == "porcelain":
        problems.append(
            f"baseline_wave leaves {unitemised} entries of growth unitemised, but this"
            " shard recorded a verbatim porcelain snapshot, in which every entry is a"
            " path; exhaustive itemisation is possible here and is therefore required"
        )
    if unitemised and not str(wave.get("dirty_growth_unitemised_reason") or "").strip():
        problems.append(
            "baseline_wave.dirty_growth_unitemised_reason must state why the recorded"
            " snapshot cannot support exhaustive itemisation"
        )
    if len(named) + unitemised != growth:
        problems.append(
            f"baseline_wave itemises {len(named)} path(s) plus {unitemised} unitemised"
            f" entries, which does not account for the {growth} entries of baseline growth"
            " recomputed from the two recorded snapshots"
        )
    return problems


def _adjudicate_serialized_wave(
    project_root: Path, shards: list[tuple[str, dict]], aggregate: ModuleType
) -> tuple[set[str], list[str]]:
    """Adjudicate declared serialized-wave baselines.

    Returns ``(retirable, errors)``: the exact `_validate_shards` detail strings
    a fully verified declaration explains, and the problems found in defective
    declarations.  With no declaration anywhere, returns ``(set(), [])`` and the
    caller's behaviour is unchanged.

    The retirable details are reconstructed in the aggregator's own wording from
    the shards' own recorded values.  That coupling fails CLOSED on purpose: if
    the aggregator's wording ever changes, nothing matches, no detail is retired,
    and the gate blocks again -- the safe direction.
    """
    by_label = {label: data for label, data in shards}
    declared = {
        label: data[BASELINE_WAVE_KEY]
        for label, data in shards
        if isinstance(data.get(BASELINE_WAVE_KEY), dict)
    }
    if not declared:
        return set(), []

    first_sha = str(shards[0][1].get("baseline_head_sha") or "") if shards else ""
    cyclic = _wave_cyclic_labels(declared, by_label)
    errors: list[str] = []
    retirable: set[str] = set()

    for label in sorted(declared):
        wave = declared[label]
        problems: list[str] = []

        mode = wave.get("mode")
        if mode != SERIALIZED_WAVE_MODE:
            problems.append(
                f"baseline_wave.mode {mode!r} is not supported (expected"
                f" {SERIALIZED_WAVE_MODE!r})"
            )
        pred = str(wave.get("derived_from") or "").strip()
        if not pred:
            problems.append("baseline_wave.derived_from is missing or empty")
        elif pred == label:
            problems.append("baseline_wave.derived_from names itself")
        elif pred not in by_label:
            problems.append(
                f"baseline_wave.derived_from {pred!r} is not among the shards"
                f" {sorted(by_label)}"
            )
        if label in cyclic:
            problems.append(
                "baseline_wave chain never roots at an undeclared baseline; a cycle"
                " establishes no order"
            )

        explains = wave.get("explains")
        if not isinstance(explains, list) or not explains:
            problems.append(
                "baseline_wave.explains must be a non-empty list naming the baseline"
                f" dimension(s) the chain accounts for, drawn from {list(WAVE_DIMENSIONS)}"
            )
            explains = []
        else:
            unsupported = sorted({str(d) for d in explains} - set(WAVE_DIMENSIONS))
            if unsupported:
                problems.append(
                    f"baseline_wave.explains names unsupported dimension(s) {unsupported};"
                    f" only {list(WAVE_DIMENSIONS)} can be accounted for by a chain"
                )

        own_sha = str(by_label[label].get("baseline_head_sha") or "")
        pred_sha = str(by_label.get(pred, {}).get("baseline_head_sha") or "")
        head_ok = False
        if WAVE_HEAD_DIMENSION in explains and not problems:
            restated = str(wave.get("predecessor_head_sha") or "")
            if not restated:
                problems.append(
                    "baseline_wave.predecessor_head_sha is required to account for a"
                    " baseline_head_sha divergence"
                )
            elif restated != pred_sha:
                problems.append(
                    f"baseline_wave.predecessor_head_sha {restated!r} does not match the"
                    f" baseline_head_sha {pred_sha!r} that {pred!r} recorded for itself"
                )
            elif not own_sha:
                problems.append(
                    "baseline_head_sha is empty, so there is no successor baseline whose"
                    " reachability could be verified"
                )
            else:
                reach = _wave_reachability_problem(
                    project_root, aggregate, pred_sha, own_sha
                )
                if reach is not None:
                    problems.append(reach)
                else:
                    head_ok = True

        dirty_ok = False
        if WAVE_DIRTY_DIMENSION in explains and not problems:
            prefix = _wave_chain_prefix(label, declared, by_label)
            dirty_pred = str(wave.get("dirty_predecessor") or "").strip()
            if not dirty_pred:
                problems.append(
                    "baseline_wave.dirty_predecessor is required to account for a"
                    " baseline_dirty_snapshot divergence"
                )
            elif dirty_pred not in prefix:
                problems.append(
                    f"baseline_wave.dirty_predecessor {dirty_pred!r} is not among this"
                    f" shard's declared chain predecessors {prefix}"
                )
            else:
                own_snap = by_label[label].get("baseline_dirty_snapshot", "")
                pred_snap = by_label[dirty_pred].get("baseline_dirty_snapshot", "")
                own_n = aggregate._snapshot_entry_count(
                    own_snap if isinstance(own_snap, str) else ""
                )
                pred_n = aggregate._snapshot_entry_count(
                    pred_snap if isinstance(pred_snap, str) else ""
                )
                if own_n is None or pred_n is None:
                    uncountable = label if own_n is None else dirty_pred
                    problems.append(
                        f"baseline_dirty_snapshot for {uncountable!r} is neither porcelain"
                        " output nor a leading-count summary, so a declared chain cannot"
                        " corroborate it"
                    )
                elif own_n < pred_n:
                    problems.append(
                        f"baseline records {own_n} dirty entries but its declared"
                        f" predecessor {dirty_pred!r} recorded {pred_n}; a serialized"
                        " wave's working tree may only grow along the chain"
                    )
                elif wave.get("dirty_growth") != own_n - pred_n:
                    problems.append(
                        f"baseline_wave.dirty_growth {wave.get('dirty_growth')!r} does not"
                        f" equal the {own_n - pred_n} entry growth recomputed from the two"
                        " recorded snapshots"
                    )
                else:
                    growth_problems = _wave_growth_problems(
                        project_root,
                        aggregate,
                        wave,
                        own_n - pred_n,
                        prefix,
                        by_label,
                        _wave_snapshot_form(aggregate, own_snap),
                        str(by_label[dirty_pred].get("baseline_head_sha") or ""),
                        own_sha,
                    )
                    problems.extend(growth_problems)
                    dirty_ok = not growth_problems

        if problems:
            errors.extend(f"shard '{label}': {problem}" for problem in problems)
            continue
        if head_ok:
            retirable.add(
                f"shard '{label}': baseline_head_sha {own_sha!r} != first shard"
                f" {first_sha!r}"
            )
        if dirty_ok:
            retirable.add(f"shard '{label}': baseline_dirty_snapshot mismatch")

    return retirable, errors


def resolve_chain(project_root: Path | str, task_id: str) -> dict[str, Any]:
    """Resolve and validate one artifact chain without mutating the filesystem."""
    root = Path(project_root).resolve()
    task_id = task_id.strip()
    dev_dir = root / "docs" / "dev"
    parents = _parent_paths(dev_dir, task_id)
    result = _base_result(
        task_id,
        _rel(parents["dev_report"], root),
        _rel(parents["completion"], root),
    )
    validator = ChainValidator(root, task_id)

    if not _safe_task_id(task_id):
        validator.error(
            "INVALID_TASK_ID",
            "",
            "task-id must be a safe, non-empty filename component",
        )
        result["errors"] = validator.errors
        return result
    if not dev_dir.is_dir():
        validator.error(
            "MISSING_DEV_DIRECTORY",
            _rel(dev_dir, root),
            "docs/dev directory is absent",
        )
        result["errors"] = validator.errors
        return result

    canonical = validator.read_json(parents["dev_report"])
    completion = validator.read_text(parents["completion"])
    if canonical is None:
        result["errors"] = validator.errors
        # The dev-report itself could not be read (absent, empty, malformed,
        # or non-object) -- exactly the R1.4 "missing more than QA" shape that
        # can include a wholly-absent dev-report (R4/AC-13).  A sibling shard
        # makes the shape ambiguous (possibly a broken fan-out canonical,
        # out of scope this cycle); classify only when unambiguous.
        if not _dev_report_has_sibling_shards(dev_dir, task_id):
            # No sibling shard evidence of a fan-out canonical: classify as
            # the singular shape gap classification requires (R4/AC-13's
            # wholly-absent-dev-report case can only be reached this way).
            result["mode"] = "singular"
            qa_report_path = _rel(parents["qa_report"], root)
            (
                result["stage_gaps"],
                result["non_gap_errors"],
                result["late_repair_eligible"],
                result["gap_classification"],
            ) = _compute_gap_fields(validator.errors, qa_report_path)
        return result

    validator.validate_dev(canonical, task_id, parents["dev_report"])
    # Reached before the branch split, so both modes are held to it.
    _check_declared_paths_exist(validator, canonical, result)
    workers_declaration = _workers_declaration_state(canonical)
    result["parallel_workers_declaration"] = workers_declaration
    workers_value = canonical.get("parallel_workers", [])
    workers: list[str] = []
    if not isinstance(workers_value, list) or any(
        not isinstance(worker, str) or not WORKER_RE.fullmatch(worker)
        for worker in workers_value
    ):
        validator.error(
            "INVALID_WORKER_SET",
            result["canonical_dev_report"],
            "parallel_workers must be an array of valid worker labels",
        )
    else:
        workers = list(workers_value)
        if len(set(workers)) != len(workers):
            validator.error(
                "AMBIGUOUS_WORKER_SET",
                result["canonical_dev_report"],
                "parallel_workers contains duplicates",
            )

    try:
        aggregate = _load_aggregate_module()
        bare_task_id = aggregate._bare_task_id(task_id)
        # Shards belong to the FULL task-id.  When the bare timestamp is a
        # truncation of it (prefixed/suffixed ids), classifying against that key
        # collects this task's own canonical and unrelated sibling tasks, so the
        # filename must name this task-id plus a worker suffix instead.
        scan_key_is_truncated = bare_task_id != task_id
        own_canonical = parents["dev_report"].name
        scanned = []
        scanned_lanes: set[str] = set()
        try:
            children = sorted(dev_dir.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            validator.error(
                "UNREADABLE_DEV_DIRECTORY", _rel(dev_dir, root), str(exc)
            )
            children = []
        for child in children:
            if not child.is_file() or child.name == own_canonical:
                continue
            if scan_key_is_truncated:
                label = _lane_shard_label(child.name, task_id, aggregate)
                is_worker = label is not None
            else:
                is_worker, label = aggregate._is_worker_for_task(
                    child.name, bare_task_id, task_id
                )
            if is_worker and label is not None:
                # The filename settles only WHETHER a file is a dev-report shard
                # of this task; WHICH lane it belongs to is settled by the
                # identity it declares about itself, exactly as
                # `_find_undeclared_lane_artifacts` already settles it.  A lane's
                # fix round is a second report OF that lane carrying a
                # distinguishing suffix, and naming a lane after the whole suffix
                # invents a worker that never ran.  The filename stays the
                # fallback and never becomes an escape: a shard with no usable
                # self-declaration keeps its filename label, so damaging or
                # omitting one's own identity can never buy a weaker verdict than
                # declaring it honestly, and a declaration naming a lane the
                # canonical never declared is not honoured either, so no artifact
                # can smuggle itself into the lane set by claiming a lane nobody
                # dispatched -- the identity and lane-set checks then report it
                # under their own codes.
                declared_lane = _self_declared_worker(child, task_id)
                if declared_lane is not None and declared_lane in workers:
                    label = declared_lane
                # One lane can own several shards once identity decides, so the
                # lane is recorded once; the exact-match comparison below is
                # against the set of lanes present, not the file count.
                if label in scanned_lanes:
                    continue
                scanned_lanes.add(label)
                scanned.append((label, child))
        scanned.sort(key=lambda item: item[0])
    except Exception as exc:
        validator.error(
            "AGGREGATE_IMPLEMENTATION_ERROR",
            "scripts/aggregate-dev-report.py",
            str(exc),
        )
        scanned = []
        aggregate = None

    if workers:
        result["mode"] = "fanout"
        if len(workers) < 2:
            validator.error(
                "AMBIGUOUS_WORKER_SET",
                result["canonical_dev_report"],
                "fan-out requires at least two workers",
            )
        scanned_labels = [worker for worker, _ in scanned]
        if scanned_labels != workers:
            validator.error(
                "LANE_SET_MISMATCH",
                result["canonical_dev_report"],
                f"parallel_workers {workers!r} do not exactly match shards {scanned_labels!r}",
            )
        _find_undeclared_lane_artifacts(validator, workers, aggregate)

        loaded_shards: list[tuple[str, dict[str, Any]]] = []
        completion_refs = [result["canonical_dev_report"]]
        artifact_paths = [result["canonical_dev_report"], result["completion"]]
        result["report_paths"] = [result["canonical_dev_report"]]
        for worker in workers:
            lane_id = f"{task_id}-{worker}"
            paths = _lane_paths(dev_dir, task_id, worker)
            lane = {
                "worker": worker,
                "task_id": lane_id,
                **{key: _rel(path, root) for key, path in paths.items()},
            }
            result["lanes"].append(lane)
            result["report_paths"].extend((lane["dev_report"], lane["qa_report"]))
            lane_refs = [lane[key] for key in ("ticket", "context", "dev_report", "qa_report")]
            completion_refs.extend(lane_refs)
            artifact_paths.extend(lane_refs)

            ticket = validator.read_text(paths["ticket"])
            if ticket is not None:
                validator.validate_markdown_identity(ticket, lane_id, paths["ticket"])
            context = validator.read_json(paths["context"])
            if context is not None:
                validator.validate_json_identity(context, lane_id, paths["context"])
            dev = validator.read_json(paths["dev_report"])
            if dev is not None:
                validator.validate_dev(dev, lane_id, paths["dev_report"])
                loaded_shards.append((worker, dev))
            qa = validator.read_json(paths["qa_report"])
            if qa is not None:
                validator.validate_qa(qa, lane_id, paths["qa_report"])

        if completion is not None:
            validator.validate_completion(
                completion, task_id, parents["completion"], completion_refs
            )
        result["artifact_paths"] = artifact_paths
        result["commit_whitelist_artifacts"] = artifact_paths
        result["qa_inputs"] = [
            {"task_id": lane["task_id"], "qa_report": lane["qa_report"]}
            for lane in result["lanes"]
        ]

        # The roster each lane copied verbatim from its dispatch (lane_set):
        # divergent copies are one mismatch naming them all; otherwise a roster
        # lane with no shard, or a shard outside the roster, is one each.
        rosters = {
            worker: data["lane_set"]
            for worker, data in loaded_shards
            if isinstance(data.get("lane_set"), list)
        }
        distinct = list({json.dumps(r): r for r in rosters.values()}.values())
        if len(distinct) > 1:
            validator.error(
                "LANE_SET_MISMATCH",
                result["canonical_dev_report"],
                f"shards record divergent lane_set rosters {rosters!r}",
            )
        elif distinct:
            roster = distinct[0]
            for lane_label in [name for name in roster if name not in scanned_labels]:
                validator.error(
                    "LANE_SET_MISMATCH",
                    result["canonical_dev_report"],
                    f"roster lane {lane_label!r} of lane_set {roster!r} has no shard",
                )
            for lane_label in [name for name in scanned_labels if name not in roster]:
                validator.error(
                    "LANE_SET_MISMATCH",
                    result["canonical_dev_report"],
                    f"shard {lane_label!r} is outside the recorded lane_set {roster!r}",
                )

        if aggregate is not None and len(loaded_shards) == len(workers):
            shard_errors = aggregate._validate_shards(loaded_shards, task_id)
            # A serialized fan-out is a declared shape, not an accident.  The
            # adjudication below is additive: with no declaration it returns
            # nothing and shard_errors is reported exactly as before, and a
            # defective declaration ADDS errors under its own code.  Only a
            # declaration that survives every check in
            # _adjudicate_serialized_wave retires the specific divergence
            # detail it accounts for, and only for the dimension it named.
            wave_retirable, wave_errors = _adjudicate_serialized_wave(
                root, loaded_shards, aggregate
            )
            for detail in wave_errors:
                validator.error(
                    "INVALID_BASELINE_WAVE", result["canonical_dev_report"], detail
                )
            shard_errors = [
                detail for detail in shard_errors if detail not in wave_retirable
            ]
            for detail in shard_errors:
                validator.error(
                    "INVALID_SHARD_SET", result["canonical_dev_report"], detail
                )
            if not shard_errors:
                expected = aggregate._build_aggregate(loaded_shards, task_id)
                canonical_dev = canonical.get("dev")
                if not isinstance(canonical_dev, dict):
                    canonical_dev = {}
                result["checks"]["file_unions_exact"] = (
                    canonical_dev.get("files_modified")
                    == expected.get("dev", {}).get("files_modified")
                    and canonical_dev.get("files_created")
                    == expected.get("dev", {}).get("files_created")
                )
                result["checks"]["canonical_fresh"] = aggregate._canonical_projection(
                    canonical
                ) == aggregate._canonical_projection(expected)
                if not result["checks"]["file_unions_exact"]:
                    validator.error(
                        "STALE_FILE_UNION",
                        result["canonical_dev_report"],
                        "canonical file unions do not match current lane reports",
                    )
                if not result["checks"]["canonical_fresh"]:
                    validator.error(
                        "STALE_CANONICAL",
                        result["canonical_dev_report"],
                        "canonical aggregate projection does not match current lane reports",
                    )
            # Ownership completeness (backlog #99 criterion C) is this
            # resolver's OWN error class, so a gap blocks /close by its own
            # code instead of riding anonymously on UNRESOLVED_BLOCKERS.  It
            # rode there only because the aggregator appended its diagnostics
            # to `blocking_issues`, which made the canonical permanently stale
            # against its own rebuild (see aggregate-dev-report.py's
            # COMPLETENESS_GAPS_KEY).  Three properties are load-bearing:
            #
            #   * RECOMPUTED, never read from the canonical's stored record, so
            #     neither an outdated nor a forged record can suppress a gap;
            #   * computed by the producer's OWN `_apply_completeness_check` --
            #     one implementation with two callers, so the halves cannot
            #     drift into disagreeing about what a gap is;
            #   * OUTSIDE the `not shard_errors` guard above, so no gap class
            #     becomes unreachable behind an unrelated shard error.
            #
            # Design-direction correction (task dev-20260927-135305,
            # spec-20260914-052140 S5.3): the ERROR that blocks /close is now
            # computed with `same_cycle_only=True` -- does THIS cycle's own
            # set of declared lanes/claimants correctly and non-conflictingly
            # account for the bytes its OWN ledgers claim? That question
            # never depends on whether some OTHER, possibly still-active,
            # session has declared its bytes in a shared file yet (the
            # forbidden shape: an unbounded number of concurrent sessions
            # must be able to land their own bytes in a shared file, and the
            # mere fact a file was touched by a peer must never itself
            # trigger a cross-check EXCLUDE). The full, cross-cycle-aware
            # call (default `same_cycle_only=False`) keeps running UNCHANGED
            # -- span accounting, the declared-boundary chain, the
            # parent_cycle claimant reader, the anti-absorption rule, all of
            # it -- and its diagnostics are never discarded: they land in
            # `result["ownership_completeness_informational"]` as non-
            # blocking forensic information for a human or a later process,
            # not as an error any gate reads.
            completeness_gaps = aggregate._apply_completeness_check(
                canonical, root, loaded_shards
            )
            result["ownership_completeness_informational"] = list(completeness_gaps)
            same_cycle_completeness_gaps = aggregate._apply_completeness_check(
                canonical, root, loaded_shards, same_cycle_only=True
            )
            for detail in same_cycle_completeness_gaps:
                validator.error(
                    "OWNERSHIP_COMPLETENESS_GAP",
                    result["canonical_dev_report"],
                    detail,
                )
            # The producer/consumer agreement, COMPARED AT RUNTIME rather than
            # declared in a comment: the producer's half of this fix is that no
            # completeness diagnostic is ever written into `blocking_issues`.
            # If that half is reverted or bypassed, the gap texts reappear
            # there and this fires -- which is what keeps the two files' halves
            # from being reverted independently and silently.  Checked against
            # the UNION of both channels: a leak of either the blocking or the
            # now-informational diagnostic text into `blocking_issues` is the
            # same regression.
            canonical_blockers = canonical.get("blocking_issues")
            all_completeness_diagnostics = set(completeness_gaps) | set(
                same_cycle_completeness_gaps
            )
            if isinstance(canonical_blockers, list) and all_completeness_diagnostics:
                leaked = sorted(set(canonical_blockers) & all_completeness_diagnostics)
                if leaked:
                    validator.error(
                        "COMPLETENESS_CHANNEL_VIOLATION",
                        result["canonical_dev_report"],
                        "ownership-completeness diagnostics are present in the "
                        "freshness-compared blocking_issues field, which makes the "
                        f"canonical unable to converge: {leaked[:4]}",
                    )
    else:
        result["mode"] = "singular"
        # Both are comparisons of the canonical against a rebuild from two or
        # more shards.  A singular chain has no shards, so neither has a
        # singular analogue -- report that, rather than a value that would read
        # as a check having been performed.  Assigned per key so the
        # branch-independent checks computed above survive.
        for check in ("canonical_fresh", "file_unions_exact"):
            result["checks"][check] = NOT_APPLICABLE
            result["checks_not_applicable"][check] = SINGULAR_RELATIONAL_REASON
        if scanned:
            validator.error(
                "AMBIGUOUS_SINGULAR_CHAIN",
                result["canonical_dev_report"],
                f"singular canonical coexists with worker shards {[label for label, _ in scanned]!r}",
            )
        if workers_declaration == "absent" and scanned:
            # Additive to AMBIGUOUS_SINGULAR_CHAIN above, which still fires
            # unchanged.  That error says "a singular chain has shards"; this one
            # says "this is an aggregate that lost its parallel_workers key",
            # which is a different diagnosis with a different remedy.
            validator.error(
                "LOST_WORKER_DECLARATION",
                result["canonical_dev_report"],
                "parallel_workers key is absent, not empty, while worker shards "
                f"{[label for label, _ in scanned]!r} survive on disk; an aggregate "
                "that lost the key is indistinguishable from a singular chain",
            )
        completion_refs = [
            _rel(parents[key], root)
            for key in ("ticket", "context", "dev_report", "qa_report")
        ]
        ticket = validator.read_text(parents["ticket"])
        if ticket is not None:
            validator.validate_markdown_identity(ticket, task_id, parents["ticket"])
        context = validator.read_json(parents["context"])
        if context is not None:
            validator.validate_json_identity(context, task_id, parents["context"])
        qa = validator.read_json(parents["qa_report"])
        if qa is not None:
            validator.validate_qa(qa, task_id, parents["qa_report"])
        if completion is not None:
            validator.validate_completion(
                completion, task_id, parents["completion"], completion_refs
            )
        result["report_paths"] = [
            result["canonical_dev_report"],
            _rel(parents["qa_report"], root),
        ]
        result["artifact_paths"] = completion_refs + [result["completion"]]
        result["commit_whitelist_artifacts"] = list(result["artifact_paths"])
        result["qa_inputs"] = [
            {"task_id": task_id, "qa_report": _rel(parents["qa_report"], root)}
        ]

    result["parallel_workers"] = workers
    result["errors"] = validator.errors
    result["status"] = "fail" if validator.errors else "pass"
    if result["mode"] == "singular":
        (
            result["stage_gaps"],
            result["non_gap_errors"],
            result["late_repair_eligible"],
            result["gap_classification"],
        ) = _compute_gap_fields(validator.errors, _rel(parents["qa_report"], root))
    return result


def exit_status(result: dict[str, Any]) -> int:
    """The chain's verdict as an exit status: 0 for a complete chain (status
    "pass"), 2 otherwise. main exits with it; a caller that loads this module
    acts on the verdict through it, never through a status test of its own."""
    return 0 if result["status"] == "pass" else 2


def late_repair_eligible(result: dict[str, Any]) -> bool:
    """The chain's verdict on the late-repair route: the field
    `_compute_gap_fields` computes, true only for a singular chain whose every
    gap is a stage gap; NOT_APPLICABLE (a fan-out chain, or none classified) is
    not eligible."""
    return result.get("late_repair_eligible") is True


# --- Disposition --------------------------------------------------------------
#
# One answer per task and stage for every consumer: chain_pass, or incomplete
# with its gaps.  A gap holds facts only: the artifact, the failing check's code
# and message, and the lane of the dispatch that declared the artifact.  A
# broken instrument raises instead, so it is never read as a gap.
STAGES = ("dev", "close", "commit")
# The chain's data fields the disposition prints for a /dev task (its CHAIN= line).
CHAIN_FIELDS = ("mode", "lanes", "report_paths", "canonical_dev_report", "artifact_paths",
                "commit_whitelist_artifacts", "qa_inputs")
INSTRUMENT_CODES = frozenset({"AGGREGATE_IMPLEMENTATION_ERROR", "UNREADABLE_DEV_DIRECTORY"})
# Python's own exit status for an unhandled exception, so a failure main()
# catches and one it cannot (raised while the interpreter loads it) read alike.
INSTRUMENT_FAILURE_EXIT = 1
# Gap-line values stay one printable-ASCII line: anything else is a JSON string.
_GAP_TOKEN_RE = re.compile(r'[!#-\[\]-~]+')
_GAP_MESSAGE_UNSAFE_RE = re.compile(r'[^ -~]|^"| lane=')


def _harness_lib(name: str) -> ModuleType:
    """hooks/lib/<name> of the harness this script is installed in."""
    harness = str(Path(__file__).resolve().parent.parent)
    if harness not in sys.path:
        sys.path.insert(0, harness)
    return importlib.import_module(f"hooks.lib.{name}")


def _newer(path: Path, than: Path) -> bool:
    try:
        return path.stat().st_mtime_ns > than.stat().st_mtime_ns
    except OSError:
        return False


def _check_dev_chain(validator: ChainValidator, task_id: str, obligation: ModuleType) -> dict[str, str]:
    """The dev chain, strict, plus each lane's BA-QA verdict and unanswered
    producer questions.  Returns each lane artifact's lane label, the lane a
    gap takes when no dispatch declared its artifact."""
    root, dev_dir = validator.root, validator.dev_dir
    result = resolve_chain(root, task_id)
    validator.chain = {key: result[key] for key in CHAIN_FIELDS}
    for error in result["errors"]:
        if error["code"] in INSTRUMENT_CODES:
            raise RuntimeError(f"{error['code']} at {error['path']}: {error['detail']}")
    validator.errors.extend(
        error for error in result["errors"]
        if (error["code"], error["path"]) != ("MISSING_ARTIFACT", result["completion"])
    )
    units = {
        "singular": [(task_id, None)],
        "fanout": [(lane["task_id"], lane["worker"]) for lane in result["lanes"]],
    }.get(result["mode"], [])
    roles = sorted(obligation._schema_enum("producer-question.v1", "role"))
    lanes: dict[str, str] = {}
    for unit, worker in units:
        paths = _parent_paths(dev_dir, unit)
        ba_qa = dev_dir / f"ba-qa-report-{unit}.json"
        questions = [(role, dev_dir / f"producer-question-{unit}-{role}.json") for role in roles]
        if worker:
            lanes.update((_rel(path, root), worker) for path in (*paths.values(), ba_qa, *dict(questions).values()))
        report = validator.read_json(ba_qa)
        if report is not None and obligation.terminal_status("ba-qa-report.v1", report) != "pass":
            validator.error(
                "INVALID_BA_QA_VERDICT",
                _rel(ba_qa, root),
                f"verdict is {report.get('verdict')!r}; expected 'pass'",
            )
        for role, question in questions:
            if not question.is_file():
                continue
            # Asked by the dispatch whose own task_id and role name it, as G2 reads it (no obligation
            # declares it, so declaring_dispatch finds none); all else it declares answers it (D21).
            asking = obligation._latest([
                r for r in obligation._task_records(task_id, root, None)
                if (r["obligation"].get("task_id"), r["obligation"].get("role")) == (unit, role)])
            rel = _rel(question, root)
            owed = {Path(a["path"]).as_posix() for a in (asking["obligation"].get("artifacts", []) if asking else [])
                    if "path" in a} - {rel}
            late = sorted(path for path in owed if not _newer(root / path, question))
            if not owed or late:
                validator.error("unanswered", rel, f"{', '.join(late)} not written after the question" if late
                                else "no dispatch of the task declares the artifacts that answer it")
    return lanes


def _do_minted(root: Path, task_id: str) -> bool:
    """Whether the UserPromptSubmit hook minted ``task_id`` for a /do the human
    typed: a /do span whose hook-minted id (command_span.Span.minted_id, the
    transcripts' one reader) is the task, in any session of the project's
    transcript store (a later session's /close finds it too)."""
    obligation, command_span = (_harness_lib(name) for name in ("obligation", "command_span"))
    for transcript in obligation._session_transcripts(root, None):
        for line, command, args in command_span.openers(str(transcript)):
            if command == "do" and command_span.Span(command, args, line, str(transcript)).minted_id() == task_id:
                return True
    return False


def _check_do_report(
    validator: ChainValidator, path: Path, record: dict | None, problem: str | None, obligation: ModuleType
) -> None:
    relative = _rel(path, validator.root)
    if record is None:  # do_report.load's verdict, the report's one reading (P1b E8)
        validator.error("MISSING_ARTIFACT", relative, problem)
    elif obligation.terminal_status("do-report.v1", record) != "completed":
        do = record.get("do") if record else None
        status = do.get("status") if isinstance(do, dict) else None
        validator.error(
            f"do.status:{status if isinstance(status, str) else json.dumps(status)}",
            relative,
            problem or f"do.status is {status!r}; expected 'completed'",
        )


def _check_commits(validator: ChainValidator, task_id: str, report: Path, lifecycle: ModuleType) -> None:
    """A ``Task-id`` line reachable from HEAD in every repository of the task's
    commit plan, the plan built as dev-lifecycle's commit_detection builds it;
    its dirty-tree half is no part of the disposition."""
    root = validator.root
    repos = lifecycle._load_commit_repos_module()
    try:
        plan = repos.build_plan(
            task_id=task_id,
            control_root_arg=str(root),
            supported_repo_args=[],
            report_arg=str(report),
            verify_ownership=False,
        )
    except repos.PlanError as exc:
        validator.error("REPO_PLAN_ERROR", _rel(report, root), str(exc))
        return
    trailer = f"Task-id: {task_id}"
    for repo in plan["repositories"]:
        repo_root = Path(repo["repo_root"])
        if not lifecycle._head_reachable_trailer(repo_root, trailer):
            validator.error(
                "MISSING_TASK_TRAILER",
                _rel(repo_root, root),
                f"no commit reachable from HEAD carries the line {trailer!r}",
            )


def disposition(project_root: Path | str, task_id: str, stage: str) -> dict[str, Any]:
    """The task's disposition at ``stage`` (dev, close or commit), read-only:
    ``{"disposition": "chain_pass" | "incomplete", "stage", "task_id",
    "gaps": [{"artifact", "problem", "message", "lane"}, ...]}``, the gaps in
    stage order.  Raises on an instrument failure (an unknown stage, an unsafe
    task id, a missing project root, an unimportable helper, an unreadable
    docs/dev, a failing aggregator)."""
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {', '.join(STAGES)}, not {stage!r}")
    task_id = task_id.strip()
    if not _safe_task_id(task_id):
        raise ValueError(f"task-id {task_id!r} is not a safe filename component")
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"project root {root} is not a directory")
    obligation = _harness_lib("obligation")
    validator = ChainValidator(root, task_id)
    report = validator.dev_dir / f"dev-report-{task_id}.json"
    do_path = validator.dev_dir / f"do-report-{task_id}.json"
    lanes: dict[str, str] = {}
    do_record, do_problem = _harness_lib("do_report").load(do_path)
    do_task = (do_record is not None and do_record.get("source") == "do") or (
        not report.is_file() and _do_minted(root, task_id))
    if do_task and report.is_file() and obligation.terminal_status("do-report.v1", do_record) != "completed":
        # Q7: the report of dev, dispatched along the do-report's route, concludes the /do task (G2 verified it),
        # and the do-report's lists equal that report's (A3.c with no transcript, do_report_gaps)
        if (record := validator.read_json(report)) is not None:
            validator.validate_dev(record, task_id, report)
        for code, artifact, detail in do_report_gaps(root, task_id, do_path):
            validator.error(code, artifact, detail)
    elif do_task:
        report = do_path
        _check_do_report(validator, do_path, do_record, do_problem, obligation)
    else:
        lanes = _check_dev_chain(validator, task_id, obligation)
    if stage != "dev":
        lifecycle = _exec_script("dev-lifecycle.py", "_disposition_lifecycle")
        close_report = validator.dev_dir / f"close-report-{task_id}.md"
        verdict = lifecycle._load_close_verdict_module().classify_file(close_report)
        if verdict != "yes":
            validator.error(
                "INVALID_CLOSE_VERDICT",
                _rel(close_report, root),
                f"the last non-empty line classifies as {verdict!r}; expected 'yes'",
            )
        if stage == "commit":
            _check_commits(validator, task_id, report, lifecycle)
    declared: dict[str, dict | None] = {}
    gaps = []
    for error in validator.errors:
        path = error["path"]
        if path not in declared:
            declared[path] = obligation.declaring_dispatch(task_id, path, root)
        gaps.append({
            "artifact": path,
            "problem": error["code"],
            "message": error["detail"],
            "lane": (declared[path] or {}).get("lane") or lanes.get(path),
        })
    return {
        "disposition": "incomplete" if gaps else "chain_pass",
        "stage": stage,
        "task_id": task_id,
        "gaps": gaps,
        "chain": getattr(validator, "chain", None),
    }


def gap_line(gap: dict[str, Any]) -> str:
    """One gap as the CLI prints it.  A value outside its plain form (a token
    without spaces or quotes; a message without control or non-ASCII
    characters, a leading quote or " lane=") is written as a JSON string."""
    def token(value: Any) -> str:
        text = str(value)
        return text if _GAP_TOKEN_RE.fullmatch(text) else json.dumps(text)

    message = str(gap["message"])
    if _GAP_MESSAGE_UNSAFE_RE.search(message):
        message = json.dumps(message)
    lane = "-" if gap["lane"] is None else token(gap["lane"])
    return f"GAP artifact={token(gap['artifact'])} problem={token(gap['problem'])}: {message} lane={lane}"


def _print_disposition(project_dir: str, task_id: str, stage: str | None) -> int:
    try:
        outcome = disposition(project_dir, task_id, stage)
    except Exception as exc:  # an instrument failure: never a disposition
        print(
            f"resolve-dev-artifact-chain.py: instrument failure: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return INSTRUMENT_FAILURE_EXIT
    print(f"DISPOSITION={outcome['disposition']} STAGE={outcome['stage']} TASK={outcome['task_id']}")
    for gap in outcome["gaps"]:
        print(gap_line(gap))
    if outcome.get("chain") is not None:
        print("CHAIN=" + json.dumps(outcome["chain"], ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


def _default_project_dir() -> str:
    """The working directory's git top level, else the working directory: the
    CLI is run from inside the project, and a Bash call's environment carries
    no CLAUDE_PROJECT_DIR."""
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return os.getcwd()
    return top.stdout.strip() if top.returncode == 0 and top.stdout.strip() else os.getcwd()


def do_report_gaps(
    project_root: Path | str, task_id: str, path: Path, transcript: str | None = None
) -> list[tuple[str, str, str]]:
    """The do branch's checks beyond the record and do.status (P5 R8, A3.c), as
    (code, artifact, detail). With the session ``transcript`` (the /do Stop):
    the report fails its versioned schema; and its files_modified and
    files_created (a created file may sit in either) differ from the write set
    of every /do span of the task in it: the main agent's own
    Write/Edit/MultiEdit/NotebookEdit targets with an ok result, its Bash
    commands' paths counting as named (command_span.Span.write_set). Each
    listed file is written or named and each written file is listed, else one
    gap names the exact expected paths. Without a transcript (the Q7 route of a
    /close or /commit stage: the do-report is not completed and the task's
    dev-report, which G2 verified at dev's stop, concludes it) its lists must
    equal that dev-report's dev.files_modified and dev.files_created, else one
    gap names them; with no dev-report they stand as the report states them.
    Read-only."""
    harness = str(Path(__file__).resolve().parent.parent)
    if harness not in sys.path:
        sys.path.insert(0, harness)
    from hooks.lib import command_span, contract_runtime, do_report

    root = Path(project_root).resolve()
    path = Path(path)
    relative = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)

    def listed(section) -> set:
        lists = [section.get(key) for key in ("files_modified", "files_created")] if isinstance(section, dict) else []
        rels = (command_span._project_relative(entry, str(root), str(root))
                for listed in lists if isinstance(listed, list) for entry in listed if isinstance(entry, str))
        return {rel for rel in rels if rel}

    record, _problem = do_report.load(path)
    do = record.get("do") if isinstance(record, dict) else None
    if not transcript:
        dev_path = root / "docs" / "dev" / f"dev-report-{task_id}.json"
        try:
            dev = json.loads(dev_path.read_text(encoding="utf-8")).get("dev")
        except (OSError, ValueError, AttributeError):
            return []  # no dev-report to compare (or one the chain's own check reads)
        expected = listed(dev)
        if isinstance(do, dict) and listed(do) != expected:
            return [("FILES_NOT_DEV_REPORT", relative,
                     "do.files_modified + do.files_created must list exactly the files of "
                     f"{dev_path.relative_to(root).as_posix()} (dev.files_modified + dev.files_created): "
                     f"{json.dumps(sorted(expected))}")]
        return []
    schema = contract_runtime.validate_report_artifact(path)
    gaps = [("SCHEMA_VIOLATION", relative, str(error))
            for error in (schema.get("errors") or []) if schema.get("status") == "fail"]
    if not isinstance(do, dict):
        return gaps
    declared = listed(do)
    written, named, found = set(), set(), False
    openers = command_span.openers(transcript)
    for k, (line, command, args) in enumerate(openers):
        span = command_span.Span(command, args, line, transcript)
        if command != "do" or span.minted_id() != task_id:
            continue
        result = span.write_set(root, actor="main", stop_line=openers[k + 1][0] if k + 1 < len(openers) else None)
        if result is not None:
            found = True
            written |= result.written
            named |= result.named
    if found and (written - declared or declared - written - named):
        gaps.append((
            "FILES_NOT_WRITE_SET",
            relative,
            "do.files_modified + do.files_created must list exactly the files this /do wrote "
            f"(and may list files its Bash commands named): {json.dumps(sorted(written | (declared & named)))}",
        ))
    return gaps


def disposition_lines(project_root: Path | str, task_id: str, stage: str) -> list[str]:
    """The task's disposition at ``stage`` as the Stop gate prints it (P5
    R7): no line for chain_pass (D2: nothing else passes), else one gap_line
    per gap, where an artifact no dispatch declared yet also names the
    canonical todo step the DDR says owes it. Raises on an instrument
    failure, as disposition does; disposition and gap_line are P3's."""
    outcome = disposition(project_root, task_id, stage)
    if outcome["disposition"] == "chain_pass":
        return []
    harness = str(Path(__file__).resolve().parent.parent)
    if harness not in sys.path:
        sys.path.insert(0, harness)
    from hooks.lib import obligation

    lines = []
    for gap in outcome["gaps"]:
        owner = obligation.declaring_dispatch(task_id, gap["artifact"], project_root) \
            if gap["lane"] is None and gap["artifact"] else None
        step = owner.get("step") if isinstance(owner, dict) and owner.get("source") == "todo_step" else None
        lines.append(gap_line(gap) + (f" step={json.dumps(step, ensure_ascii=False)}" if step else ""))
    return lines or [f"{stage} {task_id}: disposition {outcome['disposition']!r}, needs 'chain_pass'"]


def unowed_gap(project_root: Path | str, task_id: str, stage: str) -> str | None:
    """The first gap artifact of the task's disposition at ``stage`` that the
    reader of dispatches (obligation.declaring_dispatch) names no owner for, as
    the gap's own artifact; None when every gap has one or there is no gap. No
    dispatch record or canonical todo step owes such a gap, so an unattended
    run can never produce it (dev-lifecycle's --auto passes the task over on
    this verdict, used verbatim). Raises on an instrument failure, as
    disposition does."""
    obligation = _harness_lib("obligation")
    return next((gap["artifact"] for gap in disposition(project_root, task_id, stage)["gaps"]
                 if obligation.declaring_dispatch(task_id, gap["artifact"], project_root) is None), None)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = StableArgumentParser(prog="resolve-dev-artifact-chain.py")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--project-dir")
    parser.add_argument("--disposition", action="store_true")
    parser.add_argument("--stage")
    try:
        args = parser.parse_args(argv)
    except ValueError as exc:
        if "--disposition" in argv:
            print(f"resolve-dev-artifact-chain.py: {exc}", file=sys.stderr)
            return INSTRUMENT_FAILURE_EXIT
        result = _base_result("", "", "")
        result["errors"] = [
            {"code": "CLI_ARGUMENT_ERROR", "path": "", "detail": str(exc)}
        ]
        print(
            json.dumps(
                result, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
        )
        return 2
    project_dir = args.project_dir or _default_project_dir()
    if args.disposition:
        return _print_disposition(project_dir, args.task_id, args.stage)
    result = resolve_chain(project_dir, args.task_id)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return exit_status(result)


if __name__ == "__main__":
    sys.exit(main())
