"""Freeze safe grep shapes and the catastrophic embedded-engine control."""

import importlib.util
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "hooks/pretool-grep-backtrack-guard.py"
SPEC = importlib.util.spec_from_file_location("grep_backtrack_guard", PATH)
GUARD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(GUARD)


def _run(monkeypatch, command):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    monkeypatch.setattr(GUARD.sys, "stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc:
        GUARD.main()
    return exc.value.code


@pytest.mark.parametrize(
    "command",
    (
        "grep -E 'bounded.{0,10}value' README.md",
        "/usr/bin/grep -E 'a.*b.*c' README.md",
        "grep -F 'a.*b.*c' README.md",
    ),
)
def test_safe_current_controls_allow_without_probe(monkeypatch, command):
    monkeypatch.setattr(GUARD, "probe_explodes", lambda *a: (_ for _ in ()).throw(AssertionError()))
    assert _run(monkeypatch, command) == 0


def test_catastrophic_shape_blocks_when_same_engine_probe_explodes(monkeypatch):
    monkeypatch.setattr(GUARD, "probe_explodes", lambda *a: True)
    assert _run(monkeypatch, "grep -E 'a.*b.*c' README.md") == 2


BOMB = "grep -E 'a.*b.*c' f"


def _shape_probe(monkeypatch):
    monkeypatch.setattr(GUARD, "probe_explodes", lambda pattern, mode: True)


@pytest.mark.parametrize(
    "command",
    (
        BOMB,
        "x=$(%s)" % BOMB,
        'echo "$(%s)"' % BOMB,
        "x=`%s`" % BOMB,
        'echo "`%s`"' % BOMB,
        "echo $(echo $(%s))" % BOMB,
        "cat <(%s)" % BOMB,
        "tee >(%s)" % BOMB,
        'eval "%s"' % BOMB,
        "eval %s" % BOMB,
        'command eval "%s"' % BOMB,
        'bash -c "%s"' % BOMB,
        'sh -xc "%s"' % BOMB,
        'eval "bash -c \\"%s\\""' % BOMB,
        "bash <<EOF\n%s\nEOF" % BOMB,
        "echo hi; %s" % BOMB,
        "echo hi && %s" % BOMB,
        "ls | %s" % BOMB,
        "echo hi\n%s" % BOMB,
        "true &\n%s" % BOMB,
        "f() { %s; }" % BOMB,
        "case x in x) %s;; esac" % BOMB,
        "if true; then %s; fi" % BOMB,
        "echo hi | while read l; do %s; done" % BOMB,
        "( %s )" % BOMB,
        "{ %s; }" % BOMB,
        "time %s" % BOMB,
        "! %s" % BOMB,
        "FOO=1 %s" % BOMB,
        "coproc %s" % BOMB,
        "\\%s" % BOMB,
        "egrep 'a.*b.*c' f",
        "ugrep -E 'a.*b.*c' f",
        "grep 'a.*b.*c' f",
        "grep -P 'a.*b.*c' f",
        "grep -e x -e 'a.*b.*c' f",
        "grep -Ee'a.*b.*c' f",
        "grep --regexp='a.*b.*c' f",
        "grep -A 3 -E 'a.*b.*c' f",
        "grep -f pats -E 'a.*b.*c' f",
        "grep -E $'a.\\x2a b.*c' f",
        "grep -E \"a.*b.*c\" f",
        "grep -E a.\\*b.\\*c f",
    ),
)
def test_a_search_that_reaches_the_embedded_engine_is_probed(monkeypatch, command):
    _shape_probe(monkeypatch)
    assert _run(monkeypatch, command) == 2


@pytest.mark.parametrize(
    "command",
    (
        "grep -E 'abc' f",
        "fgrep 'a.*b.*c' f",
        "grep -F 'a.*b.*c' f",
        "/usr/bin/" + BOMB,
        "./" + BOMB,
        "env " + BOMB,
        "env FOO=1 " + BOMB,
        "nice " + BOMB,
        "xargs " + BOMB,
        "command " + BOMB,
        "builtin " + BOMB,
        "sudo " + BOMB,
        "nohup " + BOMB,
        "exec " + BOMB,
        "exec -a foo " + BOMB,
        '/bin/bash -c "%s"' % BOMB,
        "cat <<EOF\n%s\nEOF" % BOMB,
        "cat <<'EOF'\n%s\nEOF" % BOMB,
        "# " + BOMB,
        "echo hi # " + BOMB,
        "echo '%s'" % BOMB,
        "echo \"grep -E a.*b.*c f\"",
        "ls -la",
    ),
)
def test_a_command_that_does_not_reach_the_embedded_engine_is_allowed(monkeypatch, command):
    _shape_probe(monkeypatch)
    assert _run(monkeypatch, command) == 0


@pytest.mark.parametrize(
    "command",
    (
        "exec -a ugrep /bin/x -E 'a.*b.*c' f",
        "ARGV0=ugrep /bin/x -E 'a.*b.*c' f",
    ),
)
def test_the_direct_embedded_engine_launchers_are_probed(monkeypatch, command):
    _shape_probe(monkeypatch)
    assert _run(monkeypatch, command) == 2


@pytest.mark.parametrize("command", ("grep -E 'a.*b.*c f", "echo \"unterminated; " + BOMB))
def test_a_command_the_guard_cannot_read_is_let_through(monkeypatch, command):
    _shape_probe(monkeypatch)
    assert _run(monkeypatch, command) == 0


def test_every_pattern_of_a_multi_pattern_search_is_probed(monkeypatch):
    seen = []
    monkeypatch.setattr(GUARD, "probe_explodes", lambda pattern, mode: seen.append((pattern, mode)) or False)
    assert _run(monkeypatch, "grep -e 'x.*y.*z' -e 'a.*b.*c' f") == 0
    assert sorted(seen) == [("a.*b.*c", "G"), ("x.*y.*z", "G")]


@pytest.mark.parametrize(
    "command, mode",
    (("grep -E 'a.*b.*c' f", "E"), ("grep -riP 'a.*b.*c' f", "P"), ("egrep -G 'a.*b.*c' f", "G"),
     ("grep -nEe'a.*F.*c' f", "E")),
)
def test_the_probe_runs_in_the_mode_the_command_uses(monkeypatch, command, mode):
    seen = []
    monkeypatch.setattr(GUARD, "probe_explodes", lambda pattern, m: seen.append(m) or False)
    _run(monkeypatch, command)
    assert seen == [mode]


def test_a_probe_infrastructure_error_lets_the_command_through(monkeypatch):
    def broken(pattern, mode):
        raise RuntimeError("no systemd-run")
    monkeypatch.setattr(GUARD, "probe_explodes", broken)
    assert _run(monkeypatch, BOMB) == 0
