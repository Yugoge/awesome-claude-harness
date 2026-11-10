"""hooks/pretool-claude-config-guard.py: a Bash write into the harness home is refused in every spelling of the home.

The guard reads the raw command text for a write into `.claude/hooks/` or `.claude/commands/`. A home
named through a variable names no `.claude/<dir>/` there: on the base d64fa96b,
`echo x > "${CLAUDE_HOME:-$HOME/.claude}/commands/x.md"` (the spelling the prompts use) exited 0 while
`echo x > ~/.claude/commands/x.md` exited 2, and so did `$CLAUDE_HOME`, `${CLAUDE_HOME}`, the
CLAUDE_CONFIG_DIR forms and `"$HOME/.claude"/<dir>/` (a quote between the home and its folder).
Each of those now reaches the decision of the literal home path, for every write form the guard
reads (redirects, cat into a file, cp, mv, tee), for the main agent and a subagent. A home variable
may hold a protected root in the shell that runs the command whatever the hook's own environment
holds, so a spelling of one whose value is unknown fails closed, as a written-out `.claude/hooks/`
after an unknown prefix is refused on the base. What the base let through and names no protected
folder still goes through.

Each case runs the real hook as a subprocess, with a scratch HOME and CLAUDE_HOME.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-claude-config-guard.py"
BLOCK = "BLOCKED: claude config guard: agent Bash write to .claude/{}/"

# The spellings of the harness home that the base let through, then those it already refused
# (kept here so every spelling is pinned; they pass on the base too).
NEW_SPELLINGS = {
    "CLAUDE_HOME with default": '"${CLAUDE_HOME:-$HOME/.claude}/{rest}"',
    "CLAUDE_HOME with braced default": '"${CLAUDE_HOME:-${HOME}/.claude}/{rest}"',
    "${CLAUDE_HOME}": '"${CLAUDE_HOME}/{rest}"',
    "$CLAUDE_HOME": '"$CLAUDE_HOME/{rest}"',
    "$CLAUDE_HOME unquoted": "$CLAUDE_HOME/{rest}",
    "CLAUDE_CONFIG_DIR with default": '"${CLAUDE_CONFIG_DIR:-$HOME/.claude}/{rest}"',
    "${CLAUDE_CONFIG_DIR}": '"${CLAUDE_CONFIG_DIR}/{rest}"',
    "$CLAUDE_CONFIG_DIR": '"$CLAUDE_CONFIG_DIR/{rest}"',
    "quoted $HOME/.claude then folder": '"$HOME/.claude"/{rest}',
    "quoted literal home then folder": '"{home}/.claude"/{rest}',
}
BASE_SPELLINGS = {
    "~/.claude": "~/.claude/{rest}",
    "$HOME/.claude": '"$HOME/.claude/{rest}"',
    "${HOME}/.claude": '"${HOME}/.claude/{rest}"',
    "literal home": "{home}/.claude/{rest}",
}
# Every write form the guard reads; {t} is the target.
FORMS = {
    "echo >": "echo x > {t}",
    "printf >>": "printf x >> {t}",
    "cat >": "cat notes.txt > {t}",
    "cp": "cp notes.txt {t}",
    "mv": "mv notes.txt {t}",
    "tee": "echo x | tee {t}",
    "tee -a <": "tee -a {t} < notes.txt",
}
FOLDERS = {"commands": "commands/x.md", "hooks": "hooks/x.py"}
ACTORS = {"main": None, "subagent": ("a0123456789abcdef", "dev")}


@pytest.fixture(scope="module")
def scratch(tmp_path_factory):
    root = tmp_path_factory.mktemp("config-guard-home")
    home, project = root / "home", root / "proj"
    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".claude" / "hooks").mkdir()
    (project / ".claude").mkdir(parents=True)
    return home, project


def _run(scratch, command: str, actor=None, extra_env=None):
    home, project = scratch
    payload = {"session_id": "sess-home-spellings", "transcript_path": str(project / "t.jsonl"),
               "cwd": str(project), "hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": command}}
    if actor:
        payload.update(agent_id=actor[0], agent_type=actor[1])
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=str(home), CLAUDE_HOME=str(home / ".claude"), CLAUDE_PROJECT_DIR=str(project),
               PYTHONDONTWRITEBYTECODE="1")
    env.update(extra_env or {})
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=str(project), env=env, timeout=30)


def _command(scratch, spelling: str, form: str, folder: str) -> str:
    target = spelling.replace("{home}", str(scratch[0])).replace("{rest}", FOLDERS[folder])
    return FORMS[form].format(t=target)


def _refused(proc, folder: str) -> None:
    assert proc.returncode == 2, (proc.returncode, proc.stderr)
    assert BLOCK.format(folder) in proc.stderr, proc.stderr


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("folder", FOLDERS)
@pytest.mark.parametrize("form", FORMS)
@pytest.mark.parametrize("spelling", list(NEW_SPELLINGS) + list(BASE_SPELLINGS))
def test_a_write_into_the_home_is_refused_in_every_spelling(scratch, spelling, form, folder, actor):
    text = NEW_SPELLINGS.get(spelling) or BASE_SPELLINGS[spelling]
    _refused(_run(scratch, _command(scratch, text, form, folder), ACTORS[actor]), folder)


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("command", [
    # a home variable whose value is not the home here: the shell's may be (fails closed)
    'echo x > "${CLAUDE_HOME:-/elsewhere}/commands/x.md"',
    'cp notes.txt "${CLAUDE_CONFIG_DIR-/elsewhere}/hooks/x.py"',
    'echo x | tee "${CLAUDE_HOME%/}/hooks/x.py"',
    # another variable defaulting to the home
    'echo x > "${TARGET:-$HOME/.claude}/hooks/x.py"',
    'mv notes.txt "${TARGET:-${CLAUDE_HOME}}/commands/x.md"',
    'cp notes.txt "${TARGET:-$HOME/.claude/commands}/x.md"',
    'echo x | tee "${1:-$HOME/.claude}/hooks/x.py"',
    # nested deeper than Python's recursion limit: still read, not an exception (which fails open)
    pytest.param('echo x > ' + '${A:-' * 3000 + '$CLAUDE_HOME' + '}' * 3000 + '/commands/x.md',
                 id="nested 3000 deep"),
])
def test_a_home_spelling_whose_value_is_unknown_fails_closed(scratch, command, actor):
    folder = "hooks" if "hooks" in command else "commands"
    _refused(_run(scratch, command, ACTORS[actor]), folder)


@pytest.mark.parametrize("actor", ACTORS)
def test_the_hooks_environment_does_not_decide(scratch, actor):
    """CLAUDE_HOME unset or elsewhere in the hook: the shell may still hold the home (an assignment in the command)."""
    command = 'CLAUDE_HOME=~/.claude; echo x > "$CLAUDE_HOME/commands/x.md"'
    for extra in ({"CLAUDE_HOME": ""}, {"CLAUDE_HOME": "/elsewhere"}):
        _refused(_run(scratch, command, ACTORS[actor], extra), "commands")


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("command", [
    "echo ${A:-x} > out.txt",
    'echo "${CLAUDE_HOME}" > notes.txt',
    'ls "${CLAUDE_HOME:-$HOME/.claude}/commands/"',
    'cat "$CLAUDE_HOME/hooks/x.py"',
    'cp notes.txt "$CLAUDE_HOME/agents/x.md"',
    'echo x > "${CLAUDE_HOME:-$HOME/.claude}/notes/x.md"',
    'echo x > "${CLAUDE_HOME:+/elsewhere}/commands/x.md"',
    'echo x > "$UNKNOWN/commands/x.md"',
    'git -C "$CLAUDE_HOME" log --oneline > log.txt 2>&1',
    'echo "${unbalanced" > notes.txt',
])
def test_what_names_no_protected_folder_still_goes_through(scratch, command, actor):
    proc = _run(scratch, command, ACTORS[actor])
    assert proc.returncode == 0, (command, proc.stderr)


def test_the_sentinel_still_lets_a_home_spelling_through(scratch):
    sentinel = scratch[1] / ".claude" / ".hook-refactor-allow"
    sentinel.write_text("")
    try:
        assert _run(scratch, 'echo x > "${CLAUDE_HOME:-$HOME/.claude}/commands/x.md"').returncode == 0
    finally:
        sentinel.unlink()
