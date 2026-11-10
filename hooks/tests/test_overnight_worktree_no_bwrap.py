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
STAND_IN = ROOT / "tests" / "replay" / "bin"  # the replays' bubblewrap stand-in
# Step 1's block as P1b's head (3f0b7a2) spells it, the text a session already running carries; its
# comment says "git toplevel", and it launches `python3 ~/.claude/hooks/lib/overnight.py`.
OLD_STEP1 = r'''# 1. Resolve the live session id. The Bash environment exposes CLAUDE_CODE_SESSION_ID;
#    CLAUDE_SESSION_ID is a legacy fallback and is normally unset.
CURRENT_SESSION_ID="${CLAUDE_CODE_SESSION_ID:-${CLAUDE_SESSION_ID:-}}"
[ -n "$CURRENT_SESSION_ID" ] || { echo "ERROR: no session id in environment" >&2; exit 1; }

# 2. Bind the main root and STATE_FILE together, to the canonical ABSOLUTE path of
#    THIS session's state file. CLAUDE_PROJECT_DIR is a HINT, never a precondition:
#    it is measured UNSET in this harness (while CLAUDE_CODE_SESSION_ID is set), and
#    a STALE value must not veto the fallback — so BOTH it and $PWD are tried, in
#    that order. Each start walks UP, because the state file lives at
#    <main_root>/.claude/ and every default working root sits UNDER that root
#    (in_place == main root; .claude/worktrees/<n>; .claude/overnight-fresh-clones/<n>).
#    Selection is by exact session-keyed FILENAME and then a parsed field check, so
#    it cannot be fooled by another session's file or by JSON whitespace drift.
#    The walk DISCOVERS the record; it does NOT define the root. Take the root
#    from what the record SAYS about itself, never from the directory the record
#    happens to sit in: the launcher writes the record under its own resolved
#    project dir but the dev-registry under the git toplevel (`main_root`), and
#    those DIFFER whenever the session was launched from a SUBDIRECTORY — the
#    ordinary case, since the launcher's own resolution falls back to `$PWD`.
#    Binding to the containing directory is what made Step 1 hard-abort with
#    "verify: directory does not exist: <subdir>/.claude/dev-registry/<sid>".
#    The state's one reading (hooks/lib/overnight.py) does the walk and the field
#    checks and prints both paths, canonical; it exits 1 with the reason otherwise.
PROJECT_DIR=""; STATE_FILE=""
{ read -r STATE_FILE; read -r PROJECT_DIR; } < <(python3 ~/.claude/hooks/lib/overnight.py \
    session-root "$CURRENT_SESSION_ID" "${CLAUDE_PROJECT_DIR:-}" "$PWD")
[ -n "$STATE_FILE" ] && [ -n "$PROJECT_DIR" ] || exit 1

# 3. Normalise the variable IN THIS SHELL, so the canonical anchor below resolves.
#    Same-shell only: this export does NOT reach later Bash calls, hooks, or Agent
#    prompts — those need substituted literals (see the BINDING-EVAPORATION RULE).
export CLAUDE_PROJECT_DIR="$PROJECT_DIR"

# 4. Bind the dev-registry path that every FIRST ACTION line resolves against.
DEV_SESSION_ID="$CURRENT_SESSION_ID"
REGISTRY_DIR="$CLAUDE_PROJECT_DIR/.claude/dev-registry/$DEV_SESSION_ID"

# 5. Verify, in this same shell. Read-only by ORDERING, not by permission: the
#    launcher ran the mutating form against its temporary record BEFORE publishing
#    it, so the actor has nothing left to write. --project-dir is passed explicitly
#    so the initializer never re-derives a root from the same unreliable variable.
~/.claude/scripts/overnight-init.sh --verify-only --state-file "$STATE_FILE" --project-dir "$PROJECT_DIR"
'''

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


def _hook(main: Path, tool: str, tool_input: dict, cwd: Path, agent: bool = False, home: Path | None = None,
          bwrap: bool = False):
    """The guard as the CLI runs it. `home`: a HOME whose .claude is this tree (what `~/.claude` names);
    `bwrap`: the replays' stand-in first on PATH, a host that has bubblewrap."""
    payload = {"session_id": SID, "tool_name": tool, "tool_input": tool_input, "cwd": str(cwd),
               "transcript_path": str(main / "t.jsonl")}
    if agent:
        payload.update(agent_id="a1b2c3d4e5", agent_type="dev")
    env = {**os.environ, **GIT_ENV, "CLAUDE_PROJECT_DIR": str(main), "PWD": str(cwd),
           "CLAUDE_HOME": str(ROOT), "CLAUDE_OVERNIGHT_FORCE_NO_BWRAP": "1"}
    if home is not None:
        env.pop("CLAUDE_HOME")
        env["HOME"] = str(home)
    if bwrap:
        env.pop("CLAUDE_OVERNIGHT_FORCE_NO_BWRAP")
        env["PATH"] = f"{STAND_IN}{os.pathsep}{env['PATH']}"
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


@pytest.fixture
def home(tmp_path):
    """HOME of a session whose harness home is this tree: `~/.claude` names it."""
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / ".claude").symlink_to(ROOT)
    return tmp_path / "home"


def _bash_as(main, command, cwd, agent, home, bwrap):
    return _hook(main, "Bash", {"command": command}, cwd, agent, home=home, bwrap=bwrap)


# (the in-place launch needs bubblewrap, and its working root is the main root)
OLDER_STEP1_CASES = [(k, w, b) for k in KINDS for w in ("main root", "working root") for b in (True, False)
                     if not (k == "in_place" and (not b or w == "working root"))]


@WHO
@pytest.mark.parametrize("kind,where,bwrap", OLDER_STEP1_CASES,
                         ids=[f"{k}-{w}-{'bwrap' if b else 'no bwrap'}" for k, w, b in OLDER_STEP1_CASES])
def test_a_running_sessions_older_step1_still_passes(repo, home, kind, where, bwrap, agent):
    """P1b's Step 1 (a session that loaded it keeps running on the landed hooks): the guard passed it
    in place with bubblewrap, and must pass it wherever this tree's own Step 1 passes. Stripping the
    comments dropped the word "git" that had kept the command out of the guard's script-file scan,
    which then refused `python3 ~/.claude/hooks/lib/overnight.py` (replay: P1b's A11 (b))."""
    work = _state(repo, kind)
    r = _bash_as(repo, OLD_STEP1, repo if where == "main root" else work, agent, home, bwrap)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("kind", KINDS)
def test_a_script_of_the_actor_is_still_scanned_whatever_the_comments_say(repo, home, kind):
    """The harness-script exemption is for files of the harness, not for a script in the checkout, and
    a comment word "git" no longer keeps the scan away from one."""
    work = _state(repo, kind)
    for name in ("evil.py", "hooks_copy.py"):
        (work / name).write_text(f"import subprocess\nsubprocess.run(['git', '-C', '{repo}', 'checkout', 'master'])\n")
    for command in ("python3 evil.py", "# git\npython3 evil.py", "python3 evil.py # git checkout the worktree",
                    f"python3 {work}/hooks_copy.py # git"):
        r = _bash_as(repo, command, work, False, home, True)
        assert r.returncode == 2 and "OVERNIGHT" in r.stderr, (command, r.stderr)
    # a copy of a harness script inside the checkout is the actor's file, not the harness's
    (work / "hooks" / "lib").mkdir(parents=True)
    copy = work / "hooks" / "lib" / "overnight.py"
    copy.write_text((ROOT / "hooks" / "lib" / "overnight.py").read_text())
    r = _bash_as(repo, f"python3 {copy}", work, False, home, True)
    assert r.returncode == 2 and "OVERNIGHT" in r.stderr, r.stderr
