#!/usr/bin/env python3
"""Direct-import unit tests for lib.runtime_guard.pathmatch.

Imports the pathmatch sibling module DIRECTLY (not via the _core facade) and
unit-tests its path-normalization + segment-boundary glob-matching primitives in
isolation: _normalize_path, _glob_to_segment_regex, _has_shell_glob,
_dir_equal_or_under, _path_matches_any, _path_under_any.

All path inputs are non-existent synthetic paths, so no ambient /tmp / realpath
state can perturb assertions (the exists()/realpath() branch only ever ADDS a
candidate, never for these inputs). HOME-dependent cases save/restore os.environ.
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(__file__)
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HOOKS_DIR)

from lib.runtime_guard import pathmatch  # noqa: E402  DIRECT module import


def test_module_identity():
    assert pathmatch.__name__ == "lib.runtime_guard.pathmatch"


# ── _normalize_path ──────────────────────────────────────────────────────────

def test_normalize_path_logical_collapse():
    assert pathmatch._normalize_path("a/../b") == "b"
    assert pathmatch._normalize_path("./a/b") == "a/b"
    assert pathmatch._normalize_path("/x/./y/../z") == "/x/z"


def test_normalize_path_strips_quotes():
    assert pathmatch._normalize_path('"/tmp/x"') == "/tmp/x"


def test_normalize_path_expands_leading_home():
    saved = os.environ.get("HOME")
    try:
        os.environ["HOME"] = "/home/testuser"
        assert pathmatch._normalize_path("$HOME/x") == "/home/testuser/x"
        assert pathmatch._normalize_path("${HOME}/y") == "/home/testuser/y"
        assert pathmatch._normalize_path("~") == "/home/testuser"
        # a mid-path or non-HOME var is NOT expanded.
        assert pathmatch._normalize_path("/a/$HOME/b") == "/a/$HOME/b"
    finally:
        if saved is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = saved


# ── _glob_to_segment_regex ───────────────────────────────────────────────────

def test_glob_to_segment_regex_returns_pattern():
    assert isinstance(pathmatch._glob_to_segment_regex("a/b"), re.Pattern)


def test_glob_segment_boundary_suffix_match():
    rx = pathmatch._glob_to_segment_regex("a/b")
    assert rx.search("a/b")
    assert rx.search("x/a/b")
    # segment boundary: `xa/b` is NOT a suffix match of `a/b`.
    assert not rx.search("xa/b")
    # trailing extra chars in the last segment do not match.
    assert not rx.search("a/bc")


def test_glob_star_within_segment():
    rx = pathmatch._glob_to_segment_regex("*.mjs")
    assert rx.search("index.mjs")
    assert rx.search("dir/index.mjs")
    assert not rx.search("index.mjsx")


def test_glob_doublestar_across_segments():
    rx = pathmatch._glob_to_segment_regex("**/dist/index.mjs")
    assert rx.search("a/b/dist/index.mjs")
    assert rx.search("dist/index.mjs")
    assert not rx.search("dist/index.js")


def test_glob_anchored_absolute():
    rx = pathmatch._glob_to_segment_regex("/usr/bin/x*")
    assert rx.search("/usr/bin/xyz")
    assert not rx.search("/opt/usr/bin/xyz")
    # `*` does not cross a path separator.
    assert not rx.search("/usr/bin/xyz/child")


# ── _has_shell_glob ──────────────────────────────────────────────────────────

def test_has_shell_glob():
    assert pathmatch._has_shell_glob("a*")
    assert pathmatch._has_shell_glob("a?")
    assert pathmatch._has_shell_glob("a[bc]")
    assert pathmatch._has_shell_glob("a{b,c}")
    assert not pathmatch._has_shell_glob("abc")
    assert not pathmatch._has_shell_glob("/tmp/plain/path")


# ── _dir_equal_or_under ──────────────────────────────────────────────────────

def test_dir_equal_or_under():
    assert pathmatch._dir_equal_or_under("/a/b", "/a") is True
    assert pathmatch._dir_equal_or_under("/a/b", "/a/b") is True
    # segment boundary: `/a/bc` is NOT under `/a/b`.
    assert pathmatch._dir_equal_or_under("/a/bc", "/a/b") is False
    # the parent is not under its own child.
    assert pathmatch._dir_equal_or_under("/a", "/a/b") is False


def test_dir_equal_or_under_root_special_case():
    # `/` is the ancestor of every ABSOLUTE path (find / -delete).
    assert pathmatch._dir_equal_or_under("/anything/here", "/") is True
    # a relative child is not "under" the filesystem root.
    assert pathmatch._dir_equal_or_under("rel/path", "/") is False


# ── _path_matches_any ────────────────────────────────────────────────────────

def test_path_matches_any_literal_and_suffix():
    assert pathmatch._path_matches_any("/usr/bin/happy", ["/usr/bin/happy"]) is True
    assert pathmatch._path_matches_any(
        "workspace/packages/x/dist/index.mjs", ["**/dist/index.mjs"]) is True
    assert pathmatch._path_matches_any("/tmp/scratch", ["**/dist/index.mjs"]) is False


def test_path_matches_any_command_side_glob_selects_protected():
    # `mv /a/dir/* dst` — the `/a/dir/*` token expands to select the protected
    # file `/a/dir/secret` that lives directly under the glob-parent.
    assert pathmatch._path_matches_any("/a/dir/*", ["/a/dir/secret"]) is True
    # a glob whose parent selects nothing protected does not match.
    assert pathmatch._path_matches_any("/tmp/scratch/*", ["/a/dir/secret"]) is False


# ── _path_under_any ──────────────────────────────────────────────────────────

def test_path_under_any():
    assert pathmatch._path_under_any(
        "packages/pkg/tsconfig.json", ["**/packages/pkg"]) is True
    assert pathmatch._path_under_any(
        "/tmp/other/file", ["**/packages/pkg"]) is False
