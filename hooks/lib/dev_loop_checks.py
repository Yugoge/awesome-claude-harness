#!/usr/bin/env python3
"""Advice to the orchestrator around a dev dispatch: the anti-loop checks, tied to the dispatch's own task.

Five hooks held these checks (pretool-layer-escalation-check.sh, pretool-bisect-gate.sh,
pretool-layer-match-gate.sh, subagent-stop-guard-integrity.sh, subagent-stop-diff-check.sh).
Each guessed its task from the newest docs/dev/context-*.json (hooks-audit O10), and each
wrote to stderr and exited 0, which reaches no model (hooks-audit 5.1). Their messages
are meant for the orchestrator ("BA should re-analyze before Dev proceeds", "the
orchestrator should reject this fix"). This module gives them to it, as
``additionalContext`` on its own Agent call (code.claude.com/docs/en/hooks: PreToolUse and
PostToolUse), and never refuses the call, as none of them did.

The task is the dev dispatch's own: its obligation declares
``docs/dev/dev-report-<X>.json`` (X is the task id, lane-suffixed in a fan-out lane), and
its BA context is ``docs/dev/context-<X>.json``. A dispatch that is not dev's, or carries no
such declaration, gets no advice.

- PreToolUse (before the dev runs):
  - layer escalation: two or more prior attempts, all at one layer, and the diagnosis
    targets that layer again;
  - bisect: a regression (the checklist's flag, or the complaint's words) whose root cause
    analysis has no git_bisect_result.
- PostToolUse (the dev returned):
  - layer match: the report's fix_layer differs from the context's diagnosis_layer;
  - guard integrity: the working tree's diff against HEAD removes a guard the context
    marks removal_authorized=false;
  - minimum diff: more than 30 inserted lines in the files the report names, with no
    dev.diff_stats.justification_for_overage or dev.scope_review_requested. Checkpoints
    never move HEAD (lib/checkpoint-core.sh), so the old HEAD~5..HEAD window counted the
    user's own recent commits; the dev's work is the uncommitted diff.

Run as ``__main__`` (a rule of the dispatch gates, or a hook on its own): the payload on
stdin, one JSON object on stdout when there is advice, exit 0 always.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

_HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

REPORT_RE = re.compile(r"(?:^|/)docs/dev/dev-report-([^/]+)\.json$")
REGRESSION_RE = re.compile(r"was working|used to|broke|regression|以前|原本", re.IGNORECASE)
DIFF_THRESHOLD = 30


def _project_dir(payload: dict) -> str:
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()


def _load(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            value = json.load(fh)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _task_suffix(prompt) -> str | None:
    """X of the docs/dev/dev-report-<X>.json the dispatch's obligation declares, or None."""
    from lib.obligation import ExtractedBlock, extract_obligation_block
    block = extract_obligation_block(prompt)
    if not isinstance(block, ExtractedBlock):
        return None
    try:
        doc = json.loads(block.body)
    except ValueError:
        return None
    if not isinstance(doc, dict) or doc.get("role") != "dev":
        return None
    for artifact in doc.get("artifacts") or []:
        path = artifact.get("path") if isinstance(artifact, dict) else None
        match = REPORT_RE.search(path) if isinstance(path, str) else None
        if match:
            return match.group(1)
    return None


def _text(value) -> str:
    """A field as jq -r printed it: a string as is, anything else as JSON."""
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value)


def layer_escalation(ctx: dict, ctx_rel: str) -> list[str]:
    attempts = ctx.get("prior_attempts")
    if not isinstance(attempts, list) or len(attempts) < 2:
        return []
    layers = [a.get("target_layer") for a in attempts if isinstance(a, dict) and a.get("target_layer") is not None]
    current = ctx.get("diagnosis_layer")
    last = attempts[-1].get("target_layer") if isinstance(attempts[-1], dict) else None
    if len(set(map(str, layers))) == 1 and current and str(current) == str(last):
        return [f"SAME-LAYER RETRY DETECTED\n{len(attempts)} prior attempts all at layer {current} failed.\n"
                f"This cycle is ALSO targeting {current}. Policy: escalate to a different layer.\n"
                f"BA should re-analyze at an upstream layer before Dev proceeds.\nContext: {ctx_rel}"]
    return []


def _bisect_present(ctx: dict) -> bool:
    for holder in (ctx.get("root_cause_analysis"), ctx):
        result = holder.get("git_bisect_result") if isinstance(holder, dict) else None
        if isinstance(result, dict) and (result.get("suspect_commit") or result.get("bisect_blocked")):
            return True
    return False


def bisect(ctx: dict, ctx_rel: str) -> list[str]:
    checklist = ctx.get("regression_investigation_checklist")
    triggered = isinstance(checklist, dict) and checklist.get("triggered") is True
    complaint = _text(ctx.get("user_verbatim_complaint") or ctx.get("requirement"))
    if not (triggered or REGRESSION_RE.search(complaint)) or _bisect_present(ctx):
        return []
    return ["REGRESSION BUG WITHOUT BISECT\nUser complaint appears to be a regression but BA's context has no "
            "git_bisect_result.\nRequired: root_cause_analysis.git_bisect_result must have either suspect_commit "
            f"or bisect_blocked reason.\nBA should re-run with git bisect before Dev proceeds.\nContext: {ctx_rel}"]


def layer_match(ctx: dict, report: dict, ctx_rel: str, rep_rel: str) -> list[str]:
    diag = ctx.get("diagnosis_layer")
    dev = report.get("dev") if isinstance(report.get("dev"), dict) else {}
    fix = dev.get("fix_layer") or report.get("fix_layer")
    if not diag or not fix or str(diag) == str(fix):
        return []
    return [f"LAYER MISMATCH\nBA diagnosed at {diag}, Dev fixed at {fix}.\n"
            "If intentional, dev must declare scope_review_requested with justification.\n"
            f"Otherwise the orchestrator should reject this fix and request BA re-analysis.\n"
            f"Context: {ctx_rel}\nReport:  {rep_rel}"]


def _git(project: str, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", project, *args], capture_output=True, text=True,
                              timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def guard_integrity(ctx: dict, project: str, ctx_rel: str) -> list[str]:
    guards = [g for g in ctx.get("pre_existing_guards") or []
              if isinstance(g, dict) and g.get("removal_authorized") is False and g.get("code_snippet")]
    if not guards:
        return []
    removed = [line for line in _git(project, "diff", "HEAD").splitlines()
               if line.startswith("-") and not line.startswith("---")]
    out = []
    for g in guards:
        snippet = str(g["code_snippet"])
        if any(snippet in line for line in removed):
            out.append(f"UNAUTHORIZED GUARD REMOVAL\nFile: {g.get('file', 'unknown')}\nGuard: {snippet}\n"
                       f"Purpose: {g.get('purpose', 'unspecified')}\n"
                       "This guard has removal_authorized=false. Removing it requires BA authorization.\n"
                       f"Context: {ctx_rel}")
    return out


def minimum_diff(report: dict, project: str, rep_rel: str) -> list[str]:
    dev = report.get("dev") if isinstance(report.get("dev"), dict) else {}
    stats = dev.get("diff_stats") if isinstance(dev.get("diff_stats"), dict) else {}
    if stats.get("justification_for_overage") or dev.get("scope_review_requested"):
        return []
    files = [f for f in (dev.get("files_modified") or []) + (dev.get("files_created") or []) if isinstance(f, str)]
    stat = _git(project, "diff", "HEAD", "--shortstat", *(["--"] + files if files else []))
    match = re.search(r"(\d+) insertion", stat)
    total = int(match.group(1)) if match else 0
    if total <= DIFF_THRESHOLD:
        return []
    return [f"MINIMUM-DIFF RULE WARNING\nThe dev's uncommitted diff adds {total} lines (threshold: {DIFF_THRESHOLD}).\n"
            f"No justification in {rep_rel}.\nExpected one of:\n"
            '  dev.diff_stats.justification_for_overage = "<why the minimum diff cannot be smaller>"\n'
            "OR\n  dev.scope_review_requested = true\n"
            "If this was a legitimately large fix, the dev should have populated the justification field. "
            "If this was unauthorized refactoring, the orchestrator should reject and request a surgical redo."]


def advice(payload: dict) -> list[str]:
    """The advice for this Agent call, by its event; [] when there is none."""
    if payload.get("tool_name") not in ("Agent", "Task"):
        return []
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if tool_input.get("subagent_type") != "dev":
        return []
    suffix = _task_suffix(tool_input.get("prompt"))
    if suffix is None:
        return []
    project = _project_dir(payload)
    ctx_rel, rep_rel = f"docs/dev/context-{suffix}.json", f"docs/dev/dev-report-{suffix}.json"
    ctx = _load(os.path.join(project, ctx_rel))
    event = payload.get("hook_event_name")
    if ctx is None:
        return []
    if event == "PreToolUse":
        return layer_escalation(ctx, ctx_rel) + bisect(ctx, ctx_rel)
    if event == "PostToolUse":
        report = _load(os.path.join(project, rep_rel)) or {}
        return (layer_match(ctx, report, ctx_rel, rep_rel) + guard_integrity(ctx, project, ctx_rel)
                + (minimum_diff(report, project, rep_rel) if report else []))
    return []


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        found = advice(payload) if isinstance(payload, dict) else []
    except Exception:
        return 0  # advice never wedges a dispatch
    if found:
        sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": payload["hook_event_name"],
                                                            "additionalContext": "\n\n".join(found)}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
