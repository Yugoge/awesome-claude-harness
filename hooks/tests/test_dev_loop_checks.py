"""hooks/lib/dev_loop_checks.py: the five anti-loop checks, for the orchestrator, on the dev dispatch's own task.

- Before a dev dispatch (PreToolUse): layer escalation and bisect; after it returns (PostToolUse):
  layer match, guard integrity and minimum diff. The advice is additionalContext JSON (it reaches the
  orchestrator); the call is never refused; exit 0 always.
- The task is the one the dispatch's obligation names (its dev-report artifact), not the newest
  docs/dev/context-*.json (hooks-audit O10): a newer context of another task changes nothing.
- Minimum diff counts the uncommitted diff of the files the report names, never HEAD~5..HEAD
  (checkpoints do not move HEAD, so those commits are the user's own).
- Where the old shell hook found its task (one context, the newest), the message text is the same.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "hooks" / "lib" / "dev_loop_checks.py"
TASK = "20261109-101010"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.invalid",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.invalid"}).stdout


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "proj"
    (p / "docs" / "dev").mkdir(parents=True)
    (p / "src").mkdir()
    (p / "src" / "app.py").write_text("def check(x):\n    if x is None:\n        raise ValueError('x')\n    return x\n")
    subprocess.run(["git", "init", "-q", str(p)], check=True)
    _git(p, "add", "-A")
    _git(p, "commit", "-q", "-m", "init")
    return p


def _prompt(task: str = TASK, role: str = "dev") -> str:
    doc = {"task_id": task.split("-lane")[0], "role": role, "pipeline": "dev", "profile": "singular",
           "dispatched_at": "2026-11-09T10:10:10Z",
           "artifacts": [{"kind": "json", "path": f"docs/dev/dev-report-{task}.json", "schema": "dev-report.v2",
                          "identity": {"task_id": task}}]}
    return f"You are the dev subagent.\n<obligation v=\"1\">\n{json.dumps(doc)}\n</obligation>\n"


def _run(proj: Path, event: str, prompt: str | None = None, subagent_type: str = "dev", raw: str | None = None):
    payload = raw if raw is not None else json.dumps({
        "hook_event_name": event, "tool_name": "Agent", "session_id": "s1", "cwd": str(proj),
        "tool_input": {"description": "d", "subagent_type": subagent_type,
                       "prompt": _prompt() if prompt is None else prompt}})
    proc = subprocess.run([sys.executable, str(MODULE)], input=payload, capture_output=True, text=True,
                          env={**os.environ, "CLAUDE_PROJECT_DIR": str(proj), "PYTHONDONTWRITEBYTECODE": "1"},
                          timeout=60)
    assert (proc.returncode, proc.stderr) == (0, "")
    if not proc.stdout:
        return None
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == event
    return out["additionalContext"]


def _ctx(proj: Path, task: str = TASK, **fields) -> Path:
    path = proj / "docs" / "dev" / f"context-{task}.json"
    path.write_text(json.dumps(fields))
    return path


def _report(proj: Path, task: str = TASK, **dev) -> None:
    (proj / "docs" / "dev" / f"dev-report-{task}.json").write_text(json.dumps({"dev": dev}))


RETRY = {"diagnosis_layer": "L3", "prior_attempts": [{"target_layer": "L3"}, {"target_layer": "L3"}]}


def test_layer_escalation_is_told_before_the_dev_runs(proj):
    _ctx(proj, **RETRY)
    text = _run(proj, "PreToolUse")
    assert text.startswith("SAME-LAYER RETRY DETECTED\n2 prior attempts all at layer L3 failed.")
    _ctx(proj, diagnosis_layer="L2", prior_attempts=RETRY["prior_attempts"])
    assert _run(proj, "PreToolUse") is None


def test_the_task_is_the_dispatchs_own_not_the_newest_context(proj):
    _ctx(proj, diagnosis_layer="L2")
    time.sleep(0.05)
    _ctx(proj, "20261109-202020", **RETRY)  # newer, another task's
    assert _run(proj, "PreToolUse") is None
    assert _run(proj, "PreToolUse", prompt=_prompt("20261109-202020")).startswith("SAME-LAYER RETRY")


def test_bisect_is_asked_for_a_regression_without_one(proj):
    _ctx(proj, user_verbatim_complaint="search used to work and broke yesterday")
    assert _run(proj, "PreToolUse").startswith("REGRESSION BUG WITHOUT BISECT")
    _ctx(proj, user_verbatim_complaint="it broke", root_cause_analysis={"git_bisect_result": {"suspect_commit": "abc"}})
    assert _run(proj, "PreToolUse") is None
    _ctx(proj, requirement={"original": "add a field"}, regression_investigation_checklist={"triggered": True})
    assert _run(proj, "PreToolUse").startswith("REGRESSION BUG WITHOUT BISECT")


def test_layer_match_is_told_when_the_dev_returns(proj):
    _ctx(proj, diagnosis_layer="L3")
    _report(proj, fix_layer="L5")
    assert _run(proj, "PostToolUse").startswith("LAYER MISMATCH\nBA diagnosed at L3, Dev fixed at L5.")
    _report(proj, fix_layer="L3")
    assert _run(proj, "PostToolUse") is None
    assert _run(proj, "PreToolUse") is None  # a report is judged after the dev, not before


def test_guard_removal_is_found_in_the_uncommitted_diff(proj):
    _ctx(proj, pre_existing_guards=[{"file": "src/app.py", "code_snippet": "raise ValueError('x')",
                                     "purpose": "reject None", "removal_authorized": False}])
    _report(proj, files_modified=["src/app.py"])
    assert _run(proj, "PostToolUse") is None
    (proj / "src" / "app.py").write_text("def check(x):\n    return x\n")
    assert "UNAUTHORIZED GUARD REMOVAL\nFile: src/app.py\nGuard: raise ValueError('x')" in _run(proj, "PostToolUse")


def test_minimum_diff_counts_the_reports_files_and_never_head_5(proj):
    _ctx(proj, diagnosis_layer="L3")
    (proj / "notes.txt").write_text("".join(f"line {i}\n" for i in range(100)))
    _git(proj, "add", "notes.txt")
    _git(proj, "commit", "-q", "-m", "the user's own commit, 100 lines")
    _report(proj, files_modified=["src/app.py"])
    assert _run(proj, "PostToolUse") is None  # HEAD~5..HEAD would have counted 100
    (proj / "src" / "app.py").write_text("".join(f"x{i} = {i}\n" for i in range(40)))
    assert _run(proj, "PostToolUse").startswith("MINIMUM-DIFF RULE WARNING\nThe dev's uncommitted diff adds 40 lines")
    _report(proj, files_modified=["src/app.py"], diff_stats={"justification_for_overage": "table data"})
    assert _run(proj, "PostToolUse") is None
    (proj / "other.py").write_text("".join(f"y{i} = {i}\n" for i in range(50)))
    _git(proj, "add", "other.py")  # another lane's file: not this report's
    _report(proj, files_modified=["src/app.py"], scope_review_requested=True)
    assert _run(proj, "PostToolUse") is None


def test_only_a_dev_dispatch_with_its_own_declaration_gets_advice(proj):
    _ctx(proj, **RETRY)
    assert _run(proj, "PreToolUse", subagent_type="qa") is None
    assert _run(proj, "PreToolUse", prompt="no obligation here") is None
    assert _run(proj, "PreToolUse", prompt=_prompt(role="qa")) is None
    assert _run(proj, "PreToolUse", raw="{not json") is None
    assert _run(proj, "PreToolUse", raw=json.dumps({"tool_name": "Bash"})) is None


def test_a_fan_out_lane_reads_its_lane_context(proj):
    lane = f"{TASK}-lane2"
    _ctx(proj, lane, **RETRY)
    _ctx(proj, diagnosis_layer="L1")
    assert _run(proj, "PreToolUse", prompt=_prompt(lane)).startswith("SAME-LAYER RETRY")
    assert _run(proj, "PreToolUse") is None


@pytest.mark.parametrize("hook, event, setup", [
    ("pretool-layer-escalation-check.sh", "PreToolUse", lambda p: _ctx(p, **RETRY)),
    ("pretool-bisect-gate.sh", "PreToolUse", lambda p: _ctx(p, user_verbatim_complaint="it used to work")),
    ("pretool-layer-match-gate.sh", "PostToolUse",
     lambda p: (_ctx(p, diagnosis_layer="L3"), _report(p, fix_layer="L4"))),
])
def test_the_message_is_the_old_hooks_where_it_found_the_same_task(proj, hook, event, setup):
    setup(proj)
    old = subprocess.run(["bash", str(ROOT / "hooks" / hook)], input="{}", capture_output=True, text=True,
                         env={**os.environ, "CLAUDE_PROJECT_DIR": str(proj)}, timeout=60)
    assert old.returncode == 0 and old.stderr
    assert _run(proj, event) == old.stderr.rstrip("\n")
