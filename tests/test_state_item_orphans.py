"""Orphans of the location audit (f199dfb1e), each settled, and two names that did not match.

S21  push.sh's grant manifest was written and never read: the writer is gone, and the sweep no longer names it.
E01  the daily sweep named files no program writes: those names are gone.
S31  the blessed-token minter had no caller: the minter and the keystone's exemption that read its grant are gone.
S23  the run-code watchdog pid file was named from CLAUDE_SESSION_ID, which the CLI never exports, so every
     session shared one name: both hooks now take the payload's session id.
C01  session-promote built the transcript folder name by replacing "/" only; Claude Code replaces every
     character other than an ASCII letter or digit.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SWEEP = (REPO / "scripts" / "install" / "tmp-cleanup-install.sh").read_text()


def test_s21_the_push_grant_manifest_has_no_writer_and_no_sweep_entry():
    assert "claude-push-grant-" not in (REPO / "hooks" / "push.sh").read_text()
    assert "claude-push-grant-" not in SWEEP


def test_e01_the_sweep_names_no_file_nothing_writes():
    for name in ("contract-bookmark-", "artifact-status-", "claude-commit-plan-"):
        assert name not in SWEEP, name


def test_s31_no_blessed_token_minter_and_no_exemption_reading_its_grant():
    assert not (REPO / "scripts" / "mint-git-blessed-token.sh").exists()
    assert "CLAUDE_GIT_BLESSED_TOKEN" not in (REPO / "hooks" / "git-keystone" / "reference-transaction").read_text()
    assert "mint-git-blessed-token" not in (REPO / "settings.json").read_text()


def test_s23_the_watchdog_pid_file_is_the_payload_sessions(tmp_path):
    """The PostToolUse hook cancels the watchdog the PreToolUse hook started for THIS session."""
    state = tmp_path / "state"
    state.mkdir()
    sleeper = subprocess.Popen(["sleep", "60"])
    try:
        pid_file = state / ".runcode-watchdog-sess-a.pid"
        pid_file.write_text(str(sleeper.pid))
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path), "CLAUDE_STATE_DIR": str(state),
               "PYTHONDONTWRITEBYTECODE": "1"}
        payload = {"session_id": "sess-a", "tool_name": "mcp__playwright__browser_run_code", "tool_input": {}}
        subprocess.run([sys.executable, str(REPO / "hooks" / "posttool-runcode-watchdog.py")], input=json.dumps(payload),
                       env=env, capture_output=True, text=True, timeout=60)
        assert not pid_file.exists()
    finally:
        sleeper.kill()
        sleeper.wait()


def test_c01_the_promote_hook_uses_the_cli_folder_name():
    text = (REPO / "hooks" / "session-promote-hook.sh").read_text()
    line = re.search(r"^PROJECT_NAME=.*$", text, re.M).group(0)
    got = subprocess.run(["bash", "-c", 'CWD=/srv/a.b_c; ' + line + '; printf %s "$PROJECT_NAME"'],
                         capture_output=True, text=True, timeout=30).stdout
    assert got == re.sub(r"[^A-Za-z0-9]", "-", "/srv/a.b_c")
