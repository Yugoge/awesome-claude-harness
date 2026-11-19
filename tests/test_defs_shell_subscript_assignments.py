"""An array assignment whose subscript holds a blank, an operator, quotes or a newline is one
assignment word where bash accepts an assignment (before a command's name), as bash reads it.

bash reads `m[a b]=c` as an assignment to m["a b"], `m[a b] echo hi` as a command named
`m[a b]`, and `echo m[a b]=c` / `declare m[a b]=c` as two words; an unclosed `x[` there is a
syntax error ("looking for matching `]'"). shell_parse read `m[a b]=c` as a command `m[a`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / "hooks"
sys.path[:0] = [str(HOOKS), str(HOOKS / "lib")]

from lib import shell_parse as sp  # noqa: E402

# command -> [(assignment words, command words)] per simple command, as bash reads it
CASES = [
    ("m[a b]=c", [(["m[a b]=c"], [])]),
    ("m[a b]+=c", [(["m[a b]+=c"], [])]),
    ("m[$i + 1]=x", [(["m[$i + 1]=x"], [])]),
    ("m[a|b]=1; ls", [(["m[a|b]=1"], []), ([], ["ls"])]),
    ('m[a "]" b]=1; ls', [(['m[a "]" b]=1'], []), ([], ["ls"])]),
    ("m['x]y']=1; ls", [(["m['x]y']=1"], []), ([], ["ls"])]),
    ("m[$(echo k l)]=w", [(["m[$(echo k l)]=w"], []), ([], ["echo", "k", "l"])]),
    ("m[a\nb]=1; ls", [(["m[a\nb]=1"], []), ([], ["ls"])]),
    ("m[a]=1 n[b c]=2 echo hi", [(["m[a]=1", "n[b c]=2"], ["echo", "hi"])]),
    ("m[a b]=1 && rm -rf x", [(["m[a b]=1"], []), ([], ["rm", "-rf", "x"])]),
    ("if m[a b]=1; then :; fi", [(["m[a b]=1"], []), ([], [":"])]),
    ("m[a b] echo hi", [([], ["m[a b]", "echo", "hi"])]),
    ("echo m[a b]=c", [([], ["echo", "m[a", "b]=c"])]),
    ("declare m[a b]=c", [([], ["declare", "m[a", "b]=c"])]),
    ("ls [abc] x[1]", [([], ["ls", "[abc]", "x[1]"])]),
]


@pytest.mark.parametrize("command,expected", CASES, ids=[c[0] for c in CASES])
def test_a_subscript_assignment_is_read_as_bash_reads_it(command, expected):
    script = sp.parse(command)
    assert script.error is None
    got = [([a.word.raw.text for a in c.assignments], [w.raw.text for w in c.words])
           for c in sp.iter_commands(script)]
    assert got == expected


@pytest.mark.parametrize("command", ["x[ echo hi; echo after", "FOO=1 bar[ x"])
def test_an_unclosed_subscript_where_an_assignment_stands_is_an_error(command):
    assert sp.parse(command).error is not None


@pytest.mark.skipif(shutil.which("bash") is None, reason="no bash")
@pytest.mark.parametrize("assignment,key", [
    ("m[a b]=c", "a b"), ("m[a b]+=c", "a b"), ('m[a "]" b]=1', "a ] b"),
    ("m['x]y']=1", "x]y"), ("m[$(echo k l)]=w", "k l"),
])
def test_bash_assigns_these(assignment, key):
    out = subprocess.run(["bash", "-c", 'declare -A m; %s; printf "%%s" "${!m[@]}"' % assignment],
                         capture_output=True, text=True, timeout=30)
    assert out.stdout == key
