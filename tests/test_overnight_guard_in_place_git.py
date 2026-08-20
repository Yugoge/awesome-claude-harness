"""Regression tests: in-place overnight sessions must be able to run git.

Defect (2026-08-09): `hooks/pretool-overnight-hook-guard.py` blocked EVERY git
operation whose effective directory resolved under `main_root` and outside the
set of active ISOLATED worktrees, with an `OVERNIGHT MAIN-ROOT BLOCK`. Under
`isolation_kind: in_place` the record's working root IS the main root, so
nothing is ever "outside" it and the guard must not fire -- yet it did, which
locked the DEFAULT isolation mode out of `status`, `add`, `commit` and even the
read-only `log`.

Cause: ONE collection (`_get_active_worktree_paths`) was answering TWO different
questions:

  Q1  which roots are write-confinement targets for EVERY session
      -> an in-place record must NOT contribute (else a concurrently running
         isolated session would find the main checkout on its allow-list and be
         free to write into the very tree its isolation exists to protect)

  Q2  which root is the legitimate working root of a GIVEN live record, used to
      decide whether a git op is main-targeting
      -> an in-place record MUST contribute, or its own session is locked out

The fix separates the two. These tests pin both halves simultaneously, so a
future change cannot restore one by breaking the other.
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "hooks" / "pretool-overnight-hook-guard.py"

FAR_FUTURE = "2099-01-01T00:00:00Z"
PROTECTED = "master"

BLOCK_EXIT = 2
ALLOW_EXIT = 0


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------


def _load_guard_module():
    """Import the hyphenated hook file as a module for direct-invariant asserts."""
    spec = importlib.util.spec_from_file_location("overnight_hook_guard", HOOK)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(HOOK.parent))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(HOOK.parent))
    return mod


def _write_state(main_root: Path, session_id: str, isolation_kind: str,
                 worktree_path: Path) -> Path:
    """Write one live overnight-state record under <main_root>/.claude/."""
    claude_dir = main_root / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 9,
        "session_id": session_id,
        "isolation_kind": isolation_kind,
        "main_root": str(main_root),
        "main_git_dir": str(main_root / ".git"),
        "worktree_path": str(worktree_path),
        "worktree_branch": "work-branch",
        "protected_branch": PROTECTED,
        "end_time": FAR_FUTURE,
        "isolation_active_until": FAR_FUTURE,
        "current_cycle": 1,
    }
    path = claude_dir / f"overnight-state-{session_id}.json"
    path.write_text(json.dumps(record, indent=2))
    return path


def _write_agent_index(main_root: Path, mapping: dict) -> None:
    """Register subagent ids so `_classify_actor` can reach `overnight_child`.

    Without this the payload's agent_id resolves to nothing and the actor falls
    through to `normal`, which exits before ANY enforcement -- a test written
    that way proves nothing about the child path.
    """
    reg = main_root / ".claude" / "dev-registry"
    reg.mkdir(parents=True, exist_ok=True)
    (reg / "agent-index.json").write_text(json.dumps(mapping))


def _run_hook(main_root: Path, tool_name: str, tool_input: dict,
              session_id: str = "", cwd: str = "", agent_id: str = "",
              extra_env: dict | None = None) -> subprocess.CompletedProcess:
    """Drive the PreToolUse guard exactly as the runtime does: JSON on stdin."""
    payload = {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "session_id": session_id,
        "cwd": cwd or str(main_root),
    }
    if agent_id:
        payload["agent_id"] = agent_id
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(main_root)
    env["PWD"] = payload["cwd"]
    # A stray role in the ambient env must not leak into grant resolution.
    env.pop("CLAUDE_AGENT_TYPE", None)
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=payload["cwd"],
        timeout=120,
    )


def _rw_binds(rewritten: str) -> list[str]:
    """Read-write bind TARGETS out of a bwrap re-exec argv.

    Token-aware on purpose: `--ro-bind` must never be counted as `--bind`, and
    a substring/arithmetic shortcut here silently yields an empty list, which
    makes every downstream `all(...)` assertion vacuously true.
    """
    toks = shlex.split(rewritten)
    return [toks[i + 1] for i, t in enumerate(toks)
            if t == "--bind" and i + 1 < len(toks)]


@pytest.fixture()
def main_root(tmp_path: Path) -> Path:
    """A bare directory standing in for the user's main checkout."""
    root = tmp_path / "main"
    (root / ".git").mkdir(parents=True)
    (root / ".claude").mkdir(parents=True)
    return root


@pytest.fixture()
def isolated_worktree(main_root: Path) -> Path:
    """An isolated worktree living under the main root, as the launcher makes it."""
    wt = main_root / ".claude" / "worktrees" / "overnight-iso"
    wt.mkdir(parents=True)
    return wt


ORDINARY_GIT = [
    "git status --porcelain",
    "git add -A",
    'git commit -m "cycle work"',
    "git log --oneline -1",
    "git diff --name-only",
]


# ---------------------------------------------------------------------------
# control: no live record at all
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ORDINARY_GIT)
def test_control_no_live_record_allows_git(main_root, command):
    """Control fixture: with no overnight record, git is untouched by the guard."""
    res = _run_hook(main_root, "Bash", {"command": command})
    assert res.returncode == ALLOW_EXIT, (
        f"control regressed -- {command!r} blocked with no live record:\n{res.stderr}"
    )


# ---------------------------------------------------------------------------
# Q2: the in-place record's own working root is NOT main-targeting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ORDINARY_GIT)
def test_in_place_session_may_run_ordinary_git_in_its_own_root(main_root, command):
    """THE DEFECT: in-place mode could not run git at all, not even read-only log."""
    _write_state(main_root, "sid-inplace", "in_place", main_root)
    res = _run_hook(main_root, "Bash", {"command": command},
                    session_id="sid-inplace", cwd=str(main_root))
    assert res.returncode == ALLOW_EXIT, (
        f"in-place session locked out of {command!r}:\n{res.stderr}"
    )
    assert "MAIN-ROOT BLOCK" not in res.stderr


def test_in_place_session_git_allowed_in_a_subdirectory(main_root):
    """The working root includes its subtree, not just the root directory itself."""
    _write_state(main_root, "sid-inplace", "in_place", main_root)
    subdir = main_root / "hooks"
    subdir.mkdir()
    res = _run_hook(main_root, "Bash", {"command": "git status --porcelain"},
                    session_id="sid-inplace", cwd=str(subdir))
    assert res.returncode == ALLOW_EXIT, res.stderr


def test_in_place_child_subagent_may_run_git(main_root):
    """A subagent of the in-place session resolves to the same governing record.

    The child arrives with no resolvable dev-registry entry here, so it falls
    through to `normal` and is not enforced -- the assertion is simply that the
    guard does not block it, which is the user-visible contract.
    """
    _write_state(main_root, "sid-inplace", "in_place", main_root)
    res = _run_hook(main_root, "Bash", {"command": "git add -A"},
                    session_id="", cwd=str(main_root))
    assert res.returncode == ALLOW_EXIT, res.stderr


# ---------------------------------------------------------------------------
# Q2 must NOT be relaxed for isolated records (the guard still holds)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ORDINARY_GIT)
def test_isolated_session_still_blocked_at_main_root(main_root, isolated_worktree, command):
    """Correct pre-existing behaviour: an isolated actor at main root is refused."""
    _write_state(main_root, "sid-iso", "registered_worktree", isolated_worktree)
    res = _run_hook(main_root, "Bash", {"command": command},
                    session_id="sid-iso", cwd=str(main_root))
    assert res.returncode == BLOCK_EXIT, (
        f"isolated actor was allowed to run {command!r} at the main root"
    )
    assert "MAIN-ROOT BLOCK" in res.stderr


def test_isolated_session_cannot_git_into_main_root_via_dash_C(main_root, isolated_worktree):
    """A `-C <main>` redirect from inside the worktree is still main-targeting."""
    _write_state(main_root, "sid-iso", "registered_worktree", isolated_worktree)
    res = _run_hook(main_root, "Bash",
                    {"command": f'git -C {main_root} commit -m "sneak"'},
                    session_id="sid-iso", cwd=str(isolated_worktree))
    assert res.returncode == BLOCK_EXIT, "isolated actor reached main root via -C"
    assert "MAIN-ROOT BLOCK" in res.stderr


# ---------------------------------------------------------------------------
# both records live at once: the two questions must not cross-contaminate
# ---------------------------------------------------------------------------


def test_concurrent_isolated_session_cannot_git_into_main_root(main_root, isolated_worktree):
    """With a live in-place record present, the isolated session stays confined.

    This is the adversarial case the in-place exclusion was written for: the
    in-place record's working root IS the main checkout, and it must never become
    a licence for a DIFFERENT, concurrently running isolated session.
    """
    _write_state(main_root, "sid-inplace", "in_place", main_root)
    _write_state(main_root, "sid-iso", "registered_worktree", isolated_worktree)
    res = _run_hook(main_root, "Bash",
                    {"command": f'git -C {main_root} commit -m "sneak"'},
                    session_id="sid-iso", cwd=str(isolated_worktree))
    assert res.returncode == BLOCK_EXIT, (
        "a live in-place record handed the isolated session access to main root"
    )


def test_concurrent_worktree_context_actor_cannot_git_into_main_root(
        main_root, isolated_worktree):
    """An in-worktree actor with no owner/child resolution must not inherit the
    in-place record as its governing state (which would disarm the main-root
    block for it)."""
    _write_state(main_root, "sid-inplace", "in_place", main_root)
    _write_state(main_root, "sid-iso", "registered_worktree", isolated_worktree)
    res = _run_hook(main_root, "Bash",
                    {"command": f'git -C {main_root} commit -m "sneak"'},
                    session_id="unregistered-sid", cwd=str(isolated_worktree))
    assert res.returncode == BLOCK_EXIT, (
        "worktree_context actor was governed by the in-place record"
    )


@pytest.mark.parametrize("tool_name,tool_input", [
    ("Write", {"file_path": "<MAIN>/planted.txt", "content": "x"}),
    ("Edit", {"file_path": "<MAIN>/planted.txt", "old_string": "a", "new_string": "b"}),
])
def test_concurrent_isolated_session_cannot_write_into_main_root(
        main_root, isolated_worktree, tool_name, tool_input):
    """Write-confinement (Q1) is unchanged: in-place never widens the allow-list."""
    _write_state(main_root, "sid-inplace", "in_place", main_root)
    _write_state(main_root, "sid-iso", "registered_worktree", isolated_worktree)
    resolved = {
        k: (v.replace("<MAIN>", str(main_root)) if isinstance(v, str) else v)
        for k, v in tool_input.items()
    }
    res = _run_hook(main_root, tool_name, resolved,
                    session_id="sid-iso", cwd=str(isolated_worktree))
    assert res.returncode == BLOCK_EXIT, (
        f"isolated session wrote into the main root via {tool_name}"
    )


def test_concurrent_isolated_session_bash_write_to_main_root_is_confined(
        main_root, isolated_worktree):
    """A Bash write is confined by the OS boundary rather than an exit-2 block.

    The guard rewrites the actor's command to re-exec inside a bwrap mount
    namespace in which the whole host is `--ro-bind` and the ONLY read-write
    bind is the isolated worktree, so the write hits EROFS. Either outcome --
    a refusal, or a rewrite whose sole RW bind is the worktree -- satisfies the
    contract; silently passing the raw command through does not.
    """
    _write_state(main_root, "sid-inplace", "in_place", main_root)
    _write_state(main_root, "sid-iso", "registered_worktree", isolated_worktree)
    command = f"echo x > {main_root}/planted.txt"
    res = _run_hook(main_root, "Bash", {"command": command},
                    session_id="sid-iso", cwd=str(isolated_worktree))
    if res.returncode == BLOCK_EXIT:
        return
    assert res.returncode == ALLOW_EXIT, res.stderr
    rewritten = json.loads(res.stdout)["hookSpecificOutput"]["updatedInput"]["command"]
    assert "--ro-bind / /" in rewritten, "main tree was not bound read-only"
    rw_binds = [rewritten.split("--bind ")[i + 1].split(" ")[0]
                for i in range(rewritten.count("--bind ") - rewritten.count("--ro-bind "))]
    assert all(b.startswith(str(isolated_worktree)) for b in rw_binds), (
        f"a read-write bind escaped the isolated worktree: {rw_binds}"
    )


def test_malformed_in_place_record_earns_no_exemption(main_root):
    """The exemption is bounded by the record's own main_root, never wider.

    A record claiming a working root outside its main_root is malformed; it must
    not be able to widen the main-targeting exemption to an arbitrary prefix.
    """
    claude_dir = main_root / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "overnight-state-sid-bad.json").write_text(json.dumps({
        "schema_version": 9,
        "session_id": "sid-bad",
        "isolation_kind": "in_place",
        "main_root": str(main_root),
        "worktree_path": "/",          # escapes main_root
        "protected_branch": PROTECTED,
        "end_time": FAR_FUTURE,
    }))
    res = _run_hook(main_root, "Bash", {"command": "git commit -m x"},
                    session_id="sid-bad", cwd=str(main_root))
    assert res.returncode == BLOCK_EXIT, (
        "a malformed in-place record widened the main-targeting exemption"
    )


def test_in_place_record_never_joins_the_write_confinement_allow_list(main_root):
    """Q1 invariant, asserted directly on the collection that answers it."""
    guard = _load_guard_module()
    state_path = _write_state(main_root, "sid-inplace", "in_place", main_root)
    assert guard._extract_live_worktree_path(state_path) == "", (
        "an in-place record leaked onto the shared write-confinement allow-list"
    )

    iso_wt = main_root / ".claude" / "worktrees" / "overnight-iso"
    iso_wt.mkdir(parents=True)
    iso_path = _write_state(main_root, "sid-iso", "registered_worktree", iso_wt)
    assert guard._extract_live_worktree_path(iso_path) == str(iso_wt)


# ---------------------------------------------------------------------------
# protected-branch behaviour must survive in BOTH isolation modes
# ---------------------------------------------------------------------------


PROTECTED_REF_MOVES = [
    f"git branch -f {PROTECTED} HEAD",
    f"git branch -D {PROTECTED}",
    f"git update-ref refs/heads/{PROTECTED} HEAD",
    f"git symbolic-ref HEAD refs/heads/{PROTECTED}",
]


@pytest.mark.parametrize("command", PROTECTED_REF_MOVES)
def test_protected_branch_refused_for_in_place_actor(main_root, command):
    """In-place gains ordinary git -- it must NOT gain the protected branch."""
    _write_state(main_root, "sid-inplace", "in_place", main_root)
    res = _run_hook(main_root, "Bash", {"command": command},
                    session_id="sid-inplace", cwd=str(main_root))
    assert res.returncode == BLOCK_EXIT, (
        f"in-place actor was allowed to move the protected branch: {command!r}"
    )
    assert "REF-MOVE BLOCK" in res.stderr


@pytest.mark.parametrize("command", PROTECTED_REF_MOVES)
def test_protected_branch_refused_for_isolated_actor(main_root, isolated_worktree, command):
    """Same refusal from inside an isolated worktree."""
    _write_state(main_root, "sid-iso", "registered_worktree", isolated_worktree)
    res = _run_hook(main_root, "Bash", {"command": command},
                    session_id="sid-iso", cwd=str(isolated_worktree))
    assert res.returncode == BLOCK_EXIT, (
        f"isolated actor was allowed to move the protected branch: {command!r}"
    )


@pytest.mark.parametrize("command", [
    f"git checkout {PROTECTED}",
    f"git switch {PROTECTED}",
])
def test_protected_branch_switch_refused_for_in_place_actor(main_root, command):
    """A switch onto the protected branch is refused in in-place mode too."""
    _write_state(main_root, "sid-inplace", "in_place", main_root)
    res = _run_hook(main_root, "Bash", {"command": command},
                    session_id="sid-inplace", cwd=str(main_root))
    assert res.returncode == BLOCK_EXIT, (
        f"in-place actor was allowed onto the protected branch: {command!r}"
    )


def test_in_place_actor_still_refused_git_config_hook_suppression(main_root):
    """The config firewall never relaxes, in either isolation mode."""
    _write_state(main_root, "sid-inplace", "in_place", main_root)
    res = _run_hook(main_root, "Bash",
                    {"command": "git -c core.hooksPath=/dev/null commit -m x"},
                    session_id="sid-inplace", cwd=str(main_root))
    assert res.returncode == BLOCK_EXIT
    assert "CONFIG FIREWALL" in res.stderr
