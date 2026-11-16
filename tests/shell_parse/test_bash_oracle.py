"""The parser never finds fewer commands than bash runs.

bash runs each generated command with an empty PATH and a
command_not_found_handle that prints one line, so every command it would run is
counted and nothing real runs; it runs in a scratch directory with no stdin.
The fragments cover the readings consumer lanes found missing: substitutions
inside ${...} and arithmetic, brace groups, line continuations, compound
commands and heredocs.
"""

import random
import re
import shutil
import subprocess
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                "hooks", "lib"))
import shell_parse as sp  # noqa: E402

FRAGMENTS = ["x ", "y", " ", "q", ";", "&&", "||", "|", "\n", '"', "'", "$'", "\\", "\\\\", "\\\n", "#", " #",
             "$(x)", "`y`", "${Z:-$(q)}", "$(( $(x) + 1 ))", "{ x; }", "( y )", "; ", " && ", " | ",
             "<<EOF\nq $(x)\nEOF\n", "<<'EOF'\nq\nEOF\n", "for i in 1; do x; done", "if x; then y; fi",
             "eval 'q'", "<<< w ", "$[1]", "\\;", "{a,b}", "a=1 "]


def _reserved(bash):
    out = subprocess.run([bash, "-c", "compgen -b; compgen -k"], capture_output=True, text=True,
                         timeout=10, stdin=subprocess.DEVNULL, env={"PATH": ""}).stdout
    return set(out.split()) - {"eval"}


def _ran(bash, command, empty, work):
    harness = "command_not_found_handle(){ echo C; return 0; }\n"
    try:
        done = subprocess.run([bash, "-c", harness + command], capture_output=True, text=True, timeout=10,
                              stdin=subprocess.DEVNULL, cwd=work,
                              env={"PATH": str(empty), "LC_ALL": "C", "HOME": str(work)})
    except subprocess.TimeoutExpired:
        return None
    return done.stdout.count("C\n")


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash as the oracle")
def test_walk_reaches_every_command_bash_runs(tmp_path):
    bash = shutil.which("bash")
    empty, work = tmp_path / "no-programs", tmp_path / "work"
    empty.mkdir()
    work.mkdir()
    reserved = _reserved(bash)
    rnd = random.Random(20261116)
    checked = 0
    for _ in range(2500):
        command = "".join(rnd.choice(FRAGMENTS) for _ in range(rnd.randint(1, 8)))
        words = set(re.split(r"[\s;&|<>#(){}$`]+", re.sub(r"[\"'\\]", "", command)))
        if words & reserved or subprocess.run([bash, "-n", "-c", command], capture_output=True, cwd=work,
                                              env={"PATH": str(empty)}).returncode != 0:
            continue
        ran = _ran(bash, command, empty, work)
        if ran is None:
            continue
        checked += 1
        script = sp.parse(command)
        assert script.error is None or script.error.code == "unterminated_heredoc", (command, script.error)
        assert len(list(sp.walk(script))) >= ran, repr(command)
    assert checked > 300, checked
