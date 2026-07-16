#!/usr/bin/env python3
"""Direct-import unit tests for lib.runtime_guard.shell_lex.

Imports the shell_lex sibling module DIRECTLY (not via the _core facade's
evaluate() e2e path) and unit-tests its public lexing primitives in isolation:
_split_pipeline, _is_redirect_amp, _strip_compound_delims, _strip_quotes,
_safe_shlex, _has_redirect_to, _write_redirect_targets, _WRITE_REDIRECT_RE.

Mirrors the dual-context sys.path idiom of hooks/tests/test_runtime_guard.py
(sys.path.insert(HOOKS_DIR); import lib.runtime_guard) — here we reach the
submodule via the package so module identity is `lib.runtime_guard.shell_lex`.
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(__file__)
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HOOKS_DIR)

from lib.runtime_guard import shell_lex  # noqa: E402  DIRECT module import


def test_module_identity():
    assert shell_lex.__name__ == "lib.runtime_guard.shell_lex"


# ── _split_pipeline ──────────────────────────────────────────────────────────

def test_split_pipeline_basic_operators():
    assert shell_lex._split_pipeline("a && b | c") == ["a", "b", "c"]
    assert shell_lex._split_pipeline("echo a; echo b") == ["echo a", "echo b"]
    assert shell_lex._split_pipeline("a || b") == ["a", "b"]
    assert shell_lex._split_pipeline("a\nb") == ["a", "b"]


def test_split_pipeline_background_amp_splits():
    # a bare `&` (backgrounding) is a separator, not an fd redirect.
    assert shell_lex._split_pipeline("a & b") == ["a", "b"]


def test_split_pipeline_double_quote_protects_separators():
    assert shell_lex._split_pipeline('echo "a && b"') == ['echo "a && b"']
    assert shell_lex._split_pipeline("echo 'a | b; c'") == ["echo 'a | b; c'"]


def test_split_pipeline_command_substitution_not_split():
    # separators inside $(...) / `...` belong to the outer simple command.
    assert shell_lex._split_pipeline("echo $(a && b)") == ["echo $(a && b)"]
    assert shell_lex._split_pipeline("echo `a | b`") == ["echo `a | b`"]


def test_split_pipeline_fd_redirect_amp_not_separator():
    # `2>&1` and `>&2` contain `&` that is part of an fd redirect, not a split.
    assert shell_lex._split_pipeline("cmd 2>&1") == ["cmd 2>&1"]
    assert shell_lex._split_pipeline("cmd >&2") == ["cmd >&2"]


def test_split_pipeline_strips_and_drops_empty():
    assert shell_lex._split_pipeline("  a  ;  ; b ") == ["a", "b"]
    assert shell_lex._split_pipeline("") == []


# ── _is_redirect_amp ─────────────────────────────────────────────────────────

def test_is_redirect_amp_control_operator():
    # `&&` — the `&` at index 1 is followed by `&` → control operator, not redirect.
    assert shell_lex._is_redirect_amp("a && b", 2) is False


def test_is_redirect_amp_ampgt_forms():
    # `&>file` / `&>>file` — `&` followed by `>` is a redirect.
    assert shell_lex._is_redirect_amp("a &> f", 2) is True
    # `2>&1` — `&` followed by a digit is a redirect fd dup.
    s = "cmd 2>&1"
    assert shell_lex._is_redirect_amp(s, s.index("&")) is True


def test_is_redirect_amp_preceded_by_redirect_op():
    # `>&2` — `&` preceded by `>` (an fd-dup) is a redirect.
    s = "cmd >&2"
    assert shell_lex._is_redirect_amp(s, s.index("&")) is True


def test_is_redirect_amp_background_is_not_redirect():
    assert shell_lex._is_redirect_amp("a & b", 2) is False


# ── _strip_compound_delims ───────────────────────────────────────────────────

def test_strip_compound_delims_parens_become_separators():
    assert shell_lex._strip_compound_delims("(cd x && node y)") == " ; cd x && node y ; "


def test_strip_compound_delims_preserves_command_substitution():
    assert shell_lex._strip_compound_delims("echo $(a b)") == "echo $(a b)"


def test_strip_compound_delims_preserves_param_expansion():
    assert shell_lex._strip_compound_delims("x ${V}y") == "x ${V}y"


def test_strip_compound_delims_preserves_xargs_replstr_braces():
    # `-I{}` / trailing `{}` (xargs placeholder) must NOT be mangled.
    assert shell_lex._strip_compound_delims("xargs -I{} rm {}") == "xargs -I{} rm {}"


def test_strip_compound_delims_brace_group_words():
    # `{ cmd; }` standalone brace words ARE group delimiters → `;`.
    out = shell_lex._strip_compound_delims("{ echo a; }")
    assert "{" not in out and "}" not in out


# ── _strip_quotes ────────────────────────────────────────────────────────────

def test_strip_quotes():
    assert shell_lex._strip_quotes('"abc"') == "abc"
    assert shell_lex._strip_quotes("'abc'") == "abc"
    assert shell_lex._strip_quotes("abc") == "abc"
    assert shell_lex._strip_quotes('""') == ""
    # mismatched / partial quote is left intact
    assert shell_lex._strip_quotes('"a') == '"a'
    assert shell_lex._strip_quotes("'") == "'"


# ── _safe_shlex ──────────────────────────────────────────────────────────────

def test_safe_shlex_balanced():
    assert shell_lex._safe_shlex('echo "a b" c') == ["echo", "a b", "c"]


def test_safe_shlex_unbalanced_falls_back_to_whitespace_split():
    # unbalanced quote → shlex raises ValueError → whitespace-split fallback.
    assert shell_lex._safe_shlex('echo "unbalanced arg') == ["echo", '"unbalanced', "arg"]


# ── _has_redirect_to (legacy first-target probe) ─────────────────────────────

def test_has_redirect_to():
    assert shell_lex._has_redirect_to("echo x > out") == "out"
    assert shell_lex._has_redirect_to("echo x >> out2") == "out2"
    assert shell_lex._has_redirect_to("cat in") is None
    # fd-prefixed `2>` is intentionally NOT matched by the bare legacy probe.
    assert shell_lex._has_redirect_to("cmd 2> err") is None


# ── _write_redirect_targets / _WRITE_REDIRECT_RE ─────────────────────────────

def test_write_redirect_targets_all_forms():
    assert shell_lex._write_redirect_targets("echo x > /tmp/out") == ["/tmp/out"]
    assert shell_lex._write_redirect_targets("echo x >> a 2> b") == ["a", "b"]
    assert shell_lex._write_redirect_targets("echo x >| forced") == ["forced"]
    assert shell_lex._write_redirect_targets("cmd &> both") == ["both"]


def test_write_redirect_targets_ignores_read_redirect():
    # a read redirect `<` is never a write target.
    assert shell_lex._write_redirect_targets("cat < in") == []


def test_write_redirect_re_is_compiled_pattern():
    assert isinstance(shell_lex._WRITE_REDIRECT_RE, re.Pattern)
    assert shell_lex._WRITE_REDIRECT_RE.findall("echo x > out") == ["out"]
