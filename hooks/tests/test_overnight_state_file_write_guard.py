#!/usr/bin/env python3
"""Regression coverage for hooks/pretool-overnight-hook-guard.py's
overnight-state write-protection (ticket 20261001-161041-r10, AC4/AC5/AC6).

Prior to this file, zero tests anywhere in the repo exercised
is_state_file_path / OVERNIGHT STATE PROTECTION / check_bash_targets_state
(confirmed via grep in the BA investigation for this ticket). Locks in
three guarantees, each reproduced live via direct subprocess invocation
of the real hook script:

  - AC4: a direct Write/Edit to an overnight-state-*.json path is blocked
    (exit 2, 'OVERNIGHT STATE PROTECTION') while any overnight session is
    live anywhere under CLAUDE_PROJECT_DIR/.claude/ -- even from an
    unrelated session_id with no agent_id (main-agent actor); the block
    is global, not session-scoped.
  - AC5: the same block applies to a Bash redirect into the state-file
    path, while scripts/update-overnight-state.sh remains exempt.
  - AC6: the identical Write payload from AC4 is NOT blocked (exit 0) when
    no overnight session is live anywhere -- the protection is
    conditional on is_overnight_active(), not an unconditional global
    block (hooks/pretool-overnight-hook-guard.py main():2277-2278:
    `if is_overnight_active(): apply_global_security_checks(...)`). This
    is the honest scoping disclosure the lane's requirement asked for.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

HOOK_PATH = Path(__file__).resolve().parent.parent / "pretool-overnight-hook-guard.py"


def _write_live_state(project_dir: Path, session_id: str) -> Path:
    """A fresh, live overnight-state file: future end_time, no
    isolation_released_at, no worktree_path (so orphan-detection falls
    back to file age, which is ~0 for a just-written fixture -- see
    hooks/pretool-overnight-hook-guard.py:_is_orphaned_state)."""
    claude_dir = project_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    state_path = claude_dir / f"overnight-state-{session_id}.json"
    future = (datetime.now() + timedelta(hours=2)).isoformat()
    state_path.write_text(json.dumps({"session_id": session_id, "end_time": future}))
    return state_path


def _run_guard(project_dir: Path, payload: dict) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


def test_write_to_state_file_blocked_while_overnight_active(tmp_path: Path) -> None:
    """AC4 (Write branch)."""
    state_path = _write_live_state(tmp_path, "ac4-write")
    result = _run_guard(
        tmp_path,
        {
            "session_id": "unrelated-session",
            "tool_name": "Write",
            "tool_input": {"file_path": str(state_path)},
        },
    )
    assert result.returncode == 2
    assert "OVERNIGHT STATE PROTECTION" in result.stderr


def test_edit_to_state_file_blocked_while_overnight_active(tmp_path: Path) -> None:
    """AC4 (Edit branch)."""
    state_path = _write_live_state(tmp_path, "ac4-edit")
    result = _run_guard(
        tmp_path,
        {
            "session_id": "unrelated-session",
            "tool_name": "Edit",
            "tool_input": {"file_path": str(state_path)},
        },
    )
    assert result.returncode == 2
    assert "OVERNIGHT STATE PROTECTION" in result.stderr


def test_bash_redirect_into_state_file_blocked_but_update_script_exempt(
    tmp_path: Path,
) -> None:
    """AC5: a raw redirect into the state file is blocked; the sanctioned
    update-overnight-state.sh path remains exempt."""
    state_path = _write_live_state(tmp_path, "ac5-bash")

    redirect_result = _run_guard(
        tmp_path,
        {
            "session_id": "unrelated-session",
            "tool_name": "Bash",
            "tool_input": {"command": f"echo '{{}}' > {state_path}"},
        },
    )
    assert redirect_result.returncode == 2
    assert "OVERNIGHT STATE PROTECTION" in redirect_result.stderr

    sanctioned_result = _run_guard(
        tmp_path,
        {
            "session_id": "unrelated-session",
            "tool_name": "Bash",
            "tool_input": {
                "command": f"scripts/update-overnight-state.sh {state_path} cycle_count 7"
            },
        },
    )
    assert sanctioned_result.returncode == 0, sanctioned_result.stderr


def test_write_to_state_file_allowed_when_no_overnight_session_is_live(
    tmp_path: Path,
) -> None:
    """AC6: the SAME Write payload shape as AC4, replayed against a
    project dir with no overnight-state file anywhere, is NOT blocked --
    proving the AC4/AC5 protection is conditional, not unconditional."""
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    target = tmp_path / ".claude" / "overnight-state-ac6-no-session.json"
    result = _run_guard(
        tmp_path,
        {
            "session_id": "unrelated-session",
            "tool_name": "Write",
            "tool_input": {"file_path": str(target)},
        },
    )
    assert result.returncode == 0, result.stderr
