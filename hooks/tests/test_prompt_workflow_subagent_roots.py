"""P2-3: a subagent starts with the roots a harness command's text names.

No UserPromptSubmit output reaches a subagent, so an agent text's harness line kept the
`"${CLAUDE_HOME:-$HOME/.claude}/..."` channel, and Claude Code 2.1.319 asks for every line that
holds a `${...}` expansion. prompt-workflow.py answers a SubagentStart payload with root_lines
(PROJECT_ROOT=<abs>, HARNESS_ROOT=<abs>: the hook's own install) as the subagent's
additionalContext, which the CLI hands the subagent before its first turn; the agent then writes
`<HARNESS_ROOT>` as the literal path the Bash allow entries match. With the session's overnight
record, PROJECT_ROOT is its worktree_path, as at /dev-overnight. The answer writes no state.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "prompt-workflow.py"
HARNESS = HOOK.parent.parent


def _start(tmp_path: Path, cwd: Path, session_id: str = "sub-s1", event: str = "SubagentStart"):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_"))}
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    env.update(HOME=str(tmp_path / "home"), CLAUDE_STATE_DIR=str(state_dir), TMPDIR=str(tmp_path),
               GIT_CEILING_DIRECTORIES=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    transcript = tmp_path / "transcript.jsonl"
    transcript.touch()
    payload = {"session_id": session_id, "transcript_path": str(transcript), "cwd": str(cwd),
               "hook_event_name": event, "agent_id": "a1", "agent_type": "dev"}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, cwd=cwd, timeout=60)


def _context(proc) -> str:
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "SubagentStart"
    return out["hookSpecificOutput"]["additionalContext"]


def test_subagent_start_context_carries_both_roots_and_writes_nothing(tmp_path):
    product = tmp_path / "product"
    product.mkdir()
    proc = _start(tmp_path, product)
    assert _context(proc) == f"PROJECT_ROOT={product}\nHARNESS_ROOT={HARNESS}"
    assert not (product / ".claude").exists()
    assert not any((tmp_path / "state").iterdir())


def test_subagent_project_root_is_the_overnight_records_worktree_path(tmp_path):
    product = tmp_path / "product"
    worktree = product / ".claude" / "worktrees" / "w1"
    worktree.mkdir(parents=True)
    state = product / ".claude" / "overnight-state-night1.json"
    state.write_text(json.dumps({"session_id": "night1", "worktree_path": str(worktree)}))
    assert _context(_start(tmp_path, product, "night1")) == f"PROJECT_ROOT={worktree}\nHARNESS_ROOT={HARNESS}"
    # another session's record is never used
    assert _context(_start(tmp_path, product, "other")) == f"PROJECT_ROOT={product}\nHARNESS_ROOT={HARNESS}"


def test_a_plain_prompt_gets_no_subagent_answer(tmp_path):
    product = tmp_path / "product"
    product.mkdir()
    proc = _start(tmp_path, product, event="UserPromptSubmit")
    assert proc.returncode == 0, proc.stderr
    assert "SubagentStart" not in proc.stdout and "HARNESS_ROOT=" not in proc.stdout
