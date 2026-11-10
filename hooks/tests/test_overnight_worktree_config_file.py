#!/usr/bin/env python3
"""An overnight actor cannot write a worktree's per-worktree git config (P2-8, P2 R13).

With `extensions.worktreeConfig` on, git reads `<gitdir>/config.worktree` after the shared config, so
a core.hooksPath or include.path written there redirects the keystone for that worktree, and
bubblewrap's read-only rebind covers `<common>/config` and `<common>/hooks` only. Measured on
af26b72 (scratch toy repository, a linked worktree, the replays' bubblewrap stand-in and no
bubblewrap, main agent and subagent): the `git config` forms that name the key were already refused,
but a write onto the file passed the guard by a shell redirect, `tee`, `cp`, `mv`, `sed -i`, `ln`,
`dd`, `perl -pi` or `>|` (in place: every spelling; in --worktree mode: a path built from
`git rev-parse --git-dir`, and `ln`, `dd`, `truncate`, `rm`, `>|` with a literal one), the key
spelled with quotes, a variable or a substitution passed (`git config --worktree core.hooks"Path"`),
and a substitution in the command cut the invocation scanner off before the key
(`git config -f "$(git rev-parse --git-common-dir)/config" --unset core.hooksPath` removed the shared
keystone key with no bubblewrap). The guard now refuses all of these in every mode.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-overnight-hook-guard.py"
SID = "s-p28"
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}
STAND_IN = ROOT / "tests" / "replay" / "bin"  # the replays' bubblewrap stand-in
WHO = pytest.mark.parametrize("agent", [False, True], ids=["main agent", "subagent"])
# (isolation kind, a host with bubblewrap): the in-place launch needs bubblewrap
MODES = pytest.mark.parametrize("kind,bwrap", [("registered_worktree", False), ("registered_worktree", True),
                                               ("in_place", True)],
                                ids=["worktree no bwrap", "worktree bwrap", "in place bwrap"])


def _load_guard():
    sys.path.insert(0, str(ROOT / "hooks"))
    spec = importlib.util.spec_from_file_location("overnight_hook_guard_p28", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A product checkout with the keystone and `extensions.worktreeConfig` in its git config, and
    two linked worktrees of it (the session's own and another)."""
    main = tmp_path / "toy"
    main.mkdir()
    _git("init", "-q", "-b", "master", cwd=main)
    _git("config", "core.hooksPath", "/keystone-hooks", cwd=main)
    _git("config", "extensions.worktreeConfig", "true", cwd=main)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=main)
    _git("worktree", "add", "-q", "-b", "night-work", str(tmp_path / "wt"), cwd=main)
    _git("worktree", "add", "-q", "-b", "other-work", str(tmp_path / "other"), cwd=main)
    return main


def _state(main: Path, kind: str, sid: str = SID) -> Path:
    work = main if kind == "in_place" else main.parent / "wt"
    (main / ".claude").mkdir(exist_ok=True)
    (main / ".claude" / f"overnight-state-{sid}.json").write_text(json.dumps({
        "schema_version": 9, "session_id": sid, "isolation_kind": kind, "main_root": str(main),
        "main_git_dir": str(main / ".git"), "worktree_path": str(work), "worktree_branch": "night-work",
        "protected_branch": "master", "end_time": "2099-01-01T00:00:00Z",
        "isolation_active_until": "2099-01-01T00:00:00Z", "current_cycle": 1}))
    return work


def _hook(main: Path, tool: str, tool_input: dict, cwd: Path, agent: bool, bwrap: bool, session: str = SID):
    payload = {"session_id": session, "tool_name": tool, "tool_input": tool_input, "cwd": str(cwd),
               "transcript_path": str(main / "t.jsonl")}
    if agent:
        payload.update(agent_id="a1b2c3d4e5", agent_type="dev")
    env = {**os.environ, **GIT_ENV, "CLAUDE_PROJECT_DIR": str(main), "PWD": str(cwd), "CLAUDE_HOME": str(ROOT)}
    if bwrap:
        env["PATH"] = f"{STAND_IN}{os.pathsep}{env['PATH']}"
    else:
        env["CLAUDE_OVERNIGHT_FORCE_NO_BWRAP"] = "1"
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, cwd=cwd, timeout=120)


def _cfg(main: Path, kind: str) -> Path:
    """The per-worktree config file of the session's working root."""
    return main / ".git" / "config.worktree" if kind == "in_place" else \
        main / ".git" / "worktrees" / "wt" / "config.worktree"


def _refused_routes(main: Path, kind: str) -> list[str]:
    c = str(_cfg(main, kind))
    other = str(main / ".git" / "worktrees" / "other" / "config.worktree")
    gd = '"$(git rev-parse --git-dir)/config.worktree"'
    return [
        # the git config forms that write the file, with the key spelled out
        "git config --worktree core.hooksPath /dev/null",
        "git config --worktree --unset core.hooksPath",
        "git config --worktree --replace-all core.hooksPath /x",
        "git config --worktree include.path /tmp/x",
        f"git config --file {c} core.hooksPath /x",
        f"git config -f {c} --unset core.hooksPath",
        f"git config --file={c} include.path /tmp/x",
        f'git config -f {gd} core.hooksPath /x',
        # the key spelled so that the words are not the key's text
        'git config --worktree core.hooks"Path" /x',
        "git config --worktree core.hooksP\\ath /x",
        "K=core.hooksPath; git config --worktree $K /x",
        "git config --worktree $(echo core.hooksPath) /x",
        "git config --worktree `echo core.hooksPath` /x",
        'git config --worktree "$KEY" /x',
        # a substitution in the command cut the scanner off before the key
        'git config --file "$(git rev-parse --git-common-dir)/config" --unset core.hooksPath',
        'git config --local "$(echo core.hooksPath)" /dev/null',
        # a write onto the file by the shell
        f"printf '[core]\\n\\thooksPath = /x\\n' > {c}",
        f"printf x >> {c}",
        f"printf x >| {c}",
        f"printf x | tee {c}",
        f"printf x | tee -a {c}",
        f"cp /tmp/x {c}",
        f"mv /tmp/x {c}",
        f"sed -i 's/a/b/' {c}",
        f"perl -pi -e 's/a/b/' {c}",
        f"ln -sf /tmp/x {c}",
        f"printf x | dd of={c}",
        f"install /tmp/x {c}",
        f"truncate -s 0 {c}",
        f"rm -f {c}",
        f"exec 3> {c}",
        f"cat > {c} <<'EOF'\n[core]\n\thooksPath = /x\nEOF",
        f"python3 -c \"open('{c}','w').write('x')\"",
        f"cd {Path(c).parent} && printf x > config.worktree",
        f"cd {Path(c).parent} && printf x > 'config.work''tree'",
        f"printf x > {Path(c).parent}/config.w*",
        f"printf x > {other}",
        f"( printf x > {c} )",
        # the path built from git's own directory query
        'printf x > "$(git rev-parse --git-dir)/config.worktree"',
        'printf x > "$(git rev-parse --git-dir)"/config.w*',
        'printf x | tee "$(git rev-parse --git-dir)/config.worktree"',
        'cp /tmp/x "$(git rev-parse --git-dir)/config.worktree"',
        "sed -i 's/a/b/' \"$(git rev-parse --git-dir)/config.worktree\"",
        'printf x > "$(git rev-parse --git-common-dir)"/worktrees/*/config.worktree',
        'printf x > "$GIT_DIR/$NAME"',
        'cp /tmp/x `git rev-parse --absolute-git-dir`/$NAME',
    ]


@WHO
@MODES
def test_no_route_writes_the_per_worktree_config(repo, kind, bwrap, agent):
    work = _state(repo, kind)
    passed = []
    for command in _refused_routes(repo, kind):
        r = _hook(repo, "Bash", {"command": command}, work, agent, bwrap)
        if r.returncode != 2 or "OVERNIGHT" not in r.stderr or r.stdout.strip():
            passed.append((command, r.returncode, r.stdout[:60], r.stderr[:80]))
    assert not passed, passed


@WHO
@MODES
def test_the_write_and_edit_tools_cannot_write_it(repo, kind, bwrap, agent):
    work = _state(repo, kind)
    paths = [_cfg(repo, kind), repo / ".git" / "worktrees" / "other" / "config.worktree",
             repo / ".git" / "config.worktree",
             repo / ".git" / "worktrees" / "wt" / ".." / "wt" / "config.worktree",
             repo / ".git" / "worktrees" / "not-yet" / "config.worktree",   # its directory does not exist
             repo / ".git" / "worktrees" / "wt" / "CONFIG.WORKTREE"]
    link = repo.parent / "wt" / "innocent.txt"  # a path in the checkout that is a link to the file
    link.symlink_to(_cfg(repo, kind))
    paths.append(link)
    for target in paths:
        for tool, tool_input in (("Write", {"file_path": str(target), "content": "x"}),
                                 ("Edit", {"file_path": str(target), "old_string": "a", "new_string": "b"}),
                                 ("MultiEdit", {"file_path": str(target),
                                                "edits": [{"old_string": "a", "new_string": "b"}]})):
            r = _hook(repo, tool, tool_input, work, agent, bwrap)
            assert r.returncode == 2 and "OVERNIGHT" in r.stderr, (tool, str(target), r.returncode, r.stderr)


@WHO
@MODES
def test_reading_and_ordinary_config_work_still_passes(repo, kind, bwrap, agent):
    work = _state(repo, kind)
    c = str(_cfg(repo, kind))
    for command in ("git config --get core.hooksPath", "git config --list", "git config --worktree --list",
                    "git config --worktree --get core.hooksPath", f"git config --file {c} --list",
                    "git config get core.hooksPath", "git config user.name x",
                    'git config user.email "$(whoami)@example.invalid"', 'git config user.name "$NAME"',
                    'git config alias."$NAME" status', "git config --worktree user.name x",
                    "git config -f .gitmodules submodule.a.url https://example.invalid/a",
                    f"cat {c}", f"grep -n hooksPath {c}", f"ls -l {Path(c).parent}/config.worktree",
                    "echo 'the file config.worktree is per worktree' > notes.md",
                    'git commit -q --allow-empty -m "explain config.worktree"',
                    'git commit -q --allow-empty -m "the config is per worktree, see config.worktree"',
                    'cp notes.txt "$(git rev-parse --show-toplevel)/notes2.txt"',
                    'cd "$(git rev-parse --show-toplevel)" && ls', "X=$(git rev-parse --git-dir); echo $X",
                    "git rev-parse --git-dir", "git diff > patch.diff", "printf x | tee out.txt"):
        r = _hook(repo, "Bash", {"command": command}, work, agent, bwrap)
        assert r.returncode == 0, (command, r.stderr)


@pytest.mark.parametrize("kind", ["registered_worktree", "in_place"])
def test_a_session_that_is_not_overnight_is_not_held(repo, kind):
    _state(repo, kind)
    c = _cfg(repo, kind)
    r = _hook(repo, "Bash", {"command": f"printf x >> {c}"}, repo, False, True, session="s-someone-else")
    assert r.returncode == 0, r.stderr
    r = _hook(repo, "Write", {"file_path": str(c), "content": "x"}, repo, False, True, session="s-someone-else")
    assert r.returncode == 0, r.stderr


def test_the_premise_git_reads_the_hooks_path_of_the_per_worktree_file(repo):
    """What the guard protects: with extensions.worktreeConfig on, a core.hooksPath in the linked
    worktree's config.worktree is the one git uses there (and not in the main checkout)."""
    wt = repo.parent / "wt"
    assert _git("config", "--get", "core.hooksPath", cwd=wt) == "/keystone-hooks"
    _git("config", "--worktree", "core.hooksPath", "/elsewhere", cwd=wt)
    assert _cfg(repo, "registered_worktree").read_text().strip().endswith("hooksPath = /elsewhere")
    assert _git("config", "--get", "core.hooksPath", cwd=wt) == "/elsewhere"
    assert _git("config", "--get", "core.hooksPath", cwd=repo) == "/keystone-hooks"


def test_helpers_read_a_command_the_way_git_and_the_shell_do():
    g = _load_guard()
    assert g._neutralize_substitutions('a "$(git rev-parse --git-dir)/c" `x y` ${A:-b} k') \
        == 'a "$SUBST_git_rev_parse___git_dir/c" $SUBST_x_y $SUBST_A__b k'
    assert g._neutralize_substitutions("echo $(unclosed") == "echo $(unclosed"
    for key in ("core.hookspath", "include.path", "includeif.gitdir:/a/.path", "$k", "core.$k",
                "includeif.$d.path", "includeif.gitdir:$d"):
        assert g._key_may_be_keystone(key), key
    for key in ("user.name", "alias.$name", "core.autocrlf", "user.$field", "remote.origin.url"):
        assert not g._key_may_be_keystone(key), key
    assert g._names_worktree_config("'/x/.git/worktrees/w/config.work''tree'")
    assert g._names_worktree_config("/x/config.w*") and g._names_worktree_config("/x/config.[w]orktree")
    assert not g._names_worktree_config("/x/config") and not g._names_worktree_config("/x/config.*.bak")
