"""A container run or create that replaces the image's entry program is read as what it runs.

`--entrypoint` (a separate word or `=`-joined, on `run` and `create`) names the program the container runs, and the
words after the image become that program's arguments. The reading judges that command as any other it resolves: a
removal, a shell with a command string, an interpreter with inline code. A value it cannot resolve is unproven, not
inert. An empty value restores the image's own entry program, and a command without the option keeps its verdict.
The commands below are data; none is executed.
"""
import io
import json
import os
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


def refused(command):
    """removal_policy() alone, in this process: whether it exits 2."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    saved, real = os.environ.get("CLAUDE_HOOK_BOUNDARY_TIMEOUT"), sys.stderr
    os.environ["CLAUDE_HOOK_BOUNDARY_TIMEOUT"] = "120s"
    sys.stderr = io.StringIO()
    try:
        R.removal_policy(payload, command)
        return False
    except SystemExit as exc:
        assert exc.code == 2, exc.code
        return True
    finally:
        sys.stderr = real
        os.environ.pop("CLAUDE_HOOK_BOUNDARY_TIMEOUT", None)
        if saved is not None:
            os.environ["CLAUDE_HOOK_BOUNDARY_TIMEOUT"] = saved


FORMS = [("run", "--entrypoint {}"), ("run", "--entrypoint={}"), ("create", "--entrypoint {}"),
         ("create", "--entrypoint={}")]
PAYLOADS = {
    "a removal": ("rm", "-rf /host"),
    "a shell with a command string": ("sh", "-c 'rm -rf /host'"),
    "an interpreter with inline code": ("python3", "-c 'import shutil; shutil.rmtree(\"/host\")'"),
}


@pytest.mark.parametrize("sub, option", FORMS)
@pytest.mark.parametrize("what", sorted(PAYLOADS))
def test_the_entry_program_and_the_trailing_words_are_judged_as_its_command(sub, option, what):
    program, rest = PAYLOADS[what]
    command = "docker %s -v /:/host %s img %s" % (sub, option.format(program), rest)
    assert eb.analyze(command)["verdict"] == eb.FORBIDDEN_REMOVAL, command
    assert refused(command), command


@pytest.mark.parametrize("sub, option", FORMS)
def test_an_entry_program_the_reading_cannot_resolve_is_unproven(sub, option):
    command = 'docker %s %s img -rf /host' % (sub, option.format('"$X"'))
    assert eb.analyze(command)["verdict"] == eb.UNRESOLVED, command


@pytest.mark.parametrize("command", [
    "docker run --rm --entrypoint ls img -la",       # a harmless entry program stays inert
    "docker run --rm --entrypoint= img ls -la",      # an empty value: the image's own, the payload as the command
    "docker run --name --entrypoint img ls -la",     # `--entrypoint` here is the name's value
    "docker run --rm img ls -la",                    # no option: verdicts unchanged
    "podman create --entrypoint=/bin/true img",
    "docker create --",                              # a reading with no image word left: nothing runs
    "docker run --rm",
])
def test_a_harmless_or_absent_entry_program_stays_inert(command):
    assert eb.analyze(command)["verdict"] == eb.PROVEN_INERT, command
    assert not refused(command), command


def test_without_the_option_a_removal_in_the_payload_is_judged_as_before():
    assert eb.analyze("docker run --rm img rm -rf /x")["verdict"] == eb.FORBIDDEN_REMOVAL
