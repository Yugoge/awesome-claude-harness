#!/usr/bin/env python3
"""SubagentStop Hook: producer-side artifact schema gate for dev/qa reports.

Ports the /close "Artifact schema gate" (commands/close.md §"Artifact schema gate" — the
contract_runtime.validate_report_artifact() Draft7 check that rejects a
versioned-but-schema-invalid dev/qa report at close time) to the PRODUCER's
stop boundary: the qa/dev subagent that just wrote the report is blocked
from stopping while it still has full context to repair it, instead of the
identical violation surfacing later as a /close schema-gate rejection after the
producer's context is gone.

Scope discipline (deliberately the SAME blocking surface as /close):
  - BLOCKS only validate_report_artifact() status == "fail": the report
    DECLARES report_version but VIOLATES its versioned schema. Same engine,
    same semantics ("this is the only blocking outcome" — close.md).
  - Unversioned legacy reports, unparseable JSON, unregistered kinds, and
    validator-infra problems all return 'skip' from the shared engine and
    pass through. Measured baseline 2026-09-26: 674 real reports in
    docs/dev/ -> 9 pass / 0 fail / 665 skip, so this gate rejects zero
    existing compliant reports.
  - A MISSING report is NOT blocked here: qa-report existence is already
    enforced (exit 2) by subagentstop-e2e-enforce.py, and dev-report
    existence by /close's Step-0 artifact-chain resolver. Duplicating
    existence enforcement would create a drift-prone mirrored pair, so a
    missing report passes here.

Activation chain (every step fails open to exit 0):
  1. stdin carries agent_id (subagent stop, not a main-session stop).
  2. resolve_dev_registry_entry() resolves the agent. LOW-10 contract
     (hooks/lib/agent_resolver.py): callers MUST NOT hard-block on None —
     a skipped FIRST ACTION registration fails open here, as in every
     sibling SubagentStop hook.
  3. The entry carries dev_session_id (legacy flat entries skip).
  4. .claude/dev-registry/<sid>/artifact-contract-enforce.json exists with
     enabled == true (written by scripts/write-enforce-flag.sh
     --flag artifact-contract from /dev-family init and /close Step 2).
  5. The producer's own dispatch declares the reports it owes (its json
     artifacts, read as declared also when the block fails the grammar, as a
     pre-P1 template's does; P1b E3): no name decides whose a report is.

Every declared report on disk is validated, each one, rather than a single
pick: picking one file would let an invalid report be shadowed by a valid
sibling (codex audit finding, HIGH). Each producer is judged on its own
reports at its own stop, never on a sibling lane's; a BA-validation QA
declares the BA-QA report, which no report schema of the engine covers.

Mode: ARTIFACT_CONTRACT_ENFORCE_MODE environment variable.
  "block" (default) — schema-fail exits 2 with an
                      ARTIFACT_CONTRACT_BLOCKED message.
  "advisory"        — schema-fail allows the stop.
  Default is block — unlike cp-enforce's advisory-first default — because
  the validator is not new judgment: the identical engine already blocks
  these exact reports at /close today; this hook only moves WHERE the
  rejection lands (user ruling 2026-09-26). The env var is the kill-switch.

Exit codes:
  0: Allow stop (pass-through).
  2: Block stop (ARTIFACT_CONTRACT_BLOCKED — repair the report first).

Spec alignment (2026-09-26, do-20260926-073930): this hook is a PROPER SUBSET
of docs/dev/specs/spec-20260914-052140.md §5.1 (contract-driven SubagentStop
source-blocking of MISSING artifacts, still pending, never checked out) — it
implements only the schema-wellformedness half of that spec's
_artifact_valid_for_entry() end state, for the two roles whose reports already
carry versioned schemas, via the existing enforce-flag channel instead of
cycle-contract required_calls[]. It does NOT implement and does NOT supersede
§5.1: missing-artifact blocking, contract-driven role coverage, the role-enum
extension, prerequisite (f) (hooks reading the contract), and the advisory-log
cleanup precondition (c) all remain that spec's scope. When §5.1 lands, its
mechanism subsumes this hook's check (existence + schema in one entry lookup):
retire this hook or fold it into the contract-driven gate at that point rather
than running both. Rollout style follows spec-20260916-031427 §8.1
(no over-engineering: reuse existing plumbing, no new mechanism); the
default-block-instead-of-advisory-first deviation from that spec's §5.2 is
deliberate and evidence-backed — the blocking predicate is not new judgment
(the identical engine already blocks the identical reports at /close's
Artifact schema gate;
measured 674-report corpus: 0 fail) and the user ordered immediate blocking
on 2026-09-26; ARTIFACT_CONTRACT_ENFORCE_MODE=advisory is the rollback lever.
"""

import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.agent_resolver import resolve_dev_registry_entry
from lib import contract_runtime
from lib import dispatch_template
from lib import obligation

def _load_stdin() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _last_nonempty_line(text: str) -> str:
    """Return the last non-blank line of ``text`` (or '' when none)."""
    non_empty = [ln for ln in (text or "").splitlines() if ln.strip()]
    return non_empty[-1] if non_empty else ""


def _classify_verdict_line(line: str) -> str:
    """Classify a CLOSE: terminal line via the canonical close-verdict
    classifier (hooks/lib/close-verdict.py), loaded with SourceFileLoader
    (hyphenated filename -- same technique as scripts/close-report-
    append.py:205-211) so the AC5 consistency check can never silently
    drift from the authoritative classifier's own rules. Fail-open: any
    load/classify problem returns 'unknown', which never trips the
    verdict_class inconsistency check below (both sides must classify to
    'yes'/'no')."""
    try:
        from importlib.machinery import SourceFileLoader

        cv_path = Path(__file__).parent / "lib" / "close-verdict.py"
        module = SourceFileLoader("close_verdict", str(cv_path)).load_module()
        return module.classify_line(line)
    except Exception:
        return "unknown"


def _dispatch_obligation(prompt) -> dict:
    """This producer's own dispatch obligation as declared, read even when the
    block fails the grammar (a pre-P1 template still carries required_values),
    so the legacy check knows which reports are its own and which it owes; {}
    when the prompt carries none."""
    block = obligation.extract_obligation_block(prompt) if isinstance(prompt, str) else None
    if not isinstance(block, obligation.ExtractedBlock):
        return {}
    try:
        doc = json.loads(block.body)
    except ValueError:
        return {}
    return doc if isinstance(doc, dict) else {}


# ---------------------------------------------------------------------------
# Producer stop gate (lane L2): the dev report's own downstream wires. A
# failing stop is a plain exit 2 naming each failing artifact and its check to
# the stopping producer, in every round; nothing admits it but a repair. A wire
# that cannot run (a checker that will not load, crashes or times out) judges
# nothing: the producer's repair could not clear it, so it never blocks.
# ---------------------------------------------------------------------------

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
WIRE_FILE_TIMEOUT_S = 30
WIRE_TOTAL_BUDGET_S = 120


class _WireTimeout(BaseException):
    """Raised by the alarm handler; BaseException so no broad except eats it."""


def _load_script_module(script_name: str):
    loader_path = SCRIPTS_DIR / "lib" / "sibling_loader.py"
    spec = importlib.util.spec_from_file_location("l2_sibling_loader", loader_path)
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    return loader.load_sibling_module(script_name, str(SCRIPTS_DIR / "placeholder.py"))


def _nested_claude_repo() -> list:
    """Same supported-repository admission /commit Step 5 passes: the real
    harness checkout this hook is installed in (omitted when it is not a git checkout)."""
    try:
        real = str(SCRIPTS_DIR.parent)
        proc = subprocess.run(
            ["git", "-C", real, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
        top = proc.stdout.strip()
        return [top] if proc.returncode == 0 and top else []
    except Exception:
        return []


def _with_alarm(seconds: float, fn):
    def _handler(signum, frame):
        raise _WireTimeout()

    try:
        previous = signal.signal(signal.SIGALRM, _handler)
    except (ValueError, AttributeError):
        return fn()
    signal.setitimer(signal.ITIMER_REAL, max(seconds, 0.05))
    try:
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _wire_trial_plan(report_full: Path, report_rel: str, project_dir: str, task_id: str):
    """Findings: PlanError of any code (or none) is a finding against the
    producer's report; a planner that will not load or times out judges
    nothing."""
    try:
        mod = _load_script_module("resolve-commit-repos.py")
    except Exception:
        return []
    try:
        _with_alarm(
            WIRE_FILE_TIMEOUT_S,
            lambda: mod.build_plan(
                task_id=task_id, control_root_arg=project_dir,
                supported_repo_args=_nested_claude_repo(), report_arg=str(report_full),
            ),
        )
    except _WireTimeout:
        return []
    except mod.PlanError as exc:
        code = getattr(exc, "code", None) or "uncoded"
        return [{
            "path": report_rel, "reason": "repository_plan_error",
            "errors": [f"/commit would reject this report (consumer: resolve-commit-repos.py build_plan), code={code}: {exc}"],
        }]
    return []


def _load_lib_module(name: str):
    """Load scripts/lib/<name>.py by path (scripts/lib, not scripts/ -- see
    _load_script_module for the sibling-script loader this complements)."""
    path = SCRIPTS_DIR / "lib" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _wire_ledger_judgment(report: dict, project_dir: str, task_id: str, deadline: float) -> list:
    """Attribution-journal consumer cutover (docs/reference/attribution-
    journal-cutover-flip-plan-20261003.md, superseded by the zero-blocking
    constraint of the follow-up consumer-cutover task): replaces this hook's
    two self-reported-ledger replay checks -- check-owned-edits-ledger.py's
    structural+replay validation and stage-owned-hunks.py --dry-run's hunk-
    replay exclusion. check-owned-edits-ledger.py has since been deleted;
    stage-owned-hunks.py still exists but is no longer invoked from this
    blocking path.

    Every path this cycle claims (dev.files_modified + dev.files_created) is
    asked the SAME lane-agnostic question scripts/resolve-commit-repos.py's
    ownership gate now asks (scripts/lib/attribution_adjudicator.py
    ledger_structural_verdict()): does the write-time hash-chain journal
    measure a structural conflict (ENTANGLED) for this path? Only that
    blocks here. No journal evidence at all, or evidence that does not
    reach back to the current HEAD blob, is deferred to the commit
    analyst's own judgment (agents/changelog-analyst.md's "Attribution and
    staging decision" is the actual staging authority, not this gate) --
    never a finding. A journal/adjudicator read failure, or a budget spent
    before every path was asked, judges the paths not asked: no finding.
    """
    dev = report.get("dev") if isinstance(report.get("dev"), dict) else {}
    modified = dev.get("files_modified") if isinstance(dev.get("files_modified"), list) else []
    created = dev.get("files_created") if isinstance(dev.get("files_created"), list) else []
    paths = sorted({p for p in (modified + created) if isinstance(p, str) and p})
    findings = []
    if not paths:
        return findings
    try:
        ledger = _load_lib_module("attribution_adjudicator")
    except Exception:
        return findings
    for rel in paths:
        if time.monotonic() > deadline:
            break
        absolute = str(Path(project_dir) / rel)
        try:
            verdict = ledger.ledger_structural_verdict(absolute, root=project_dir, task_id=task_id)
        except Exception:
            continue
        if verdict.get("verdict") == ledger.ENTANGLED:
            findings.append({
                "path": rel, "reason": "ledger_entangled_conflict",
                "errors": [("write-time attribution journal (consumer: attribution_adjudicator.py) measures "
                           f"an unresolved structural conflict for this file: {verdict.get('detail', '')}")[:400]],
            })
    return findings


def _run_downstream_wires(project_dir: str, ob: dict, json_artifacts: list) -> list:
    """The dev report's wires (ledger judgment and /commit's trial plan).
    Returns findings. Another producer's artifact is never judged at this
    stop: G3 decides on it at the next dispatch."""
    findings = []
    if ob.get("role") != "dev":
        return findings
    deadline = time.monotonic() + WIRE_TOTAL_BUDGET_S
    lane_set = ob.get("lane_set")
    # A lane's report alone is not the cycle /commit plans: the trial plan
    # runs on a singular report only.
    shard = isinstance(lane_set, list) and len(lane_set) > 1
    for art in json_artifacts:
        # Only the v2 report carries the nested dev section, owned_edits
        # ledger and pre_edit_snapshots the downstream consumers read; the
        # flat v1 shape is unplannable by /commit itself and is shape-gated
        # only (schema + identity + terminal state).
        if not str(art.get("schema", "")).startswith("dev-report.v2"):
            continue
        report_rel = art["path"]
        report_full = Path(project_dir) / report_rel
        task_id = str(ob.get("task_id"))
        findings += _wire_ledger_judgment(_read_json(report_full), project_dir, task_id, deadline)
        if not shard:
            findings += _wire_trial_plan(report_full, report_rel, project_dir, task_id)
    return findings


def _template_declared(resolution):
    """P1b row 8: a spec subagent dispatched from the base's /spec template
    carries no obligation, yet its split is checked by the rule the current
    /spec template declares for it (dispatch_template: the template of the
    command whose span holds the dispatch, bound to the dispatch's own values).
    Only that rule is taken from the template: a Resolved holding the declared
    spec_views entries, or None."""
    found = dispatch_template.dispatch_of(resolution.transcript_path)
    declared = dispatch_template.template_obligation(*found) if found else None
    views = [a for a in (declared or {}).get("artifacts", []) if a.get("kind") == "spec_views"]
    if not views:
        return None
    return obligation.Resolved(
        obligation=dict(declared, artifacts=views), rung=resolution.rung, prompt=resolution.prompt,
        transcript_path=resolution.transcript_path, cross_check=resolution.cross_check,
    )


def _spec_views_failure(project_dir: str, art: dict):
    """P1b row 8 (moved from stop-spec-coverage-enforce.py): a split's own
    properties at its producer's stop, `spec-verify.py --strict` on the declared
    views against the declared monolith (coverage 100%, pairwise overlap and
    per-view uniqueness thresholds). A missing verifier checks nothing, as the
    Stop hook it replaces did."""
    verifier = SCRIPTS_DIR / "spec-verify" / "spec-verify.py"
    if not verifier.is_file():
        return None
    monolith = Path(project_dir) / art["monolith"]
    views = Path(project_dir) / art["path"]
    if not monolith.is_file() or not views.is_dir():
        return {"path": art["path"], "reason": "spec_views_missing",
                "errors": [f"monolith {art['monolith']} or views directory {art['path']} does not exist"]}
    try:
        run = subprocess.run(
            [sys.executable, str(verifier), "--monolith", str(monolith), "--views-dir", str(views), "--strict"],
            capture_output=True, text=True, timeout=WIRE_FILE_TIMEOUT_S, cwd=project_dir,
        )
    except subprocess.TimeoutExpired:
        return {"path": art["path"], "reason": "spec_verify_timeout",
                "errors": [f"spec-verify.py --strict ran longer than {WIRE_FILE_TIMEOUT_S}s"]}
    if run.returncode == 0:
        return None
    lines = [line.strip() for line in (run.stdout + run.stderr).splitlines() if line.strip()]
    # The verifier's summary rows that FAIL name the check and what failed in
    # it (a structural row names the view and the section it lacks); a plain
    # tail cuts the coverage and structural rows off behind the PASS rows.
    failed = [line for line in lines if re.match(r"\w+:\s+FAIL\b", line)]
    return {"path": art["path"], "reason": "spec_verify_strict_failed", "errors": (failed or lines)[-10:]}


def _producer_question(project_dir: str, ob: dict):
    """TC-33: docs/dev/producer-question-<task_id>-<role>.json named by the
    obligation's own task_id and role. Which producers may ask is the
    producer-question.v1 schema's role enum (ba and dev, D23), so a question
    from any other role is schema-invalid. Returns None when absent or not
    fresh against the obligation's dispatched_at (a file from an earlier
    round; None freshness counts as stale), "valid" when it stands in for the
    declared artifacts, else a failure naming why it is invalid."""
    rel = f"docs/dev/producer-question-{ob.get('task_id')}-{ob.get('role')}.json"
    full = Path(project_dir) / rel
    try:
        mtime = full.stat().st_mtime
    except OSError:
        return None
    if obligation.artifact_freshness_satisfied("json", mtime, ob.get("dispatched_at")) is not True:
        return None
    result = contract_runtime.validate_artifact_for_obligation(str(full), "producer-question.v1")
    errors = list(result.get("errors", []))[:10] or [str(result.get("reason"))]
    if result.get("status") == "pass":
        record = _read_json(full)
        labels = [o.get("label") for o in record.get("options", []) if isinstance(o, dict)]
        errors = [f"{key}: obligation declares {ob.get(key)!r}, file has {record.get(key)!r}"
                  for key in ("task_id", "role") if record.get(key) != ob.get(key)]
        if record.get("default") not in labels:
            errors.append(f"default {record.get('default')!r} is not one of the option labels {labels}")
        if not errors:
            return "valid"
    return {"path": rel, "reason": "producer_question_invalid", "errors": errors}


def main() -> None:
    data = _load_stdin()
    if not data:
        sys.exit(0)

    agent_id = data.get("agent_id")
    if not agent_id:
        sys.exit(0)

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())

    # Resolved unconditionally (no early-exit here): the obligation-mode
    # block below does not depend on agent-index.json / resolve_dev_registry_entry
    # at all (hooks/lib/obligation.py has zero references to either). The
    # LOW-10 "never hard-block on an unresolved agent" early-exits are
    # deferred to immediately before the LEGACY correlation path's first
    # actual use of dev_session_id, below -- relocated so a skipped FIRST
    # ACTION registry Read no longer silently discards obligation-mode
    # enforcement of the agent's own dev-report/context.json obligation too.
    entry = resolve_dev_registry_entry(agent_id, project_dir)
    agent_type = entry.get("agent_type", "") if entry else ""

    # Obligation mode (rollout S4): verify the artifacts THIS agent's own
    # dispatch obligation names, ahead of the session-wide correlation guess
    # below. CLAUDE_OBLIGATION_STOPGATE is a DIFFERENT switch from
    # ARTIFACT_CONTRACT_ENFORCE_MODE, which continues to govern only the
    # untouched legacy path.
    stopgate_mode = os.environ.get("CLAUDE_OBLIGATION_STOPGATE", "advisory").strip().lower()
    if stopgate_mode not in {"advisory", "block", "off"}:
        stopgate_mode = "advisory"
    resolution = None
    if stopgate_mode != "off":
        try:
            session_id = data.get("session_id") or data.get("sessionId")
            transcript_hint = data.get("agent_transcript_path")
            last_assistant_message = data.get("last_assistant_message")
            resolution = obligation.resolve_own_obligation(
                session_id=session_id,
                agent_id=agent_id,
                project_dir=project_dir,
                payload_agent_transcript_path=transcript_hint,
                # Every template and canonical todo step declares a dispatch's
                # role as its subagent_type (G1 refuses any other), the type
                # this agent registered as; no role list says which.
                expected_role=agent_type or None,
            )
            if isinstance(resolution, obligation.NoObligationInPrompt):
                resolution = _template_declared(resolution) or resolution
            if isinstance(resolution, obligation.Resolved):
                artifacts = resolution.obligation.get("artifacts", [])
                json_artifacts = [a for a in artifacts if a.get("kind") == "json"]
                markdown_artifacts = [a for a in artifacts if a.get("kind") == "markdown"]
                response_line_artifacts = [a for a in artifacts if a.get("kind") == "response_line"]
                response_block_artifacts = [a for a in artifacts if a.get("kind") == "response_block"]
                spec_views_artifacts = [a for a in artifacts if a.get("kind") == "spec_views"]
                # W1/M4: any other kind belongs to a different G5 bullet;
                # it is skipped here, never blocked or crashed on.
                verified_artifacts = (
                    json_artifacts + markdown_artifacts + response_line_artifacts
                    + response_block_artifacts + spec_views_artifacts
                )
                failures = []
                question = _producer_question(project_dir, resolution.obligation)
                if question == "valid":
                    # The question stands in for every declared artifact; nothing
                    # that reads those artifacts runs for this stop.
                    sys.exit(0)
                if question is not None:
                    failures.append(question)
                for art in json_artifacts:
                    full_path = Path(project_dir) / art["path"]
                    result = contract_runtime.validate_artifact_for_obligation(
                        str(full_path), art["schema"]
                    )
                    if result.get("status") == "skip":
                        # Infra unavailable (unregistered schema id, registry
                        # error): fail-safe, never a verification failure.
                        continue
                    if result.get("status") == "fail":
                        failures.append(
                            {
                                "path": art["path"],
                                "reason": result.get("reason"),
                                "errors": result.get("errors", [])[:10],
                            }
                        )
                        continue
                    # "pass": identity comparison is this lane's own
                    # responsibility (validate_artifact_for_obligation does
                    # not check it).
                    record = _read_json(full_path)
                    for key, value in art.get("identity", {}).items():
                        if record.get(key) != value:
                            failures.append(
                                {
                                    "path": art["path"],
                                    "reason": "identity_mismatch",
                                    "errors": [
                                        f"identity.{key}: obligation declares "
                                        f"{value!r}, file has {record.get(key)!r}"
                                    ],
                                }
                            )
                markdown_waived_paths: set[str] = set()
                for art in markdown_artifacts:
                    # M3: markdown-kind entries get the same producer-side
                    # Stop verification json-kind entries already have,
                    # reusing the shared contract_runtime function (ticket
                    # 20261001-161041-r01) -- folded into the SAME
                    # failures/advisory/block control flow, no new branch.
                    #
                    # waived_by_response (ticket 20261001-161041-r12, AC4):
                    # an append-sentinel response means
                    # scripts/close-report-append.py itself already refused
                    # to touch the file -- its on-disk terminal line
                    # reflects a PRIOR, unrelated attempt, so the file
                    # check is SKIPPED (not failed) and excluded from the
                    # consistency check below. Matched against the reply's
                    # final non-empty line, the line response_line checks.
                    waiver = art.get("waived_by_response")
                    if (
                        isinstance(waiver, str) and waiver
                        and isinstance(last_assistant_message, str)
                        and re.search(waiver, _last_nonempty_line(last_assistant_message))
                    ):
                        markdown_waived_paths.add(art["path"])
                        continue
                    full_path = Path(project_dir) / art["path"]
                    result = contract_runtime.validate_markdown_artifact_for_obligation(
                        str(full_path), art.get("identity_anchor"), art.get("terminal_line_regex")
                    )
                    if result.get("status") == "fail":
                        failures.append(
                            {
                                "path": art["path"],
                                "reason": result.get("reason"),
                                "errors": result.get("errors", [])[:10],
                            }
                        )
                for art in response_line_artifacts:
                    # response_line-kind entries (ticket 20261001-161041-r12,
                    # AC3): validated against this agent's OWN final
                    # response text, independent of the markdown file
                    # channel above -- a failure here never suppresses, and
                    # is never suppressed by, a markdown-channel result.
                    result = contract_runtime.validate_response_line_for_obligation(
                        last_assistant_message, art.get("terminal_line_regex")
                    )
                    if result.get("status") == "fail":
                        failures.append(
                            {
                                "path": "<response_line>",
                                "reason": result.get("reason"),
                                "errors": result.get("errors", [])[:10],
                            }
                        )
                for art in spec_views_artifacts:
                    failure = _spec_views_failure(project_dir, art)
                    if failure is not None:
                        failures.append(failure)
                for art in response_block_artifacts:
                    # response_block-kind entries (ticket 20261001-161041-r21,
                    # M2): validated against this agent's OWN final response
                    # text via the sentinel-delimited JSON block it declares
                    # (e.g. changelog-analyst's changelog-status.v1), reusing
                    # the SAME last_assistant_message field response_line
                    # already keys off -- no transcript scan, no second
                    # jsonschema call path (see
                    # contract_runtime.validate_response_block_for_obligation).
                    result = contract_runtime.validate_response_block_for_obligation(
                        last_assistant_message, art.get("begin"), art.get("end"), art["schema"]
                    )
                    if result.get("status") == "skip":
                        continue
                    if result.get("status") == "fail":
                        failures.append(
                            {
                                "path": "<response_block>",
                                "reason": result.get("reason"),
                                "errors": result.get("errors", [])[:10],
                            }
                        )
                # Cross-channel consistency (ticket 20261001-161041-r12,
                # AC5): the markdown artifact's file terminal line and the
                # response_line artifact's response terminal line must
                # classify to the same CLOSE: verdict. Skipped when the
                # obligation does not declare consistency:"verdict_class",
                # either channel is absent, the markdown channel was
                # waived (no file verdict to compare), or either channel's
                # own check already failed above (that failure is already
                # reported; a derived inconsistency would be redundant).
                if (
                    resolution.obligation.get("consistency") == "verdict_class"
                    and markdown_artifacts and response_line_artifacts
                    and not markdown_waived_paths
                    and not failures
                ):
                    try:
                        md_path = Path(project_dir) / markdown_artifacts[0]["path"]
                        md_class = _classify_verdict_line(
                            _last_nonempty_line(md_path.read_text(encoding="utf-8"))
                        )
                        resp_text = (
                            last_assistant_message
                            if isinstance(last_assistant_message, str) else ""
                        )
                        resp_class = _classify_verdict_line(_last_nonempty_line(resp_text))
                        if (
                            md_class in ("yes", "no") and resp_class in ("yes", "no")
                            and md_class != resp_class
                        ):
                            failures.append(
                                {
                                    "path": markdown_artifacts[0]["path"],
                                    "reason": "verdict_class_inconsistent",
                                    "errors": [
                                        f"file classifies '{md_class}', response classifies '{resp_class}'"
                                    ],
                                }
                            )
                    except Exception:
                        pass  # fail-open: never block on consistency-check infra errors
                # Downstream wires (L2): only once the artifacts themselves are
                # shape- and terminal-valid, so the checkers see a usable report.
                if not failures:
                    try:
                        failures.extend(
                            _run_downstream_wires(project_dir, resolution.obligation, json_artifacts)
                        )
                    except Exception:
                        pass  # a crashed wire judges nothing (see its section comment)
                if not failures:
                    # M3: all pass -- bypass the legacy correlation path
                    # entirely for this stop.
                    sys.exit(0)
                if stopgate_mode == "block":
                    detail_lines = ""
                    for f in failures[:10]:
                        detail_lines += f"  - {f['path']}: {f['reason']}\n"
                        for err in f.get("errors", [])[:10]:
                            detail_lines += f"    {err}\n"
                    sys.stderr.write(
                        f"OBLIGATION_STOPGATE_BLOCKED: agent {agent_id} "
                        f"(role={resolution.obligation.get('role')}, "
                        f"task_id={resolution.obligation.get('task_id')}) declared "
                        f"{len(verified_artifacts)} obligated artifact(s); "
                        f"{len(failures)} failed verification:\n"
                        f"{detail_lines}"
                        f"Fix your OWN artifact(s) listed above, then stop "
                        f"again. Do NOT edit any other agent's artifact.\n"
                    )
                    sys.exit(2)
                # advisory mode: never blocks (AC4/AC5).
                sys.exit(0)
            # Unresolvable or NoObligationInPrompt: the legacy path below
            # decides.
        except Exception:
            # M4: an obligation-mode-only failure must degrade to "run
            # legacy path", never "allow" and never escape from inside
            # this except block.
            pass

    # LOW-10: never hard-block the legacy correlation path on an
    # unresolved agent. Deferred here (was previously gating the
    # obligation-mode block above too) because only this legacy path
    # actually needs dev_session_id.
    if entry is None:
        sys.exit(0)
    dev_session_id = entry.get("dev_session_id")
    if not dev_session_id:
        sys.exit(0)

    registry_dir = Path(project_dir) / ".claude" / "dev-registry" / dev_session_id

    flag = _read_json(registry_dir / "artifact-contract-enforce.json")
    if not flag.get("enabled"):
        sys.exit(0)

    # The reports this producer owes are the json artifacts its own dispatch
    # declares, read as declared even when the block fails the grammar (a
    # pre-P1 template): each producer is judged on its own reports at its own
    # stop, never on a sibling lane's. validate_report_artifact decides the
    # dev, qa and do report kinds and skips every other.
    declared = _dispatch_obligation(getattr(resolution, "prompt", None))
    report_paths = [
        Path(project_dir) / a["path"]
        for a in declared.get("artifacts") or []
        if isinstance(a, dict) and a.get("kind") == "json"
        and obligation._legal_repo_relative_path(a.get("path"))
    ]
    report_paths = [p for p in report_paths if p.is_file()]
    if not report_paths:
        # Existence enforcement belongs to subagentstop-e2e-enforce.py (qa)
        # and /close's chain resolver (dev). Never block here.
        sys.exit(0)

    failures = []
    for report_path in report_paths:
        result = contract_runtime.validate_report_artifact(str(report_path))
        if result.get("status") == "fail":
            failures.append((report_path, result))
    if not failures:
        sys.exit(0)

    mode = os.environ.get("ARTIFACT_CONTRACT_ENFORCE_MODE", "block").strip().lower()
    if mode == "advisory":
        sys.exit(0)

    detail_lines = ""
    for p, r in failures[:5]:
        detail_lines += f"  report {p} violates schema {r.get('schema')!r}:\n"
        detail_lines += "".join(f"    - {e}\n" for e in r.get("errors", [])[:10])
    sys.stderr.write(
        f"ARTIFACT_CONTRACT_BLOCKED: agent {agent_id} (type={agent_type}) in "
        f"session {dev_session_id}: {len(failures)} correlated report(s) "
        f"declare report_version but violate their schema.\n"
        f"{detail_lines}"
        f"This is the same check /close's Artifact schema gate applies — /close would "
        f"reject these reports identically. Repair the named report(s) so they "
        f"satisfy their declared schema before stopping. If a named report was "
        f"written by a sibling lane agent, report the blockage instead of "
        f"editing a peer's artifact.\n"
    )
    sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # A hook bug must never trap a subagent exit.
        sys.exit(0)
