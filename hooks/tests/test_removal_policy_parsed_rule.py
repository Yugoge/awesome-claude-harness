"""The removal rule decides from the parsed command, not from words found anywhere in its text (owner, 2026-11-19).

"Only a removal program in a position where it would be executed counts, and removal calls in Python that will be
executed. Text written to a file, search words and variable names never count." On the primary path the analyzer
refuses every removal it sees where it would run; the word list (lib/pol_degraded_removal_reference.ere) is asked
only of the text that can become a command the analyzer could not resolve (`unresolved_scopes`). The degraded path
(no usable verdict) still asks it of the whole text. No command here is ever executed: each is data.
"""
import io
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HOOKS_DIR, "lib"))

import bash_execution_boundary as eb  # noqa: E402

_argv, sys.argv = sys.argv, [sys.argv[0], HOOKS_DIR]
try:
    import bash_safety_rules as R  # noqa: E402
finally:
    sys.argv = _argv
R.HOOKS, R.LIB = HOOKS_DIR, os.path.join(HOOKS_DIR, "lib")


def _word_list():
    with open(os.path.join(HOOKS_DIR, "lib", "pol_degraded_removal_reference.ere"), encoding="utf-8") as fh:
        return re.compile(next(ln.strip() for ln in fh if ln.strip() and not ln.lstrip().startswith("#")))


WORDS = _word_list()


def policy(command, degraded=False):
    """removal_policy() alone, in this process: (refused, entry, stderr text)."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    saved, real = os.environ.get("CLAUDE_HOOK_BOUNDARY_TIMEOUT"), sys.stderr
    os.environ["CLAUDE_HOOK_BOUNDARY_TIMEOUT"] = "0.001s" if degraded else "120s"
    sys.stderr = err = io.StringIO()
    try:
        return False, R.removal_policy(payload, command), ""
    except SystemExit as exc:
        assert exc.code == 2, exc.code
        return True, None, err.getvalue()
    finally:
        sys.stderr = real
        os.environ.pop("CLAUDE_HOOK_BOUNDARY_TIMEOUT", None)
        if saved is not None:
            os.environ["CLAUDE_HOOK_BOUNDARY_TIMEOUT"] = saved


def seen(command):
    """The primary path's answer, read from the analyzer in this process."""
    v = eb.analyze(command)
    return v["verdict"] == "FORBIDDEN_REMOVAL" or v["verdict"] == "UNRESOLVED" and any(
        WORDS.search(t) for t in v.get("unresolved_scopes") or [])


# The four shapes of the 23 refusals of 2026-11-16..18 whose removal word was only text. Each command is
# unproven for another reason (a program name held in a variable, a grep option with a wildcard, a computed git
# subcommand, a sourced file), so before this rule its raw text decided and refused it.
TEXT_ONLY = {
    "a heredoc written to a file": "$TOOL --version; cat > notes.md <<'EOF'\nnever rm -rf the build tree\nEOF",
    "a grep pattern": "grep -rIn --include=*.ts -e unlink -e rmSync src",
    "a variable name": "python3 - <<'EOF'\nrm = {'rows': [1]}\nprint(len(rm['rows']))\nEOF",
    "a commit message": "S=status; git $S --short; git commit -m 'drop the rm call from the loader'",
    "an echo text": "for d in a b; do t=$d/x; echo \"rmdir $t\"; done",
    "a shell variable": "f=a; $TOOL \"$rm\" \"$f\"",
}


@pytest.mark.parametrize("shape", sorted(TEXT_ONLY))
def test_a_removal_word_that_is_only_text_does_not_refuse(shape):
    refused, entry, err = policy(TEXT_ONLY[shape])
    assert not refused, err


# R0833 (2026-11-18): a Python .unlink() in a heredoc fed to python through timeout, after a sourced venv. Before,
# python's standard input was not read (the wrapper dropped the redirection), so only the raw text refused it.
R0833_SHAPE = ("source venv/bin/activate; timeout 110 python - <<'PYEOF' 2>&1 | tail -5\n"
               "from pathlib import Path\nreal = Path('cfg/form.json')\nif real.exists(): real.unlink()\nPYEOF")
PYTHON_REMOVALS = [
    R0833_SHAPE,
    "timeout 5 python3 - <<'E'\nimport os\nos.remove('x')\nE",
    "cat <<'E' | python3\nimport shutil\nshutil.rmtree('build')\nE",
    "python3 -c 'import os; globals()[\"os\"].remove(\"x\")'",
    "python3 -c '__import__(\"os\").unlink(\"x\")'",
    "python3 -c 'import subprocess; subprocess.run([\"rm\", \"-rf\", \"build\"])'",
    "python3 -c 'import os; getattr(os, \"remove\")(\"x\")'",
]


@pytest.mark.parametrize("command", PYTHON_REMOVALS)
def test_a_removal_call_in_python_that_runs_is_refused_as_a_removal(command):
    refused, _entry, err = policy(command)
    assert refused and "FORBIDDEN_REMOVAL interpreter_removal_call" in err, err


PYTHON_NO_REMOVAL = [
    "python3 -c 'x = [1, 2]; x.remove(1); print(x)'",
    "python3 - <<'E'\nimport json\nprint(json.dumps({'note': 'rm -rf is refused'}))\nE",
    "python3 -c 'import shutil; shutil.rm_rf(\"X\")'",  # no such function: it raises and removes nothing
]


@pytest.mark.parametrize("command", PYTHON_NO_REMOVAL)
def test_python_read_with_ast_counts_calls_not_names_or_strings(command):
    assert eb.analyze(command)["verdict"] == "PROVEN_INERT"


# A computed program name is residue: the word list is asked of the words that can become it.
COMPUTED_REMOVALS = ["r${EMPTY}m qa-p # rm", "r${EMPTY}m qa-p", "x=rm; $x -r build", "printf -v C %s rm; \"$C\" f",
                     "$'\\x72m' -rf build", "printf '%s\\n' 'rm -rf build' | bash", "echo 'rm -rf /x' | at now"]


@pytest.mark.parametrize("command", COMPUTED_REMOVALS)
def test_a_removal_reached_through_computed_text_is_refused(command):
    assert seen(command), eb.analyze(command)


TRAILING_COMMENT = ["r${EMPTY}m qa-p", "$TOOL --version", "grep -rn x src", "rm -rf build", "ls -la",
                    "S=status; git $S --short", "python3 - <<'E'\nprint(1)\nE"]


@pytest.mark.parametrize("command", TRAILING_COMMENT)
def test_a_trailing_comment_does_not_change_the_verdict(command):
    for comment in (" # rm -rf x", "\n# rm -rf x"):
        if "\n" in command and comment[0] == " ":
            continue
        assert seen(command + comment) == seen(command), (command, comment)


# Strings the analyzer does not model that remove nothing: they run, and the policy hands the seam an entry.
NOT_MODELLED = {
    "php /bin/rm -rf qa-target": "php reads the file /bin/rm as a PHP script; nothing is removed",
    "docker /bin/rm -rf qa-target": "/bin/rm is no docker subcommand; docker exits with an error",
}


@pytest.mark.parametrize("command", sorted(NOT_MODELLED))
def test_an_unmodelled_string_that_removes_nothing_runs_and_is_recorded(command):
    refused, entry, err = policy(command)
    assert not refused, err
    assert entry and entry["path"] == "primary" and entry["reason"].startswith("UNRESOLVED"), entry


def test_the_degraded_path_still_reads_the_whole_text():
    refused, _entry, _err = policy(TEXT_ONLY["a commit message"], degraded=True)
    assert refused


def _heads_that_run_a_program():
    cases = {}
    for base, ent in sorted(eb.WRAPPERS.items()):
        if ent is not None:
            cases["wrapper " + base] = base + " " + "1 " * ent[1] + "rm -rf /x/y"
    for sh in sorted(eb.SHELLS):
        cases[sh + " -c"] = sh + " -c 'rm -rf /x/y'"
        cases[sh + " heredoc"] = sh + " <<'E'\nrm -rf /x/y\nE"
        cases[sh + " pipe"] = "printf '%s\\n' 'rm -rf /x/y' | " + sh
    for ip in sorted(eb.INTERPRETERS):
        code = "import os\nos.unlink('/x/y')" if ip.startswith("python") else "unlink('/x/y')"
        cases[ip + " heredoc"] = "%s - <<'E'\n%s\nE" % (ip, code)
    for c in ("command rm -rf /x/y", "eval 'rm -rf /x/y'", "busybox rm -rf /x/y", "flock /tmp/l rm -rf /x/y",
              "su -c 'rm -rf /x/y'", "runuser -u u -- rm -rf /x/y", "sg g -c 'rm -rf /x/y'",
              "script -qc 'rm -rf /x/y'", "start-stop-daemon --start --exec /bin/rm -- -rf /x/y",
              "machinectl shell m /bin/rm -rf /x/y", "bwrap --bind / / rm -rf /x/y", "ssh h rm -rf /x/y",
              "kubectl exec p -- rm -rf /x/y", "echo 'rm -rf /x/y' | at now", "watch rm -rf /x/y",
              "echo /x/y | xargs rm -rf", "parallel rm -rf ::: /x/y", "echo 'rm -rf /x' | parallel",
              "find /x -exec rm -rf {} +", "find /x -delete", "perf record rm -rf /x/y",
              "git -c alias.z='!rm -rf /x/y' z", "docker run i rm -rf /x/y", "sudo rm -rf /x/y",
              "exec rm -rf /x/y", "hash -p /bin/rm z; z -rf /x/y", "alias z='rm -rf /x/y'; z"):
        cases[c] = c
    return cases


def test_every_head_that_runs_a_program_sees_a_removal_behind_it():
    """The condition under which an undischarged removal_reference may refuse nothing by itself
    (lib/bash_active_syntax_census.py): every place a program can run from is a site of the walk."""
    missed = [name for name, c in _heads_that_run_a_program().items() if not seen(c)]
    assert not missed, missed
