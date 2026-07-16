#!/usr/bin/env python3
"""Direct-import unit tests for lib.runtime_guard.git_cmds.

Imports the git_cmds sibling module DIRECTLY (not via the _core facade) and
unit-tests its pure git argv PARSERS in isolation: _git_subcommand_index,
_git_effective_cwd, _strip_git_pathspec_magic, _git_destructive_pathspecs,
_git_is_destructive_invocation. Crafted argv token lists in, parsed structure /
predicate out — NOT full evaluate() e2e.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(__file__)
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HOOKS_DIR)

from lib.runtime_guard import git_cmds  # noqa: E402  DIRECT module import


def test_module_identity():
    assert git_cmds.__name__ == "lib.runtime_guard.git_cmds"


# ── _git_subcommand_index ────────────────────────────────────────────────────

def test_git_subcommand_index_plain():
    assert git_cmds._git_subcommand_index(["git", "status"], 0) == ("status", 1)


def test_git_subcommand_index_skips_global_opts_with_arg():
    assert git_cmds._git_subcommand_index(["git", "-C", "/dir", "clean"], 0) == ("clean", 3)
    assert git_cmds._git_subcommand_index(["git", "-c", "k=v", "log"], 0) == ("log", 3)


def test_git_subcommand_index_none_when_no_subcommand():
    assert git_cmds._git_subcommand_index(["git"], 0) == (None, None)


# ── _git_effective_cwd ───────────────────────────────────────────────────────

def test_git_effective_cwd_absolute_dashC():
    assert git_cmds._git_effective_cwd(["git", "-C", "/abs", "clean"], 0, None, True) == ("/abs", True)


def test_git_effective_cwd_dynamic_operand_marks_indeterminate():
    assert git_cmds._git_effective_cwd(["git", "-C", "$X", "clean"], 0, "/base", True) == ("/base", False)


def test_git_effective_cwd_no_dashC_passthrough():
    assert git_cmds._git_effective_cwd(["git", "clean"], 0, "/base", True) == ("/base", True)


# ── _strip_git_pathspec_magic ────────────────────────────────────────────────

def test_strip_pathspec_magic_plain():
    assert git_cmds._strip_git_pathspec_magic("a/b") == ("a/b", False, False, False)


def test_strip_pathspec_magic_top_is_repo_relative():
    assert git_cmds._strip_git_pathspec_magic(":(top)a") == ("a", True, False, False)
    assert git_cmds._strip_git_pathspec_magic(":/a") == ("a", True, False, False)


def test_strip_pathspec_magic_icase():
    assert git_cmds._strip_git_pathspec_magic(":(icase)a") == ("a", False, True, False)


def test_strip_pathspec_magic_exclude_forms():
    assert git_cmds._strip_git_pathspec_magic(":(exclude)a") == ("a", False, False, True)
    assert git_cmds._strip_git_pathspec_magic(":!a") == ("a", False, False, True)
    assert git_cmds._strip_git_pathspec_magic(":^a") == ("a", False, False, True)


def test_strip_pathspec_magic_combined():
    assert git_cmds._strip_git_pathspec_magic(":(top,glob,icase)x") == ("x", True, True, False)


def test_strip_pathspec_magic_bare_repo_root():
    # `:/` (repo-root with empty path) normalizes to '.'.
    assert git_cmds._strip_git_pathspec_magic(":/") == (".", True, False, False)


# ── _git_destructive_pathspecs ───────────────────────────────────────────────

def test_destructive_pathspecs_clean_explicit_paths():
    out = git_cmds._git_destructive_pathspecs(["git", "clean", "-fd", "a", "b"], 1, "clean")
    assert ("a", False, False, False) in out
    assert ("b", False, False, False) in out


def test_destructive_pathspecs_pathless_targets_cwd():
    # a path-less `git clean -fdx` targets the whole worktree → a single '.'.
    out = git_cmds._git_destructive_pathspecs(["git", "clean", "-fdx"], 1, "clean")
    assert out == [(".", False, False, False)]


def test_destructive_pathspecs_exclude_captured_with_positive():
    toks = ["git", "clean", "-fd", "--", ":!keep", "target"]
    out = git_cmds._git_destructive_pathspecs(toks, 1, "clean")
    assert ("keep", False, False, True) in out       # exclude flag preserved
    assert ("target", False, False, False) in out    # positive target present


def test_destructive_pathspecs_checkout_branch_not_a_pathspec():
    # `git checkout main` — the branch name is NOT a pathspec; fallback '.' only.
    out = git_cmds._git_destructive_pathspecs(["git", "checkout", "main"], 1, "checkout")
    assert out == [(".", False, False, False)]


# ── _git_is_destructive_invocation ───────────────────────────────────────────

def test_destructive_clean_requires_force():
    assert git_cmds._git_is_destructive_invocation(["git", "clean", "-fdx"], 1, "clean") is True
    assert git_cmds._git_is_destructive_invocation(["git", "clean", "-n"], 1, "clean") is False


def test_destructive_restore_always():
    assert git_cmds._git_is_destructive_invocation(["git", "restore", "x"], 1, "restore") is True


def test_destructive_reset_requires_hard():
    assert git_cmds._git_is_destructive_invocation(["git", "reset", "--hard"], 1, "reset") is True
    assert git_cmds._git_is_destructive_invocation(["git", "reset", "--soft"], 1, "reset") is False


def test_destructive_checkout_pathspec_vs_branch():
    assert git_cmds._git_is_destructive_invocation(["git", "checkout", "--", "."], 1, "checkout") is True
    assert git_cmds._git_is_destructive_invocation(["git", "checkout", "src/x"], 1, "checkout") is True
    # a plain branch switch is not a worktree-file wipe.
    assert git_cmds._git_is_destructive_invocation(["git", "checkout", "main"], 1, "checkout") is False
