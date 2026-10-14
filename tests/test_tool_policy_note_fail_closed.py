"""An exception inside the tool-policy refusal note never turns exit 2 into an allow.

hooks/pretool-tool-policy.py refuses a Bash write target with exit 2 and then
appends an explanatory note (_note_bash_write_target). Its __main__ block
catches any exception and exits 0 (fail open), so the note must swallow its own
failures. Three faults are injected, each only inside the note:

  dumps   json.dumps raises from the moment the refusal line has been written,
          so the note's own json.dumps calls raise inside its body.
  write   the note's own sys.stderr.write raises, after the refusal line was
          written without trouble.
  lookup  the note receives a tool_input that is not a dict, so reading the
          command from it raises. The real _extract_targets returns [None] for
          such an input, so it is patched to still yield the refused target.

dumps and write run the real hook, __main__ block included (runpy). lookup
needs the hook imported to patch it, so the driver reproduces the __main__
handler (any exception: report "unexpected", exit 0). The refusal must still
exit 2 with the refusal line intact, and nothing may reach the fail-open
handler. The driver counts the injected faults (for lookup: the note calls that
received the non-dict input) and no note line may appear, so a note that no
longer reaches the fault cannot pass vacuously, and a control run without a
fault shows the note is emitted on the same path.

Both refusal sites are covered: the prefix layer (a target outside the role's
write prefixes) and the scratch actor-exactness gate (another dispatch's
scratch directory).

Restores the fail-closed cases (a), (b) and (c) of
tests/test_tool_policy_inference_note.py, removed in P0 because it needed a
gitignored baseline copy of the hook. Standard library and pytest only; the
hook process gets a pytest temporary HOME.
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
FAULTS = ("dumps", "write", "lookup")

# site -> (command, refused target, deny_reason fragment)
REFUSALS = {
    "prefix": ("cp src /srv/data/out", "/srv/data/out",
               "not in allowed_write_path_prefixes"),
    # a qa dispatch other than this one ("D", not the payload's agent_id)
    "scratch": ("cp src .claude/scratch/S/qa/D/file", ".claude/scratch/S/qa/D/file",
                "sibling scratch target denied"),
}

# argv: hook path, mode (control or one of FAULTS), refused target (lookup only)
_DRIVER = r'''
import importlib.util, json, runpy, sys

hook, mode = sys.argv[1], sys.argv[2]
real_dumps, real_stderr = json.dumps, sys.stderr
state = {"armed": False, "raised": 0}


def dumps(*args, **kwargs):
    if state["armed"]:
        state["raised"] += 1
        raise RuntimeError("injected json.dumps failure")
    return real_dumps(*args, **kwargs)


class Stderr:
    """dumps: arms the fault once the refusal line itself has been written.
    write: the note's own write raises."""

    def write(self, text):
        if mode == "write" and text.startswith("tool-policy.v1 note: "):
            state["raised"] += 1
            raise RuntimeError("injected note write failure")
        written = real_stderr.write(text)
        if mode == "dumps" and text.startswith("BLOCKED by tool-policy.v1: "):
            state["armed"] = True
        return written

    def __getattr__(self, name):
        return getattr(real_stderr, name)


def run_lookup(target):
    spec = importlib.util.spec_from_file_location("tool_policy_under_fault", hook)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    real_note = module._note_bash_write_target

    def note(data, refused):
        state["raised"] += not isinstance(data.get("tool_input"), dict)
        return real_note(data, refused)

    module._extract_targets = lambda tool_name, tool_input: [None, target]
    module._note_bash_write_target = note
    try:
        module.main()
    except Exception as e:  # the hook's __main__ handler: fail open
        sys.stderr.write("pretool-tool-policy: unexpected (%s)\n" % (e,))
        sys.exit(0)


json.dumps = dumps
sys.stderr = Stderr()
try:
    if mode == "lookup":
        run_lookup(sys.argv[3])
    else:
        runpy.run_path(hook, run_name="__main__")
finally:
    sys.stdout.write("faults=%d\n" % state["raised"])
'''


def _run_hook(tmp_path: Path, site: str, mode: str):
    command, target, _reason = REFUSALS[site]
    tool_input = "not-a-dict" if mode == "lookup" else {"command": command}
    payload = {"tool_name": "Bash", "tool_input": tool_input,
               "subagent_type": ROLE, "agent_id": "a" + ROLE + "probe",
               "session_id": "note-fail-closed-sess"}
    env = {**os.environ, "HOME": str(tmp_path)}
    env.pop("CLAUDE_PROJECT_DIR", None)
    proc = subprocess.run(
        [sys.executable, "-B", "-c", _DRIVER, str(HOOK), mode, target],
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
    proc, faults = _run_hook(tmp_path, site, "control")
    assert proc.returncode == 2, proc.stderr
    _assert_refusal_line(proc.stderr, site)
    assert proc.stderr.split("\n")[1].startswith(NOTE_PREFIX), proc.stderr
    assert faults == 0


@pytest.mark.parametrize("fault", FAULTS)
@pytest.mark.parametrize("site", sorted(REFUSALS))
def test_exception_inside_the_note_keeps_exit_2(tmp_path, site, fault):
    proc, faults = _run_hook(tmp_path, site, fault)
    assert faults >= 1, f"the injected fault never fired inside the note\n{proc.stderr}"
    assert proc.returncode == 2, (
        f"refusal became exit {proc.returncode} (fail open)\n{proc.stderr}")
    _assert_refusal_line(proc.stderr, site)
    assert NOTE_PREFIX not in proc.stderr, proc.stderr
    assert "pretool-tool-policy: unexpected" not in proc.stderr, proc.stderr
    assert "Traceback" not in proc.stderr, proc.stderr
