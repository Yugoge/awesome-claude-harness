"""A dispatch is refused when its subagent could not write a file its obligation declares.

hooks/pretool-tool-policy.py's _check_dispatch_writes: for each file artifact (a kind whose fields
require a path) the Agent call's obligation declares, the hook's own decision (_decide) is asked
about the dispatched subagent's Write of it, with the dispatch recorded as the CLI records one.
A refusal refuses the dispatch, naming the artifact, the role and the rule, so no subagent is
started into a stop gate (G2) that demands a file it may not write.

The projects are never created: only paths are judged. The RAM-disk project lies under /dev/shm,
where a declared path never reaches the derived write permission (its targets drop /dev/ paths)
and the role rows refuse it; the other project lies outside /dev, /tmp and /var/tmp, as one under a
home path does, and the same dispatch goes on.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "hooks" / "pretool-tool-policy.py"
GATE = ROOT / "hooks" / "pretool-write-gate.py"
RAM_DISK = "/dev/shm/nonexistent-dispatch-writes/toyproj"
ELSEWHERE = "/nonexistent-dispatch-writes/toyproj"  # outside /dev, /tmp and /var/tmp, as a home path is
TASK = "20261119-101010"
REPORT = f"docs/dev/qa-report-{TASK}.json"
BLOCK = "BLOCKED by tool-policy.v1: "


def _prompt(role: str, *artifacts: dict) -> str:
    doc = {"task_id": TASK, "lane": None, "lane_set": None, "role": role, "pipeline": "dev",
           "profile": "singular", "artifacts": list(artifacts),
           "dispatched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return f"You are the {role} subagent.\n<obligation v=\"1\">\n{json.dumps(doc)}\n</obligation>\n"


QA_REPORT = {"kind": "json", "path": REPORT, "schema": "qa-report.v2", "identity": {"task_id": TASK}}
RESPONSE_LINE = {"kind": "response_line", "terminal_line_regex": "^QA: (PASS|FAIL)$"}


def _dispatch(tmp_path: Path, project: str, prompt: str, role: str = "qa", hook: Path = POLICY):
    """The main agent's Agent call through ``hook``, on an empty session transcript."""
    transcript = tmp_path / "projects" / "sess.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.touch()
    payload = {"session_id": "sess", "transcript_path": str(transcript), "cwd": project,
               "hook_event_name": "PreToolUse", "permission_mode": "default", "tool_name": "Agent",
               "tool_use_id": "toolu_" + uuid.uuid4().hex[:20],
               "tool_input": {"description": "d", "subagent_type": role, "prompt": prompt}}
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tmp").mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update({"HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"), "TMPDIR": str(tmp_path / "tmp"),
                "CLAUDE_STATE_DIR": str(tmp_path / "state"), "CLAUDE_PROJECT_DIR": project,
                "PYTHONDONTWRITEBYTECODE": "1"})
    proc = subprocess.run([sys.executable, str(hook)], input=json.dumps(payload), capture_output=True, text=True,
                          cwd=str(tmp_path), env=env, timeout=60)
    assert not Path(project).parent.exists(), "the dispatch check must not create the project"
    assert not list((tmp_path / "tmp").iterdir()), "the dispatch check must leave no store behind"
    return proc


def test_a_dispatch_whose_declared_report_its_role_may_not_write_is_refused(tmp_path):
    proc = _dispatch(tmp_path, RAM_DISK, _prompt("qa", QA_REPORT))
    assert proc.returncode == 2, proc.stderr
    first = proc.stderr.splitlines()[0]
    assert first.startswith(BLOCK), proc.stderr
    denial = json.loads(first[len(BLOCK):])
    assert denial["role"] == "main" and denial["tool"] == "Agent" and denial["target"] == REPORT
    reason = denial["deny_reason"]
    assert f"declares {REPORT} for its qa subagent" in reason  # the artifact and the role
    assert "tool-policy.v1 (hooks/pretool-tool-policy.py)" in reason  # the rule
    assert f"write target {RAM_DISK}/{REPORT} not in allowed_write_path_prefixes" in reason  # its own reason


def test_the_main_agent_meets_the_refusal_through_the_write_gate(tmp_path):
    proc = _dispatch(tmp_path, RAM_DISK, _prompt("qa", QA_REPORT), hook=GATE)
    assert proc.returncode == 2, proc.stderr
    assert f"declares {REPORT} for its qa subagent" in proc.stderr


def test_the_same_dispatch_outside_dev_goes_on(tmp_path):
    proc = _dispatch(tmp_path, ELSEWHERE, _prompt("qa", QA_REPORT))
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""


@pytest.mark.parametrize("prompt", [
    pytest.param("You are the qa subagent. Review the toy package; write nothing.", id="no-obligation"),
    pytest.param(_prompt("qa", RESPONSE_LINE), id="response-line-only"),
])
def test_a_dispatch_that_declares_no_file_is_unaffected(tmp_path, prompt):
    proc = _dispatch(tmp_path, RAM_DISK, prompt)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""


def test_every_declared_file_is_asked_and_the_first_refused_one_named(tmp_path):
    """BA's context and ticket: the rows let BA write neither under /dev/shm; the first is named."""
    context = {"kind": "json", "path": f"docs/dev/context-{TASK}.json", "schema": "context.v1",
               "identity": {"task_id": TASK}}
    ticket = {"kind": "markdown", "path": f"docs/dev/ticket-{TASK}.md", "identity_anchor": TASK}
    proc = _dispatch(tmp_path, RAM_DISK, _prompt("ba", ticket, context), role="ba")
    assert proc.returncode == 2, proc.stderr
    assert f"declares docs/dev/ticket-{TASK}.md for its ba subagent" in proc.stderr
    assert _dispatch(tmp_path, ELSEWHERE, _prompt("ba", ticket, context), role="ba").returncode == 0
