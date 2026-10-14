"""An exception inside the tool-policy refusal note never turns exit 2 into an allow.

hooks/pretool-tool-policy.py refuses a Bash write target with exit 2 and then
appends an explanatory note (_note_bash_write_target). Its __main__ block
catches any exception and exits 0 (fail open), so the note must swallow its own
failures. The real hook runs here, __main__ block included (runpy), with
json.dumps made to raise from the moment the refusal line has been written:
the note's own json.dumps calls then raise inside its body. The refusal must
still exit 2 with the refusal line intact. The driver counts the injected
failures, so a note that no longer reaches json.dumps cannot pass vacuously,
and a control run without the fault shows the note is emitted on the same path.

Both refusal sites are covered: the prefix layer (a target outside the role's
write prefixes) and the scratch actor-exactness gate (another dispatch's
scratch directory).

Restores the fail-closed case of tests/test_tool_policy_inference_note.py,
removed in P0 because it needed a gitignored baseline copy of the hook. Standard
library and pytest only; the hook process gets a pytest temporary HOME.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "pretool-tool-policy.py"
ROLE = "qa"
BLOCK_PREFIX = "BLOCKED by tool-policy.v1: "
NOTE_PREFIX = "tool-policy.v1 note: "

# site -> (command, refused target, deny_reason fragment)
REFUSALS = {
    "prefix": ("cp src /srv/data/out", "/srv/data/out",
               "not in allowed_write_path_prefixes"),
    # a qa dispatch other than this one ("D", not the payload's agent_id)
    "scratch": ("cp src .claude/scratch/S/qa/D/file", ".claude/scratch/S/qa/D/file",
                "sibling scratch target denied"),
}

_DRIVER = r'''
import json, runpy, sys

hook, inject = sys.argv[1], sys.argv[2] == "fault"
real_dumps, real_stderr = json.dumps, sys.stderr
state = {"armed": False, "raised": 0}


def dumps(*args, **kwargs):
    if state["armed"]:
        state["raised"] += 1
        raise RuntimeError("injected json.dumps failure")
    return real_dumps(*args, **kwargs)


class Stderr:
    """Arms the fault once the refusal line itself has been written."""

    def write(self, text):
        written = real_stderr.write(text)
        if inject and text.startswith("BLOCKED by tool-policy.v1: "):
            state["armed"] = True
        return written

    def __getattr__(self, name):
        return getattr(real_stderr, name)


json.dumps = dumps
sys.stderr = Stderr()
try:
    runpy.run_path(hook, run_name="__main__")
finally:
    sys.stdout.write("faults=%d\n" % state["raised"])
'''


def _run_hook(tmp_path: Path, command: str, inject: bool):
    payload = {"tool_name": "Bash", "tool_input": {"command": command},
               "subagent_type": ROLE, "agent_id": "a" + ROLE + "probe",
               "session_id": "note-fail-closed-sess"}
    env = {**os.environ, "HOME": str(tmp_path)}
    env.pop("CLAUDE_PROJECT_DIR", None)
    proc = subprocess.run(
        [sys.executable, "-B", "-c", _DRIVER, str(HOOK), "fault" if inject else "control"],
        input=json.dumps(payload), capture_output=True, text=True,
        cwd=str(ROOT), env=env, timeout=90)
    match = re.search(r"^faults=(\d+)$", proc.stdout, re.MULTILINE)
    assert match, f"driver did not finish\n{proc.stdout}\n{proc.stderr}"
    return proc, int(match.group(1))


def _assert_refusal_line(stderr: str, site: str) -> None:
    _command, target, reason = REFUSALS[site]
    first = stderr.split("\n")[0]
    assert first.startswith(BLOCK_PREFIX), stderr
    block = json.loads(first[len(BLOCK_PREFIX):])
    assert block["role"] == ROLE and block["tool"] == "Write", block
    assert block["target"] == target and reason in block["deny_reason"], block


@pytest.mark.parametrize("site", sorted(REFUSALS))
def test_note_follows_the_refusal_without_a_fault(tmp_path, site):
    proc, faults = _run_hook(tmp_path, REFUSALS[site][0], inject=False)
    assert proc.returncode == 2, proc.stderr
    _assert_refusal_line(proc.stderr, site)
    assert proc.stderr.split("\n")[1].startswith(NOTE_PREFIX), proc.stderr
    assert faults == 0


@pytest.mark.parametrize("site", sorted(REFUSALS))
def test_exception_inside_the_note_keeps_exit_2(tmp_path, site):
    proc, faults = _run_hook(tmp_path, REFUSALS[site][0], inject=True)
    assert faults >= 1, f"the injected fault never fired inside the note\n{proc.stderr}"
    assert proc.returncode == 2, (
        f"refusal became exit {proc.returncode} (fail open)\n{proc.stderr}")
    _assert_refusal_line(proc.stderr, site)
    assert NOTE_PREFIX not in proc.stderr, proc.stderr
    assert "pretool-tool-policy: unexpected" not in proc.stderr, proc.stderr
    assert "Traceback" not in proc.stderr, proc.stderr
