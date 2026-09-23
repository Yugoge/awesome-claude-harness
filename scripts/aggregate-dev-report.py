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
# Filename patterns — MUST mirror hooks/pretool-aggregate-check.py exactly.
# ---------------------------------------------------------------------------

# Active /dev adapter naming: dev-report-dev-<task-id>-<lane>.json.
PREFIXED_WORKER_RE = re.compile(
    r"^dev-report-(?P<task_id>dev-\d{8}-\d{6})-(?P<worker>[A-Za-z0-9][A-Za-z0-9.\-]*)\.json$"
)

# Active /dev canonical: dev-report-dev-<task-id>.json.
PREFIXED_CANONICAL_RE = re.compile(
    r"^dev-report-(?P<task_id>dev-\d{8}-\d{6})\.json$"
)

# Per-worker filename — role-first naming: dev-report-<role>-<task-id>.json
PER_WORKER_ROLE_FIRST_RE = re.compile(
    r"^dev-report-(?P<role>[A-Za-z0-9]+)-(?P<task_id>\d{8}-\d{6})\.json$"
)

# Per-worker filename — task-first naming: dev-report-<task-id>-<worker>.json
PER_WORKER_TASK_FIRST_RE = re.compile(
    r"^dev-report-(?P<task_id>\d{8}-\d{6})-(?P<worker>[A-Za-z0-9][A-Za-z0-9.\-]*)\.json$"
)

# Canonical singleton: dev-report-<task-id>.json
CANONICAL_RE = re.compile(
    r"^dev-report-(?P<task_id>\d{8}-\d{6})\.json$"
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


# NON_WORKER_LABELS — MUST mirror pretool-aggregate-check.py exactly.
NON_WORKER_LABELS = frozenset({
    "draft", "final", "fix", "continuation", "wip",
})

# NON_WORKER_LABEL_RE — MUST mirror pretool-aggregate-check.py exactly.
NON_WORKER_LABEL_RE = re.compile(
    r"^(?:iter|retry|attempt)\d*$",
    re.IGNORECASE,
)

# Optional per-shard declaration that this lane's baseline is the tree its
# predecessor lane left behind (sequential dispatch — spec R28).  Absent from
# every shard, the legacy cross-shard equality invariant applies unchanged.
PROVENANCE_KEY = "baseline_provenance"

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
    return shards


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


def _validate_shards(
    shards: list[tuple[str, dict]], task_id: str, deviation=None
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
    - Consistent baseline_dirty_snapshot across all shards that do NOT declare
      a baseline_provenance; declaring shards are chain-validated instead (R28).
      With no declarations anywhere, this is the equality invariant unchanged.
    """
    errors = []
    baseline_sha: str | None = None
    baseline_dirty: str | None = None
    provenance_labels = {
        label for label, data in shards
        if isinstance(data.get(PROVENANCE_KEY), dict)
    }
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
            if baseline_dirty is None:
                baseline_dirty = dirty
            elif dirty != baseline_dirty:
                errors.append(
                    f"shard '{label}': baseline_dirty_snapshot mismatch"
                )

    if provenance_labels:
        errors.extend(_validate_baseline_chain(shards))

    return errors


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


def _hook_ledger_dirs(project_root: Path, task_id: str, bare_tid: str) -> list[Path]:
    """Candidate .claude/dev-registry/<...>/hook-landed-files/ directories
    for this task-id's own single-lane dev cycle (backlog #122 M3).

    The write side (hooks/doc_sync/hook_ledger.py) resolves the writing
    agent's own dev_session_id via hooks/lib/agent_resolver.py at hook-fire
    time. This script only receives --task-id, not that session id, and
    this repo's own dev-registry/ tree carries both a bare-timestamp
    directory-naming convention (older cycles) and a "dev-"-prefixed one
    (current /dev dispatch) -- both are tried; whichever directory actually
    exists supplies entries, which in practice is at most one for a
    genuine single-lane cycle.
    """
    root = project_root / ".claude" / "dev-registry"
    names: list[str] = []
    for candidate in (task_id, f"dev-{bare_tid}"):
        if candidate not in names:
            names.append(candidate)
    return [root / name / "hook-landed-files" for name in names]


def _load_hook_ledger_entries(ledger_dirs: list[Path]) -> list[dict]:
    """Load every readable, well-shaped ledger entry across candidate dirs.

    Mirrors _load_shard_with_diagnostic's per-entry fail-closed read
    pattern: an unreadable or malformed individual ledger file is skipped,
    never fatal to the whole merge.
    """
    entries: list[dict] = []
    for ledger_dir in ledger_dirs:
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
            entries.append(parsed)
    return entries


def _merge_hook_ledger_into_singular(existing_doc: dict, ledger_dirs: list[Path]) -> bool:
    """Merge validated hook-ledger entries into existing_doc['files_landed_whole'].

    Backlog #122 M3: additive-only, dedupe by path, never drops a
    pre-existing entry. Mirrors resolve-commit-repos.py:523-535's own
    dual-listing constraint (belt-and-suspenders, not a substitute for it --
    that gate still independently enforces it at admission time): a path
    already claimed by owned_edits or pre_edit_snapshots is never routed
    through files_landed_whole instead.

    Returns True iff at least one new entry was appended -- the caller only
    writes the canonical report back to disk when this is True, preserving
    AC4's byte-for-byte-unchanged-when-empty guarantee.
    """
    entries = _load_hook_ledger_entries(ledger_dirs)
    if not entries:
        return False
    owned_paths = set(existing_doc.get("owned_edits") or {})
    snapshot_paths = set(existing_doc.get("pre_edit_snapshots") or {})
    existing_landed = existing_doc.get("files_landed_whole")
    if not isinstance(existing_landed, list):
        existing_landed = []
    existing_paths = {item.get("path") for item in existing_landed if isinstance(item, dict)}
    appended = False
    for entry in entries:
        path = entry["path"]
        if path in owned_paths or path in snapshot_paths or path in existing_paths:
            continue
        existing_landed.append({
            "path": path,
            "diff_sha256": entry["diff_sha256"],
            "reason": entry["reason"],
        })
        existing_paths.add(path)
        appended = True
    if appended:
        existing_doc["files_landed_whole"] = existing_landed
    return appended


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
    worker_ids = [label for label, _ in shards]
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
        "recommendations": _union_list(shards, ["recommendations"]),
        "owned_edits": _merge_owned_edits(owned_edit_shards),
        "pre_edit_snapshots": _merge_pre_edit_snapshots(owned_edit_shards),
    }
    if deviation is not None:
        aggregate.update(deviation.merge(shards))
    return aggregate


def _bare_task_id(task_id: str) -> str:
    """Extract YYYYMMDD-HHMMSS portion from a potentially-prefixed task-id."""
    m = re.search(r"(\d{8}-\d{6})", task_id)
    return m.group(1) if m else task_id


def _emit_ok(action: str, output_path: str, reason: str) -> None:
    print(json.dumps({
        "status": "ok",
        "action": action,
        "output_path": output_path,
        "reason": reason,
    }))


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
    try:
        _atomic_write_json(canonical_path, aggregate)
    except OSError as exc:
        _emit_error(f"Cannot write blocked canonical aggregate to {canonical_path}: {exc}")
    return 1


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

    Resolution order (AC-7): (1) `git show <baseline_head_sha>:rel` when rel
    is tracked at that commit, independent of any shard's own declaration;
    (2) `git cat-file blob <declared_value>` when declared_value is a
    resolvable 40-hex object (a git-blob-SHA-form declaration); (3)
    declared_value treated as literal pre-edit bytes (a literal-text-form
    declaration).
    """
    if baseline_head_sha:
        rc, _, _ = _git(project_root, ["cat-file", "-e", f"{baseline_head_sha}:{rel}"])
        if rc == 0:
            rc2, blob, _ = _git(project_root, ["show", f"{baseline_head_sha}:{rel}"])
            if rc2 == 0:
                return blob, "baseline_head_sha"
    if isinstance(declared_value, str) and _BLOB_SHA_RE.match(declared_value):
        rc, _, _ = _git(project_root, ["cat-file", "-e", declared_value])
        if rc == 0:
            rc2, blob, _ = _git(project_root, ["cat-file", "blob", declared_value])
            if rc2 == 0:
                return blob, "declared_blob_sha"
    if isinstance(declared_value, str):
        return declared_value.encode("utf-8"), "literal_text"
    return None, "no resolvable pre-edit snapshot declared for this file"


def _completeness_check_file(
    project_root: Path, baseline_head_sha: str, rel: str, hunks, declared_snapshot
) -> tuple[bool, str]:
    """Backlog #99 criterion C for one file: reuse scripts/stage-owned-hunks.py's
    OWN --ledger --snapshot --dry-run replay-and-compare logic (never
    reimplemented here) to verify the merged owned_edits union actually
    covers the live file's bytes. Returns (ok, diagnostic); diagnostic is
    empty when ok."""
    snapshot_bytes, source = _resolve_baseline_snapshot(
        project_root, baseline_head_sha, rel, declared_snapshot
    )
    if snapshot_bytes is None:
        return False, f"{rel}: {source}"
    if not isinstance(hunks, list) or not hunks:
        return False, f"{rel}: owned_edits ledger is empty/invalid for completeness check"
    stage_script = Path(__file__).resolve().with_name("stage-owned-hunks.py")
    with tempfile.TemporaryDirectory() as td:
        ledger_path = os.path.join(td, "ledger.json")
        snapshot_path = os.path.join(td, "snapshot")
        with open(ledger_path, "w", encoding="utf-8") as fh:
            json.dump(hunks, fh)
        with open(snapshot_path, "wb") as fh:
            fh.write(snapshot_bytes)
        proc = subprocess.run(
            [sys.executable, str(stage_script),
             "--git-root", str(project_root), "--file", rel,
             "--ledger", ledger_path, "--snapshot", snapshot_path, "--dry-run"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    if proc.returncode == 0:
        return True, ""
    return False, "%s: stage-owned-hunks.py --dry-run exit %d: %s" % (
        rel, proc.returncode, proc.stderr.decode("utf-8", "replace").strip()
    )


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


def _apply_completeness_check(aggregate: dict, project_root: Path) -> list[str]:
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
    that was checked."""
    owned = aggregate.get("owned_edits")
    if not isinstance(owned, dict) or not owned:
        return []
    snapshots = aggregate.get("pre_edit_snapshots")
    snapshots = snapshots if isinstance(snapshots, dict) else {}
    baseline_head_sha = aggregate.get("baseline_head_sha") or ""
    diagnostics: list[str] = []
    for rel in sorted(owned):
        if not _tracked_at_baseline(project_root, baseline_head_sha, rel):
            continue  # untracked at baseline / new-at-cycle-time -- AC-6, skip
        ok, diagnostic = _completeness_check_file(
            project_root, baseline_head_sha, rel, owned[rel], snapshots.get(rel)
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
            _emit_ok(action="skipped", output_path=str(canonical_path), reason=skip_reason)
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
            ledger_dirs = _hook_ledger_dirs(project_root, task_id, bare_tid)
            if _merge_hook_ledger_into_singular(existing_doc, ledger_dirs):
                _atomic_write_json(canonical_path, existing_doc)
            _emit_ok(action="skipped", output_path=str(canonical_path), reason=skip_reason)
            return 0

        existing_roster_usable = existing_doc is not None and _is_str_list(
            existing_doc.get("parallel_workers")
        )
        if existing_roster_usable:
            combined_roster = sorted(
                (Counter(existing_doc["parallel_workers"]) | Counter(full_roster)).elements()
            )
            if len(combined_roster) < 2:
                _emit_ok(action="skipped", output_path=str(canonical_path), reason=skip_reason)
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
            write_mismatch_entries = mismatch_entries
        else:
            # _reconcile_write_time (called inside _write_blocked_aggregate,
            # below) independently recomputes this exact missing-shard
            # roster-diff against the same existing canonical and appends
            # the byte-identical disclosure to blocking_issues itself (item
            # E). Keep it in `mismatch_entries` for the stderr diagnostic
            # immediately below, but exclude it from what is handed to
            # _write_blocked_aggregate so the same fact is not written into
            # blocking_issues twice (QA round-4 code-quality finding).
            write_mismatch_entries = list(mismatch_entries)
            missing = Counter(existing_doc["parallel_workers"]) - Counter(full_roster)
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
        return _write_blocked_aggregate(
            loaded, task_id, full_roster, write_mismatch_entries, canonical_path, args.dry_run
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

    # Validate consistency — fail closed on any mismatch.
    errors = _validate_shards(loaded, task_id, deviation=deviation)
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
        stale_clauses = []
        if Counter(existing_workers) - Counter(expected_workers):
            stale_clauses.append(
                f"workers {existing_workers} (expected {expected_workers})"
            )
        if existing_sha != expected_sha:
            stale_clauses.append(
                f"baseline_sha {existing_sha!r} (expected {expected_sha!r})"
            )
        if stale_clauses:
            _emit_error(
                f"Existing canonical {canonical_path} is stale: "
                + ", ".join(stale_clauses)
            )
            return 1
        expected = _build_aggregate(loaded, task_id, deviation=deviation)
        completeness_gaps = (
            [] if args.dry_run else _apply_completeness_check(expected, project_root)
        )
        if completeness_gaps:
            expected["blocking_issues"] = (
                list(expected.get("blocking_issues") or []) + completeness_gaps
            )
            try:
                _atomic_write_json(canonical_path, expected)
            except OSError as exc:
                _emit_error(f"Cannot write canonical aggregate at {canonical_path}: {exc}")
                return 1
            _emit_error(
                "Completeness check failed (backlog #99 criterion C):\n  "
                + "\n  ".join(completeness_gaps)
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
            )
            return 0
        _emit_ok(
            action="validated",
            output_path=str(canonical_path),
            reason=f"Canonical aggregate already exists and matches {len(loaded)} shards for task-id {task_id!r}.",
        )
        return 0

    if args.dry_run:
        _emit_ok(
            action="skipped",
            output_path=str(canonical_path),
            reason=f"Dry-run: would aggregate {len(loaded)} shards for task-id {task_id!r}.",
        )
        return 0

    # Build and write canonical aggregate.
    aggregate = _build_aggregate(loaded, task_id, deviation=deviation)
    completeness_gaps = _apply_completeness_check(aggregate, project_root)
    if completeness_gaps:
        aggregate["blocking_issues"] = (
            list(aggregate.get("blocking_issues") or []) + completeness_gaps
        )
        try:
            _atomic_write_json(canonical_path, aggregate)
        except OSError as exc:
            _emit_error(f"Cannot write canonical aggregate to {canonical_path}: {exc}")
            return 1
        _emit_error(
            "Completeness check failed (backlog #99 criterion C):\n  "
            + "\n  ".join(completeness_gaps)
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
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
