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

Filename patterns:
  Prefixed:   dev-report-dev-<task-id>-<worker>.json
  Prefixed canonical: dev-report-dev-<task-id>.json
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
from lib.harness_state_dir import harness_state_dir  # noqa: E402
from lib import obligation as obligation_lib  # noqa: E402
from lib import contract_runtime  # noqa: E402
from lib.dev_report_shard_patterns import (  # noqa: E402
    PREFIXED_WORKER_RE,
    PREFIXED_CANONICAL_RE,
    PER_WORKER_ROLE_FIRST_RE,
    PER_WORKER_TASK_FIRST_RE,
    CANONICAL_RE,
    NON_WORKER_LABELS,
    NON_WORKER_LABEL_RE,
    classify_filename as _shared_classify_filename,
)

# Filename-classification regexes and the NON_WORKER_LABELS/NON_WORKER_LABEL_RE
# iteration-suffix filter now live in lib/dev_report_shard_patterns.py (the ONE
# shared module scripts/aggregate-dev-report.py and
# hooks/posttool-lane-completeness-watch.py also import) -- ticket
# 20261001-161041-r05 M2. Re-exported here as module attributes (not just used
# locally) so existing callers/tests referencing them via this module's own
# namespace keep working unchanged.

# Task-id reference patterns inside QA dispatch prompts. Used to scope the
# aggregate check to only the current cycle's task-id (BUG-AGGCHK-2).
# Accepts BOTH `ba-spec-` (legacy 90 historical artifacts) and `ticket-` (new
# active-write site, post-rename per spec-20260503-091826.md M10).
TASK_ID_REF_PATTERNS = (
    re.compile(r"context-(?P<task_id>dev-\d{8}-\d{6})(?:-[A-Za-z0-9.\-]+)?\.json"),
    re.compile(r"dev-report-(?P<task_id>dev-\d{8}-\d{6})(?:-[A-Za-z0-9.\-]+)?\.json"),
    re.compile(r"(?:ba-spec|ticket)-(?P<task_id>dev-\d{8}-\d{6})(?:-[A-Za-z0-9.\-]+)?\.md"),
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

# Retry contexts (`context-iter<N>-<task-id>-<lane>.json`) are recognized for
# TASK-SCOPING ONLY: without this pattern a retry QA prompt would fall through
# to the conservative global docs/dev scan. It carries NO gate of its own — the
# hook never blocks on iteration/promotion evidence.
ITERATION_CONTEXT_RE = re.compile(
    r"context-iter(?P<iteration>[1-9][0-9]*)-"
    r"(?P<task_id>dev-\d{8}-\d{6})-"
    r"(?P<lane>[A-Za-z0-9][A-Za-z0-9.\-]*)\.json"
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

    Delegates to lib.dev_report_shard_patterns.classify_filename (ticket
    20261001-161041-r05 M2) -- kept as a thin wrapper here, same name/
    signature/docstring, so existing callers and tests referencing
    `_classify_filename` on this module keep working unchanged (AC5).
    """
    return _shared_classify_filename(name)


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


def _collect_iteration_context_refs(prompt):
    """Return distinct, explicitly named retry contexts in prompt order."""
    refs = []
    seen = set()
    for match in ITERATION_CONTEXT_RE.finditer(prompt):
        ref = (
            match.group("task_id"),
            match.group("lane"),
            int(match.group("iteration")),
        )
        if ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return refs


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
    for task_id, _, _ in _collect_iteration_context_refs(prompt):
        if task_id not in task_ids:
            task_ids.append(task_id)
    return task_ids if task_ids else None


def _normalize_task_id_prefix(task_id):
    """Return the scanner key of a possibly-suffixed task-id.

    The hook indexes per_worker / canonical_present by the bare timestamp
    (file regexes capture only the YYYYMMDD-HHMMSS group). Prompts may
    carry a fuller task-id like "20260427-130000-bugfix"; this maps it
    back to the timestamp prefix used as the dict key.
    """
    if not isinstance(task_id, str):
        return None
    m = re.match(r"^(?P<prefix>dev-)?(?P<stamp>\d{8}-\d{6})", task_id)
    if not m:
        return None
    return (m.group("prefix") or "") + m.group("stamp")


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


#  ---------------------------------------------------------------------------
# G3: obligation-scoped collection barrier. Generalizes this hook beyond the
# QA-only canonical-aggregate special case above: activates on ANY Agent/Task
# dispatch (any subagent_type) whose own prompt carries an "<obligation"
# block, and re-verifies this dev-registry session's prior-stage
# obligation-declared artifacts on disk before the orchestrator dispatches a
# later pipeline stage. See docs/reference/close-commit-zero-failure-
# mechanism-20260928.md Â§1.3-G3 and docs/dev/ticket-20260930-132644-l3.md
# (M1-M9). Purely additive: does not alter the QA-only block above.
#  ---------------------------------------------------------------------------

OBLIGATION_BARRIER_ENV = "CLAUDE_OBLIGATION_BARRIER"
OBLIGATION_ADVISORY_LOG = os.path.join(
    "~", ".claude", "logs", "obligation-barrier-advisory.jsonl"
)
REPAIR_PROFILE = "repair"


def _dispatch_prompt_body(data):
    """Like _qa_prompt_body, but for ANY Agent/Task dispatch (not qa-only)."""
    if not isinstance(data, dict):
        return ""
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return ""
    prompt = tool_input.get("prompt") or ""
    return prompt if isinstance(prompt, str) else ""


def _lenient_obligation_fields(prompt):
    """Lenient (grammar-only, non-field-validating) extraction of a dispatch
    prompt's obligation body as a dict, or None.

    Deliberately never routes through obligation_lib.validate_obligation /
    parse_obligation: those fail-closed on profile="repair" (not a
    registered PROFILES member -- ticket Edge Case 1). Only checks
    block-count/version (extract_obligation_block) then parses the body
    as plain JSON.
    """
    if not isinstance(prompt, str) or not prompt:
        return None
    try:
        extracted = obligation_lib.extract_obligation_block(prompt)
    except Exception:
        return None
    body = getattr(extracted, "body", None)
    if not isinstance(body, str):
        return None
    try:
        doc = json.loads(body)
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


def _scan_transcript_for_prior_obligations(transcript_path, task_id_prefix):
    """Scan this session's own transcript for earlier Agent/Task tool_use
    dispatches whose own prompt carries an obligation with a matching
    task_id (prefix-normalized).

    Mirrors the JSONL-scan shape of hooks/lib/subagent_restart.py
    :func:`_read_parent_calls` (iterate lines, json.loads, walk
    message.content[] blocks where type=="tool_use" and name in
    {"Agent","Task"}, read input.prompt) as a NEW local function --
    re-implemented rather than imported (underscore-private, foreign-module
    coupling risk).

    Returns a list of {"obligation": dict, "line": int}, ascending by
    transcript line. Defensive (Edge Case 4): a malformed JSONL line or a
    malformed historical obligation is skipped, never raised; one bad entry
    never aborts the scan of the rest.
    """
    found = []
    if not transcript_path or not task_id_prefix:
        return found
    try:
        path = Path(transcript_path)
        if not path.exists():
            return found
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, raw_line in enumerate(handle, 1):
                try:
                    record = json.loads(raw_line)
                except Exception:
                    continue
                if not isinstance(record, dict):
                    continue
                message = record.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use" or block.get("name") not in (
                        "Agent", "Task",
                    ):
                        continue
                    tool_input = block.get("input")
                    if not isinstance(tool_input, dict):
                        continue
                    prompt = tool_input.get("prompt")
                    obligation = (
                        _lenient_obligation_fields(prompt)
                        if isinstance(prompt, str) else None
                    )
                    if obligation is None:
                        continue
                    prior_task_id = obligation.get("task_id")
                    if not isinstance(prior_task_id, str):
                        continue
                    if _normalize_task_id_prefix(prior_task_id) != task_id_prefix:
                        continue
                    found.append({"obligation": obligation, "line": line_no})
    except Exception:
        return found
    return found


def _verify_prior_artifact(entry, project_dir):
    """Re-verify one prior obligation's artifacts[] entry on disk.

    Returns (ok: bool, violation: dict | None). `violation` (when ok is
    False) carries {"code", "path", "problem"} -- distinguishable per
    violation kind: artifact_missing / not_valid_json / schema_invalid
    (AC11) / identity_mismatch (AC9) for kind=="json"; artifact_missing /
    identity_anchor_missing (AC10) / terminal_line_mismatch (AC12) for
    kind=="markdown". Any other kind (response_block/response_line, W3) is
    never a violation -- (True, None), defensively, even though the only
    caller already filters these out before calling.
    """
    if not isinstance(entry, dict):
        return (True, None)
    kind = entry.get("kind")
    path = entry.get("path")
    if kind == "json":
        if not isinstance(path, str) or not path:
            return (True, None)
        schema_id = entry.get("schema")
        if not isinstance(schema_id, str) or not schema_id:
            return (True, None)  # malformed historical entry: no evidence, not a violation
        full_path = Path(project_dir) / path
        result = contract_runtime.validate_artifact_for_obligation(full_path, schema_id)
        status = result.get("status") if isinstance(result, dict) else None
        reason_text = (result.get("reason") if isinstance(result, dict) else None) or ""
        if status == "skip":
            return (True, None)
        if status == "fail":
            if "schema-invalid" in reason_text:
                code = "schema_invalid"
            elif "not valid JSON" in reason_text:
                code = "not_valid_json"
            else:
                code = "artifact_missing"
            return (
                False,
                {
                    "code": code, "path": path,
                    "problem": reason_text or "artifact failed obligation verification",
                },
            )
        if status == "pass":
            identity = entry.get("identity")
            if isinstance(identity, dict) and identity:
                try:
                    record = json.loads(full_path.read_text(encoding="utf-8"))
                except Exception:
                    return (True, None)
                if isinstance(record, dict):
                    for key, expected in identity.items():
                        if record.get(key) != expected:
                            return (
                                False,
                                {
                                    "code": "identity_mismatch", "path": path,
                                    "problem": (
                                        f"identity.{key} mismatch: obligation declares "
                                        f"{expected!r}, artifact has {record.get(key)!r}"
                                    ),
                                },
                            )
            return (True, None)
        return (True, None)
    if kind == "markdown":
        if not isinstance(path, str) or not path:
            return (True, None)
        full_path = Path(project_dir) / path
        result = contract_runtime.validate_markdown_artifact_for_obligation(
            full_path, entry.get("identity_anchor"), entry.get("terminal_line_regex")
        )
        if result.get("status") != "fail":
            # "pass" (and the defensive "skip", never actually returned by
            # this function today) both mean "not a violation".
            return (True, None)
        reason_text = result.get("reason") or ""
        if "identity_anchor_missing" in reason_text:
            code = "identity_anchor_missing"
        elif "terminal_line_mismatch" in reason_text:
            code = "terminal_line_mismatch"
        else:
            code = "artifact_missing"
        problem = reason_text.split(":", 1)[1].strip() if ":" in reason_text else reason_text
        return (False, {"code": code, "path": path, "problem": problem})
    return (True, None)


def _format_barrier_violation(code, path, problem, role, lane, action):
    """Unified three-element template (blueprint Â§2): ``[code] path: problem
    | role: role(lane) | fix: action``."""
    role_s = role if isinstance(role, str) and role else "unknown"
    lane_s = lane if isinstance(lane, str) and lane else "unknown"
    return f"[{code}] {path}: {problem} | role: {role_s}({lane_s}) | fix: {action}"


def _log_barrier_advisory(record):
    """Best-effort append to the G3 advisory log. Never raises."""
    try:
        log_path = os.path.expanduser(OBLIGATION_ADVISORY_LOG)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except Exception:
        pass


def _run_obligation_barrier(data):
    """G3 collection barrier orchestrator (ticket M1-M9).

    Entire body wrapped in its own try/except (layered ON TOP of this
    file's outer __main__ try/except, which is silent): any unexpected
    exception here is advisory-logged with reason "gate_error" and
    swallowed -- the caller (main()) always proceeds to its own
    sys.exit(0) afterward.
    """
    try:
        mode = os.environ.get(OBLIGATION_BARRIER_ENV, "advisory").strip().lower()
        if mode == "off":
            return
        prompt = _dispatch_prompt_body(data)
        if obligation_lib.OBLIGATION_OPEN_TOKEN not in prompt:
            return
        current = _lenient_obligation_fields(prompt)
        if current is None:
            return
        if current.get("profile") == REPAIR_PROFILE:
            return
        task_id = current.get("task_id")
        task_id_prefix = (
            _normalize_task_id_prefix(task_id) if isinstance(task_id, str) else None
        )
        if task_id_prefix is None:
            return
        transcript_path = data.get("transcript_path") if isinstance(data, dict) else None
        prior_obligations = _scan_transcript_for_prior_obligations(
            transcript_path, task_id_prefix
        )
        if not prior_obligations:
            return
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        for prior in prior_obligations:
            obligation = prior.get("obligation") or {}
            artifacts = obligation.get("artifacts")
            if not isinstance(artifacts, list):
                continue
            role = obligation.get("role")
            lane = obligation.get("lane")
            for entry in artifacts:
                if not isinstance(entry, dict) or entry.get("kind") not in (
                    "json", "markdown",
                ):
                    # response_block/response_line (AC6, W3) and unknown
                    # kinds have no on-disk representation to check.
                    continue
                ok, violation = _verify_prior_artifact(entry, project_dir)
                if ok:
                    continue
                record = {
                    "reason": "obligation_barrier_violation",
                    "code": violation["code"],
                    "path": violation["path"],
                    "problem": violation["problem"],
                    "role": role,
                    "lane": lane,
                    "task_id": task_id,
                }
                if mode == "block":
                    sys.stderr.write(
                        "\n"
                        + _format_barrier_violation(
                            violation["code"], violation["path"], violation["problem"],
                            role, lane,
                            "regenerate or repair the named artifact before dispatching "
                            "this later pipeline stage",
                        )
                        + "\n"
                    )
                    sys.exit(2)
                _log_barrier_advisory(record)
    except Exception:
        _log_barrier_advisory({"reason": "gate_error"})


def main():
    data = _load_stdin()
    if data is None:
        sys.exit(0)

    if _is_qa_dispatch(data):
        # /do bypass: main-agent-only
        try:
            if not data.get('agent_id'):
                sid = (data.get('session_id') or
                       os.environ.get('CLAUDE_SESSION_ID', '') or 'default')
                flag = Path(f'{harness_state_dir()}/claude-orchestrator-consent-{sid}.flag')
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

    _run_obligation_barrier(data)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Fail-open: never crash orchestrator on a self-bug
        sys.exit(0)
