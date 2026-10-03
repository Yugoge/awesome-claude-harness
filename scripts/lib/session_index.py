#!/usr/bin/env python3
"""Per-session private git index: the one mechanism staging and commit paths use.

A repository has exactly one shared index file (``$GIT_DIR/index``). Every session
that stages or commits in a worktree writes to it, so one session's pre-staging
check can unstage a peer's staged files, and a commit can pick up bytes staged by
a peer. Giving each session its own index file removes that contention point with
no lock and no queue: a session only reads and writes its own index.

Layout (per worktree git dir)::

    <git-dir>/session-indexes/<session-key>.index       the private index
    <git-dir>/session-indexes/<session-key>.index.base  HEAD sha it was seeded from
                                                        (empty for an unborn HEAD)

Fail-closed contract. A missing session key, a missing or corrupt private index,
or a HEAD that moved since seeding raises ``SessionIndexError``. Nothing falls
back to the shared index, and nothing seeds the private index implicitly except
an explicit ``init``.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Dict, Mapping, Optional

SESSION_ENV_KEYS = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID")
INDEX_DIR_NAME = "session-indexes"
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class SessionIndexError(RuntimeError):
    """Explicit refusal. ``reason`` is a stable slug; ``detail`` is for humans."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__("%s: %s" % (reason, detail))
        self.reason = reason
        self.detail = detail


def _run(args, cwd, env=None, input_bytes=None):
    return subprocess.run(
        ["git", "-C", cwd] + list(args),
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def _private_env(index: str) -> Dict[str, str]:
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = index
    return env


def _shared_env() -> Dict[str, str]:
    # Strip any inherited GIT_INDEX_FILE so the call really addresses the shared index.
    env = dict(os.environ)
    env.pop("GIT_INDEX_FILE", None)
    return env


def session_key(environ: Optional[Mapping[str, str]] = None) -> str:
    """Return this session's key. No default: an absent key is an explicit error."""
    env = os.environ if environ is None else environ
    for name in SESSION_ENV_KEYS:
        value = (env.get(name) or "").strip()
        if value:
            if not _KEY_RE.match(value):
                raise SessionIndexError(
                    "session_key_invalid",
                    "%s contains characters outside [A-Za-z0-9._-]" % name)
            return value
    raise SessionIndexError(
        "session_key_missing",
        "neither CLAUDE_CODE_SESSION_ID nor CLAUDE_SESSION_ID is set")


def _absolute_git_dir(git_root: str) -> str:
    proc = _run(["rev-parse", "--absolute-git-dir"], git_root, env=_shared_env())
    if proc.returncode != 0:
        raise SessionIndexError(
            "not_a_repository", proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout.decode("utf-8", "replace").strip()


def index_path(git_root: str, key: Optional[str] = None) -> str:
    key = session_key() if key is None else key
    return os.path.join(_absolute_git_dir(git_root), INDEX_DIR_NAME, key + ".index")


def _base_path(index: str) -> str:
    return index + ".base"


def head_sha(git_root: str) -> str:
    """HEAD commit sha, or '' when HEAD is unborn."""
    proc = _run(["rev-parse", "--verify", "-q", "HEAD^{commit}"], git_root,
                env=_shared_env())
    return proc.stdout.decode("utf-8", "replace").strip() if proc.returncode == 0 else ""


def _read_base(index: str) -> str:
    with open(_base_path(index), "r", encoding="utf-8") as fh:
        return fh.read().strip()


def _write_atomic(path: str, text: str) -> None:
    tmp = "%s.tmp-%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def init(git_root: str, key: Optional[str] = None) -> str:
    """Seed this session's private index from HEAD and record the base.

    Always re-seeds: a commit run must start from the HEAD it will commit onto.
    The seed is HEAD (or the empty tree when unborn), never the shared index,
    so no peer's staged bytes can enter this session's index.
    """
    index = index_path(git_root, key)
    os.makedirs(os.path.dirname(index), exist_ok=True)
    head = head_sha(git_root)
    tmp = "%s.tmp-%d" % (index, os.getpid())
    args = ["read-tree", head] if head else ["read-tree", "--empty"]
    proc = _run(args, git_root, env=_private_env(tmp))
    if proc.returncode != 0:
        _unlink_quiet(tmp)
        raise SessionIndexError(
            "seed_failed", proc.stderr.decode("utf-8", "replace").strip())
    os.replace(tmp, index)
    _write_atomic(_base_path(index), head + "\n")
    return index


def _unlink_quiet(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def verify(git_root: str, key: Optional[str] = None) -> str:
    """Prove the private index exists, is seeded, and parses. Return its path.

    A zero-byte or garbled file is reported as ``index_corrupt`` by git itself;
    a missing file is reported here as ``index_missing`` (git would otherwise
    treat a missing index as empty and happily report every HEAD path as deleted).
    """
    index = index_path(git_root, key)
    if not os.path.isfile(index):
        raise SessionIndexError(
            "index_missing",
            "no private index at %s; run `session-index.py init` first" % index)
    if not os.path.isfile(_base_path(index)):
        raise SessionIndexError(
            "base_missing", "private index %s has no .base sidecar; re-run init" % index)
    proc = _run(["ls-files", "--stage"], git_root, env=_private_env(index))
    if proc.returncode != 0:
        raise SessionIndexError(
            "index_corrupt",
            "git cannot read %s: %s" % (index, proc.stderr.decode("utf-8", "replace").strip()))
    return index


def commit_gate(git_root: str, key: Optional[str] = None) -> Dict[str, str]:
    """Pre-commit gate: verify the private index and that HEAD has not moved.

    Returns the environment to run `git commit` with. A moved HEAD means the
    private index would commit a tree that reverts the intervening commits, so
    it is refused rather than committed.
    """
    index = verify(git_root, key)
    base = _read_base(index)
    head = head_sha(git_root)
    if head != base:
        raise SessionIndexError(
            "head_moved",
            "HEAD is %s but the private index was seeded from %s; re-run init and re-stage"
            % (head or "<unborn>", base or "<unborn>"))
    return _private_env(index)


def _tree_entry(git_root: str, rev: str, path: str):
    proc = _run(["ls-tree", "-z", rev, "--", path], git_root, env=_shared_env())
    if proc.returncode != 0 or not proc.stdout:
        return None
    meta, _, _ = proc.stdout.rstrip(b"\0").partition(b"\t")
    mode, kind, sha = meta.decode("utf-8", "replace").split()
    return (mode, sha) if kind == "blob" else None


def _shared_entry(git_root: str, path: str):
    proc = _run(["ls-files", "--stage", "-z", "--", path], git_root, env=_shared_env())
    if proc.returncode != 0 or not proc.stdout:
        return None
    meta, _, _ = proc.stdout.rstrip(b"\0").partition(b"\t")
    mode, sha, stage = meta.decode("utf-8", "replace").split()
    return (mode, sha) if stage == "0" else "conflicted"


def _empty_tree(git_root: str) -> str:
    proc = _run(["mktree"], git_root, env=_shared_env(), input_bytes=b"")
    return proc.stdout.decode("utf-8", "replace").strip()


def sync_shared_after_commit(git_root: str, key: Optional[str] = None) -> Dict[str, list]:
    """Bring the shared index's entries for committed paths up to the new HEAD.

    The private-index commit moves HEAD but not the shared index. Left alone, the
    shared index would still hold the pre-commit blobs, and `git status` would show
    the commit as reverted (and a plain `git commit` would revert it). For each path
    the commit touched, the shared entry is moved to the committed blob only when it
    still equals the pre-commit entry. A path that a peer has staged in the shared
    index is left alone and reported, never overwritten.
    """
    index = index_path(git_root, key)
    base = _read_base(index)
    new = head_sha(git_root)
    report: Dict[str, list] = {"synced": [], "left_foreign": [], "unchanged": []}
    if not new or new == base:
        return report
    old_tree = _run(["rev-parse", "%s^{tree}" % base], git_root, env=_shared_env()) \
        if base else None
    old_rev = old_tree.stdout.decode().strip() if old_tree and old_tree.returncode == 0 \
        else _empty_tree(git_root)
    diff = _run(["diff-tree", "-r", "--no-renames", "--name-only", "-z", old_rev,
                 "%s^{tree}" % new], git_root, env=_shared_env())
    if diff.returncode != 0:
        raise SessionIndexError(
            "sync_failed", diff.stderr.decode("utf-8", "replace").strip())
    paths = [p.decode("utf-8", "surrogateescape")
             for p in diff.stdout.split(b"\0") if p]
    for path in paths:
        before = _tree_entry(git_root, base or old_rev, path)
        after = _tree_entry(git_root, new, path)
        current = _shared_entry(git_root, path)
        if current == after:
            report["unchanged"].append(path)
            continue
        if current != before:
            report["left_foreign"].append(path)
            continue
        if after is None:
            _run(["update-index", "--force-remove", "--", path], git_root, env=_shared_env())
        else:
            mode, sha = after
            proc = _run(["update-index", "--add", "--cacheinfo",
                         "%s,%s,%s" % (mode, sha, path)], git_root, env=_shared_env())
            if proc.returncode != 0:
                raise SessionIndexError(
                    "sync_failed", proc.stderr.decode("utf-8", "replace").strip())
        report["synced"].append(path)
    return report
