#!/usr/bin/env python3
"""A --worktree /dev-overnight starts on a host without bubblewrap, and the keystone stays (P2-5).

Measured on d64fa96 with no bubblewrap: the guard refused /dev-overnight's Step 1 in
--worktree mode in every spelling, from the main root (the comment words "the git common dir"
and the `git rev-parse` fallback read as git ops on the main root) and from the working root
(the harness's own `python3 .../overnight.py` and `bash .../overnight-init.sh` were "not provably
worktree-local"). The in-place launch without bubblewrap names --worktree as its remedy, so such a
host could not start /dev-overnight at all. The same run showed `git config --unset
core.hooksPath` and `git config core.hooksPath /dev/null`, from the working root, passing every
hook and removing the key in --worktree mode. Now Step 1 passes, and every keystone removal P2's
R13 lists is refused in both modes, for the main agent and a subagent.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-overnight-hook-guard.py"
SID = "s-p25"
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}
STEP1 = re.search(r"### Step 1:.*?```bash\n(.*?)```",
                  (ROOT / "commands" / "dev-overnight.md").read_text(), re.S).group(1)
KINDS = ["registered_worktree", "in_place"]
WHO = pytest.mark.parametrize("agent", [False, True], ids=["main agent", "subagent"])


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A product checkout with the keystone in its git config, and a linked worktree of it."""
    main = tmp_path / "toy"
    main.mkdir()
    _git("init", "-q", "-b", "master", cwd=main)
    _git("config", "core.hooksPath", "/keystone-hooks", cwd=main)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=main)
    _git("worktree", "add", "-q", "-b", "night-work", str(tmp_path / "wt"), cwd=main)
    return main


def _state(main: Path, kind: str) -> Path:
    work = main if kind == "in_place" else main.parent / "wt"
    (main / ".claude").mkdir(exist_ok=True)
    (main / ".claude" / f"overnight-state-{SID}.json").write_text(json.dumps({
        "schema_version": 9, "session_id": SID, "isolation_kind": kind, "main_root": str(main),
        "main_git_dir": str(main / ".git"), "worktree_path": str(work), "worktree_branch": "night-work",
        "protected_branch": "master", "end_time": "2099-01-01T00:00:00Z",
        "isolation_active_until": "2099-01-01T00:00:00Z", "current_cycle": 1}))
    return work


def _hook(main: Path, tool: str, tool_input: dict, cwd: Path, agent: bool = False):
    payload = {"session_id": SID, "tool_name": tool, "tool_input": tool_input, "cwd": str(cwd),
               "transcript_path": str(main / "t.jsonl")}
    if agent:
        payload.update(agent_id="a1b2c3d4e5", agent_type="dev")
    env = {**os.environ, **GIT_ENV, "CLAUDE_PROJECT_DIR": str(main), "PWD": str(cwd),
           "CLAUDE_HOME": str(ROOT), "CLAUDE_OVERNIGHT_FORCE_NO_BWRAP": "1"}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, cwd=cwd, timeout=120)


def _bash(main, command, cwd, agent=False):
    return _hook(main, "Bash", {"command": command}, cwd, agent)


@WHO
@pytest.mark.parametrize("where", ["main root", "working root"])
def test_step1_as_written_passes_in_worktree_mode_without_bwrap(repo, where, agent):
    work = _state(repo, "registered_worktree")
    for command in (STEP1, "\n".join(ln for ln in STEP1.splitlines() if not ln.lstrip().startswith("#"))):
        r = _bash(repo, command, repo if where == "main root" else work, agent)
        assert r.returncode == 0, r.stderr


def _removals(main: Path) -> list[tuple[str, dict]]:
    return [("Bash", {"command": "git config --unset core.hooksPath"}),
            ("Bash", {"command": f"git -C {main} config --unset-all core.hooksPath"}),
            ("Bash", {"command": "git config core.hooksPath /dev/null"}),
            ("Bash", {"command": "git config --replace-all CORE.HOOKSPATH /dev/null"}),
            ("Bash", {"command": "git config --remove-section core"}),
            ("Bash", {"command": "git config remove-section core"}),
            ("Bash", {"command": "git config --edit"}),
            ("Bash", {"command": "git config --local include.path /tmp/x"}),
            ("Bash", {"command": "git config core.hooksPath get"}),
            ("Bash", {"command": "git config set core.hooksPath /dev/null"}),
            ("Bash", {"command": "git config core.hooksPath -- --get"}),
            ("Edit", {"file_path": str(main / ".git" / "config"), "old_string": "hooksPath",
                      "new_string": "x"})]


@WHO
@pytest.mark.parametrize("kind", KINDS)
def test_keystone_removals_stay_refused_without_bwrap(repo, kind, agent):
    work = _state(repo, kind)
    for cwd in {work, repo}:
        for tool, tool_input in _removals(repo):
            r = _hook(repo, tool, tool_input, cwd, agent)
            assert r.returncode == 2, (kind, cwd, tool_input, r.stderr)
    assert _git("config", "--get", "core.hooksPath", cwd=repo) == "/keystone-hooks"


@pytest.mark.parametrize("kind", KINDS)
def test_reading_the_keystone_passes(repo, kind):
    work = _state(repo, kind)
    for command in ("git config --get core.hooksPath", "git config --list --show-origin",
                    "git config get core.hooksPath", "git config user.name edit",
                    "git rev-parse --show-toplevel"):
        r = _bash(repo, command, work)
        assert r.returncode == 0, (command, r.stderr)


def test_other_interpreter_launches_still_fail_closed_without_bwrap(repo):
    work = _state(repo, "registered_worktree")
    (work / "x.sh").write_text("true\n")
    (work / "hooks").mkdir()
    (work / "hooks" / "y.py").write_text("pass\n")
    for command in ('python3 -c "print(1)"', "bash x.sh", f"bash {work}/x.sh", "python3 -m pytest -q",
                    f"python3 {work}/hooks/y.py", f'python3 "{ROOT}/hooks/lib/agent_cycle.py" x; python3 -c 1',
                    f"python3 {ROOT}/hooks/../../etc/passwd"):
        r = _bash(repo, command, work)
        assert r.returncode == 2 and "WRITE-BOUNDARY FAIL-CLOSED" in r.stderr, (command, r.stderr)


def test_a_harness_script_launch_passes_without_bwrap(repo):
    work = _state(repo, "registered_worktree")
    # (a script whose text carries a main-targeting git op, such as hooks/lib/overnight.py, is still
    # refused by the guard's operand scan when it runs on its own, in every mode)
    for command in ('python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/lib/agent_cycle.py" x',
                    'bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/overnight-init.sh" --verify-only',
                    f"bash {ROOT}/scripts/overnight-init.sh --verify-only"):
        r = _bash(repo, command, work)
        assert r.returncode == 0, (command, r.stderr)


def test_comments_are_not_read_as_git_but_quoted_hashes_hide_nothing(repo):
    work = _state(repo, "registered_worktree")
    assert _bash(repo, "# the git common dir, then git checkout master\ntrue", repo).returncode == 0
    for command in (f'echo "a #"; git -C {repo} checkout -b x', f"echo $'a\\' #'; git -C {repo} checkout -b x",
                    f'echo "$(echo " #")"; git -C {repo} checkout -b x',
                    f'echo "${{X:-" #"}}"; git -C {repo} checkout -b x'):
        r = _bash(repo, command, work)
        assert r.returncode == 2 and "OVERNIGHT" in r.stderr, (command, r.stderr)
