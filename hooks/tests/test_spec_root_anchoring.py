#!/usr/bin/env python3
"""The views guard and the cp-state guard are anchored to the real spec roots (F14, F15).

hooks/pretool-bash-views-guard.py refused a Bash redirect into any `*.lock.json` anywhere
(`npm ls --json > /tmp/deps.lock.json`), and hooks/pretool-cp-state-write-guard.py refused a
subagent's write of any `*/specs/*/cp-state-*.json` (a test fixture under tests/fixtures/specs/).
Both now refuse only a path that lies under a spec root: a `.claude/specs/`, `docs/dev/specs/` or
`dot-claude/specs/` directory, read from the call's directory (and each `cd` of the command), by
the path as written and by its real path, so `../`, `./`, absolute spellings and a symlink that
lands in a spec root are refused as the plain path is.

Each case runs the real hook process in a throwaway project, with that project as the call's
directory, and checks only its exit status (0 allow, 2 refuse).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VIEWS = ROOT / "hooks" / "pretool-bash-views-guard.py"
CP_STATE = ROOT / "hooks" / "pretool-cp-state-write-guard.py"


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "proj"
    for d in (".claude/specs/s1", ".claude/specs/x", "docs/dev/specs/s1/views", "docs/dev/specs/x",
              "dot-claude/specs/x", "tests/fixtures/specs/demo", "home"):
        (p / d).mkdir(parents=True, exist_ok=True)
    (p / "README.md").write_text("readme\n")
    return p


def _run(hook: Path, payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HOME"] = str(cwd / "home")
    env.pop("CLAUDE_PROJECT_DIR", None)
    payload = dict(payload, cwd=str(cwd), session_id="spec-root-anchoring", hook_event_name="PreToolUse")
    return subprocess.run([sys.executable, str(hook)], input=json.dumps(payload), text=True,
                          capture_output=True, cwd=str(cwd), env=env, check=False, timeout=30)


def _bash(command: str, cwd: Path) -> int:
    return _run(VIEWS, {"tool_name": "Bash", "tool_input": {"command": command}}, cwd).returncode


def _write(path: str, cwd: Path, agent: bool = True, tool: str = "Write") -> int:
    payload = {"tool_name": tool, "tool_input": {"file_path": path, "content": "{}"}}
    if agent:
        payload.update(agent_id="a-dev", agent_type="dev")
    return _run(CP_STATE, payload, cwd).returncode


# ---- F15: the views guard --------------------------------------------------------------------

BASH_MUST_PASS = [
    "npm ls --all --json > /tmp/deps.lock.json",
    "cat README.md > build-info.lock.json",
    "cat README.md >> build-info.lock.json",
    "cat README.md >build-info.lock.json",
    "echo x>out/manifest.json.lock",
    "jq . package.json > tests/fixtures/specs/demo/cp-state-dev.json",
    "echo x > tests/fixtures/specs/demo/views/a.md",
    "echo x > notes/views/manifest.json",
    "cat docs/dev/specs/s1/views/manifest.json > /tmp/manifest-copy.json",
    "ls .claude/specs/s1 > /tmp/listing.txt",
    "grep -rn lock.json docs/ > /tmp/hits.txt",
    "echo hello",
    "env FOO=1 npm ls --json > /tmp/deps.lock.json",
    "cd /tmp && npm ls --json > deps.lock.json",
]

BASH_MUST_REFUSE = [
    "echo x > docs/dev/specs/s1/views/manifest.json.lock",
    "> .claude/specs/s1/cp-state-qa.json",
    "echo x > .claude/specs/s1/cp-state-qa.json",
    "echo x > docs/dev/specs/s1/views/dev.md",
    "echo x >> docs/dev/specs/s1/views/dev.md",
    "echo x > docs/dev/specs/s1/views/manifest.json",
    "echo x > docs/dev/specs/s1/views.lock.json",
    "echo x > .claude/specs/s1/state.lock.json",
    "echo x > dot-claude/specs/s1/cp-state-qa.json",
    "echo x > dot-claude/specs/s1/views/a.md",
    # attached and quoted spellings
    "echo x>docs/dev/specs/s1/views/dev.md",
    "echo x >'docs/dev/specs/s1/views/dev.md'",
    'echo x > "docs/dev/specs/s1/views/manifest.json"',
    # ./ and ../ spellings, and an absolute one built from $HOME-free text
    "echo x > ./docs/dev/specs/s1/views/dev.md",
    "echo x > tests/../docs/dev/specs/s1/views/dev.md",
    "echo x > docs/dev/specs/s1/views/../views/manifest.json",
    # cd chains
    "cd docs/dev/specs/s1/views && echo x > manifest.json",
    "cd docs/dev/specs/s1/views; echo x > dev.md",
    "cd docs && cd dev/specs/s1/views && echo x > manifest.json",
    "cd .claude/specs/s1 && echo x > cp-state-qa.json",
    "cd tests && echo x > ../.claude/specs/s1/cp-state-qa.json",
    "cd docs/dev/specs/s1 && echo x > views.lock.json",
    # wrappers, nested shells, process substitution, other writers
    "env FOO=1 echo x > docs/dev/specs/s1/views/dev.md",
    "command echo x > docs/dev/specs/s1/views/dev.md",
    "timeout 5 echo x > docs/dev/specs/s1/views/dev.md",
    "bash -c 'echo x > docs/dev/specs/s1/views/dev.md'",
    "bash -c 'cd docs/dev/specs/s1/views && echo x > manifest.json'",
    "echo x | tee docs/dev/specs/s1/views/dev.md",
    "echo x | tee >(cat > docs/dev/specs/s1/views/dev.md)",
    "cp /tmp/a.md docs/dev/specs/s1/views/dev.md",
    "cp -t docs/dev/specs/s1/views/manifest.json /tmp/a",
    "exec > .claude/specs/s1/cp-state-qa.json",
]


@pytest.mark.parametrize("command", BASH_MUST_PASS)
def test_views_guard_allows_lock_and_fixture_writes_outside_spec_roots(proj, command):
    (proj / "out").mkdir(exist_ok=True)
    (proj / "notes" / "views").mkdir(parents=True, exist_ok=True)
    assert _bash(command, proj) == 0, command


@pytest.mark.parametrize("command", BASH_MUST_REFUSE)
def test_views_guard_refuses_writes_into_spec_roots(proj, command):
    assert _bash(command, proj) == 2, command


def test_views_guard_refuses_absolute_spellings(proj):
    for target in (proj / "docs/dev/specs/s1/views/manifest.json.lock",
                   proj / ".claude/specs/s1/cp-state-qa.json",
                   proj / "docs/dev/specs/s1/views/dev.md"):
        assert _bash(f"echo x > {target}", proj) == 2, target
        assert _bash(f"echo x > {target}", proj / "tests") == 2, target


def test_views_guard_refuses_a_symlink_into_a_spec_root(proj):
    (proj / "tests/fixtures/vlink").symlink_to(Path("../../docs/dev/specs/s1/views"))
    assert _bash("echo x > tests/fixtures/vlink/manifest.json", proj) == 2
    assert _bash("echo x > tests/fixtures/vlink/dev.md", proj) == 2


def test_views_guard_reads_relative_targets_from_the_call_directory(proj):
    # from inside a spec root a bare lock file name is inside it
    assert _bash("echo x > state.lock.json", proj / ".claude/specs/s1") == 2
    assert _bash("echo x > state.lock.json", proj / "tests/fixtures/specs/demo") == 0


def test_views_guard_keeps_the_spec_check_exemption(proj):
    cmd = ("python3 ~/.claude/scripts/spec-check.py mark --spec-id s1 --agent qa --agent-id a "
           "--cp-id cp-1 > .claude/specs/s1/cp-state-qa.json")
    assert _bash(cmd, proj) == 0
    cmd = ('python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/spec-check.py" checkpoints '
           '"Write -> docs/dev/specs/s1/views/dev.md"')
    assert _bash(cmd, proj) == 0


def test_views_guard_parse_error_behaviour_is_unchanged(proj):
    # a payload that is not JSON exits 0, as on the base
    p = subprocess.run([sys.executable, str(VIEWS)], input="{not json", text=True,
                       capture_output=True, cwd=str(proj), check=False)
    assert p.returncode == 0
    # a command the shell parser cannot read is still scanned for a redirect into a spec root
    assert _bash("echo x > docs/dev/specs/s1/views/dev.md 'unterminated", proj) == 2
    assert _bash("echo x > /tmp/deps.lock.json 'unterminated", proj) == 0


# ---- F14: the cp-state guard -----------------------------------------------------------------

def test_cp_state_guard_allows_a_fixture_outside_spec_roots(proj):
    assert _write("tests/fixtures/specs/demo/cp-state-dev.json", proj) == 0
    assert _write(str(proj / "tests/fixtures/specs/demo/cp-state-dev.json"), proj) == 0
    assert _write(str(proj / "tests/fixtures/specs/demo/cp-state-dev.json"), proj, tool="Edit") == 0
    assert _write("/tmp/x/specs/demo/cp-state-qa.json", proj) == 0


CP_REFUSE_RELATIVE = [
    ".claude/specs/x/cp-state-qa.json",
    "docs/dev/specs/x/cp-state-qa.json",
    "dot-claude/specs/x/cp-state-qa.json",
    "./.claude/specs/x/cp-state-qa.json",
    "./docs/dev/specs/x/cp-state-qa.json",
    "./dot-claude/specs/x/cp-state-qa.json",
    "tests/../.claude/specs/x/cp-state-qa.json",
    "tests/fixtures/../../docs/dev/specs/x/cp-state-qa.json",
    "docs/../dot-claude/specs/x/cp-state-qa.json",
    ".claude/specs/x/cp-state-qa-2.json",
]


@pytest.mark.parametrize("path", CP_REFUSE_RELATIVE)
def test_cp_state_guard_refuses_relative_spellings(proj, path):
    assert _write(path, proj) == 2, path
    assert _write(path, proj, tool="Edit") == 2, path


@pytest.mark.parametrize("path", CP_REFUSE_RELATIVE)
def test_cp_state_guard_refuses_absolute_spellings(proj, path):
    assert _write(str(proj / path), proj) == 2, path
    assert _write(os.path.normpath(str(proj / path)), proj / "tests") == 2, path


def test_cp_state_guard_reads_relative_paths_from_the_call_directory(proj):
    assert _write("../.claude/specs/x/cp-state-qa.json", proj / "tests") == 2
    assert _write("../../.claude/specs/x/cp-state-qa.json", proj / "tests/fixtures") == 2
    assert _write("cp-state-qa.json", proj / ".claude/specs/x") == 2
    assert _write("cp-state-qa.json", proj / "tests/fixtures/specs/demo") == 0


def test_cp_state_guard_refuses_a_symlink_landing_in_a_spec_root(proj):
    (proj / "tests/fixtures/link").symlink_to(Path("../../.claude/specs"))
    (proj / "tests/fixtures/dlink").symlink_to(Path("../../docs/dev/specs"))
    (proj / "tests/fixtures/mlink").symlink_to(Path("../../dot-claude/specs"))
    for path in ("tests/fixtures/link/x/cp-state-qa.json", "tests/fixtures/dlink/x/cp-state-qa.json",
                 "tests/fixtures/mlink/x/cp-state-qa.json"):
        assert _write(path, proj) == 2, path
        assert _write(str(proj / path), proj) == 2, path


def test_cp_state_guard_still_leaves_the_main_agent_alone(proj):
    assert _write(".claude/specs/x/cp-state-qa.json", proj, agent=False) == 0
