"""P10 R6 (P10-9): what P5 left without a caller is gone, and the hooks that kept it still run.

- posttool-subagent-track.py's bookmark marker. P5 moved Gate 4 to the transcript, so
  only the Codex plan path writes a bookmark's `last_todos`, and the marker was written
  only under one. That path reads its subagent steps from Codex's own records
  (`native_subagent_evidence_for_transition`, which sets `subagent_calls` itself), and
  this hook's PostToolUse matcher is `Agent`, a tool name Codex does not have. The hook
  now writes only the /dev-overnight cycle contract: a bookmark with `last_todos` is
  left byte for byte.
- lib.overnight.session_state. P5's PM TRIAGE handler reads the record through
  contract_runtime.session_record, its last caller; the locator is session_state_file.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1]
TRACK = HOOKS / "posttool-subagent-track.py"


def _codex_bookmark(project: Path, sid: str) -> Path:
    """A /dev bookmark as the Codex plan path leaves it: its last_todos are dev's
    canonical steps, the BA dispatch step in progress."""
    canonical = json.loads(subprocess.run(
        [sys.executable, str(HOOKS.parent / "scripts" / "todo" / "dev.py")],
        capture_output=True, text=True, check=True, timeout=60).stdout)
    ba = next(i for i, step in enumerate(canonical)
              if (step.get("subagent_call") or {}).get("subagent_type") == "ba")
    todos = [{"content": step["content"], "activeForm": step.get("activeForm", ""),
              "status": "completed" if i < ba else "in_progress" if i == ba else "pending"}
             for i, step in enumerate(canonical)]
    path = project / ".claude" / f"workflow-{sid}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"command": "dev", "arguments": "", "last_todos": todos}))
    return path


def test_agent_return_leaves_a_codex_plan_bookmark_unchanged(tmp_path):
    sid = "sid-now-unreferenced"
    project = tmp_path / "project"
    bookmark = _codex_bookmark(project, sid)
    before = bookmark.read_bytes()
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
    env.update(HOME=str(tmp_path / "home"), CLAUDE_PROJECT_DIR=str(project),
               CLAUDE_STATE_DIR=str(tmp_path / "state"))
    payload = {"session_id": sid, "cwd": str(project), "hook_event_name": "PostToolUse",
               "tool_name": "Agent",
               "tool_input": {"subagent_type": "ba", "prompt": "plan it", "description": "plan"},
               "tool_response": {"content": "done"}}
    done = subprocess.run([sys.executable, str(TRACK)], input=json.dumps(payload), env=env,
                          cwd=project, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert bookmark.read_bytes() == before
    assert "SUBAGENT TRACKED" not in done.stdout


def test_the_names_p5_left_without_a_caller_are_gone():
    sys.path.insert(0, str(HOOKS))
    from lib import overnight
    assert not hasattr(overnight, "session_state")
    assert callable(overnight.session_state_file)
    source = TRACK.read_text(encoding="utf-8")
    for name in ("_record_subagent_call_legacy", "last_todos", "subagent_calls", "write_bookmark"):
        assert name not in source, name
