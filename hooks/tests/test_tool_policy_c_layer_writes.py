"""T2-16: tool-policy reads the writes inside a shell's -c string as it reads the command run plainly.

hooks/pretool-tool-policy.py judges a Bash command's write targets (the protected stage for every
caller, the role rows for a subagent). Its readers blank quoted text, so a write inside a `-c`
string named no target: `bash -c "cp x <protected>"` exited 0 where `cp x <protected>` exits 2.
The layers are now read through lib/git_command_classifier's walker, each as the command run
plainly. Every case below runs the real hook file for the main agent and for a dev subagent, and
the layer form exits as its plain form does. A run-time value inside a layer is an unresolvable
target, decided as the plain command's `$X` is (no stage refuses it by itself); `$HOME` and a
`T=<path>;` assignment before the shell reach a double-quoted string, as the outer shell expands
it, and not a single-quoted one (the inner shell's `$T` is its own, unset).

The harness home is this checkout (the hook resolves it from its own location); only paths are
judged, nothing is written. hooks/tests/test_c_layer_protected_targets.py holds the full sweep.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
HOOK = os.path.join(ROOT, "hooks", "pretool-tool-policy.py")
SID = "5a6b7c8d-9e0f-4a1b-8c2d-3e4f5a6b7c8d"
CALLERS = {"main": None, "dev": ("a0dev", "dev")}
# A product repository outside /tmp and /var/tmp (the scratch rule denies every role there), never created.
PRODUCT = "/nonexistent-t2-16-c-layer/product"
PRE_COMMIT = os.path.join(ROOT, "hooks", "git-hooks", "pre-commit")
GIT_HOOK = os.path.join(ROOT, ".git", "hooks", "pre-commit")
MACHINE = os.path.join(ROOT, "settings.machine.json")
REFUSED, ALLOWED = {"main": 2, "dev": 2}, {"main": 0, "dev": 0}
DEV_ONLY = {"main": 0, "dev": 2}  # the dev role's rows: raw /tmp is denied to every role ($HOME is in tmp_path)

# (name, plain form, layer form, exit per caller)
CASES = [
    ("double-quoted protected cp", f"cp notes.txt {PRE_COMMIT}", f'bash -c "cp notes.txt {PRE_COMMIT}"', REFUSED),
    ("single-quoted protected rm", f"rm -f {GIT_HOOK}", f"bash -c 'rm -f {GIT_HOOK}'", REFUSED),
    ("a layer in a layer", f"echo x > {MACHINE}", f"sh -c \"bash -c 'echo x > {MACHINE}'\"", REFUSED),
    ("a login shell's option cluster", f"truncate -s 0 {MACHINE}", f'zsh -lc "truncate -s 0 {MACHINE}"', REFUSED),
    ("a run-time operand beside the target", f"cp $S {PRE_COMMIT}", f'bash -c "cp $S {PRE_COMMIT}"', REFUSED),
    ("a run-time option before -c", f"rm -f {GIT_HOOK}", f'bash $OPT -c "rm -f {GIT_HOOK}"', REFUSED),
    ("an assignment the outer shell expands (TC-47)", f"T={PRE_COMMIT}; echo x | tee $T",
     f'T={PRE_COMMIT}; bash -c "echo x | tee $T"', REFUSED),
    ("$HOME in a double-quoted string", "cp notes.txt $HOME/out.txt", 'bash -c "cp notes.txt $HOME/out.txt"', DEV_ONLY),
    ("$HOME in a single-quoted string", "cp notes.txt $HOME/out.txt", "bash -c 'cp notes.txt $HOME/out.txt'", DEV_ONLY),
    ("a raw temp redirect", "echo x > /tmp/t2-16-out", 'bash -c "echo x > /tmp/t2-16-out"', DEV_ONLY),
    ("run-time words only", "mv $A $B", 'bash -c "mv $A $B"', ALLOWED),
    ("a run-time target", f"cp notes.txt $T", 'bash -c "cp notes.txt $T"', ALLOWED),
    ("no write", "cat notes.txt | wc -l", 'bash -c "cat notes.txt | wc -l"', ALLOWED),
    ("a write in the product", "echo x > out.txt", 'bash -c "echo x > out.txt"', ALLOWED),
    ("quoted text is no write", "echo 'a > b'", "bash -c \"echo 'a > b'\"", ALLOWED),
]


def run(tmp_path, command: str, caller):
    home = tmp_path / "home"
    payload = {"session_id": SID, "transcript_path": str(home / ".claude" / "projects" / "-p" / f"{SID}.jsonl"),
               "cwd": PRODUCT, "hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": command}}
    if caller:
        payload.update(agent_id=caller[0], agent_type=caller[1], subagent_type=caller[1])
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_PROJECT_DIR=PRODUCT,
               CLAUDE_STATE_DIR=str(tmp_path / "state"), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True,
                          cwd=str(tmp_path), env=env, timeout=60)


@pytest.mark.parametrize("caller", list(CALLERS))
@pytest.mark.parametrize("name,plain,layer,expected", CASES, ids=[c[0] for c in CASES])
def test_a_layer_exits_as_its_plain_command(tmp_path, name, plain, layer, expected, caller):
    top, lay = run(tmp_path, plain, CALLERS[caller]), run(tmp_path, layer, CALLERS[caller])
    assert (top.returncode, lay.returncode) == (expected[caller],) * 2, (plain, top.stderr, layer, lay.stderr)
    if expected[caller] == 2:
        assert lay.stderr.startswith("BLOCKED by tool-policy.v1: "), lay.stderr


@pytest.mark.parametrize("caller", list(CALLERS))
def test_a_single_quoted_string_is_not_reached_by_the_outer_assignment(tmp_path, caller):
    # The outer shell neither expands a single-quoted string nor passes it the unexported T: the
    # inner `tee $T` names no file, so nothing protected is written.
    proc = run(tmp_path, f"T={PRE_COMMIT}; bash -c 'echo x | tee $T'", CALLERS[caller])
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("caller", list(CALLERS))
def test_the_refusal_names_the_protected_file_a_layer_writes(tmp_path, caller):
    proc = run(tmp_path, f'bash -c "cp notes.txt {PRE_COMMIT}"', CALLERS[caller])
    reason = json.loads(proc.stderr.splitlines()[0].split(": ", 1)[1])["deny_reason"]
    assert reason == (f"{PRE_COMMIT} is the harness home's hooks/git-hooks/pre-commit: "
                      "no agent writes, deletes or renames it (D11/D12)"), reason


def test_the_layers_read_are_the_walkers_and_the_command_stays_first():
    sys.path.insert(0, os.path.join(ROOT, "hooks"))
    import importlib.util

    spec = importlib.util.spec_from_file_location("tool_policy_t2_16", HOOK)
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    command = 'T=/p/out; bash -c "echo x | tee $T"'
    texts = policy._bash_texts(command)
    assert texts[0] == command
    assert "echo x | tee ${__runtime__}" in texts  # the walker's own text: a run-time value
    assert "T=/p/out; bash -c \necho x | tee $T\n" in texts  # read in its place: the assignment reaches it
    assert policy._bash_texts("git status") == ("git status",)
