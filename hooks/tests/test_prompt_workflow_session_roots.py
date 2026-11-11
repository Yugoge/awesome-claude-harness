"""P2-4: the main agent's context holds the roots again after a compaction.

dev.md's and dev-command.md's start-function fallback runs when the command start's output is gone:
a compaction removed it, or the hook printed none. Its line kept the
`"${CLAUDE_HOME:-$HOME/.claude}/..."` channel, and Claude Code 2.1.319 asks for every line that holds a
`${...}` expansion. prompt-workflow.py answers a SessionStart payload, for every source, with root_lines
(PROJECT_ROOT=<abs>, HARNESS_ROOT=<abs>: the hook's own install) as additionalContext, and the CLI runs
SessionStart again at a compaction and puts that context after the summary; the fallback then writes
`<HARNESS_ROOT>` as the literal path `Bash(python3:*)` matches. The answer writes no state.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "prompt-workflow.py"
HARNESS = HOOK.parent.parent


def _session_start(tmp_path: Path, cwd: Path, source: str, session_id: str = "main-s1"):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_"))}
    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    env.update(HOME=str(tmp_path / "home"), CLAUDE_STATE_DIR=str(state_dir), TMPDIR=str(tmp_path),
               GIT_CEILING_DIRECTORIES=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    transcript = tmp_path / "transcript.jsonl"
    transcript.touch()
    payload = {"session_id": session_id, "transcript_path": str(transcript), "cwd": str(cwd),
               "hook_event_name": "SessionStart", "source": source}
    proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, cwd=cwd, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    return out["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("source", ["startup", "resume", "clear", "compact"])
def test_session_start_context_carries_both_roots_and_writes_nothing(tmp_path, source):
    product = tmp_path / "product"
    product.mkdir()
    assert _session_start(tmp_path, product, source) == f"PROJECT_ROOT={product}\nHARNESS_ROOT={HARNESS}"
    assert not (product / ".claude").exists()
    assert not any((tmp_path / "state").iterdir())


def test_session_project_root_is_the_overnight_records_worktree_path(tmp_path):
    product = tmp_path / "product"
    worktree = product / ".claude" / "worktrees" / "w1"
    worktree.mkdir(parents=True)
    (product / ".claude" / "overnight-state-night1.json").write_text(
        json.dumps({"session_id": "night1", "worktree_path": str(worktree)}))
    assert _session_start(tmp_path, product, "compact", "night1") == f"PROJECT_ROOT={worktree}\nHARNESS_ROOT={HARNESS}"
