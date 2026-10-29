#!/usr/bin/env python3
"""PreToolUse Hook (Agent matcher): Enforce canonical aggregate dev-report
existence before allowing the orchestrator to dispatch the QA subagent in
parallel-dev cycles. G3, the collection check at the next dispatch.

Fan-out collection check (QA dispatches only; blocks in every mode). A lane
report declares a fan-out by its own `lane_set` naming two or more lanes. For
each fan-out in the dispatch's scope it BLOCKS (exit 2) while:
  (a) a lane its lane_set declares has no lane report (the roster check that
      hooks/posttool-lane-completeness-watch.py used to make before it ran
      the aggregator), or, once every lane has reported,
  (b) the canonical aggregate dev-report-<task-id>.json is missing, or its
      parallel_workers does not name every declared lane (it predates the
      last lane report).
A report without a lane_set declares no fan-out: a singular cycle, or one of
the overnight pipelines' dev-report-<ts>-<N>.json, which the filenames alone
would read as lanes of task <ts>. The canonical's one producer is the lane
completeness watch, which runs the harness's aggregator whenever a lane report
is written; a lane report's is its lane's dev.

Task-id scoping (BUG-AGGCHK-2): the check covers the cycle of the task the
QA dispatch's own obligation names. A shard family is in scope when its id and
that task id name the same cycle under the one task-id rule
(obligation.canonical_task_id): equal, or the task id extends the family's by a
suffix (a lane, a pipeline index). A task id mentioned anywhere else in the
prompt does not move the scope. A QA dispatch without an obligation keeps the
conservative global scan, which demands only (b)'s canonical, of each fan-out
whose lanes have all reported.

Filename patterns (lib/dev_report_shard_patterns.py) find a family's lane
reports and its canonical; worker labels in NON_WORKER_LABELS (bare "iter",
"iter2", "draft", "retry", "fix", ...) are within-shard iteration markers, not
lanes (iter2 FINDING-3).

The obligation barrier and the gitignore rule below block only when
CLAUDE_OBLIGATION_BARRIER=block.

Fail-open contract: parsing failures, missing stdin, missing project dir,
unexpected exceptions -> exit 0. Never crash the orchestrator on a self-bug.
"""

import importlib.util
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.allowlist import has_do_consent, match_sentinel_grant_for_tool  # noqa: E402
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
    """Return ({task_id: {label: path}}, {task_id: path}): the lane-shaped
    reports of each task family in docs/dev, and each family's canonical.

    Canonical singletons are excluded from the lane reports via
    _classify_filename ordering.
    """
    lane_reports = defaultdict(dict)
    canonicals = {}
    if not dev_dir.exists() or not dev_dir.is_dir():
        return lane_reports, canonicals
    try:
        children = list(dev_dir.iterdir())
    except OSError:
        return lane_reports, canonicals
    for child in children:
        if not child.is_file():
            continue
        result = _classify_filename(child.name)
        if result is None:
            continue
        if result[0] == "canonical":
            canonicals[result[1]] = child
        else:
            lane_reports[result[1]][result[2]] = child
    return lane_reports, canonicals


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _qa_prompt_body(data):
    """Extract the QA dispatch prompt body string, or '' when unavailable."""
    if not isinstance(data, dict):
        return ""
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return ""
    prompt = tool_input.get("prompt") or ""
    return prompt if isinstance(prompt, str) else ""


def _scope_task_id(data):
    """The task id this QA dispatch's own obligation names, or None (no
    obligation: the conservative global scan)."""
    obligation = _parsed_obligation(_qa_prompt_body(data))
    task_id = obligation.get("task_id") if obligation else None
    return task_id if isinstance(task_id, str) and task_id else None


def _same_cycle(family_task_id, scope_task_id):
    """True when a shard family's id and the dispatch's task id name one cycle:
    their canonical ids (obligation.canonical_task_id) are equal, or the task
    id extends the family's by a suffix (a lane, a pipeline index)."""
    family = obligation_lib.canonical_task_id(family_task_id)
    scope = obligation_lib.canonical_task_id(scope_task_id)
    return bool(family) and bool(scope) and (scope == family or scope.startswith(family + "-"))


def _find_violations(lane_reports, canonicals, dev_dir, scope_task_id=None):
    """Return [(code, path, problem, lane)] for each fan-out in scope whose
    collection is incomplete; lane is None for the canonical's findings.

    A family is a fan-out only when one of its lane reports declares it: its
    own lane_set names two or more lanes. A lane counts as reported when a
    report of the family carries its label or names it as its `lane`. Only
    once every declared lane has reported is the canonical due: it must exist
    and name each declared lane in parallel_workers.

    BUG-AGGCHK-2: when scope_task_id is provided, restrict the result to
    that task's cycle (_same_cycle). When None (a QA dispatch without an
    obligation names no cycle), the conservative global scan keeps only the
    canonical's presence for each fan-out whose lanes have all reported: an
    unrelated cycle's abandoned lane is not this dispatch's to collect, and
    the scan never blocks more than the filename rule it replaces did.
    """
    violations = []
    for task_id, reports in sorted(lane_reports.items()):
        if scope_task_id is not None and not _same_cycle(task_id, scope_task_id):
            continue
        declared, reported = {}, set(reports)
        for label, path in sorted(reports.items()):
            report = _read_json(path)
            if not isinstance(report, dict):
                continue
            if isinstance(report.get("lane"), str):
                reported.add(report["lane"])
            lane_set = report.get("lane_set")
            lanes = [x for x in lane_set if isinstance(x, str) and x] if isinstance(lane_set, list) else []
            if len(set(lanes)) >= 2:
                for lane in lanes:
                    declared.setdefault(lane, path.name)
        if not declared:
            continue
        missing = [lane for lane in sorted(declared) if lane not in reported]
        if scope_task_id is not None:
            for lane in missing:
                violations.append((
                    "lane_report_missing", dev_dir / f"dev-report-{task_id}-{lane}.json",
                    f"lane {lane}, which the lane_set of {declared[lane]} declares, has no report", lane,
                ))
        if missing:
            continue
        canonical = canonicals.get(task_id) or dev_dir / f"dev-report-{task_id}.json"
        if not canonical.is_file():
            violations.append((
                "canonical_missing", canonical,
                f"the canonical aggregate of lanes {', '.join(sorted(declared))} is missing", None,
            ))
            continue
        if scope_task_id is None:
            continue
        aggregate = _read_json(canonical)
        workers = aggregate.get("parallel_workers") if isinstance(aggregate, dict) else None
        workers = workers if isinstance(workers, list) else []
        unnamed = [lane for lane in sorted(declared) if lane not in workers]
        if unnamed:
            violations.append((
                "canonical_stale", canonical,
                f"its parallel_workers {workers} do not name lane(s) {', '.join(unnamed)} "
                "the lane_set declares", None,
            ))
    return violations


def _emit_block(violations):
    """Print the BLOCK message to stderr and exit 2: each failing artifact's
    path and check, and its producer."""
    lines = ["", "BLOCKED Agent dispatch (qa): a fan-out's lane reports and canonical "
                 "aggregate are not all collected."]
    for code, path, problem, lane in violations:
        producer = (
            f"dev (lane {lane})" if lane is not None else
            "hooks/posttool-lane-completeness-watch.py, which runs the aggregator "
            "whenever a lane report of the task is written"
        )
        lines.append(f"  [{code}] {path}: {problem} | producer: {producer}")
    lines.append("")
    sys.stderr.write("\n".join(lines) + "\n")
    sys.exit(2)


def _resolve_dev_dir():
    """Resolve docs/dev under CLAUDE_PROJECT_DIR, fail-open if absent."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return Path(project_dir) / "docs" / "dev"


#  ---------------------------------------------------------------------------
# G3: obligation-scoped collection barrier. Generalizes this hook beyond the
# QA-only canonical-aggregate special case above: activates on ANY Agent/Task
# dispatch (any subagent_type) whose own prompt carries an "<obligation"
# block, and re-verifies the artifacts that the same task family's COMPLETED
# prior stages declared, on disk, before the orchestrator dispatches a later
# pipeline stage. Under the CLI's transcript order the in-flight tool_use is
# already in the transcript when PreToolUse runs, so a prior stage is an
# Agent/Task tool_use with a non-error tool_result and an id other than this
# payload's tool_use_id. See docs/reference/close-commit-zero-failure-
# mechanism-20260928.md Â§1.3-G3 and docs/dev/ticket-20260930-132644-l3.md
# (M1-M9). Purely additive: does not alter the QA-only block above.
#  ---------------------------------------------------------------------------

OBLIGATION_BARRIER_ENV = "CLAUDE_OBLIGATION_BARRIER"


def _dispatch_prompt_body(data):
    """Like _qa_prompt_body, but for ANY Agent/Task dispatch (not qa-only)."""
    if not isinstance(data, dict):
        return ""
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return ""
    prompt = tool_input.get("prompt") or ""
    return prompt if isinstance(prompt, str) else ""


def _parsed_obligation(prompt):
    """The strictly parsed obligation of a dispatch prompt, or None."""
    parsed = obligation_lib.parse_obligation(prompt) if isinstance(prompt, str) else None
    return parsed.obligation if isinstance(parsed, obligation_lib.ParsedObligation) else None


def _scan_transcript_for_prior_obligations(transcript_path, family, current_tool_use_id):
    """Earlier COMPLETED stages of ``family`` in this session's transcript.

    A completed stage is an Agent/Task tool_use whose id differs from the
    in-flight call's and which has a non-error tool_result: the in-flight
    call, parallel siblings with no result yet and dispatches a hook refused
    are not prior stages. Obligations parse strictly; a malformed one is
    skipped, as is a malformed JSONL line. Returns [{"obligation", "line"}]
    in transcript order.
    """
    uses, results = [], {}
    if not transcript_path or not family:
        return []
    try:
        with Path(transcript_path).open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, raw_line in enumerate(handle, 1):
                try:
                    record = json.loads(raw_line)
                except Exception:
                    continue
                message = record.get("message") if isinstance(record, dict) else None
                content = message.get("content") if isinstance(message, dict) else None
                for block in content if isinstance(content, list) else ():
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        results[block.get("tool_use_id")] = bool(block.get("is_error"))
                    elif block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task"):
                        tool_input = block.get("input")
                        prompt = tool_input.get("prompt") if isinstance(tool_input, dict) else None
                        uses.append((line_no, block.get("id"), prompt))
    except Exception:
        return []
    found = []
    for line_no, use_id, prompt in uses:
        if use_id == current_tool_use_id or results.get(use_id, True):
            continue
        obligation = _parsed_obligation(prompt)
        if obligation is not None and obligation_lib.task_family(obligation.get("task_id")) == family:
            found.append({"obligation": obligation, "line": line_no})
    return found


def _verify_prior_artifact(entry, project_dir):
    """Re-verify one prior obligation's artifacts[] entry on disk.

    Returns (ok: bool, violation: dict | None). `violation` (when ok is
    False) carries {"code", "path", "problem"} -- distinguishable per
    violation kind: artifact_missing / not_valid_json / schema_invalid
    (AC11) / identity_mismatch (AC9) for kind=="json"; artifact_missing /
    identity_anchor_missing (AC10) / terminal_line_mismatch (AC12) for
    kind=="markdown". Any other kind (response_block/response_line, W3, has
    no on-disk file to check) is never a violation -- (True, None).
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


def _run_obligation_barrier(data):
    """G3 collection barrier orchestrator (ticket M1-M9).

    Entire body wrapped in its own try/except (layered ON TOP of this
    file's outer __main__ try/except, which is silent): any unexpected
    exception here is swallowed -- the caller (main()) always proceeds to
    its own sys.exit(0) afterward.
    """
    try:
        mode = os.environ.get(OBLIGATION_BARRIER_ENV, "advisory").strip().lower()
        if mode == "off":
            return
        prompt = _dispatch_prompt_body(data)
        if obligation_lib.OBLIGATION_OPEN_TOKEN not in prompt:
            return
        # A current block that does not parse is G1's finding; nothing here.
        current = _parsed_obligation(prompt)
        if current is None:
            return
        task_id = current.get("task_id")
        family = obligation_lib.task_family(task_id)
        if family is None:
            return
        prior_obligations = _scan_transcript_for_prior_obligations(
            data.get("transcript_path"), family, data.get("tool_use_id")
        )
        if not prior_obligations:
            return
        # Declared again by this dispatch: a re-dispatch after a producer
        # question or a QA fail, or the next close-QA round, rewrites it.
        redeclared = {
            a.get("path") for a in current.get("artifacts", []) if isinstance(a, dict)
        }
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        for prior in prior_obligations:
            obligation = prior.get("obligation") or {}
            artifacts = obligation.get("artifacts")
            if not isinstance(artifacts, list):
                continue
            role = obligation.get("role")
            lane = obligation.get("lane")
            for entry in artifacts:
                if not isinstance(entry, dict) or entry.get("path") in redeclared:
                    continue
                ok, violation = _verify_prior_artifact(entry, project_dir)
                if ok:
                    continue
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
    except Exception:
        pass  # fail open: an internal error never blocks a dispatch


#  ---------------------------------------------------------------------------
# G3's rule on a dev report a dispatch names (P1b row 6): a path in its
# dev.files_modified or dev.files_created that `git check-ignore` matches, with
# no gitignore_waiver, blocks the dispatch; /commit's changelog-analyst landing
# of the report's own task is admitted from its obligation (profile
# commit-landing). The rule is hooks/pretool-gitignore-preflight.py's
# gitignored_deliverables(), called here, so the two never disagree; that hook
# keeps blocking on it while this switch is advisory in the tracked settings.
#  ---------------------------------------------------------------------------

GITIGNORE_RULE_PATH = Path(__file__).parent / "pretool-gitignore-preflight.py"


def _gitignored_deliverables(prompt):
    spec = importlib.util.spec_from_file_location("pretool_gitignore_preflight", GITIGNORE_RULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.gitignored_deliverables(prompt)


def _run_gitignore_rule(data):
    """Apply the gitignore rule to an Agent/Task dispatch; blocks only when
    CLAUDE_OBLIGATION_BARRIER=block (it does nothing while advisory)."""
    try:
        if os.environ.get(OBLIGATION_BARRIER_ENV, "advisory").strip().lower() != "block":
            return
        if not isinstance(data, dict) or data.get("tool_name") not in ("Agent", "Task"):
            return
        findings = _gitignored_deliverables(_dispatch_prompt_body(data))
    except Exception:
        return  # fail open: an internal error never blocks a dispatch
    if findings:
        sys.stderr.write("".join(
            f"\n[gitignored_deliverable] {report}: {', '.join(paths)} declared in its "
            "dev.files_modified/files_created match .gitignore and it carries no gitignore_waiver"
            for report, paths in findings
        ) + "\n")
        sys.exit(2)


def main():
    data = _load_stdin()
    if data is None:
        sys.exit(0)

    if _is_qa_dispatch(data):
        if has_do_consent(data):
            sys.exit(0)

        # /allow bypass: if allowlist pattern matches "Agent" dispatch, pass
        try:
            if not data.get('agent_id'):
                _sid = (data.get('session_id') or
                        os.environ.get('CLAUDE_SESSION_ID', '') or 'default')
                if match_sentinel_grant_for_tool(_sid, 'Agent') is not None:
                    sys.exit(0)
        except Exception:
            pass

        dev_dir = _resolve_dev_dir()
        lane_reports, canonicals = _scan_dev_dir(dev_dir)
        violations = _find_violations(lane_reports, canonicals, dev_dir, _scope_task_id(data))
        if violations:
            _emit_block(violations)

    _run_obligation_barrier(data)
    _run_gitignore_rule(data)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Fail-open: never crash orchestrator on a self-bug
        sys.exit(0)
