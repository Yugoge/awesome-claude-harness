#!/usr/bin/env python3
"""Canonical aggregate writer for parallel-dev cycles.

Scans docs/dev/ for per-worker shard dev-reports matching a given task-id,
validates consistency across shards, and writes a canonical aggregate
docs/dev/dev-report-<task-id>.json.

Classification logic (NON_WORKER_LABELS, NON_WORKER_LABEL_RE, and all filename
patterns) mirrors hooks/pretool-aggregate-check.py exactly — do NOT diverge.

Shard scanning uses the bare YYYYMMDD-HHMMSS timestamp as the scan key for
the standard shard patterns (PER_WORKER_ROLE_FIRST_RE, PER_WORKER_TASK_FIRST_RE).
The active adapter's `dev-<timestamp>` IDs use explicit prefixed-worker patterns;
the canonical prefixed filename is excluded before legacy role-first matching.
Bare timestamp role-first/task-first behavior remains unchanged.

Usage:
    python3 scripts/aggregate-dev-report.py --task-id <TASK_ID>
    python3 scripts/aggregate-dev-report.py --task-id <TASK_ID> --dry-run

Exit codes:
    0   Success (action: aggregated | validated | skipped)
    1   Validation failure or I/O error (descriptive message on stderr)
    2   Bad arguments

stdout (on exit 0):
    JSON: {"status": "ok", "action": "aggregated"|"validated"|"skipped",
           "output_path": "<path>", "reason": "<human-readable>"}
stderr (on non-zero exit):
    Human-readable error describing the failure.

Shard-mismatch side effect (spec-20260904-harness-fixes.md R29): on exit 1
from a shard-load failure, a _validate_shards mismatch, or the
len(shards_info)<2 skip branch when a pre-existing canonical's own recorded
roster establishes the cycle was genuinely parallel (not --dry-run), this
now ALSO writes docs/dev/dev-report-<task-id>.json as a 'blocked' canonical
aggregate with an itemized blocking_issues array -- IN ADDITION TO, never
instead of, the stderr diagnostic above -- so downstream /close and /commit
get an auditable record instead of a missing artifact. A write-time
reconciliation step (Layer-Escalation Review, spec-20260904-harness-fixes.md)
additionally ensures this write never silently discards a pre-existing
canonical's own recorded baseline_head_sha or parallel_workers -- any
conflict is preserved and disclosed, never silently overwritten.
"""

import argparse
import hashlib
import importlib.util
import itertools
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

# ---------------------------------------------------------------------------
# Filename patterns — sourced from lib/dev_report_shard_patterns.py, the ONE
# shared module hooks/pretool-aggregate-check.py and
# hooks/posttool-lane-completeness-watch.py also import (ticket
# 20261001-161041-r05 M2; was two hand-mirrored copies, "MUST mirror ...
# exactly" comments on both sides).
#
# Resolved via CLAUDE_PROJECT_DIR / cwd, deliberately NOT __file__: this
# module's source is also exec'd into a bare namespace with no __file__ by
# tests/test_ac_deviation_fanout_consumer.py::bare_aggregator(), and a
# module-top-level __file__ reference there raises NameError (see
# _ledger_contract()'s docstring below for the established precedent this
# follows). Any failure (unresolvable root, import error) falls back to
# byte-identical literal copies so classification behavior never changes.
# ---------------------------------------------------------------------------

try:
    _shard_patterns_root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    if str(_shard_patterns_root) not in sys.path:
        sys.path.insert(0, str(_shard_patterns_root))
    from hooks.lib.dev_report_shard_patterns import (
        PREFIXED_WORKER_RE,
        PREFIXED_CANONICAL_RE,
        PER_WORKER_ROLE_FIRST_RE,
        PER_WORKER_TASK_FIRST_RE,
        CANONICAL_RE,
        NON_WORKER_LABELS,
        NON_WORKER_LABEL_RE,
    )
except Exception:
    # Fallback — MUST mirror hooks/lib/dev_report_shard_patterns.py exactly.
    PREFIXED_WORKER_RE = re.compile(
        r"^dev-report-(?P<task_id>dev-\d{8}-\d{6})-(?P<worker>[A-Za-z0-9][A-Za-z0-9.\-]*)\.json$"
    )
    PREFIXED_CANONICAL_RE = re.compile(
        r"^dev-report-(?P<task_id>dev-\d{8}-\d{6})\.json$"
    )
    PER_WORKER_ROLE_FIRST_RE = re.compile(
        r"^dev-report-(?P<role>[A-Za-z0-9]+)-(?P<task_id>\d{8}-\d{6})\.json$"
    )
    PER_WORKER_TASK_FIRST_RE = re.compile(
        r"^dev-report-(?P<task_id>\d{8}-\d{6})-(?P<worker>[A-Za-z0-9][A-Za-z0-9.\-]*)\.json$"
    )
    CANONICAL_RE = re.compile(
        r"^dev-report-(?P<task_id>\d{8}-\d{6})\.json$"
    )
    NON_WORKER_LABELS = frozenset({
        "draft", "final", "fix", "continuation", "wip",
    })
    NON_WORKER_LABEL_RE = re.compile(
        r"^(?:iter|retry|attempt)\d*$",
        re.IGNORECASE,
    )

# Superseded-round shard, discovered under docs/dev/superseded-<task-id>/ for
# a lane already present in the primary shard set (backlog #99): a QA-FAIL'd
# round-N attempt archived there before a corrective retry was promoted as
# that lane's own top-level shard.
SUPERSEDED_ROUND_RE = re.compile(
    r"^dev-report-(?P<task_id>\d{8}-\d{6})-(?P<lane>[A-Za-z0-9][A-Za-z0-9.\-]*)-round(?P<round>\d+)\.json$"
)

# Strips a superseded-round label's "-round<N>" suffix back to its lane's own
# base label (backlog #99 iteration 1): e.g. "d-round0" -> "d". Used by
# _merge_owned_edits to recognise that a round shard and its lane's own
# promoted shard are the SAME lane, for the same-anchor collapse there.
_ROUND_LABEL_SUFFIX_RE = re.compile(r"-round\d+$")


def _base_lane(label: str) -> str:
    return _ROUND_LABEL_SUFFIX_RE.sub("", label)


# NON_WORKER_LABELS / NON_WORKER_LABEL_RE now sourced above from
# lib.dev_report_shard_patterns (ticket 20261001-161041-r05 M2).

# Optional per-shard declaration that this lane's baseline is the tree its
# predecessor lane left behind (sequential dispatch — spec R28).  Absent from
# every shard, the legacy cross-shard equality invariant applies unchanged.
PROVENANCE_KEY = "baseline_provenance"

# Optional per-shard declaration that this fan-out was dispatched SERIALIZED,
# so its lanes' baselines diverge lawfully along a declared order.  The key,
# its mode, and every rule it must satisfy are OWNED AND ENFORCED by
# scripts/resolve-dev-artifact-chain.py::_adjudicate_serialized_wave; this
# module names the key only so it can recognise a declaration and hand it to
# that one adjudicator (see _retire_serialized_wave_details).  Deliberately
# NOT a second vocabulary for the same fact: one declaration satisfies both
# tools, and a divergence between them could not then be a divergence of
# rules.  Distinct from PROVENANCE_KEY above, whose own narrower rules
# (_validate_baseline_chain) can only express a predecessor that CREATED
# files and have no bearing on a head divergence.
BASELINE_WAVE_KEY = "baseline_wave"

# Shape of a worker label this module's own filename patterns can produce.
# A lane a shard DECLARES for itself is held to the same shape, so declared
# identity can never name a lane the filename grammar could not have named.
# Mirrors resolve-dev-artifact-chain.py::WORKER_RE.
DECLARED_WORKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]*$")

# A `git status --porcelain` line: two status columns, a space, then a path.
PORCELAIN_LINE_RE = re.compile(r"^[ MADRCU?!]{2} \S")

# Count-summary form some dispatch payloads carry instead of porcelain lines,
# e.g. "62 modified/untracked entries at dispatch time".
COUNT_SUMMARY_RE = re.compile(r"^\s*(\d+)\b")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_project_root() -> Path:
    """Derive project root from CLAUDE_PROJECT_DIR env var or script location.

    Never hardcodes an absolute path.
    """
    env_root = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if env_root:
        return Path(env_root)
    # Fall back: this script lives at <project-root>/scripts/aggregate-dev-report.py
    return Path(__file__).resolve().parent.parent


def _resolve_dev_dir(project_root: Path) -> Path:
    return project_root / "docs" / "dev"


def _is_worker_for_task(filename: str, target_bare_tid: str, original_task_id: str) -> tuple[bool, str | None]:
    """Return (is_worker, label) for a filename scoped to the given task.

    target_bare_tid is the YYYYMMDD-HHMMSS portion of original_task_id.
    original_task_id may have a prefix or suffix (e.g. "dev-20260524-170335").

    Shard isolation rule:
    - When original_task_id == target_bare_tid (pure bare timestamp), match
      both role-first and task-first patterns using the bare timestamp.
    - When original_task_id has a suffix beyond the bare timestamp (e.g.
      "20260524-125300-push"), only match task-first shards whose worker
      label cannot be confused with unrelated tasks sharing the bare timestamp.
      Specifically we require the shard's task_id group to equal target_bare_tid
      AND the shard filename to NOT match any bare-timestamp-only canonical name
      that could belong to a different suffixed task.
    - When original_task_id has a prefix (e.g. "dev-20260524-170335"), the
      role-first pattern dev-report-<role>-<bare_tid>.json is still a valid
      shard naming for this task (role acts as prefix), so we allow it.
    """
    # Prefixed canonical must be excluded before legacy role-first matching,
    # where its `dev` prefix would otherwise look like a worker role.
    m_prefixed_canonical = PREFIXED_CANONICAL_RE.match(filename)
    if m_prefixed_canonical is not None:
        return False, None

    m_prefixed_worker = PREFIXED_WORKER_RE.match(filename)
    if m_prefixed_worker is not None:
        if m_prefixed_worker.group("task_id") != original_task_id:
            return False, None
        worker = m_prefixed_worker.group("worker")
        worker_lc = worker.lower()
        if worker_lc in NON_WORKER_LABELS or NON_WORKER_LABEL_RE.match(worker_lc):
            return False, None
        return True, worker

    # Bare canonical must be excluded from worker matches.
    if CANONICAL_RE.match(filename):
        return False, None

    # Role-first: dev-report-<role>-<task-id>.json
    m_role = PER_WORKER_ROLE_FIRST_RE.match(filename)
    if m_role is not None:
        if m_role.group("task_id") != target_bare_tid:
            return False, None
        role = m_role.group("role")
        role_lc = role.lower()
        if role_lc in NON_WORKER_LABELS or NON_WORKER_LABEL_RE.match(role_lc):
            return False, None
        return True, role

    # Task-first: dev-report-<task-id>-<worker>.json
    m_task = PER_WORKER_TASK_FIRST_RE.match(filename)
    if m_task is None:
        return False, None
    if m_task.group("task_id") != target_bare_tid:
        return False, None
    worker = m_task.group("worker")
    worker_lc = worker.lower()
    if worker_lc in NON_WORKER_LABELS:
        return False, None
    if NON_WORKER_LABEL_RE.match(worker_lc):
        return False, None
    # Extra isolation when original_task_id has a suffix:
    # "20260524-125300-push" has suffix "-push"; shards of the plain
    # "20260524-125300" task (e.g. dev-report-20260524-125300-B.json) share
    # the bare timestamp but belong to a different task.  Reject them if the
    # original task_id has a suffix by requiring the worker not to be a
    # single uppercase letter (likely a different parallel task's worker label)
    # — this is a best-effort heuristic.  The recommended fix from codex is to
    # validate the loaded shard's task_id field in _validate_shards, which we do.
    return True, worker


def _self_declared_lane(path: Path, original_task_id: str) -> str | None:
    """Return the lane an artifact's OWN identity fields name, or None.

    Mirrors resolve-dev-artifact-chain.py::_self_declared_identity /
    _self_declared_worker, which is the authority for this rule.  A lane
    identity is exactly ``<task-id>-<worker>``; both identity keys must be
    present, non-blank and agree; and every degenerate shape (unreadable,
    malformed, non-object, absent/blank/non-string key, two contradicting
    keys, an identity naming another task, or the bare parent id with no
    worker) collapses to the single answer None, meaning "not vouched for".
    They collapse so that damaging or omitting one's own identity can never
    buy a weaker verdict than declaring it honestly.

    Read-only and non-raising.  _load_shard() deliberately lets a non-UTF-8
    file raise (UnicodeDecodeError is a ValueError, not an OSError) because
    main()'s own loader must classify that as a load failure and write a
    record; asking a file what lane it belongs to must not be the thing that
    crashes, so the degenerate answer is caught here instead.
    """
    try:
        data = _load_shard(path)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    declared: set[str] = set()
    for key in ("request_id", "task_id"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            return None
        declared.add(value.strip())
    if len(declared) != 1:
        return None
    identity = declared.pop()
    prefix = f"{original_task_id}-"
    if not identity.startswith(prefix):
        return None
    worker = identity[len(prefix) :]
    return worker if DECLARED_WORKER_RE.match(worker) else None


def _attribute_shards_by_identity(
    shards: list[tuple[str, Path]], original_task_id: str
) -> tuple[list[tuple[str, Path]], list[tuple[str, str, str]]]:
    """Settle WHICH lane each scanned shard belongs to from declared identity.

    F-AGG-ASYMMETRY: the filename settles only WHETHER a file is a dev-report
    shard of this task.  WHICH lane it belongs to is settled by the identity
    it declares about itself -- the same rule the resolver's own shard scan
    and _find_undeclared_lane_artifacts already use, and for the reason their
    docstrings give: a lane's fix round is a second report OF that lane
    carrying a distinguishing suffix, and naming a lane after the whole
    suffix invents a worker that never ran.  The question is not which
    revision labels a vocabulary happens to list -- extending that list is
    endless and cannot distinguish "<lane>-<roundlabel>" from a real worker
    -- but what lane the artifact says it belongs to.

    Honouring identity can only MERGE a file into a lane the shard set
    already contains under its own name; it can never create one.  The
    declared lane must be some OTHER shard's filename label, which is that
    lane's own canonically named ``dev-report-<task-id>-<lane>.json`` -- the
    same file the resolver loads as that lane.  So the lane stays represented
    by the report whose name IS the lane, and the suffixed revision is
    attributed to it instead of standing up as an extra worker.

    Fail-closed in every other case, so nothing can be smuggled or lost:
    a shard with no usable self-declaration, or one naming a lane that no
    filename names, keeps its filename label exactly as before.  An artifact
    therefore cannot evade a lane set by blanking its identity, and a lane
    whose only report carries a suffix is still surfaced (under that suffix)
    rather than silently dropped.

    Returns ``(lane_shards, merged)``; ``merged`` is
    ``(filename, filename_label, declared_lane)`` per re-attributed revision,
    so the attribution is observable rather than a silent omission.
    """
    filename_labels = {label for label, _ in shards}
    lane_shards: list[tuple[str, Path]] = []
    merged: list[tuple[str, str, str]] = []
    for label, path in shards:
        declared = _self_declared_lane(path, original_task_id)
        if declared is not None and declared != label and declared in filename_labels:
            merged.append((path.name, label, declared))
            continue
        lane_shards.append((label, path))
    return lane_shards, merged


def _scan_shards(dev_dir: Path, bare_tid: str, original_task_id: str) -> list[tuple[str, Path]]:
    """Return list of (worker_label, shard_path) for task_id in dev_dir."""
    shards = []
    if not dev_dir.is_dir():
        return shards
    try:
        children = list(dev_dir.iterdir())
    except OSError as exc:
        sys.stderr.write(f"aggregate-dev-report: cannot read {dev_dir}: {exc}\n")
        return shards
    for child in children:
        if not child.is_file():
            continue
        is_worker, label = _is_worker_for_task(child.name, bare_tid, original_task_id)
        if is_worker and label is not None:
            shards.append((label, child))
    shards.sort(key=lambda t: t[0])
    return _attribute_shards_by_identity(shards, original_task_id)[0]


def _load_shard(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"aggregate-dev-report: cannot load shard {path}: {exc}\n")
        return None


def _load_shard_with_diagnostic(path: Path) -> tuple[dict | None, str | None]:
    """Load a shard, surfacing the caught exception text for main()'s own use.

    A SEPARATE helper from _load_shard() -- that function's dict|None return
    signature is left completely unchanged because scripts/dev-lifecycle.py:256
    (roster_preview()) is an independent caller that depends on it exactly
    (spec-20260904-harness-fixes.md R29, QA objection 1). This helper is used
    only by main()'s own shard-load loop, which needs the real parse/read
    error text for blocking_issues, not just stderr.

    A syntactically-valid but non-object JSON root (bare list/string/number --
    json.loads does not require an object root) is also classified as a load
    failure, since _build_aggregate's dict-assuming .get()/_union_list calls
    would otherwise crash on it (codex round-3 finding 2).

    A non-UTF-8 shard file (Path.read_text() raises UnicodeDecodeError, a
    ValueError subclass -- NOT an OSError) is also caught here: an uncaught
    UnicodeDecodeError would crash this helper's caller with zero artifact
    written, the exact zero-artifact-on-crash regression R29 exists to close
    (dev-level codex consultation, finding 1, live-reproduced).
    """
    try:
        parsed = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        return None, str(exc)
    if not isinstance(parsed, dict):
        return None, f"shard JSON root is {type(parsed).__name__}, expected an object"
    return parsed, None


def _load_all_shards(
    shards_info: list[tuple[str, Path]]
) -> tuple[list[tuple[str, dict]], list[tuple[str, str]]]:
    """Load every discovered shard, collecting ALL load outcomes instead of
    stopping at the first failure (R29 -- a caller here must not assume >=1
    loaded shard; the all-fail case is possible and must not crash). Shared
    by main()'s >=2-shard load loop and the len(shards_info)<2 skip-branch
    extension (Layer-Escalation Review item F, AC-09), which also needs to
    load whatever 0 or 1 shard(s) it found.
    """
    loaded: list[tuple[str, dict]] = []
    load_failures: list[tuple[str, str]] = []
    for label, path in shards_info:
        data, load_error = _load_shard_with_diagnostic(path)
        if data is None:
            load_failures.append((label, load_error or "unknown load error"))
        else:
            loaded.append((label, data))
    return loaded, load_failures


def _snapshot_entry_count(snapshot: str) -> int | None:
    """Return the number of working-tree entries a snapshot records, else None.

    Two recognised forms: verbatim `git status --porcelain` output (count the
    lines) and the leading-integer count summary some dispatch payloads carry.
    Anything else is uncountable and yields None, which callers treat as
    "cannot corroborate" rather than as "corroborated".
    """
    lines = [ln for ln in (snapshot or "").splitlines() if ln.strip()]
    if lines and all(PORCELAIN_LINE_RE.match(ln) for ln in lines):
        return len(lines)
    m = COUNT_SUMMARY_RE.match(snapshot or "")
    if m is not None:
        return int(m.group(1))
    return None


def _validate_baseline_chain(shards: list[tuple[str, dict]]) -> list[str]:
    """Validate declared sequential baseline provenance; return error strings.

    When lanes target overlapping files the orchestrator must dispatch them
    sequentially, so lane N's baseline is the tree lane N-1 left behind and the
    cross-shard equality invariant is constructionally inapplicable (spec R28).
    A shard may therefore declare where its baseline came from:

        "baseline_provenance": {
            "mode": "sequential",
            "derived_from": "<predecessor worker label>",
            "predecessor_files_created": [...]
        }

    The declaration is NOT a waiver.  The named predecessor must exist among the
    shards, the delta the declaration attributes to it must equal that
    predecessor's OWN recorded dev.files_created, and the two recorded snapshots
    must corroborate the delta -- an empty delta still demands equality, and a
    non-empty delta demands a difference large enough to account for it.
    """
    errors: list[str] = []
    by_label = {label: data for label, data in shards}
    declared = {
        label: data[PROVENANCE_KEY]
        for label, data in shards
        if isinstance(data.get(PROVENANCE_KEY), dict)
    }

    for label, prov in sorted(declared.items()):
        mode = prov.get("mode")
        if mode != "sequential":
            errors.append(
                f"shard '{label}': baseline_provenance.mode {mode!r} is not supported"
                " (expected 'sequential')"
            )
            continue
        pred = str(prov.get("derived_from") or "").strip()
        if not pred:
            errors.append(
                f"shard '{label}': baseline_provenance.derived_from is missing or empty"
            )
            continue
        if pred == label:
            errors.append(
                f"shard '{label}': baseline_provenance.derived_from names itself"
            )
            continue
        if pred not in by_label:
            errors.append(
                f"shard '{label}': baseline_provenance.derived_from {pred!r} is not among"
                f" the shards {sorted(by_label)}"
            )
            continue

        # Correspondence: the declared delta must match what the predecessor
        # itself recorded producing.  Cross-checked against another shard's
        # independently written field, so it cannot be self-asserted.
        pred_dev = by_label[pred].get("dev")
        pred_created = pred_dev.get("files_created") if isinstance(pred_dev, dict) else None
        if not isinstance(pred_created, list):
            errors.append(
                f"shard '{label}': predecessor '{pred}' has no dev.files_created list to"
                " corroborate the declared chain"
            )
            continue
        claimed = prov.get("predecessor_files_created")
        if not isinstance(claimed, list):
            errors.append(
                f"shard '{label}': baseline_provenance.predecessor_files_created must be a list"
            )
            continue
        claimed_set = {str(p) for p in claimed}
        actual_set = {str(p) for p in pred_created}
        if claimed_set != actual_set:
            errors.append(
                f"shard '{label}': baseline_provenance claims predecessor '{pred}' created"
                f" {sorted(claimed_set)} but '{pred}' recorded {sorted(actual_set)}"
            )
            continue

        # Corroboration: the two recorded baselines must reflect that delta.
        own_snap = by_label[label].get("baseline_dirty_snapshot", "")
        pred_snap = by_label[pred].get("baseline_dirty_snapshot", "")
        if not claimed_set:
            if own_snap != pred_snap:
                errors.append(
                    f"shard '{label}': baseline_provenance declares an empty delta from"
                    f" '{pred}' but the two baseline_dirty_snapshot values differ"
                )
            continue
        if own_snap == pred_snap:
            errors.append(
                f"shard '{label}': baseline_provenance declares {len(claimed_set)} file(s)"
                f" created by '{pred}' but the two baseline_dirty_snapshot values are identical"
            )
            continue
        own_n = _snapshot_entry_count(own_snap)
        pred_n = _snapshot_entry_count(pred_snap)
        if own_n is None or pred_n is None:
            uncountable = label if own_n is None else pred
            errors.append(
                f"shard '{label}': baseline_provenance cannot be corroborated because"
                f" baseline_dirty_snapshot for '{uncountable}' is neither porcelain output"
                " nor a leading-count summary"
            )
            continue
        if own_n < pred_n + len(claimed_set):
            errors.append(
                f"shard '{label}': baseline records {own_n} entries but predecessor '{pred}'"
                f" recorded {pred_n} plus {len(claimed_set)} created file(s); the declared"
                " chain does not account for the observed baseline"
            )

    # The chain must root at an undeclared baseline; a cycle roots nowhere.
    cyclic: set[str] = set()
    for start in declared:
        seen: list[str] = []
        cur = start
        while cur in declared:
            if cur in seen:
                cyclic.update(seen[seen.index(cur):])
                break
            seen.append(cur)
            cur = str(declared[cur].get("derived_from") or "").strip()
            if cur not in by_label:
                break
    if cyclic:
        errors.append(
            f"baseline_provenance chain is cyclic among shards {sorted(cyclic)};"
            " no shard roots the chain at an undeclared baseline"
        )

    return errors


_RESOLVER_MODULE_CACHE: list = []  # [module | None], lazy singleton


def _self_as_module() -> ModuleType:
    """This module as an object, for a callee that takes it as a parameter."""
    existing = sys.modules.get(__name__)
    if existing is not None:
        return existing
    # exec'd into a bare namespace (how the resolver loads this file): there
    # is no sys.modules entry, so expose this module's globals as one.
    module = ModuleType(__name__)
    module.__dict__.update(globals())
    return module


def _load_resolver_module() -> ModuleType | None:
    """Load scripts/resolve-dev-artifact-chain.py, or None if unavailable.

    The resolver OWNS the `baseline_wave` route and is its single enforcer.
    Consulting it -- rather than restating its rules here -- is what makes one
    declaration satisfy both tools; a second implementation would be a second
    vocabulary able to drift from the first, which is the failure this is
    written to avoid.

    Loaded exactly the way the resolver loads THIS module (exec'd into a bare
    ModuleType rather than imported into sys.modules), so neither direction
    can create an import cycle: the resolver's module body loads this module
    only inside resolve_chain(), never at module scope.  Cached because that
    body is ~2200 lines.  None on any failure, which the caller turns into a
    refusal to retire anything -- the fail-closed direction.
    """
    if not _RESOLVER_MODULE_CACHE:
        module: ModuleType | None = None
        try:
            path = Path(__file__).with_name("resolve-dev-artifact-chain.py")
            module = ModuleType("_dev_chain_resolver")
            module.__file__ = str(path)
            exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
        except Exception:
            module = None
        _RESOLVER_MODULE_CACHE.append(module)
    return _RESOLVER_MODULE_CACHE[0]


def _retire_serialized_wave_details(
    errors: list[str], shards: list[tuple[str, dict]], project_root: Path | None
) -> list[str]:
    """Adjudicate declared serialized-wave baselines; return the final errors.

    F-AGG-SHARED-ASSUMPTION: the cross-shard baseline-equality invariant in
    _validate_shards encodes an assumption the dispatcher is free not to make
    -- that a fan-out is SIMULTANEOUS.  When lanes edit the same file the
    orchestrator MUST serialize them (dispatching in parallel would create the
    very same-file interleave such a cycle usually exists to fix), and then
    lanes see different dirty trees by construction and a lane dispatched
    after a peer session committed sees a different head.  That set is honest.
    The equality invariant had no route for it here: its head check has no
    provenance exemption at all, and _validate_baseline_chain can express only
    a predecessor that CREATED files, not a head that moved.

    The route already exists and is already enforced -- in the resolver, under
    BASELINE_WAVE_KEY.  This hands the declaration to that one adjudicator,
    which requires the declaration to prove strictly MORE than equality would
    have asked: a real predecessor in the set, the predecessor's own recorded
    head restated, a git-verified ancestor relation between the two heads, a
    working tree that only grows along the chain, a growth figure equal to one
    recomputed from the two recorded snapshots, and that growth itemised
    against evidence another lane or git itself wrote.

    Opt-in and fail-closed.  Without `project_root` -- every pre-existing
    caller, including the resolver, which runs this same adjudication itself,
    and scripts/dev-lifecycle.py -- nothing is adjudicated and `errors` is
    returned unchanged, byte for byte.  With it, a shard set that declares
    nothing is likewise unchanged; a declaration retires ONLY the exact
    divergence detail it named and fully verified; and a defective declaration
    ADDS errors rather than removing any.  The retirable details are matched by
    the adjudicator against this module's own wording, so if that wording ever
    changes nothing matches, nothing is retired, and the invariant blocks
    again.
    """
    if project_root is None:
        return errors
    if not any(isinstance(data.get(BASELINE_WAVE_KEY), dict) for _, data in shards):
        return errors
    resolver = _load_resolver_module()
    if resolver is None:
        return errors + [
            f"{BASELINE_WAVE_KEY} is declared, but its adjudicator "
            "(scripts/resolve-dev-artifact-chain.py) could not be loaded, so no "
            "declared baseline divergence can be verified"
        ]
    retirable, wave_errors = resolver._adjudicate_serialized_wave(
        Path(project_root), shards, _self_as_module()
    )
    return [detail for detail in errors if detail not in retirable] + wave_errors


def _validate_shards(
    shards: list[tuple[str, dict]],
    task_id: str,
    deviation=None,
    project_root: Path | None = None,
) -> list[str]:
    """Return list of validation error strings (empty = all pass).

    `deviation` (harness backlog #92 residual) is the optional provider the
    resolver exposes (`ac_deviation_provider()`); None keeps the behavior below
    byte-identical.  With a provider, a `blocked` shard is accepted exactly
    when the provider's single validator accepts its AC-deviation record, and a
    blocked shard that carries a flag but a defective record gets one extra
    explicit rejection line after today's line.

    Each shard must have:
    - Non-empty task_id or request_id matching the target (bare-timestamp normalized)
    - Non-empty baseline_head_sha (empty string is rejected)
    - Explicit baseline_dirty_snapshot key (may be empty string if clean)
    - dev.status in ('completed', 'needs_review') -- 'needs_review' is a disclosed,
      narrower sibling of 'completed' (ticket 20260911-011232 M5); it is NEVER a
      relaxation of 'blocked', which stays a hard shard-validation failure --
      except, when a deviation provider is passed, for a lane whose AC-deviation
      record its single validator accepts (harness backlog #92 residual).
      Substantive eligibility for the resulting needs_review canonical is decided
      downstream by resolve-dev-artifact-chain.py's reclassification pass, not here.
    - Consistent baseline_head_sha across all shards
    - baseline_dirty_snapshot: when ANY shard's baseline_head_sha disagrees
      with another's, byte-equality is still required for every shard that
      does not declare a baseline_provenance (R28 unchanged) -- a moved head
      is exactly the "stale or foreign tree" signal the equality check exists
      to catch, and BASELINE_WAVE_KEY's WAVE_HEAD_DIMENSION remains the
      sanctioned, verified way to explain it.  When every shard's
      baseline_head_sha agrees, non-declaring shards are NOT required to be
      byte-identical: a same-head concurrent fan-out dispatches lanes at
      different instants into one shared, mutating working tree, and two
      honest lanes can legitimately disagree about which files are dirty in
      either direction (agents/dev.md's own "best-effort, point-in-time...
      not concurrency-complete, by design" semantics) -- not a chain (R28
      remains the fix for sequential, moved-head dispatch) and not
      necessarily a monotonic wave, just incomparable snapshots of a race.
      What is still required of every non-empty, non-declaring shard in this
      case is that its own capture be genuine: a verbatim `git status
      --porcelain` snapshot or a leading-count summary (the same classifier
      the chain/wave routes use for corroboration) -- this is what still
      catches a corrupted or prose-paraphrased snapshot, a defect distinct
      from legitimate drift. Declaring shards remain chain-validated instead
      regardless of head agreement.

    `project_root` opts this call in to the serialized-fan-out route: a lane
    that declares BASELINE_WAVE_KEY and proves its divergence lawful retires
    the specific equality detail it accounted for, and a defective declaration
    adds errors.  Omitted (the default, and every pre-existing caller) nothing
    is adjudicated and the two requirements above are unchanged.  See
    _retire_serialized_wave_details.
    """
    errors = []
    baseline_sha: str | None = None
    baseline_dirty: str | None = None
    provenance_labels = {
        label for label, data in shards
        if isinstance(data.get(PROVENANCE_KEY), dict)
    }
    # Only when every shard's own baseline_head_sha agrees is a same-head
    # concurrent fan-out's baseline_dirty_snapshot divergence structurally
    # distinguishable from the stale/foreign-tree corruption the strict
    # byte-equality check exists to catch (see
    # test_undeclared_divergent_baseline_is_still_rejected, whose fixture
    # moves the head too).  A single non-empty, disagreeing head -- or any
    # shard omitting it -- keeps the strict path, fail-closed.
    non_empty_heads = {
        str(data.get("baseline_head_sha") or "")
        for _, data in shards
        if data.get("baseline_head_sha")
    }
    heads_agree = len(non_empty_heads) <= 1 and len(shards) == sum(
        1 for _, data in shards if data.get("baseline_head_sha")
    )
    m_target = re.search(r"(\d{8}-\d{6})", task_id)
    normalized_target = m_target.group(1) if m_target else task_id
    labels = [label for label, _ in shards]
    duplicate_labels = sorted({label for label in labels if labels.count(label) > 1})
    if duplicate_labels:
        errors.append(f"duplicate worker labels are ambiguous: {duplicate_labels}")

    for label, data in shards:
        # Require non-empty task_id or request_id.
        shard_task_id = (data.get("task_id") or data.get("request_id") or "").strip()
        if not shard_task_id:
            errors.append(
                f"shard '{label}': missing or empty task_id / request_id field"
            )
        else:
            m = re.search(r"(\d{8}-\d{6})", shard_task_id)
            normalized_shard = m.group(1) if m else shard_task_id
            if normalized_shard != normalized_target:
                errors.append(
                    f"shard '{label}': task_id {shard_task_id!r} does not match target {task_id!r}"
                )

        # Check dev.status is 'completed' or the disclosed 'needs_review' sibling
        # (ticket 20260911-011232 M5).  'blocked' (and any other value) stays a
        # hard failure here -- only the resolver's M3 cross-check may later admit
        # a needs_review shard into pass_with_exceptions.
        dev = data.get("dev", {})
        status = dev.get("status") if isinstance(dev, dict) else None
        if status not in ("completed", "needs_review"):
            violations = deviation.violations(data) if deviation is not None else None
            if violations != []:
                errors.append(
                    f"shard '{label}': dev.status is {status!r}, expected 'completed' or 'needs_review'"
                )
                if violations:
                    errors.append(
                        f"shard '{label}': AC-deviation record rejected: "
                        + "; ".join(violations)
                    )

        # Require non-empty baseline_head_sha.
        sha = data.get("baseline_head_sha", "")
        if not sha:
            errors.append(
                f"shard '{label}': baseline_head_sha is missing or empty"
            )
        if baseline_sha is None:
            baseline_sha = sha
        elif sha != baseline_sha:
            errors.append(
                f"shard '{label}': baseline_head_sha {sha!r} != first shard {baseline_sha!r}"
            )

        # Require explicit baseline_dirty_snapshot key (value may be empty string).
        if "baseline_dirty_snapshot" not in data:
            errors.append(
                f"shard '{label}': missing baseline_dirty_snapshot key"
            )
        dirty = data.get("baseline_dirty_snapshot", "")
        # Empty string means the worker did not capture git status (parallel
        # dispatch timing); skip it as a comparison candidate so it does not
        # become the reference value that causes non-empty shards to mismatch.
        # A shard declaring baseline_provenance is neither compared against the
        # reference nor allowed to become it -- its divergence is explained by
        # the chain, which _validate_baseline_chain verifies below.
        if dirty and label not in provenance_labels:
            if heads_agree:
                # Same-head concurrent fan-out: byte-equality is not required
                # (see docstring); only genuineness of the capture is.
                if _snapshot_entry_count(dirty) is None:
                    errors.append(
                        f"shard '{label}': baseline_dirty_snapshot is neither"
                        " verbatim porcelain output nor a leading-count summary"
                    )
            elif baseline_dirty is None:
                baseline_dirty = dirty
            elif dirty != baseline_dirty:
                errors.append(
                    f"shard '{label}': baseline_dirty_snapshot mismatch"
                )

    if provenance_labels:
        errors.extend(_validate_baseline_chain(shards))

    return _retire_serialized_wave_details(errors, shards, project_root)


def _union_list(shards: list[tuple[str, dict]], key_path: list[str]) -> list:
    """Return ordered union of list-typed fields across shards (no dedup by value)."""
    seen_json = set()
    result = []
    for _, data in shards:
        obj = data
        for key in key_path:
            if not isinstance(obj, dict):
                obj = None
                break
            obj = obj.get(key)
        if not isinstance(obj, list):
            continue
        for item in obj:
            item_json = json.dumps(item, sort_keys=True)
            if item_json not in seen_json:
                seen_json.add(item_json)
                result.append(item)
    return result


def _merge_owned_edits(shards: list[tuple[str, dict]]) -> dict:
    """Per-file ordered union of owned-edit hunks across shards (task 20260917-195216).

    Mirrors _union_list's ordered-union/dedup-by-exact-JSON-value convention,
    extended from a plain list field to a dict-of-lists field: shard order is
    _scan_shards' existing alphabetical label sort, which this file's own
    baseline_provenance chain (spec R28) already assumes reflects dispatch
    order (a predecessor label sorts before its successor), so concatenating
    per-file hunk lists in that same order is a documented assumption, not a
    guess. A shard whose owned_edits is not a dict, or a per-file value that
    is not a list, is skipped for that shard/file rather than raising.

    Same-anchor collapse (backlog #99 iteration 1): when
    _expand_shards_with_superseded_rounds feeds a lane's own superseded
    round(s) ahead of its promoted shard, the promoted report is free to
    re-declare a hunk for the SAME `old` anchor a round already declared --
    e.g. a squashed "final authored text of the region" hunk that already
    incorporates the round's own edit plus later revisions (observed on the
    real cycle 20260921-134709's lane a: round0 and promoted both anchor a
    hunk on the identical `old` text, but promoted's `new` text differs and
    carries an extra 'note' key). Exact-JSON-value dedup does not recognise
    these as the same edit, so BOTH would ship, and stage-owned-hunks.py's
    sequential replay then double-applies the same region -- corrupting the
    ledger even though a naive anchor search may still "succeed" (a large
    `new` block can happen to re-embed the anchor text at its own tail).
    Two hunks sharing an `old` anchor can never BOTH be truthfully replayed,
    so only one may survive: within a single lane's OWN fold sequence (its
    round(s), then its own promoted shard -- `_base_lane` strips the
    "-roundN" suffix _expand_shards_with_superseded_rounds adds, to
    recognise this), the LATER declaration wins on CONTENT (it is that
    lane's own final authored state for the region -- verified empirically
    against the real cycle: taking the promoted shard's hunks alone already
    byte-replays the live file), while keeping the EARLIER declaration's
    ledger POSITION so replay order is otherwise unaffected. No information
    is lost by discarding the earlier declaration here: it remains fully
    recoverable from its own archived docs/dev/superseded-<task-id>/ report
    (untouched by this fix); it is excluded only from this replay-facing
    ledger. The winning hunk's own auxiliary metadata (e.g. 'note') is kept
    as-is, since the entry is kept wholesale, not merged field-by-field.
    This collapse is intentionally scoped to a single base lane -- two
    DIFFERENT lanes sharing an `old` anchor (never observed in practice,
    and not this ticket's defect) are NOT collapsed, so ordinary cross-lane
    merges keep their pre-existing exact-JSON-only dedup, unchanged.
    """
    result: dict[str, list] = {}
    seen_json: dict[str, set] = {}
    anchor_index: dict[str, dict[tuple[str, str], int]] = {}
    for label, data in shards:
        owned = data.get("owned_edits")
        if not isinstance(owned, dict):
            continue
        base_lane = _base_lane(label)
        for file_path, hunks in owned.items():
            if not isinstance(hunks, list):
                continue
            bucket = result.setdefault(file_path, [])
            seen = seen_json.setdefault(file_path, set())
            anchors = anchor_index.setdefault(file_path, {})
            for hunk in hunks:
                hunk_json = json.dumps(hunk, sort_keys=True)
                if hunk_json in seen:
                    continue
                old_text = hunk.get("old") if isinstance(hunk, dict) else None
                anchor_key = (base_lane, old_text) if isinstance(old_text, str) else None
                if anchor_key is not None and anchor_key in anchors:
                    idx = anchors[anchor_key]
                    seen.discard(json.dumps(bucket[idx], sort_keys=True))
                    bucket[idx] = hunk
                    seen.add(hunk_json)
                    continue
                seen.add(hunk_json)
                bucket.append(hunk)
                if anchor_key is not None:
                    anchors[anchor_key] = len(bucket) - 1
    return result


def _merge_pre_edit_snapshots(shards: list[tuple[str, dict]]) -> dict:
    """Per-file first-shard-wins scalar across shards (task 20260917-195216).

    Mirrors the existing next(... for _, d in shards) first-shard-wins
    convention already used for baseline_head_sha/baseline_dirty_snapshot:
    once a file's snapshot has been claimed by the earliest shard (in
    _scan_shards' alphabetical order) declaring it, later shards' values for
    that same file are ignored. A shard whose pre_edit_snapshots is not a
    dict is skipped entirely rather than raising.
    """
    result: dict[str, object] = {}
    for _, data in shards:
        snapshots = data.get("pre_edit_snapshots")
        if not isinstance(snapshots, dict):
            continue
        for file_path, snapshot in snapshots.items():
            if file_path not in result:
                result[file_path] = snapshot
    return result


def _scan_superseded_shards(
    dev_dir: Path, bare_tid: str, lanes: set[str]
) -> dict[str, list[tuple[int, Path]]]:
    """Discover per-lane superseded-round shards for lanes already present in
    the primary shard set (backlog #99): scans docs/dev/superseded-<task-id>/
    directories whose own bare timestamp matches bare_tid, for files named
    dev-report-<bare_tid>-<lane>-round<N>.json, restricted to `lanes`.

    Ordering within a lane is derived strictly from the filename's numeric
    round suffix -- never mtime or directory-listing order, per
    commands/dev.md:858's existing "never discovered by mtime" principle. A
    lane with no superseded rounds on disk is simply absent from the result,
    leaving the no-retry case untouched.
    """
    by_lane: dict[str, list[tuple[int, Path]]] = {}
    if not dev_dir.is_dir():
        return by_lane
    try:
        top_level = list(dev_dir.iterdir())
    except OSError:
        return by_lane
    for entry in top_level:
        if not entry.is_dir() or not entry.name.startswith("superseded-"):
            continue
        if _bare_task_id(entry.name[len("superseded-"):]) != bare_tid:
            continue
        try:
            children = list(entry.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_file():
                continue
            m = SUPERSEDED_ROUND_RE.match(child.name)
            if not m or m.group("task_id") != bare_tid:
                continue
            lane = m.group("lane")
            if lane not in lanes:
                continue
            by_lane.setdefault(lane, []).append((int(m.group("round")), child))
    for entries in by_lane.values():
        entries.sort(key=lambda t: t[0])
    return by_lane


def _expand_shards_with_superseded_rounds(
    shards: list[tuple[str, dict]], dev_dir: Path, bare_tid: str
) -> list[tuple[str, dict]]:
    """Fold each lane's superseded-round reports ahead of its own promoted
    shard, for owned_edits/pre_edit_snapshots merge input ONLY (backlog #99).

    A retried lane's promoted report may record only a delta on top of its
    superseded round(s) rather than full re-attribution; without this, the
    round(s)' owned_edits/pre_edit_snapshots entries would be invisible to
    _merge_owned_edits/_merge_pre_edit_snapshots. Callers must use the
    returned list ONLY for that merge -- every OTHER field
    (tasks_completed/files_modified/etc.) keeps using the original `shards`
    unchanged. `shards`' own alphabetical-by-lane order (from _scan_shards)
    is preserved; only each lane's own superseded rounds are inserted
    immediately before that lane's entry, in ascending round order. When no
    lane in `shards` has any superseded round on disk (the ordinary
    no-retry case), this returns `shards` itself, unmodified.
    """
    lanes = {label for label, _ in shards}
    superseded = _scan_superseded_shards(dev_dir, bare_tid, lanes)
    if not superseded:
        return shards
    expanded: list[tuple[str, dict]] = []
    for label, data in shards:
        for round_num, round_path in superseded.get(label, []):
            round_data = _load_shard(round_path)
            if round_data is not None:
                expanded.append((f"{label}-round{round_num}", round_data))
        expanded.append((label, data))
    return expanded


# Ownership-completeness diagnostics (backlog #99 criterion C) travel on THIS
# top-level key and never on `blocking_issues`.
#
# `blocking_issues` is a member of _canonical_projection below, and its built
# value is a pure function of the lane shards (`_union_list(shards,
# ["blocking_issues"])`, the union commands/dev.md:947 documents).
# `_apply_completeness_check` runs only in main(), never in `_build_aggregate`,
# so a diagnostic appended to `blocking_issues` is written into a field whose
# every rebuild recomputes WITHOUT it: the canonical is then judged stale
# against its own rebuild forever, and no number of rebuilds can converge.  One
# real diagnostic text even embeds the subject file's current byte count, so
# that field could not settle even in principle.
#
# The key is deliberately OUTSIDE the projection because a completeness gap is
# a live property of the worktree, not a fact about the lane reports -- the two
# things the projection compares.  That does NOT make a real gap unreportable:
# main() still writes the canonical and still returns 1 on any gap, and
# scripts/resolve-dev-artifact-chain.py RECOMPUTES the gaps through
# `_apply_completeness_check` -- this one implementation, not a second copy --
# and reports them under its own OWNERSHIP_COMPLETENESS_GAP code.  The stored
# value here is an audit record that no gate reads, so a stale or forged record
# can neither suppress a real gap nor manufacture a phantom one.
COMPLETENESS_GAPS_KEY = "ownership_completeness_gaps"

# Same-cycle-only completeness gate (spec-20260914-052140 S5.3 design-
# direction correction, task dev-20260927-135305, seat
# "completeness-gate-rescope"). OWNERSHIP_COMPLETENESS_GAP previously
# required GLOBAL completeness -- every byte of a shared file attributed to
# SOME claimant from ANY cycle -- before THIS cycle's own gate could pass.
# That makes this cycle's close depend on whether some OTHER, possibly
# still-active, session has gotten around to declaring its bytes yet, which
# is the forbidden shape (an unbounded number of concurrent sessions must be
# able to land their own bytes in a shared file; the mere fact a file was
# touched by a peer must never itself trigger a cross-check EXCLUDE)
# restated at the gate layer instead of the file-touch layer. Under an
# unbounded number of concurrently active sessions there is, by
# construction, always a nonzero chance some byte is mid-flight and
# undeclared at the instant anyone checks -- requiring global completeness as
# a precondition for any one cycle's close requires the impossible, forever.
#
# This key holds the narrower, always-answerable question instead: does THIS
# cycle's own set of declared lanes (plus its own non-lane parent_cycle
# claimants, via _cycle_claimant_index -- those are this cycle's own
# declared work too, just not lane-numbered) correctly and non-conflictingly
# account for the bytes its OWN ledgers claim? That question never depends
# on what any other session is doing concurrently. The full, cross-cycle-
# aware computation under COMPLETENESS_GAPS_KEY keeps running UNCHANGED
# (span accounting, the declared-boundary chain, the parent_cycle claimant
# reader, the anti-absorption rule) and stays visible as non-blocking
# forensic information for a human or a later process; only THIS key's
# result drives the gate. See `_completeness_check_file`'s
# `require_full_coverage` parameter and `_apply_completeness_check`'s
# `same_cycle_only` parameter for the mechanism.
OWNERSHIP_COMPLETENESS_BLOCKING_KEY = "ownership_completeness_blocking_gaps"


def _canonical_projection(document: dict, deviation=None) -> dict:
    """Select deterministic aggregate fields; timestamp is intentionally excluded.

    With a provider (`deviation`), the fields it names for this document (the
    AC-deviation flag and record, only when they apply) join the projection so
    a canonical that lost or gained the record compares stale; None keeps the
    eleven baseline keys exactly.
    """
    keys = (
        "request_id",
        "task_id",
        "baseline_head_sha",
        "baseline_dirty_snapshot",
        "dev_report_path",
        "parallel_workers",
        "dev",
        "blocking_issues",
        "recommendations",
        "owned_edits",
        "pre_edit_snapshots",
    )
    projection = {key: document.get(key) for key in keys}
    if deviation is not None:
        projection.update(deviation.projection(document))
    return projection


def _carry_forward_unbuilt_keys(built: dict, canonical_path: Path) -> list[str]:
    """Carry an existing canonical's non-built top-level keys into `built`.

    A regeneration writes the built document WHOLESALE, so before this every
    top-level key a canonical carried that _build_aggregate does not produce
    was destroyed by the next refresh -- including hand-recorded audit history
    such as the correction of a false lane declaration, or the per-entry
    adjudication of blockers that were withdrawn.  Erasing the record of a
    false declaration is its own defect: the declaration's withdrawal is only
    auditable while the premise, the entries it produced, and what withdrew
    them are still readable.

    One condition, no list of blessed key names: a key the builder has no
    opinion about is preserved.  A key the builder DOES produce always wins,
    so nothing stale can survive and no preserved key can alter a freshness
    verdict -- _build_aggregate produces every key _canonical_projection
    compares, so a preserved key is by construction outside the projection and
    can neither mask nor manufacture a STALE_CANONICAL result.

    Unreadable/malformed/non-object existing canonical, or none at all:
    nothing is carried and `built` is untouched.  Returns the keys carried.
    """
    try:
        existing = json.loads(canonical_path.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    if not isinstance(existing, dict):
        return []
    carried = [key for key in existing if key not in built]
    for key in carried:
        built[key] = existing[key]
    return carried


def _atomic_write_json(path: Path, document: dict) -> None:
    """Durably replace path without deleting a stale canonical first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


_HOOK_LEDGER_ENTRY_FIELDS = ("path", "diff_sha256", "reason")


def _ledger_contract():
    """hooks/doc_sync/ledger_contract.py -- the ONE authoritative declaration
    of the ledger layout (M6), which the producer imports too.

    Imported lazily HERE for the same reason _diff_sha256 is (see
    _merge_hook_ledger_into_singular): a module-top-level __file__ reference
    breaks tests/test_ac_deviation_fanout_consumer.py's bare_aggregator()
    helper, which execs this file's source into a namespace with no __file__.
    """
    own_repo_root = Path(__file__).resolve().parent.parent
    if str(own_repo_root) not in sys.path:
        sys.path.insert(0, str(own_repo_root))
    from hooks.doc_sync import ledger_contract
    return ledger_contract


def _hook_ledger_discovery(project_root: Path, task_id: str) -> dict:
    """Which producer directories this task-id may consume, and what the
    AUTHORITY gate rejected (backlog #122 M3a/M3b).

    Replaces a two-name candidate list -- `(task_id, f"dev-{bare_tid}")` --
    whose second element hardcoded the `dev-` dispatch prefix. That list
    could not see a directory minted under any third prefix, and a
    `/dev-command` cycle mints exactly such a name, so five real records sat
    in a directory neither candidate named. Adding `"dev-command-"` beside
    `"dev-"` would only move the blind spot to the next dispatch shape.

    Authority now comes from hook-authored evidence: a registry directory is
    a producer identity only when its co-minted docs/dev/user-requirement-<id>.md
    exists. Selection still matches on the embedded timestamp and is LABELLED
    `binding_provenance: timestamp_inferred` rather than presented as exact --
    the artifact that would make it exact does not exist and is escalated.

    See ledger_contract.select_producers for the full contract; nothing about
    the layout is restated here.
    """
    contract = _ledger_contract()
    return contract.select_producers(project_root, task_id)


def _load_hook_ledger_entries(dir_pairs: list) -> list:
    """[(registry_file, producer_identity, record)] for every readable, well-shaped record.

    Mirrors _load_shard_with_diagnostic's per-entry fail-closed read
    pattern: an unreadable or malformed individual ledger file is skipped,
    never fatal to the whole merge.

    Every record is now retained WITH its own registry file path and the
    identity of the directory it came from, because M8 requires freshness to
    be evaluated per RECORD before any path-level aggregation, and because a
    record excluded later must be nameable: a diagnostic that cannot say
    which file on disk it is talking about is not a diagnostic.
    """
    loaded: list = []
    for ledger_dir, identity in dir_pairs:
        if not ledger_dir.is_dir():
            continue
        try:
            children = sorted(ledger_dir.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_file() or child.suffix != ".json":
                continue
            try:
                parsed = json.loads(child.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeError):
                continue
            if not isinstance(parsed, dict):
                continue
            if not all(
                isinstance(parsed.get(field), str) and parsed.get(field)
                for field in _HOOK_LEDGER_ENTRY_FIELDS
            ):
                continue
            loaded.append((str(child), identity, parsed))
    return loaded


def _hook_ledger_exclusion_warning(exclusion: dict) -> str:
    """One bounded WARNING for one LOSS-class record exclusion.

    Mirrors the field set agents/changelog-analyst.md already emits for the
    identical condition one layer later (find it by the literal 'declared
    files_landed_whole, but the staged diff does not match'), and adds the
    claimant that message lacks -- which is the whole point: a refusal that
    cannot name whose record it dropped cannot name both sides of a contested
    region.
    """
    claimant = exclusion["claimant"]
    recomputed = exclusion["recomputed_diff_sha256"]
    tail = f"recomputed {recomputed}" if recomputed is not None else "the digest could not be recomputed"
    return (
        f"WARNING: excluding {exclusion['path']} -- ledger record "
        f"{exclusion['registry_file']}, declared by task {claimant['task']} "
        f"(agent {claimant['agent'] or 'unrecorded'}, task_provenance "
        f"{claimant['task_provenance']}), is classified {exclusion['class']}: "
        f"declared {exclusion['declared_diff_sha256']}, {tail}. The claimant is retained "
        f"in hook_ledger_exclusions; only its landing declaration is dropped."
    )


def _hook_ledger_unauthorised_warning(dropped: dict) -> str:
    """One bounded WARNING for one DISCOVERY-layer directory exclusion.

    The record count is mandatory in the message. Without it the operator
    learns that something was dropped but not how much -- which is the same
    silent-loss shape, in miniature, that this whole change exists to remove.
    """
    return (
        f"WARNING: excluding producer directory {dropped['directory']} -- identity "
        f"{dropped['identity']!r} is not an authorised producer identity because its "
        f"co-minted {dropped['absent_document']} does not exist, so "
        f"{dropped['records_not_loaded']} record(s) were NOT loaded. "
        f"class={dropped['class']} (unit: directory). The records remain on disk at that "
        f"directory, so their identity is recoverable."
    )


def _emit_hook_ledger_summary(contract, counts: dict, discovery: dict) -> None:
    """Two SEPARATELY LABELLED blocks, because the two classes count different units.

    The record-level block accounts for records excluded AFTER they were
    loaded. The discovery-level block counts DIRECTORIES excluded BEFORE any
    record was loaded. They are never summed, and the discovery-level class
    contributes nothing to the record-level totals -- that separation is what
    keeps the record census meaningful.
    """
    record_line = ", ".join(f"{name}={counts[name]}" for name in contract.RECORD_LEVEL_CLASSES)
    _emit_error(
        f"hook-ledger exclusions [{contract.SUMMARY_BLOCK_RECORD_LEVEL}] (unit: record): {record_line}"
    )
    _emit_error(
        f"hook-ledger exclusions [{contract.SUMMARY_BLOCK_DISCOVERY_LEVEL}] (unit: directory): "
        f"{contract.CLASS_PRODUCER_IDENTITY_UNAUTHORISED}={len(discovery.get('unauthorised') or [])}"
    )
    _emit_error(
        "hook-ledger discovery: "
        f"{contract.BINDING_PROVENANCE_FIELD}={discovery.get(contract.BINDING_PROVENANCE_FIELD)}, "
        f"consumed={discovery.get('consumed')}"
    )


def _merge_hook_ledger_into_singular(
    existing_doc: dict, discovery: dict, project_root: Path
) -> bool:
    """Merge validated hook-ledger entries into existing_doc['files_landed_whole'].

    Backlog #122 M3: additive-only, dedupe by path, never drops a
    pre-existing entry. Mirrors resolve-commit-repos.py:523-535's own
    dual-listing constraint (belt-and-suspenders, not a substitute for it --
    that gate still independently enforces it at admission time): a path
    already claimed by owned_edits or pre_edit_snapshots is never routed
    through files_landed_whole instead.

    Freshness recheck (backlog #122 M4, ticket dev-20260926-044454): a
    ledger entry's diff_sha256 is only ever true AT RECORD TIME -- the path
    may have been edited again since. Before folding a surviving entry in,
    recompute sha256(git diff --no-ext-diff --no-textconv HEAD -- path)
    against project_root using hook_ledger.py's own _diff_sha256 (imported
    directly, not re-derived) and require byte-for-byte equality with the
    recorded value. Any mismatch -- including a None/failed recompute -- is
    rejected on the same fail-closed terms, with NO special-case exemption
    for a recorded sha256("") (a legitimate "no diff existed at record
    time" write-side value per hook_ledger.py::_diff_sha256's own
    docstring, but not exempt from this comparison: recorded-empty vs.
    now-non-empty is a mismatch like any other). This mirrors
    agents/changelog-analyst.md:792-832's own recompute/compare/fail-closed
    pattern for the same files_landed_whole channel at a later point (there
    stage-then-verify against the index, since staging is the operation it
    protects) -- defense-in-depth, not a duplicate of that later check.

    Every excluded record is CLASSIFIED (M4). Three of the four classes are a
    genuine loss and get a bounded per-record WARNING plus a durable entry in
    hook_ledger_exclusions; the fourth, dual_listing_admission, is DELIBERATE
    behaviour (see the mirrored gate named above) and is counted under its own
    label with no warning -- it is the majority class on live data, so warning
    on it would bury the three that matter under correct behaviour.

    Freshness is evaluated for EVERY loaded record BEFORE any path-level
    dedupe (M8). Previously the dedupe ran first, so once one claimant's
    record for a path was folded, a second claimant's record for that path was
    skipped without ever being freshness-checked and without any diagnostic --
    a second silent-loss path invisible to any single-record test.

    Returns True iff THE DOCUMENT WAS MUTATED AT ALL -- an entry was appended
    OR an exclusion was recorded. Widened from "at least one entry was
    appended": a cycle whose records are ALL excluded appends nothing, so
    under the old contract its exclusions would never reach disk, which is
    exactly the both-claimants-stale case this change exists to make durable.
    The byte-for-byte-unchanged-when-empty guarantee is untouched, because
    zero records still yields zero appends AND zero exclusions.
    """
    contract = _ledger_contract()
    dir_pairs = [
        (contract.ledger_dir(project_root, identity), identity)
        for identity in (discovery.get("consumed") or [])
    ]
    loaded = _load_hook_ledger_entries(dir_pairs)
    unauthorised = discovery.get("unauthorised") or []
    binding_provenance = discovery.get(contract.BINDING_PROVENANCE_FIELD)
    counts = {name: 0 for name in contract.RECORD_LEVEL_CLASSES}

    # The discovery layer reports even when nothing was loaded: a gate that
    # silently drops a record-bearing directory is the defect, not the remedy.
    for dropped in unauthorised:
        _emit_error(_hook_ledger_unauthorised_warning(dropped))
    if discovery.get("ambiguous"):
        _emit_error(
            "WARNING: more than one record-bearing minted identity resolves for task-id "
            f"{discovery.get('task_id')!r}: {discovery.get('matched')}. None was consumed -- "
            "choosing between them would be a landing verdict this step does not make."
        )

    if not loaded:
        if unauthorised or discovery.get("ambiguous"):
            _emit_hook_ledger_summary(contract, counts, discovery)
        return False

    # Reuse hook_ledger.py's own _diff_sha256 directly (not a re-derived
    # hashing scheme), imported lazily HERE rather than at module top level --
    # mirrors the scripts/*.py -> hooks.doc_sync.* import precedent already
    # established by scripts/regen-index-dirs.py:18-26. A module-top-level
    # __file__ reference breaks
    # tests/test_ac_deviation_fanout_consumer.py's bare_aggregator() helper,
    # which execs this file's source into a bare namespace with no __file__
    # at all (test_c8_..._bare_namespace__pin); deferring the reference into
    # this function body means it is only evaluated when this function
    # actually runs, which that helper never does.
    own_repo_root = Path(__file__).resolve().parent.parent
    if str(own_repo_root) not in sys.path:
        sys.path.insert(0, str(own_repo_root))
    from hooks.doc_sync.hook_ledger import _diff_sha256 as hook_ledger_diff_sha256

    owned_paths = set(existing_doc.get("owned_edits") or {})
    snapshot_paths = set(existing_doc.get("pre_edit_snapshots") or {})
    existing_landed = existing_doc.get("files_landed_whole")
    if not isinstance(existing_landed, list):
        existing_landed = []
    existing_paths = {item.get("path") for item in existing_landed if isinstance(item, dict)}
    appended = False
    exclusions: list = []
    folded: dict = {}

    def _exclude(failure_class, registry_file, path, claimant, declared, recomputed):
        """Classify, count, warn, and retain durably -- in that order, always together.

        Exclusion from LANDING is permitted; loss of IDENTITY is not. Every
        loss-class record therefore leaves both an ephemeral WARNING an
        operator can see now and a durable hook_ledger_exclusions entry the
        sibling conflict-classification lane can read later without touching
        the registry, stderr, or this process's exit status.
        """
        counts[failure_class] += 1
        exclusion = {
            "registry_file": registry_file,
            "path": path,
            "claimant": claimant,
            "declared_diff_sha256": declared,
            "recomputed_diff_sha256": recomputed,
            "class": failure_class,
            contract.BINDING_PROVENANCE_FIELD: binding_provenance,
        }
        exclusions.append(exclusion)
        _emit_error(_hook_ledger_exclusion_warning(exclusion))

    for registry_file, identity, record in loaded:
        path = record["path"]
        declared = record["diff_sha256"]
        claimant = contract.claimant_of(record, identity)
        if path in owned_paths or path in snapshot_paths or path in existing_paths:
            # DELIBERATE admission behaviour, not loss: counted under its own
            # label, no WARNING, and no hook_ledger_exclusions entry.
            counts[contract.CLASS_DUAL_LISTING_ADMISSION] += 1
            continue
        current_diff_sha256 = hook_ledger_diff_sha256(path, project_root)
        if current_diff_sha256 is None:
            # Distinguishable from a digest that merely DIFFERS: "could not be
            # computed" and "computed to something else" are different facts
            # and an operator needs to tell them apart.
            _exclude(contract.CLASS_RECOMPUTE_FAILURE, registry_file, path, claimant, declared, None)
            continue
        if current_diff_sha256 != declared:
            _exclude(
                contract.CLASS_FRESHNESS_MISMATCH, registry_file, path, claimant,
                declared, current_diff_sha256,
            )
            continue
        already = folded.get(path)
        if already is None:
            entry = {"path": path, "diff_sha256": declared, "reason": record["reason"]}
            existing_landed.append(entry)
            folded[path] = (entry, [claimant])
            appended = True
            continue
        entry, claimants = already
        if entry["diff_sha256"] != declared:
            # Two records for one path that EACH passed freshness against
            # their own recompute -- reachable only when the shared working
            # tree moved between the two recomputes, which is the ordinary
            # condition of this repository. The path-level entry carries ONE
            # digest, so this claimant's declared state cannot be represented
            # in it. It is classified and retained rather than dropped, and no
            # side is picked: choosing a winner is a landing verdict.
            _exclude(
                contract.CLASS_PATH_DEDUPE_SECOND_CLAIMANT, registry_file, path, claimant,
                declared, current_diff_sha256,
            )
            continue
        claimants.append(claimant)

    # ADDITIVE metadata only: `path`, `diff_sha256` and `reason` keep their
    # existing shape and values, path cardinality is unchanged, and nothing
    # below alters entry membership, digest selection, the emitted action or
    # the return code. Grouping collapses two agents of ONE task into ONE
    # claimant, because the claimant unit is the task -- handing the sibling
    # escalation lane a "contested" pair that is one task's two agents would
    # be a fabricated conflict.
    for entry, claimants in folded.values():
        entry["claimants"] = contract.group_claimants(claimants)
    if appended:
        existing_doc["files_landed_whole"] = existing_landed
    if exclusions:
        # ABSENT, not empty, when nothing was excluded by a loss class, so a
        # report with nothing to disclose stays byte-identical to today's.
        existing_doc[contract.EXCLUSIONS_FIELD] = exclusions
    _emit_hook_ledger_summary(contract, counts, discovery)
    return appended or bool(exclusions)


def _synthesize_status_rationale(shards: list[tuple[str, dict]], needs_review_labels: list[str]) -> dict:
    """Aggregate the contributing needs_review shards' own status_rationale.

    Ticket 20260911-011232 M5: lets the canonical's own INVALID_DEV_STATUS
    become reclassifiable by the SAME resolver M3 algorithm as a single lane --
    no special-casing of "the canonical" vs. "a lane" anywhere in the resolver.
    """
    by_label = {label: data for label, data in shards}
    classifications: set[str] = set()
    blocked_by_parts: list[str] = []
    for label in needs_review_labels:
        rationale = by_label[label].get("dev", {}).get("status_rationale")
        if isinstance(rationale, dict):
            classification = rationale.get("classification")
            if isinstance(classification, str) and classification:
                classifications.add(classification)
            blocked_by = rationale.get("blocked_by")
            blocked_by_parts.append(
                f"{label}: {blocked_by}" if blocked_by else f"{label}: (no blocked_by recorded)"
            )
        else:
            blocked_by_parts.append(f"{label}: (no status_rationale recorded)")
    classification = classifications.pop() if len(classifications) == 1 else "other_disclosed_handoff"
    return {
        "classification": classification,
        "blocked_by": "; ".join(blocked_by_parts),
        "forbidden_action": "see per-lane status_rationale in the referenced lane dev-report(s)",
    }


def _build_aggregate(
    shards: list[tuple[str, dict]], task_id: str, deviation=None
) -> dict:
    """Construct the canonical aggregate document from the given shards.

    `deviation` (harness backlog #92 residual) is the optional provider the
    resolver exposes; None keeps every behavior below byte-identical.  With a
    provider, a shard whose AC-deviation record the single validator accepts
    makes the canonical `blocked` (worst-of: blocked > needs_review >
    completed), the provider's merged record is added to the document, and the
    needs_review rationale is synthesized only when the canonical stays
    needs_review.

    On the successful path, called only after _validate_shards passes (all
    shards 'completed' or the disclosed 'needs_review' sibling, consistent
    baseline).  R29 (spec-20260904-harness-fixes.md) also reuses this as the
    base for a 'blocked' aggregate on a shard-load or shard-validation
    mismatch -- in that case `shards` may not have passed _validate_shards
    (may contain a malformed dev field); the caller overrides dev.status to
    'blocked' and pops dev.status_rationale afterward, so entering the
    needs_review-synthesis branch below transiently is harmless -- the final
    written document is what is contracted, not whether this branch was
    entered. `shards` is never duplicate-labeled here: R29's own
    _write_blocked_aggregate deduplicates by label (see
    _dedupe_shards_by_label) before calling this function, so the
    needs_review-correlation logic below -- OWNED BY TICKET 20260911-011232,
    reverted byte-for-byte to that ticket's own original by_label form
    (Revision 9 Decision 1, cross-task-boundary ruling) -- never sees one.

    When any contributing shard declares dev.status == 'needs_review' (ticket
    20260911-011232 M5), the canonical's own dev.status becomes 'needs_review'
    too, with a synthesized dev.status_rationale aggregating the contributing
    shard(s); otherwise dev.status is 'completed' exactly as before.
    """
    # The shard-carried lane_set (when authoritative) restricts ONLY this worker
    # count; every shard below still feeds the status fold and unions.
    worker_ids = [label for label, _ in _partition_roster(shards)[0]]
    now_iso = datetime.now(timezone.utc).isoformat()

    # All shards are guaranteed validated-consistent at this point.
    sha = next((d.get("baseline_head_sha", "") for _, d in shards), "")
    dirty = next((d.get("baseline_dirty_snapshot", "") for _, d in shards), "")

    needs_review_labels = [
        label
        for label, data in shards
        if isinstance(data.get("dev"), dict) and data["dev"].get("status") == "needs_review"
    ]

    has_deviation = deviation is not None and any(
        deviation.violations(data) == [] for _, data in shards
    )
    if has_deviation:
        canonical_status = "blocked"
    else:
        canonical_status = "needs_review" if needs_review_labels else "completed"

    dev_block = {
        "status": canonical_status,
        "tasks_completed": _union_list(shards, ["dev", "tasks_completed"]),
        "scripts_created": _union_list(shards, ["dev", "scripts_created"]),
        "permissions_to_add": _union_list(shards, ["dev", "permissions_to_add"]),
        "files_modified": _union_list(shards, ["dev", "files_modified"]),
        "files_created": _union_list(shards, ["dev", "files_created"]),
        "observed_preexisting": _union_list(shards, ["dev", "observed_preexisting"]),
    }
    if needs_review_labels and not has_deviation:
        dev_block["status_rationale"] = _synthesize_status_rationale(shards, needs_review_labels)

    # backlog #99: fold each lane's superseded-round reports (a QA-FAIL'd
    # attempt archived under docs/dev/superseded-<task-id>/) ahead of that
    # lane's own promoted contribution, for owned_edits/pre_edit_snapshots
    # ONLY -- every other field above still unions the original `shards`.
    # _resolve_project_root()'s __file__ fallback is unavailable when this
    # module is exec()'d into a bare namespace without CLAUDE_PROJECT_DIR set
    # (e.g. tests/test_ac_deviation_record_chain.py's minimal loader) -- fall
    # back to `shards` unchanged rather than crash a caller that never asked
    # for superseded-round discovery in the first place.
    try:
        owned_edit_shards = _expand_shards_with_superseded_rounds(
            shards, _resolve_dev_dir(_resolve_project_root()), _bare_task_id(task_id)
        )
    except NameError:
        owned_edit_shards = shards

    aggregate = {
        "request_id": task_id,
        "task_id": task_id,
        "timestamp": now_iso,
        "baseline_head_sha": sha,
        "baseline_dirty_snapshot": dirty,
        "dev_report_path": f"docs/dev/dev-report-{task_id}.json",
        "parallel_workers": worker_ids,
        "dev": dev_block,
        "blocking_issues": _union_list(shards, ["blocking_issues"]),
        # Emitted EMPTY by the builder on purpose.  The builder never runs the
        # completeness check, so the honest built value is "nothing measured";
        # main() overwrites it with what it actually measured.  Emitting it
        # here is what stops `_carry_forward_unbuilt_keys` from resurrecting a
        # previous run's gap list on any write path that does not re-measure
        # (e.g. `_write_blocked_aggregate`): a key the builder produces always
        # wins over the one the existing canonical carried.
        COMPLETENESS_GAPS_KEY: [],
        # Same reasoning, same key-always-wins mechanism, for the narrower
        # same-cycle-only BLOCKING channel (see OWNERSHIP_COMPLETENESS_
        # BLOCKING_KEY's own comment): the builder never runs this check
        # either, so this stays [] until main() overwrites it with what it
        # actually measured.
        OWNERSHIP_COMPLETENESS_BLOCKING_KEY: [],
        "recommendations": _union_list(shards, ["recommendations"]),
        "owned_edits": _merge_owned_edits(owned_edit_shards),
        "pre_edit_snapshots": _merge_pre_edit_snapshots(owned_edit_shards),
    }
    wave = _baseline_wave_projection(shards)
    if wave is not None:
        aggregate["baseline_wave_projection"] = wave
    if deviation is not None:
        aggregate.update(deviation.merge(shards))
    return aggregate


def _baseline_wave_projection(shards: list[tuple[str, dict]]) -> dict | None:
    """Disclose a serialized fan-out's per-lane baselines, or None.

    The two scalars above are the FIRST shard's.  Under the equality
    invariant that is lossless, which is what lets every downstream pre-edit
    and ownership cross-check resolve every lane's files against them.  Under
    a declared serialized wave the lanes' baselines legitimately differ, so
    those scalars stop being every lane's and a reader -- or a consumer
    resolving a lane's evidence -- would otherwise be silently told that one
    lane's baseline was the whole fan-out's.  That is the falsification this
    block removes: it records what each lane actually recorded, and which
    lane the projected scalars came from.

    Facts only, read straight off the shards: this reports what the lanes
    DECLARE and RECORD, never that a declaration was verified -- verification
    is _retire_serialized_wave_details'/the resolver's to assert, and
    _build_aggregate is also reached with unvalidated shards via
    _write_blocked_aggregate.

    Returns None when no shard declares BASELINE_WAVE_KEY, so a fan-out that
    is simultaneous (every pre-existing cycle) gains no key and every
    document this module writes for one is unchanged.  Not part of
    _canonical_projection, so it can neither mask nor manufacture a freshness
    verdict.
    """
    declaring = sorted(
        label for label, data in shards if isinstance(data.get(BASELINE_WAVE_KEY), dict)
    )
    if not declaring:
        return None
    return {
        "_doc": (
            "This fan-out was dispatched serialized, so its lanes' baselines "
            "diverge along a declared order. baseline_head_sha and "
            "baseline_dirty_snapshot above are the first shard's values and are "
            "NOT every lane's; each lane's own recorded values are below. The "
            "declarations are adjudicated by "
            "scripts/resolve-dev-artifact-chain.py::_adjudicate_serialized_wave "
            f"under the shard key {BASELINE_WAVE_KEY!r}."
        ),
        "projected_from_lane": shards[0][0] if shards else None,
        "declaring_lanes": declaring,
        "per_lane_baseline": {
            label: {
                "baseline_head_sha": data.get("baseline_head_sha", ""),
                "baseline_dirty_snapshot_sha256": hashlib.sha256(
                    (data.get("baseline_dirty_snapshot") or "").encode("utf-8")
                ).hexdigest(),
                "baseline_dirty_snapshot_chars": len(
                    data.get("baseline_dirty_snapshot") or ""
                ),
                "declares_baseline_wave": label in declaring,
                "explains": (
                    data[BASELINE_WAVE_KEY].get("explains")
                    if label in declaring
                    else None
                ),
                "derived_from": (
                    data[BASELINE_WAVE_KEY].get("derived_from")
                    if label in declaring
                    else None
                ),
            }
            for label, data in shards
        },
    }


def _bare_task_id(task_id: str) -> str:
    """Extract YYYYMMDD-HHMMSS portion from a potentially-prefixed task-id."""
    m = re.search(r"(\d{8}-\d{6})", task_id)
    return m.group(1) if m else task_id


def _roster_authority(shards: list[tuple[str, dict]]) -> tuple[list[str] | None, list[str]]:
    """Return (lane_set, conflict_labels) from the shards' own `lane_set`.

    Authority exists iff at least one shard carries a valid lane_set (a
    non-empty list of unique non-blank strings) and EVERY carrier's value is
    valid and verbatim equal.  Otherwise (none / malformed / conflicting) the
    lane_set is None and `conflict_labels` names the carriers when carriers
    exist.  Only the flat docs/dev shards main() loaded are passed in, so a
    shard in a support subdirectory never contributes authority.
    """
    carriers = [(label, data["lane_set"]) for label, data in shards
                if isinstance(data, dict) and "lane_set" in data]
    if not carriers:
        return None, []

    def _valid(value) -> bool:
        return (isinstance(value, list) and bool(value)
                and all(isinstance(x, str) and x.strip() for x in value)
                and len(set(value)) == len(value))

    first = carriers[0][1]
    if all(_valid(v) and v == first for _, v in carriers):
        return list(first), []
    return None, sorted(label for label, _ in carriers)


def _partition_roster(shards: list[tuple[str, dict]]):
    """Split shards into (counted, excluded, conflict_labels) for the roster.

    The roster governs ONLY the worker count (`parallel_workers`); validation,
    the canonical status fold and stdout outcome always use the full set.  A
    shard carrying the lane_set is never excluded.
    """
    lane_set, conflict = _roster_authority(shards)
    if lane_set is None:
        return list(shards), [], conflict
    counted, excluded = [], []
    for label, data in shards:
        if label in lane_set or "lane_set" in data:
            counted.append((label, data))
        else:
            excluded.append((label, data))
    return counted, excluded, conflict


def _shard_status(data) -> str | None:
    dev = data.get("dev") if isinstance(data, dict) else None
    status = dev.get("status") if isinstance(dev, dict) else None
    return status if isinstance(status, str) else None


def _outcome_fields(dev_status, loaded: list[tuple[str, dict]], shards_info) -> dict:
    """Additive stdout fields reporting the canonical outcome truthfully."""
    fields: dict = {}
    if isinstance(dev_status, str):
        fields["dev_status"] = dev_status
    needs_review = sorted(l for l, d in loaded if _shard_status(d) == "needs_review")
    if needs_review:
        fields["needs_review_lanes"] = needs_review
    _, excluded, conflict = _partition_roster(loaded)
    files = {label: path.name for label, path in shards_info}
    if excluded:
        fields["excluded_non_lane_reports"] = [
            {"file": files.get(l), "label": l, "declared_status": _shard_status(d)}
            for l, d in excluded
        ]
        nr_reports = [{"file": files.get(l), "label": l}
                      for l, d in excluded if _shard_status(d) == "needs_review"]
        if nr_reports:
            fields["needs_review_reports"] = nr_reports
    if conflict:
        fields["lane_set_conflict"] = conflict
    return fields


def _emit_ok(action: str, output_path: str, reason: str, extra: dict | None = None) -> None:
    payload = {
        "status": "ok",
        "action": action,
        "output_path": output_path,
        "reason": reason,
    }
    if extra:
        if extra.get("dev_status") == "needs_review":
            payload["reason"] = (
                f"{reason} Canonical dev.status is needs_review"
                f" (lanes: {extra.get('needs_review_lanes', [])})."
            )
        payload.update(extra)
    print(json.dumps(payload))


def _emit_error(reason: str) -> None:
    sys.stderr.write(f"aggregate-dev-report: {reason}\n")


_DEVIATION_PROVIDER_CACHE: list = []


def _load_deviation_provider():
    """The AC-deviation provider of the resolver next to this script, or None.

    The resolver owns the ONE definition of the deviation record's shape and
    exposes it through `ac_deviation_provider()`.  It is loaded lazily and only
    by `main` (the resolver loads this module inside `resolve_chain`, so an
    import here would be a cycle), by executing the resolver source located
    next to this file -- the mirror of the resolver's own loader -- and cached
    for the process.  FAILS CLOSED: when the source is absent, cannot be
    executed or exposes no provider, exactly one stderr line names the loss and
    None is returned, so the caller keeps the baseline behavior (a blocked lane
    is rejected) and never releases a lane on a guess.
    """
    if _DEVIATION_PROVIDER_CACHE:
        return _DEVIATION_PROVIDER_CACHE[0]
    try:
        path = Path(__file__).with_name("resolve-dev-artifact-chain.py")
        module = ModuleType("_dev_resolver_provider")
        module.__file__ = str(path)
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
        provider = module.ac_deviation_provider()
    except Exception as exc:
        _emit_error("AC-deviation provider unavailable: " + " ".join(str(exc).split()))
        provider = None
    _DEVIATION_PROVIDER_CACHE.append(provider)
    return provider


def _has_blocked_shard(shards: list[tuple[str, dict]]) -> bool:
    """Whether any shard reports dev.status == 'blocked' (the only shards the
    deviation provider can affect)."""
    return any(
        isinstance(data.get("dev"), dict) and data["dev"].get("status") == "blocked"
        for _, data in shards
    )


def _is_str_list(value) -> bool:
    """True iff value is a list whose every element is a str.

    Layer-Escalation Review item G: baseline_head_sha/parallel_workers are
    validated and reconciled INDEPENDENTLY of each other -- a wrong-typed
    roster must never block a valid sha's reconciliation, and vice versa
    (AC-09, QA BA-validation-escalation objection 4).
    """
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _dedupe_shards_by_label(loaded: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """Deduplicate loaded shards by label -- for use ONLY as the argument
    passed into _build_aggregate from _write_blocked_aggregate (R29,
    Revision 9 Decision 1, cross-task-boundary ruling).

    _build_aggregate's needs_review-correlation logic (_synthesize_status_
    rationale's by_label dict) is owned by ticket 20260911-011232 and has
    been reverted to that ticket's own original form, which resolves a
    duplicate label via last-write-wins independent of which shard actually
    matched as needs_review -- crashing with an unhandled AttributeError if
    the OTHER duplicate's dev field is malformed. Rather than touch 011232's
    owned code, R29 removes the ambiguity BEFORE _build_aggregate ever runs.

    Deterministic, content-based tie-break: if exactly one of a label's
    duplicates has a well-formed dict `dev` field, keep that one; otherwise
    (all well-formed, or all malformed) keep the first shard in scan order.

    Every OTHER computation in _write_blocked_aggregate (the sha-unanimity
    candidate, the write-time roster/sha reconciliation, mismatch_entries)
    continues to operate on the ORIGINAL, non-deduplicated `loaded`/
    `full_roster` -- those already have their own duplicate-safe multiset
    semantics and must not have a duplicate label silently collapsed before
    they run. The duplicate-label fact itself is independently disclosed via
    _validate_shards' own blocking_issues entry, computed on the original,
    non-deduplicated list.
    """
    by_label: dict[str, list[tuple[str, dict]]] = {}
    order: list[str] = []
    for label, data in loaded:
        if label not in by_label:
            order.append(label)
        by_label.setdefault(label, []).append((label, data))

    deduped: list[tuple[str, dict]] = []
    for label in order:
        entries = by_label[label]
        if len(entries) == 1:
            deduped.append(entries[0])
            continue
        well_formed = [entry for entry in entries if isinstance(entry[1].get("dev"), dict)]
        deduped.append(well_formed[0] if len(well_formed) == 1 else entries[0])
    return deduped


def _current_run_candidate_sha(loaded: list[tuple[str, dict]]) -> str:
    """Candidate baseline_head_sha for a blocked aggregate, computed ONLY
    from the CURRENT run's own successfully-loaded shards -- never from an
    existing canonical, and never an arbitrary "first shard" pick.

    Layer-Escalation Review item D: '' unless every shard reporting a
    non-empty value agrees on the SAME one (closes codex round-6 finding 3 --
    _build_aggregate's own next(...) first-loaded-shard pick is a naive
    selection, not a unanimity check, and could silently prefer one shard's
    value over a disagreeing sibling's).
    """
    shas = {data.get("baseline_head_sha", "") for _, data in loaded}
    non_empty = {sha for sha in shas if sha}
    if len(non_empty) == 1:
        return next(iter(non_empty))
    return ""


def _reconcile_write_time(
    canonical_path: Path,
    candidate_sha: str,
    current_full_roster: list[str],
) -> tuple[str, list[str], list[str]]:
    """Reconcile the current run's own write-time candidates against
    whatever a pre-existing canonical at canonical_path already recorded, so
    a mismatch write (or the len(shards_info)<2 skip-branch extension) never
    silently discards prior sha/roster evidence (Layer-Escalation Review,
    items B'/E/G; AC-09).

    Returns (final_sha, final_roster, disclosure_entries). sha and roster
    reconcile INDEPENDENTLY of each other (item G, QA BA-validation-
    escalation objection 4): a malformed baseline_head_sha field never blocks
    a valid parallel_workers field from reconciling normally, and vice
    versa. On any full-document read failure (unreadable, non-UTF-8, or a
    non-dict JSON root), BOTH fields fail closed together, since neither can
    be independently examined.

    No existing canonical at all (first-ever write for this task-id) means
    nothing to reconcile against -- the current run's own candidates are
    written as-is.
    """
    disclosures: list[str] = []
    if not canonical_path.exists():
        return candidate_sha, sorted(current_full_roster), disclosures

    existing, read_error = _load_shard_with_diagnostic(canonical_path)
    if existing is None:
        # Full-document read failure -- neither field can be independently
        # examined. Fail closed on sha (never the current run's own
        # candidate: a real successful run's candidate is always non-empty
        # per _validate_shards' existing non-empty-sha requirement, so ''
        # can never accidentally satisfy a future legitimate recovery);
        # best-effort fall back to the current scan alone for the roster.
        disclosures.append(
            f"existing canonical {canonical_path} could not be read for write-time "
            f"reconciliation ({read_error}); baseline_head_sha forced to '' "
            "(fail-closed) and parallel_workers falls back to the current scan alone"
        )
        return "", sorted(current_full_roster), disclosures

    existing_sha_raw = existing.get("baseline_head_sha", "")
    if isinstance(existing_sha_raw, str):
        if existing_sha_raw != candidate_sha:
            final_sha = existing_sha_raw
            disclosures.append(
                f"existing canonical's baseline_head_sha {existing_sha_raw!r} conflicts "
                f"with this run's candidate {candidate_sha!r}; the existing value is "
                "preserved -- manual reconciliation required"
            )
        else:
            final_sha = candidate_sha
    else:
        final_sha = ""
        disclosures.append(
            f"existing canonical's baseline_head_sha is {type(existing_sha_raw).__name__}, "
            "not a string; unusable for write-time reconciliation -- forced to '' (fail-closed)"
        )

    existing_roster_raw = existing.get("parallel_workers", [])
    if _is_str_list(existing_roster_raw):
        existing_counter = Counter(existing_roster_raw)
        current_counter = Counter(current_full_roster)
        final_roster = sorted((existing_counter | current_counter).elements())
        missing = existing_counter - current_counter
        for label, count in sorted(missing.items()):
            disclosures.append(
                f"shard '{label}': existing canonical's parallel_workers records "
                f"{count} occurrence(s) no longer found in the current scan"
            )
    else:
        final_roster = sorted(current_full_roster)
        disclosures.append(
            "existing canonical's parallel_workers is not a list of strings; unusable "
            "for write-time reconciliation -- falls back to the current scan alone"
        )

    return final_sha, final_roster, disclosures


def _write_blocked_aggregate(
    loaded: list[tuple[str, dict]],
    task_id: str,
    full_roster: list[str],
    mismatch_entries: list[str],
    canonical_path: Path,
    dry_run: bool,
) -> int:
    """Write a 'blocked' canonical aggregate on a shard-mismatch, per
    commands/dev.md Step 11's construction rule (spec-20260904-harness-fixes.md
    R29) -- so downstream /close and /commit get an itemized, auditable
    record instead of a missing artifact when a shard-load or
    shard-validation mismatch is detected, or when the len(shards_info)<2
    skip branch is extended (Layer-Escalation Review item F, AC-09). Always
    returns 1 (the mismatch exit code is unchanged; this only adds the write
    as a side effect).

    Reuses the EXISTING _build_aggregate(loaded, task_id) directly as the
    base -- not a bespoke helper that re-derives the union logic -- so all 8
    of its unioned fields (blocking_issues plus its 7 siblings per
    commands/dev.md:883-893) carry forward from every successfully-loaded
    shard by construction. `loaded` is deduplicated by label (see
    _dedupe_shards_by_label) for THIS call only; every other computation
    below operates on the ORIGINAL, non-deduplicated `loaded`/`full_roster`.

    Exactly 5 fields are then overridden: dev.status, dev.status_rationale
    (popped), blocking_issues (union + appended mismatch/reconciliation
    entries), baseline_head_sha, and parallel_workers -- the last two via the
    write-time reconciliation (items A/D/B'/E/G, Layer-Escalation Review)
    that preserves a pre-existing canonical's own recorded evidence rather
    than silently discarding it. No sha-provenance heuristic marker is
    written or read anywhere (item A -- `_classify_sha_provenance`/
    `_sha_provenance` are deleted entirely; recovery from a genuine sha
    conflict is manual, for every predecessor status, exactly as it already
    was for 'completed'/'needs_review').

    --dry-run preserves the existing 'validate only, never write' contract,
    whether or not a canonical already exists at canonical_path.
    """
    if dry_run:
        return 1
    aggregate = _build_aggregate(_dedupe_shards_by_label(loaded), task_id)
    aggregate["dev"]["status"] = "blocked"
    aggregate["dev"].pop("status_rationale", None)

    candidate_sha = _current_run_candidate_sha(loaded)
    final_sha, final_roster, reconciliation_entries = _reconcile_write_time(
        canonical_path, candidate_sha, full_roster
    )
    aggregate["baseline_head_sha"] = final_sha
    aggregate["parallel_workers"] = final_roster
    aggregate["blocking_issues"] = (
        aggregate["blocking_issues"] + list(mismatch_entries) + reconciliation_entries
    )
    _carry_forward_unbuilt_keys(aggregate, canonical_path)
    try:
        _atomic_write_json(canonical_path, aggregate)
    except OSError as exc:
        _emit_error(f"Cannot write blocked canonical aggregate to {canonical_path}: {exc}")
    return 1


# ---------------------------------------------------------------------------
# Shrink-handling (ticket-20260930-132644-l8 Part C1): a shard-roster shrink
# must never hard-exit without first WRITING a canonical record. Either
# every missing label has a terminal trace on disk (reaggregate the shards
# actually found, annotated `shrunk_from`) or it does not (fall back to the
# existing, already-correct `_write_blocked_aggregate` naming the missing
# labels) -- see Edge Case 4 (the aggregator's shrink bug is TWO separate
# branches in main(), both fixed identically via this shared helper).
# ---------------------------------------------------------------------------

_ITER_SHARD_RE = re.compile(
    r"^dev-report-iter\d+-(?P<task_id>[A-Za-z0-9][A-Za-z0-9.\-]*)-(?P<worker>[A-Za-z0-9][A-Za-z0-9.\-]*)\.json$"
)

_TERMINAL_DEV_STATUSES = frozenset({"completed", "blocked", "needs_review"})


def _label_has_terminal_trace(
    dev_dir: Path, bare_tid: str, original_task_id: str, label: str, existing_doc: dict | None,
) -> bool:
    """A missing shard label counts as having a 'terminal trace' when EITHER
    (a) some on-disk file for this task-id and label -- a normal shard OR an
    iterN- archival variant (commands/dev.md:1275, deliberately excluded
    from _scan_shards per trap 9) -- parses with dev.status in
    {completed,blocked,needs_review}, OR (b) the EXISTING canonical's own
    blocking_issues/disclosure text already names this label. No exact
    file-format is pinned by the design docs for case (a) beyond the
    existing worker-shard patterns plus the iterN- convention; this is a
    deliberately permissive ANY-match check (never a strict schema gate) --
    the point is to avoid discarding real evidence that happens to sit
    outside the current scan's own narrow shard-roster window.
    """
    if existing_doc is not None:
        # All three disclosure channels, not just `blocking_issues`.
        # Completeness diagnostics moved to COMPLETENESS_GAPS_KEY and they
        # routinely name a lane label ("[snapshot=r02 order=r02]"), so reading
        # only `blocking_issues` here would have silently NARROWED this
        # deliberately-permissive evidence scan the moment the channel changed
        # -- discarding exactly the real evidence the docstring says must not
        # be discarded. OWNERSHIP_COMPLETENESS_BLOCKING_KEY joined the same
        # way when the gate was rescoped to same-cycle-only (task
        # dev-20260927-135305): a lane label can now appear there instead of
        # (or as well as) COMPLETENESS_GAPS_KEY.
        for key in ("blocking_issues", COMPLETENESS_GAPS_KEY, OWNERSHIP_COMPLETENESS_BLOCKING_KEY):
            disclosures = existing_doc.get(key)
            if isinstance(disclosures, list):
                for item in disclosures:
                    if isinstance(item, str) and label in item:
                        return True
    if not dev_dir.is_dir():
        return False
    try:
        children = list(dev_dir.iterdir())
    except OSError:
        return False
    for child in children:
        if not child.is_file():
            continue
        name = child.name
        is_worker, found_label = _is_worker_for_task(name, bare_tid, original_task_id)
        is_match = is_worker and found_label == label
        if not is_match:
            m_iter = _ITER_SHARD_RE.match(name)
            if (
                m_iter is not None
                and m_iter.group("worker") == label
                and (bare_tid in m_iter.group("task_id") or original_task_id in m_iter.group("task_id"))
            ):
                is_match = True
        if not is_match:
            continue
        doc, _ = _load_shard_with_diagnostic(child)
        if not isinstance(doc, dict):
            continue
        dev_obj = doc.get("dev")
        status = dev_obj.get("status") if isinstance(dev_obj, dict) else None
        if status in _TERMINAL_DEV_STATUSES:
            return True
    return False


def _all_missing_labels_have_terminal_trace(
    dev_dir: Path, bare_tid: str, original_task_id: str, missing_labels: list[str],
    existing_doc: dict | None,
) -> bool:
    if not missing_labels:
        return False
    return all(
        _label_has_terminal_trace(dev_dir, bare_tid, original_task_id, label, existing_doc)
        for label in missing_labels
    )


def _reaggregate_with_shrunk_from_or_block(
    loaded: list[tuple[str, dict]],
    task_id: str,
    full_roster: list[str],
    missing_labels: list[str],
    mismatch_entries: list[str],
    canonical_path: Path,
    dry_run: bool,
    dev_dir: Path,
    bare_tid: str,
    deviation,
    existing_doc: dict | None,
) -> int:
    """Shared Part-C1 decision (AC9/AC10): when EVERY missing label has a
    terminal trace, reaggregate from the shards actually loaded and
    annotate `shrunk_from`; otherwise fall back to the existing, unchanged
    `_write_blocked_aggregate` naming the missing labels. Either way a
    canonical record is written before any nonzero return -- never a hard
    exit with nothing written (M5).
    """
    if dry_run:
        return 1
    if _all_missing_labels_have_terminal_trace(dev_dir, bare_tid, task_id, missing_labels, existing_doc):
        aggregate = _build_aggregate(_dedupe_shards_by_label(loaded), task_id, deviation=deviation)
        aggregate["shrunk_from"] = missing_labels
        _carry_forward_unbuilt_keys(aggregate, canonical_path)
        try:
            _atomic_write_json(canonical_path, aggregate)
        except OSError as exc:
            _emit_error(f"Cannot write canonical aggregate at {canonical_path}: {exc}")
            return 1
        _emit_ok(
            action="aggregated",
            output_path=str(canonical_path),
            reason=(
                f"Reaggregated from {len(loaded)} current shard(s) for task-id "
                f"{task_id!r}; shrunk_from {missing_labels} (terminal trace "
                "confirmed for each missing label)."
            ),
            extra=_outcome_fields(
                aggregate["dev"]["status"], loaded,
                _scan_shards(dev_dir, bare_tid, task_id),
            ),
        )
        return 0
    return _write_blocked_aggregate(
        loaded, task_id, full_roster, mismatch_entries, canonical_path, dry_run
    )


_BLOB_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _git(project_root: Path, args: list[str]) -> tuple[int, bytes, bytes]:
    """Run a read-only git command scoped to project_root; return (rc, stdout,
    stderr). Used only by the backlog #99 criterion-C completeness check
    (ls-files/cat-file/show only -- never mutates the index or worktree)."""
    proc = subprocess.run(
        ["git", "-C", str(project_root)] + args,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _resolve_baseline_snapshot(
    project_root: Path, baseline_head_sha: str, rel: str, declared_value
) -> tuple[bytes | None, str]:
    """Resolve the TRUE pre-cycle snapshot bytes of rel for the criterion-C
    completeness check ONLY -- never mutates the aggregate's own
    pre_edit_snapshots field, which _merge_pre_edit_snapshots computes
    unchanged (backlog #99 Edge Case 2: the first-shard-wins declared value
    can silently be wrong when the alphabetically-first lane is not the
    chronologically-first editor).

    Resolution order (task 20260930-132644, superseding AC-7's unconditional
    HEAD-first order): (1) `git cat-file blob <declared_value>` when
    declared_value is a resolvable 40-hex object (a git-blob-SHA-form
    declaration) AND its content differs from -- or HEAD cannot resolve rel
    at all -- `git show <baseline_head_sha>:rel`. A blob-SHA-form
    declaration is independently verified by git's own content-addressed
    object store, and it is the ONLY evidence that can correctly reflect a
    file that was ALREADY DIRTY (uncommitted changes from a prior session or
    a concurrent sibling lane) before this cycle's capture ran -- in that
    case baseline_head_sha names the last CLEAN commit, which is not a valid
    stand-in for "this file's content at the moment this lane began editing
    it". (2) `git show <baseline_head_sha>:rel` when rel is tracked at that
    commit -- used whenever the declared blob is absent, unresolvable, or
    itself byte-identical to HEAD (i.e. there is no better evidence than
    HEAD). (3) declared_value treated as literal pre-edit bytes (a
    literal-text-form declaration is NEVER independently verifiable -- AC-7
    deliberately protects against trusting an inaccurate literal-text
    first-shard-wins declaration over HEAD -- so it stays the lowest-
    priority fallback, exactly as before this fix).

    Already-resolved `bytes` pass straight through.  That is an IN-PROCESS
    channel only -- `pre_edit_snapshots` is parsed from JSON, which can never
    produce `bytes` -- used by `_evidenced_claimant_candidates`, which has
    already resolved and verified a non-lane claimant's snapshot against that
    claimant's OWN declared object.  Re-resolving it here against this cycle's
    baseline_head_sha could only substitute HEAD's bytes (via the AC-7
    literal-text downgrade below) for a start that was already verified.
    """
    if isinstance(declared_value, bytes):
        return declared_value, "pre_resolved_snapshot"

    declared_blob: bytes | None = None
    if isinstance(declared_value, str) and _BLOB_SHA_RE.match(declared_value):
        rc, _, _ = _git(project_root, ["cat-file", "-e", declared_value])
        if rc == 0:
            rc2, blob, _ = _git(project_root, ["cat-file", "blob", declared_value])
            if rc2 == 0:
                declared_blob = blob

    head_blob: bytes | None = None
    if baseline_head_sha:
        rc, _, _ = _git(project_root, ["cat-file", "-e", f"{baseline_head_sha}:{rel}"])
        if rc == 0:
            rc2, blob, _ = _git(project_root, ["show", f"{baseline_head_sha}:{rel}"])
            if rc2 == 0:
                head_blob = blob

    if declared_blob is not None and (head_blob is None or declared_blob != head_blob):
        return declared_blob, "declared_blob_sha"
    if head_blob is not None:
        return head_blob, "baseline_head_sha"
    if isinstance(declared_value, str):
        return declared_value.encode("utf-8"), "literal_text"
    return None, "no resolvable pre-edit snapshot declared for this file"


_STAGE_OWNED_HUNKS_CACHE: list = []  # [(replay_with_provenance, OwnedLandingRefusal)], lazy singleton

# Bounded combinatorial guard (ticket 20261001-close-multilane-stall Edge
# Cases & Risks, re-measured 2026-10-02 task 20261001-161041-guard-fix):
# below this count, full N! x N exhaustive permutation (today's historical
# behavior) stays cheap and is kept verbatim. At/above it, measured directly
# against this task's own real 6-lane file (hooks/tests/test_artifact_
# contract_enforce.py) via the production _completeness_check_file: the
# isolated single-file exhaustive search alone exceeded 120s and the full
# 21-lane aggregate run exceeded 16m47s -- both far past "a few seconds" for
# a one-time aggregation step, and neither run even found a match (see
# _chain_bounded_orderings below for why: one declaring lane's ledger entry
# had an empty `old` string, which stage-owned-hunks.py's replay primitive
# refuses unconditionally, so every permutation containing it fails only
# after however much OTHER work that ordering did first). Raising this
# constant alone is therefore not a safe fix at N=6; above this bound, the
# search is handed to the chain-aware algorithm instead, which only widens
# to a brute-force-shaped branch at a single ambiguous step, bounded by
# this same constant applied there instead of to the whole lane count.
_MAX_COMPLETENESS_CANDIDATE_LANES = 4

# Hard ceiling on total chain-search recursive calls (_chain_bounded_orderings),
# independent of the per-step branch bound above -- a backstop so several
# small per-step ambiguities along a long chain cannot still compound into a
# blowup. 500 is generous: a well-formed chain (the common case this exists
# for) resolves in O(lane count) nodes with no branching at all; this only
# matters when ambiguity recurs across multiple steps.
_MAX_COMPLETENESS_CHAIN_NODES = 500

# Sub-lane (individual-hunk) search bounds, for _chain_bounded_hunk_orderings
# -- a SEPARATE, wider pair from the two constants above because the common
# first step of a hunk-level search legitimately has more simultaneously-
# viable candidates than a lane-block search ever does: at the hunk
# granularity, every declaring lane's FIRST hunk can be independently
# anchor-viable at once (nothing has landed yet to disambiguate them), so a
# branch cap as tight as _MAX_COMPLETENESS_CANDIDATE_LANES (4) would reject
# the very first step on this task's own motivating file (task
# 20261001-161041-interleave-fix, hooks/tests/test_artifact_contract_enforce.py,
# 6 declaring lanes) before it could explore anything. 6 was measured
# sufficient there (peak simultaneous viable-candidate count observed: 5).
# Node cost is dominated by `_load_stage_owned_hunks_replay`'s replay
# primitive (an alignment computation, not a cheap string op), so this is
# bounded far below a lane-count-factorial blowup: measured end-to-end on
# that same file (6 lanes, 10 hunks, one genuinely-required reverse-of-
# declared-order step), with memoization on (accumulated-bytes, remaining-
# hunks) collapsing the redundant exploration a commutative hunk prefix
# would otherwise repeat, the correct answer resolved in 416 nodes / 112s
# for the single worst (wrong) starting candidate tried, and the correct
# starting candidate resolved in under 7s -- both comfortably inside this
# ceiling, and a hard ceiling rather than an unbounded search either way.
_MAX_COMPLETENESS_HUNK_BRANCH = 6
_MAX_COMPLETENESS_HUNK_CHAIN_NODES = 1000


def _load_stage_owned_hunks_replay():
    """Import scripts/stage-owned-hunks.py and return its ENTRY-side replay
    primitives, following scripts/check-owned-edits-ledger.py:127-165's exact
    file-location import pattern -- never invoking main()/the --dry-run CLI,
    so the irrelevant BASELINE-side ownership-conflict probe (the false-
    positive source, task 20261001-close-multilane-stall) is never reached.

    Behavioral-binding assertion (S2, this ticket's Volatility Dependency
    Analysis): stage-owned-hunks.py is volatile from unrelated concurrent
    activity, and `_replay_with_provenance` is an internal (underscore-
    prefixed) symbol. Asserting the symbols merely EXIST would not catch a
    semantic drift, so a trivial single-entry replay with a uniquely-anchored
    `old` is checked against its expected output every time this is loaded;
    a mismatch raises loudly rather than trusting a possibly-wrong verdict.
    """
    if _STAGE_OWNED_HUNKS_CACHE:
        return _STAGE_OWNED_HUNKS_CACHE[0]
    consumer = Path(__file__).resolve().with_name("stage-owned-hunks.py")
    if not consumer.is_file():
        raise RuntimeError(
            "consumer not found at %s; the completeness check cannot verify "
            "without it" % consumer
        )
    spec = importlib.util.spec_from_file_location("stage_owned_hunks", consumer)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # import-time failure is environmental, not a verdict
        raise RuntimeError(
            "cannot import consumer %s: %s: %s" % (consumer, type(exc).__name__, exc)
        )
    missing = [name for name in ("_replay_with_provenance", "OwnedLandingRefusal")
               if not hasattr(module, name)]
    if missing:
        raise RuntimeError(
            "consumer %s no longer exports %s -- it has been refactored "
            "underneath this checker; re-derive before trusting any verdict"
            % (consumer, ", ".join(missing))
        )
    replay = module._replay_with_provenance
    refusal = module.OwnedLandingRefusal
    probe_bytes, _, _ = replay(b"S-O-H-PROBE-abc-TAIL", [{"old": "abc", "new": "XYZ"}], "probe")
    if probe_bytes != b"S-O-H-PROBE-XYZ-TAIL":
        raise RuntimeError(
            "consumer %s's _replay_with_provenance failed a known-behavior "
            "probe; its semantics have drifted underneath this checker and "
            "the rule table must be re-derived" % consumer
        )
    _STAGE_OWNED_HUNKS_CACHE.append((replay, refusal))
    return replay, refusal


_ATTRIBUTION_ADJUDICATOR_CACHE: list = []  # [module], lazy singleton


def _load_attribution_adjudicator():
    """Import scripts/lib/attribution_adjudicator.py (the write-time hash-
    chain judgment the same-cycle-only completeness gate below switches to;
    see _completeness_check_file's require_full_coverage=False branch)."""
    if _ATTRIBUTION_ADJUDICATOR_CACHE:
        return _ATTRIBUTION_ADJUDICATOR_CACHE[0]
    path = Path(__file__).resolve().with_name("lib") / "attribution_adjudicator.py"
    spec = importlib.util.spec_from_file_location("attribution_adjudicator", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _ATTRIBUTION_ADJUDICATOR_CACHE.append(module)
    return module


_CYCLE_CLAIMANT_INDEX_CACHE: dict = {}

# Namespace for a non-lane claimant's candidate label.  It can never be
# mistaken for, merged into, or counted as a worker of this cycle: `_base_lane`
# is never applied to it, it never reaches `parallel_workers`, and the ':' it
# carries cannot occur in a shard label at all (WORKER_RE and the
# PER_WORKER_* filename patterns admit only [A-Za-z0-9.-]).
_CLAIMANT_LABEL_PREFIX = "claimant:"


def _cycle_claimant_index(dev_dir: Path, bare_tid: str, task_id: str) -> dict:
    """Declarations by NON-LANE claimants OF THIS CYCLE, as
    {rel: [(source, declared_snapshot, hunks), ...]}.

    A tool-owner round does cycle-level work and is legitimately NOT a lane.
    Before this reader, admission to a cycle's claimant set was decidable
    solely from a report's FILENAME, which left such a round two outcomes and
    no third: a name inside `dev-report-<task-id>-*` is admitted but
    fail-closes to its filename label and manufactures a PHANTOM LANE, while a
    name outside it never reaches any claimant enumeration at all.  Compliance
    itself therefore produced unattributable bytes.

    What was missing is a READER, not a field.  `parent_cycle` is ALREADY
    written by those rounds and already accepted by the repository's ledger
    contract checker; nothing read it, so no producer changes here.  Admission
    is decided from DECLARED CONTENT, so there is no hand-maintained list of
    exempt paths, cycles, report names or seat shapes here for a later
    instance to be appended to.

    A report is a non-lane claimant of this cycle iff ALL of:
      (1) it declares `parent_cycle` naming this cycle, compared on the bare
          YYYYMMDD-HHMMSS form so `dev-<tid>` and `<tid>` both match;
      (2) its filename is NOT admissible as a worker shard of this cycle by
          `_is_worker_for_task`.  The LANE roster stays filename-keyed exactly
          as today: this reader asks that function rather than reimplementing
          it, so the lane-named reports of this cycle that also carry
          `parent_cycle` are refused here and stay refused there;
      (3) its own declared identity does not name this cycle either (identity
          first, mirroring the aggregator's identity-first lane attribution;
          the filename test is the defensive fallback for a report declaring
          no task_id), so an in-cycle lane's gap can never be excused by a
          sibling lane through this channel;
      (4) it declares BOTH a ledger and a starting point for the path -- a
          ledger with no declared starting point is not a claim.

    Entries are deduplicated by (declared_snapshot, hunks): a round's shard
    and that round's own aggregate carry byte-identical claims, which are one
    declaration and not two.  Memoized per (dev_dir, task_id).
    """
    key = (str(dev_dir), task_id)
    cached = _CYCLE_CLAIMANT_INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    index: dict[str, list] = {}
    seen: dict[str, set] = {}
    try:
        names = sorted(
            entry.name for entry in os.scandir(dev_dir)
            if entry.is_file()
            and entry.name.startswith("dev-report-") and entry.name.endswith(".json")
        )
    except OSError:
        names = []
    for name in names:
        is_worker, _label = _is_worker_for_task(name, bare_tid, task_id)
        if is_worker:
            continue  # a lane: admitted by the roster, never through here
        try:
            data = json.loads((dev_dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if _bare_task_id(str(data.get("parent_cycle") or "")) != bare_tid:
            continue
        declared_tid = _bare_task_id(str(data.get("task_id") or ""))
        if declared_tid == bare_tid or declared_tid.startswith(bare_tid + "-"):
            continue  # declares this cycle's own identity: not a non-lane claimant
        if bare_tid in name:
            continue
        owned = data.get("owned_edits")
        snapshots = data.get("pre_edit_snapshots")
        if not isinstance(owned, dict) or not isinstance(snapshots, dict):
            continue
        for rel, hunks in owned.items():
            if not isinstance(rel, str) or not isinstance(hunks, list) or not hunks:
                continue
            if rel not in snapshots:
                continue  # a ledger with no declared starting point is not a claim
            signature = "%r|%s" % (snapshots[rel], json.dumps(hunks, sort_keys=True))
            if signature in seen.setdefault(rel, set()):
                continue
            seen[rel].add(signature)
            index.setdefault(rel, []).append(
                (str(data.get("task_id") or name), snapshots[rel], hunks)
            )
    _CYCLE_CLAIMANT_INDEX_CACHE[key] = index
    return index


def _evidenced_claimant_candidates(
    project_root: Path, rel: str, claims: list
) -> list[tuple[str, object, list]]:
    """The subset of `claims` whose declaration is EVIDENCED, as candidates.

    A declaration is honoured only when BOTH halves of its own evidence hold,
    so a forged or unevidenced declaration cannot suppress a real gap:

      (1) its own snapshot RESOLVES.  It is resolved with an EMPTY
          baseline_head_sha deliberately -- a claimant's starting point is its
          OWN declared object, never this cycle's HEAD, exactly as
          `_follow_declared_claim_chain` documents for the cross-cycle case.
          Passing this cycle's HEAD would let the AC-7 literal-text downgrade
          in `_resolve_baseline_snapshot` silently substitute HEAD's bytes and
          verify a starting point the claimant never declared;
      (2) its own ledger REPLAYS from those bytes with every anchor uniquely
          locatable -- the replay primitive raises OwnedLandingRefusal
          otherwise -- so a ledger that cannot replay from its own declared
          starting point is not a claim and is never admitted.

    The verified bytes are carried forward as the candidate's declared value
    so the re-resolution inside `_completeness_check_file` cannot substitute
    different bytes for the start that was just verified.
    """
    try:
        replay_with_provenance, _refusal = _load_stage_owned_hunks_replay()
    except RuntimeError:
        return []
    admitted: list[tuple[str, object, list]] = []
    for source, declared_snapshot, hunks in claims:
        snapshot_bytes, _snap_source = _resolve_baseline_snapshot(
            project_root, "", rel, declared_snapshot
        )
        if snapshot_bytes is None:
            continue  # unresolvable starting point: never admitted
        try:
            replay_with_provenance(snapshot_bytes, hunks, rel)
        except Exception:
            continue  # unreplayable ledger: never admitted
        admitted.append((_CLAIMANT_LABEL_PREFIX + source, snapshot_bytes, hunks))
    return admitted


def _lane_candidates_for_file(
    expanded_shards: list[tuple[str, dict]], rel: str,
    cycle_claimants: list | None = None, project_root: Path | None = None,
) -> list[tuple[str, object, list]]:
    """Per-declaring-lane (snapshot, hunks) candidates for `rel` (task
    20261001-close-multilane-stall), each folded through the SAME
    _merge_owned_edits/_merge_pre_edit_snapshots functions used for the real
    merge, scoped to only that lane's own shard(s) (its superseded round(s),
    if any, plus its promoted shard) -- so a retried lane's own round-fold
    collapse happens exactly as it would in the real merge. Lanes not
    declaring `rel` are omitted. Empty when no lane declares `rel`.

    `cycle_claimants`/`project_root` (opt-in, absent by default so every
    existing caller behaves exactly as before) append this cycle's NON-LANE
    claimants of `rel` -- see `_cycle_claimant_index` for how membership is
    decided from the declaration rather than the filename, and
    `_evidenced_claimant_candidates` for the two ways each one is
    evidence-bound.  They join the (snapshot, order) CANDIDATE set that
    `_completeness_check_file` searches, which has no power to create a lane:
    the roster comes from `_scan_shards`, nothing here reaches
    `parallel_workers`, and a claimant's label is namespaced so it can never
    collide with or fold into a lane label.  This is what lets a claimant that
    edited `rel` BEFORE a lane did be accounted for at all -- the forward-only
    cross-cycle chain in `_follow_declared_claim_chain` starts from a lane's
    replay output and so structurally cannot reach backwards past it."""
    base_lanes: list[str] = []
    seen: set[str] = set()
    for label, _ in expanded_shards:
        base = _base_lane(label)
        if base not in seen:
            seen.add(base)
            base_lanes.append(base)
    candidates = []
    for base in base_lanes:
        subset = [(label, data) for label, data in expanded_shards if _base_lane(label) == base]
        lane_hunks = _merge_owned_edits(subset).get(rel)
        if not isinstance(lane_hunks, list) or not lane_hunks:
            continue
        lane_snapshot = _merge_pre_edit_snapshots(subset).get(rel)
        candidates.append((base, lane_snapshot, lane_hunks))
    if cycle_claimants and project_root is not None:
        candidates.extend(
            _evidenced_claimant_candidates(project_root, rel, cycle_claimants)
        )
    return candidates


_MAX_CLAIM_CHAIN_LINKS = 8
_FOREIGN_CLAIM_INDEX_CACHE: dict = {}


def _foreign_claim_index(dev_dir: Path, own_bare_tid: str) -> dict:
    """Ownership declarations made by cycles OTHER than `own_bare_tid`, as
    {rel: [(source, declared_snapshot, hunks), ...]}.

    Built by reading the artifacts themselves, so the rule it feeds is
    derived from declarations rather than from any hand-maintained list of
    exempt paths, cycles or error wordings -- there is no list here to append
    an instance to. A report counts as foreign only when BOTH its own
    declared `task_id` and its filename fail to name this cycle (identity
    first, mirroring the aggregator's identity-first lane attribution;
    filename as the defensive fallback for a report declaring no task_id).
    Same-cycle lanes are deliberately excluded: an in-cycle lane's gap must
    stay reachable through the existing lane-permutation machinery and can
    never be excused by a sibling lane here.

    ADMISSION IS DECIDED BY DECLARATION, NOT BY A FILENAME PREFIX. Candidacy
    was previously pre-filtered to names beginning `dev-report-`, which is a
    proxy for "carries an ownership declaration" and not the question itself.
    Measured on this repository at 2026-10-02T09Z, the proxy excluded
    docs/dev/aggregator-fix-report-20260930-132644.json -- a report declaring
    both a ledger and a starting point for scripts/aggregate-dev-report.py,
    whose snapshot resolves against its own declared git object and whose
    ledger replays with every anchor uniquely locatable (a verified
    101660 -> 102908 boundary) -- solely because of its name. Admitting a
    third filename prefix beside the first would only move the blind spot to
    the next report-naming shape; the real question, asked below for every
    candidate alike, is whether the artifact declares BOTH `owned_edits` and
    `pre_edit_snapshots` for the path. The directory scope is unchanged (one
    non-recursive scandir of docs/dev/); only the name test is gone.

    Entries are deduplicated by (declared_snapshot, hunks) because a cycle's
    lane shard and that cycle's own aggregate carry byte-identical claims;
    they are one declaration, not two chain links.

    Built once and memoized per (dev_dir, own_bare_tid). It is built on the
    happy path too, because `_absorbed_foreign_claims` consults it for every
    file -- including files that replay exactly, which is precisely where an
    absorbed hunk would otherwise hide. Measured cost over this repository's
    443 `dev-report-*` files at 2026-10-02T04:58Z: 0.28s cold for the whole
    index (613 paths, 1028 claims); re-measured over all 2759 candidate
    `*.json` files once the filename proxy was dropped: see the recorded
    figure in the dev-report for this change. That is one build per aggregate
    run, against a check that already shells out to git per file.
    """
    key = (str(dev_dir), own_bare_tid)
    cached = _FOREIGN_CLAIM_INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    index: dict[str, list] = {}
    seen: dict[str, set] = {}
    try:
        names = sorted(
            entry.name for entry in os.scandir(dev_dir)
            if entry.is_file() and entry.name.endswith(".json")
        )
    except OSError:
        names = []
    for name in names:
        try:
            data = json.loads((dev_dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        declared_tid = str(data.get("task_id") or "")
        if _bare_task_id(declared_tid) == own_bare_tid or own_bare_tid in name:
            continue
        owned = data.get("owned_edits")
        snapshots = data.get("pre_edit_snapshots")
        if not isinstance(owned, dict) or not isinstance(snapshots, dict):
            continue
        for rel, hunks in owned.items():
            if not isinstance(rel, str) or not isinstance(hunks, list) or not hunks:
                continue
            if rel not in snapshots:
                continue  # a ledger with no declared starting point is not a boundary
            signature = "%r|%s" % (snapshots[rel], json.dumps(hunks, sort_keys=True))
            if signature in seen.setdefault(rel, set()):
                continue
            seen[rel].add(signature)
            index.setdefault(rel, []).append(
                (declared_tid or name, snapshots[rel], hunks)
            )
    _FOREIGN_CLAIM_INDEX_CACHE[key] = index
    return index


def _follow_declared_claim_chain(
    project_root: Path, dev_dir: Path, own_bare_tid: str, rel: str,
    start_bytes: bytes, live_bytes: bytes,
) -> tuple[bool, list[str], bytes]:
    """Follow declared cross-cycle ownership boundaries forward from
    `start_bytes` (a lane's replay output) toward `live_bytes`.

    The rule: a lane's authorship legitimately ENDS where another cycle's
    declared pre-edit snapshot for the same path BEGINS. A lane is not
    answerable for bytes a different cycle has declared it wrote.

    It is evidence-bound in three ways and a hole in none of them:
      (1) the other cycle's declared snapshot must resolve to bytes
          BYTE-IDENTICAL to the current chain position. A declaration that
          merely mentions the path, or resolves to different bytes, is not a
          boundary and excuses nothing;
      (2) that claimant's own ledger must then REPLAY from those bytes with
          every anchor uniquely locatable -- the replay primitive raises
          OwnedLandingRefusal otherwise -- so an unverifiable claim never
          advances the chain and never excuses a byte;
      (3) the chain is followed to its END, not one hop.

    Returns (closed, links, end_bytes); `closed` is True only when the chain
    arrives at `live_bytes` exactly.

    `end_bytes` is where the chain STALLED, which is NOT the same question as
    which bytes are unclaimed: a single mid-chain hole stops the walk, and
    every declaration whose own starting point lies PAST that hole is then
    unreachable from it however well evidenced it is. Callers must therefore
    account for the remainder with `_unclaimed_spans` rather than subtracting
    `len(end_bytes)` from the live size -- see that function for the measured
    3x overstatement the subtraction produced on this repository's own
    scripts/aggregate-dev-report.py.
    """
    try:
        replay_with_provenance, _refusal = _load_stage_owned_hunks_replay()
    except RuntimeError:
        return False, [], start_bytes
    claims = list(_foreign_claim_index(dev_dir, own_bare_tid).get(rel) or ())
    current = start_bytes
    links: list[str] = []
    while current != live_bytes and len(links) < _MAX_CLAIM_CHAIN_LINKS:
        for position, (source, declared_snapshot, hunks) in enumerate(claims):
            # baseline_head_sha is deliberately "" -- a foreign claimant's
            # boundary is its OWN declared object, never this cycle's HEAD.
            snapshot_bytes, _source = _resolve_baseline_snapshot(
                project_root, "", rel, declared_snapshot
            )
            if snapshot_bytes is None or snapshot_bytes != current:
                continue
            try:
                advanced, _prov, _components = replay_with_provenance(
                    snapshot_bytes, hunks, rel
                )
            except Exception:
                continue  # unverifiable claim: never advances the chain
            claims.pop(position)  # each declaration can be consumed at most once
            links.append("%s(%+d bytes)" % (source, len(advanced) - len(current)))
            current = advanced
            break
        else:
            break
    return current == live_bytes, links, current


_DECLARED_INTERVALS_CACHE: dict = {}


def _declared_length_intervals(
    project_root: Path, dev_dir: Path, own_bare_tid: str, rel: str,
) -> list[tuple[int, int, str]]:
    """Every VERIFIED declaration for `rel` as the size interval it bridges:
    (lo, hi, source), lo/hi being the byte lengths of its own declared
    starting point and of its own replay output.

    Verified means the same two things `_follow_declared_claim_chain` and
    `_evidenced_claimant_candidates` already demand, and nothing weaker: the
    declared snapshot RESOLVES against the claimant's OWN declared object
    (baseline_head_sha is deliberately "" -- passing this cycle's HEAD would
    let the literal-text downgrade in `_resolve_baseline_snapshot` substitute
    HEAD's bytes for a start the claimant never declared), and its ledger
    REPLAYS from those bytes with every anchor uniquely locatable. An
    unresolvable or unreplayable declaration yields no interval and so
    excuses nothing. A shrinking edit is normalised to (min, max) so the
    interval it accounts for is still the span between the two sizes.

    Memoized per (dev_dir, own_bare_tid, rel) because the callers below are
    reached once per failing replay candidate, and the work is one resolve
    plus one replay per claim.
    """
    key = (str(dev_dir), own_bare_tid, rel)
    cached = _DECLARED_INTERVALS_CACHE.get(key)
    if cached is not None:
        return cached
    intervals: list[tuple[int, int, str]] = []
    try:
        replay_with_provenance, _refusal = _load_stage_owned_hunks_replay()
    except RuntimeError:
        return intervals
    for source, declared_snapshot, hunks in _foreign_claim_index(dev_dir, own_bare_tid).get(rel) or ():
        snapshot_bytes, _snap_source = _resolve_baseline_snapshot(
            project_root, "", rel, declared_snapshot
        )
        if snapshot_bytes is None:
            continue  # unresolvable starting point: declares no interval
        try:
            advanced, _prov, _components = replay_with_provenance(
                snapshot_bytes, hunks, rel
            )
        except Exception:
            continue  # unverifiable ledger: declares no interval
        lo, hi = len(snapshot_bytes), len(advanced)
        if lo != hi:
            intervals.append((min(lo, hi), max(lo, hi), source))
    _DECLARED_INTERVALS_CACHE[key] = intervals
    return intervals


def _unclaimed_spans(
    project_root: Path, dev_dir: Path, own_bare_tid: str, rel: str,
    stalled_at: int, live_size: int,
) -> tuple[list[tuple[int, int]], list[tuple[int, int, str]]]:
    """The UNION of sub-spans of [stalled_at, live_size) that no verified
    declaration accounts for, plus the covering declarations that account for
    the rest -- each named, so every byte this stops counting is named to the
    declaration that claims it.

    This is the difference between STALL-accounting and SPAN-accounting.
    `_follow_declared_claim_chain` reports where the byte-exact walk stopped;
    subtracting that from the live size counts every later byte as unclaimed,
    including spans that ARE declared and DO replay but are merely unreachable
    from behind a hole. Measured on this repository's own
    scripts/aggregate-dev-report.py at 2026-10-02T09Z: the subtraction said
    71278 of 172938 live bytes were "claimed by no declaration", of which
    47221 were in fact declared and replay-verified past the break, so the
    honest figure was 24057 in three spans. A figure overstating by ~3x makes
    a reader mis-rank the problem, and it cannot be stated stably at all
    while it is anchored to a live size that grows with every arriving byte.

    This narrows only the ACCOUNTING, never the verdict: the caller's `ok` is
    still driven solely by whether the chain arrived at `live_bytes` exactly,
    so a file whose spans happen to be fully covered by length still FAILS
    (and says so). No byte is dropped silently -- a span that no declaration
    covers is returned and reported individually.
    """
    clipped: list[tuple[int, int, str]] = []
    for lo, hi, source in _declared_length_intervals(
        project_root, dev_dir, own_bare_tid, rel
    ):
        start, end = max(lo, stalled_at), min(hi, live_size)
        if end > start:
            clipped.append((start, end, source))
    spans: list[tuple[int, int]] = []
    cursor = stalled_at
    for start, end, _source in sorted(clipped):
        if start > cursor:
            spans.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < live_size:
        spans.append((cursor, live_size))
    return spans, sorted(clipped)


def _span_shortfall_diagnostic(
    rel: str, label: str, replayed: bytes, links: list[str], end_bytes: bytes,
    live_bytes: bytes, spans: list[tuple[int, int]],
    covered: list[tuple[int, int, str]],
) -> str:
    """The one wording for a chain that stopped short, shared by both of
    `_completeness_check_file`'s diagnostic sites so the two cannot drift
    into disagreeing about the same fact.

    Reports the spans INDIVIDUALLY, not only a total, and names the
    declaration accounting for each span it does not count. Retains the
    "claimed by no declaration" wording the gap class is recognised by.
    """
    unclaimed_total = sum(hi - lo for lo, hi in spans)
    covered_note = (
        "; past the break %d byte(s) are declared and replay-verified but "
        "unreachable from it (%s)" % (
            sum(hi - lo for lo, hi, _s in covered),
            ", ".join("%d-%d by %s" % (lo, hi, src) for lo, hi, src in covered),
        )
        if covered else ""
    )
    if not spans:
        return (
            "%s: [%s] replay produced %d bytes; declared cross-cycle boundary "
            "chain %s reaches %d bytes%s, leaving 0 of the %d live bytes claimed "
            "by no declaration BY LENGTH -- but the chain is not byte-closed at "
            "%d bytes, so a length-neutral undeclared edit remains unreconciled"
            % (rel, label, len(replayed), " -> ".join(links), len(end_bytes),
               covered_note, len(live_bytes), len(end_bytes))
        )
    return (
        "%s: [%s] replay produced %d bytes; declared cross-cycle boundary chain "
        "%s reaches %d bytes%s, leaving %d of the %d live bytes claimed by no "
        "declaration in %d span(s): %s"
        % (rel, label, len(replayed), " -> ".join(links), len(end_bytes),
           covered_note, unclaimed_total, len(live_bytes), len(spans),
           "; ".join("%d-%d (%d bytes)" % (lo, hi, hi - lo) for lo, hi in spans))
    )


def _foreign_prefix_extend(
    project_root: Path, dev_dir: Path, own_bare_tid: str, rel: str, start_bytes: bytes,
    stop_when=None,
) -> bytes:
    """Advance `start_bytes` forward through declared foreign-cycle claims
    whose own pre-edit snapshot matches the CURRENT position -- the PREFIX
    counterpart to `_follow_declared_claim_chain`'s SUFFIX direction (task
    20261001-161041-interleave-fix).

    `_follow_declared_claim_chain` extends a lane's own replay OUTPUT
    forward toward `live_bytes`, which structurally can only ever explain
    bytes a foreign cycle added AFTER this cycle's own lanes stopped
    editing. Nothing enforces that ordering on a shared working tree: a
    foreign cycle's edits can just as easily have already landed BEFORE any
    of this cycle's own lanes started, in which case `baseline_head_sha`'s
    committed blob is not actually this cycle's lanes' true pre-edit state
    -- the foreign cycle's own edits, already sitting in the working tree
    ahead of them, are. This walks `start_bytes` forward through exactly
    those, evidence-bound the same two ways as the suffix direction (the
    claim's own declared snapshot must byte-match the current position, and
    its own ledger must replay with every anchor uniquely locatable -- an
    unverifiable claim never advances the chain), bounded by the same
    `_MAX_CLAIM_CHAIN_LINKS`, and consuming a claimed declaration at most
    once. Returns `start_bytes` unchanged when no foreign claim matches it
    at all -- the common, unaffected case -- so no existing caller's
    behavior for a file with no foreign entanglement changes.

    `stop_when` (optional, default None keeps every pre-existing caller's
    maximal-consumption behavior unchanged): a predicate checked after EACH
    successful hop; when it returns True the walk stops immediately instead
    of greedily consuming further hops. A MID-CHAIN caller (task
    20261001-161041-selfhost-close) needs this: stopping as soon as some
    remaining in-cycle lane's own declared snapshot matches is the correct
    hand-off point, whereas consuming maximally can overshoot straight past
    it into a foreign claim's own interior with no remaining lane to resume
    from there.
    """
    try:
        replay_with_provenance, _refusal = _load_stage_owned_hunks_replay()
    except RuntimeError:
        return start_bytes
    claims = list(_foreign_claim_index(dev_dir, own_bare_tid).get(rel) or ())
    current = start_bytes
    links = 0
    while links < _MAX_CLAIM_CHAIN_LINKS:
        advanced_this_round = False
        for position, (_source, declared_snapshot, hunks) in enumerate(claims):
            # baseline_head_sha is deliberately "" -- a foreign claimant's
            # boundary is its OWN declared object, never this cycle's HEAD.
            snapshot_bytes, _source2 = _resolve_baseline_snapshot(
                project_root, "", rel, declared_snapshot
            )
            if snapshot_bytes is None or snapshot_bytes != current:
                continue
            try:
                advanced, _prov, _components = replay_with_provenance(
                    snapshot_bytes, hunks, rel
                )
            except Exception:
                continue  # unverifiable claim: never advances the chain
            claims.pop(position)  # each declaration can be consumed at most once
            current = advanced
            links += 1
            advanced_this_round = True
            break
        if not advanced_this_round:
            break
        if stop_when is not None and stop_when(current):
            break
    return current


def _absorbed_foreign_claims(dev_dir: Path, own_bare_tid: str, rel: str, hunks) -> list[str]:
    """Hunks in THIS cycle's ledger for `rel` that another cycle has already
    declared it authored, byte-for-byte (same `old` AND same `new`).

    This is the anti-absorption half of the boundary rule, and it is why
    recognising a boundary cannot be used to bless theft. The boundary rule
    makes a lane that STOPS at another cycle's declaration complete; this
    makes a lane that CROSSES that boundary and claims the bytes anyway
    INCOMPLETE -- even when the absorbed hunks make its replay reach the live
    file exactly, which is precisely the shape a prior round measured passing
    the repository's own ledger checker clean at exit 0. Two cycles cannot
    both be the author of one identical transformation, so an exact
    (old, new) collision across cycles is a double claim on its face.
    """
    if not isinstance(hunks, list) or not hunks:
        return []
    foreign: dict[tuple[str, str], str] = {}
    for source, _snapshot, claimed in _foreign_claim_index(dev_dir, own_bare_tid).get(rel) or ():
        for hunk in claimed:
            if (isinstance(hunk, dict) and isinstance(hunk.get("old"), str)
                    and isinstance(hunk.get("new"), str)):
                foreign.setdefault((hunk["old"], hunk["new"]), source)
    collisions = []
    for position, hunk in enumerate(hunks):
        if not isinstance(hunk, dict):
            continue
        source = foreign.get((hunk.get("old"), hunk.get("new")))
        if source is not None:
            collisions.append("edit %d already declared by %s" % (position, source))
    return collisions


def _chain_bounded_orderings(
    lane_candidates: list[tuple[str, object, list]], start_bytes: bytes,
    project_root: Path, rel: str,
    replay_with_provenance, owned_landing_refusal,
    max_branch: int, max_nodes: int,
    dev_dir: Path | None = None, own_bare_tid: str = "",
):
    """Lazily yield (ordered_hunks, chain_labels, final_bytes) replay-order
    candidates starting from `start_bytes`, for lane counts beyond the
    exhaustive N! permutation bound (_MAX_COMPLETENESS_CANDIDATE_LANES).
    `final_bytes` is the ACTUAL accumulated bytes the walk itself produced --
    not merely `ordered_hunks` replayed fresh from `start_bytes` -- so a
    caller never has to re-derive what a mid-chain foreign hop (below)
    already computed once.

    Mirrors _follow_declared_claim_chain's declared-boundary philosophy,
    applied intra-cycle instead of cross-cycle: a lane's own declared
    pre_edit_snapshot is expected to byte-match the accumulated post-edit
    state of whichever lanes already landed before it -- the real shape
    measured on this task's own 6-lane file (each lane's snapshot sized
    strictly between the git baseline and the live file, growing lane over
    lane: a genuine edit chain, not N independent readers of one baseline).
    At each step, only the remaining lane(s) whose OWN declared snapshot
    matches the accumulated bytes so far are tried next -- usually exactly
    one, costing one replay call with no branching. When none or more than
    one match (a genuine ambiguity, not a derivable chain position), ALL
    remaining lanes become candidates for that step -- bounded by
    `max_branch`, applied only to that ambiguous step's own branching, not
    to the total lane count the way the old guard capped unconditionally.
    `max_nodes` is a hard ceiling on total recursive calls, independent of
    per-step branching, so several small per-step ambiguities cannot still
    compound into a blowup.

    Each candidate's own declared snapshot is resolved with an EMPTY
    baseline_head_sha deliberately (task 20261001-161041-selfhost-close),
    mirroring `_evidenced_claimant_candidates`'s own reasoning for the
    cross-cycle case: a lane's starting point is its OWN declared object,
    never this cycle's HEAD. Passing this cycle's HEAD would let the AC-7
    literal-text downgrade in `_resolve_baseline_snapshot` silently
    substitute HEAD's bytes for a lane's own literal-text declaration,
    which is exactly as wrong here as it would be for a foreign claimant.

    `dev_dir`/`own_bare_tid` (optional, default off for back-compat) enable
    a MID-CHAIN counterpart to `_foreign_prefix_extend`: a foreign cycle's
    edit can land on the shared tree BETWEEN two of this cycle's own lanes,
    not only before the first or after the last. When no remaining
    candidate's own snapshot matches the accumulated bytes, this tries
    advancing those bytes through declared foreign claims first (same two
    evidence requirements as every other use of that function) before
    falling back to the ambiguous-step branch below -- so a real foreign
    gap is bridged instead of either wrongly widening the branch or failing
    outright."""
    nodes = [0]

    def resolve(snap_declared):
        snapshot_bytes, _src = _resolve_baseline_snapshot(
            project_root, "", rel, snap_declared
        )
        return snapshot_bytes

    def walk(order_labels, order_hunks, current, remaining):
        nodes[0] += 1
        if nodes[0] > max_nodes:
            return
        if not remaining:
            yield list(order_hunks), list(order_labels), current
            return
        matched = [cand for cand in remaining if resolve(cand[1]) == current]
        step_start = current
        if not matched and dev_dir is not None and own_bare_tid:
            extended = _foreign_prefix_extend(
                project_root, dev_dir, own_bare_tid, rel, current,
                stop_when=lambda b: any(resolve(cand[1]) == b for cand in remaining),
            )
            if extended != current:
                bridged = [cand for cand in remaining if resolve(cand[1]) == extended]
                if bridged:
                    matched, step_start = bridged, extended
        branch = matched if matched else remaining
        if len(branch) > max_branch:
            return
        for cand in branch:
            name, _snap_declared, cand_hunks = cand
            try:
                advanced, _prov, _components = replay_with_provenance(step_start, cand_hunks, rel)
            except owned_landing_refusal:
                continue
            except Exception:
                continue
            next_remaining = [c for c in remaining if c is not cand]
            yield from walk(
                order_labels + [name], order_hunks + list(cand_hunks), advanced, next_remaining
            )

    yield from walk([], [], start_bytes, list(lane_candidates))


def _chain_bounded_hunk_orderings(
    lane_candidates: list[tuple[str, object, list]], start_bytes: bytes,
    rel: str, replay_with_provenance, owned_landing_refusal,
    max_branch: int, max_nodes: int,
    dev_dir: Path | None = None, own_bare_tid: str = "",
):
    """Lazily yield (ordered_hunks, item_labels) replay-order candidates that
    interleave INDIVIDUAL hunks across (and, when the evidence requires it,
    WITHIN) declaring lanes, for files where no LANE-BLOCK ordering --
    exhaustive permutation or `_chain_bounded_orderings`'s own chaining --
    replays to the live bytes (task 20261001-161041-interleave-fix).

    `_completeness_check_file` only reaches this after every lane-block
    candidate has already failed, so the common (non-interleaved) case never
    pays this function's extra cost.

    Every hunk from every declaring lane is pooled as an independent item.
    This is NOT scoped to inter-lane interleaving only: verified directly on
    this task's own motivating file
    (hooks/tests/test_artifact_contract_enforce.py, 6 declaring lanes), one
    lane's (r21's) own two hunks must apply in the REVERSE of their declared
    order for the replay to reach the live bytes exactly -- a declared
    `owned_edits` hunk order records the FINAL authored state per region
    (per dev.md's own ledger contract), not necessarily the chronological
    application order, so a same-lane reordering is exactly as evidence-
    bound as a cross-lane one: both are accepted only when the replay
    primitive itself finds the hunk's `old` text uniquely locatable in the
    accumulated bytes, and rejected otherwise. No ordering this yields can
    therefore "explain" bytes that were not genuinely reachable this way;
    it only widens WHICH orderings are considered.

    `dev_dir`/`own_bare_tid` (optional, default off for back-compat) pool in
    every declared FOREIGN claim's own hunks too, each marked OPTIONAL (task
    20261001-161041-selfhost-close): a foreign cycle's edit can land BETWEEN
    two of this cycle's own hunks at a granularity finer than any single
    lane-block boundary, so neither `_foreign_prefix_extend` (prefix-only)
    nor `_follow_declared_claim_chain` (suffix-only) can express it. Only
    this cycle's OWN hunks are mandatory -- the walk's terminal condition is
    "no mandatory item remains", not "no item remains" -- so a foreign hunk
    is used only when its own `old` text is uniquely locatable, exactly the
    same evidence bound as every in-cycle hunk, and never required to be
    consumed: an unused foreign item left in `remaining` is simply a claim
    this file's gap did not need. Measured directly on this task's own
    motivating file (task 20261001-161041-selfhost-close,
    scripts/aggregate-dev-report.py itself): the correct interleaving
    (6 of a 7-hunk foreign claim's own hunks, each the sole viable candidate
    at its step) resolved with zero branching at every step.

    Guarded three ways so this cannot blow up the way brute permutation of
    individual hunks would (N=10 hunks -> 3,628,800 raw orderings):
      (1) a cheap O(n) occurrence-count of each candidate hunk's own `old`
          text in the accumulated bytes gates it BEFORE the expensive
          replay primitive (an alignment computation, not a cheap string
          op) is ever invoked -- a step with several textually non-viable
          candidates stays cheap;
      (2) memoization on (accumulated bytes, remaining-item identities)
          collapses the redundant re-exploration that disjoint, mutually
          commutative edits would otherwise repeat under every one of their
          equivalent orderings landing on the same intermediate state;
      (3) `max_branch` bounds a single step's own viable-candidate count and
          `max_nodes` hard-ceilings total recursive calls, identically in
          meaning to `_chain_bounded_orderings`'s own two guards -- see
          `_MAX_COMPLETENESS_HUNK_BRANCH`/`_MAX_COMPLETENESS_HUNK_CHAIN_NODES`
          for why this function's bounds are wider than those, with the
          measurement that justifies it.
    """
    nodes = [0]
    dead: set = set()
    pool = [
        (name, idx, hunk, True)
        for name, _snap, hunks in lane_candidates
        for idx, hunk in enumerate(hunks)
    ]
    if dev_dir is not None and own_bare_tid:
        for source, _snap, hunks in (_foreign_claim_index(dev_dir, own_bare_tid).get(rel) or ()):
            pool.extend((source, idx, hunk, False) for idx, hunk in enumerate(hunks))

    def walk(item_labels, ordered_hunks, current, remaining):
        nodes[0] += 1
        if nodes[0] > max_nodes:
            return
        done = not any(item[3] for item in remaining)
        if done:
            yield list(ordered_hunks), list(item_labels)
            if not remaining:
                return
        memo_key = (current, frozenset(id(item) for item in remaining))
        if memo_key in dead:
            return
        viable = []
        for item in remaining:
            _name, _idx, hunk, _mandatory = item
            old_str = hunk.get("old") if isinstance(hunk, dict) else None
            old_b = old_str.encode("utf-8") if isinstance(old_str, str) else b""
            if old_b and current.count(old_b) == 1:
                viable.append(item)
        if len(viable) > max_branch:
            dead.add(memo_key)
            return
        yielded_any = done
        for item in viable:
            name, idx, hunk, _mandatory = item
            try:
                advanced, _prov, _components = replay_with_provenance(current, [hunk], rel)
            except owned_landing_refusal:
                continue
            except Exception:
                continue
            next_remaining = [c for c in remaining if c is not item]
            for result in walk(
                item_labels + ["%s[%d]" % (name, idx)], ordered_hunks + [hunk],
                advanced, next_remaining,
            ):
                yielded_any = True
                yield result
        if not yielded_any:
            dead.add(memo_key)

    yield from walk([], [], start_bytes, pool)


def _completeness_check_file(
    project_root: Path, baseline_head_sha: str, rel: str, hunks, declared_snapshot,
    lane_candidates: list[tuple[str, object, list]] | None = None,
    dev_dir: Path | None = None, own_bare_tid: str = "",
    require_full_coverage: bool = True,
) -> tuple[bool, str]:
    """Backlog #99 criterion C for one file -- redesigned for task
    20261001-close-multilane-stall: verify that SOME internally-consistent
    (snapshot, hunk-order) combination among the declaring lane(s)' own
    declared values reproduces the live worktree bytes exactly, via a direct
    call into stage-owned-hunks.py's own ENTRY-side `_replay_with_provenance`
    primitive -- never its `--dry-run` CLI (which also runs the irrelevant
    BASELINE-side ownership-conflict probe). `lane_candidates`, when
    non-empty, supplies each declaring lane's own (snapshot, hunks) pair; a
    single lane is the degenerate N=1 case of the same mechanism (M3). When
    `lane_candidates` is falsy (back-compat for direct callers that have not
    threaded per-lane shard data through, e.g. pre-existing tests), falls
    back to the single merged (declared_snapshot, hunks) pair -- today's
    historical behavior, just verified via the same direct-import mechanism
    instead of the subprocess CLI. Returns (ok, diagnostic); diagnostic is
    empty when ok.

    `dev_dir`/`own_bare_tid` (this task) enable the declared cross-cycle
    boundary rule: a lane's authorship ends where another cycle's declared
    pre-edit snapshot begins, so the remainder past that boundary is not this
    lane's gap -- see `_follow_declared_claim_chain` for the three ways that
    is evidence-bound, and `_absorbed_foreign_claims` for why it cannot be
    used to bless absorbing another cycle's bytes. Both default to
    off/absent for back-compat with direct callers (e.g. pre-existing tests)
    that pre-date these parameters; with them absent the behavior is exactly
    today's.

    `require_full_coverage` (default True, today's historical behavior):
    when True, a candidate only counts as explaining `rel` when its replay
    reaches `live_bytes` EXACTLY (optionally via the cross-cycle boundary
    chain) -- the GLOBAL-completeness question. When False, a candidate
    counts as soon as its replay SUCCEEDS without error (every hunk anchor
    uniquely locatable, no conflict) from its own declared starting point,
    regardless of whether it reaches `live_bytes` -- the SAME-CYCLE-ONLY
    self-consistency question (OWNERSHIP_COMPLETENESS_BLOCKING_KEY): does
    this lane's (or these lanes') own declared ledger correctly and
    non-conflictingly reproduce the bytes it itself claims to own? A file
    legitimately short of `live_bytes` because an unrelated concurrent
    session holds undeclared bytes there is never a defect in THIS cycle's
    own deliverable, so it must never fail this narrower question. `dev_dir`
    and `own_bare_tid` are forced off below when this is False: the
    cross-cycle boundary rule, the anti-absorption check, and foreign-hunk
    pooling must never influence a same-cycle-only verdict, however this is
    called."""
    if not require_full_coverage:
        # Same-cycle-only mode (OWNERSHIP_COMPLETENESS_BLOCKING_KEY) is the
        # ONE blocking call of this function (require_full_coverage=True's
        # global diagnostic below is advisory-only and untouched). Attribution-
        # journal consumer cutover (docs/reference/attribution-journal-
        # cutover-flip-plan-20261003.md, superseded by the zero-blocking
        # constraint of the follow-up consumer-cutover task): the self-
        # reported-ledger replay combinatorics below this branch (still used
        # by the advisory call) are no longer this gate's authority. A file
        # with no write-time journal evidence, or evidence that does not
        # reach back to the current HEAD blob, is deferred to the commit
        # analyst's own judgment -- never blocked here. Only a MEASURED
        # structural conflict (ENTANGLED) blocks.
        try:
            ledger = _load_attribution_adjudicator()
            verdict = ledger.ledger_structural_verdict(str(project_root / rel), root=str(project_root))
        except Exception as exc:
            # An infrastructure fault is never a verdict (constraint 1): deferred,
            # same as no journal evidence, not blocked -- but disclosed, not silent.
            print(f"ledger judgment infrastructure fault for {rel}: {exc!r}", file=sys.stderr)
            return True, ""
        if verdict.get("verdict") == ledger.ENTANGLED:
            return False, (f"{rel}: write-time attribution journal measures an unresolved "
                           f"structural conflict: {verdict.get('detail', '')}")
        return True, ""
    try:
        live_bytes = (project_root / rel).read_bytes()
    except OSError as exc:
        return False, f"{rel}: cannot read live worktree file: {exc}"

    boundary_rule_available = (
        require_full_coverage and dev_dir is not None and bool(own_bare_tid)
    )
    if boundary_rule_available:
        absorbed = _absorbed_foreign_claims(dev_dir, own_bare_tid, rel, hunks)
        if absorbed:
            return False, (
                f"{rel}: ledger absorbs bytes another cycle already declared it "
                f"authored ({'; '.join(absorbed)}) -- a boundary crossed and claimed "
                "is not completeness, it is a double claim on the declaring cycle's "
                "ownership"
            )

    try:
        replay_with_provenance, owned_landing_refusal = _load_stage_owned_hunks_replay()
    except RuntimeError as exc:
        return False, f"{rel}: {exc}"

    # 4th element is final_bytes PRE-COMPUTED by _chain_bounded_orderings'
    # own walk (None when a candidate still needs a fresh replay below): a
    # mid-chain foreign-prefix hop that walk already applied cannot be
    # reconstructed by blindly re-replaying `ordered_hunks` from
    # `snapshot_bytes` a second time, so the bytes it already produced are
    # carried forward instead of discarded (task 20261001-161041-selfhost-close).
    candidates: list[tuple[bytes, list, str, bytes | None]] = []
    if lane_candidates:
        lane_names = [name for name, _, _ in lane_candidates]
        hunks_by_lane = {name: lane_hunks for name, _, lane_hunks in lane_candidates}
        if len(lane_candidates) < _MAX_COMPLETENESS_CANDIDATE_LANES:
            for snap_name, snap_declared, _ in lane_candidates:
                snapshot_bytes, snap_source = _resolve_baseline_snapshot(
                    project_root, baseline_head_sha, rel, snap_declared
                )
                if snapshot_bytes is None:
                    continue
                for order in itertools.permutations(lane_names):
                    ordered_hunks = [h for name in order for h in hunks_by_lane[name]]
                    candidates.append((
                        snapshot_bytes, ordered_hunks,
                        "snapshot=%s order=%s" % (snap_name, "+".join(order)),
                        None,
                    ))
        else:
            # N exceeds the exhaustive-permutation bound: chain the lanes via
            # their own declared pre_edit_snapshot instead of trying every
            # N! ordering blind (see _chain_bounded_orderings and the
            # constant's comment for the measured evidence this is unsafe).
            # The start, like every per-lane candidate resolved inside
            # _chain_bounded_orderings itself, is resolved with an empty
            # baseline_head_sha -- a lane's own declared snapshot is its own
            # evidence, never this cycle's HEAD (same AC-7 reasoning as the
            # cross-cycle claimant path).
            for snap_name, snap_declared, _ in lane_candidates:
                start_bytes, snap_source = _resolve_baseline_snapshot(
                    project_root, "", rel, snap_declared
                )
                if start_bytes is None:
                    continue
                for ordered_hunks, chain_labels, final_bytes in _chain_bounded_orderings(
                    lane_candidates, start_bytes, project_root, rel,
                    replay_with_provenance, owned_landing_refusal,
                    _MAX_COMPLETENESS_CANDIDATE_LANES, _MAX_COMPLETENESS_CHAIN_NODES,
                    dev_dir=dev_dir, own_bare_tid=own_bare_tid,
                ):
                    candidates.append((
                        start_bytes, ordered_hunks,
                        "snapshot=%s chain=%s" % (snap_name, "+".join(chain_labels)),
                        final_bytes,
                    ))
    if not candidates:
        snapshot_bytes, snap_source = _resolve_baseline_snapshot(
            project_root, baseline_head_sha, rel, declared_snapshot
        )
        if snapshot_bytes is None:
            return False, f"{rel}: {snap_source}"
        if not isinstance(hunks, list) or not hunks:
            return False, f"{rel}: owned_edits ledger is empty/invalid for completeness check"
        candidates.append((snapshot_bytes, hunks, "merged:%s" % snap_source, None))

    last_diagnostic = ""
    for snapshot_bytes, ordered_hunks, label, precomputed in candidates:
        if precomputed is not None:
            # Already a verified replay result from _chain_bounded_orderings'
            # own walk (which may have crossed a mid-chain foreign hop
            # `ordered_hunks` alone cannot re-express) -- use it as-is rather
            # than re-replaying `ordered_hunks` from `snapshot_bytes`, which
            # would repeat the same anchor failure the walk already resolved.
            replayed = precomputed
        else:
            try:
                replayed, _prov, _components = replay_with_provenance(
                    snapshot_bytes, ordered_hunks, rel
                )
            except owned_landing_refusal as exc:
                last_diagnostic = f"{rel}: [{label}] {exc}"
                continue
            except Exception as exc:  # malformed ledger entry etc. -- try next candidate
                last_diagnostic = f"{rel}: [{label}] {type(exc).__name__}: {exc}"
                continue
        if replayed == live_bytes or not require_full_coverage:
            # Same-cycle-only mode: the replay already succeeded without
            # error from its own declared starting point above (no
            # OwnedLandingRefusal, no malformed-ledger exception), which IS
            # the self-consistency this mode asks for. Whether it also
            # reaches every byte of the live file is the separate,
            # cross-cycle, non-blocking question -- never this one's.
            return True, ""
        if boundary_rule_available:
            closed, links, end_bytes = _follow_declared_claim_chain(
                project_root, dev_dir, own_bare_tid, rel, replayed, live_bytes
            )
            if closed:
                return True, ""
            if links:
                # Chain stopped short: report the UNION OF UNCLAIMED SPANS
                # past the last verified link, not everything after it. A
                # mid-chain hole makes later declarations unreachable from
                # the walk without making them undeclared, so subtracting
                # the stall position from the live size reports declared,
                # replay-verified spans as unclaimed -- see _unclaimed_spans.
                spans, covered = _unclaimed_spans(
                    project_root, dev_dir, own_bare_tid, rel,
                    len(end_bytes), len(live_bytes),
                )
                last_diagnostic = _span_shortfall_diagnostic(
                    rel, label, replayed, links, end_bytes, live_bytes, spans, covered
                )
                continue
        last_diagnostic = (
            f"{rel}: [{label}] replay produced {len(replayed)} bytes but live "
            f"worktree file has {len(live_bytes)} bytes (byte mismatch)"
        )

    if lane_candidates and len(lane_candidates) >= 2:
        # Every LANE-BLOCK candidate above failed. Before concluding there is
        # no explanation, try interleaving INDIVIDUAL hunks instead of whole
        # lane-blocks -- see `_chain_bounded_hunk_orderings` for why no
        # lane-block ordering, however it is permuted or chained, can express
        # a real concurrent-edit history that interleaves below lane-block
        # granularity (task 20261001-161041-interleave-fix).
        tried_starts: list[bytes] = []
        for snap_name, snap_declared, _ in lane_candidates:
            start_bytes, _snap_source = _resolve_baseline_snapshot(
                project_root, baseline_head_sha, rel, snap_declared
            )
            if start_bytes is None:
                continue
            extended_starts = [(start_bytes, snap_name)]
            if boundary_rule_available:
                # A foreign cycle's edits can sit on the shared working tree
                # BEFORE any of this cycle's own lanes started editing --
                # `_foreign_prefix_extend` is the prefix counterpart to the
                # suffix boundary chain already tried above.
                prefixed = _foreign_prefix_extend(
                    project_root, dev_dir, own_bare_tid, rel, start_bytes
                )
                if prefixed != start_bytes:
                    extended_starts.append((prefixed, snap_name + "+foreign-prefix"))
            for extended_start, start_label in extended_starts:
                if any(extended_start == seen for seen in tried_starts):
                    continue  # same bytes already searched from; skip the dup
                tried_starts.append(extended_start)
                for ordered_hunks, item_labels in _chain_bounded_hunk_orderings(
                    lane_candidates, extended_start, rel,
                    replay_with_provenance, owned_landing_refusal,
                    _MAX_COMPLETENESS_HUNK_BRANCH, _MAX_COMPLETENESS_HUNK_CHAIN_NODES,
                    dev_dir=dev_dir, own_bare_tid=own_bare_tid,
                ):
                    label = "snapshot=%s hunk-order=%s" % (start_label, "+".join(item_labels))
                    try:
                        replayed, _prov, _components = replay_with_provenance(
                            extended_start, ordered_hunks, rel
                        )
                    except owned_landing_refusal as exc:
                        last_diagnostic = f"{rel}: [{label}] {exc}"
                        continue
                    except Exception as exc:
                        last_diagnostic = f"{rel}: [{label}] {type(exc).__name__}: {exc}"
                        continue
                    if replayed == live_bytes or not require_full_coverage:
                        # Same reasoning as the lane-block site above: a
                        # successful (non-raising) interleaved replay is
                        # already same-cycle self-consistency; reaching every
                        # live byte is the separate cross-cycle question.
                        return True, ""
                    if boundary_rule_available:
                        closed, links, end_bytes = _follow_declared_claim_chain(
                            project_root, dev_dir, own_bare_tid, rel, replayed, live_bytes
                        )
                        if closed:
                            return True, ""
                        if links:
                            # Span-accounted exactly as the lane-block site
                            # above, through the one shared wording.
                            spans, covered = _unclaimed_spans(
                                project_root, dev_dir, own_bare_tid, rel,
                                len(end_bytes), len(live_bytes),
                            )
                            last_diagnostic = _span_shortfall_diagnostic(
                                rel, label, replayed, links, end_bytes, live_bytes,
                                spans, covered,
                            )
                            continue
                    last_diagnostic = (
                        f"{rel}: [{label}] replay produced {len(replayed)} bytes but live "
                        f"worktree file has {len(live_bytes)} bytes (byte mismatch)"
                    )

    return False, last_diagnostic or f"{rel}: no verifiable (snapshot, order) combination found"


def _tracked_at_baseline(project_root: Path, baseline_head_sha: str, rel: str) -> bool:
    """Whether rel existed in the git tree AT baseline_head_sha (backlog #99
    iteration 1, AC-6 fix). A file untracked AT CYCLE TIME but since
    committed by an unrelated/intervening commit (e.g. this same task-id's
    own earlier partial /commit of another lane) must stay skipped -- the
    live index/HEAD is not this check's reference point, baseline_head_sha
    is. When baseline_head_sha itself is empty (never true for a shard that
    passed _validate_shards, but _write_blocked_aggregate's own
    reconciliation-failure path can leave it '' on the aggregate), falls
    back to the current index so a missing baseline never makes this check
    MORE permissive than before this fix.
    """
    if not baseline_head_sha:
        rc, _, _ = _git(project_root, ["ls-files", "--error-unmatch", "--", rel])
        return rc == 0
    rc, _, _ = _git(project_root, ["cat-file", "-e", f"{baseline_head_sha}:{rel}"])
    return rc == 0


def _apply_completeness_check(
    aggregate: dict, project_root: Path, loaded: list[tuple[str, dict]] | None = None,
    same_cycle_only: bool = False,
) -> list[str]:
    """Backlog #99 criterion C, applied to every file in the final merged
    owned_edits. Files untracked AT baseline_head_sha are SKIPPED (AC-6):
    they are brand-new, whole-file-owned files, not hunk-stageable, and
    stage-owned-hunks.py's own new-file gate would EXCLUDE them for an
    unrelated reason. Scoped to baseline_head_sha (backlog #99 iteration
    1), NOT the live index/HEAD: a file legitimately untracked at cycle
    time that has since been committed by an unrelated/intervening commit
    must stay skipped, since the live index would otherwise wrongly
    re-include it and route its legitimate whole-file-creation hunk into
    this tracked-file replay check. Returns a list of diagnostic strings;
    empty means the union is complete for every file tracked at baseline
    that was checked.

    `loaded` (task 20261001-close-multilane-stall): the per-lane shards this
    aggregate was built from. When supplied, recovers each declaring lane's
    OWN (snapshot, hunks) pair per file (via `_lane_candidates_for_file`,
    folding in superseded rounds exactly as `_build_aggregate` does) so
    `_completeness_check_file` can try the declaring lanes' own (snapshot,
    order) combinations instead of assuming shard-alphabetical order is
    dependency order. Optional and defaulting to None for back-compat with
    direct callers (e.g. pre-existing tests) that pre-date this parameter;
    those fall back to the single merged-candidate path, unchanged.

    `same_cycle_only` (task dev-20260927-135305, default False = today's
    full, cross-cycle-aware, GLOBAL-completeness question, unchanged): when
    True, every per-file check is made with
    `_completeness_check_file(..., require_full_coverage=False)`, which never
    requires reaching every live byte -- only that THIS cycle's own
    declaring lane(s) (plus its own non-lane parent_cycle claimants, which
    `claimants` below already is) replay without internal conflict from
    their own declared starting point. This is the narrower question meant
    to GATE a cycle's own close (OWNERSHIP_COMPLETENESS_BLOCKING_KEY); the
    default (False) call keeps producing the broader forensic diagnostic
    (OWNERSHIP_COMPLETENESS_GAP's informational channel) that must never
    itself block since it can depend on an unrelated, still-active session's
    undeclared bytes."""
    owned = aggregate.get("owned_edits")
    if not isinstance(owned, dict) or not owned:
        return []
    snapshots = aggregate.get("pre_edit_snapshots")
    snapshots = snapshots if isinstance(snapshots, dict) else {}
    baseline_head_sha = aggregate.get("baseline_head_sha") or ""
    dev_dir = _resolve_dev_dir(project_root)
    own_bare_tid = _bare_task_id(str(aggregate.get("task_id") or ""))
    expanded_shards = None
    if loaded:
        try:
            expanded_shards = _expand_shards_with_superseded_rounds(
                loaded, dev_dir, own_bare_tid,
            )
        except Exception:
            expanded_shards = None
    claimants = _cycle_claimant_index(
        dev_dir, own_bare_tid, str(aggregate.get("task_id") or "")
    )
    diagnostics: list[str] = []
    for rel in sorted(owned):
        if not _tracked_at_baseline(project_root, baseline_head_sha, rel):
            continue  # untracked at baseline / new-at-cycle-time -- AC-6, skip
        lane_candidates = (
            _lane_candidates_for_file(expanded_shards, rel) if expanded_shards else None
        )
        ok, diagnostic = _completeness_check_file(
            project_root, baseline_head_sha, rel, owned[rel], snapshots.get(rel),
            lane_candidates=lane_candidates,
            dev_dir=dev_dir, own_bare_tid=own_bare_tid,
            require_full_coverage=not same_cycle_only,
        )
        if not ok and claimants.get(rel):
            # Widen to this cycle's non-lane claimants ONLY after the lane-only
            # check has already failed, and keep the LANE-ONLY diagnostic when
            # widening does not help either.  Widening can therefore only turn
            # a FAIL into a PASS: no gap class becomes unreachable, and no
            # still-failing file loses its lane-anchored diagnostic for a less
            # informative one produced by a longer candidate set.  That last
            # clause is measured, not assumed: widening unconditionally
            # replaced this repository's own "...N of the M live bytes claimed
            # by no declaration" figure on scripts/aggregate-dev-report.py
            # with a bare BOUNDARY_INDETERMINATE from a deeper permutation.
            widened = _lane_candidates_for_file(
                expanded_shards or [], rel,
                cycle_claimants=claimants[rel], project_root=project_root,
            )
            if len(widened) > len(lane_candidates or []):
                ok, _widened_diagnostic = _completeness_check_file(
                    project_root, baseline_head_sha, rel, owned[rel],
                    snapshots.get(rel), lane_candidates=widened,
                    dev_dir=dev_dir, own_bare_tid=own_bare_tid,
                    require_full_coverage=not same_cycle_only,
                )
        if not ok:
            diagnostics.append(diagnostic)
    return diagnostics


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aggregate-dev-report.py",
        description="Write canonical aggregate dev-report for parallel-dev cycles.",
    )
    parser.add_argument(
        "--task-id",
        required=True,
        help="Task-id for the parallel-dev cycle (e.g. dev-20260524-170335 or 20260524-170335).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Validate shards without writing the canonical aggregate.",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    task_id = args.task_id.strip()
    if not task_id:
        _emit_error("--task-id must be non-empty")
        return 2

    # Bare timestamp needed for shard filename matching (patterns use YYYYMMDD-HHMMSS).
    bare_tid = _bare_task_id(task_id)

    project_root = _resolve_project_root()
    dev_dir = _resolve_dev_dir(project_root)
    # Canonical path uses the FULL task_id (not bare timestamp) so that
    # dev-report-dev-20260524-170335.json ≠ dev-report-20260524-170335.json.
    canonical_path = dev_dir / f"dev-report-{task_id}.json"

    # Scan for shards scoped to this task-id (using bare timestamp for pattern matching).
    shards_info = _scan_shards(dev_dir, bare_tid, task_id)

    # Full scanned label roster, independent of load/validate outcome — used
    # as parallel_workers on a blocked aggregate (R29).
    full_roster = [label for label, _ in shards_info]

    if len(shards_info) < 2:
        # <=1 shard is not a parallel cycle UNLESS a pre-existing canonical's
        # OWN recorded roster establishes that it was (Layer-Escalation
        # Review item F, AC-09): silently skipping in that case would abandon
        # a multi-worker canonical's evidence just because the CURRENT scan
        # no longer sees every worker -- squarely the user's own "shard
        # count/roster mismatch" complaint category.
        skip_reason = (
            f"Found {len(shards_info)} worker shard(s) for task-id {task_id!r}; "
            "parallel aggregation requires >=2."
        )
        if not canonical_path.exists():
            _emit_ok(action="skipped", output_path=str(canonical_path), reason=skip_reason,
                     extra=_outcome_fields(None, [], shards_info))
            return 0

        existing_doc, _ = _load_shard_with_diagnostic(canonical_path)
        if existing_doc is not None and "parallel_workers" not in existing_doc:
            # The existing canonical has no `parallel_workers` key AT ALL.
            # _build_aggregate (the ONLY producer of an aggregate-shaped
            # document, via either the successful path or
            # _write_blocked_aggregate) always sets this key -- even to an
            # empty list -- on every document it writes. Total absence
            # therefore proves this canonical was NEVER built via
            # _build_aggregate: it is a genuine SINGULAR dev-report written
            # directly by a dev subagent per agents/dev.md's own Output
            # Format schema, which has no parallel_workers concept at all --
            # this was never an aggregate cycle to begin with. Total absence
            # must never be read as "ambiguous, assume parallel": that
            # conflation previously caused this skip branch to silently
            # overwrite a plain, non-fan-out /dev cycle's own canonical
            # dev-report with a generic blocked aggregate the moment
            # /close's Step 0 invoked this script (the single most common
            # invocation shape) -- see
            # test_len_below_2_singular_dev_report_with_no_parallel_workers_key_is_skipped_untouched.
            #
            # backlog #122 M3: before the no-op return, merge any
            # hook-authored side-effect-file declarations (hooks/doc_sync/
            # hook_ledger.py's write side) into this genuine singular
            # report's files_landed_whole exemption channel, so a
            # hook-regenerated file (e.g. an INDEX.md doc-sync rewrites as a
            # side effect of a dev cycle's own edit) gets a legitimate
            # declaration path into build_plan()'s ownership gate. Writes
            # ONLY when there is something new to merge -- an empty or
            # absent ledger leaves this branch's own untouched guarantee
            # (see test_len_below_2_singular_dev_report_with_no_parallel_
            # workers_key_is_skipped_untouched) unaffected. `action` stays
            # "skipped" either way -- this insertion never invents a 4th
            # action value.
            ledger_discovery = _hook_ledger_discovery(project_root, task_id)
            if _merge_hook_ledger_into_singular(existing_doc, ledger_discovery, project_root):
                _atomic_write_json(canonical_path, existing_doc)
            _emit_ok(action="skipped", output_path=str(canonical_path), reason=skip_reason,
                     extra=_outcome_fields(_shard_status(existing_doc), [], shards_info))
            return 0

        existing_roster_usable = existing_doc is not None and _is_str_list(
            existing_doc.get("parallel_workers")
        )
        if existing_roster_usable:
            combined_roster = sorted(
                (Counter(existing_doc["parallel_workers"]) | Counter(full_roster)).elements()
            )
            if len(combined_roster) < 2:
                _emit_ok(action="skipped", output_path=str(canonical_path), reason=skip_reason,
                         extra=_outcome_fields(_shard_status(existing_doc), [], shards_info))
                return 0

        # Do not skip: the existing canonical's presence (item F/G --
        # presence, not readability, withholds the skip) either establishes
        # >=2 workers or cannot be confirmed to cover fewer than 2. Load
        # whatever 0 or 1 shard(s) the current scan DID find and write a
        # blocked aggregate naming what is missing/unusable.
        loaded, load_failures = _load_all_shards(shards_info)
        mismatch_entries = [
            f"shard '{label}': failed to load: {err}" for label, err in load_failures
        ]
        if not existing_roster_usable:
            mismatch_entries.append(
                f"existing canonical {canonical_path} roster could not be confirmed as "
                "covering fewer than 2 workers (unreadable, malformed, or wrong-typed "
                "parallel_workers); treating this cycle as parallel"
            )
            # Unknown roster -- "missing" cannot be enumerated, so the
            # Part-C1 reaggregate-with-shrunk_from decision does not apply
            # here; this sub-case is unchanged from before this ticket.
            _emit_error(
                "Shard roster mismatch (fewer than 2 shards found this scan, but "
                "an existing canonical established a larger parallel roster):\n  "
                + "\n  ".join(mismatch_entries)
            )
            return _write_blocked_aggregate(
                loaded, task_id, full_roster, mismatch_entries, canonical_path, args.dry_run
            )
        # _reconcile_write_time (called inside _write_blocked_aggregate, when
        # that fallback path is taken below) independently recomputes this
        # exact missing-shard roster-diff against the same existing
        # canonical and appends the byte-identical disclosure to
        # blocking_issues itself (item E). Keep it in `mismatch_entries` for
        # the stderr diagnostic immediately below, but exclude it from what
        # is handed onward so the same fact is not written into
        # blocking_issues twice (QA round-4 code-quality finding).
        write_mismatch_entries = list(mismatch_entries)
        missing = Counter(existing_doc["parallel_workers"]) - Counter(full_roster)
        missing_labels = sorted(missing.elements())
        for label, count in sorted(missing.items()):
            mismatch_entries.append(
                f"shard '{label}': existing canonical's parallel_workers records "
                f"{count} occurrence(s) no longer found in the current scan"
            )
        # Preserve the stderr diagnostic here too, matching the load-failure
        # and validate-failure branches above and the module docstring's own
        # claim (lines 32-43) -- the file write must never be the ONLY signal
        # of this mismatch (QA round-3 code-quality finding, this revision).
        _emit_error(
            "Shard roster mismatch (fewer than 2 shards found this scan, but "
            "an existing canonical established a larger parallel roster):\n  "
            + "\n  ".join(mismatch_entries)
        )
        return _reaggregate_with_shrunk_from_or_block(
            loaded, task_id, full_roster, missing_labels, write_mismatch_entries,
            canonical_path, args.dry_run, dev_dir, bare_tid, None, existing_doc,
        )

    # Load all shards, collecting EVERY load outcome instead of returning on
    # the first failure (R29 -- a builder here must not assume >=1 loaded
    # shard; the all-fail case is possible and must not crash).
    loaded, load_failures = _load_all_shards(shards_info)

    if load_failures:
        # At least one shard failed to load: do NOT run _validate_shards
        # against the incomplete loaded subset -- a lane that failed to load
        # could otherwise be misreported by the cross-shard validator as "not
        # among the shards" (codex round-1 finding 3).
        _emit_error(
            "Failed to load shard(s):\n  "
            + "\n  ".join(f"'{label}': {err}" for label, err in load_failures)
        )
        mismatch_entries = [
            f"shard '{label}': failed to load: {err}" for label, err in load_failures
        ]
        return _write_blocked_aggregate(
            loaded, task_id, full_roster, mismatch_entries, canonical_path, args.dry_run
        )

    # A blocked lane can be legitimate only through the resolver's deviation
    # provider, so it is fetched (fail closed to None) only when some shard is
    # blocked: no other document is affected by it.
    deviation = _load_deviation_provider() if _has_blocked_shard(loaded) else None

    # Validate consistency — fail closed on any mismatch.  project_root opts
    # this call in to the serialized-fan-out route (a divergence a lane
    # DECLARES and the resolver's adjudicator fully verifies); a set that
    # declares nothing is adjudicated by the untouched equality invariant.
    errors = _validate_shards(
        loaded, task_id, deviation=deviation, project_root=project_root
    )
    if errors:
        _emit_error("Shard validation failed:\n  " + "\n  ".join(errors))
        return _write_blocked_aggregate(
            loaded, task_id, full_roster, errors, canonical_path, args.dry_run
        )

    if canonical_path.exists():
        # Preserve the legacy fail-closed identity/baseline checks, then
        # compare the aggregate projection for freshness.
        try:
            existing = json.loads(canonical_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            _emit_error(f"Cannot read existing canonical {canonical_path}: {exc}")
            return 1
        expected_workers = sorted(label for label, _ in loaded)
        existing_workers = sorted(existing.get("parallel_workers") or [])
        expected_sha = next((d.get("baseline_head_sha", "") for _, d in loaded), "")
        existing_sha = existing.get("baseline_head_sha", "")
        # No sha bypass survives for ANY predecessor dev.status
        # (Layer-Escalation Review item A) -- recovery from a genuine sha
        # conflict is manual, for a 'blocked' predecessor exactly as it
        # already was for 'completed'/'needs_review'. Two prior
        # dev-implementation rounds (a naive blocking_issues substring
        # match; an explicit `_sha_provenance` corroboration marker) were
        # each rejected by QA's live adversarial reproduction for producing
        # a NEW instance of the "mismatch silently resolved as success"
        # class this ticket exists to eliminate -- see AC-08.
        #
        # Multiset (Counter) containment, not plain set containment, for the
        # workers check too (item H, generalizing what revision 6/7 already
        # used for a 'blocked' predecessor to EVERY predecessor status): a
        # duplicated worker-label occurrence a predecessor recorded is
        # meaningful evidence (>=2 real shard files sharing a label), never
        # silently collapsed by treating {'A','B'} as satisfying
        # {'A','A','B'}. Each clause is appended only when its OWN
        # comparison fails, so a message can never render "X (expected X)"
        # with identical values.
        workers_missing = Counter(existing_workers) - Counter(expected_workers)
        sha_stale = existing_sha != expected_sha
        if sha_stale:
            # No sha bypass survives, exactly as before this ticket (Part
            # C1 only touches the workers-only mismatch sub-case below --
            # Layer-Escalation Review item A stays hard-blocked).
            stale_clauses = []
            if workers_missing:
                stale_clauses.append(
                    f"workers {existing_workers} (expected {expected_workers})"
                )
            stale_clauses.append(
                f"baseline_sha {existing_sha!r} (expected {expected_sha!r})"
            )
            _emit_error(
                f"Existing canonical {canonical_path} is stale: "
                + ", ".join(stale_clauses)
            )
            return 1
        if workers_missing:
            # ticket-20260930-132644-l8 Part C1, Branch B: the ONLY stale
            # clause is a workers shrink (no baseline_sha mismatch) -- never
            # hard-exit without writing (M5); branch exactly as Branch A.
            missing_labels = sorted(workers_missing.elements())
            mismatch_entries = [
                f"shard '{label}': existing canonical's parallel_workers records "
                f"{count} occurrence(s) no longer found in the current scan"
                for label, count in sorted(workers_missing.items())
            ]
            _emit_error(
                f"Existing canonical {canonical_path} is stale: "
                f"workers {existing_workers} (expected {expected_workers})"
            )
            return _reaggregate_with_shrunk_from_or_block(
                loaded, task_id, full_roster, missing_labels, mismatch_entries,
                canonical_path, args.dry_run, dev_dir, bare_tid, deviation, existing,
            )
        expected = _build_aggregate(loaded, task_id, deviation=deviation)
        # A refresh must not erase audit history the builder has no opinion
        # about; see _carry_forward_unbuilt_keys.  Done before the freshness
        # comparison below so a canonical that differs ONLY by preserved keys
        # is still recognised as fresh and is not rewritten pointlessly.
        _carry_forward_unbuilt_keys(expected, canonical_path)
        completeness_gaps = (
            [] if args.dry_run else _apply_completeness_check(expected, project_root, loaded)
        )
        # same_cycle_only=True is the GATING question (task dev-20260927-
        # 135305): never depends on whether some OTHER, possibly still-
        # active, session has declared its bytes in a shared file yet. The
        # full cross-cycle-aware `completeness_gaps` above keeps being
        # computed and stored, unchanged, as non-blocking forensic
        # information -- see OWNERSHIP_COMPLETENESS_BLOCKING_KEY.
        blocking_completeness_gaps = (
            [] if args.dry_run
            else _apply_completeness_check(
                expected, project_root, loaded, same_cycle_only=True
            )
        )
        if not args.dry_run:
            # Assigned UNCONDITIONALLY, empty list included: a cleared gap must
            # erase the record of the gap that is gone, never leave the last
            # non-empty measurement standing as if it were current.  See
            # COMPLETENESS_GAPS_KEY for why this is not `blocking_issues`.
            expected[COMPLETENESS_GAPS_KEY] = completeness_gaps
            expected[OWNERSHIP_COMPLETENESS_BLOCKING_KEY] = blocking_completeness_gaps
        if blocking_completeness_gaps:
            try:
                _atomic_write_json(canonical_path, expected)
            except OSError as exc:
                _emit_error(f"Cannot write canonical aggregate at {canonical_path}: {exc}")
                return 1
            _emit_error(
                "Completeness check failed (backlog #99 criterion C, same-cycle scope):\n  "
                + "\n  ".join(blocking_completeness_gaps)
            )
            return 1
        if _canonical_projection(existing, deviation) != _canonical_projection(
            expected, deviation
        ):
            if args.dry_run:
                _emit_ok(
                    action="skipped",
                    output_path=str(canonical_path),
                    reason=(
                        f"Dry-run: existing canonical is stale and would be refreshed "
                        f"from {len(loaded)} current shards for task-id {task_id!r}."
                    ),
                    extra=_outcome_fields(expected["dev"]["status"], loaded, shards_info),
                )
                return 0
            try:
                _atomic_write_json(canonical_path, expected)
            except OSError as exc:
                _emit_error(f"Cannot refresh canonical aggregate at {canonical_path}: {exc}")
                return 1
            _emit_ok(
                action="aggregated",
                output_path=str(canonical_path),
                reason=(
                    f"Refreshed stale canonical from {len(loaded)} current shards "
                    f"for task-id {task_id!r}."
                ),
                extra=_outcome_fields(expected["dev"]["status"], loaded, shards_info),
            )
            return 0
        _emit_ok(
            action="validated",
            output_path=str(canonical_path),
            reason=f"Canonical aggregate already exists and matches {len(loaded)} shards for task-id {task_id!r}.",
            extra=_outcome_fields(expected["dev"]["status"], loaded, shards_info),
        )
        return 0

    if args.dry_run:
        _emit_ok(
            action="skipped",
            output_path=str(canonical_path),
            reason=f"Dry-run: would aggregate {len(loaded)} shards for task-id {task_id!r}.",
            extra=_outcome_fields(
                _build_aggregate(loaded, task_id, deviation=deviation)["dev"]["status"],
                loaded, shards_info,
            ),
        )
        return 0

    # Build and write canonical aggregate.
    aggregate = _build_aggregate(loaded, task_id, deviation=deviation)
    completeness_gaps = _apply_completeness_check(aggregate, project_root, loaded)
    # same_cycle_only=True is the GATING question; see the refresh path above
    # and OWNERSHIP_COMPLETENESS_BLOCKING_KEY for why `completeness_gaps`
    # (full, cross-cycle-aware) must never itself drive `return 1`.
    blocking_completeness_gaps = _apply_completeness_check(
        aggregate, project_root, loaded, same_cycle_only=True
    )
    # Same unconditional assignment as the refresh path above; this branch is
    # already past the dry-run early return, so there is no dry-run guard here.
    aggregate[COMPLETENESS_GAPS_KEY] = completeness_gaps
    aggregate[OWNERSHIP_COMPLETENESS_BLOCKING_KEY] = blocking_completeness_gaps
    if blocking_completeness_gaps:
        try:
            _atomic_write_json(canonical_path, aggregate)
        except OSError as exc:
            _emit_error(f"Cannot write canonical aggregate to {canonical_path}: {exc}")
            return 1
        _emit_error(
            "Completeness check failed (backlog #99 criterion C, same-cycle scope):\n  "
            + "\n  ".join(blocking_completeness_gaps)
        )
        return 1
    try:
        _atomic_write_json(canonical_path, aggregate)
    except OSError as exc:
        _emit_error(f"Cannot write canonical aggregate to {canonical_path}: {exc}")
        return 1

    _emit_ok(
        action="aggregated",
        output_path=str(canonical_path),
        reason=f"Aggregated {len(loaded)} worker shards into {canonical_path}.",
        extra=_outcome_fields(aggregate["dev"]["status"], loaded, shards_info),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
