#!/usr/bin/env python3
"""PreToolUse Hook (Agent matcher): Enforce canonical aggregate dev-report
existence before allowing the orchestrator to dispatch the QA subagent in
parallel-dev cycles.

Predicate: BLOCK (exit 2) iff
  (a) docs/dev/ contains >=2 files matching dev-report-<role>-<task-id>.json
      sharing the same <task-id>, AND
  (b) the canonical singular dev-report-<task-id>.json is absent for that
      task-id.
Otherwise: silent exit 0.

Triggers ONLY for Agent tool calls dispatching subagent_type=qa. Other Agent
dispatches (ba, dev, specialists, etc.) are not gated -- the rule is that
the aggregate must exist BEFORE QA reads it.

Fail-open contract: parsing failures, missing stdin, missing project dir,
unexpected exceptions -> exit 0. Never crash the orchestrator on a self-bug.

Filename patterns (BOTH supported as of BUG-AGGCHK-1 fix):
  Role-first:  dev-report-<role>-<task-id>.json
    role     := alphanumeric (no dashes), e.g. R1, ba, qa
    task-id  := \\d{8}-\\d{6} (YYYYMMDD-HHMMSS)
  Task-first:  dev-report-<task-id>-<worker>.json
    task-id  := \\d{8}-\\d{6} (YYYYMMDD-HHMMSS)
    worker   := alphanumeric+dot (e.g. T3.2, T3.6-iter2 -> the part after
                the task-id, no anchored format restriction beyond
                "non-canonical, non-trivial")
  Canonical:   dev-report-<task-id>.json   (the aggregate singleton)

The canonical singular MUST be excluded from per-worker matches; it is the
target of the aggregate write that this hook gates.

Task-id scoping (BUG-AGGCHK-2 fix; iter2 FINDING-1 hardened): the hook
extracts the current cycle's task-id(s) from the QA dispatch prompt body
by scanning ONLY pattern-anchored references in priority order:
  1. context-<task-id>.json
  2. dev-report-<task-id>.json
  3. ticket-<task-id>.md (legacy: ba-spec-<task-id>.md — both prefixes accepted)
The first task-id wins for the "primary" scope, but distinct anchored
references for OTHER task-ids do NOT vote against it -- they ADD to the
scope (union semantics). This resists prompt manipulation: an attacker
mentioning a stale task-id N times in the prompt body cannot scope away
a current-task-id violation. When ZERO pattern-anchored references are
present, the conservative global scan is retained.

Iteration-suffix filter (iter2 FINDING-3): worker labels in
NON_WORKER_LABELS (bare "iter", "iter2", "draft", "retry", "fix", ...)
are NOT classified as workers. They are within-shard iteration markers
emitted by real cycles (e.g. dev-report-<task-id>-iter2.json) and
treating them as separate workers triggered false BLOCKs.

Authoritative construction rule for the aggregate: commands/dev.md lines
613-670. See also docs/dev/dev-report-20260426-122733.json for a canonical
exemplar written in Phase 1.
"""

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.allowlist import read_grant  # noqa: E402


# Per-worker filename — role-first naming: dev-report-<role>-<task-id>.json
# task-id format: YYYYMMDD-HHMMSS (8 digits, dash, 6 digits)
# role may not contain dashes (so the role/task-id boundary is unambiguous).
PER_WORKER_ROLE_FIRST_RE = re.compile(
    r"^dev-report-(?P<role>[A-Za-z0-9]+)-(?P<task_id>\d{8}-\d{6})\.json$"
)

# Per-worker filename — task-first naming: dev-report-<task-id>-<worker>.json
# task-id format: YYYYMMDD-HHMMSS (8 digits, dash, 6 digits)
# worker may contain alphanumerics, dots, dashes -- it is everything after
# the task-id and before the .json extension and is not empty.
PER_WORKER_TASK_FIRST_RE = re.compile(
    r"^dev-report-(?P<task_id>\d{8}-\d{6})-(?P<worker>[A-Za-z0-9][A-Za-z0-9.\-]*)\.json$"
)

# FINDING-3: exclusion set for bare iteration / draft / retry suffixes that
# real cycles use as within-shard markers (NOT separate workers). Without
# this filter, dev-report-<task-id>-iter2.json would be classified as a
# worker shard, triggering false BLOCKs in iteration cycles where a
# canonical aggregate has not yet been written. Real worker labels like
# "T3.2", "R1", or compound labels like "T3.2-iter2" are NOT in this set
# (the worker token is "T3.2-iter2", not bare "iter2"); they remain
# detected as workers.
# Bare iteration / draft / retry suffixes that real cycles emit as
# within-shard markers (NOT separate workers). Static set covers
# non-numeric tokens; the regex below catches numeric variants of
# any size (iter, iter1, iter999, retry, retry1, retry42, ...).
NON_WORKER_LABELS = frozenset({
    "draft", "final", "fix", "continuation", "wip",
})

# Codex iter2 review point 5: bounded iter1..iter10 / retry1..retry2 was
# brittle. Real cycles already emit iter11+ in long-running specs and
# retry3+ in flaky-test cycles. Switch to a regex covering any numeric
# suffix on the bare token. Compound labels like "T3.2-iter2" still pass
# through (the regex anchors on ^...$ and the bare token "T3.2-iter2"
# does not match the iter/retry shape).
NON_WORKER_LABEL_RE = re.compile(
    r"^(?:iter|retry|attempt)\d*$",
    re.IGNORECASE,
)


# Canonical singular: dev-report-<task-id>.json
CANONICAL_RE = re.compile(r"^dev-report-(?P<task_id>\d{8}-\d{6})\.json$")

# Task-id reference patterns inside QA dispatch prompts. Used to scope the
# aggregate check to only the current cycle's task-id (BUG-AGGCHK-2).
# Accepts BOTH `ba-spec-` (legacy 90 historical artifacts) and `ticket-` (new
# active-write site, post-rename per spec-20260503-091826.md M10).
TASK_ID_REF_PATTERNS = (
    re.compile(r"context-(?P<task_id>\d{8}-\d{6}(?:-[A-Za-z0-9.\-]+)?)\.json"),
    re.compile(r"dev-report-(?P<task_id>\d{8}-\d{6}(?:-[A-Za-z0-9.\-]+)?)\.json"),
    # /do path: a QA close dispatch for /do-developed work references its
    # do-report-<task-id>.json (NOT dev-report-). Without this pattern the /do
    # QA prompt has ZERO anchored refs -> conservative global scan -> an
    # unrelated parallel-dev cycle's orphaned shards falsely BLOCK it. Scoping
    # to the do-report's own task-id (which has no worker shards) clears it.
    re.compile(r"do-report-(?P<task_id>\d{8}-\d{6}(?:-[A-Za-z0-9.\-]+)?)\.json"),
    re.compile(r"(?:ba-spec|ticket)-(?P<task_id>\d{8}-\d{6}(?:-[A-Za-z0-9.\-]+)?)\.md"),
)

# Path to dev.md construction-rule citation
DEV_MD_REF = "commands/dev.md lines 613-670"


def _load_stdin():
    try:
        return json.load(sys.stdin)
    except Exception:
        return None


def _is_qa_dispatch(data):
    """Return True iff this Agent call dispatches subagent_type=qa."""
    if not isinstance(data, dict):
        return False
    if data.get("tool_name") != "Agent" and data.get("tool_name") != "Task":
        return False
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return False
    return tool_input.get("subagent_type") == "qa"


def _classify_filename(name):
    """Return ('canonical', task_id) | ('worker', task_id, label) | None.

    Order: canonical first (most specific), then role-first per-worker, then
    task-first per-worker. Each branch returns once; None if no match.

    FINDING-3: task-first matches whose worker label is a bare iteration /
    draft suffix (in NON_WORKER_LABELS) are NOT classified as workers. They
    represent within-shard iteration markers, not separate workers, and
    treating them as workers triggered false BLOCKs in iteration cycles.
    Compound labels like "T3.2-iter2" do NOT match the exclusion set
    (the worker token is "T3.2-iter2", not bare "iter2") and remain
    detected as workers.
    """
    m_can = CANONICAL_RE.match(name)
    if m_can is not None:
        return ("canonical", m_can.group("task_id"))
    m_role = PER_WORKER_ROLE_FIRST_RE.match(name)
    if m_role is not None:
        return ("worker", m_role.group("task_id"), m_role.group("role"))
    m_task = PER_WORKER_TASK_FIRST_RE.match(name)
    if m_task is None:
        return None
    worker = m_task.group("worker")
    worker_lc = worker.lower()
    if worker_lc in NON_WORKER_LABELS:
        return None
    if NON_WORKER_LABEL_RE.match(worker_lc):
        return None
    return ("worker", m_task.group("task_id"), worker)


def _scan_dev_dir(dev_dir):
    """Return ({task_id: [worker_label,...]}, {task_id: True}).

    Worker labels combine role-first roles and task-first workers (both
    are equivalent evidence of a per-worker shard). Canonical singletons
    are excluded from worker counts via _classify_filename ordering.
    """
    per_worker = defaultdict(list)
    canonical_present = {}
    if not dev_dir.exists() or not dev_dir.is_dir():
        return per_worker, canonical_present
    try:
        children = list(dev_dir.iterdir())
    except OSError:
        return per_worker, canonical_present
    for child in children:
        if not child.is_file():
            continue
        result = _classify_filename(child.name)
        if result is None:
            continue
        if result[0] == "canonical":
            canonical_present[result[1]] = True
        else:
            per_worker[result[1]].append(result[2])
    return per_worker, canonical_present


def _qa_prompt_body(data):
    """Extract the QA dispatch prompt body string, or '' when unavailable."""
    if not isinstance(data, dict):
        return ""
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return ""
    prompt = tool_input.get("prompt") or ""
    return prompt if isinstance(prompt, str) else ""


def _scan_pattern_for_task_ids(prompt, pattern, idx, seen):
    """Helper: walk one regex over the prompt; record first-seen positions."""
    for m in pattern.finditer(prompt):
        tid = m.group("task_id")
        if not tid:
            continue
        if tid not in seen:
            seen[tid] = (idx, m.start())


def _collect_anchored_task_ids(prompt):
    """Scan prompt for pattern-anchored task-id refs.

    Returns a list of distinct task-id strings ordered by
    (pattern-priority, first-character-offset). TASK_ID_REF_PATTERNS encodes
    priority: context- first, dev-report- second, ticket-/ba-spec- third.

    FINDING-1 fix: replaces the prior most-frequent heuristic. Frequency
    cannot scope away a violation any longer; all distinct pattern-anchored
    task-ids contribute to scope (union semantics in caller).
    """
    seen = {}
    for idx, pattern in enumerate(TASK_ID_REF_PATTERNS):
        _scan_pattern_for_task_ids(prompt, pattern, idx, seen)
    return [tid for tid, _ in sorted(seen.items(), key=lambda kv: kv[1])]


def _extract_current_task_ids(data):
    """Return list of distinct pattern-anchored task-ids in QA prompt, or None.

    None signals "fall back to conservative global scan" (the prompt has
    ZERO pattern-anchored refs). Single match -> 1-element list. Multiple
    distinct matches -> all of them (union for scope, no majority-vote).

    FINDING-1 (replaces _extract_current_task_id): an attacker mentioning a
    stale task-id N times in the prompt body cannot scope the hook away
    from a current-task-id violation. Each anchored ref counts once; all
    contribute to the scope-set.
    """
    prompt = _qa_prompt_body(data)
    if not prompt:
        return None
    task_ids = _collect_anchored_task_ids(prompt)
    return task_ids if task_ids else None


def _normalize_task_id_prefix(task_id):
    """Return the YYYYMMDD-HHMMSS prefix of a possibly-suffixed task-id.

    The hook indexes per_worker / canonical_present by the bare timestamp
    (file regexes capture only the YYYYMMDD-HHMMSS group). Prompts may
    carry a fuller task-id like "20260427-130000-bugfix"; this maps it
    back to the timestamp prefix used as the dict key.
    """
    if not isinstance(task_id, str):
        return None
    m = re.match(r"^(\d{8}-\d{6})", task_id)
    return m.group(1) if m else None


def _find_violations(per_worker, canonical_present, scope_task_id=None):
    """Return list of (task_id, [labels]) tuples that violate the predicate.

    Violation = >=2 per-worker reports for same task-id AND no canonical.

    BUG-AGGCHK-2: when scope_task_id is provided, restrict the result to
    that task-id only. When None, scan globally (legacy conservative
    behavior preserved for cases where the QA prompt has no task-id ref).
    """
    violations = []
    for task_id, roles in per_worker.items():
        if scope_task_id is not None and task_id != scope_task_id:
            continue
        if len(roles) >= 2 and not canonical_present.get(task_id):
            violations.append((task_id, sorted(roles)))
    return violations


def _emit_block(violations, dev_dir):
    """Print BLOCK message to stderr and exit 2."""
    lines = ["", "BLOCKED Agent dispatch (qa): canonical aggregate dev-report missing."]
    for task_id, roles in violations:
        canonical = dev_dir / f"dev-report-{task_id}.json"
        lines.append("")
        lines.append(f"  task-id: {task_id}")
        lines.append(f"  per-worker reports present: {', '.join(roles)}")
        lines.append(f"  missing canonical aggregate: {canonical}")
    lines.append("")
    lines.append(
        f"REQUIRED: orchestrator must write the canonical aggregate before "
        f"dispatching QA. See {DEV_MD_REF} for the construction rule."
    )
    lines.append("")
    sys.stderr.write("\n".join(lines) + "\n")
    sys.exit(2)


def _resolve_dev_dir():
    """Resolve docs/dev under CLAUDE_PROJECT_DIR, fail-open if absent."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return Path(project_dir) / "docs" / "dev"


def _resolve_scope_task_ids(raw_task_ids):
    """Normalize a list of raw task-ids to the YYYYMMDD-HHMMSS prefix set.

    Returns None when the input is None or every entry fails normalization
    (signaling "no anchored refs -- fall back to global scan"). Otherwise
    returns the deduped list of normalized prefixes, preserving order.
    """
    if not raw_task_ids:
        return None
    normalized = []
    seen = set()
    for raw in raw_task_ids:
        n = _normalize_task_id_prefix(raw)
        if n and n not in seen:
            seen.add(n)
            normalized.append(n)
    return normalized if normalized else None


def _aggregate_one_task(per_worker, canonical_present, tid, seen_keys, out):
    """Helper: append unique violations for a single task-id into `out`."""
    for entry in _find_violations(per_worker, canonical_present, tid):
        if entry[0] in seen_keys:
            continue
        seen_keys.add(entry[0])
        out.append(entry)


def _collect_violations(per_worker, canonical_present, scope_task_ids):
    """Return aggregated violations across all scope_task_ids.

    When scope_task_ids is None, scan globally (legacy conservative
    behavior). When it is a list, scan once per task-id in the list and
    union the results (FINDING-1 union semantics on ambiguous prompt).
    """
    if scope_task_ids is None:
        return _find_violations(per_worker, canonical_present, None)
    aggregated = []
    seen_keys = set()
    for tid in scope_task_ids:
        _aggregate_one_task(per_worker, canonical_present, tid, seen_keys, aggregated)
    return aggregated


def main():
    data = _load_stdin()
    if data is None:
        sys.exit(0)
    if not _is_qa_dispatch(data):
        sys.exit(0)

    # /do bypass: main-agent-only
    try:
        if not data.get('agent_id'):
            sid = (data.get('session_id') or
                   os.environ.get('CLAUDE_SESSION_ID', '') or 'default')
            flag = Path(f'/tmp/claude-orchestrator-consent-{sid}.flag')
            if flag.exists() and flag.read_text().strip() == 'true':
                sys.exit(0)
    except Exception:
        pass

    # /allow bypass: if allowlist pattern matches "Agent" dispatch, pass
    try:
        if not data.get('agent_id'):
            _sid = (data.get('session_id') or
                    os.environ.get('CLAUDE_SESSION_ID', '') or 'default')
            if read_grant('Agent', _sid):
                sys.exit(0)
    except Exception:
        pass

    dev_dir = _resolve_dev_dir()
    per_worker, canonical_present = _scan_dev_dir(dev_dir)
    # FINDING-1: extract the LIST of pattern-anchored task-ids. None = no
    # anchored refs -> conservative global scan. List = scope detection
    # to the union of the listed task-ids (each scanned once, results
    # unioned). No frequency / majority-vote weighting.
    raw_task_ids = _extract_current_task_ids(data)
    scope_task_ids = _resolve_scope_task_ids(raw_task_ids)
    violations = _collect_violations(per_worker, canonical_present, scope_task_ids)
    if violations:
        _emit_block(violations, dev_dir)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Fail-open: never crash orchestrator on a self-bug
        sys.exit(0)
