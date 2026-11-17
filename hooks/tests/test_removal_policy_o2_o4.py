"""O2 and O4: the removal policy reads $'...' and comments as bash does.

Each command below was denied as UNRESOLVED because the census or the lexer
read an escaped quote inside $'...', or a quote inside a comment or an
unquoted heredoc body, as an open quote. Bash runs each of them. The verdict is
now the one their real commands earn: inert where nothing is removed, a
forbidden removal where `rm` runs. Strings bash itself rejects stay fatal.
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
sys.path.insert(0, HERE)

import bash_active_syntax_census as census_mod  # noqa: E402
import bash_execution_boundary as eb  # noqa: E402
import pol_replay_harness as H  # noqa: E402

CASES = [
    # O2: $'...' with an escaped quote
    ("git commit -m $'a\\'; b'", eb.PROVEN_INERT, 0),
    ("git commit -m $'fix(x): it\\'s a; b'", eb.PROVEN_INERT, 0),
    ("echo $'a\\'b' \"$(echo x)\"", eb.PROVEN_INERT, 0),
    ("git commit -m $'a\\'; b'; rm x", eb.FORBIDDEN_REMOVAL, 2),
    # O4: a quote inside a comment
    ("git commit -m a # don't", eb.PROVEN_INERT, 0),
    ("git commit -m a #it's", eb.PROVEN_INERT, 0),
    ("echo hi # don't", eb.PROVEN_INERT, 0),
    ("# it's\nls", eb.PROVEN_INERT, 0),
    ("rm x # ok\" $(y", eb.FORBIDDEN_REMOVAL, 2),
    # O4: a quote inside an unquoted heredoc body
    ("cat <<EOF\nit's\nEOF\n", eb.PROVEN_INERT, 0),
    ("cat <<EOF\nit's $(id)\nEOF\n", eb.PROVEN_INERT, 0),
    ("cat <<EOF\nit's $(rm x)\nEOF\n", eb.FORBIDDEN_REMOVAL, 2),
]


@pytest.mark.parametrize("command,verdict,_rc", CASES)
def test_analyzer_verdict(command, verdict, _rc):
    result = eb.analyze(command)
    assert result["verdict"] == verdict, result
    assert census_mod.census(command)["fatal"] == []


@pytest.mark.parametrize("command,_verdict,rc", CASES)
def test_hook_decision(command, _verdict, rc, tmp_path):
    code, _out, err = H.run_hook_command(command, env={**os.environ, "HOME": str(tmp_path)})
    if rc == 0:
        assert "removal-policy" not in err, err
    else:
        assert code == 2 and "removal-policy" in err, err


@pytest.mark.parametrize("command,fatal", [
    ("git commit -m $'a; b", "unbalanced:ansi_quote"),
    ("git commit -m a # don't\nrm x; echo '", "unbalanced:single_quote"),
    ("cat <<EOF\nx\n  EOF\n", "unterminated_heredoc"),
])
def test_what_bash_rejects_or_leaves_open_stays_fatal(command, fatal):
    assert fatal in census_mod.census(command)["fatal"]
    assert eb.analyze(command)["verdict"] == eb.UNRESOLVED
