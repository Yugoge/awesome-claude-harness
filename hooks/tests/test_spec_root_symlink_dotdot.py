#!/usr/bin/env python3
"""The views and cp-state guards read `..` after a symlink as the kernel does, and judge a
directory destination and `touch` (OB-L37 rework).

The kernel resolves a symlink before the `..` that follows it: with `link -> .claude/specs/s1`,
`link/../s1/cp-state-qa.json` is `.claude/specs/s1/cp-state-qa.json`, while a textual fold of
`..` reads it as `s1/cp-state-qa.json` beside `link`. Both guards now also match the real path
of the unfolded spelling (and the views guard does so for each `cd` directory too).

The views guard also judges a copy, move, install or link into a directory as
`<dest>/<basename(source)>` (a trailing `/`, `-t`/`--target-directory`, several sources or an
existing directory destination), and a `touch` of a cp-state or views file as a write.

Each case runs the real hook process in a throwaway project and checks only its exit status.
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
    for d in (".claude/specs/s1/views", ".claude/specs/x", "docs/dev/specs/s1/views", "docs/dev/specs/x",
              "tests/fixtures/specs/demo", "home", "out", "sub"):
        (p / d).mkdir(parents=True, exist_ok=True)
    (p / "README.md").write_text("readme\n")
    os.symlink(p / ".claude/specs/s1", p / "link")
    os.symlink(p / ".claude/specs/s1/views", p / "vlink")
    os.symlink(p / "tests/fixtures/specs/demo", p / "flink")
    return p


def _run(hook: Path, payload: dict, cwd: Path) -> int:
    env = dict(os.environ)
    env["HOME"] = str(cwd / "home")
    env.pop("CLAUDE_PROJECT_DIR", None)
    payload = dict(payload, cwd=str(cwd), session_id="spec-root-symlink", hook_event_name="PreToolUse")
    return subprocess.run([sys.executable, str(hook)], input=json.dumps(payload), text=True,
                          capture_output=True, cwd=str(cwd), env=env, check=False, timeout=30).returncode


def _bash(command: str, cwd: Path) -> int:
    return _run(VIEWS, {"tool_name": "Bash", "tool_input": {"command": command.replace("@P", str(cwd))}}, cwd)


def _write(path: str, cwd: Path, tool: str = "Write") -> int:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    payload = {"tool_name": tool, "tool_input": {key: path.replace("@P", str(cwd)), "content": "{}"},
               "agent_id": "a-dev", "agent_type": "dev"}
    return _run(CP_STATE, payload, cwd)


# ---- the cp-state guard: symlink then `..` ----------------------------------------------------

CP_STATE_DOTDOT = [
    "link/../s1/cp-state-qa.json",
    "@P/link/../s1/cp-state-qa.json",
    "link/../x/cp-state-qa.json",
    "vlink/../cp-state-qa.json",
    "vlink/../../s1/cp-state-qa.json",
]


@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit", "NotebookEdit"])
@pytest.mark.parametrize("path", CP_STATE_DOTDOT)
def test_cp_state_guard_resolves_a_symlink_before_dotdot(proj, path, tool):
    assert _write(path, proj, tool) == 2


@pytest.mark.parametrize("path", [
    "tests/fixtures/specs/demo/cp-state-dev.json",
    "flink/../demo/cp-state-dev.json",
    "sub/../notes.json",
    "link/../../../README.md",
])
def test_cp_state_guard_still_allows_paths_outside_spec_roots(proj, path):
    assert _write(path, proj) == 0


# ---- the views guard: symlink then `..`, in a target and in a `cd` ----------------------------

VIEWS_DOTDOT = [
    "echo x > link/../s1/cp-state-qa.json",
    "echo x > @P/link/../x/cp-state-qa.json",
    "echo x > vlink/../../s1/views/a.md",
    "echo x | tee vlink/../cp-state-qa.json",
    "cd vlink/.. && echo x > cp-state-qa.json",
    "cd -P vlink/.. && echo x > cp-state-qa.json",
    "cd link && cd .. && echo x > x/cp-state-qa.json",
]


@pytest.mark.parametrize("command", VIEWS_DOTDOT)
def test_views_guard_resolves_a_symlink_before_dotdot(proj, command):
    assert _bash(command, proj) == 2


# ---- the views guard: a directory destination -------------------------------------------------

DIR_DEST_REFUSE = [
    "cp /tmp/cp-state-qa.json .claude/specs/s1/",
    "cp /tmp/cp-state-qa.json .claude/specs/s1",
    "cp -t .claude/specs/s1 /tmp/cp-state-qa.json",
    "cp --target-directory=.claude/specs/s1 /tmp/cp-state-qa.json",
    "cp --target-directory .claude/specs/s1 /tmp/cp-state-qa.json",
    "cp /tmp/a.txt /tmp/cp-state-qa.json .claude/specs/new-id",
    "cp -p /tmp/cp-state-qa.json @P/.claude/specs/s1",
    "mv /tmp/dev.md docs/dev/specs/s1/views/",
    "mv /tmp/dev.md docs/dev/specs/s1/views",
    "mv -t docs/dev/specs/s1/views /tmp/dev.md",
    "install -m 644 /tmp/dev.md docs/dev/specs/s1/views",
    "ln -s /tmp/dev.md docs/dev/specs/s1/views/",
    "cd docs/dev/specs/s1/views && ln -s /tmp/dev.md",
    "rsync -a /tmp/cp-state-qa.json .claude/specs/s1/",
    "cp /tmp/cp-state-qa.json link",
    "cd .claude/specs && cp /tmp/cp-state-qa.json s1",
    "bash -c 'cp /tmp/cp-state-qa.json .claude/specs/s1'",
    "env cp /tmp/cp-state-qa.json .claude/specs/s1/",
    "timeout 5 mv /tmp/manifest.json docs/dev/specs/s1/views/",
]


@pytest.mark.parametrize("command", DIR_DEST_REFUSE)
def test_views_guard_judges_a_directory_destination_by_the_source_name(proj, command):
    assert _bash(command, proj) == 2


DIR_DEST_PASS = [
    "cp /tmp/cp-state-qa.json /tmp/out/",
    "cp /tmp/cp-state-qa.json out",
    "cp README.md .claude/specs/s1/",
    "cp /tmp/cp-state-qa.json .claude/specs/s1/notes.json",
    "cp -T /tmp/cp-state-qa.json .claude/specs/s1/notes.json",
    "cp /tmp/cp-state-qa.json tests/fixtures/specs/demo/",
    "mv docs/dev/specs/s1/views/a.md /tmp/",
    "cp -r docs/dev/specs/s1/views out/",
    "ln -s /tmp/a.txt .claude/specs/s1/",
]


@pytest.mark.parametrize("command", DIR_DEST_PASS)
def test_views_guard_allows_directory_copies_that_land_outside_the_patterns(proj, command):
    assert _bash(command, proj) == 0


# ---- the views guard: touch ---------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "touch .claude/specs/s1/cp-state-qa.json",
    "touch docs/dev/specs/s1/views/a.md",
    "touch -d now docs/dev/specs/s1/views/manifest.json",
    "touch -c -- .claude/specs/x/cp-state-dev.json",
    "env touch link/cp-state-qa.json",
    "touch README.md .claude/specs/s1/run.lock.json",
])
def test_views_guard_refuses_touch_of_a_guarded_file(proj, command):
    assert _bash(command, proj) == 2


@pytest.mark.parametrize("command", [
    "touch README.md",
    "touch tests/fixtures/specs/demo/cp-state-dev.json",
    "touch -r .claude/specs/s1/cp-state-qa.json /tmp/stamp",
    "touch --reference=docs/dev/specs/s1/views/a.md out/stamp",
    "touch .claude/specs/s1/notes.txt",
])
def test_views_guard_allows_touch_elsewhere(proj, command):
    assert _bash(command, proj) == 0


# ---- the lane's must-pass examples still pass --------------------------------------------------

@pytest.mark.parametrize("command", [
    "npm ls --all --json > /tmp/deps.lock.json",
    "cat README.md > build-info.lock.json",
])
def test_must_pass_bash_examples_still_pass(proj, command):
    assert _bash(command, proj) == 0
