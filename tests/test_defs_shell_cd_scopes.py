"""Where a relative write lands after a cd: compound commands run in the shell's own directory.

A brace group, a loop, an if and a case body run in the current shell, in the directory in effect,
and so do a compound's own redirections (`{ ...; } > f`, `done > f`). A function defined and called
in the same command runs its body where it is called. The directory stays unknown (`$(pwd)/`) for a
function the command defines and never calls, and after a computed cd.

The last test is the shape of a recorded refusal: a ba subagent's `cd <its scratch> && ... &&
{ echo ...; } > sec13.md` was refused as a write to `$(pwd)/sec13.md`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / "hooks"
sys.path[:0] = [str(HOOKS), str(HOOKS / "lib")]

from lib import shell_parse as sp  # noqa: E402


def placed(command):
    return sorted(p for t in sp.write_targets(sp.parse(command), raw=command) for p in t.placed())


@pytest.mark.parametrize("command,expected", [
    ("cd /d && { echo a; } > f", ["/d/f"]),
    ("cd /d && { echo a > g; }", ["/d/g"]),
    ("cd /d && for i in 1; do :; done > h", ["/d/h"]),
    ("cd /d && for i in 1; do echo > h; done", ["/d/h"]),
    ("cd /d && while read x; do echo > y; done < in", ["/d/y"]),
    ("cd /d && if true; then echo > i; fi > i2", ["/d/i", "/d/i2"]),
    ("cd /d && case x in x) echo > p;; esac", ["/d/p"]),
    ("cd /d && f() { echo > k; } && f", ["/d/k"]),
    ("f() { echo > k; }; cd /d && f", ["/d/k"]),
    ("f() { cd /e; }; cd /d && f && echo > z", ["/e/z"]),
])
def test_a_compound_runs_in_the_directory_in_effect(command, expected):
    assert placed(command) == expected


@pytest.mark.parametrize("command", [
    "cd /d && f() { echo > k; }",          # defined, never called here: it runs wherever it is called later
    'cd "$D" && { echo a; } > f',          # a computed cd
])
def test_the_directory_stays_unknown_where_bash_cannot_say(command):
    assert all(p.startswith("$(pwd)/") for p in placed(command)) and placed(command)


ROW = ("cd /tmp/claude-scratch/ba/r00rev && jq -r '.decisions_new[] | .id' governance.json > sec1_rows.md "
       "&& wc -l sec1_rows.md &&\n{\necho '## Section 13. Rulings'\necho\necho 'Every request has one row.'\n} > sec13.md")


def _tool_policy(tmp_path, command):
    proj, home = tmp_path / "proj", tmp_path / "home"
    for d in (proj / ".claude", home / ".claude", tmp_path / "state", tmp_path / "tmp"):
        d.mkdir(parents=True, exist_ok=True)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(home / ".claude"), "CLAUDE_STATE_DIR": str(tmp_path / "state"),
           "TMPDIR": str(tmp_path / "tmp"), "CLAUDE_PROJECT_DIR": str(proj), "PYTHONDONTWRITEBYTECODE": "1"}
    payload = {"session_id": "sess-" + uuid.uuid4().hex[:8], "transcript_path": str(tmp_path / "none.jsonl"),
               "cwd": str(proj), "hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": command}, "tool_use_id": "toolu_" + uuid.uuid4().hex[:24],
               "agent_id": "a1", "agent_type": "ba", "subagent_type": "ba"}
    return subprocess.run([sys.executable, str(HOOKS / "pretool-tool-policy.py")], input=json.dumps(payload),
                          text=True, capture_output=True, cwd=str(proj), env=env, timeout=120)


def test_the_recorded_ba_command_is_placed_in_its_scratch_and_allowed(tmp_path):
    assert "/tmp/claude-scratch/ba/r00rev/sec13.md" in placed(ROW)
    assert _tool_policy(tmp_path, ROW).returncode == 0


def test_the_same_group_after_a_cd_out_of_the_prefix_is_refused(tmp_path):
    assert _tool_policy(tmp_path, ROW.replace("/tmp/claude-scratch/ba/r00rev", "/etc")).returncode == 2
