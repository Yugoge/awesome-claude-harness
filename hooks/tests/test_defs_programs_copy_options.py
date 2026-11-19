"""cp, mv, install, ln and rsync's value options are one table (hooks/lib/shell_parse.py VERBS), read as GNU reads them.

GNU getopt gives an optional-argument option (cp --preserve[=ATTR], --reflink[=WHEN], --context[=CTX],
--backup[=CONTROL]) its value only after `=`; -Z and install's -D take none. The parser's cp table and the
runtime guard's own table (_VALUE_OPTS) took the next word as their value, so in `cp SRC --preserve DEST` the
destination was read as the option's value and SRC as the destination, and in `mv --backup SRC DEST` the moved
SRC (removed from where it was) was not seen. Checked against GNU coreutils 9.4 and rsync 3.2.7 `--help`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS / "lib"))
import shell_parse  # noqa: E402
from runtime_guard import _core  # noqa: E402
sys.path.pop(0)


@pytest.mark.parametrize("command,dest,source", [
    ("cp SRC --preserve DEST", "DEST", "SRC"), ("cp SRC --reflink DEST", "DEST", "SRC"),
    ("cp SRC --context DEST", "DEST", "SRC"), ("cp SRC -Z DEST", "DEST", "SRC"),
    ("install SRC -D DEST", "DEST", "SRC"), ("cp --preserve=all SRC DEST", "DEST", "SRC"),
    ("cp -S .bak SRC DEST", "DEST", "SRC"), ("rsync --info progress2 SRC DEST", "DEST", "SRC"),
])
def test_both_readers_find_the_destination(command, dest, source):
    words = command.split()
    written = [t for t in shell_parse.write_targets(command) if t.mode != shell_parse.DELETE]
    assert [(t.path, t.source) for t in written] == [(dest, source)]
    assert _core._operands_and_tdir(words[0], words[1:]) == ([source, dest], None)


def test_a_backup_move_still_removes_its_source():
    assert [(t.path, t.mode) for t in shell_parse.write_targets("mv --backup SRC DEST")] == [
        ("DEST", shell_parse.MOVE_DEST), ("SRC", shell_parse.DELETE)]


def _hook(name: str, command: str, project: Path) -> int:
    home = project.parent / "home"
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
               "cwd": str(project), "session_id": "copyopts", "transcript_path": str(project / "t.jsonl"),
               "permission_mode": "default", "tool_use_id": "toolu_copyopts"}
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "CODEX"))}
    env.update(HOME=str(home), CLAUDE_PROJECT_DIR=str(project), CLAUDE_CONFIG_DIR=str(home / ".claude"),
               CLAUDE_STATE_DIR=str(home / "state"))
    return subprocess.run([sys.executable, str(HOOKS / name)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=str(project), env=env, timeout=60).returncode


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("copyopts")
    p = root / "proj"
    for d in (".claude/hooks", ".claude/specs/s1"):
        (p / d).mkdir(parents=True)
    (p / "src.txt").write_text("x\n")
    (root / "home" / ".claude").mkdir(parents=True)
    (root / "home" / "state").mkdir()
    return p


@pytest.mark.parametrize("hook,target", [("pretool-claude-config-guard.py", ".claude/hooks/x.py"),
                                         ("pretool-bash-views-guard.py", ".claude/specs/s1/cp-state-dev.json")])
@pytest.mark.parametrize("option", ["--preserve", "--reflink"])
def test_a_copy_onto_a_protected_file_is_refused_whatever_the_option_order(project, hook, target, option):
    assert _hook(hook, f"cp src.txt {option} {target}", project) == 2
