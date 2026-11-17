#!/usr/bin/env python3
"""Unit tests for how the runtime guard reads a command through the shared parser.

The guard splits a command into pipeline groups of simple commands, tokenizes each
simple command and reads its write-redirect targets with `hooks/lib/shell_parse.py`
(`_pipeline_groups`, `_safe_shlex`, `_write_redirect_targets` in
`lib.runtime_guard._core`); `_strip_quotes` lives in `lib.runtime_guard.pathmatch`.
Each case below is a reading the guard's decisions depend on.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(__file__)
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HOOKS_DIR)

from lib.runtime_guard import _core  # noqa: E402
from lib.runtime_guard.pathmatch import _strip_quotes  # noqa: E402


def flat(command):
    return [sc for g in _core._pipeline_groups(command) for sc in g]


# ── simple commands ──────────────────────────────────────────────────────────

def test_split_on_control_operators():
    assert flat("a && b | c") == ["a", "b", "c"]
    assert flat("echo a; echo b") == ["echo a", "echo b"]
    assert flat("a || b") == ["a", "b"]
    assert flat("a\nb") == ["a", "b"]


def test_background_ampersand_splits():
    assert flat("a & b") == ["a", "b"]


def test_quoted_separators_do_not_split():
    assert flat('echo "a && b"') == ['echo "a && b"']
    assert flat("echo 'a | b; c'") == ["echo 'a | b; c'"]


def test_substitutions_stay_in_their_command():
    assert flat("echo $(a && b)") == ["echo $(a && b)"]
    assert flat("echo `a | b`") == ["echo `a | b`"]


def test_fd_redirections_are_not_separators():
    assert flat("cmd 2>&1") == ["cmd 2>&1"]
    assert flat("cmd >&2") == ["cmd >&2"]
    assert flat("cmd &> f") == ["cmd &> f"]
    assert flat("echo x >| f") == ["echo x >| f"]


def test_empty_commands_dropped():
    assert flat("  a  ;  b ") == ["a", "b"]
    assert flat("") == []


def test_compound_groups_decompose_into_their_commands():
    assert flat("(cd x && node y)") == ["cd x", "node y"]
    assert flat("{ echo a; }") == ["echo a"]
    assert flat("xargs -I{} rm {}") == ["xargs -I{} rm {}"]
    assert flat("x ${V}y") == ["x ${V}y"]


def test_compound_redirect_is_a_segment_of_its_own():
    assert flat("{ echo a; } > out") == ["echo a", "> out"]


def test_pipe_connects_a_group_and_a_loop_it_feeds():
    assert _core._pipeline_groups("pgrep x | while read p; do kill $p; done; ls") == [
        ["pgrep x", "read p", "kill $p"], ["ls"]]


def test_unquoted_heredoc_expansion_is_read_quoted_body_is_data():
    assert flat("cat <<EOF\n$(rm x)\nEOF") == ["cat <<EOF", "rm x"]
    assert flat("cat <<'EOF'\n$(rm x)\nEOF") == ["cat <<'EOF'"]


def test_text_after_a_parse_error_is_kept():
    assert flat('ls; echo "unbalanced arg') == ["ls", 'echo "unbalanced arg']


# ── _strip_quotes ────────────────────────────────────────────────────────────

def test_strip_quotes():
    assert _strip_quotes('"abc"') == "abc"
    assert _strip_quotes("'abc'") == "abc"
    assert _strip_quotes("abc") == "abc"
    assert _strip_quotes('""') == ""
    assert _strip_quotes('"a') == '"a'
    assert _strip_quotes("'") == "'"


# ── _safe_shlex ──────────────────────────────────────────────────────────────

def test_safe_shlex_balanced():
    assert _core._safe_shlex('echo "a b" c') == ["echo", "a b", "c"]


def test_safe_shlex_unbalanced_falls_back_to_whitespace_split():
    assert _core._safe_shlex('echo "unbalanced arg') == ["echo", '"unbalanced', "arg"]


def test_safe_shlex_keeps_expansions_and_splits_redirects():
    assert _core._safe_shlex('cp "$DEST" ${HOME}/y >out') == ["cp", "$DEST", "${HOME}/y", ">", "out"]
    assert _core._safe_shlex("X=1 cmd 2>&1") == ["X=1", "cmd", "2>&", "1"]


# ── _write_redirect_targets ──────────────────────────────────────────────────

def test_write_redirect_targets_all_forms():
    assert _core._write_redirect_targets("echo x > /tmp/out") == ["/tmp/out"]
    assert _core._write_redirect_targets("echo x >> a 2> b") == ["a", "b"]
    assert _core._write_redirect_targets("echo x >| forced") == ["forced"]
    assert _core._write_redirect_targets("cmd &> both") == ["both"]
    assert _core._write_redirect_targets("echo x>out") == ["out"]


def test_write_redirect_targets_ignores_reads_and_fd_duplication():
    assert _core._write_redirect_targets("cat < in") == []
    assert _core._write_redirect_targets("cmd 2>&1 >&2") == []
