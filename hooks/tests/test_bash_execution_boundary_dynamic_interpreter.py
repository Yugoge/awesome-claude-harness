"""P2-6: an inline interpreter program whose word holds a shell expansion.

Before this fix, `python3 -c "import shutil; shutil.rmtree('$HOME/x')"` reached
the scoped `dynamic_interpreter_code` check, which refuses only when the raw
command carries an rm/unlink/shred/srm word. A library removal call carries
none, so the program text was never classified and the command was judged
proven inert, while its literal-path form was refused as
`interpreter_api_removal_not_proven_inert`.

The fix classifies the program's fixed text, each expansion replaced by a
placeholder, with the classifier the literal form uses, and fails closed where
an expansion could change the program itself rather than supply a value inside
one of its string literals.

ZERO EXECUTION: every command below is a string handed to the analyzer, or to
the hook as JSON on stdin with a scratch HOME. Nothing here runs a program.
Target paths are placeholders under a scratch directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "hooks", "lib"))

import bash_execution_boundary as eb  # noqa: E402

HOOK = os.path.join(REPO_ROOT, "hooks", "pretool-bash-safety.sh")
LITERAL_TARGET = "/tmp/p26-scratch/x"

# Per interpreter: (literal-path program, program with {T} for the target).
# The program text is classified, never run.
PROGRAMS = {
    "python3": ("-c", "import shutil; shutil.rmtree('{T}')"),
    "node": ("-e", "require('fs').rmSync('{T}',{{recursive:true}})"),
    "perl": ("-e", "use File::Path; rmtree('{T}')"),
    "ruby": ("-e", "require 'fileutils'; FileUtils.rm_rf('{T}')"),
}


def _program(interp, target):
    flag, body = PROGRAMS[interp]
    return flag, body.format(T=target)


def _spellings(interp):
    """Every spelling the item names, each built around one interpreter."""
    flag, home_braced = _program(interp, "${HOME}/x")
    _, home_plain = _program(interp, "$HOME/x")
    _, cmdsub = _program(interp, "$(pwd)/x")
    _, var = _program(interp, "$D/x")
    # Inside the single-quoted bash -c layer the program's own string quotes
    # become \" so the layer stays one word.
    _, layered = _program(interp, "$HOME/x")
    layered = layered.replace("'", '\\"')
    return {
        "braced_param": '%s %s "%s"' % (interp, flag, home_braced),
        "plain_param": '%s %s "%s"' % (interp, flag, home_plain),
        "command_substitution": '%s %s "%s"' % (interp, flag, cmdsub),
        "variable_set_earlier": 'D=/tmp/p26-scratch; %s %s "%s"' % (interp, flag, var),
        "wrapper_env": 'env %s %s "%s"' % (interp, flag, home_plain),
        "wrapper_sudo": 'sudo %s %s "%s"' % (interp, flag, home_plain),
        "wrapper_timeout": 'timeout 5 %s %s "%s"' % (interp, flag, home_plain),
        "attached_flag": '%s %s"%s"' % (interp, flag, home_plain),
        "bash_c_layer": "bash -c '%s %s \"%s\"'" % (interp, flag, layered),
    }


INTERPRETERS = ("python3", "node", "perl", "ruby")
SPELLINGS = sorted(_spellings("python3"))
DESTRUCTIVE = [(i, s, _spellings(i)[s]) for i in INTERPRETERS for s in SPELLINGS]

# Programs with an expansion that only print, read or compute.
INERT = [
    "python3 -c \"print('$HOME')\"",
    "python3 -c \"print(open('${HOME}/notes.txt').read())\"",
    "python3 -c \"import os; print(os.listdir('$HOME'))\"",
    "python3 -c \"print(len('$HOME') + 1)\"",
    "python3 -c\"print('$HOME')\"",
    "D=/tmp/p26-scratch; python3 -c \"print('$D')\"",
    "env python3 -c \"print('$HOME')\"",
    "node -e \"console.log('$HOME')\"",
    "perl -e \"print '$HOME'\"",
    "ruby -e \"puts '$HOME'\"",
]


def _literal_form(interp):
    flag, body = _program(interp, LITERAL_TARGET)
    return '%s %s "%s"' % (interp, flag, body)


@pytest.mark.parametrize("interp", INTERPRETERS)
def test_the_literal_form_is_refused(interp):
    result = eb.analyze(_literal_form(interp))
    assert result["allowed"] is False
    assert result["reason"].startswith("interpreter_api_removal_not_proven_inert")


@pytest.mark.parametrize("interp,spelling,command", DESTRUCTIVE,
                         ids=["%s-%s" % (i, s) for i, s, _ in DESTRUCTIVE])
def test_an_expansion_target_is_refused_like_the_literal_form(interp, spelling, command):
    result = eb.analyze(command)
    literal = eb.analyze(_literal_form(interp))
    assert result["allowed"] is False, command
    assert result["verdict"] == literal["verdict"], command
    assert result["reason"] == literal["reason"], command


@pytest.mark.parametrize("command", INERT)
def test_an_inert_program_with_an_expansion_stays_allowed(command):
    result = eb.analyze(command)
    assert result["allowed"] is True, (command, result["reason"])


@pytest.mark.parametrize("command,why", [
    ('python3 -c "$PROG"', "expansion_outside_string_literal"),
    ("python3 -c \"print('${HOME:-/tmp}')\"", "parameter_operator"),
    ("python3 -c \"print('$@')\"", "parameter_operator"),
    ("python3 -c \"print(f'{$X}')\"", "expansion_outside_string_literal"),
    ("P=\"$(cat f)\"; python3 -c \"print('$P')\"", "variable_set_in_command"),
])
def test_an_expansion_that_can_change_the_program_fails_closed(command, why):
    result = eb.analyze(command)
    assert result["allowed"] is False, command
    assert result["reason"] == "interpreter_expansion_changes_program:python3:" + why


def test_an_old_scoped_refusal_still_refuses():
    # The raw command carries an rm word: the scoped check refused this before
    # the fix, and it still must.
    result = eb.analyze("python3 -c \"import os; os.system('rm -rf $HOME/x')\"")
    assert result["allowed"] is False


# ── The real hook, for the main agent and a subagent ─────────────────────────

@pytest.fixture(scope="module")
def scratch_home(tmp_path_factory):
    return str(tmp_path_factory.mktemp("home"))


def _hook_exit(command, home, agent):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    if agent:
        payload.update({"agent_id": "p26-subagent", "agent_type": "dev"})
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": home}
    proc = subprocess.run(["bash", HOOK], input=json.dumps(payload), text=True,
                          capture_output=True, cwd=REPO_ROOT, env=env, timeout=120)
    return proc.returncode, proc.stderr


# node is left out of the hook replay: the protected-runtime guard refuses every
# `node -e` launch, with or without an expansion, on the base as well, so a node
# row would pass there for a reason unrelated to this item. The analyzer-level
# tests above cover node.
HOOK_INTERPRETERS = ("python3", "perl", "ruby")
HOOK_DESTRUCTIVE = [c for i, _s, c in DESTRUCTIVE if i in HOOK_INTERPRETERS]
HOOK_INERT = [c for c in INERT if not c.startswith("node ")]


@pytest.mark.parametrize("agent", [False, True], ids=["main", "subagent"])
@pytest.mark.parametrize("command", HOOK_DESTRUCTIVE)
def test_the_hook_refuses_the_expansion_forms(command, agent, scratch_home):
    code, err = _hook_exit(command, scratch_home, agent)
    assert code == 2, (command, err[:300])


@pytest.mark.parametrize("agent", [False, True], ids=["main", "subagent"])
@pytest.mark.parametrize("command", HOOK_INERT)
def test_the_hook_allows_the_inert_forms(command, agent, scratch_home):
    code, err = _hook_exit(command, scratch_home, agent)
    assert code == 0, (command, err[:300])
