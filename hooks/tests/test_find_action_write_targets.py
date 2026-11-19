"""find's file-writing actions are write targets (hardcode audit 2026-11-19, finding 6).

The shared parser's table of find actions held the four that run a program; `-fprint`, `-fprint0`,
`-fprintf` and `-fls` write the file the next word names, and `shell_parse.write_targets` named
none of them: the role rows of tool-policy let a role write where it may not, and the attribution
journal did not record the write. One table (shell_parse.FIND_ACTIONS) now holds the nine.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hooks"))
from lib import attribution_journal, shell_parse as sp  # noqa: E402
from lib.bash_write_targets import extract_bash_touched_paths, extract_bash_write_paths  # noqa: E402

POLICY = ROOT / "hooks" / "pretool-tool-policy.py"
WRITES = [  # (command, the file it writes, the mechanism)
    ("find . -maxdepth 0 -fprintf src/planted.py 'import os\\n'", "src/planted.py", "find-fprintf"),
    ("find . -maxdepth 0 -fprint src/planted.py", "src/planted.py", "find-fprint"),
    ("find . -maxdepth 0 -fprint0 src/planted.py", "src/planted.py", "find-fprint0"),
    ("find . -maxdepth 0 -fls src/planted.py", "src/planted.py", "find-fls"),
    ("find docs -name '*.md' -fprint src/planted.py -o -name '*.py' -print", "src/planted.py", "find-fprint"),
    ("cd x && sudo find . -newer stamp -fprintf \"src/planted.py\" '%p\\n'", "src/planted.py", "find-fprintf"),
]
READS = [  # an ordinary find, and words that only look like an action
    "find . -name '*.py'",
    "find src -type f -newer stamp -print",
    "find . -maxdepth 2 -name 'fprint*' -print0",
    "find hooks -type f -executable",
    "find . -name '*.py' -exec grep -l -fprint {} +",   # -fprint here is grep's word, inside the -exec
]


@pytest.mark.parametrize("command, path, mechanism", WRITES)
def test_a_file_writing_action_is_a_write_target(command, path, mechanism):
    found = [(t.path, t.mode, t.mechanism) for t in sp.write_targets(sp.parse(command))]
    assert found == [(path, sp.TRUNCATE, mechanism)]
    assert extract_bash_write_paths(command) == [path]
    assert extract_bash_touched_paths(command) == [(path, False)]


@pytest.mark.parametrize("command", READS)
def test_an_ordinary_find_writes_nothing(command):
    assert sp.write_targets(sp.parse(command)) == []
    assert extract_bash_write_paths(command) == []


def test_two_actions_and_a_computed_file():
    targets = sp.write_targets(sp.parse('find . -fprint a.txt -fls "$OUT"'))
    assert [(t.path, t.decidable) for t in targets] == [("a.txt", True), (None, False)]
    assert extract_bash_write_paths('find . -fprint a.txt -fls "$OUT"') == ["a.txt", "$OUT"]


def test_the_exec_actions_are_read_as_before():
    """-exec, -execdir, -ok, -okdir: the command they run is walked, as on the base."""
    for action in sp._FIND_EXEC:
        targets = sp.write_targets(sp.parse("find src/planted.py %s rm {} +" % action))
        assert [(t.path, t.mode) for t in targets] == [("{}", sp.DELETE)]


def test_one_table_holds_every_action_that_runs_writes_or_deletes():
    assert set(sp.FIND_ACTIONS) == {"-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf",
                                    "-fls", "-delete"}


def test_the_attribution_journal_sees_the_write(tmp_path):
    for command, path, _ in WRITES[:4]:
        assert attribution_journal.extract_targets("Bash", {"command": command}, str(tmp_path)) == \
            [str(tmp_path / path)], command
    assert attribution_journal.extract_targets("Bash", {"command": READS[0]}, str(tmp_path)) == []


def _policy(tmp_path, command, role="qa"):
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True, exist_ok=True)
    payload = {"session_id": "s", "cwd": str(proj), "hook_event_name": "PreToolUse", "agent_id": "a1",
               "agent_type": role, "subagent_type": role, "tool_name": "Bash", "tool_input": {"command": command}}
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj))
    return subprocess.run([sys.executable, str(POLICY)], input=json.dumps(payload), capture_output=True, text=True,
                          cwd=str(proj), env=env, timeout=120)


@pytest.mark.parametrize("command, path, _mechanism", WRITES[:4])
def test_a_role_that_may_not_write_there_is_refused_through_find(tmp_path, command, path, _mechanism):
    """qa's rows deny /src/: the redirect was refused, the same write through find passed."""
    control = _policy(tmp_path, "printf x > src/planted.py")
    assert control.returncode == 2 and "denied_write_path_prefixes" in control.stderr, control.stderr
    proc = _policy(tmp_path, command)
    assert proc.returncode == 2 and '"target":"%s"' % path in proc.stderr, proc.stderr
    assert "denied_write_path_prefixes" in proc.stderr, proc.stderr


@pytest.mark.parametrize("command", READS)
def test_the_same_role_still_runs_an_ordinary_find(tmp_path, command):
    proc = _policy(tmp_path, command)
    assert proc.returncode == 0 and "BLOCKED" not in proc.stderr, proc.stderr
