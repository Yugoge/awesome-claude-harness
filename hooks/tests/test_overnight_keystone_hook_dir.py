#!/usr/bin/env python3
"""An overnight actor leaves the keystone hook dir as it is, in both modes.

In both isolation modes neither a `chmod -x` of `<common>/keystone-hooks/reference-transaction`
nor, in place, a redirect or a `cp` onto it may pass: after either, the keystone would refuse no
ref move. The shared parser reads the operands of chmod, chown, chattr and setfacl as write
targets, the keystone hook dir is one of the guard's git-config paths for a Write, an Edit and each
Bash write target, and bubblewrap rebinds it read-only. A file in the worktree, and every session
outside overnight, pass.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
GUARD = HOOKS / "pretool-overnight-hook-guard.py"
INSTALLER = ROOT / "scripts" / "install-git-keystone.sh"
STAND_IN = ROOT / "tests" / "replay" / "bin"  # a bubblewrap that applies no binds
SID = "s-keystone-dir"
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}
KINDS = ["in_place", "registered_worktree"]
WHO = pytest.mark.parametrize("agent", [False, True], ids=["main agent", "subagent"])
BWRAP = pytest.mark.parametrize("bwrap", [False, True], ids=["no bwrap", "bwrap"])


def _git(*args, cwd) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A product checkout with the keystone installed by its own installer, and a linked worktree."""
    main = tmp_path / "toy"
    main.mkdir()
    _git("init", "-q", "-b", "master", cwd=main)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=main)
    subprocess.run(["bash", str(INSTALLER), "--project-dir", str(main)], check=True, capture_output=True,
                   env={**os.environ, **GIT_ENV})
    _git("worktree", "add", "-q", "-b", "night-work", str(tmp_path / "wt"), cwd=main)
    return main


def _keystone(main: Path) -> Path:
    """The keystone hook file, where the installer's core.hooksPath puts it."""
    return Path(_git("config", "--get", "core.hooksPath", cwd=main)) / "reference-transaction"


def _state(main: Path, kind: str) -> Path:
    work = main if kind == "in_place" else main.parent / "wt"
    (main / ".claude").mkdir(exist_ok=True)
    (main / ".claude" / f"overnight-state-{SID}.json").write_text(json.dumps({
        "schema_version": 9, "session_id": SID, "isolation_kind": kind, "main_root": str(main),
        "main_git_dir": str(main / ".git"), "worktree_path": str(work), "worktree_branch": "night-work",
        "protected_branch": "master", "end_time": "2099-01-01T00:00:00Z",
        "isolation_active_until": "2099-01-01T00:00:00Z", "current_cycle": 1}))
    return work


def _env(main: Path, cwd: Path, bwrap: bool) -> dict:
    env = {**os.environ, **GIT_ENV, "CLAUDE_PROJECT_DIR": str(main), "PWD": str(cwd), "CLAUDE_HOME": str(ROOT)}
    if bwrap:
        env.pop("CLAUDE_OVERNIGHT_FORCE_NO_BWRAP", None)
        env["PATH"] = f"{STAND_IN}{os.pathsep}{env['PATH']}"
    else:
        env["CLAUDE_OVERNIGHT_FORCE_NO_BWRAP"] = "1"
    return env


def _hook(main: Path, tool: str, tool_input: dict, cwd: Path, agent: bool = False, bwrap: bool = False,
          session: str = SID, hook: Path = GUARD):
    payload = {"session_id": session, "tool_name": tool, "tool_input": tool_input, "cwd": str(cwd),
               "transcript_path": str(main / "t.jsonl")}
    if agent:
        payload.update(agent_id="a1b2c3d4e5", agent_type="dev")
    return subprocess.run([sys.executable, str(hook)], input=json.dumps(payload), capture_output=True,
                          text=True, env=_env(main, cwd, bwrap), cwd=cwd, timeout=120)


def _actions(rt: Path, cwd: Path) -> dict[str, tuple[str, dict]]:
    """Every form A1 names, aimed at the keystone hook file."""
    other = cwd / "evil-hook"
    return {
        "chmod -x": ("Bash", {"command": f"chmod -x {rt}"}),
        "chmod 000": ("Bash", {"command": f"chmod 000 {rt}"}),
        "chown": ("Bash", {"command": f"chown 65534:65534 {rt}"}),
        "chattr": ("Bash", {"command": f"chattr +i {rt}"}),
        "setfacl -m": ("Bash", {"command": f"setfacl -m u:65534:--- {rt}"}),
        "> redirect": ("Bash", {"command": f"echo 'exit 0' > {rt}"}),
        "cp onto it": ("Bash", {"command": f"cp {other} {rt}"}),
        "Write": ("Write", {"file_path": str(rt), "content": "#!/bin/sh\nexit 0\n"}),
        "Edit": ("Edit", {"file_path": str(rt), "old_string": "set -u", "new_string": "exit 0"}),
    }


FORMS = list(_actions(Path("/x"), Path("/x")))


@WHO
@BWRAP
@pytest.mark.parametrize("form", FORMS)
@pytest.mark.parametrize("kind", KINDS)
def test_an_actor_cannot_change_the_keystone_hook(repo, kind, form, bwrap, agent):
    """A1: each form is refused by the guard, with or without bubblewrap, and the hook is unchanged."""
    work = _state(repo, kind)
    rt = _keystone(repo)
    before = (rt.read_bytes(), stat.S_IMODE(rt.stat().st_mode))
    tool, tool_input = _actions(rt, work)[form]
    r = _hook(repo, tool, tool_input, work, agent, bwrap)
    assert r.returncode == 2 and "OVERNIGHT" in r.stderr, (kind, form, r.returncode, r.stdout, r.stderr)
    assert (rt.read_bytes(), stat.S_IMODE(rt.stat().st_mode)) == before


@pytest.mark.parametrize("kind", KINDS)
def test_the_keystone_hook_dir_and_a_relative_spelling_are_refused(repo, kind):
    work = _state(repo, kind)
    rt = _keystone(repo)
    rel = os.path.relpath(rt, work)
    for command in (f"chmod -R -x {rt.parent}", f"chmod -x {rel}", f"chmod u-x -- {rt}",
                    f"/bin/chmod -x {rt}", f"sudo chmod -x {rt}", f"install -m 0644 /dev/null {rt}"):
        r = _hook(repo, "Bash", {"command": command}, work)
        assert r.returncode == 2 and "OVERNIGHT GIT CONFIG PROTECTION" in r.stderr, (command, r.stderr)


def _guard_module():
    spec = importlib.util.spec_from_file_location("overnight_guard_for_test", GUARD)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(HOOKS))
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("kind", KINDS)
def test_bubblewrap_rebinds_the_keystone_hook_dir_read_only(repo, kind, monkeypatch):
    """The third check: the boundary's argv nests a read-only bind of the dir over the RW common dir,
    derived from `git rev-parse --git-common-dir` and core.hooksPath's install, in both modes."""
    work = _state(repo, kind)
    monkeypatch.setenv("PATH", f"{STAND_IN}{os.pathsep}{os.environ['PATH']}")
    guard = _guard_module()
    argv = guard._build_bwrap_argv("true", str(repo), str(work), kind)
    ro = [argv[i + 1] for i, a in enumerate(argv) if a == "--ro-bind"]
    common = Path(_git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=work)).resolve()
    assert str(_keystone(repo).parent) in ro
    assert {str(common / "config"), str(common / "hooks")} <= set(ro)


def _real_bwrap() -> bool:
    exe = shutil.which("bwrap")
    if not exe or os.path.realpath(exe).startswith(str(STAND_IN)):
        return False
    return subprocess.run([exe, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--", "true"],
                          capture_output=True).returncode == 0


@pytest.mark.skipif(not _real_bwrap(), reason="needs a bubblewrap that can run on this host")
@pytest.mark.parametrize("kind", KINDS)
def test_inside_the_boundary_the_keystone_hook_is_read_only(repo, kind):
    """With a real bubblewrap, a form the parser cannot read (a `cd` into the dir) hits EROFS too,
    while a commit in the working root still lands."""
    work = _state(repo, kind)
    rt = _keystone(repo)
    guard = _guard_module()
    for command in (f"cd {rt.parent} && chmod -x reference-transaction",
                    f"cd {rt.parent} && cp /bin/true reference-transaction"):
        argv = guard._build_bwrap_argv(command, str(repo), str(work), kind)
        r = subprocess.run(argv, capture_output=True, text=True, cwd=work, env={**os.environ, **GIT_ENV})
        assert r.returncode != 0 and "Read-only file system" in r.stderr, (command, r.stderr)
        assert os.access(rt, os.X_OK) and b"keystone" in rt.read_bytes()
    argv = guard._build_bwrap_argv("echo x > f && git add f && git commit -qm f", str(repo), str(work), kind)
    r = subprocess.run(argv, capture_output=True, text=True, cwd=work, env={**os.environ, **GIT_ENV})
    assert r.returncode == 0, r.stderr


@WHO
@BWRAP
@pytest.mark.parametrize("kind", KINDS)
def test_a_dev_chmod_in_its_working_root_passes(repo, kind, bwrap, agent):
    """A2: a chmod +x of a file inside the working root is no new block."""
    work = _state(repo, kind)
    (work / "tools").mkdir()
    (work / "tools" / "run.sh").write_text("#!/bin/sh\n")
    for command in ("chmod +x tools/run.sh", f"chmod +x {work}/tools/run.sh", "chmod -R u+rwX tools"):
        r = _hook(repo, "Bash", {"command": command}, work, agent, bwrap)
        assert r.returncode == 0, (command, r.stderr)


def test_outside_overnight_every_consumer_passes_a_chmod(repo):
    """A2: the main agent's chmod of an ordinary product file, no overnight session: each consumer of
    the shared parser exits 0."""
    (repo / "run.sh").write_text("#!/bin/sh\n")
    for hook in ("pretool-overnight-hook-guard.py", "pretool-tool-policy.py", "pretool-cp-state-write-guard.py"):
        for command in (f"chmod +x {repo}/run.sh", "chmod 644 run.sh", f"chown 0:0 {repo}/run.sh"):
            r = _hook(repo, "Bash", {"command": command}, repo, hook=HOOKS / hook)
            assert r.returncode == 0, (hook, command, r.stderr)


def test_another_session_while_overnight_runs_passes(repo):
    """The owner's own session is no overnight actor: its keystone refresh and a chmod in the hook dir
    pass the guard while a session is live."""
    _state(repo, "in_place")
    rt = _keystone(repo)
    for command in (f"bash {INSTALLER} --project-dir {repo}", f"chmod 0755 {rt}"):
        r = _hook(repo, "Bash", {"command": command}, repo, session="the-owner")
        assert r.returncode == 0, (command, r.stderr)


def test_the_installer_installs_and_refreshes(tmp_path):
    """A3: the owner's install, then a refresh of a hook someone emptied and made non-executable."""
    main = tmp_path / "toy"
    main.mkdir()
    _git("init", "-q", "-b", "master", cwd=main)
    hooks = Path(_git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=main)) / "hooks"
    (hooks / "post-commit").write_text("#!/bin/sh\necho kept\n")
    (hooks / "post-commit").chmod(0o755)
    env = {**os.environ, **GIT_ENV}
    first = subprocess.run(["bash", str(INSTALLER), "--project-dir", str(main)], capture_output=True, text=True,
                           env=env)
    assert first.returncode == 0 and "REHOMED_HOOKS=post-commit" in first.stdout, first.stderr
    rt = _keystone(main)
    assert os.access(rt, os.X_OK) and rt.read_bytes() == (HOOKS / "git-keystone" / "reference-transaction").read_bytes()
    rt.write_text("")
    rt.chmod(0o644)
    again = subprocess.run(["bash", str(INSTALLER), "--project-dir", str(main)], capture_output=True, text=True,
                           env=env)
    assert again.returncode == 0 and "already installed; keystone refreshed" in again.stdout, again.stderr
    assert os.access(rt, os.X_OK) and rt.read_bytes() == (HOOKS / "git-keystone" / "reference-transaction").read_bytes()
    commit = subprocess.run(["git", "commit", "--allow-empty", "-m", "x"], cwd=main, env=env, capture_output=True,
                            text=True)
    assert commit.returncode == 0 and "kept" in commit.stdout + commit.stderr  # the re-homed hook still fires


READ = {"dd of=": "dd if=/dev/null of={rt}", "truncate": "truncate -s 0 {rt}", "ln -sf": "ln -sf /bin/true {rt}",
        "rsync": "rsync {work}/x {rt}"}
MISSES = {"cd, then a relative chmod": "cd {dir} && chmod -x reference-transaction"}


@pytest.mark.parametrize("form", list(READ))
def test_the_parser_reads_these_writes_of_the_keystone_hook(repo, form):
    """The shared parser names the target of each, so the guard refuses it without bubblewrap too."""
    work = _state(repo, "registered_worktree")
    rt = _keystone(repo)
    command = READ[form].format(rt=rt, work=work, dir=rt.parent)
    r = _hook(repo, "Bash", {"command": command}, work)
    assert r.returncode == 2, (form, r.stderr)


@pytest.mark.xfail(strict=True, reason="out of scope, found: on a --worktree host without bubblewrap the parser "
                                       "reads no target of these, so the keystone hook is reachable")
@pytest.mark.parametrize("form", list(MISSES))
def test_out_of_scope_found_writes_the_parser_cannot_read(repo, form):
    """Measured on this tree: each passes the guard here and, run, changes the keystone hook; with
    bubblewrap (in place always has it) the read-only rebind refuses every one with EROFS."""
    work = _state(repo, "registered_worktree")
    rt = _keystone(repo)
    command = MISSES[form].format(rt=rt, work=work, dir=rt.parent)
    r = _hook(repo, "Bash", {"command": command}, work)
    assert r.returncode == 2, (form, r.stderr)
