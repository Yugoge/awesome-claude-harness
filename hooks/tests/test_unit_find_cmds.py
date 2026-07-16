#!/usr/bin/env python3
"""Direct-import unit tests for lib.runtime_guard.find_cmds.

Imports the find_cmds sibling module DIRECTLY (not via the _core facade) and
unit-tests its pure find/fd argv PARSERS in isolation: _find_path_operands,
_fd_positional_roots, _find_predicate_values, _glob_basenames,
_name_value_matches_protected. Crafted argv token lists in, parsed structure out
— NOT full evaluate() e2e.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(__file__)
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HOOKS_DIR)

from lib.runtime_guard import find_cmds  # noqa: E402  DIRECT module import


def test_module_identity():
    assert find_cmds.__name__ == "lib.runtime_guard.find_cmds"


# ── _find_path_operands ──────────────────────────────────────────────────────

def test_find_path_operands_basic():
    assert find_cmds._find_path_operands(["find", "/root", "-delete"], 0) == ["/root"]


def test_find_path_operands_skips_global_noarg_opts():
    assert find_cmds._find_path_operands(["find", "-L", "/root", "-delete"], 0) == ["/root"]


def test_find_path_operands_skips_prepath_arg_opts():
    assert find_cmds._find_path_operands(
        ["find", "-maxdepth", "1", "/root", "-delete"], 0) == ["/root"]


def test_find_path_operands_honors_dashdash():
    assert find_cmds._find_path_operands(["find", "--", "/root", "-delete"], 0) == ["/root"]


def test_find_path_operands_multiple_roots():
    assert find_cmds._find_path_operands(["find", "p1", "p2", "-delete"], 0) == ["p1", "p2"]


def test_find_path_operands_pathless_is_empty():
    # `find -delete` with no explicit path → [] (caller treats as implicit cwd).
    assert find_cmds._find_path_operands(["find", "-delete"], 0) == []


# ── _fd_positional_roots ─────────────────────────────────────────────────────

def test_fd_positional_roots_after_glob_value():
    # `fd -g <glob> /root ./sub -X rm` → search dirs are the path-like positionals.
    toks = ["fd", "-g", "*.mjs", "/root", "./sub", "-X", "rm"]
    assert find_cmds._fd_positional_roots(toks, 0) == ["/root", "./sub"]


def test_fd_positional_roots_bare_stem_excluded():
    # a bare pattern stem without a slash is the search pattern, not a search dir.
    toks = ["fd", "-g", "*.mjs", "stem", "-X", "rm"]
    assert find_cmds._fd_positional_roots(toks, 0) == []


def test_fd_positional_roots_stops_at_exec():
    # everything after -x/-X is the executed command, not a search dir.
    toks = ["fd", "pat", "/search", "-x", "rm", "/not-a-search-dir"]
    assert find_cmds._fd_positional_roots(toks, 0) == ["/search"]


# ── _find_predicate_values ───────────────────────────────────────────────────

def test_find_predicate_values_name_and_path():
    vals = list(find_cmds._find_predicate_values(
        ["find", "/root", "-name", "index.mjs", "-delete"], 0))
    assert ("name", "index.mjs", False) in vals

    vals = list(find_cmds._find_predicate_values(
        ["find", "/root", "-path", "/root/secret", "-delete"], 0))
    assert ("path", "/root/secret", False) in vals


def test_find_predicate_values_case_insensitive():
    vals = list(find_cmds._find_predicate_values(
        ["find", ".", "-iname", "INDEX.MJS", "-delete"], 0))
    assert ("name", "INDEX.MJS", True) in vals


def test_find_predicate_values_fused_form():
    vals = list(find_cmds._find_predicate_values(["find", ".", "-path=/a/b"], 0))
    assert ("path", "/a/b", False) in vals


def test_find_predicate_values_none_for_plain_find():
    assert list(find_cmds._find_predicate_values(["find", "/root", "-delete"], 0)) == []


# ── _glob_basenames ──────────────────────────────────────────────────────────

def test_glob_basenames_keeps_literal_drops_pure_wildcard():
    out = find_cmds._glob_basenames(["**/dist/index.mjs", "/usr/bin/happy*"])
    assert "index.mjs" in out
    assert "happy*" in out  # has a literal 'happy' component → retained
    # a pure-wildcard basename carries no literal component → dropped.
    assert find_cmds._glob_basenames(["some/dir/*"]) == set()


# ── _name_value_matches_protected ────────────────────────────────────────────

def test_name_value_literal_stem_equals_protected_basename():
    assert find_cmds._name_value_matches_protected("index.mjs", ["**/dist/index.mjs"]) is True


def test_name_value_case_insensitive():
    assert find_cmds._name_value_matches_protected(
        "INDEX.MJS", ["**/dist/index.mjs"], ignore_case=True) is True
    assert find_cmds._name_value_matches_protected(
        "INDEX.MJS", ["**/dist/index.mjs"], ignore_case=False) is False


def test_name_value_predicate_glob_selects_protected():
    # `-name 'index.*'` expands to the protected basename `index.mjs`.
    assert find_cmds._name_value_matches_protected("index.*", ["**/dist/index.mjs"]) is True


def test_name_value_pure_wildcard_and_nonmatch_are_false():
    # a pure-wildcard predicate matches nothing here (positional-root scan covers it).
    assert find_cmds._name_value_matches_protected("*", ["**/dist/index.mjs"]) is False
    assert find_cmds._name_value_matches_protected("other.txt", ["**/dist/index.mjs"]) is False
